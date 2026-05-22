"""Default :class:`IAIService` implementation, registered as a global utility."""

from collective.ai import logger
from collective.ai.client import chat_completion
from collective.ai.client import chat_completion_message
from collective.ai.client import embeddings
from collective.ai.interfaces import IAIService
from collective.ai.permissions import entry_permits
from collective.ai.utils import resolve_model
from plone import api
from zope.interface import implementer


# REST/API capability name → registry-vocabulary token used to resolve a
# matching model entry. Keeping the mapping here so both the facade methods
# and the async REST endpoint share the same understanding of what e.g.
# "chat" means in terms of model selection.
CAPABILITY_TOKEN = {
    "chat": "completion",
    "think": "thinking",
    "vision": "vision",
    "embed": "embedding",
    "tools": "tools",
}


def _build_messages(prompt, system=None):
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if isinstance(prompt, str):
        messages.append({"role": "user", "content": prompt})
    elif prompt:
        messages.extend(prompt)
    return messages


@implementer(IAIService)
class AIService:
    """Resolve the configured model and dispatch the call to :mod:`client`."""

    # ---- low-level methods (shared with the async REST endpoint) ----

    def resolve_for(self, capability: str, model_override: str | None):
        """Return a model entry for ``capability`` (or None). Request-thread
        only — reads the plone registry."""
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

    def run_call(self, capability: str, entry: dict, data: dict) -> dict:
        """Run the actual outbound HTTP call. Worker-thread safe.

        The permission gate (if any) must have already been checked by the
        caller before invoking ``run_call``.
        """
        url = entry["url"]
        api_key = entry.get("api_key") or None
        model_name = entry["model"]

        if capability == "chat":
            text = chat_completion(
                url,
                api_key,
                model_name,
                _build_messages(data.get("prompt"), data.get("system")),
                think=False,
            )
            return {"response": text}

        if capability == "think":
            text = chat_completion(
                url,
                api_key,
                model_name,
                _build_messages(data.get("prompt"), data.get("system")),
            )
            return {"response": text}

        if capability == "vision":
            content = [
                {"type": "text", "text": data.get("prompt") or ""},
                {"type": "image_url", "image_url": {"url": data.get("image")}},
            ]
            text = chat_completion(
                url,
                api_key,
                model_name,
                [{"role": "user", "content": content}],
                think=False,
            )
            return {"response": text}

        if capability == "embed":
            text = data.get("input")
            if text is None:
                text = data.get("text") or ""
            single = isinstance(text, str)
            inputs = [text] if single else list(text)
            vectors = embeddings(url, api_key, model_name, inputs)
            if vectors is None:
                return {"embedding": None}
            if single:
                return {"embedding": vectors[0] if vectors else None}
            return {"embedding": vectors}

        if capability == "tools":
            message = chat_completion_message(
                url,
                api_key,
                model_name,
                data.get("messages") or [],
                tools=data.get("tools") or [],
                think=False,
            )
            return {"response": message}

        raise ValueError(f"unknown capability {capability!r}")

    # ---- high-level facade (request-thread, resolve + permit + run) ----

    def _call(
        self,
        capability: str,
        model_override: str | None,
        data: dict,
        context=None,
        result_key: str = "response",
    ):
        entry = self.resolve_for(capability, model_override)
        if entry is None:
            return None
        gate_ctx = context if context is not None else api.portal.get()
        if not entry_permits(entry, gate_ctx):
            logger.info(
                "AI call for capability %r denied by permission gate on context %r.",
                capability,
                getattr(gate_ctx, "absolute_url", lambda: gate_ctx)(),
            )
            return None
        return self.run_call(capability, entry, data).get(result_key)

    def chat(self, prompt, model=None, system=None, context=None):
        return self._call(
            "chat",
            model,
            {"prompt": prompt, "system": system},
            context=context,
        )

    def think(self, prompt, model=None, system=None, context=None):
        return self._call(
            "think",
            model,
            {"prompt": prompt, "system": system},
            context=context,
        )

    def analyze_image(self, prompt, image, model=None, context=None):
        return self._call(
            "vision",
            model,
            {"prompt": prompt, "image": image},
            context=context,
        )

    def embed(self, text, model=None, context=None):
        return self._call(
            "embed",
            model,
            {"input": text},
            context=context,
            result_key="embedding",
        )

    def tool_call(self, messages, tools, model=None, context=None):
        return self._call(
            "tools",
            model,
            {"messages": messages, "tools": tools},
            context=context,
        )
