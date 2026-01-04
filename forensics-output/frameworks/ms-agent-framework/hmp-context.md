# HMP Context: ms-agent-framework

## Quick Facts

- **Repository**: microsoft/agent-framework
- **Primary Languages**: C#/.NET and Python (dual-language framework)
- **Architecture Style**: Modular, protocol-based with graph-based workflow orchestration
- **Version Analyzed**: Python packages (core implementation)
- **Key Innovation**: Graph-based workflows with streaming, checkpointing, and time-travel capabilities

### Async/Streaming Model
- **Pattern**: Native async/await throughout
- **Key Characteristics**:
  - All core methods are `async def` (e.g., `async def run()`)
  - Streaming support via `AsyncIterable` generators
  - Context managers via `AbstractAsyncContextManager` and `AsyncExitStack`
  - No sync wrappers detected - fully async-native
- **Implications**:
  - Clean, performant async code

### Streaming Mentions
- **Key Innovation**: Graph-based workflows with streaming, checkpointing, and time-travel capabilities
  - Streaming support via `AsyncIterable` generators
  - Streaming: Real-time progress updates
   - Support streaming for real-time feedback
   - AsyncIterable for streaming

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `python/packages/ag-ui/agent_framework_ag_ui/_client.py`
- `python/packages/ag-ui/agent_framework_ag_ui/_message_adapters.py`
- `python/packages/ag-ui/agent_framework_ag_ui/_orchestration/_message_hygiene.py`
- `python/packages/ag-ui/getting_started/client.py`
- `python/packages/ag-ui/getting_started/client_advanced.py`
- `python/packages/ag-ui/getting_started/client_with_agent.py`
- `python/packages/ag-ui/tests/test_ag_ui_client.py`
- `python/packages/ag-ui/tests/test_message_adapters.py`
- `python/packages/ag-ui/tests/test_message_hygiene.py`
- `python/packages/anthropic/agent_framework_anthropic/__init__.py`
- `python/packages/anthropic/agent_framework_anthropic/_chat_client.py`
- `python/packages/anthropic/tests/conftest.py`
- `python/packages/anthropic/tests/test_anthropic_client.py`
- `python/packages/azure-ai-search/agent_framework_azure_ai_search/_search_provider.py`
- `python/packages/azure-ai-search/tests/test_search_provider.py`
- `python/packages/azure-ai/agent_framework_azure_ai/_chat_client.py`
- `python/packages/azure-ai/agent_framework_azure_ai/_client.py`
- `python/packages/azure-ai/tests/test_azure_ai_agent_client.py`
- `python/packages/azure-ai/tests/test_azure_ai_client.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_models.py`
- `python/packages/azurefunctions/tests/test_models.py`
- `python/packages/bedrock/agent_framework_bedrock/_chat_client.py`
- `python/packages/bedrock/tests/test_bedrock_client.py`
- `python/packages/chatkit/agent_framework_chatkit/__init__.py`
- `python/packages/chatkit/agent_framework_chatkit/_converter.py`
- `python/packages/chatkit/agent_framework_chatkit/_streaming.py`
- `python/packages/chatkit/tests/test_converter.py`
- `python/packages/chatkit/tests/test_streaming.py`
- `python/packages/core/agent_framework/_clients.py`
- `python/packages/core/agent_framework/_workflows/_base_group_chat_orchestrator.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy