"""Tests for the environment-driven AI connections file.

These exercise :mod:`collective.aisettings.utils` — reading, validating and
merging the JSON file named by ``COLLECTIVE_AISETTINGS_CONNECTIONS`` with the
registry-configured connections (file-first precedence).
"""

from collective.aisettings import utils
from collective.aisettings.interfaces import IAISettings
from collective.aisettings.utils import CONNECTIONS_ENV
from plone import api

import json
import pytest


def _write(tmp_path, data):
    path = tmp_path / "connections.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level file cache around every test."""
    utils._file_cache = None
    yield
    utils._file_cache = None


class TestFileConnections:
    def test_no_env_var_returns_empty(self, monkeypatch):
        monkeypatch.delenv(CONNECTIONS_ENV, raising=False)
        assert utils._file_connections() == []

    def test_reads_valid_file(self, monkeypatch, tmp_path):
        path = _write(tmp_path, [{"url": "http://svc:1234", "models": []}])
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        conns = utils._file_connections()
        assert conns == [{"url": "http://svc:1234", "models": []}]

    def test_missing_file_falls_back_to_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv(CONNECTIONS_ENV, str(tmp_path / "nope.json"))
        assert utils._file_connections() == []

    def test_malformed_json_falls_back_to_empty(self, monkeypatch, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv(CONNECTIONS_ENV, str(path))
        assert utils._file_connections() == []

    def test_schema_violation_falls_back_to_empty(self, monkeypatch, tmp_path):
        # A connection missing the required "url" is invalid.
        path = _write(tmp_path, [{"models": []}])
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        assert utils._file_connections() == []

    def test_cache_keyed_by_mtime(self, monkeypatch, tmp_path):
        path = _write(tmp_path, [{"url": "http://one", "models": []}])
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        assert utils._file_connections()[0]["url"] == "http://one"

        # Rewrite with a bumped mtime; the new content must be picked up.
        import os

        new_mtime = os.path.getmtime(path) + 10
        (tmp_path / "connections.json").write_text(
            json.dumps([{"url": "http://two", "models": []}]), encoding="utf-8"
        )
        os.utime(path, (new_mtime, new_mtime))
        assert utils._file_connections()[0]["url"] == "http://two"


class TestApiKeyEnv:
    def test_api_key_env_resolved(self, monkeypatch, tmp_path):
        path = _write(
            tmp_path,
            [{"url": "http://svc", "api_key_env": "MY_AI_KEY", "models": []}],
        )
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        monkeypatch.setenv("MY_AI_KEY", "sk-secret")
        conn = utils._file_connections()[0]
        assert conn["api_key"] == "sk-secret"
        # The indirection key is dropped so downstream sees only api_key.
        assert "api_key_env" not in conn

    def test_api_key_env_wins_over_inline(self, monkeypatch, tmp_path):
        path = _write(
            tmp_path,
            [
                {
                    "url": "http://svc",
                    "api_key": "inline",
                    "api_key_env": "MY_AI_KEY",
                    "models": [],
                }
            ],
        )
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        monkeypatch.setenv("MY_AI_KEY", "from-env")
        assert utils._file_connections()[0]["api_key"] == "from-env"

    def test_unset_env_keeps_inline_key(self, monkeypatch, tmp_path):
        path = _write(
            tmp_path,
            [
                {
                    "url": "http://svc",
                    "api_key": "inline",
                    "api_key_env": "MISSING_KEY",
                    "models": [],
                }
            ],
        )
        monkeypatch.setenv(CONNECTIONS_ENV, path)
        monkeypatch.delenv("MISSING_KEY", raising=False)
        conn = utils._file_connections()[0]
        assert conn["api_key"] == "inline"
        assert "api_key_env" not in conn


class TestMergePrecedence:
    def test_file_connections_come_first(self, portal, monkeypatch, tmp_path):
        with api.env.adopt_roles(["Manager"]):
            api.portal.set_registry_record(
                "models",
                [{"url": "http://registry", "models": []}],
                interface=IAISettings,
            )
        path = _write(tmp_path, [{"url": "http://file", "models": []}])
        monkeypatch.setenv(CONNECTIONS_ENV, path)

        merged = utils._all_connections()
        assert [c["url"] for c in merged] == ["http://file", "http://registry"]

    def test_registry_only_when_no_file(self, portal, monkeypatch):
        monkeypatch.delenv(CONNECTIONS_ENV, raising=False)
        with api.env.adopt_roles(["Manager"]):
            api.portal.set_registry_record(
                "models",
                [{"url": "http://registry", "models": []}],
                interface=IAISettings,
            )
        merged = utils._all_connections()
        assert [c["url"] for c in merged] == ["http://registry"]

    def test_file_model_wins_capability_resolution(self, portal, monkeypatch, tmp_path):
        with api.env.adopt_roles(["Manager"]):
            api.portal.set_registry_record(
                "models",
                [
                    {
                        "url": "http://registry",
                        "models": [
                            {"model": "reg-model", "capabilities": ["completion"]}
                        ],
                    }
                ],
                interface=IAISettings,
            )
        path = _write(
            tmp_path,
            [
                {
                    "url": "http://file",
                    "models": [{"model": "file-model", "capabilities": ["completion"]}],
                }
            ],
        )
        monkeypatch.setenv(CONNECTIONS_ENV, path)

        entry = utils.resolve_model("completion")
        assert entry["url"] == "http://file"
        assert entry["model"] == "file-model"
