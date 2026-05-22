# collective.ai

Connect your AI models to Plone — the backend (Python) half.

This Plone addon registers a control panel, a global utility, and a
small family of REST API endpoints that let a Plone site talk to one
or more OpenAI-compatible LLM services.

The addon works on classic Plone as well as Volto. For the Volto-side
UI integration see [`../frontend/README.md`](../frontend/README.md).

## Features

- **AI Settings control panel** under *Site Setup → General*, exposed
  on both classic Plone (`@@ai-settings`) and Volto
  (`@controlpanels/ai-settings`). Both UIs edit the same
  registry-backed JSON list.
- **`IAIService` global utility** with methods for chat, reasoning,
  vision, embeddings, and tool/function calls.
- **Async `@ai` REST endpoint** with a polling counterpart
  `@ai-task/<id>` so calls that take minutes don't hit proxy /
  load-balancer timeouts.
- **Capability-based model resolution** (`completion`, `embedding`,
  `vision`, `tools`, `thinking`) — callers ask for *what they need*;
  the addon picks the right configured model.
- **Per-model permission gating** so individual models can be
  restricted to particular roles via Plone permissions.
- **Generic passthrough connections** — declare an endpoint without
  pinning any model and let callers ask for any model name the
  upstream service hosts.

## Installation

Add the package to your Plone installation. For development:

```shell
uv add collective.ai
```

Then install the addon profile via *Site Setup → Add-ons* (or by
adding `collective.ai:default` to the site creation profile list).

## Configuration

Open *Site Setup → AI Settings*. The registry stores a list of
*connections*, each holding one URL + optional API key and zero or
more pinned models.

### JSON shape

The control panel renders this shape (mirrored on Volto via the
custom widget; in classic Plone via the z3c.form `AIModelsWidget`):

```jsonc
[
  {
    "url": "http://localhost:11434",        // required
    "api_key": "",                          // optional
    "models": [
      {
        "model": "llama3.2",                // required when present
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
    "models": []      // ← empty list = generic passthrough
  }
]
```

Connections and models are both **ordered**; the first match wins
during resolution. The classic widget supports drag-and-drop
reordering at both scopes.

### Capabilities vocabulary

The token strings in `capabilities` are tracked by the
`collective.ai.Capabilities` named vocabulary (defined in
[vocabularies/capabilities.py](src/collective/ai/vocabularies/capabilities.py)).
They match the strings Ollama returns from `/api/show`, so the
widget can auto-detect a model's capabilities when it's selected.

| Token        | Use                                       |
| ------------ | ----------------------------------------- |
| `completion` | Chat / text completion                    |
| `embedding`  | Text embeddings (`/v1/embeddings`)        |
| `vision`     | Image understanding                       |
| `tools`      | Function calling / tool use               |
| `thinking`   | Reasoning / chain-of-thought models       |

### Permission gate

A model with `protect_with_permission=true` is only usable if the
current user holds **at least one** of the Plone permission titles
listed in `permissions` (e.g. `"View"`, `"Modify portal content"`,
`"Manage portal"`) on the call's context. The check is
[permissions.entry_permits](src/collective/ai/permissions.py) which
in turn calls `AccessControl.getSecurityManager().checkPermission`.

Generic-passthrough connections cannot be gated per-model (they have
no per-model entries).

## Using the addon

### From Python — the `IAIService` utility

```python
from collective.ai.interfaces import IAIService
from zope.component import queryUtility

service = queryUtility(IAIService)

# Chat completion — uses the first model whose capabilities include "completion"
text = service.chat("Summarise this article: …")

# System prompt
text = service.chat("Summarise this article: …", system="You are a helpful editor.")

# Pin an explicit model — must be configured somewhere
text = service.chat("…", model="llama3.1:70b")

# Vision
caption = service.analyze_image(
    "Describe this picture",
    "https://…/photo.jpg",  # URL the AI service can fetch, or a data: URI
)

# Embeddings — single string in, single vector out
vec = service.embed("Hello world")

# Reasoning model
answer = service.think("Walk me through this proof: …")

# Tool / function calling — returns the full assistant message dict
reply = service.tool_call(
    messages=[{"role": "user", "content": "…"}],
    tools=[{"type": "function", "function": {…}}],
)

# Permission-gated call: pass context= so the gate evaluates against
# the right object. Defaults to the portal root if omitted.
text = service.chat("…", context=self.context)
```

All methods return `None` when no matching model is configured or
when the permission gate denies the call (the denial is logged at
INFO level). Network and parsing failures are logged at WARNING
level and also return `None`.

### From Python — lower-level helpers

If you want to drive HTTP yourself but still let the addon pick the
right connection:

```python
from collective.ai.utils import resolve_model

entry = resolve_model("completion", override=None)
# entry is a flat dict: {url, api_key, model, capabilities,
#                        protect_with_permission, permissions}
if entry is None:
    ...
```

For the actual HTTP calls, [`client.py`](src/collective/ai/client.py)
exposes `chat_completion`, `chat_completion_message` (full assistant
message), and `embeddings`. The utility uses these internally.

### From HTTP / Volto — the `@ai` endpoint

The endpoint is async because individual model calls can take minutes,
which exceeds typical proxy timeouts. The request enqueues a worker
thread and returns a task id immediately; the client polls.

```http
POST /Plone/<path>/++api++/@ai
Accept: application/json
Content-Type: application/json

{
  "capability": "chat",
  "prompt": "Summarise …",
  "system": "You are a helpful editor.",
  "model": "llama3.1:70b"
}
```

Response (HTTP 202):

```json
{ "task_id": "1244133e-7506-…", "status": "running" }
```

Then poll:

```http
GET /Plone/<path>/++api++/@ai-task/1244133e-7506-…
Accept: application/json
```

```jsonc
{
  "task_id": "1244133e-7506-…",
  "status": "done",            // or "running" | "error"
  "started_at": 1779291357.7,
  "finished_at": 1779291488.8,
  "result": { "response": "…" }
}
```

The endpoint is registered for `IDexterityContent` (so the URL can
be rooted at any content item including the site root) with the
`zope2.View` permission. The matched model's permission gate is
evaluated against `self.context`; on denial the endpoint returns
HTTP 403.

#### Body shapes per capability

| `capability` | required body                                | optional   | `result` key  |
| ------------ | -------------------------------------------- | ---------- | ------------- |
| `chat`       | `prompt`                                     | `system`   | `response`    |
| `think`      | `prompt`                                     | `system`   | `response`    |
| `vision`     | `prompt`, `image` (URL or `data:` URI)       | —          | `response`    |
| `embed`      | `input` (string or list of strings)          | —          | `embedding`   |
| `tools`      | `messages` (array), `tools` (array)          | —          | `response`    |

All variants accept an optional top-level `model` to override
capability-based selection.

### Helper endpoints (for control-panel widgets)

These endpoints power the model-list and capability-detection
behavior in the AI Settings widget; they're useful from any client
that needs to introspect the upstream service:

- `POST /++api++/@ai-list-models` — body `{url, api_key?}` → returns
  `{models: [...]}`. Calls `/v1/models` on the supplied URL. Permission:
  `cmf.ManagePortal`.
- `POST /++api++/@ai-model-capabilities` — body `{url, api_key?,
  model}` → returns `{capabilities: ["completion", …]}`. Calls
  `/api/show` (Ollama) for the model; falls back to `/v1/models`
  metadata. Permission: `cmf.ManagePortal`.

### From a Plone event subscriber

Subscribers that want to invoke the AI on content events should pass
the content object as `context` so the permission gate evaluates
correctly:

```python
from collective.ai.interfaces import IAIService
from zope.component import queryUtility

def my_subscriber(obj, event):
    service = queryUtility(IAIService)
    if service is None:
        return
    result = service.chat("…", context=obj)
```

## Module reference

Where to look when you need to find / change something:

| Concern                                | File                                                                 |
| -------------------------------------- | -------------------------------------------------------------------- |
| Registry schema (JSON shape) + `IAIService` interface | [interfaces.py](src/collective/ai/interfaces.py)                     |
| Capability resolution (overrides, passthrough, etc.) | [utils.py](src/collective/ai/utils.py)                               |
| Permission gate                        | [permissions.py](src/collective/ai/permissions.py)                   |
| `IAIService` implementation            | [service.py](src/collective/ai/service.py)                           |
| Low-level HTTP (chat/embed/etc.)       | [client.py](src/collective/ai/client.py)                             |
| Async REST endpoint `@ai`              | [services/ai.py](src/collective/ai/services/ai.py)                   |
| Task polling endpoint `@ai-task`       | [services/task_status.py](src/collective/ai/services/task_status.py) |
| Task registry (in-memory)              | [services/tasks.py](src/collective/ai/services/tasks.py)             |
| Helper REST: list models               | [services/list_models.py](src/collective/ai/services/list_models.py) |
| Helper REST: model capabilities        | [services/model_capabilities.py](src/collective/ai/services/model_capabilities.py) |
| Capabilities vocabulary                | [vocabularies/capabilities.py](src/collective/ai/vocabularies/capabilities.py) |
| Helper: query `/v1/models`             | [vocabularies/models.py](src/collective/ai/vocabularies/models.py)   |
| Classic Plone form + Volto REST adapter | [controlpanels/ai.py](src/collective/ai/controlpanels/ai.py)        |
| Classic z3c.form widget for the JSONField | [controlpanels/widgets.py](src/collective/ai/controlpanels/widgets.py) |
| Classic widget template                | [controlpanels/templates/ai_models_widget.pt](src/collective/ai/controlpanels/templates/ai_models_widget.pt) |
| Classic widget JS                      | [static/ai-models-widget.js](src/collective/ai/static/ai-models-widget.js) |
| Classic widget CSS                     | [static/ai-models-widget.css](src/collective/ai/static/ai-models-widget.css) |

For internals and editing rules, see [AGENTS.md](./AGENTS.md).

## Contribute

- [Issue tracker](https://github.com/collective/collective-ai/issues)
- [Source code](https://github.com/collective/collective-ai/)

### Prerequisites

- An [operating system](https://6.docs.plone.org/install/create-project-cookieplone.html#prerequisites-for-installation) that runs all the requirements mentioned.
- [uv](https://6.docs.plone.org/install/create-project-cookieplone.html#uv)
- [Make](https://6.docs.plone.org/install/create-project-cookieplone.html#make)
- [Git](https://6.docs.plone.org/install/create-project-cookieplone.html#git)
- [Docker](https://docs.docker.com/get-started/get-docker/) (optional)

### Development setup

```shell
git clone git@github.com:collective/collective-ai.git
cd collective-ai/backend
make install
make create-site
make start
```

### Add features using `plonecli` or `bobtemplates.plone`

This package provides markers as strings (`<!-- extra stuff goes here -->`) that are compatible with [`plonecli`](https://github.com/plone/plonecli) and [`bobtemplates.plone`](https://github.com/plone/bobtemplates.plone).
These markers act as hooks to add all kinds of features through subtemplates, including behaviors, control panels, upgrade steps, or other subtemplates from `bobtemplates.plone`.

To add a feature as a subtemplate to your package, use the following command pattern.

```shell
make add <template_name>
```

For example:

```shell
make add content_type
make add behavior
```

```{seealso}
You can check the list of available subtemplates in the [`bobtemplates.plone` `README.md` file](https://github.com/plone/bobtemplates.plone/?tab=readme-ov-file#provided-subtemplates).
See also the documentation of [Mockup and Patternslib](https://6.docs.plone.org/classic-ui/mockup.html) for how to build the UI toolkit for Classic UI.
```

## License

The project is licensed under GPLv2.

## Credits and acknowledgements 🙏

Generated using [Cookieplone (2.0.0a2)](https://github.com/plone/cookieplone) and [cookieplone-templates (b0189a8)](https://github.com/plone/cookieplone-templates/commit/b0189a8ecb475bf5661a824bfefc5f07248654d4) on 2026-05-20 10:53:22.434266. A special thanks to all contributors and supporters!
