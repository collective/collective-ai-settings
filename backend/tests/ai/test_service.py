"""Tests for the pydantic-ai-backed AIService.

These exercise the service without any network access by installing a
pydantic-ai ``TestModel`` through ``models.set_test_model`` and by patching the
OpenAI-SDK helpers used for embeddings / the raw tool passthrough.
"""

from collective.aisettings import models as ai_models
from collective.aisettings import service as ai_service
from collective.aisettings.interfaces import IAIService
from collective.aisettings.interfaces import IAISettings
from collective.aisettings.interfaces import IAITool
from collective.aisettings.tools import AITool
from plone import api
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel
from zope.component import getGlobalSiteManager
from zope.component import queryUtility

import pytest


CONNECTION = {
    "url": "http://localhost:11434",
    "models": [
        {
            "model": "test-model",
            "capabilities": [
                "completion",
                "thinking",
                "vision",
                "embedding",
                "tools",
            ],
        }
    ],
}


@pytest.fixture()
def configured(portal):
    """A portal with one connection advertising every capability."""
    with api.env.adopt_roles(["Manager"]):
        api.portal.set_registry_record("models", [CONNECTION], interface=IAISettings)
    return portal


@pytest.fixture()
def test_model():
    """Install a pydantic-ai TestModel for the duration of a test."""
    model = TestModel()
    previous = ai_models.set_test_model(model)
    yield model
    ai_models.set_test_model(previous)


@pytest.fixture()
def service():
    return queryUtility(IAIService)


class TestAIServiceRun:
    def test_utility_registered(self, configured, service):
        assert service is not None

    def test_chat_returns_text(self, configured, test_model, service):
        result = service.chat("hello", context=configured)
        assert isinstance(result, str)

    def test_no_model_configured_returns_none(self, portal, test_model, service):
        # No registry record set → resolution fails before any model call.
        assert service.chat("hello", context=portal) is None

    def test_structured_output(self, configured, test_model, service):
        class Summary(BaseModel):
            title: str
            score: int

        result = service.chat("summarize", context=configured, output_type=Summary)
        assert isinstance(result, Summary)
        assert isinstance(result.title, str)

    def test_run_executes_registered_tool(self, configured, test_model, service):
        calls = []

        class RecordingTool(AITool):
            name = "record"
            description = "record the argument"
            parameters = {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            }

            def run(self, ctx, value):
                calls.append(value)
                return {"ok": True}

        gsm = getGlobalSiteManager()
        tool = RecordingTool()
        gsm.registerUtility(tool, IAITool, name="record")
        try:
            # TestModel auto-calls every offered tool once.
            service.chat("do it", context=configured, use_tools=True)
        finally:
            gsm.unregisterUtility(tool, IAITool, name="record")

        assert calls, "the registered tool was not executed by the agent"

    def test_use_tools_false_skips_tools(self, configured, test_model, service):
        calls = []

        class RecordingTool(AITool):
            name = "record2"
            description = "record"
            parameters = {"type": "object", "properties": {}}

            def run(self, ctx):
                calls.append(True)
                return {}

        gsm = getGlobalSiteManager()
        tool = RecordingTool()
        gsm.registerUtility(tool, IAITool, name="record2")
        try:
            service.chat("no tools", context=configured, use_tools=False)
        finally:
            gsm.unregisterUtility(tool, IAITool, name="record2")

        assert calls == []


class TestEmbeddingsAndToolCall:
    def test_embed_single(self, configured, service, monkeypatch):
        monkeypatch.setattr(ai_service, "_embeddings", lambda *a, **kw: [[0.1, 0.2]])
        result = service.embed("hello", context=configured)
        assert result == [0.1, 0.2]

    def test_embed_list(self, configured, service, monkeypatch):
        monkeypatch.setattr(ai_service, "_embeddings", lambda *a, **kw: [[0.1], [0.2]])
        result = service.embed(["a", "b"], context=configured)
        assert result == [[0.1], [0.2]]

    def test_tool_call_passthrough(self, configured, service, monkeypatch):
        message = {"role": "assistant", "content": None, "tool_calls": [{"x": 1}]}
        monkeypatch.setattr(ai_service, "raw_tool_call", lambda *a, **kw: message)
        result = service.tool_call(
            [{"role": "user", "content": "hi"}],
            [{"type": "function"}],
            context=configured,
        )
        assert result == message
