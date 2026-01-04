# HMP Context: pydantic-ai

## Quick Facts

- **Repository**: https://github.com/pydantic/pydantic-ai
- **Primary Language**: Python
- **Architecture Style**: Modular with graph-based execution engine
- **Key Strength**: Type-safe, production-ready agent framework with excellent async support
- **Target Use Case**: Production applications requiring reliability, observability, and multi-provider support

### Async/Streaming Model
- **Pattern**: Async throughout, sync wrappers via `run_in_executor`
- **Streaming**: Two-level AsyncIterator protocols (model + events)
- **Execution**: Graph-based state machine with async nodes
- **Tool Support**: Auto-detects sync vs async, wraps sync in executor
- **Implications**: Modern Python, efficient I/O, excellent for production

**Key Innovation**: Streams auto-complete if not consumed, ensuring usage tracking accuracy.

### Schema Generation (from tool-interface-analysis)
**From function signature** + docstring:
```python
def generate_schema(
    func: Callable,
    docstring_format: DocstringFormat = 'auto'
) -> tuple[str, ObjectJsonSchema]:

### Streaming Mentions
class AgentStream(Generic[AgentDepsT, OutputDataT]):
    _raw_stream_response: models.StreamedResponse
#### Async Model: Native asyncio with Streaming First-Class
- **Streaming**: Two-level AsyncIterator protocols (model + events)
**Key Innovation**: Streams auto-complete if not consumed, ensuring usage tracking accuracy.

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `examples/pydantic_ai_examples/ag_ui/api/agentic_chat.py`
- `examples/pydantic_ai_examples/chat_app.py`
- `examples/pydantic_ai_examples/evals/example_04_compare_models.py`
- `examples/pydantic_ai_examples/evals/models.py`
- `examples/pydantic_ai_examples/pydantic_model.py`
- `examples/pydantic_ai_examples/slack_lead_qualifier/models.py`
- `examples/pydantic_ai_examples/stream_markdown.py`
- `examples/pydantic_ai_examples/stream_whales.py`
- `pydantic_ai_slim/pydantic_ai/_otel_messages.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/dbos/_model.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/prefect/_model.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_model.py`
- `pydantic_ai_slim/pydantic_ai/messages.py`
- `pydantic_ai_slim/pydantic_ai/models/__init__.py`
- `pydantic_ai_slim/pydantic_ai/models/anthropic.py`
- `pydantic_ai_slim/pydantic_ai/models/bedrock.py`
- `pydantic_ai_slim/pydantic_ai/models/cerebras.py`
- `pydantic_ai_slim/pydantic_ai/models/cohere.py`
- `pydantic_ai_slim/pydantic_ai/models/fallback.py`
- `pydantic_ai_slim/pydantic_ai/models/function.py`
- `pydantic_ai_slim/pydantic_ai/models/gemini.py`
- `pydantic_ai_slim/pydantic_ai/models/google.py`
- `pydantic_ai_slim/pydantic_ai/models/groq.py`
- `pydantic_ai_slim/pydantic_ai/models/huggingface.py`
- `pydantic_ai_slim/pydantic_ai/models/instrumented.py`
- `pydantic_ai_slim/pydantic_ai/models/mcp_sampling.py`
- `pydantic_ai_slim/pydantic_ai/models/mistral.py`
- `pydantic_ai_slim/pydantic_ai/models/openai.py`
- `pydantic_ai_slim/pydantic_ai/models/openrouter.py`
- `pydantic_ai_slim/pydantic_ai/models/outlines.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy