from collective.aisettings.vocabularies.models import fetch_model_capabilities
from plone.restapi.deserializer import json_body
from plone.restapi.services import Service


class GetAIModelCapabilities(Service):
    """Return the capabilities advertised by a specific model.

    POST @ai-model-capabilities with body:
        {"url": "http://...", "api_key": "optional", "model": "<id>"}

    Returns `{"capabilities": [...]}` normalized to the
    `collective.aisettings.Capabilities` vocabulary tokens.
    """

    def reply(self):
        data = json_body(self.request)
        url = (data.get("url") or "").strip()
        api_key = data.get("api_key") or None
        model = (data.get("model") or "").strip()
        if not url or not model:
            self.request.response.setStatus(400)
            return {"error": "url and model are required"}
        return {
            "capabilities": fetch_model_capabilities(url, api_key, model),
        }
