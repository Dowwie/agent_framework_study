# HMP Context: swarm

## Quick Facts

- **Repository**: https://github.com/openai/swarm (OpenAI experimental framework)
- **Primary Language**: Python
- **Architecture Style**: Monolithic (single 293-line class)
- **Core Philosophy**: Simplicity over extensibility - educational/prototype framework
- **Total Core Code**: ~380 lines (core.py, types.py, util.py)

### Async/Streaming Model
**Approach**: No async/await support
- **Implementation**: Synchronous OpenAI client, blocking I/O on every LLM call
- **Trade-offs**: Simpler code, but blocks entire process on API calls
- **Missing**: Cannot leverage async benefits for concurrent tool execution or streaming

**Production Impact**: Not suitable for high-concurrency scenarios.

**Recommendation**: Add async variant using `AsyncOpenAI` client.

### Schema Generation (from tool-interface-analysis)
**Method**: Reflection via `inspect.signature()`

```python

### Streaming Mentions
- **Missing**: Cannot leverage async benefits for concurrent tool execution or streaming
### 1. Streaming Mode Code Duplication
**Issue**: ~100 lines duplicated between `run()` and `run_and_stream()`
**Fix**: Extract common loop body, wrap with streaming abstraction
   - Streaming with async generators

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `examples/customer_service_streaming/configs/__init__.py`
- `examples/customer_service_streaming/configs/general.py`
- `examples/customer_service_streaming/configs/prompts.py`
- `examples/customer_service_streaming/configs/tools/query_docs/handler.py`
- `examples/customer_service_streaming/configs/tools/send_email/handler.py`
- `examples/customer_service_streaming/configs/tools/submit_ticket/handler.py`
- `examples/customer_service_streaming/main.py`
- `examples/customer_service_streaming/prep_data.py`
- `examples/customer_service_streaming/src/__init__.py`
- `examples/customer_service_streaming/src/arg_parser.py`
- `examples/customer_service_streaming/src/evals/eval_function.py`
- `examples/customer_service_streaming/src/runs/run.py`
- `examples/customer_service_streaming/src/swarm/assistants.py`
- `examples/customer_service_streaming/src/swarm/conversation.py`
- `examples/customer_service_streaming/src/swarm/engines/assistants_engine.py`
- `examples/customer_service_streaming/src/swarm/engines/engine.py`
- `examples/customer_service_streaming/src/swarm/engines/local_engine.py`
- `examples/customer_service_streaming/src/swarm/swarm.py`
- `examples/customer_service_streaming/src/swarm/tool.py`
- `examples/customer_service_streaming/src/tasks/task.py`
- `examples/customer_service_streaming/src/utils.py`
- `examples/customer_service_streaming/src/validator.py`
- `tests/mock_client.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy