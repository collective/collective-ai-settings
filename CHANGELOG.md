# Change log

<!-- You should *NOT* be adding new change log entries to this file.
     You should create a file in the news directory instead.
     For helpful instructions, please see:
     https://6.docs.plone.org/contributing/index.html#contributing-change-log-label
-->

<!-- towncrier release notes start -->
## 1.1.0 (2026-07-15)

### Backend


#### Breaking changes:

- The `IAIService` utility was redesigned around pydantic-ai: a new `run()` method (with `output_type`/`use_tools`), and `chat`/`think`/`analyze_image` gained `request`/`output_type`/`use_tools` keywords. `run_call` is now tool-less and worker-safe; `tool_call` remains a raw passthrough. @frapell 


#### New features:

- AI calls (chat/think/vision) now run through [pydantic-ai](https://ai.pydantic.dev) agents instead of raw HTTP, adding multimodal input, an agentic tool-execution loop and structured (typed) output. @frapell 
- Other add-ons can now register AI tools through the component architecture — as named `IAITool` utilities (global) or `IAIToolProvider` subscription adapters (context-aware) — which the agent auto-executes during a call. @frapell 



### Frontend

No significant changes.


### Project

No significant changes.




## 1.0.0 (2026-05-26)

### Backend


#### Internal:

- Initial release. @frapell 



### Frontend

#### Internal

- Initial release. @frapell 



### Project


#### Internal

- Initial release. @frapell 



## 1.0.0a6 (2026-05-26)

### Backend

No significant changes.




### Frontend

No significant changes.


### Project

No significant changes.




## 1.0.0a5 (2026-05-26)

### Backend

No significant changes.




### Frontend

#### Internal

- Initial release. @frapell 



### Project

No significant changes.




## 1.0.0a4 (2026-05-26)

### Backend

No significant changes.




### Frontend

#### Internal

- Initial release. @frapell 



### Project


#### Internal

- Initial release. @frapell 



## 1.0.0a3 (2026-05-26)

### Backend

No significant changes.




### Frontend

#### Internal

- Initial release. @frapell 



### Project

No significant changes.




## 1.0.0a2 (2026-05-26)

### Backend

No significant changes.




### Frontend

#### Internal

- Initial release. @frapell 



### Project

No significant changes.




## 1.0.0a1 (2026-05-26)

### Backend


#### Internal:

- Initial release. @frapell 



### Frontend

#### Internal

- Initial release. @frapell 



### Project


#### Internal

- Initial release. @frapell 



