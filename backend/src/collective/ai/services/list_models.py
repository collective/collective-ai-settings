from collective.ai.vocabularies.models import fetch_models
from plone.restapi.deserializer import json_body
from plone.restapi.services import Service


class ListAIModels(Service):
    """Return the models exposed by a given AI service URL.

    POST @ai-list-models with body:
        {
            "url": "http://...",
            "api_key": "optional",
            "capability": "completion|embedding|vision|tools|thinking"
        }

    When ``capability`` is provided, only models advertising that capability
    (via Ollama's /api/show) are returned.
    """

    def reply(self):
        data = json_body(self.request)
        url = (data.get("url") or "").strip()
        api_key = data.get("api_key") or None
        capability = (data.get("capability") or "").strip() or None
        if not url:
            self.request.response.setStatus(400)
            return {"error": "url is required"}
        return {
            "models": fetch_models(url, api_key, capability=capability),
        }
