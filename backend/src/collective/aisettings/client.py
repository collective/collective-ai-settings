"""OpenAI-SDK helpers for the bits pydantic-ai does not cover.

pydantic-ai handles chat/think/vision (see :mod:`collective.aisettings.models`
and :mod:`collective.aisettings.service`). Two things it does not:

- **Embeddings** — there is no embeddings API in pydantic-ai.
- **Raw function-calling passthrough** — returning *unexecuted* ``tool_calls``
  for the caller to run (the legacy :meth:`IAIService.tool_call` contract).

Both go straight through the ``openai`` client here.
"""

from collective.aisettings import logger
from collective.aisettings.models import openai_base_url
from openai import OpenAI


# OpenAI clients hold an httpx connection pool; reuse one per connection.
_CLIENT_CACHE: dict[tuple[str, str], OpenAI] = {}


def get_client(url: str, api_key: str | None) -> OpenAI:
    """Return a (cached) ``openai.OpenAI`` client for a connection URL."""
    key = (url, api_key or "")
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = OpenAI(
            base_url=openai_base_url(url),
            # Local servers (Ollama, vLLM) ignore the key but the client
            # requires a non-empty string.
            api_key=api_key or "unused",
        )
        _CLIENT_CACHE[key] = client
    return client


def embeddings(
    url: str,
    api_key: str | None,
    model: str,
    inputs: list[str],
) -> list[list[float]] | None:
    """Return one embedding vector per input string, or ``None`` on failure."""
    try:
        response = get_client(url, api_key).embeddings.create(model=model, input=inputs)
    except Exception as exc:
        logger.warning("AI embeddings call to %s failed: %s", url, exc)
        return None
    return [item.embedding for item in response.data]


def raw_tool_call(
    url: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    tools: list[dict],
) -> dict | None:
    """Raw function-calling passthrough.

    Returns the full assistant message dict (including any *unexecuted*
    ``tool_calls``), or ``None`` on failure.
    """
    try:
        response = get_client(url, api_key).chat.completions.create(
            model=model, messages=messages, tools=tools
        )
    except Exception as exc:
        logger.warning("AI tool call to %s failed: %s", url, exc)
        return None
    try:
        return response.choices[0].message.model_dump()
    except (IndexError, AttributeError):
        logger.warning("Unexpected tool call response: %s", response)
        return None
