"""Permission-gate helper for AI model entries.

When a model entry has ``protect_with_permission=true`` the caller must
hold at least one of ``entry["permissions"]`` on the call context. The
stored permission names are Plone permission *titles* (e.g. ``View``,
``Modify portal content``), which is what
:func:`AccessControl.SecurityManagement.getSecurityManager.checkPermission`
expects.
"""

from AccessControl import getSecurityManager
from collective.ai import logger


def entry_permits(entry: dict, context) -> bool:
    """Return ``True`` if the current user may call ``entry`` against
    ``context``. Always ``True`` when ``protect_with_permission`` is not
    enabled on the entry.
    """
    if not entry.get("protect_with_permission"):
        return True
    permissions = entry.get("permissions") or []
    if not permissions:
        # Toggle on but no permissions listed → deny by default; an entry
        # opted into protection should declare at least one allowed grant.
        logger.warning(
            "AI model entry %r has protect_with_permission=true but no "
            "permissions configured; denying.",
            entry.get("model") or entry.get("url"),
        )
        return False
    sm = getSecurityManager()
    return any(sm.checkPermission(perm, context) for perm in permissions)
