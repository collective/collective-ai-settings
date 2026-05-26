import type { ConfigType } from '@plone/registry';
import ModelsWidget from '../components/ModelsWidget';
import '../components/ModelsWidget.scss';

export default function install(config: ConfigType) {
  // Control panel: render the `models` JSONField with our custom UI.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (config.widgets as any).id.models = ModelsWidget;

  return config;
}
