"""Build pydantic-ai models from resolved registry entries.

A registry *entry* is the flat dict returned by
:func:`collective.aisettings.utils.resolve_model` (``url``/``api_key``/
``model``/...). :func:`build_model` turns one into a pydantic-ai
``OpenAIChatModel`` pointed at the OpenAI-compatible endpoint.
"""

from pydantic import create_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

import typing


# Built models hold an httpx client and are safe to reuse across calls, so we
# cache them by the connection coordinates rather than rebuilding per request.
_MODEL_CACHE: dict[tuple[str, str, str], OpenAIChatModel] = {}

# Test seam: when set (see tests), :func:`build_model` returns this model
# instead of talking to a real endpoint.
_TEST_MODEL = None


def set_test_model(model):
    """Force :func:`build_model` to return ``model`` (or clear with ``None``).

    Returns the previously installed override so callers can restore it.
    """
    global _TEST_MODEL
    previous = _TEST_MODEL
    _TEST_MODEL = model
    return previous


def openai_base_url(url: str) -> str:
    """Normalise a stored connection URL to an OpenAI ``/v1`` base URL.

    The registry stores the bare host (e.g. ``http://localhost:11434``); the
    OpenAI-compatible API lives under ``/v1``. Tolerates a URL that already
    ends in ``/v1``.
    """
    base = (url or "").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


def build_model(entry: dict) -> OpenAIChatModel:
    """Return an ``OpenAIChatModel`` for a resolved registry ``entry``."""
    if _TEST_MODEL is not None:
        return _TEST_MODEL

    url = entry["url"]
    api_key = entry.get("api_key") or ""
    model_name = entry["model"]

    cache_key = (url, api_key, model_name)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    provider = OpenAIProvider(
        base_url=openai_base_url(url),
        # The OpenAI client requires a non-empty key; many local servers
        # (Ollama, vLLM) ignore it.
        api_key=api_key or "unused",
    )
    model = OpenAIChatModel(model_name, provider=provider)
    _MODEL_CACHE[cache_key] = model
    return model


# --- JSON Schema -> pydantic model (for REST structured output) -------------

_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _py_type(field_schema: dict):
    json_type = field_schema.get("type")
    if json_type == "array":
        item_type = _py_type(field_schema.get("items") or {})
        return list[item_type]
    return _JSON_TYPES.get(json_type, typing.Any)


def model_from_json_schema(schema: dict, name: str = "AIOutput"):
    """Build a pydantic model from a (top-level object) JSON Schema.

    Supports the common case — an object with scalar/array/object properties —
    so REST callers can request structured output. Returns ``None`` when the
    schema is not a usable object schema.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    properties = schema.get("properties") or {}
    if not properties:
        return None
    required = set(schema.get("required") or [])
    fields: dict[str, tuple] = {}
    for field_name, field_schema in properties.items():
        py_type = _py_type(field_schema or {})
        if field_name in required:
            fields[field_name] = (py_type, ...)
        else:
            fields[field_name] = (py_type | None, None)
    return create_model(name, **fields)
