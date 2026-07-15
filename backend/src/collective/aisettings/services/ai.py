"""REST proxy for :class:`IAIService`.

By default the endpoint runs the AI call **synchronously** in the request
thread and returns the result in the response body. Chat/think/vision run as
pydantic-ai agents and may auto-execute tools registered by other add-ons (see
:mod:`collective.aisettings.tools`); pass ``"use_tools": false`` to disable.

For long-running calls that risk exceeding HTTP timeouts, callers can pass
``"async": true``. In that mode the endpoint enqueues the call onto a worker
thread, returns a task id with HTTP 202, and the client polls
``GET @ai-task/<task_id>``. Because tools run inside the agent loop and need
Plone security/the ZODB, **async runs are tool-less** — an async chat/think/
vision call with tools enabled is rejected.

URL: ``POST /++api++/@ai`` with body::

    {
      "capability": "chat" | "think" | "vision" | "embed" | "tools",
      "model": "...",          // optional override
      "async": false,          // optional; true → background thread + task_id
      "use_tools": true,       // optional (chat/think/vision); run registered tools
      "output_schema": {...},  // optional (chat/think/vision); JSON Schema output
      // capability-specific fields:
      //   chat/think  → prompt (required), system
      //   vision      → prompt (required), image (required)
      //   embed       → input | text (required)
      //   tools       → messages, tools (both required)
    }
"""

from collective.aisettings import logger
from collective.aisettings.interfaces import IAIService
from collective.aisettings.models import model_from_json_schema
from collective.aisettings.permissions import entry_permits
from collective.aisettings.services.tasks import complete_task
from collective.aisettings.services.tasks import create_task
from collective.aisettings.services.tasks import fail_task
from plone.restapi.deserializer import json_body
from plone.restapi.services import Service
from pydantic import BaseModel
from threading import Thread
from zope.component import queryUtility


SUPPORTED_CAPABILITIES = ("chat", "think", "vision", "embed", "tools")
AGENTIC_CAPABILITIES = ("chat", "think", "vision")


def _validate(capability: str, data: dict) -> str | None:
    if capability in ("chat", "think") and not data.get("prompt"):
        return "prompt is required"
    if capability == "vision" and (not data.get("prompt") or not data.get("image")):
        return "prompt and image are required"
    if capability == "embed" and not (data.get("input") or data.get("text")):
        return "input is required"
    if capability == "tools" and (not data.get("messages") or not data.get("tools")):
        return "messages and tools are required"
    return None


def _serialize(output):
    """Make an agent output JSON-serialisable (structured outputs are pydantic
    models)."""
    if isinstance(output, BaseModel):
        return output.model_dump()
    return output


def _worker(service, task_id, capability, entry, data):
    """Worker-thread body. Touches no Zope state — uses only the utility's
    tool-less, HTTP-only ``run_call`` against a pre-resolved entry."""
    try:
        result = service.run_call(capability, entry, data)
        complete_task(task_id, result)
    except Exception as exc:
        logger.exception("AI task %s failed", task_id)
        fail_task(task_id, str(exc))


class AIServiceEndpoint(Service):
    """``POST /++api++/@ai`` — run an AI call."""

    def reply(self):
        data = json_body(self.request)
        capability = (data.get("capability") or "").strip()
        if not capability:
            self.request.response.setStatus(400)
            return {"error": "capability is required"}
        if capability not in SUPPORTED_CAPABILITIES:
            self.request.response.setStatus(404)
            return {"error": f"unknown capability {capability!r}"}

        validation_error = _validate(capability, data)
        if validation_error:
            self.request.response.setStatus(400)
            return {"error": validation_error}

        service = queryUtility(IAIService)
        if service is None:
            self.request.response.setStatus(503)
            return {"error": "AI service utility not registered"}

        agentic = capability in AGENTIC_CAPABILITIES
        use_tools = bool(data.get("use_tools", True)) if agentic else False

        if data.get("async"):
            return self._reply_async(service, capability, data, agentic, use_tools)
        if agentic:
            return self._reply_agentic(service, capability, data, use_tools)
        return self._reply_raw(service, capability, data)

    # -- async (tool-less worker thread) --

    def _reply_async(self, service, capability, data, agentic, use_tools):
        if agentic and use_tools:
            self.request.response.setStatus(400)
            return {
                "error": (
                    "asynchronous runs cannot execute server-side tools; "
                    "set use_tools=false or run synchronously"
                )
            }
        entry = service.resolve_for(capability, data.get("model") or None)
        if entry is None:
            self.request.response.setStatus(503)
            return {"error": f"no AI model configured for capability {capability!r}"}
        if not entry_permits(entry, self.context):
            self.request.response.setStatus(403)
            return {"error": "permission denied for AI model"}
        task_id = create_task()
        Thread(
            target=_worker,
            args=(service, task_id, capability, dict(entry), dict(data)),
            daemon=True,
            name=f"ai-task-{task_id[:8]}",
        ).start()
        self.request.response.setStatus(202)
        return {"task_id": task_id, "status": "running"}

    # -- sync agentic (pydantic-ai, may run tools) --

    def _reply_agentic(self, service, capability, data, use_tools):
        # Resolve + gate here so we can return precise status codes; service.run
        # re-checks but that is cheap (a registry read).
        entry = service.resolve_for(capability, data.get("model") or None)
        if entry is None:
            self.request.response.setStatus(503)
            return {"error": f"no AI model configured for capability {capability!r}"}
        if not entry_permits(entry, self.context):
            self.request.response.setStatus(403)
            return {"error": "permission denied for AI model"}

        output_type = None
        schema = data.get("output_schema")
        if schema:
            output_type = model_from_json_schema(schema)
            if output_type is None:
                self.request.response.setStatus(400)
                return {"error": "output_schema must be a JSON object schema"}

        common = {
            "model": data.get("model") or None,
            "context": self.context,
            "request": self.request,
            "output_type": output_type,
            "use_tools": use_tools,
        }
        try:
            if capability == "vision":
                output = service.analyze_image(
                    data.get("prompt"), data.get("image"), **common
                )
            else:
                output = service.run(
                    data.get("prompt"),
                    capability=capability,
                    system=data.get("system"),
                    **common,
                )
        except Exception as exc:
            logger.exception("AI call failed")
            self.request.response.setStatus(502)
            return {"status": "error", "error": str(exc)}
        return {"status": "done", "result": {"response": _serialize(output)}}

    # -- sync raw (embed / tools passthrough) --

    def _reply_raw(self, service, capability, data):
        entry = service.resolve_for(capability, data.get("model") or None)
        if entry is None:
            self.request.response.setStatus(503)
            return {"error": f"no AI model configured for capability {capability!r}"}
        if not entry_permits(entry, self.context):
            self.request.response.setStatus(403)
            return {"error": "permission denied for AI model"}
        try:
            result = service.run_call(capability, dict(entry), dict(data))
        except Exception as exc:
            logger.exception("AI call failed")
            self.request.response.setStatus(502)
            return {"status": "error", "error": str(exc)}
        return {"status": "done", "result": result}
