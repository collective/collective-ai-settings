from collective.aisettings import logger
from collective.aisettings.interfaces import IAISettings
from plone import api


def _all_connections() -> list[dict]:
    return (
        api.portal.get_registry_record("models", interface=IAISettings, default=[])
        or []
    )


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
