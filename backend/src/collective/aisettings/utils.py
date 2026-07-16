from collective.aisettings import logger
from collective.aisettings.interfaces import IAISettings
from collective.aisettings.interfaces import MODEL_JSON_SCHEMA
from jsonschema import validate as _json_validate
from jsonschema import ValidationError
from plone import api

import json
import os


# Name of the environment variable pointing at a JSON file with extra AI
# connections, merged *before* the registry ones (file-first precedence).
CONNECTIONS_ENV = "COLLECTIVE_AISETTINGS_CONNECTIONS"

# Process-wide cache for the parsed file, keyed by (path, mtime) so live edits
# are picked up without a restart but the file isn't re-read on every AI call.
_file_cache: tuple[tuple[str, float], list[dict]] | None = None


def _resolve_api_key(connection: dict) -> None:
    """Resolve ``api_key_env`` into a concrete ``api_key`` in place.

    If ``api_key_env`` names an environment variable that is set, its value
    wins over any inline ``api_key``. If it is named but unset, warn and leave
    the inline ``api_key`` (or empty) untouched. The ``api_key_env`` key is
    dropped so downstream consumers only ever see ``api_key``.
    """
    env_name = connection.pop("api_key_env", None)
    if not env_name:
        return
    value = os.environ.get(env_name)
    if value:
        connection["api_key"] = value
    elif not connection.get("api_key"):
        logger.warning(
            "AI connection %r references api_key_env %r, but that environment "
            "variable is not set; proceeding without an API key.",
            connection.get("url"),
            env_name,
        )


def _load_connections_file(path: str) -> list[dict]:
    """Read, validate and normalise the connections JSON file at ``path``.

    Returns ``[]`` (and logs) on any error so a broken file never takes the
    site down — it just falls back to registry-only configuration.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.error("Could not read AI connections file %r: %s", path, exc)
        return []
    try:
        _json_validate(data, MODEL_JSON_SCHEMA)
    except ValidationError as exc:
        logger.error("AI connections file %r is invalid: %s", path, exc.message)
        return []
    for connection in data:
        _resolve_api_key(connection)
    return data


def _file_connections() -> list[dict]:
    """Return connections declared in the file named by ``CONNECTIONS_ENV``.

    ``[]`` when the env var is unset or the file cannot be used. Cached by
    ``(path, mtime)``.
    """
    global _file_cache
    path = os.environ.get(CONNECTIONS_ENV)
    if not path:
        return []
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        logger.error("AI connections file %r is not accessible: %s", path, exc)
        return []
    cache_key = (path, mtime)
    if _file_cache is not None and _file_cache[0] == cache_key:
        return _file_cache[1]
    connections = _load_connections_file(path)
    _file_cache = (cache_key, connections)
    return connections


def _all_connections() -> list[dict]:
    registry = (
        api.portal.get_registry_record("models", interface=IAISettings, default=[])
        or []
    )
    # File-first: connections injected via the environment win on capability
    # and explicit-name resolution; registry connections extend them.
    return _file_connections() + list(registry)


def _flatten(connection: dict, model_def: dict) -> dict:
    """Collapse a ``(connection, model_def)`` pair into the flat entry dict
    that ``service.run_call`` and :func:`permissions.entry_permits` consume.

    ``model_def`` may be a synthesised stub like ``{"model": override}`` when
    a generic passthrough is being used.
    """
    return {
        "url": connection["url"],
        "api_key": connection.get("api_key") or "",
        "model": model_def.get("model", ""),
        "capabilities": list(model_def.get("capabilities") or []),
        "protect_with_permission": bool(model_def.get("protect_with_permission")),
        "permissions": list(model_def.get("permissions") or []),
    }


def pick_model(capability: str | None = None) -> dict | None:
    """Return the first configured (flattened) model.

    Without ``capability``: the first pinned model anywhere, or ``None`` if
    no connection has any pinned model.

    With ``capability``: only pinned models whose ``capabilities`` list
    contains ``capability`` are eligible. Generic-passthrough connections
    are skipped because they declare no capability metadata.
    """
    for connection in _all_connections():
        for model_def in connection.get("models") or []:
            if capability is None or capability in (
                model_def.get("capabilities") or []
            ):
                return _flatten(connection, model_def)
    return None


def resolve_model(capability: str, override: str | None = None) -> dict | None:
    """Return the model entry (flattened) that should be used for a call.

    With ``override`` — strict match, in order:
      1. The first pinned model anywhere whose ``model`` matches
         ``override`` exactly. Use it (its capabilities/permissions).
      2. Otherwise the first connection with no pinned models (generic
         passthrough). Use its ``url``/``api_key`` with ``override`` as the
         model name to send to the API.
      3. Otherwise ``None`` — no capability-based fallback when an override
         is supplied.

    Without ``override``: the first pinned model whose ``capabilities``
    list contains ``capability``. ``None`` if none match.
    """
    connections = _all_connections()
    if override:
        for connection in connections:
            for model_def in connection.get("models") or []:
                if model_def.get("model") == override:
                    return _flatten(connection, model_def)
        for connection in connections:
            if not (connection.get("models") or []):
                # Generic passthrough: connection has no pinned definitions.
                return _flatten(connection, {"model": override})
        logger.warning(
            "Requested AI model %r is not configured (no pinned model "
            "matches and no generic-passthrough connection is available).",
            override,
        )
        return None
    return pick_model(capability=capability)
