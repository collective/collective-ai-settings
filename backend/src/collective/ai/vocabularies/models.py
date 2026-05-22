from collective.ai import logger

import json
import urllib.error
import urllib.request


REQUEST_TIMEOUT = 5

# Map raw capability names returned by various AI services to the tokens used
# by the `collective.ai.Capabilities` vocabulary. Anything not listed here is
# dropped during normalization.
CAPABILITY_ALIASES = {
    "chat": "completion",
    "completion": "completion",
    "completions": "completion",
    "embed": "embedding",
    "embedding": "embedding",
    "embeddings": "embedding",
    "vision": "vision",
    "image": "vision",
    "images": "vision",
    "tools": "tools",
    "function-calling": "tools",
    "function_calling": "tools",
    "functions": "tools",
    "tool-use": "tools",
    "reasoning": "thinking",
    "thinking": "thinking",
}


def _http_json(request: urllib.request.Request):
    try:
        with urllib.request.urlopen(  # noqa: S310 - URI is admin-supplied
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("AI request to %s failed: %s", request.full_url, exc)
        return None


def _list_models_raw(uri: str, api_key: str | None) -> list:
    """Return the raw entries from /v1/models (dicts or strings)."""
    endpoint = uri.rstrip("/") + "/v1/models"
    request = urllib.request.Request(endpoint)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    payload = _http_json(request)
    if not payload:
        return []
    return payload.get("data") or payload.get("models") or []


def _entry_name(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("id") or entry.get("name")
    return entry or None


def _list_models(uri: str, api_key: str | None) -> list[str]:
    return [
        name
        for name in (_entry_name(e) for e in _list_models_raw(uri, api_key))
        if name
    ]


def _model_capabilities(uri: str, api_key: str | None, model: str) -> list[str] | None:
    """Return Ollama `/api/show` capabilities for a model, or None on failure."""
    endpoint = uri.rstrip("/") + "/api/show"
    body = json.dumps({"model": model}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    payload = _http_json(request)
    if not payload:
        return None
    return payload.get("capabilities") or []


def _capabilities_from_v1_entry(entry: dict) -> list[str]:
    """Read capability hints from an OpenAI-compatible /v1/models entry."""
    raw: list[str] = []
    for field in ("capabilities", "labels", "tags"):
        value = entry.get(field)
        if not value:
            continue
        if isinstance(value, list):
            raw.extend(str(v) for v in value)
        elif isinstance(value, dict):
            raw.extend(k for k, v in value.items() if v)
    return raw


def _normalize(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        token = CAPABILITY_ALIASES.get(value.lower().replace(" ", "-"))
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def fetch_models(
    uri: str,
    api_key: str | None = None,
    capability: str | None = None,
) -> list[str]:
    """Return models from an OpenAI-compatible /v1/models endpoint.

    If ``capability`` is given, each model is checked against Ollama's
    ``/api/show`` endpoint and only models advertising that capability are
    returned. Models whose capabilities cannot be determined are dropped
    from the filtered result.
    """
    if not uri:
        return []
    models = _list_models(uri, api_key)
    if not capability:
        return models
    return [
        m for m in models if capability in (_model_capabilities(uri, api_key, m) or [])
    ]


def fetch_model_capabilities(uri: str, api_key: str | None, model: str) -> list[str]:
    """Return the capabilities advertised by a given model.

    Tries Ollama's ``/api/show`` first; if that yields no capabilities,
    falls back to looking up the model in the OpenAI-compatible
    ``/v1/models`` listing and reading ``capabilities``, ``labels`` or
    ``tags`` fields. Returned tokens are normalized to match the
    ``collective.ai.Capabilities`` vocabulary; unknown values are dropped.
    """
    if not uri or not model:
        return []

    raw = _model_capabilities(uri, api_key, model) or []
    if not raw:
        for entry in _list_models_raw(uri, api_key):
            if isinstance(entry, dict) and _entry_name(entry) == model:
                raw = _capabilities_from_v1_entry(entry)
                break
    return _normalize(raw)
