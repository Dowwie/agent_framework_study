# HMP Context: aws-strands

## Quick Facts

- **Repository**: https://github.com/awslabs/strands (AWS Labs)
- **Primary Language**: Python
- **Architecture Style**: Modular with experimental features
- **Target Use Case**: AWS Bedrock-focused agent framework with multi-modal support
- **Key Innovation**: Bidirectional streaming agents + graph-based multi-agent coordination

### Async/Streaming Model
**Approach**: Native async/await throughout

- Pure asyncio (no sync wrappers)
- AsyncGenerator for streaming (backpressure-aware)
- Explicit task management via `_TaskPool`
- Concurrent tool execution (optional)

**Implications**:

### Streaming Mentions
- **Key Innovation**: Bidirectional streaming agents + graph-based multi-agent coordination
- AsyncGenerator for streaming (backpressure-aware)
- ✅ Composable streaming
- **Model**: ABC with 4 abstract methods (config, stream, structured output)
**Alternative Architecture**: Bidirectional streaming agent

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `src/strands/event_loop/_recover_message_on_max_tokens_reached.py`
- `src/strands/event_loop/streaming.py`
- `src/strands/experimental/bidi/models/__init__.py`
- `src/strands/experimental/bidi/models/gemini_live.py`
- `src/strands/experimental/bidi/models/model.py`
- `src/strands/experimental/bidi/models/nova_sonic.py`
- `src/strands/experimental/bidi/models/openai_realtime.py`
- `src/strands/experimental/bidi/types/model.py`
- `src/strands/experimental/steering/context_providers/__init__.py`
- `src/strands/experimental/steering/context_providers/ledger_provider.py`
- `src/strands/experimental/steering/handlers/llm/__init__.py`
- `src/strands/experimental/steering/handlers/llm/llm_handler.py`
- `src/strands/experimental/steering/handlers/llm/mappers.py`
- `src/strands/experimental/tools/tool_provider.py`
- `src/strands/models/__init__.py`
- `src/strands/models/_validation.py`
- `src/strands/models/anthropic.py`
- `src/strands/models/bedrock.py`
- `src/strands/models/gemini.py`
- `src/strands/models/litellm.py`
- `src/strands/models/llamaapi.py`
- `src/strands/models/llamacpp.py`
- `src/strands/models/mistral.py`
- `src/strands/models/model.py`
- `src/strands/models/ollama.py`
- `src/strands/models/openai.py`
- `src/strands/models/sagemaker.py`
- `src/strands/models/writer.py`
- `src/strands/tools/mcp/mcp_client.py`
- `src/strands/types/streaming.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy