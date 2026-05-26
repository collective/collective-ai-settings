# AGENTS.md — frontend

Agent guide for the `volto-collective-ai-settings` Volto addon
(`frontend/packages/volto-collective-ai-settings/`). For the cross-cutting
picture of how this half talks to the Plone backend, read
[`../AGENTS.md`](../AGENTS.md) first.

## Scope

- The product addon: `frontend/packages/volto-collective-ai-settings/src/`
- Workspace plumbing at the repo root: `package.json`,
  `pnpm-workspace.yaml`, `volto.config.js`, `mrs.developer.json`

**Out of scope:**

- `frontend/core/` is a vendored copy of Volto core with its own
  `AGENTS.md`. Treat it as read-only; never modify it as part of an
  addon change.

## Package layout

```
frontend/packages/volto-collective-ai-settings/
├── package.json
├── src/
│   ├── index.ts                 ← applyConfig entry — calls install(config)
│   ├── config/
│   │   └── settings.ts          ← widget registration (config.widgets.id.models)
│   └── components/
│       ├── ModelsWidget.tsx     ← the only product UI
│       └── ModelsWidget.scss    ← styles for it
├── locales/                     ← .po files (Volto i18n)
├── babel.config.js
├── tsconfig.json
├── vitest.config.mjs
└── CHANGELOG.md
```

## What this addon ships

Exactly one feature: the **`ModelsWidget`** that drives the
`IAISettings.models` JSONField on the AI Settings control panel in
Volto. It mirrors, feature-for-feature, the classic z3c.form widget
on the Plone side (`backend/src/collective/aisettings/static/ai-models-widget.js`);
when the contract changes, both must change.

It is registered against the field id `models` in
[`src/config/settings.ts`](packages/volto-collective-ai-settings/src/config/settings.ts):

```ts
(config.widgets as any).id.models = ModelsWidget;
```

The widget reads/writes the same nested JSON described in
[`../README.md`](../README.md#data-model):

```jsonc
[
  { "url": "…", "api_key": "…",
    "models": [{ "model": "…", "capabilities": ["…"],
                 "protect_with_permission": false, "permissions": ["…"] }]
  }
]
```

## Key contracts with the backend

These are the only seams this widget cares about. If you change one,
update the matching backend symbol in the same PR (see
[`../backend/AGENTS.md`](../backend/AGENTS.md)).

| Contract                                | Where it's defined (backend)                                              | Where it's consumed (frontend)               |
| --------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------- |
| Registry JSON shape                     | `interfaces.py` → `MODEL_JSON_SCHEMA`                                     | `ModelsWidget.tsx` (TypeScript types)        |
| Capabilities vocabulary                 | `vocabularies/capabilities.py` (REST: `/@vocabularies/collective.aisettings.Capabilities`) | `ModelsWidget.tsx` — `apiFetch('/@vocabularies/…')` |
| Model list per URL                      | `services/list_models.py` (REST: `/@ai-list-models`)                      | `ModelsWidget.tsx` — `loadModels`            |
| Per-model capability auto-detect        | `services/model_capabilities.py` (REST: `/@ai-model-capabilities`)        | `ModelsWidget.tsx` — `handleModelChange`     |
| Async `@ai` endpoint (chat/vision/etc.) | `services/ai.py`                                                          | (consumed by addon callers via `fetch`)      |

## Widget internals (`ModelsWidget.tsx`)

### State
- `connections` — derived from the `value` prop via `parseValue`.
  Always the source of truth for what gets saved.
- `connectionsRef` — a `useRef` mirror used inside the async
  `handleModelChange` so the response of the slow
  `@ai-model-capabilities` call updates the *latest* form state, not
  the snapshot captured when the request was sent.
- `capabilities` — the vocabulary, loaded once on mount.
- `modelsByUrl` — per-URL cache: `{ loading, items, error? }`.
  Populated lazily when a connection has ≥1 pinned models (we don't
  bother fetching for passthrough-only connections).
- Drag state — two pairs of indices, one for connection-level drag
  and one for model-level drag-within-connection. Model drag
  handlers `e.stopPropagation()` so they don't bubble up to the
  connection drop target.
- `permDrafts` — keyed `<connIndex>:<modelIndex>` so each model card
  has its own custom-permission input state.

### Drag-and-drop rules
- Each connection card has its own `dragstart`/`dragover`/`drop`/
  `dragend` handlers; same for each model card.
- The connection-level handlers refuse to fire while `modelDrag !==
  null` so dragging a model inside a connection never accidentally
  moves the connection.
- We do not re-render during drag — visual feedback (`.is-dragging`
  / `.is-drop-target`) is applied via React class names; only `drop`
  triggers a `onChange` that re-renders.
- The drop index math: `targetIndex = from < to ? to - 1 : to`. This
  lands the row where the cursor is, with the rest of the list
  closing in behind it.
- Cross-connection model drag is not supported (intentional). It
  would make the drop target ambiguous and there's no UX need yet.

### Async + stale-state guard
`handleModelChange` updates the model name immediately (so the
dropdown is responsive), then calls `@ai-model-capabilities` and
asynchronously overwrites the row's `capabilities` if the response
is non-empty. Before overwriting it re-checks `connectionsRef.current`
to make sure the user didn't pick a different model in the meantime.

### Persistence
The Volto form passes `onChange(id, value)` where `value` is the
new connections array. We always rebuild the array immutably (no
in-place mutation) so React-Redux selectors notice the change. The
form state ends up at `state.form.global.models`; the control panel
save button sends it back to the registry through plone.restapi.

## Where to look when you need to change something

| You want to…                                       | Look at                                                            |
| -------------------------------------------------- | ------------------------------------------------------------------ |
| Change which Plone permissions appear as checkboxes | `COMMON_PERMISSIONS` in `ModelsWidget.tsx`                         |
| Add a new field to the model JSON                   | Type `ModelDef`, `EMPTY_MODEL`, and the rendering JSX. **Also** update the backend schema and `utils._flatten`. |
| Add a new field to the connection JSON              | Type `Connection`, `EMPTY_CONNECTION`, and the connection-level rendering. **Also** update the backend schema. |
| Change the drag-and-drop UX                         | `onConnDrag*` and `onModelDrag*` callbacks + `.is-dragging` / `.is-drop-target` styles in `ModelsWidget.scss` |
| Add a new capability checkbox                       | No frontend change needed — the list comes from the backend vocabulary at runtime. Add the token on the backend (see `../backend/AGENTS.md`). |
| Wire a new REST endpoint into the widget            | Add an `apiFetch` call. URLs are relative to `/++api++/…` — the dev server proxies that to Plone. |

## Validation commands

```sh
# From frontend/
make install
make backend-docker-start     # Plone backend in Docker on :8080
make start                    # Volto dev server on :3000 (separate shell)

make lint                     # ESLint + Prettier + Stylelint check
make format                   # …in fix mode
make i18n                     # extract translatable strings
make test                     # vitest unit tests

# Cypress acceptance (each in its own shell)
make acceptance-frontend-dev-start
make acceptance-backend-start
make acceptance-test
```

Prefer the package-scoped variants when iterating:

```sh
pnpm --filter volto-collective-ai-settings <script>
```

## Editing rules

- Read this file, [`../AGENTS.md`](../AGENTS.md), and (if the change
  touches the REST contract) [`../backend/AGENTS.md`](../backend/AGENTS.md)
  before editing.
- This addon ships **one** widget. New product features that touch
  the data model should land in `ModelsWidget.tsx`, with the matching
  changes in `backend/src/collective/aisettings/static/ai-models-widget.js`
  (the classic-Plone equivalent) and `interfaces.py`.
- Don't introduce new top-level addons or duplicate Volto core
  functionality. If something doesn't fit into the existing widget /
  config registration scheme, propose it in an issue first.
- Don't write to `frontend/core/`. Volto core has its own `AGENTS.md`
  and release cadence; we vendor it via `mrs-developer` for local
  dev only.
- TypeScript is the convention for everything new under `src/`.
  `react-redux` and `react` come transitively via the Volto workspace;
  IDE warnings about missing modules are false positives when ESLint
  isn't pointed at the workspace node_modules.

## Releasing

The addon publishes independently on npm as `volto-collective-ai-settings`.
Use the existing release-it config (`.release-it.json` in
`packages/volto-collective-ai-settings/`); don't write your own release
automation. Keep `CHANGELOG.md` updated via towncrier entries in
`news/`.
