"""ZCA-based registry of AI tools an agent can call.

Other add-ons contribute tools either as **named utilities** providing
:class:`IAITool` (global, offered on every tool-enabled run) or as
:class:`IAIToolProvider` **subscription adapters** (context-aware). At call
time :func:`collect_tools` gathers both, drops tools the current user may not
use, and converts the survivors to ``pydantic_ai.Tool`` objects for the agent.

Subclass :class:`AITool`, declare ``parameters`` as a JSON Schema and override
:meth:`AITool.run`. Tools that prefer type-hint inference can override
:meth:`AITool.to_pydantic_tool` to return any ``pydantic_ai.Tool``.
"""

from AccessControl import getSecurityManager
from collective.aisettings import logger
from collective.aisettings.interfaces import IAITool
from collective.aisettings.interfaces import IAIToolProvider
from pydantic_ai import Tool
from zope.component import getUtilitiesFor
from zope.component import subscribers
from zope.interface import implementer


# A no-argument tool still needs a valid object schema for the model.
_EMPTY_SCHEMA = {"type": "object", "properties": {}}


@implementer(IAITool)
class AITool:
    """Base class for an AI tool. See :class:`IAITool`."""

    name: str = ""
    description: str = ""
    parameters: dict | None = None
    permission: str | None = None
    capabilities = None

    def available_for(self, context) -> bool:
        """Return ``True`` if the current user may use this tool against
        ``context`` (honours :attr:`permission`)."""
        if not self.permission:
            return True
        return bool(getSecurityManager().checkPermission(self.permission, context))

    def run(self, ctx, **kwargs):
        """Execute the tool. Override in subclasses."""
        raise NotImplementedError

    def _invoke(self, ctx, **kwargs):
        """pydantic-ai entry point: re-check the gate, then delegate to
        :meth:`run`. The gate is also applied at collection time; this guards
        against a context that changed mid-run."""
        context = getattr(ctx.deps, "context", None)
        if not self.available_for(context):
            return {"error": f"permission denied for tool {self.name!r}"}
        return self.run(ctx, **kwargs)

    def to_pydantic_tool(self) -> Tool:
        """Return the ``pydantic_ai.Tool`` wrapping this component."""
        return Tool.from_schema(
            self._invoke,
            name=self.name,
            description=self.description or self.name,
            json_schema=self.parameters or _EMPTY_SCHEMA,
            takes_ctx=True,
        )


def _iter_registered(context):
    """Yield every registered :class:`IAITool` for ``context`` — global named
    utilities plus context-aware provider subscribers."""
    for _name, tool in getUtilitiesFor(IAITool):
        yield tool
    if context is not None:
        for provider in subscribers((context,), IAIToolProvider):
            try:
                yield from provider.get_tools()
            except Exception:
                # take down the whole run.
                logger.exception("IAIToolProvider %r failed", provider)


def collect_tools(context, capability: str | None = None) -> list[Tool]:
    """Return the ``pydantic_ai.Tool`` list available for ``context``.

    Tools are filtered by their declared :attr:`~IAITool.capabilities` (when
    set) and the per-tool permission gate. Call from the request thread — the
    gate reads the current security manager.
    """
    tools: list[Tool] = []
    for tool in _iter_registered(context):
        caps = getattr(tool, "capabilities", None)
        if caps and capability and capability not in caps:
            continue
        if not tool.available_for(context):
            continue
        tools.append(tool.to_pydantic_tool())
    return tools
