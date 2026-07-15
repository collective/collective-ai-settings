"""Live integration tests against a real Ollama server.

These are **opt-in**: set ``AISETTINGS_OLLAMA_URL`` to your server's
OpenAI-compatible endpoint to run them, e.g.::

    AISETTINGS_OLLAMA_URL=http://10.100.0.10:11434/v1 .venv/bin/pytest tests/ai/test_ollama_live.py

When the variable is unset, or the server is unreachable / has no usable
model, the relevant tests are skipped. Each capability test first looks for an
installed model that advertises that capability (via Ollama's ``/api/show``);
if none is found it skips with a suggestion of a common model to ``ollama pull``.
"""

from collective.aisettings.interfaces import IAIService
from collective.aisettings.interfaces import IAISettings
from collective.aisettings.interfaces import IAITool
from collective.aisettings.tools import AITool
from collective.aisettings.vocabularies.models import fetch_model_capabilities
from collective.aisettings.vocabularies.models import fetch_models
from plone import api
from zope.component import getGlobalSiteManager
from zope.component import queryUtility

import os
import pytest


OLLAMA_URL = os.environ.get("AISETTINGS_OLLAMA_URL")

# A 1x1 transparent PNG, enough to exercise the vision pipeline end to end.
PNG_1PX = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0"
    "lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# Suggested model to pull per capability token when none is installed.
SUGGESTED = {
    "completion": "llama3.2",
    "tools": "llama3.2",
    "thinking": "qwen3",
    "vision": "llama3.2-vision",
    "embedding": "nomic-embed-text",
}


pytestmark = pytest.mark.skipif(
    not OLLAMA_URL,
    reason=(
        "set AISETTINGS_OLLAMA_URL to run live Ollama tests "
        "(e.g. http://10.100.0.10:11434/v1)"
    ),
)


def _base_host(url: str) -> str:
    """Strip a trailing ``/v1`` so the Ollama-native helpers hit the right URL."""
    base = (url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


@pytest.fixture(scope="module")
def discovered():
    """Discover installed models + capabilities, or skip the whole module."""
    base = _base_host(OLLAMA_URL)
    names = fetch_models(base)
    if not names:
        pytest.skip(
            f"No models found at {OLLAMA_URL} (server unreachable or empty). "
            f"Try `ollama pull {SUGGESTED['completion']}`."
        )
    pinned = []
    cap_index: dict[str, str] = {}
    for name in names:
        caps = fetch_model_capabilities(base, None, name)
        if not caps:
            continue
        pinned.append({"model": name, "capabilities": caps})
        for cap in caps:
            cap_index.setdefault(cap, name)
    if not pinned:
        pytest.skip("No model capabilities could be detected via Ollama's /api/show.")
    return {"pinned": pinned, "cap_index": cap_index}


@pytest.fixture()
def configured(portal, discovered):
    """Register the live connection with every discovered model pinned."""
    connection = {"url": OLLAMA_URL, "models": discovered["pinned"]}
    with api.env.adopt_roles(["Manager"]):
        api.portal.set_registry_record("models", [connection], interface=IAISettings)
    return portal


@pytest.fixture()
def service(configured):
    return queryUtility(IAIService)


def _require(discovered, token):
    """Return a model advertising ``token`` or skip with a pull suggestion."""
    name = discovered["cap_index"].get(token)
    if not name:
        pytest.skip(
            f"No installed Ollama model advertises {token!r}; "
            f"try `ollama pull {SUGGESTED.get(token, token)}`."
        )
    return name


class TestLiveCapabilities:
    def test_chat(self, discovered, configured, service):
        _require(discovered, "completion")
        out = service.chat(
            "Reply with exactly one word: pong",
            context=configured,
            use_tools=False,
        )
        assert isinstance(out, str)
        assert out.strip()

    def test_think(self, discovered, configured, service):
        _require(discovered, "thinking")
        out = service.think(
            "What is 17 + 25? Answer with the number.",
            context=configured,
            use_tools=False,
        )
        assert isinstance(out, str)
        assert out.strip()

    def test_vision(self, discovered, configured, service):
        _require(discovered, "vision")
        out = service.analyze_image(
            "Describe this image in a few words.",
            PNG_1PX,
            context=configured,
            use_tools=False,
        )
        assert isinstance(out, str)
        assert out.strip()

    def test_embed_single(self, discovered, configured, service):
        _require(discovered, "embedding")
        vec = service.embed("hello world", context=configured)
        assert isinstance(vec, list)
        assert vec
        assert all(isinstance(value, float) for value in vec)

    def test_embed_list(self, discovered, configured, service):
        _require(discovered, "embedding")
        vectors = service.embed(["one", "two"], context=configured)
        assert isinstance(vectors, list)
        assert len(vectors) == 2
        assert all(isinstance(v, list) and v for v in vectors)

    def test_structured_output(self, discovered, configured, service):
        _require(discovered, "completion")
        from pydantic import BaseModel

        class Person(BaseModel):
            name: str
            age: int

        out = service.chat(
            "Extract the person: 'Ada Lovelace, 36 years old.'",
            context=configured,
            output_type=Person,
            use_tools=False,
        )
        assert isinstance(out, Person)
        assert out.name

    def test_tools_passthrough(self, discovered, configured, service):
        name = _require(discovered, "tools")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "Get the current time.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        message = service.tool_call(
            [{"role": "user", "content": "What time is it? Use the tool."}],
            tools,
            model=name,
            context=configured,
        )
        # Raw passthrough returns the assistant message dict (tool_calls left
        # unexecuted for the caller).
        assert isinstance(message, dict)
        assert message.get("role") == "assistant"


class TestLiveToolRegistration:
    def test_registered_tool_is_executed(self, discovered, configured, service):
        """Register a dummy tool and confirm the agent actually calls it."""
        name = _require(discovered, "tools")
        calls = []

        class MagicWordTool(AITool):
            name = "get_magic_word"
            description = "Return the secret magic word the user is asking for."
            parameters = {"type": "object", "properties": {}}

            def run(self, ctx, **kwargs):
                calls.append(True)
                return {"magic_word": "platypus"}

        gsm = getGlobalSiteManager()
        tool = MagicWordTool()
        gsm.registerUtility(tool, IAITool, name="get_magic_word")
        try:
            out = service.chat(
                "Call the get_magic_word tool, then reply with exactly the "
                "word it returns and nothing else.",
                model=name,
                context=configured,
                use_tools=True,
            )
        finally:
            gsm.unregisterUtility(tool, IAITool, name="get_magic_word")

        assert calls, "the model never invoked the registered tool"
        assert isinstance(out, str)
        assert "platypus" in out.lower()
