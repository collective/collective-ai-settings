# Collective AI 🚀

[![Built with Cookieplone](https://img.shields.io/badge/built%20with-Cookieplone-0083be.svg?logo=cookiecutter)](https://github.com/plone/cookieplone-templates/)
[![Black code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![CI](https://github.com/collective/collective-ai-settings/actions/workflows/main.yml/badge.svg)](https://github.com/collective/collective-ai-settings/actions/workflows/main.yml)

Connect your AI models to Plone.

`collective.aisettings` lets a Plone site talk to one or more OpenAI-compatible Large
Language Model services (Ollama, Lemonade, OpenAI, vLLM, etc.) from both
backend Python code and the Volto frontend, with per-model capability
declaration and permission gating.

## What you get

- A **registry-backed control panel** to declare AI connections and the models
  hosted on each — usable from both the classic Plone UI and Volto.
- A reusable **`IAIService` utility** so any Plone addon, view, subscriber,
  or block can perform `chat`, `think`, `analyze_image`, `embed`, or
  `tool_call` operations against the configured models.
- An asynchronous **`@ai` REST endpoint** that enqueues calls on a worker
  thread so long-running model invocations don't hit proxy/LB request
  timeouts, with a polling endpoint `@ai-task/<id>` for the result.
- **Capability-based resolution** (`completion`, `embedding`, `vision`,
  `tools`, `thinking`) so callers ask for *what they need* rather than for
  a specific model name. Callers can still pin a specific model name when
  they need to.
- **Per-model permission gating** with OR semantics over any number of
  Plone permissions, so e.g. expensive vision models can be restricted to
  Editors while text completion is available to everyone.
- **Generic passthrough connections** — declare an endpoint with no
  pinned models and let callers ask for any model name the upstream
  service hosts.

## Quick start 🏁

### Prerequisites ✅

- An [operating system](https://6.docs.plone.org/install/create-project-cookieplone.html#prerequisites-for-installation) that runs all the requirements mentioned.
- [uv](https://6.docs.plone.org/install/create-project-cookieplone.html#uv)
- [nvm](https://6.docs.plone.org/install/create-project-cookieplone.html#nvm)
- [Node.js and pnpm](https://6.docs.plone.org/install/create-project.html#node-js) 24
- [Make](https://6.docs.plone.org/install/create-project-cookieplone.html#make)
- [Git](https://6.docs.plone.org/install/create-project-cookieplone.html#git)
- [Docker](https://docs.docker.com/get-started/get-docker/) (optional)
- An OpenAI-compatible AI service reachable from the Plone backend. The
  default development assumption is a local [Ollama](https://ollama.com)
  install at `http://localhost:11434`.

### Installation 🔧

1. Clone this repository, then change your working directory.

    ```shell
    git clone git@github.com:collective/collective-ai-settings.git
    cd collective-ai-settings
    ```

2. Install this code base.

    ```shell
    make install
    ```

### Fire up the servers 🔥

1. Create a new Plone site on your first run.

    ```shell
    make backend-create-site
    ```

2. Start the backend at http://localhost:8080/.

    ```shell
    make backend-start
    ```

3. In a new shell session, start the frontend at http://localhost:3000/.

    ```shell
    make frontend-start
    ```

Voila! Your Plone site should be live and kicking 🎉

### Local stack deployment 📦

Deploy a local Docker Compose environment that includes the following.

- Docker images for Backend and Frontend 🖼️
- A stack with a Traefik router and a PostgreSQL database 🗃️
- Accessible at [http://collective-ai-settings.localhost](http://collective-ai-settings.localhost) 🌐

Run the following commands in a shell session.

```shell
make stack-create-site
make stack-start
```

## Configuring AI connections

After installing the addon on a Plone site, the **AI Settings** control panel
is registered under *Site Setup → General*. It supports both UIs:

- **Volto**: `http://localhost:3000/controlpanel/ai-settings`
- **Classic Plone**: `http://localhost:8080/Plone/@@ai-settings`

Both UIs render the same data structure (a single JSONField in the registry)
with a feature-equivalent rich editor.

### Data model

The control panel stores a list of *connections*. Each connection is one
remote AI service endpoint, and can optionally pin one or more *models* that
live behind that endpoint:

```jsonc
[
  {
    "url": "http://localhost:11434",
    "api_key": "",
    "models": [
      {
        "model": "llama3.2",
        "capabilities": ["completion", "tools"],
        "protect_with_permission": false,
        "permissions": []
      },
      {
        "model": "llava",
        "capabilities": ["vision"],
        "protect_with_permission": true,
        "permissions": ["Modify portal content"]
      }
    ]
  },
  {
    "url": "https://api.openai.com",
    "api_key": "sk-…",
    "models": []
  }
]
```

A connection with an empty `models` list is a **generic passthrough**: it
won't be picked by capability-based resolution, but it can serve any model
name that an `@ai` caller asks for explicitly.

### Environment-based configuration (connections file)

For deployments you often want to inject the endpoint, API key and models at
deploy time rather than clicking them into the ZODB — to keep secrets out of
the database and make the configuration reproducible. Set the environment
variable `COLLECTIVE_AISETTINGS_CONNECTIONS` to the **absolute path** of a
JSON file holding the *same* array of connections the control panel edits:

```jsonc
[
  {
    "url": "https://api.openai.com",
    "api_key_env": "OPENAI_API_KEY",   // read from the environment at load time
    "models": [
      { "model": "gpt-4o", "capabilities": ["completion", "vision", "tools"] },
      { "model": "text-embedding-3-small", "capabilities": ["embedding"] }
    ]
  },
  {
    "url": "http://localhost:11434",     // no key needed
    "models": []                          // generic passthrough
  }
]
```

Notes:

- **Same schema** as the control panel, plus one extra optional field per
  connection: **`api_key_env`** names an environment variable to read the key
  from, so the secret need not live in the file. When set and the variable is
  present it wins over any inline `api_key`; if the variable is unset it falls
  back to the inline `api_key` (and logs a warning).
- **File-first precedence.** File connections are merged *before* the
  registry ones, so on any overlap (same capability, or an explicitly named
  model) the file wins; registry connections still extend the set for
  capabilities/model names the file does not cover.
- **Live reload.** The file is re-read when its modification time changes —
  no restart needed — and otherwise cached.
- **Fail-safe.** A missing, unreadable, malformed or schema-invalid file is
  logged as an error and ignored; the site keeps running on the
  registry-configured connections.
- File-provided connections are **not** shown in the control panel; the panel
  only edits the registry-stored list.

### Resolution rules

When a caller asks for an AI operation, the addon walks the connections in
declared order and picks the first match:

- **Caller passes `model=X`** (an explicit model name):
  1. The first pinned model anywhere with `model == X` → that connection +
     that model definition.
  2. Otherwise the first generic-passthrough connection (empty `models`) →
     uses its URL/api key with `X` as the model name to send.
  3. Otherwise fail.
- **Caller passes no model**, just a capability:
  1. The first pinned model whose `capabilities` list contains the
     requested capability → use it.
  2. Otherwise fail. Generic-passthrough connections are skipped here
     because they declare no capability metadata.

The ordering of connections, and the ordering of models within a connection,
both matter. The UI supports drag-and-drop reordering at both scopes.

### Capabilities

Each pinned model can advertise zero or more capabilities. The vocabulary
mirrors the strings returned by [Ollama's `/api/show`
endpoint](https://github.com/ollama/ollama/blob/main/docs/api.md#show-model-information),
so the widget can auto-detect capabilities by querying the service:

| Token         | Description                                |
| ------------- | ------------------------------------------ |
| `completion`  | Chat / text completion                     |
| `embedding`   | Text embeddings (`/v1/embeddings`)         |
| `vision`      | Image understanding                        |
| `tools`       | Function calling / tool use                |
| `thinking`    | Reasoning / chain-of-thought models        |

### Permission gating

Each pinned model can opt in to **Protect with permission**. When enabled,
the call is only allowed if the current user holds **at least one** of the
listed Plone permission *titles* (e.g. `View`, `Modify portal content`,
`Manage portal`) on the call's context. The widget surfaces checkboxes for
the three common permissions and a free-text + add-button for custom ones,
with selected entries displayed as removable chips.

Generic passthrough connections cannot be gated per-model (they have no
per-model definitions).

## Using the AI from Python

Any Plone addon, browser view, event subscriber, or block can use the
registered global utility:

```python
from collective.aisettings.interfaces import IAIService
from zope.component import queryUtility

service = queryUtility(IAIService)

# Capability-based selection (uses the first configured model that
# advertises `completion`)
text = service.chat("Summarise this article: …")

# Pin a specific model by name
text = service.chat("Summarise …", model="llama3.1:70b")

# Vision model
description = service.analyze_image(
    "Describe the image", "https://…/photo.jpg",
)

# Embeddings (single string in, single vector out)
vector = service.embed("Hello world")

# Reasoning model
answer = service.think("Walk me through this proof: …")

# Tool / function calling — returns the full assistant message dict
reply = service.tool_call(messages, tools)

# Permission-gated call: pass `context=` to scope the check
text = service.chat("…", context=self.context)
```

When the resolved model has `protect_with_permission` on, the utility runs
the gate against `context` (defaulting to the portal root) and returns
`None` if denied, logging the denial.

See [backend/README.md](./backend/README.md) for the full Python API
reference.

## Using the AI from the Volto frontend (or any HTTP client)

The asynchronous REST endpoint accepts the same operations:

```http
POST /Plone/<path>/++api++/@ai
Content-Type: application/json
Accept: application/json

{
  "capability": "chat",         // chat | think | vision | embed | tools
  "prompt": "Summarise …",
  "model": "llama3.1:70b",       // optional; resolution falls back to capability
  "system": "You are a helpful editor."   // optional system instruction
}
```

The endpoint replies immediately with HTTP 202 and a task id:

```json
{ "task_id": "1244133e-…", "status": "running" }
```

The client then polls until the task is done:

```http
GET /Plone/<path>/++api++/@ai-task/<task_id>
```

```jsonc
{
  "task_id": "1244133e-…",
  "status": "done",
  "started_at": 1779291357.7,
  "finished_at": 1779291488.8,
  "result": { "response": "…" }
}
```

The endpoint is registered for any `IDexterityContent` (so the URL can be
rooted at the site or at any content item), with `zope2.View` as the
required permission. The permission gate on the matched model is checked
against the called context and returns HTTP 403 on denial.

Body shapes per capability:

| capability | required body fields              | optional      | result key  |
| ---------- | --------------------------------- | ------------- | ----------- |
| `chat`     | `prompt`                          | `system`      | `response`  |
| `think`    | `prompt`                          | `system`      | `response`  |
| `vision`   | `prompt`, `image`                 | —             | `response`  |
| `embed`    | `input` (string or list)          | —             | `embedding` |
| `tools`    | `messages` (array), `tools` (array) | —           | `response`  |

`image` may be either a URL the AI service can fetch or a `data:` URI.

See [frontend/README.md](./frontend/README.md) for the Volto-specific
integration.

## Project structure 🏗️

This monorepo consists of the following distinct sections:

- **backend/** — Plone addon `collective.aisettings`. Houses the registry schema,
  control-panel form, classic z3c.form widget, IAIService utility, async
  REST endpoint, capabilities vocabulary, and permission helpers. See
  [backend/README.md](./backend/README.md) and
  [backend/AGENTS.md](./backend/AGENTS.md).
- **frontend/** — Volto addon `volto-collective-ai-settings`. Houses the custom
  control-panel widget (`ModelsWidget`) that renders the connection /
  model UI in Volto. See [frontend/README.md](./frontend/README.md) and
  [frontend/AGENTS.md](./frontend/AGENTS.md).
- **devops/** — Docker stack, Ansible playbooks, cache settings.
- **docs/** — Scaffold for end-user documentation.

For agents working on this codebase, start at [AGENTS.md](./AGENTS.md).

## Code quality assurance 🧐

To check your code against quality standards, run the following shell command.

```shell
make check
```

### Format the codebase

To format and rewrite the code base, ensuring it adheres to quality standards,
run the following shell command.

```shell
make format
```

| Section  | Tool         | Description                              | Configuration |
| -------- | ------------ | ---------------------------------------- | ------------- |
| backend  | Ruff         | Python code formatting, imports sorting  | [`backend/pyproject.toml`](./backend/pyproject.toml) |
| backend  | `zpretty`    | XML and ZCML formatting                  | -- |
| frontend | ESLint       | Fixes most common frontend issues        | [`frontend/.eslintrc.js`](.frontend/.eslintrc.js) |
| frontend | prettier     | Format JS and TypeScript code            | [`frontend/.prettierrc`](.frontend/.prettierrc) |
| frontend | Stylelint    | Format styles (css, less, sass)          | [`frontend/.stylelintrc`](.frontend/.stylelintrc) |

Formatters can also be run within the `backend` or `frontend` folders.

### Lint the codebase

```shell
make lint
```

| Section  | Tool                    | Description                                | Configuration |
| -------- | ----------------------- | ------------------------------------------ | ------------- |
| backend  | Ruff                    | Checks code formatting, imports sorting    | [`backend/pyproject.toml`](./backend/pyproject.toml) |
| backend  | Pyroma                  | Checks Python package metadata             | -- |
| backend  | check-python-versions   | Checks Python version information          | -- |
| backend  | `zpretty`               | Checks XML and ZCML formatting             | -- |
| frontend | ESLint                  | Checks JS / TypeScript lint                | [`frontend/.eslintrc.js`](.frontend/.eslintrc.js) |
| frontend | prettier                | Check JS / TypeScript formatting           | [`frontend/.prettierrc`](.frontend/.prettierrc) |
| frontend | Stylelint               | Check styles (css, less, sass) formatting  | [`frontend/.stylelintrc`](.frontend/.stylelintrc) |

Linters can be run individually within the `backend` or `frontend` folders.

## Internationalization 🌐

Generate translation files for Plone and Volto with ease:

```shell
make i18n
```

## Credits and acknowledgements 🙏

Generated using [Cookieplone (2.0.0a2)](https://github.com/plone/cookieplone)
and [cookieplone-templates
(b0189a8)](https://github.com/plone/cookieplone-templates/commit/b0189a8ecb475bf5661a824bfefc5f07248654d4)
on 2026-05-20 10:53:22.434266. A special thanks to all contributors and
supporters!
