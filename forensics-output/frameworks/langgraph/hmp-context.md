# HMP Context: langgraph

## Quick Facts

- **Repository**: https://github.com/langchain-ai/langgraph
- **Primary language**: Python (with TypeScript SDK)
- **Architecture style**: Modular monorepo (multiple libraries)
- **Core paradigm**: Graph-based workflow orchestration using Bulk Synchronous Parallel (BSP) model

### Async/Streaming Model
- **Pattern**: Separate sync and async loop implementations
- **No wrappers**: `SyncPregelLoop` and `AsyncPregelLoop` share logic via inheritance
- **APIs**: `invoke` / `ainvoke`, `stream` / `astream`, `batch` / `abatch`
- **Tradeoff**: Code duplication vs optimal performance for each paradigm

**Assessment**: Excellent. Avoids sync-wrapping-async anti-patterns. Clean separation.

### Schema Generation (from tool-interface-analysis)
- **Method**: Delegated to LangChain (Pydantic-based)
- **Location**: `libs/prebuilt/langgraph/prebuilt/tool_node.py`
- **Expressiveness**: Rich (Pydantic models, docstrings)

### Streaming Mentions
- **APIs**: `invoke` / `ainvoke`, `stream` / `astream`, `batch` / `abatch`
   - Multiple stream modes (values, updates, debug)
   - LLM token streaming
- ✅ Observability (streaming modes)
- Streaming modes

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `docs/_scripts/generate_llms_text.py`
- `docs/docs/tutorials/chatbot-simulation-evaluation/simulation_utils.py`
- `docs/docs/tutorials/llm-compiler/math_tools.py`
- `docs/docs/tutorials/llm-compiler/output_parser.py`
- `examples/chatbot-simulation-evaluation/simulation_utils.py`
- `libs/langgraph/langgraph/graph/message.py`
- `libs/langgraph/langgraph/pregel/_messages.py`
- `libs/langgraph/langgraph/pregel/protocol.py`
- `libs/langgraph/tests/fake_chat.py`
- `libs/langgraph/tests/messages.py`
- `libs/langgraph/tests/test_messages_state.py`
- `libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py`
- `libs/prebuilt/tests/messages.py`
- `libs/prebuilt/tests/model.py`
- `libs/sdk-py/langgraph_sdk/client.py`
- `libs/sdk-py/tests/test_assistants_client.py`
- `libs/sdk-py/tests/test_client_stream.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy