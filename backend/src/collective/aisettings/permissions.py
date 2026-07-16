"""Permission-gate helper for AI model entries.

An entry may declare two independent gates:

- ``only_for_authenticated=true`` requires the caller to be logged in
  (anonymous callers are denied); no specific permission is checked.
- ``protect_with_permission=true`` requires the caller to hold at least one
  of ``entry["permissions"]`` on the call context. The stored permission
  names are Plone permission *titles* (e.g. ``View``, ``Modify portal
  content``), which is what
  :func:`AccessControl.SecurityManagement.getSecurityManager.checkPermission`
  expects.

When both are enabled they combine with AND semantics.
"""

from AccessControl import getSecurityManager
from collective.aisettings import logger
from plone import api


def entry_permits(entry: dict, context) -> bool:
    """Return ``True`` if the current user may call ``entry`` against
    ``context``. Always ``True`` when no gate is enabled on the entry.
    """
    if entry.get("only_for_authenticated") and api.user.is_anonymous():
        logger.info(
            "AI model entry %r requires authentication; denying anonymous "
            "caller.",
            entry.get("model") or entry.get("url"),
        )
        return False
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
