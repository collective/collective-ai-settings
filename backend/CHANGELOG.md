# Changelog

<!--
   You should *NOT* be adding new change log entries to this file.
   You should create a file in the news directory instead.
   For helpful instructions, please see:
   https://github.com/plone/plone.releaser/blob/master/ADD-A-NEWS-ITEM.rst
-->

<!-- towncrier release notes start -->

## 1.2.0 (2026-07-16)


### New features:

- Add optional environment-driven AI connections: set ``COLLECTIVE_AISETTINGS_CONNECTIONS`` to a JSON file (same shape as the control panel, plus an ``api_key_env`` field to read keys from the environment). File connections are merged before the registry ones (file-first precedence) and reloaded on change. @frapell 

## 1.1.0 (2026-07-15)


### Breaking changes:

- The `IAIService` utility was redesigned around pydantic-ai: a new `run()` method (with `output_type`/`use_tools`), and `chat`/`think`/`analyze_image` gained `request`/`output_type`/`use_tools` keywords. `run_call` is now tool-less and worker-safe; `tool_call` remains a raw passthrough. @frapell 


### New features:

- AI calls (chat/think/vision) now run through [pydantic-ai](https://ai.pydantic.dev) agents instead of raw HTTP, adding multimodal input, an agentic tool-execution loop and structured (typed) output. @frapell 
- Other add-ons can now register AI tools through the component architecture — as named `IAITool` utilities (global) or `IAIToolProvider` subscription adapters (context-aware) — which the agent auto-executes during a call. @frapell 

## 1.0.0 (2026-05-26)


### Internal:

- Initial release. @frapell 

## 1.0.0a6 (2026-05-26)

No significant changes.


## 1.0.0a5 (2026-05-26)

No significant changes.


## 1.0.0a4 (2026-05-26)

No significant changes.


## 1.0.0a3 (2026-05-26)

No significant changes.


## 1.0.0a2 (2026-05-26)

No significant changes.


## 1.0.0a1 (2026-05-26)


### Internal:

- Initial release. @frapell
