"""z3c.form widget for editing :data:`IAISettings.models` in classic Plone.

The widget mirrors the Volto ``ModelsWidget``: a row per model with URL,
API key, model dropdown (populated by ``@ai-list-models``), capability
checkboxes (auto-filled by ``@ai-model-capabilities``), drag-and-drop
ordering and an Add/Remove pair. State is serialized to a single hidden
input as JSON; the converter turns that into the Python list the
``JSONField`` expects.
"""

from plone.schema import IJSONField
from Products.CMFCore.utils import getToolByName
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from z3c.form.browser.widget import addFieldClass
from z3c.form.browser.widget import HTMLFormElement
from z3c.form.converter import BaseDataConverter
from z3c.form.interfaces import IDataConverter
from z3c.form.interfaces import IFieldWidget
from z3c.form.interfaces import IFormLayer
from z3c.form.interfaces import IWidget
from z3c.form.widget import FieldWidget
from z3c.form.widget import Widget
from zope.component import adapter
from zope.interface import implementer
from zope.interface import implementer_only

import json


class IAIModelsWidget(IWidget):
    """Marker interface for :class:`AIModelsWidget`."""


@implementer_only(IAIModelsWidget)
class AIModelsWidget(HTMLFormElement, Widget):
    """Hidden-input-backed widget rendered by a Page Template + JS."""

    klass = "ai-models-widget"

    input_template = ViewPageTemplateFile("templates/ai_models_widget.pt")

    def update(self):
        super().update()
        addFieldClass(self)

    def render(self):
        return self.input_template(self)

    @property
    def json_value(self) -> str:
        if self.value is None or self.value == "":
            return "[]"
        if isinstance(self.value, str):
            return self.value
        try:
            return json.dumps(self.value)
        except (TypeError, ValueError):
            return "[]"

    @property
    def portal_url(self) -> str:
        return getToolByName(self.context, "portal_url")()


@adapter(IJSONField, IAIModelsWidget)
@implementer(IDataConverter)
class AIModelsDataConverter(BaseDataConverter):
    """JSON-string ↔ Python list/dict around an :class:`AIModelsWidget`."""

    def toWidgetValue(self, value):
        if value is None:
            return "[]"
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            return "[]"

    def toFieldValue(self, value):
        if value is None or value == "":
            return []
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []


@adapter(IJSONField, IFormLayer)
@implementer(IFieldWidget)
def AIModelsFieldWidget(field, request):
    return FieldWidget(field, AIModelsWidget(request))
