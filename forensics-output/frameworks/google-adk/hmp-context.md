# HMP Context: google-adk

## Quick Facts

- **Repository**: https://github.com/google/adk-python
- **Primary Language**: Python
- **Architecture Style**: Modular with service-oriented design
- **Framework Philosophy**: Code-first, production-ready Google agent framework
- **Primary Use Case**: Enterprise-grade agentic applications optimized for Gemini

### Async/Streaming Model
**Native asyncio with AsyncGenerator streaming**

Implications:
- **Pros**: Clean async boundaries throughout, no sync/async mixing, streaming-first architecture
- **Cons**: No parallel tool execution, sequential sub-agent execution, no timeout decorators
- **Notable**: Dual execution modes (standard `run_async()` + bidirectional streaming `run_live()`)

Key patterns:

### Schema Generation (from tool-interface-analysis)
**FunctionDeclaration Format**:
```python
FunctionDeclaration(
    name="tool_name",
    description="Tool description",
    parameters={

### Streaming Mentions
**Native asyncio with AsyncGenerator streaming**
- **Pros**: Clean async boundaries throughout, no sync/async mixing, streaming-first architecture
- **Notable**: Dual execution modes (standard `run_async()` + bidirectional streaming `run_live()`)
- AsyncGenerator[Event, None] for event streaming
- LiveRequestQueue for bidirectional streaming with WebSocket support

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `contributing/dev/utils/build_llms_txt.py`
- `contributing/samples/adk_answering_agent/gemini_assistant/__init__.py`
- `contributing/samples/adk_answering_agent/gemini_assistant/agent.py`
- `contributing/samples/hello_world_anthropic/__init__.py`
- `contributing/samples/hello_world_anthropic/agent.py`
- `contributing/samples/hello_world_anthropic/main.py`
- `contributing/samples/hello_world_apigeellm/agent.py`
- `contributing/samples/hello_world_apigeellm/main.py`
- `contributing/samples/hello_world_litellm/__init__.py`
- `contributing/samples/hello_world_litellm/agent.py`
- `contributing/samples/hello_world_litellm/main.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/__init__.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/agent.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/main.py`
- `contributing/samples/hello_world_stream_fc_args/__init__.py`
- `contributing/samples/hello_world_stream_fc_args/agent.py`
- `contributing/samples/litellm_inline_tool_call/__init__.py`
- `contributing/samples/litellm_inline_tool_call/agent.py`
- `contributing/samples/litellm_structured_output/__init__.py`
- `contributing/samples/litellm_structured_output/agent.py`
- `contributing/samples/litellm_with_fallback_models/__init__.py`
- `contributing/samples/litellm_with_fallback_models/agent.py`
- `contributing/samples/live_bidi_streaming_multi_agent/__init__.py`
- `contributing/samples/live_bidi_streaming_multi_agent/agent.py`
- `contributing/samples/live_bidi_streaming_single_agent/__init__.py`
- `contributing/samples/live_bidi_streaming_single_agent/agent.py`
- `contributing/samples/live_bidi_streaming_tools_agent/__init__.py`
- `contributing/samples/live_bidi_streaming_tools_agent/agent.py`
- `contributing/samples/mcp_streamablehttp_agent/__init__.py`
- `contributing/samples/mcp_streamablehttp_agent/agent.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy