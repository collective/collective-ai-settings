# collective.aisettings

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
- **`IAIService` global utility**, backed by
  [pydantic-ai](https://ai.pydantic.dev), with methods for chat,
  reasoning, vision, embeddings, structured output, and tool calls.
- **Pluggable tools** — other add-ons register `IAITool` utilities or
  `IAIToolProvider` adapters that the agent auto-executes during a call.
- **`@ai` REST endpoint** (sync by default) with a polling counterpart
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
uv add collective.aisettings
```

Then install the addon profile via *Site Setup → Add-ons* (or by
adding `collective.aisettings:default` to the site creation profile list).

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
`collective.aisettings.Capabilities` named vocabulary (defined in
[vocabularies/capabilities.py](src/collective/aisettings/vocabularies/capabilities.py)).
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
[permissions.entry_permits](src/collective/aisettings/permissions.py) which
in turn calls `AccessControl.getSecurityManager().checkPermission`.

Generic-passthrough connections cannot be gated per-model (they have
no per-model entries).

## Using the addon

### From Python — the `IAIService` utility

```python
from collective.aisettings.interfaces import IAIService
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

# Structured output — pass a pydantic model (or any type) as output_type
from pydantic import BaseModel

class Article(BaseModel):
    title: str
    tags: list[str]

article = service.chat("Extract metadata from: …", output_type=Article)
# -> an Article instance

# Server-executed tools: chat/think/analyze_image run a pydantic-ai agent
# that auto-executes every tool registered by add-ons (see "Registering
# tools" below). Pass use_tools=False to disable.
text = service.chat("What's the weather in Rosario?", context=self.context)
text = service.chat("…", use_tools=False)

# Raw function-calling passthrough — returns the full assistant message dict
# with *unexecuted* tool_calls for you to run yourself.
reply = service.tool_call(
    messages=[{"role": "user", "content": "…"}],
    tools=[{"type": "function", "function": {…}}],
)

# Permission-gated call: pass context= so the gate evaluates against
# the right object. Defaults to the portal root if omitted.
text = service.chat("…", context=self.context)
```

`chat`, `think` and `analyze_image` accept `output_type=` (structured
output), `use_tools=` (default `True`) and `request=` (made available to
tools). They delegate to the generic `service.run(prompt, capability=…)`.

All methods return `None` when no matching model is configured or
when the permission gate denies the call (the denial is logged at
INFO level). Network failures are logged at WARNING level and also
return `None`.

### From Python — lower-level helpers

If you want to drive HTTP yourself but still let the addon pick the
right connection:

```python
from collective.aisettings.utils import resolve_model

entry = resolve_model("completion", override=None)
# entry is a flat dict: {url, api_key, model, capabilities,
#                        protect_with_permission, permissions}
if entry is None:
    ...
```

Chat/think/vision go through [pydantic-ai](https://ai.pydantic.dev)
models built in [`models.py`](src/collective/aisettings/models.py)
(`build_model(entry)`). For the bits pydantic-ai does not cover,
[`client.py`](src/collective/aisettings/client.py) exposes `embeddings`
and `raw_tool_call` on top of the OpenAI SDK.

### Registering tools (other add-ons)

`chat`/`think`/`analyze_image` run an agent that can call tools your
add-on contributes through the component architecture. Subclass
`AITool`, declare a JSON-Schema for the arguments and implement `run`:

```python
from collective.aisettings.tools import AITool

class WeatherTool(AITool):
    name = "get_weather"
    description = "Return the current weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
    permission = "View"          # optional Plone permission gate (title)
    capabilities = ("chat",)     # optional; default = all tool-enabled runs

    def run(self, ctx, city):
        # ctx.deps is an AIDeps with .context / .request / .security_manager
        portal = ctx.deps.context
        return {"city": city, "temp_c": 21}
```

Register it as a **named utility** (global, offered on every run):

```xml
<utility
    factory=".tools.WeatherTool"
    provides="collective.aisettings.interfaces.IAITool"
    name="get_weather"
    />
```

For tools whose availability depends on the content object the call is
rooted at, register an `IAIToolProvider` **subscription adapter** that
yields tools per context:

```python
from collective.aisettings.interfaces import IAIToolProvider
from zope.interface import implementer

@implementer(IAIToolProvider)
class MyContextTools:
    def __init__(self, context):
        self.context = context

    def get_tools(self):
        return [WeatherTool()] if IMyType.providedBy(self.context) else []
```

```xml
<subscriber
    provides="collective.aisettings.interfaces.IAIToolProvider"
    for="*"
    factory=".tools.MyContextTools"
    />
```

Tools are filtered by their `capabilities` and the `permission` gate
before being offered to the model. Because tools execute inside the
agent loop (touching Plone security and the ZODB), tool-enabled runs
happen in the request thread — see the async note below.

### From HTTP / Volto — the `@ai` endpoint

By default the endpoint is **synchronous**: it runs the AI call in the
request thread and returns the result in the response body. For
long-running calls (vision, long-context generations) that risk
exceeding proxy timeouts, pass `"async": true` to defer the call onto
a worker thread; the endpoint then returns a task id immediately and
the client polls.

```http
POST /Plone/<path>/++api++/@ai
Accept: application/json
Content-Type: application/json

{
  "capability": "chat",
  "prompt": "Summarise …",
  "system": "You are a helpful editor.",
  "model": "llama3.1:70b",
  "use_tools": true,            // optional (chat/think/vision); default true
  "output_schema": {            // optional (chat/think/vision); JSON Schema
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"]
  }
}
```

For chat/think/vision the endpoint runs a pydantic-ai agent that
auto-executes registered tools (set `"use_tools": false` to disable).
When `output_schema` is given (a JSON object schema) the `response` is a
structured object matching it instead of plain text.

Synchronous response (HTTP 200):

```jsonc
{
  "status": "done",            // or "error"
  "result": { "response": "…" }
}
```

On a synchronous failure the endpoint returns HTTP 502 with
`{"status": "error", "error": "..."}`.

#### Async mode

Add `"async": true` to the body. Async runs are **tool-less** (the worker
thread has no Plone security context), so an async chat/think/vision call
with `use_tools` enabled is rejected with HTTP 400 — run it synchronously
or set `"use_tools": false`. Response (HTTP 202):

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

| `capability` | required body                                | optional                                  | `result` key  |
| ------------ | -------------------------------------------- | ----------------------------------------- | ------------- |
| `chat`       | `prompt`                                     | `system`, `use_tools`, `output_schema`    | `response`    |
| `think`      | `prompt`                                     | `system`, `use_tools`, `output_schema`    | `response`    |
| `vision`     | `prompt`, `image` (URL or `data:` URI)       | `use_tools`, `output_schema`              | `response`    |
| `embed`      | `input` (string or list of strings)          | —                                         | `embedding`   |
| `tools`      | `messages` (array), `tools` (array)          | —                                         | `response`    |

All variants accept an optional top-level `model` to override
capability-based selection. The `tools` capability is the raw
passthrough (unexecuted `tool_calls`); for server-executed tools use
`chat`/`think`/`vision` with `use_tools` (the default).

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
from collective.aisettings.interfaces import IAIService
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
| Registry schema (JSON shape) + `IAIService` interface | [interfaces.py](src/collective/aisettings/interfaces.py)                     |
| Capability resolution (overrides, passthrough, etc.) | [utils.py](src/collective/aisettings/utils.py)                               |
| Permission gate                        | [permissions.py](src/collective/aisettings/permissions.py)                   |
| `IAIService` implementation            | [service.py](src/collective/aisettings/service.py)                           |
| pydantic-ai model construction         | [models.py](src/collective/aisettings/models.py)                             |
| ZCA tool registry (`IAITool`)          | [tools.py](src/collective/aisettings/tools.py)                               |
| Tool run dependencies (`AIDeps`)       | [deps.py](src/collective/aisettings/deps.py)                                 |
| Embeddings + raw tool passthrough (OpenAI SDK) | [client.py](src/collective/aisettings/client.py)                     |
| REST endpoint `@ai`                    | [services/ai.py](src/collective/aisettings/services/ai.py)                   |
| Task polling endpoint `@ai-task`       | [services/task_status.py](src/collective/aisettings/services/task_status.py) |
| Task registry (in-memory)              | [services/tasks.py](src/collective/aisettings/services/tasks.py)             |
| Helper REST: list models               | [services/list_models.py](src/collective/aisettings/services/list_models.py) |
| Helper REST: model capabilities        | [services/model_capabilities.py](src/collective/aisettings/services/model_capabilities.py) |
| Capabilities vocabulary                | [vocabularies/capabilities.py](src/collective/aisettings/vocabularies/capabilities.py) |
| Helper: query `/v1/models`             | [vocabularies/models.py](src/collective/aisettings/vocabularies/models.py)   |
| Classic Plone form + Volto REST adapter | [controlpanels/ai.py](src/collective/aisettings/controlpanels/ai.py)        |
| Classic z3c.form widget for the JSONField | [controlpanels/widgets.py](src/collective/aisettings/controlpanels/widgets.py) |
| Classic widget template                | [controlpanels/templates/ai_models_widget.pt](src/collective/aisettings/controlpanels/templates/ai_models_widget.pt) |
| Classic widget JS                      | [static/ai-models-widget.js](src/collective/aisettings/static/ai-models-widget.js) |
| Classic widget CSS                     | [static/ai-models-widget.css](src/collective/aisettings/static/ai-models-widget.css) |

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
