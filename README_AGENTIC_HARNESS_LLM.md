# Agentic Harness + LLM Engineering README

This document explains how the SurfSense chat agent works end-to-end, with a focus on:

- Agent harness (graph, middleware, tools, state)
- LLM configuration and routing
- Streaming lifecycle and persistence
- Reliability and recovery paths
- Practical extension and debugging workflow

---

## 1) What this system is

At runtime, the backend builds a **compiled LangGraph agent** (via LangChain/deepagents integration), runs it in streaming mode, and emits SSE events to the frontend.

High-level pipeline:

1. HTTP route receives chat request
2. `stream_new_chat` resolves model config and builds runtime objects
3. `create_surfsense_deep_agent` builds tools + prompt + middleware and compiles graph
4. `_stream_agent_events` runs the graph and translates events to SSE
5. Server persists user and assistant turns (not frontend-only)
6. Cleanup/finalize always runs in `finally`

Primary entry files:

- `source/SurfSense/surfsense_backend/app/routes/new_chat_routes.py`
- `source/SurfSense/surfsense_backend/app/tasks/chat/stream_new_chat.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/chat_deepagent.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/llm_config.py`

---

## 2) Request entrypoint and stream handoff

The route calls `stream_new_chat(...)` and returns a `StreamingResponse` (`text/event-stream`).

Where:

- `source/SurfSense/surfsense_backend/app/routes/new_chat_routes.py`

Key behavior at handoff:

- Resolves `llm_config_id` from `SearchSpace.agent_llm_id` (fallback `-1`)
- Commits/closes dependency session before long stream (reduces lock/connection issues)
- Passes request metadata (mentions, images, visibility, disabled tools, request id)

---

## 3) LLM config model (what `AgentConfig` is)

`AgentConfig` is the canonical in-memory config object used to build model + prompt behavior.

Where defined:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/llm_config.py`

Core fields include:

- Provider/model/api (`provider`, `model_name`, `api_key`, `api_base`, `custom_provider`)
- LiteLLM params (`litellm_params`)
- Prompt controls (`system_instructions`, `use_default_system_instructions`, `citations_enabled`)
- Metadata/policy (`config_id`, `is_auto_mode`, `billing_tier`, `is_premium`, `quota_reserve_tokens`)

Config source rules:

- `config_id == 0` → Auto mode (`AgentConfig.from_auto_mode()`)
- `config_id < 0` → YAML/global config (`from_yaml_config`)
- `config_id > 0` → DB `NewLLMConfig` (`from_new_llm_config`)

Model object creation:

- `create_chat_litellm_from_agent_config(agent_config)`
- Auto mode returns router-backed model object; explicit configs return `ChatLiteLLM`

---

## 4) Stream task responsibilities (`stream_new_chat`)

Where:

- `source/SurfSense/surfsense_backend/app/tasks/chat/stream_new_chat.py`

`stream_new_chat` does much more than "call the model":

1. Initializes stream state (`StreamResult`, token accumulator, request/turn metadata)
2. Resolves pinned model via `resolve_or_get_pinned_llm_config_id(...)`
3. Loads `(llm, agent_config)` via `_load_llm_bundle(...)`
4. Runs optional quick model-access check for auto-pinned models
5. Builds connector service + checkpointer
6. Builds agent (in parallel with quick check in the common path)
7. Persists user + assistant shell rows early
8. Streams agent events and maps to SSE protocol
9. Finalizes assistant content/token usage in `finally`

### Quick model-access check and rebuild path

For auto-pinned configs, the task can issue a very small probe request before full execution.

- If probe passes: continue with early-built agent
- If probe indicates rate limit: mark old config temporarily unhealthy, select a new one, reload model config, rebuild agent

Rate-limit detection uses `_is_provider_rate_limited(...)` (it checks more than just literal status code text).

### Runtime retry path

If stream fails before first event due to provider rate limit, the task can do a one-time same-request recovery:

- Release busy lock state
- Cool down failed config
- Resolve a different model config
- Rebuild agent
- Retry stream loop

---

## 5) Agent factory (`create_surfsense_deep_agent`)

Where:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/chat_deepagent.py`

This is the core harness builder.

It performs:

1. Prompt-cache setup on model object
2. Connector/document-type discovery for current search space
3. Tool construction via async registry (`build_tools_async`)
4. System prompt construction (default or config-driven)
5. Middleware stack construction
6. Graph compilation via `create_agent(...)`
7. Optional compiled-agent caching (flag-controlled)

### Why this uses `create_agent` (LangChain) directly

The code intentionally assembles middleware itself (instead of only using convenience wrappers), so SurfSense can control ordering and custom middleware behavior.

---

## 6) Tool system

Tool registration and dependency injection live in:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/tools/registry.py`

Important details:

- `BUILTIN_TOOLS` is the declarative registry
- Each tool has a factory and required dependencies
- Connector-gated tools can be auto-disabled if connector isn’t available
- MCP tools are loaded into the same tool surface
- Some tools include dedup/reverse metadata for HITL/revert flows

Tool examples in registry:

- `generate_report`, `scrape_webpage`, `web_search`, `update_memory`
- Connector tools (Notion, Gmail, Drive, Calendar, Slack/Teams/Discord, etc.)

---

## 7) Middleware architecture

Middleware exports:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/middleware/__init__.py`

Middleware stack composition happens in `chat_deepagent.py` and includes:

- Concurrency/safety: `BusyMutexMiddleware`, `PermissionMiddleware`, `DoomLoopMiddleware`
- Context/memory: `MemoryInjectionMiddleware`, context editing + compaction
- Knowledge: `KnowledgeTreeMiddleware`, `KnowledgePriorityMiddleware`, persistence middleware
- Tool quality: tool-call repair, dedup HITL tool calls, patching
- Reliability: retry-after middleware, optional model fallback
- Observability: OTel spans, action log
- Extensibility: plugin loader, skills, subagents

Ordering matters. The list is explicitly arranged to control behavior such as:

- lock handling scope
- retry/fallback boundaries
- permission checks before tool execution
- context reduction before model retries

---

## 8) Runtime context (per-turn data, not baked into graph)

Where:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/context.py`

`SurfSenseContextSchema` carries per-invocation values (for example, mentioned document IDs, request/turn IDs) so the compiled graph can be reused safely across turns.

This separation is important for cache correctness: values that change every turn should come via runtime context, not constructor closures.

---

## 9) Event streaming contract

Where:

- `_stream_agent_events(...)` in `stream_new_chat.py`

This function:

- consumes `agent.astream_events(...)`
- normalizes model/tool/custom events
- emits frontend SSE protocol events
- tracks tool-call correlation ids
- handles reasoning/text block transitions
- surfaces interrupt requests for human-in-the-loop decisions

The output stream is not raw model text; it is a structured event protocol.

---

## 10) Server-side persistence model

Where:

- `source/SurfSense/surfsense_backend/app/tasks/chat/persistence.py`
- `source/SurfSense/surfsense_backend/app/tasks/chat/content_builder.py`

Current approach:

- User turn and assistant shell row are written server-side during stream startup
- Assistant final content and token usage are finalized server-side in `finally`
- Frontend append calls are effectively legacy/no-op-safe due to idempotent constraints

`AssistantContentBuilder` mirrors frontend `ContentPart[]` projection so persisted content matches live stream semantics.

---

## 11) Checkpointing and state durability

Where:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/checkpointer.py`

The agent uses `AsyncPostgresSaver` with pooled psycopg connections.

Purpose:

- durable conversation state/checkpoints
- resume/fork behavior support
- safer long-running operation than ephemeral memory-only state

---

## 12) Feature flags and rollout controls

Where:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/feature_flags.py`

Flags control middleware/features and allow rollback without code changes.

Notable controls:

- master kill switch (`SURFSENSE_DISABLE_NEW_AGENT_STACK`)
- context editing / compaction / retry / fallback / limits
- permission / busy mutex / doom loop
- skills / specialized subagents / plugins
- action log / revert route
- compiled-agent cache

---

## 13) Mental model (plain engineering terms)

- **Harness** = code that builds and runs the agent graph (tools + middleware + prompt + model)
- **Agent config** = model + prompt + policy settings for a specific run
- **Compiled agent** = executable graph object ready to stream events
- **Runtime context** = per-request values injected at invocation time
- **Pre-check** = tiny call to catch rate-limited pinned model before expensive work
- **Recovery** = switch model and rebuild agent when upstream is throttled

---

## 14) Common extension tasks

### Add a new tool

1. Implement tool factory in `tools/`
2. Register in `BUILTIN_TOOLS` in `tools/registry.py`
3. Define required dependencies and connector gating
4. Verify middleware interactions (permission/dedup/action log)

### Add a middleware

1. Implement under `middleware/`
2. Export in `middleware/__init__.py`
3. Insert into stack in `chat_deepagent.py` with deliberate ordering
4. Gate by feature flag if risky/new

### Add new model config source behavior

1. Extend `AgentConfig` conversion/load path in `llm_config.py`
2. Ensure `create_chat_litellm_from_agent_config` covers provider/model string rules
3. Validate stream paths that reload config on retries/repins

---

## 15) Debugging checklist

1. Confirm route-level inputs (`llm_config_id`, visibility, disabled tools, images)
2. Confirm resolved/pinned config id in `stream_new_chat` logs
3. Verify `(llm, agent_config)` load success
4. Check pre-check/rebuild logs for rate-limit cases
5. Confirm tools built count and final middleware stack compile
6. Inspect SSE event flow from `_stream_agent_events`
7. Verify persistence (`persist_user_turn`, `persist_assistant_shell`, `finalize_assistant_turn`)
8. Check feature flags currently active

---

## 16) Suggested reading order for new engineers

1. `app/tasks/chat/stream_new_chat.py` (top-level orchestration)
2. `app/agents/new_chat/chat_deepagent.py` (agent build + middleware)
3. `app/agents/new_chat/llm_config.py` (config/model loading)
4. `app/agents/new_chat/tools/registry.py` (tool surface)
5. `app/agents/new_chat/middleware/*` (policy and behavior layers)
6. `app/tasks/chat/persistence.py` + `content_builder.py` (storage contract)

---

## 17) Notes on the environment copy vs source copy

You may see a mirrored installed file under your Python env path (for example, site-packages).
For engineering changes and source-of-truth documentation, use the workspace source tree under:

- `source/SurfSense/surfsense_backend/app/...`

The site-packages copy is useful for runtime inspection but should not be treated as the primary editable source in this repo.

---

## 18) Tool inventory (deepagents built-ins vs SurfSense custom tools)

This section is derived from:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/chat_deepagent.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/tools/registry.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/tools/invalid_tool.py`

### A) Built-in tools surfaced via deepagents middleware integration

These are the canonical middleware-provided tool names wired into this harness
(the integration keeps them in the valid tool-name set):

- `write_todos` (TodoListMiddleware)
- `task` (SubAgentMiddleware)
- `ls`*
- `read_file`*
- `write_file`
- `edit_file`
- `glob`*
- `grep`*
- `execute`
- `mkdir`
- `cd`
- `pwd`
- `move_file`
- `rm`
- `rmdir`
- `list_tree`*
- `execute_code`

Notes:

- `SkillsMiddleware` is enabled and can expose additional skill tools dynamically.
- In this repo, filesystem behavior is provided through `SurfSenseFilesystemMiddleware`
	(customized integration) while preserving deepagents-style tool surface.
- `*` marks tools used for local file extraction / file QA workflows.

### B) Customized tools defined in SurfSense code

These are explicitly registered in `BUILTIN_TOOLS`:

- `generate_podcast`
- `generate_video_presentation`
- `generate_report`
- `generate_resume`
- `generate_image`
- `scrape_webpage`
- `web_search`
- `search_surfsense_docs`
- `get_connected_accounts`
- `update_memory`
- `create_notion_page`
- `update_notion_page`
- `delete_notion_page`
- `create_google_drive_file`
- `delete_google_drive_file`
- `create_dropbox_file`
- `delete_dropbox_file`
- `create_onedrive_file`
- `delete_onedrive_file`
- `search_calendar_events`
- `create_calendar_event`
- `update_calendar_event`
- `delete_calendar_event`
- `search_gmail`
- `read_gmail_email`
- `create_gmail_draft`
- `send_gmail_email`
- `trash_gmail_email`
- `update_gmail_draft`
- `create_confluence_page`
- `update_confluence_page`
- `delete_confluence_page`
- `list_discord_channels`
- `read_discord_messages`
- `send_discord_message`
- `list_teams_channels`
- `read_teams_messages`
- `send_teams_message`
- `list_luma_events`
- `read_luma_event`
- `create_luma_event`

Additional SurfSense-defined fallback tool (not in `BUILTIN_TOOLS`, injected separately):

- `invalid`

Runtime-loaded custom tools:

- MCP tools are loaded dynamically via `load_mcp_tools(...)` in `build_tools_async(...)`,
	so their exact names depend on configured connectors/servers at runtime.

---

## 19) One-page memory architecture (short-term + long-term)

This section maps SurfSense memory behavior to four practical memory types:

1. Short-term working memory (current reasoning context)
2. Long-term episodic memory (what happened)
3. Long-term semantic memory (what is true)
4. Long-term procedural memory (how to do things)

### A) Short-term working memory

Definition:

- The active message/state window used during the current turn.

Where it is implemented:

- `stream_new_chat.py` builds per-turn `input_state` and `configurable` values (thread/request/turn).
- LangGraph state/messages are streamed through `_stream_agent_events(...)`.
- Checkpoint-backed continuity is enabled by the PostgreSQL checkpointer.

Key files:

- `source/SurfSense/surfsense_backend/app/tasks/chat/stream_new_chat.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/checkpointer.py`

Status:

- Implemented.

---

### B) Long-term episodic memory (what happened)

Definition:

- Durable records of conversation turns and agent actions.

Where it is implemented:

- `NewChatMessage` stores user/assistant/system turns.
- `AgentActionLog` stores append-only tool action metadata (tool name, args, ids, reversibility metadata).
- `turn_id`, `tool_call_id`, and `chat_turn_id` provide cross-linking across stream, tool execution, and persistence.
- LangGraph checkpoints preserve graph-state history for resume/fork behavior.

Key files:

- `source/SurfSense/surfsense_backend/app/db.py` (`NewChatMessage`, `AgentActionLog`)
- `source/SurfSense/surfsense_backend/app/agents/new_chat/middleware/action_log.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/checkpointer.py`

Status:

- Implemented.

---

### C) Long-term semantic memory (facts/preferences/instructions)

Definition:

- Durable factual memory used to personalize future behavior.

Where it is implemented:

- User semantic memory: `User.memory_md`.
- Team semantic memory: `SearchSpace.shared_memory_md`.
- Injection each turn via `MemoryInjectionMiddleware` as `<user_memory>` or `<team_memory>`.
- Explicit writes via `update_memory` tool (validation, scope checks, size limits, optional forced rewrite).
- Fallback background extraction after a turn when the agent did not call `update_memory`.

Key files:

- `source/SurfSense/surfsense_backend/app/db.py` (`User.memory_md`, `SearchSpace.shared_memory_md`)
- `source/SurfSense/surfsense_backend/app/agents/new_chat/middleware/memory_injection.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/tools/update_memory.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/memory_extraction.py`
- `source/SurfSense/surfsense_backend/app/tasks/chat/stream_new_chat.py` (post-turn extraction trigger)

Status:

- Implemented.

---

### D) Long-term procedural memory (how to do things)

Definition:

- Durable operating procedures, policies, and execution patterns.

Where it is implemented in SurfSense:

- Prompt fragments composed by the prompt composer (stable behavioral rules).
- Skills loaded by `SkillsMiddleware` from built-in and search-space skill sources.
- Permission/rule middleware and subagent specs encode operational constraints and role behavior.

Important nuance:

- This is procedural memory as externalized instructions/policies.
- It is not model-weight learning or autonomous skill training inside the base LLM.

Key files:

- `source/SurfSense/surfsense_backend/app/agents/new_chat/prompts/composer.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/chat_deepagent.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/middleware/skills_backends.py`
- `source/SurfSense/surfsense_backend/app/agents/new_chat/subagents/config.py`

Status:

- Partially implemented (policy/skill based, not weight-based learning).

---

### E) Data extraction walkthrough (end-to-end)

Example input:

- User says: “For future work, use PR titles in format feat(scope): summary.”

Flow:

1. Turn starts with short-term context + injected durable memory.
2. Agent may explicitly call `update_memory` with the full revised memory document.
3. If no explicit memory update happened, stream finalization triggers background extraction:
	- Private thread → `extract_and_save_memory(...)`
	- Shared thread → `extract_and_save_team_memory(...)`
4. Extractor decides if the message is durable enough:
	- If no: `NO_UPDATE`
	- If yes: returns full updated memory markdown
5. `_save_memory(...)` validates format/scope/size and persists.
6. On the next turn, `MemoryInjectionMiddleware` reinjects the updated memory block into the system context.

Operational result:

- The instruction becomes reusable across future chats without manually repeating it.

---

### F) Quick status matrix

- Short-term working memory: Implemented
- Episodic long-term memory: Implemented
- Semantic long-term memory: Implemented
- Procedural long-term memory: Partially implemented (instruction/skill layer)

