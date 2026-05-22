from collective.ai import _
from collective.ai.controlpanels.widgets import AIModelsFieldWidget
from collective.ai.interfaces import IAISettings
from plone.app.registry.browser.controlpanel import ControlPanelFormWrapper
from plone.app.registry.browser.controlpanel import RegistryEditForm
from plone.restapi.controlpanels import RegistryConfigletPanel
from plone.z3cform import layout
from zope.component import adapter
from zope.interface import Interface


@adapter(Interface, Interface)
class AIControlpanel(RegistryConfigletPanel):
    """plone.restapi adapter exposing the AI settings to Volto via
    `@controlpanels/ai-settings`."""

    schema = IAISettings
    configlet_id = "ai-settings"
    configlet_category_id = "plone-general"
    schema_prefix = None


class AISettingsEditForm(RegistryEditForm):
    schema = IAISettings
    label = _("AI Settings")
    description = _("Configure the connection to the AI service.")

    def updateFields(self):
        super().updateFields()
        # Replace the default JSONField widget (a plain textarea) with the
        # rich row editor used in the Volto control panel.
        self.fields["models"].widgetFactory = AIModelsFieldWidget


AISettingsControlPanel = layout.wrap_form(
    AISettingsEditForm, ControlPanelFormWrapper
)
