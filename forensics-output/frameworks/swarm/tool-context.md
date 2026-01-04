# Tool Interface Context: swarm

## Quick Facts

- **Repository**: https://github.com/openai/swarm (OpenAI experimental framework)
- **Primary Language**: Python
- **Architecture Style**: Monolithic (single 293-line class)
- **Core Philosophy**: Simplicity over extensibility - educational/prototype framework
- **Total Core Code**: ~380 lines (core.py, types.py, util.py)

### Tool Interface Overview
**Schema Generation**: Automatic via `inspect.signature()`
- **Ergonomics**: 9/10 - just add plain Python functions to list
- **Type Support**: Limited - only basic types (str, int, bool, etc.)
- **No support for**: Generics (List[str]), Pydantic models, Literal, enums

**Error Feedback**:
- ✅ Missing tool → sends error to LLM → allows self-correction
- ❌ Tool execution error → crashes agent → no recovery

**Magic Parameter Injection**:
```python

### Error Handling Mentions
#### Typing Strategy: Pydantic V2 with Minimal Validation
- **Trade-offs**: Type-safe interfaces with good DX, but no boundary validation
#### Error Handling: Fail-Fast with Single Exception
**Pattern**: Minimal error handling - propagate most exceptions
- **Only graceful handling**: Missing tool sends error to LLM (good pattern)

## Tool-Relevant Files

Priority files for tool interface analysis:

- `examples/airline/configs/tools.py`
- `examples/airline/evals/function_evals.py`
- `examples/basic/function_calling.py`
- `examples/customer_service_streaming/configs/tools/query_docs/handler.py`
- `examples/customer_service_streaming/configs/tools/send_email/handler.py`
- `examples/customer_service_streaming/configs/tools/submit_ticket/handler.py`
- `examples/customer_service_streaming/src/evals/eval_function.py`
- `examples/customer_service_streaming/src/swarm/tool.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support