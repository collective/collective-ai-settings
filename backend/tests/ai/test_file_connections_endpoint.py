"""Tests for the @ai-file-connections REST service."""

from collective.aisettings import utils
from collective.aisettings.services.file_connections import AIFileConnections
from collective.aisettings.utils import CONNECTIONS_ENV

import json
import pytest


def _write(tmp_path, data):
    path = tmp_path / "connections.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _reply(portal, request):
    service = AIFileConnections.__new__(AIFileConnections)
    service.context = portal
    service.request = request
    return service.reply()


@pytest.fixture(autouse=True)
def _clear_cache():
    utils._file_cache = None
    yield
    utils._file_cache = None


class TestAIFileConnectionsEndpoint:
    def test_inactive_when_env_unset(self, portal, http_request, monkeypatch):
        monkeypatch.delenv(CONNECTIONS_ENV, raising=False)
        result = _reply(portal, http_request)
        assert result["active"] is False
        assert result["env_var"] == CONNECTIONS_ENV
        assert result["connections"] == []

    def test_inactive_when_file_invalid(
        self, portal, http_request, monkeypatch, tmp_path
    ):
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        monkeypatch.setenv(CONNECTIONS_ENV, str(bad))
        result = _reply(portal, http_request)
        assert result["active"] is False

    def test_active_and_secret_free(self, portal, http_request, monkeypatch, tmp_path):
        path = _write(
            tmp_path,
            [
                {
                    "url": "http://svc",
                    "api_key_env": "MY_AI_KEY",
                    "models": [{"model": "m1", "capabilities": ["completion"]}],
                }
            ],
        )
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        monkeypatch.setenv("MY_AI_KEY", "sk-should-not-leak")
        result = _reply(portal, http_request)
        assert result["active"] is True
        assert result["connections"][0]["api_key_env"] == "MY_AI_KEY"
        assert "sk-should-not-leak" not in json.dumps(result)
