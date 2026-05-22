"""Low-level HTTP helpers for OpenAI-compatible AI services."""

from collective.ai import logger

import json
import urllib.error
import urllib.request


DEFAULT_TIMEOUT = 600


def _post_json(
    url: str,
    body: dict,
    api_key: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict | None:
    encoded = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method="POST")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(  # noqa: S310 - URI is admin-supplied
            request, timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("AI POST %s failed: %s", url, exc)
        return None


def chat_completion(
    uri: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    **extra,
) -> str | None:
    """POST a chat completion request and return the assistant message text."""
    endpoint = uri.rstrip("/") + "/v1/chat/completions"
    body = {"model": model, "messages": messages, **extra}
    payload = _post_json(endpoint, body, api_key)
    if not payload:
        return None
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected chat completion response: %s", payload)
        return None


def chat_completion_message(
    uri: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    **extra,
) -> dict | None:
    """Return the full assistant message dict (with `tool_calls` etc.)."""
    endpoint = uri.rstrip("/") + "/v1/chat/completions"
    body = {"model": model, "messages": messages, **extra}
    payload = _post_json(endpoint, body, api_key)
    if not payload:
        return None
    try:
        return payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected chat completion response: %s", payload)
        return None


def embeddings(
    uri: str,
    api_key: str | None,
    model: str,
    inputs: list[str],
) -> list[list[float]] | None:
    """POST an embeddings request and return a list of embedding vectors."""
    endpoint = uri.rstrip("/") + "/v1/embeddings"
    body = {"model": model, "input": inputs}
    payload = _post_json(endpoint, body, api_key)
    if not payload:
        return None
    try:
        return [item["embedding"] for item in payload.get("data", [])]
    except (KeyError, TypeError):
        logger.warning("Unexpected embeddings response: %s", payload)
        return None
