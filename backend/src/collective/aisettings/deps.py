"""Dependencies passed into an agent run and exposed to tools.

Every tool-enabled :meth:`IAIService.run` builds one ``AIDeps`` and hands it
to ``agent.run_sync(..., deps=deps)``. Tools that take a
``RunContext[AIDeps]`` then reach the Plone context, request and the
captured security manager through ``ctx.deps``.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class AIDeps:
    """Plone-side dependencies available to AI tools during a run."""

    context: Any = None
    request: Any = None
    security_manager: Any = None
