from collective.aisettings.utils import CONNECTIONS_ENV
from collective.aisettings.utils import file_connections_display
from plone.restapi.services import Service


class AIFileConnections(Service):
    """Report whether AI connections are managed by an environment file.

    GET @ai-file-connections returns::

        {
            "active": true,
            "env_var": "COLLECTIVE_AISETTINGS_CONNECTIONS",
            "connections": [ ...secret-free connection dicts... ]
        }

    ``active`` is true only when ``COLLECTIVE_AISETTINGS_CONNECTIONS`` is set
    *and* the file was read and validated without errors — the control panels
    use this both as a load-confirmation and to render the connections
    read-only. API keys are never exposed: an ``api_key_env`` reference is
    surfaced as its variable name only; an inline key becomes an
    ``api_key_set`` boolean.
    """

    def reply(self):
        connections = file_connections_display()
        if connections is None:
            return {"active": False, "env_var": CONNECTIONS_ENV, "connections": []}
        return {
            "active": True,
            "env_var": CONNECTIONS_ENV,
            "connections": connections,
        }
