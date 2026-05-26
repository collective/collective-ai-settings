"""Module where all interfaces, events and exceptions live."""

from collective.aisettings import _
from plone.schema import JSONField
from zope.interface import Interface
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

import json


class IBrowserLayer(IDefaultBrowserLayer):
    """Marker interface that defines a browser layer."""


MODEL_JSON_SCHEMA = {
    "type": "array",
    "items": {
        # One connection — URL + optional API key + a nested list of
        # pinned model definitions. A connection with empty/absent ``models``
        # is a *generic passthrough*: usable only when the @ai caller
        # explicitly names a model that no pinned definition serves.
        "type": "object",
        "properties": {
            "url": {"type": "string", "format": "uri"},
            "api_key": {"type": "string"},
            "models": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "capabilities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                        # When true the model is only usable if the current
                        # user has any of the listed Plone permission titles
                        # (e.g. "View", "Modify portal content") on the
                        # call context. OR semantics.
                        "protect_with_permission": {"type": "boolean"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                    },
                    "required": ["model"],
                },
            },
        },
        "required": ["url"],
    },
}


class IAIModelConfiguration(Interface):
    """Shape of the AI connections stored inside IAISettings.models.

    Kept as a documentation/reference interface. The collection is stored as
    a JSON list in the registry rather than as zope.schema Objects so it can
    be edited through plone.restapi/Volto without custom serializers.
    """


class IAISettings(Interface):
    """Settings for the AI service connections."""

    models = JSONField(
        title=_("AI Connections"),
        description=_(
            "List of configured AI connections. Each entry stores a service "
            "URL, an optional API key, and zero or more model definitions "
            "(each with capabilities and an optional permission gate). A "
            "connection with no model definitions is a generic passthrough, "
            "usable only when the caller explicitly names a model. Order "
            "matters: the first matching definition takes precedence."
        ),
        required=False,
        default=[],
        schema=json.dumps(MODEL_JSON_SCHEMA),
    )


class IAIService(Interface):
    """Public utility addons use to call the configured AI services.

    Resolution rules for every method:
      - If ``model`` is given, an entry must be findable by that exact name:
        first a specific entry (``limit_model_and_capabilities=true``) with
        ``entry["model"] == model``, otherwise the first generic entry
        (``limit_model_and_capabilities=false``) is used as a passthrough
        with the requested model name. If neither exists the call fails.
      - Otherwise the first specific entry advertising the requested
        capability is used. Generic entries are ineligible.
      - ``None`` is returned when nothing matches.

    Permission gate:
      - If the resolved entry has ``protect_with_permission=true``, the
        current user must hold at least one of ``entry["permissions"]`` on
        ``context``. On denial the call returns ``None`` and the denial is
        logged.
      - ``context`` defaults to the portal root when omitted.
    """

    def chat(prompt, model=None, system=None, context=None):
        """Generate text using a model with the ``completion`` capability.

        ``prompt`` may be a string or a pre-built list of OpenAI-style
        messages. ``system`` is an optional system instruction prepended to
        the messages. ``context`` is the object permission checks run
        against (portal root if omitted). Returns the assistant's text
        reply, or ``None``.
        """

    def think(prompt, model=None, system=None, context=None):
        """Run a reasoning call using a model with the ``thinking``
        capability. Same shape as :meth:`chat`."""

    def analyze_image(prompt, image, model=None, context=None):
        """Describe/analyze ``image`` (URL or ``data:`` URI) using a model
        with the ``vision`` capability. Returns the assistant's text reply,
        or ``None``."""

    def embed(text, model=None, context=None):
        """Compute an embedding (or list of embeddings) using a model with
        the ``embedding`` capability. ``text`` may be a string or list of
        strings; the return shape mirrors the input."""

    def tool_call(messages, tools, model=None, context=None):
        """Run a tool/function-calling completion using a model with the
        ``tools`` capability. Returns the full assistant message dict
        (including any ``tool_calls``), or ``None``."""

    # ---- low-level methods shared with the async REST endpoint ----

    def resolve_for(capability, model_override):
        """Return a configured model entry suitable for ``capability``.

        ``capability`` is the REST/API capability name (``chat``, ``think``,
        ``vision``, ``embed``, ``tools``). ``model_override`` is an optional
        model name to look up first. Returns ``None`` when no entry matches.
        When a generic (non-limited) entry is used as a passthrough with a
        model override, the returned dict carries the overridden model name.

        Reads the plone registry — call from a request thread.
        """

    def run_call(capability, entry, data):
        """Execute an AI call against a pre-resolved model ``entry``.

        ``data`` is the request payload (``prompt``/``system``/``image``/
        ``input``/``messages``/``tools`` as appropriate). Returns a result
        dict (``{"response": ...}`` or ``{"embedding": ...}``).

        Performs only outbound HTTP — safe to call from a worker thread.
        The permission gate (if any) must have been checked by the caller
        before invoking ``run_call``.
        """
