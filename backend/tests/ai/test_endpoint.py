"""Tests for the @ai REST endpoint, driven at integration level.

The endpoint is instantiated directly against the portal and the layer
request, with the JSON body set on ``request["BODY"]`` (what ``json_body``
reads).
"""

from collective.aisettings import models as ai_models
from collective.aisettings.interfaces import IAISettings
from collective.aisettings.services.ai import AIServiceEndpoint
from plone import api
from pydantic_ai.models.test import TestModel

import json
import pytest


CONNECTION = {
    "url": "http://localhost:11434",
    "models": [
        {
            "model": "test-model",
            "capabilities": ["completion", "thinking", "vision", "tools"],
        }
    ],
}


def _call(portal, request, body):
    request.set("BODY", json.dumps(body))
    # The published service mixes in BrowserView for __init__; here we set the
    # attributes directly so we can exercise reply() in isolation.
    endpoint = AIServiceEndpoint.__new__(AIServiceEndpoint)
    endpoint.context = portal
    endpoint.request = request
    result = endpoint.reply()
    return request.response.getStatus(), result


@pytest.fixture()
def configured(portal):
    with api.env.adopt_roles(["Manager"]):
        api.portal.set_registry_record("models", [CONNECTION], interface=IAISettings)
    return portal


@pytest.fixture()
def test_model():
    previous = ai_models.set_test_model(TestModel())
    yield
    ai_models.set_test_model(previous)


class TestValidation:
    def test_missing_capability(self, portal, http_request):
        status, result = _call(portal, http_request, {})
        assert status == 400
        assert "capability" in result["error"]

    def test_unknown_capability(self, portal, http_request):
        status, _ = _call(portal, http_request, {"capability": "wat"})
        assert status == 404

    def test_chat_requires_prompt(self, portal, http_request):
        status, _ = _call(portal, http_request, {"capability": "chat"})
        assert status == 400

    def test_async_with_tools_rejected(self, portal, http_request):
        status, result = _call(
            portal,
            http_request,
            {"capability": "chat", "prompt": "hi", "async": True, "use_tools": True},
        )
        assert status == 400
        assert "tool" in result["error"].lower()


class TestHappyPath:
    def test_chat_sync(self, configured, http_request, test_model):
        status, result = _call(
            configured, http_request, {"capability": "chat", "prompt": "hi"}
        )
        assert status == 200
        assert result["status"] == "done"
        assert isinstance(result["result"]["response"], str)

    def test_structured_output(self, configured, http_request, test_model):
        body = {
            "capability": "chat",
            "prompt": "summarize",
            "output_schema": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        }
        status, result = _call(configured, http_request, body)
        assert status == 200
        assert isinstance(result["result"]["response"], dict)
        assert "title" in result["result"]["response"]

    def test_invalid_output_schema(self, configured, http_request, test_model):
        body = {
            "capability": "chat",
            "prompt": "x",
            "output_schema": {"type": "string"},
        }
        status, _ = _call(configured, http_request, body)
        assert status == 400

    def test_no_model_returns_503(self, portal, http_request, test_model):
        status, _ = _call(portal, http_request, {"capability": "chat", "prompt": "hi"})
        assert status == 503
