# AGENTS.md

Top-level guide for AI agents working in this repository. This file
describes what the product is, where its pieces live, and how the
backend and frontend halves connect. Before editing inside `backend/`
or `frontend/`, read the deeper `AGENTS.md` next to the code you're
about to touch.

## What this repo is

`collective.aisettings` is a Plone 6 addon that lets a Plone site call
OpenAI-compatible LLM services from both Python and the Volto/REST
frontend. The product is split across two installable packages that
share a single registry-backed control panel:

- **`collective.aisettings`** — Python (Plone backend). Source under
  `backend/src/collective/aisettings/`.
- **`volto-collective-ai-settings`** — TypeScript/React Volto addon. Source
  under `frontend/packages/volto-collective-ai-settings/src/`.

The two halves are independent installs but designed to be used
together. Either half on its own gives a usable product (classic
Plone UI works without Volto; Volto can talk to the REST API
without the addon being mounted in classic UI).

## Repository layout

```
collective-ai-settings/
├── README.md                  ← user-facing intro + feature list + quickstart
├── AGENTS.md                  ← (this file)
├── Makefile                   ← orchestrates backend + frontend
├── backend/
│   ├── README.md              ← Plone addon user docs + Python API reference
│   ├── AGENTS.md              ← agent guide for the Plone addon
│   └── src/collective/aisettings/     ← addon source (see backend/AGENTS.md)
├── frontend/
│   ├── README.md              ← Volto addon user docs + frontend integration
│   ├── AGENTS.md              ← agent guide for the Volto addon
│   ├── core/                  ← vendored Volto core (read-only — see its own AGENTS.md)
│   └── packages/volto-collective-ai-settings/   ← addon source (see frontend/AGENTS.md)
├── devops/                    ← Docker stack, Ansible, cache settings
└── docs/                      ← end-user documentation scaffold
```

## How the two halves connect

The data model and entry points cross the language boundary in
exactly three places. Touch one and you almost always need to touch
the others.

1. **The registry record `IAISettings.models`** — a JSON list of
   connections (URL + optional API key + nested list of pinned model
   definitions). Defined in
   `backend/src/collective/aisettings/interfaces.py`. Both UI editors (Volto
   `ModelsWidget` and classic `AIModelsWidget`) read and write this
   shape verbatim, so the JSON schema is the contract.
2. **The `@vocabularies/collective.aisettings.Capabilities` vocabulary** —
   the list of capability tokens (`completion`, `embedding`,
   `vision`, `tools`, `thinking`) used by both widgets and by the
   resolution layer. Defined in
   `backend/src/collective/aisettings/vocabularies/capabilities.py`. The
   tokens match Ollama's `/api/show` keys so auto-detection works.
3. **The REST endpoints** —
   - `POST /++api++/@ai` — accepts `{capability, prompt, …, model?,
     async?}`. Synchronous by default (returns `{status, result}`);
     with `"async": true` returns `{task_id, status}` for polling.
   - `GET /++api++/@ai-task/<id>` — task polling (async mode only).
   - `POST /++api++/@ai-list-models` — lists models for a given URL
     (used by the widgets' model dropdowns).
   - `POST /++api++/@ai-model-capabilities` — auto-detects a model's
     capabilities (used by the widgets when the user selects a
     model). Wired in
     `backend/src/collective/aisettings/services/configure.zcml`.

## Capability resolution rules

Implemented in [`backend/src/collective/aisettings/utils.py`](backend/src/collective/aisettings/utils.py),
shared by both the in-process `IAIService` and the async REST
endpoint:

- Caller passes `model=X`:
  1. First pinned model anywhere with `model == X` → use it.
  2. Otherwise first generic-passthrough connection (empty `models`)
     → use its URL/api key with `X`.
  3. Otherwise fail.
- Caller passes no model, just a `capability`:
  1. First pinned model whose `capabilities` list contains the
     capability → use it.
  2. Otherwise fail. Generic passthroughs are skipped here.

There is no silent capability-based fallback when an explicit model
override is given — that's deliberate; explicit names are explicit.

## Permission gate

Per-model toggle (`protect_with_permission` + `permissions` list).
Checked in [`backend/src/collective/aisettings/permissions.py`](backend/src/collective/aisettings/permissions.py)
via `AccessControl.getSecurityManager().checkPermission(perm,
context)` with OR semantics over the listed permissions. The REST
endpoint enforces this against `self.context` (the dexterity content
the call was rooted at); the `IAIService` facade enforces it against
the caller-supplied `context=` kwarg, defaulting to the portal root.

## Validation commands (whole repo)

```sh
make install          # one-shot install of backend + frontend
make backend-create-site
make backend-start    # Plone backend on :8080
make frontend-start   # Volto frontend on :3000 (separate shell)

make check            # lint + format + tests across both halves
make format
make lint
make i18n
```

Per-half validation lives in the respective `AGENTS.md`.

## Editing rules

- Read this file, then the `AGENTS.md` in whichever subtree you're
  editing, before touching code.
- Backend and frontend changes that share a contract (the JSON
  registry shape, the REST endpoint body shape, the vocabulary
  tokens) must land together. Update both sides in the same change.
- Don't write to `frontend/core/` — it's a vendored copy of Volto
  core with its own `AGENTS.md` (read-only as far as this addon is
  concerned).
- Stick to the working directory. The plan files, the registry data,
  and any vendored Plone sources outside this repo are out of scope.

## Where to look next

- Adding a new capability to the AI catalog or changing how models
  are resolved? Start at [`backend/AGENTS.md`](backend/AGENTS.md).
- Changing the control-panel UI in Volto, or wiring an addon block
  to the REST endpoint? Start at [`frontend/AGENTS.md`](frontend/AGENTS.md).
- End-user / integrator questions are best answered by the
  matching `README.md` at each level.
