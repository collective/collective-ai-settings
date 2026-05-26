# AGENTS.md — backend

Agent guide for the `collective.aisettings` Plone addon (`backend/`). For
the cross-cutting picture of how this half talks to the Volto half,
read [`../AGENTS.md`](../AGENTS.md) first.

## Scope

Anything under `backend/src/collective/aisettings/` plus the package
metadata (`pyproject.toml`, `instance.yaml`, profiles, ZCML).

The frontend Volto addon (`frontend/packages/volto-collective-ai-settings/`)
is documented at [`../frontend/AGENTS.md`](../frontend/AGENTS.md).
Don't edit it from this side; coordinate cross-half changes via the
contracts described below.

## Package layout

```
backend/src/collective/aisettings/
├── interfaces.py              ← IAISettings (JSON schema) + IAIService
├── utils.py                   ← resolve_model / pick_model / _flatten
├── service.py                 ← AIService (registered as IAIService utility)
├── permissions.py             ← entry_permits — Plone permission gate
├── client.py                  ← low-level HTTP (chat_completion, embeddings)
├── controlpanels/
│   ├── ai.py                  ← classic RegistryEditForm + Volto REST adapter
│   ├── widgets.py             ← classic z3c.form widget for the JSONField
│   ├── templates/             ← page templates for the widget
│   └── configure.zcml         ← adapter / page registrations
├── services/
│   ├── ai.py                  ← @ai async endpoint (capability dispatch)
│   ├── task_status.py         ← @ai-task/<id> polling endpoint
│   ├── tasks.py               ← in-memory task registry (create/complete/fail)
│   ├── list_models.py         ← @ai-list-models REST helper
│   ├── model_capabilities.py  ← @ai-model-capabilities REST helper
│   └── configure.zcml         ← <plone:service> registrations
├── vocabularies/
│   ├── capabilities.py        ← collective.aisettings.Capabilities vocabulary
│   └── models.py              ← fetch_models / fetch_model_capabilities helpers
├── static/                    ← classic widget JS + CSS (served via ++resource++)
├── events/                    ← (subscriber stubs; empty by default)
├── profiles/default/          ← GenericSetup (registry, controlpanel, browserlayer)
└── configure.zcml             ← package root: imports + utility registration
```

## Key contracts

These are the seams between layers. Changing one without the others
breaks things.

### Registry schema — `IAISettings.models`

Defined in [`interfaces.py`](src/collective/aisettings/interfaces.py). A
JSON list of *connections*, each containing a URL, optional API key,
and a nested list of pinned models with capabilities and a permission
gate. See `backend/README.md` for the canonical shape. The Volto and
classic widgets write this shape verbatim.

### Flattened entry dict

`utils.resolve_model(capability, override)` returns either `None` or
a flat dict:

```python
{
  "url": "...",
  "api_key": "...",
  "model": "...",
  "capabilities": ["..."],
  "protect_with_permission": bool,
  "permissions": ["..."],
}
```

Every downstream consumer — `permissions.entry_permits`,
`service.AIService.run_call`, and `services/ai._worker` — operates
on this flat shape. If you add new per-model metadata, flatten it
here and adapt the consumers; do not propagate the nested structure
further than `utils.py`.

### REST endpoint body

`POST /++api++/@ai` body: `{capability, prompt|input|messages|image,
system?, tools?, model?, async?}`. Dispatched by the `capability`
string. Default is synchronous (returns `{status, result}` with HTTP
200/502); pass `"async": true` to defer onto a worker thread and get
`{task_id, status}` with HTTP 202 instead. Result payload key depends
on capability (`response` vs `embedding`). See the body-shapes table
in [`README.md`](./README.md).

### Capability tokens

Hard-coded list shared between
[`vocabularies/capabilities.py`](src/collective/aisettings/vocabularies/capabilities.py)
and the `CAPABILITY_TOKEN` map in
[`service.py`](src/collective/aisettings/service.py). The tokens match
Ollama's `/api/show` strings so auto-detection
([`vocabularies/models.fetch_model_capabilities`](src/collective/aisettings/vocabularies/models.py))
works without translation.

If you add a capability, update **both** the vocabulary and the
`CAPABILITY_TOKEN` map, plus the corresponding branch in
`AIService.run_call`. The frontend widget reads the vocabulary at
runtime, so no frontend update is needed for the checkbox list — but
the REST endpoint dispatch is hard-coded, so it needs the new branch.

## Adding a new capability — checklist

1. Add the token to `CAPABILITIES` in
   [`vocabularies/capabilities.py`](src/collective/aisettings/vocabularies/capabilities.py).
2. Add `"<capability_name>": "<token>"` to `CAPABILITY_TOKEN` in
   [`service.py`](src/collective/aisettings/service.py).
3. Add a branch to `AIService.run_call` (and a facade method like
   `chat`/`think`/etc.) for the new operation.
4. Add a branch to `_validate` and the body-shapes table in
   [`services/ai.py`](src/collective/aisettings/services/ai.py).
5. Add the capability name to `SUPPORTED_CAPABILITIES` in the same
   file.
6. Update the `IAIService` interface docstrings in
   [`interfaces.py`](src/collective/aisettings/interfaces.py).
7. Document in [`README.md`](./README.md): capability table + body
   shapes.

## Adding a new model permission target

The permission UI on both widgets is driven by a hard-coded list of
*common* permissions plus arbitrary user-entered ones. Backend just
calls `getSecurityManager().checkPermission(perm_title, context)` so
any Plone permission title works at runtime. If you want a new
common permission to appear as a checkbox, edit the
`COMMON_PERMISSIONS` constant in both
[`static/ai-models-widget.js`](src/collective/aisettings/static/ai-models-widget.js)
and in
`frontend/packages/volto-collective-ai-settings/src/components/ModelsWidget.tsx`.

## Async / worker thread invariants

`services/ai.py` resolves the model and runs the permission check in
the **request thread** (which is where Zope/ZODB are available),
then hands a plain dict + capability + payload to a daemon Thread
that calls `service.run_call`. The worker:

- must not touch the ZODB
- must not call `getSecurityManager()` or any other request-bound API
- must complete or fail through `complete_task` / `fail_task` so the
  polling endpoint can report the result

`run_call` itself is pure outbound HTTP; if you add behavior that
needs Zope state, do it before the `Thread(...).start()` call, not
inside the worker.

## Permission gate semantics

`permissions.entry_permits(entry, context)`:

- Returns `True` early if `protect_with_permission` is missing/False.
- Returns `False` (with a warning log) when the gate is on but no
  permissions are listed — opt-in must declare at least one allow.
- Otherwise OR-tests `checkPermission(perm, context)` over the
  `entry["permissions"]` list.

`AIService._call` always evaluates the gate, defaulting `context` to
`api.portal.get()` when the caller omitted it. The REST endpoint
always passes `self.context`.

## ZCML cheat sheet

- Top-level package configure:
  [`configure.zcml`](src/collective/aisettings/configure.zcml) — includes
  subpackages, registers `<browser:resourceDirectory name="collective.aisettings"
  directory="static" />` and the `<utility … provides=IAIService />`.
- Control panel:
  [`controlpanels/configure.zcml`](src/collective/aisettings/controlpanels/configure.zcml)
  — registers the `RegistryConfigletPanel` adapter (used by Volto),
  the classic `browser:page name="ai-settings"`, and the
  `AIModelsDataConverter` (JSONField ↔ widget string).
- REST endpoints:
  [`services/configure.zcml`](src/collective/aisettings/services/configure.zcml)
  — `@ai-list-models`, `@ai-model-capabilities`, `@ai`, `@ai-task`.
- Capabilities vocabulary:
  [`vocabularies/configure.zcml`](src/collective/aisettings/vocabularies/configure.zcml).

## Validation commands

```sh
# From backend/
make install                    # uv-driven install into ./venv
make create-site                # creates the Plone instance + addon profile
make start                      # backend on :8080

# Lint + format + tests
make lint
make format
make test
make check                      # lint + tests
```

Running tests requires the venv set up via `make install`. There's a
test scaffold at `backend/tests/` but the addon currently leans on
manual / curl-driven validation; if you add automation, follow the
existing pytest pattern.

## Editing rules

- Keep `utils.resolve_model`'s return shape stable — both
  `service.AIService` and `services/ai.AIServiceEndpoint` assume the
  flat dict. Add new fields by extending `_flatten`; don't leak the
  nested connection/model structure outside `utils.py`.
- Whenever you change the registry JSON schema in
  [`interfaces.py`](src/collective/aisettings/interfaces.py), update
  **both** widgets (the classic JS and the Volto TSX) in the same
  change. See `../frontend/AGENTS.md` for the frontend side.
- The `@ai-task` polling endpoint reads from an in-memory task
  registry ([`services/tasks.py`](src/collective/aisettings/services/tasks.py));
  tasks don't survive a restart and aren't cross-process. If you
  need persistence/horizontal scaling, document the trade-off in the
  PR — don't silently switch backing stores.
- Don't import from Volto / TypeScript code, and don't write JSON
  serializers that assume Volto-specific URL shapes. The backend is
  classic-Plone-first; Volto is one of two clients of the same REST
  API.
