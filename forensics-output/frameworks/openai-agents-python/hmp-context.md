# HMP Context: openai-agents-python

## Quick Facts

- **Repository**: openai-agents-python
- **Primary Language**: Python
- **Architecture Style**: Modular monolith with clear separation of concerns
- **Design Philosophy**: Production-grade, OpenAI-native agent framework

### Async/Streaming Model
- **Primary API**: Async-first (`async def run()`, `async def stream_response()`)
- **Sync Support**: `run_sync()` method with sophisticated event loop management (lines 795-874 in run.py)
  - Handles Python 3.14 event loop changes
  - Reuses default loop across calls to support session instances with loop-bound primitives
  - Explicit cancellation handling on abort (KeyboardInterrupt)
- **Streaming**: True async streaming via `async for event in model.stream_response()`
  - Uses `asyncio.Queue` for event propagation
  - Background task dispatching for stream event handlers

### Streaming Mentions
- **Primary API**: Async-first (`async def run()`, `async def stream_response()`)
- **Streaming**: True async streaming via `async for event in model.stream_response()`
  - Background task dispatching for stream event handlers
  - Streaming mode supports soft cancellation via `_cancel_mode` flag
### 4. Streaming with Semantic Events

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `examples/agent_patterns/agents_as_tools_streaming.py`
- `examples/agent_patterns/llm_as_a_judge.py`
- `examples/agent_patterns/streaming_guardrails.py`
- `examples/basic/previous_response_id.py`
- `examples/basic/stream_function_call_args.py`
- `examples/basic/stream_items.py`
- `examples/basic/stream_text.py`
- `examples/handoffs/message_filter.py`
- `examples/handoffs/message_filter_streaming.py`
- `examples/mcp/streamablehttp_custom_client_example/main.py`
- `examples/mcp/streamablehttp_custom_client_example/server.py`
- `examples/mcp/streamablehttp_example/main.py`
- `examples/mcp/streamablehttp_example/server.py`
- `examples/memory/openai_session_example.py`
- `examples/model_providers/custom_example_agent.py`
- `examples/model_providers/custom_example_global.py`
- `examples/model_providers/custom_example_provider.py`
- `examples/model_providers/litellm_auto.py`
- `examples/model_providers/litellm_provider.py`
- `examples/reasoning_content/gpt_oss_stream.py`
- `examples/voice/streamed/__init__.py`
- `examples/voice/streamed/main.py`
- `examples/voice/streamed/my_workflow.py`
- `src/agents/extensions/models/__init__.py`
- `src/agents/extensions/models/litellm_model.py`
- `src/agents/extensions/models/litellm_provider.py`
- `src/agents/memory/openai_conversations_session.py`
- `src/agents/model_settings.py`
- `src/agents/models/__init__.py`
- `src/agents/models/_openai_shared.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy