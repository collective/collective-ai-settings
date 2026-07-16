"""Module where all interfaces, events and exceptions live."""

from collective.aisettings import _
from plone.schema import JSONField
from zope.interface import Attribute
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
            # Only meaningful for connections loaded from the JSON file named
            # by ``COLLECTIVE_AISETTINGS_CONNECTIONS``: names an environment
            # variable to read the API key from at load time, so the secret
            # need not live in the file. Takes precedence over ``api_key``.
            "api_key_env": {"type": "string"},
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
                        # When true the model is only usable by a logged-in
                        # user — anonymous callers are denied. No specific
                        # permission is required, only authentication.
                        "only_for_authenticated": {"type": "boolean"},
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


class IAITool(Interface):
    """A single AI tool an agent may call during a :meth:`IAIService.run`.

    Other add-ons contribute tools to the agent in two ways:

    - **Global tools** — register the tool as a *named utility* providing
      ``IAITool``. It is offered on every (tool-enabled) run::

          <utility
              factory=".tools.WeatherTool"
              provides="collective.aisettings.interfaces.IAITool"
              name="get_weather"
              />

    - **Context-aware tools** — register an :class:`IAIToolProvider`
      subscription adapter that yields tools depending on the content
      object the call is rooted at.

    The base class :class:`collective.aisettings.tools.AITool` implements
    this interface; subclass it and override :attr:`description`,
    :attr:`parameters` and :meth:`run`.
    """

    name = Attribute("Tool name exposed to the model (a valid identifier).")
    description = Attribute("Natural-language description shown to the model.")
    parameters = Attribute(
        "JSON Schema (dict) describing the tool arguments, or ``None`` for "
        "a no-argument tool."
    )
    permission = Attribute(
        "Optional Plone permission *title* the current user must hold on the "
        "call context for this tool to be offered/executed. ``None`` = always."
    )
    capabilities = Attribute(
        "Optional iterable of capability names (``chat``/``think``/``vision``) "
        "the tool applies to. ``None`` = offered on every tool-enabled run."
    )

    def available_for(context):
        """Return ``True`` if the current user may use this tool against
        ``context`` (honours :attr:`permission`)."""

    def run(ctx, **kwargs):
        """Execute the tool. ``ctx`` is the pydantic-ai ``RunContext`` whose
        ``deps`` is an :class:`collective.aisettings.deps.AIDeps` (carrying the
        Plone ``context``/``request``). ``kwargs`` are the validated tool
        arguments. Returns a JSON-serialisable result for the model."""

    def to_pydantic_tool():
        """Return the ``pydantic_ai.Tool`` wrapping this component."""


class IAIToolProvider(Interface):
    """Subscription adapter (on a content object) that contributes
    context-aware :class:`IAITool` instances.

    Register one per add-on::

        <subscriber
            provides="collective.aisettings.interfaces.IAIToolProvider"
            for="*"
            factory=".tools.MyContextTools"
            />
    """

    def get_tools():
        """Return an iterable of :class:`IAITool` available for the adapted
        context."""


class IAIService(Interface):
    """Public utility add-ons use to call the configured AI services,
    backed by `pydantic-ai <https://ai.pydantic.dev>`_ agents.

    Model resolution (shared by every method):
      - If ``model`` is given, an entry must be findable by that exact name:
        first a pinned model with ``entry["model"] == model``, otherwise the
        first generic-passthrough connection (no pinned models) is used with
        the requested model name. If neither exists the call fails.
      - Otherwise the first pinned model advertising the requested capability
        is used. Generic passthroughs are ineligible.
      - ``None`` is returned when nothing matches.

    Permission gate:
      - If the resolved entry has ``only_for_authenticated=true``, the caller
        must be logged in (anonymous callers are denied); no specific
        permission is required.
      - If the resolved entry has ``protect_with_permission=true``, the
        current user must hold at least one of ``entry["permissions"]`` on
        ``context`` (portal root if omitted).
      - Both gates are independent and combine with AND semantics. On denial
        the call returns ``None`` and the denial is logged.
    """

    def run(
        prompt,
        capability="chat",
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
        message_history=None,
    ):
        """Run an agent for ``capability`` and return its output.

        ``prompt`` is the user input — a string, or a list of pydantic-ai
        content parts for multimodal calls. ``system`` becomes the agent's
        system prompt. ``output_type`` is an optional type / pydantic model
        for structured output (defaults to plain text). When ``use_tools`` is
        true the agent is offered every registered :class:`IAITool` the user
        may use against ``context`` and auto-executes them.

        Because tools run inside the agent loop and may touch Plone security
        and the ZODB, a tool-enabled run must execute in the request thread.

        Returns the agent's ``output`` (a string, or an instance of
        ``output_type``), or ``None`` when no model is configured / permitted.
        """

    def chat(
        prompt,
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        """Generate text using a model with the ``completion`` capability.
        Thin wrapper over :meth:`run` with ``capability="chat"``."""

    def think(
        prompt,
        model=None,
        system=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        """Run a reasoning call using a model with the ``thinking``
        capability. Same shape as :meth:`chat`."""

    def analyze_image(
        prompt,
        image,
        model=None,
        context=None,
        request=None,
        output_type=None,
        use_tools=True,
    ):
        """Describe/analyze ``image`` (URL or ``data:`` URI) using a model
        with the ``vision`` capability."""

    def embed(text, model=None, context=None):
        """Compute an embedding (or list of embeddings) using a model with
        the ``embedding`` capability. ``text`` may be a string or list of
        strings; the return shape mirrors the input. Uses the OpenAI SDK
        directly (pydantic-ai has no embeddings API)."""

    def tool_call(messages, tools, model=None, context=None):
        """Raw function-calling passthrough using a model with the ``tools``
        capability. ``messages``/``tools`` are OpenAI-style; returns the full
        assistant message dict (including any *unexecuted* ``tool_calls``),
        or ``None``. For server-executed tools use :meth:`run` instead."""

    # ---- low-level methods shared with the async REST endpoint ----

    def resolve_for(capability, model_override):
        """Return a configured model entry suitable for ``capability``.

        ``capability`` is the REST/API capability name (``chat``, ``think``,
        ``vision``, ``embed``, ``tools``). ``model_override`` is an optional
        model name to look up first. Returns ``None`` when no entry matches.

        Reads the plone registry — call from a request thread.
        """

    def run_call(capability, entry, data):
        """Execute a **tool-less** AI call against a pre-resolved ``entry``.

        ``data`` is the request payload (``prompt``/``system``/``image``/
        ``input``/``messages``/``tools`` as appropriate). Returns a result
        dict (``{"response": ...}`` or ``{"embedding": ...}``).

        Performs only outbound HTTP and never executes registered tools or
        touches Zope state — safe to call from a worker thread. The
        permission gate (if any) must have been checked by the caller.
        """
