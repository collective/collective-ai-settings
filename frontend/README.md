# Collective AI (volto-collective-ai)

Connect your AI models to Plone — the Volto frontend half.

[![npm](https://img.shields.io/npm/v/volto-collective-ai)](https://www.npmjs.com/package/volto-collective-ai)
[![](https://img.shields.io/badge/-Storybook-ff4785?logo=Storybook&logoColor=white&style=flat-square)](https://collective.github.io/volto-collective-ai/)
[![CI](https://github.com/collective/collective-ai/actions/workflows/main.yml/badge.svg)](https://github.com/collective/collective-ai/actions/workflows/main.yml)

`volto-collective-ai` is the Volto add-on that ships the
control-panel editor for the `collective.ai` Plone addon. The
backend half exposes the data model and the REST API; this package
provides the Volto UI that drives them.

For the cross-cutting picture — what the product does, the data
model, the REST endpoints — see [`../README.md`](../README.md). For
the backend Plone addon, see
[`../backend/README.md`](../backend/README.md).

## Features

- **Custom Volto control-panel widget (`ModelsWidget`)** that drives
  the `IAISettings.models` JSONField. Renders the nested
  connection-then-models structure with:
  - Connection cards (URL + optional API key) with drag-and-drop
    reordering.
  - Pinned-model cards nested under each connection, also with
    drag-and-drop reordering within the connection.
  - Per-model capability checkboxes whose options come from the
    backend `collective.ai.Capabilities` vocabulary.
  - Auto-detection of a model's capabilities when it's selected from
    the dropdown (via the `@ai-model-capabilities` REST helper).
  - Per-model permission gate: a toggle plus checkboxes for common
    Plone permissions (`View`, `Modify portal content`, `Add portal
    content`) plus a free-text + add-button for arbitrary
    permission titles, with selected items shown as removable chips.

## Installation

Choose the method appropriate to your version of Volto.

### Volto 18 and later

Add `volto-collective-ai` to your `package.json`.

```json
"dependencies": {
    "volto-collective-ai": "*"
}
```

Add the add-on to your `volto.config.js`.

```javascript
const addons = ['volto-collective-ai'];
```

### Volto 17 and earlier

```shell
npm install -g yo @plone/generator-volto
yo @plone/volto my-volto-project --addon volto-collective-ai
cd my-volto-project
```

Add `volto-collective-ai` to your `package.json`.

```json
"addons": [
    "volto-collective-ai"
],

"dependencies": {
    "volto-collective-ai": "*"
}
```

Install and start.

```shell
yarn install
yarn start
```

## Configuring AI connections

After installing both the Plone backend addon (`collective.ai`) and
this Volto addon, the **AI Settings** control panel appears under
*Site Setup → General*.

URL: `/controlpanel/ai-settings` on the Volto frontend.

The widget edits the same registry-backed JSON list that the classic
Plone control panel does. See [the root
README](../README.md#configuring-ai-connections) for the data shape,
resolution rules, and permission gate semantics.

## Calling the AI from a Volto addon or block

This Volto package does **not** ship a hook or component for
invoking the AI from your own code. Use `fetch` (or your preferred
HTTP client) against the same REST API that the backend exposes:

```ts
async function startAITask(payload: Record<string, unknown>): Promise<string> {
  const response = await fetch('/++api++/@ai', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`AI request failed: HTTP ${response.status}`);
  }
  const data = (await response.json()) as { task_id: string };
  return data.task_id;
}

async function pollAITask(taskId: string): Promise<unknown> {
  while (true) {
    const response = await fetch(`/++api++/@ai-task/${taskId}`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Poll failed: HTTP ${response.status}`);
    const data = (await response.json()) as {
      status: 'running' | 'done' | 'error';
      result?: unknown;
      error?: string;
    };
    if (data.status === 'done') return data.result;
    if (data.status === 'error') throw new Error(data.error ?? 'AI task failed');
    await new Promise((r) => setTimeout(r, 5000));
  }
}
```

Example invocations:

```ts
// Chat completion with capability-based selection
const taskId = await startAITask({
  capability: 'chat',
  prompt: 'Summarise this article: …',
});
const result = await pollAITask(taskId);
// result === { response: '…' }

// Vision with an explicit data: URI (works for any data the browser can fetch)
const taskId = await startAITask({
  capability: 'vision',
  prompt: 'Describe this image',
  image: 'data:image/jpeg;base64,…',
});

// Embeddings
const taskId = await startAITask({
  capability: 'embed',
  input: 'Hello world',
});
// result.embedding is a vector

// Pinning a model by name (skips capability-based resolution)
const taskId = await startAITask({
  capability: 'chat',
  prompt: '…',
  model: 'llama3.1:70b',
});
```

The endpoint is registered for `IDexterityContent` (any content
item), with `zope2.View` as the required permission. The matched
model's permission gate is checked against the called URL's context
— if the user lacks the required permissions there, the call
returns HTTP 403.

For the full body shapes, response keys, and behavior, see
[`../backend/README.md`](../backend/README.md).

## Test installation

Visit `http://localhost:3000/` in a browser, log in as Manager, and
open *Site Setup → AI Settings*. Add a connection (e.g. a local
Ollama at `http://localhost:11434`), add one or more pinned models,
save, and verify the JSON in the registry round-trips.

## Development

The development of this add-on is done in isolation using pnpm
workspaces, the latest `mrs-developer`, and other Volto core
improvements. For these reasons, it only works with pnpm and
Volto 18.

### Prerequisites

- An [operating system](https://6.docs.plone.org/install/create-project-cookieplone.html#prerequisites-for-installation) that runs all the requirements mentioned.
- [nvm](https://6.docs.plone.org/install/create-project-cookieplone.html#nvm)
- [Node.js and pnpm](https://6.docs.plone.org/install/create-project.html#node-js) 24
- [Make](https://6.docs.plone.org/install/create-project-cookieplone.html#make)
- [Git](https://6.docs.plone.org/install/create-project-cookieplone.html#git)
- [Docker](https://docs.docker.com/get-started/get-docker/) (optional)

### Set up

```shell
git clone git@github.com:collective/collective-ai.git
cd collective-ai/frontend
make install
```

### Start developing

Start the backend (in a Docker container that ships the
`collective.ai` Python addon pre-installed):

```shell
make backend-docker-start
```

In a separate terminal session, start the Volto dev server:

```shell
make start
```

### Source layout

```
frontend/
├── packages/volto-collective-ai/
│   └── src/
│       ├── index.ts                      ← Volto applyConfig entry
│       ├── config/settings.ts            ← widget + block registration
│       └── components/
│           ├── ModelsWidget.tsx          ← control-panel widget
│           └── ModelsWidget.scss         ← matching styles
├── core/                                  ← vendored Volto core (read-only)
├── cypress/                               ← acceptance tests
├── volto.config.js                        ← workspace addon list
└── mrs.developer.json                     ← extra checkouts
```

For internals, conventions, and the contracts with the backend, see
[`AGENTS.md`](./AGENTS.md).

### Make convenience commands

Run `make help` to list available Make commands. Common ones:

```shell
make install      # install workspace deps
make start        # run Volto dev server (after backend is running)
make lint         # ESLint, Prettier, Stylelint in check mode
make format       # the same, in fix mode
make i18n         # extract translatable strings
make test         # unit tests (vitest)
```

### Cypress acceptance tests

Run each in a separate terminal:

```shell
make acceptance-frontend-dev-start
make acceptance-backend-start
make acceptance-test
```

## License

The project is licensed under the MIT license.
