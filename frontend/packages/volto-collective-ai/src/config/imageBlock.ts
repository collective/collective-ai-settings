import type { ConfigType } from '@plone/registry';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type IntlLike = { formatMessage?: (msg: any) => string };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toPlainString(value: any, intl?: IntlLike): any {
  if (value == null) return value;
  if (typeof value === 'string') return value;
  if (typeof value !== 'object') return String(value);

  // Standard react-intl message descriptor.
  if (typeof value.defaultMessage === 'string') {
    if (intl?.formatMessage && typeof value.id === 'string') {
      try {
        return intl.formatMessage(value);
      } catch {
        // fall through to defaultMessage
      }
    }
    return value.defaultMessage;
  }

  // Unknown object shape — return '' so PropTypes.string is satisfied. We
  // would rather drop a label than spam the console with prop-type warnings
  // on every render of the sidebar.
  return '';
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function stringifyLabels(obj: any, intl?: IntlLike): any {
  if (!obj || typeof obj !== 'object') return obj;
  return {
    ...obj,
    title: toPlainString(obj.title, intl),
    description: toPlainString(obj.description, intl),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeProperties(properties: any, intl?: IntlLike) {
  if (!properties || typeof properties !== 'object') return properties;
  const next: Record<string, unknown> = {};
  for (const key of Object.keys(properties)) {
    next[key] = stringifyLabels(properties[key], intl);
  }
  return next;
}

export function enhanceImageBlock(config: ConfigType) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const imageBlock = (config as any).blocks?.blocksConfig?.image;
  if (!imageBlock) return;

  const prior = imageBlock.schemaEnhancer;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  imageBlock.schemaEnhancer = (args: any) => {
    const baseSchema = prior ? prior(args) : args.schema;
    const intl = args?.intl as IntlLike | undefined;

    // Stringify titles/descriptions everywhere they can appear in the
    // schema so no widget downstream is handed a message-descriptor object.
    const next = {
      ...baseSchema,
      title: toPlainString(baseSchema.title, intl),
      description: toPlainString(baseSchema.description, intl),
      properties: normalizeProperties(baseSchema.properties, intl),
      fieldsets: (baseSchema.fieldsets || []).map(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (fieldset: any) => ({
          ...stringifyLabels(fieldset, intl),
          fields: [...fieldset.fields],
        }),
      ),
    };

    if (!next.properties.ai_image_meta) {
      next.properties.ai_image_meta = {
        title: 'AI assist',
        widget: 'ai_image_meta',
      };
    }

    const firstFieldset = next.fieldsets[0];
    if (firstFieldset && !firstFieldset.fields.includes('ai_image_meta')) {
      firstFieldset.fields.push('ai_image_meta');
    }

    return next;
  };
}
