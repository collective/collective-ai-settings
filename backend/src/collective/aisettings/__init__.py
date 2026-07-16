"""Init and utils."""

from zope.i18nmessageid import MessageFactory

import logging


__version__ = "1.3.0"

PACKAGE_NAME = "collective.aisettings"

_ = MessageFactory(PACKAGE_NAME)

logger = logging.getLogger(PACKAGE_NAME)
