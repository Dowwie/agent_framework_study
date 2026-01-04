# HMP Context: agent-zero

## Quick Facts

- **Repository**: repos/agent-zero
- **Primary Language**: Python
- **Architecture Style**: Monolithic with extension-based modularity
- **Key Dependencies**: LiteLLM (multi-provider LLM access), LangChain (message handling), FAISS (vector memory), Browser-Use (web automation)
- **Lines of Code**: 205 Python files, 1175 total files

### Streaming Mentions
- `models.py:456` - `async def unified_call()` for LLM streaming
**Control Flow Topology**: Nested async loops with callback-based streaming
                # 2. Call LLM with streaming callbacks
- Stream callbacks: `agent.py:385-414` - reasoning and response callbacks
- **Strength**: Clean async/await usage, streaming-first design

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `agents/_example/tools/response.py`
- `models.py`
- `python/api/api_message.py`
- `python/api/api_reset_chat.py`
- `python/api/api_terminate_chat.py`
- `python/api/chat_create.py`
- `python/api/chat_export.py`
- `python/api/chat_files_path_get.py`
- `python/api/chat_load.py`
- `python/api/chat_remove.py`
- `python/api/chat_reset.py`
- `python/api/message.py`
- `python/api/message_async.py`
- `python/extensions/agent_init/_10_initial_message.py`
- `python/extensions/before_main_llm_call/_10_log_for_stream.py`
- `python/extensions/message_loop_end/_10_organize_history.py`
- `python/extensions/message_loop_end/_90_save_chat.py`
- `python/extensions/message_loop_prompts_after/_50_recall_memories.py`
- `python/extensions/message_loop_prompts_after/_60_include_current_datetime.py`
- `python/extensions/message_loop_prompts_after/_70_include_agent_info.py`
- `python/extensions/message_loop_prompts_after/_75_include_project_extras.py`
- `python/extensions/message_loop_prompts_after/_91_recall_wait.py`
- `python/extensions/message_loop_prompts_before/_90_organize_history_wait.py`
- `python/extensions/message_loop_start/_10_iteration_no.py`
- `python/extensions/monologue_start/_60_rename_chat.py`
- `python/extensions/reasoning_stream/_10_log_from_stream.py`
- `python/extensions/reasoning_stream_chunk/_10_mask_stream.py`
- `python/extensions/reasoning_stream_end/_10_mask_end.py`
- `python/extensions/response_stream/_10_log_from_stream.py`
- `python/extensions/response_stream/_15_replace_include_alias.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy