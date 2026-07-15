"""Default :class:`IAIService` implementation, registered as a global utility.

Chat/think/vision go through `pydantic-ai <https://ai.pydantic.dev>`_ agents
(:meth:`AIService.run`), which can auto-execute tools registered through the
component architecture (see :mod:`collective.aisettings.tools`). Embeddings and
the raw function-calling passthrough use the OpenAI SDK directly
(:mod:`collective.aisettings.client`).
"""

from AccessControl import getSecurityManager
from collective.aisettings import logger
from collective.aisettings.client import embeddings as _embeddings
from collective.aisettings.client import raw_tool_call
from collective.aisettings.deps import AIDeps
from collective.aisettings.interfaces import IAIService
from collective.aisettings.models import build_model
from collective.aisettings.permissions import entry_permits
from collective.aisettings.tools import collect_tools
from collective.aisettings.utils import resolve_model
from plone import api
from pydantic_ai import Agent
from pydantic_ai import BinaryContent
from pydantic_ai import ImageUrl
from zope.interface import implementer

import base64
import binascii


# REST/API capability name → registry-vocabulary token used to resolve a
# matching model entry. Shared by the facade methods and the REST endpoint.
CAPABILITY_TOKEN = {
    "chat": "completion",
    "think": "thinking",
    "vision": "vision",
    "embed": "embedding",
    "tools": "tools",
}


def _image_content(prompt, image):
    """Build a pydantic-ai multimodal user prompt from text + an image.

    ``image`` may be an ``http(s)`` URL or an inline ``data:`` URI.
    """
    parts: list = []
    if prompt:
        parts.append(prompt)
    if not image:
        return parts
    if isinstance(image, str) and image.startswith("data:"):
        try:
            header, encoded = image.split(",", 1)
            media_type = header[5:].split(";")[0] or "image/png"
            parts.append(
                BinaryContent(data=base64.b64decode(encoded), media_type=media_type)
            )
        except (ValueError, binascii.Error):
            logger.warning("Could not decode inline image data URI; ignoring.")
    else:
        parts.append(ImageUrl(url=image))
    return parts


@implementer(IAIService)
class AIService:
    """Resolve the configured model and dispatch the call to pydantic-ai."""

    # ---- model resolution (request thread; reads the registry) ----

    def resolve_for(self, capability: str, model_override: str | None):
        token = CAPABILITY_TOKEN.get(capability)
        if token is None:
            return None
        entry = resolve_model(token, model_override)
        if entry is None:
            logger.info(
                "No AI model configured for capability %r; call skipped.",
                capability,
            )
        return entry

    def _gate_context(self, context):
        return context if context is not None else api.portal.get()

    def _build_agent(self, entry, *, system=None, output_type=None, tools=None):
        model = build_model(entry)
        kwargs = {"deps_type": AIDeps, "tools": tools or []}
        if system:
            kwargs["system_prompt"] = system
        if output_type is not None:
            kwargs["output_type"] = output_type
        return Agent(model, **kwargs)

    # ---- high-level agentic facade (request thread) ----

    def run(
        self,
        prompt,
        capability="chat",
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
        message_history=None,
    ):
        entry = self.resolve_for(capability, model)
        if entry is None:
            return None
        gate_ctx = self._gate_context(context)
        if not entry_permits(entry, gate_ctx):
            logger.info(
                "AI call for capability %r denied by permission gate on %r.",
                capability,
                getattr(gate_ctx, "absolute_url", lambda: gate_ctx)(),
            )
            return None
        tools = collect_tools(gate_ctx, capability) if use_tools else []
        deps = AIDeps(
            context=gate_ctx,
            request=request,
            security_manager=getSecurityManager(),
        )
        agent = self._build_agent(
            entry, system=system, output_type=output_type, tools=tools
        )
        result = agent.run_sync(prompt, deps=deps, message_history=message_history)
        return result.output

    def chat(
        self,
        prompt,
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        return self.run(
            prompt,
            capability="chat",
            model=model,
            system=system,
            context=context,
            request=request,
            output_type=output_type,
            use_tools=use_tools,
        )

    def think(
        self,
        prompt,
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        return self.run(
            prompt,
            capability="think",
            model=model,
            system=system,
            context=context,
            request=request,
            output_type=output_type,
            use_tools=use_tools,
        )

    def analyze_image(
        self,
        prompt,
        image,
        model=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        return self.run(
            _image_content(prompt, image),
            capability="vision",
            model=model,
            context=context,
            request=request,
            output_type=output_type,
            use_tools=use_tools,
        )

    # ---- embeddings + raw tool passthrough (OpenAI SDK) ----

    def _embed(self, entry, text):
        single = isinstance(text, str)
        inputs = [text] if single else list(text)
        vectors = _embeddings(
            entry["url"], entry.get("api_key") or None, entry["model"], inputs
        )
        if vectors is None:
            return None
        if single:
            return vectors[0] if vectors else None
        return vectors

    def embed(self, text, model=None, context=None):
        entry = self.resolve_for("embed", model)
        if entry is None:
            return None
        gate_ctx = self._gate_context(context)
        if not entry_permits(entry, gate_ctx):
            return None
        return self._embed(entry, text)

    def tool_call(self, messages, tools, model=None, context=None):
        entry = self.resolve_for("tools", model)
        if entry is None:
            return None
        gate_ctx = self._gate_context(context)
        if not entry_permits(entry, gate_ctx):
            return None
        return raw_tool_call(
            entry["url"], entry.get("api_key") or None, entry["model"], messages, tools
        )

    # ---- worker-safe, tool-less call (used by the async REST endpoint) ----

    def _prompt_for(self, capability, data):
        if capability == "vision":
            return _image_content(data.get("prompt") or "", data.get("image"))
        return data.get("prompt") or ""

    def run_call(self, capability: str, entry: dict, data: dict) -> dict:
        """Run a tool-less AI call against a pre-resolved ``entry``.

        Outbound HTTP only; touches no Zope state and executes no registered
        tools — safe on a worker thread.
        """
        if capability == "embed":
            text = data.get("input")
            if text is None:
                text = data.get("text") or ""
            return {"embedding": self._embed(entry, text)}

        if capability == "tools":
            message = raw_tool_call(
                entry["url"],
                entry.get("api_key") or None,
                entry["model"],
                data.get("messages") or [],
                data.get("tools") or [],
            )
            return {"response": message}

        agent = self._build_agent(entry, system=data.get("system"), tools=[])
        result = agent.run_sync(self._prompt_for(capability, data), deps=AIDeps())
        return {"response": result.output}
