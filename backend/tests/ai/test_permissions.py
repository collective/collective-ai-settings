"""Tests for the model-entry permission gate (:mod:`permissions`)."""

from collective.aisettings.permissions import entry_permits
from plone.app.testing import login
from plone.app.testing import logout
from plone.app.testing import TEST_USER_NAME


class TestEntryPermits:
    def test_no_gate_permits_anonymous(self, portal):
        logout()
        assert entry_permits({"model": "m"}, portal) is True

    def test_only_for_authenticated_permits_logged_in(self, portal):
        login(portal, TEST_USER_NAME)
        entry = {"model": "m", "only_for_authenticated": True}
        assert entry_permits(entry, portal) is True

    def test_only_for_authenticated_denies_anonymous(self, portal):
        logout()
        entry = {"model": "m", "only_for_authenticated": True}
        assert entry_permits(entry, portal) is False

    def test_authenticated_gate_ignores_permissions(self, portal):
        """The authenticated gate never inspects the permissions list."""
        login(portal, TEST_USER_NAME)
        entry = {"model": "m", "only_for_authenticated": True, "permissions": []}
        assert entry_permits(entry, portal) is True

    def test_both_gates_require_both(self, portal):
        """Authenticated + permission gate combine with AND semantics."""
        logout()
        entry = {
            "model": "m",
            "only_for_authenticated": True,
            "protect_with_permission": True,
            "permissions": ["View"],
        }
        # Anonymous fails the authentication gate before any permission check.
        assert entry_permits(entry, portal) is False
        # Logged-in test user holds "View" on the portal root.
        login(portal, TEST_USER_NAME)
        assert entry_permits(entry, portal) is True
