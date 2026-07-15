"""Tests for ZCA-based tool registration and the permission gate."""

from collective.aisettings.interfaces import IAITool
from collective.aisettings.interfaces import IAIToolProvider
from collective.aisettings.tools import AITool
from collective.aisettings.tools import collect_tools
from zope.component import getGlobalSiteManager
from zope.interface import implementer

import pytest


class _Tool(AITool):
    name = "noop"
    description = "no-op"
    parameters = {"type": "object", "properties": {}}

    def run(self, ctx):
        return {}


class _ProtectedTool(_Tool):
    name = "protected"
    permission = "Manage portal"


class _ChatOnlyTool(_Tool):
    name = "chatonly"
    capabilities = ("chat",)


@implementer(IAIToolProvider)
class _Provider:
    """Context-aware provider yielding a single tool."""

    def __init__(self, context):
        self.context = context

    def get_tools(self):
        return [_Tool()]


@pytest.fixture()
def gsm():
    return getGlobalSiteManager()


class TestToolConversion:
    def test_to_pydantic_tool(self):
        tool = _Tool().to_pydantic_tool()
        assert tool.name == "noop"

    def test_empty_schema_default(self):
        # A tool with no parameters still produces a valid object schema.
        class Bare(AITool):
            name = "bare"

            def run(self, ctx):
                return {}

        assert Bare().to_pydantic_tool().name == "bare"


class TestCollectTools:
    def test_global_utility_collected(self, portal, gsm):
        tool = _Tool()
        gsm.registerUtility(tool, IAITool, name="noop")
        try:
            names = [t.name for t in collect_tools(portal)]
        finally:
            gsm.unregisterUtility(tool, IAITool, name="noop")
        assert "noop" in names

    def test_context_provider_collected(self, portal, gsm):
        gsm.registerSubscriptionAdapter(_Provider, (None,), IAIToolProvider)
        try:
            names = [t.name for t in collect_tools(portal)]
        finally:
            gsm.unregisterSubscriptionAdapter(_Provider, (None,), IAIToolProvider)
        assert "noop" in names

    def test_capability_filter(self, portal, gsm):
        tool = _ChatOnlyTool()
        gsm.registerUtility(tool, IAITool, name="chatonly")
        try:
            chat_names = [t.name for t in collect_tools(portal, capability="chat")]
            think_names = [t.name for t in collect_tools(portal, capability="think")]
        finally:
            gsm.unregisterUtility(tool, IAITool, name="chatonly")
        assert "chatonly" in chat_names
        assert "chatonly" not in think_names

    def test_permission_gate_filters(self, portal, gsm):
        tool = _ProtectedTool()
        gsm.registerUtility(tool, IAITool, name="protected")
        try:
            # The default test user is not a Manager on the portal.
            names = [t.name for t in collect_tools(portal)]
        finally:
            gsm.unregisterUtility(tool, IAITool, name="protected")
        assert "protected" not in names

    def test_permission_gate_allows_manager(self, portal, gsm, grant_roles):
        grant_roles(context=portal, roles=["Manager"])
        tool = _ProtectedTool()
        gsm.registerUtility(tool, IAITool, name="protected")
        try:
            names = [t.name for t in collect_tools(portal)]
        finally:
            gsm.unregisterUtility(tool, IAITool, name="protected")
        assert "protected" in names
