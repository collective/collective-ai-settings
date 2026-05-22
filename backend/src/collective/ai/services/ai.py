"""Async REST proxy for :class:`IAIService`.

The synchronous AI calls can take minutes (vision models, long-context
generations), which is longer than the typical HTTP request timeouts in
proxies and load balancers. To avoid timeouts the endpoint enqueues the
call onto a worker thread and returns a task id immediately. Clients
poll ``GET @ai-task/<task_id>`` until ``status`` becomes ``done`` or
``error``.

URL: ``POST /++api++/@ai`` with body::

    {
      "capability": "chat" | "think" | "vision" | "embed" | "tools",
      "model": "...",   // optional override
      // capability-specific fields:
      //   chat/think  → prompt (required), system
      //   vision      → prompt (required), image (required)
      //   embed       → input | text (required)
      //   tools       → messages, tools (both required)
    }
"""

from collective.ai import logger
from collective.ai.interfaces import IAIService
from collective.ai.permissions import entry_permits
from collective.ai.services.tasks import complete_task
from collective.ai.services.tasks import create_task
from collective.ai.services.tasks import fail_task
from plone.restapi.deserializer import json_body
from plone.restapi.services import Service
from threading import Thread
from zope.component import queryUtility


SUPPORTED_CAPABILITIES = ("chat", "think", "vision", "embed", "tools")


def _validate(capability: str, data: dict) -> str | None:
    if capability in ("chat", "think") and not data.get("prompt"):
        return "prompt is required"
    if capability == "vision":
        if not data.get("prompt") or not data.get("image"):
            return "prompt and image are required"
    if capability == "embed" and not (data.get("input") or data.get("text")):
        return "input is required"
    if capability == "tools" and (not data.get("messages") or not data.get("tools")):
        return "messages and tools are required"
    return None


def _worker(service, task_id, capability, entry, data):
    """Worker-thread body. Touches no Zope state — uses only the utility's
    HTTP-only ``run_call`` method against a pre-resolved entry."""
    try:
        result = service.run_call(capability, entry, data)
        complete_task(task_id, result)
    except Exception as exc:
        logger.exception("AI task %s failed", task_id)
        fail_task(task_id, str(exc))


class AIServiceEndpoint(Service):
    """``POST /++api++/@ai`` — enqueue an async AI call.

    Returns ``{"task_id": ..., "status": "running"}`` with HTTP 202.
    Poll ``GET @ai-task/<task_id>`` for the result.
    """

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

        # Resolve the model in the request thread (registry access stays on
        # the Zope connection); the worker thread receives a plain dict.
        entry = service.resolve_for(capability, data.get("model") or None)
        if entry is None:
            self.request.response.setStatus(503)
            return {
                "error": f"no AI model configured for capability {capability!r}",
            }

        # Permission gate against the current content context.
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
