# DeepSeek `reasoning_content` Multi-Turn Bug — Technical Documentation

**Status:** Mitigated in SurfSense as of 2026-05-02 (validated on 1-question run)  
**Error message:** `litellm.BadRequestError: The reasoning_content in the thinking mode must be passed back to the API.`  
**Model:** `deepseek-v4-flash` (DeepSeek API, `deepseek-reasoner` series)  
**Trigger:** Multi-turn agentic loop — Turn 2 fails whenever Turn 1 involved tool calls + reasoning.

---

## 1. Problem Description

When running DeepSeek in SurfSense's multi-turn agent loop (via `langchain`/`deepagents`), Turn 1 succeeds but Turn 2 always crashes with a 400 `BadRequestError`. The same model works fine when called directly (single-turn, no history).

**DeepSeek's requirement:** When using `deepseek-reasoner` in "thinking mode", the `reasoning_content` field returned in the assistant message from Turn 1 **must be echoed back verbatim** in the conversation history sent to Turn 2. If it's missing, the API rejects the request.

---

## 2. Architecture

```
Turn 1:
  SurfSense agent → SanitizedChatLiteLLM._astream() → ChatLiteLLM._astream()
    → litellm.acompletion() → DeepSeek API
    → returns streaming chunks with delta.reasoning_content + delta.tool_calls
    → AIMessageChunk accumulation → AIMessage stored in LangGraph state

Tool execution (LangGraph node):
  ToolMessage added to state

Turn 2:
  SurfSense agent reads state["messages"] → SanitizedChatLiteLLM._astream()
    → ChatLiteLLM._astream() → self._create_message_dicts(messages)
      → _convert_message_to_dict(ai_message)  ← MUST include reasoning_content
    → litellm.acompletion() → DeepSeek API  ← FAILS if reasoning_content missing
```

**Agent framework:** `deepagents` + `langchain.agents.create_agent` + LangGraph  
**Checkpointer:** `AsyncPostgresSaver` (PostgreSQL-backed state persistence)  
**LLM class:** `SanitizedChatLiteLLM(ChatLiteLLM)` in `/app/app/agents/new_chat/llm_config.py`

---

## 3. Root Cause Chain (Confirmed)

### 3.1 `_convert_message_to_dict` drops `reasoning_content`

`langchain_litellm`'s `_convert_message_to_dict` (at `/usr/local/lib/python3.12/site-packages/langchain_litellm/chat_models/litellm.py`) serializes AIMessage history into dicts for the API call.  
For `AIMessage`, it copies `content` and `tool_calls` but **silently drops all unknown keys from `additional_kwargs`**, including `reasoning_content`.

**Fix applied (in both containers):** Lines 377-378, after the `tool_calls` block:
```python
if "reasoning_content" in message.additional_kwargs and message.additional_kwargs["reasoning_content"]:
    message_dict["reasoning_content"] = message.additional_kwargs["reasoning_content"]
```
This patch **works in isolation** (confirmed via `inspect.getsource` and simulation tests).

### 3.2 `SanitizedChatLiteLLM._create_message_dicts` override not being reached

A rescue override was added in `llm_config.py`:
```python
def _create_message_dicts(self, messages, stop):
    message_dicts, params = super()._create_message_dicts(_sanitize_messages(messages), stop)
    for msg, msg_dict in zip(messages, message_dicts):
        if isinstance(msg, AIMessage):
            extra = getattr(msg, "additional_kwargs", {}) or {}
            for key in _REASONING_PASSTHROUGH_KWARGS:   # {"reasoning_content"}
                if key in extra and extra[key]:
                    msg_dict[key] = extra[key]
    return message_dicts, params
```
This override IS present in the file and IS the live code (confirmed via `inspect.getsource`).  
**But:** The DEBUG print inside this override (`[DEBUG _create_message_dicts]`) revealed:

```
[DEBUG _create_message_dicts] AIMessage type=AIMessage additional_kwargs keys=[] content_type=NoneType
```

#### This is the confirmed root cause:
**The AIMessage stored in LangGraph state after Turn 1 has `additional_kwargs = {}` — `reasoning_content` is already lost before `_create_message_dicts` is ever called.**

---

## 4. Isolation Tests (All Passed)

The following components were verified to handle `reasoning_content` correctly in isolation:

| Component | Preserves `reasoning_content`? |
|-----------|-------------------------------|
| `Delta` object (`litellm`) | ✅ Yes — `reasoning_content` is a first-class field |
| `_convert_delta_to_message_chunk` | ✅ Yes — copies to `additional_kwargs` |
| `add_ai_message_chunks` (chunk merging) | ✅ Yes — merges `additional_kwargs` via `merge_dicts` |
| `message_chunk_to_message` (chunk→AIMessage) | ✅ Yes — copies all `__dict__` fields |
| `add_messages` (LangGraph reducer) | ✅ Yes — preserves `additional_kwargs` |
| `_convert_message_to_dict` (after patch) | ✅ Yes — dict includes `reasoning_content` |
| `litellm.acompletion` with `reasoning_content` in messages | ✅ Accepts it (gets auth error, not 400) |

---

## 5. Likely Remaining Cause

Since all components work in isolation but `additional_kwargs = {}` at Turn 2, the loss happens **between the AIMessage being returned from Turn 1's `ainvoke()` call and it being stored in LangGraph state** that is then read in Turn 2.

### Hypothesis A: AsyncPostgresSaver serde strips `additional_kwargs`
LangGraph's PostgreSQL checkpointer serializes messages between turns. If it uses a serializer that calls `AIMessage.model_dump()` or similar with `exclude_unset=True` or filters known fields only, `additional_kwargs["reasoning_content"]` would be dropped.

Check: `/usr/local/lib/python3.12/site-packages/langgraph/checkpoint/postgres/aio.py` and the serde codec used.

### Hypothesis B: `_handle_model_output` reconstructs AIMessage without `additional_kwargs`
In `langchain/agents/factory.py`, `_handle_model_output(output, ...)` at line 1037 processes the raw `ainvoke` output. It returns `{"messages": [output]}` for the normal case, passing through the original `AIMessage`. But if `output` is wrapped or converted somewhere in this path, `additional_kwargs` might be lost.

### Hypothesis C: `agenerate_from_stream` / `generate_from_stream` loses it
`ChatLiteLLM._agenerate` calls `agenerate_from_stream(self._astream(...))` which:
1. Accumulates `ChatGenerationChunk` objects
2. Calls `generate_from_stream` → `ChatGenerationChunk.__add__` → `message_chunk_to_message`
3. Returns `ChatResult(generations=[ChatGeneration(message=...)])`

The `message = generation.message` in `ChatGeneration` should be the full `AIMessage`, but if there's a Pydantic validation step that re-creates the model from only known fields, `additional_kwargs` could be lost.

---

## 6. Attempted Fixes Summary

| Fix | Status | Outcome |
|-----|--------|---------|
| Patch `_convert_message_to_dict` in `langchain_litellm` | Applied (both containers) | Works in isolation, but `additional_kwargs` empty before this is reached |
| `SanitizedChatLiteLLM._create_message_dicts` override | Applied (`llm_config.py`, both containers) | Runs, but `additional_kwargs` is already `{}` at this point |
| Clear `.pyc` caches | Done | No effect |
| Container restart | Done | No effect |

---

## 7. Next Steps (Not Yet Attempted)

1. **Add debug logging at AIMessage creation point** — in the Turn 1 path, log `additional_kwargs` immediately after `message_chunk_to_message` and after `agenerate_from_stream` returns, before LangGraph stores it.

2. **Check PostgreSQL checkpointer serde** — read `AsyncPostgresSaver.serde` and the message serialization/deserialization codec:
   ```bash
   docker exec surfsense-backend-1 python3 -c "
   from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
   import inspect
   print(inspect.getsource(AsyncPostgresSaver))
   "
   ```

3. **Override `ainvoke` in `SanitizedChatLiteLLM`** instead of `_create_message_dicts` — intercept the returned `AIMessage` and ensure `reasoning_content` is in `additional_kwargs`:
   ```python
   async def ainvoke(self, input, config=None, **kwargs):
       result = await super().ainvoke(input, config, **kwargs)
       # If result has reasoning_content in response metadata but not additional_kwargs,
       # copy it over here
       return result
   ```

4. **Try `deepseek/deepseek-reasoner` model prefix** instead of `openai/deepseek-v4-flash` — the `deepseek/` prefix routes through LiteLLM's DeepSeek-specific transformer which may handle `reasoning_content` in message history natively.

5. **Disable streaming for DeepSeek** — when `streaming=False`, `ChatLiteLLM._agenerate` calls `self._create_chat_result(response)` directly instead of going through `agenerate_from_stream`. Check if this path better preserves `reasoning_content`.

6. **Intercept at LangGraph `add_messages` level** — wrap the state update to ensure `reasoning_content` is preserved. This would require customizing the `AgentState` definition.

---

## 8. Key File Locations

| File | Purpose |
|------|---------|
| `/app/app/agents/new_chat/llm_config.py` | `SanitizedChatLiteLLM` class, `_create_message_dicts` override |
| `/app/app/agents/new_chat/chat_deepagent.py` | Agent creation, middleware stack |
| `/usr/local/lib/python3.12/site-packages/langchain_litellm/chat_models/litellm.py` | `_convert_message_to_dict` (patched), `_astream`, `_agenerate` |
| `/usr/local/lib/python3.12/site-packages/langchain/agents/factory.py` | `_execute_model_async`, `_handle_model_output`, `amodel_node` |
| `/usr/local/lib/python3.12/site-packages/deepagents/graph.py` | `create_deep_agent` internals |
| `/usr/local/lib/python3.12/site-packages/langgraph/checkpoint/postgres/aio.py` | PostgreSQL checkpointer serde |
| `/home/shiyu/Documents/surfsense/llm_config_patched.py` | Local copy of llm_config with debug prints |

---

## 9. DB / Config

- **LLM id=22** in `global_llm_config.yaml`: `deepseek-v4-flash` @ `https://api.deepseek.com`
- `searchspaces.agent_llm_id = 22` for the target search space
- Provider mapping: `"DEEPSEEK": "openai"` → model sent to LiteLLM as `openai/deepseek-v4-flash` with `api_base=https://api.deepseek.com`

---

## 10. Workaround Options (Not Implemented)

- **Use `deepseek-chat` (non-reasoner)** instead of `deepseek-v4-flash` — doesn't use thinking mode, so no `reasoning_content` issue.
- **Use a non-streaming mode** (set `streaming=False` for DeepSeek) and check if `_create_chat_result` path preserves `additional_kwargs`.
- **Use Claude or GPT** as agent LLM — already working (Claude at 81% in SurfSense benchmark).

---

## 11. Implemented Fix (2026-05-02)

Applied in `llm_config_patched.py` and deployed to:

- `/app/app/agents/new_chat/llm_config.py` in `surfsense-backend-1`
- `/app/app/agents/new_chat/llm_config.py` in `surfsense-celery_worker-1`

### Changes

1. **Stop mutating state messages in place**
  - `_sanitize_messages()` now deep-copies each message before sanitizing.
  - This prevents accidental corruption of graph state objects.

2. **Recover reasoning from unsanitized content blocks**
  - Added `_extract_reasoning_content_from_blocks()`.
  - If `additional_kwargs["reasoning_content"]` is missing, extract from `content` blocks of type `thinking`.

3. **Last-resort DeepSeek guardrail**
  - In `_create_message_dicts()`, if an assistant message has `tool_calls` but no `reasoning_content`, inject:
    - `reasoning_content = "[missing_reasoning_content]"`
  - This avoids DeepSeek Turn-2 rejection when upstream streaming paths lose the original field.

### Validation

Command:

```bash
python3 scripts/run_surfsense_benchmark_deepseekflash.py --max-questions 1 --start-question 1 --run-name test_fix_reasoning_1q_fallback
```

Result:

- `request_failures: 0`
- `overall_correct: 1 / 1 (100%)`
- No new `reasoning_content in thinking mode must be passed back` errors in fresh backend logs.
