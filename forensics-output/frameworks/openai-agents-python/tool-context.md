# Tool Interface Context: openai-agents-python

## Quick Facts

- **Repository**: openai-agents-python
- **Primary Language**: Python
- **Architecture Style**: Modular monolith with clear separation of concerns
- **Design Philosophy**: Production-grade, OpenAI-native agent framework

### Tool Interface Overview
- **Primary API**: `@function_tool` decorator
  - Introspects function signature via `inspect.signature()`
  - Generates JSON schema from type annotations (via `function_schema()`)
  - Automatic strict mode schema conversion (OpenAI-compatible)
- **Context Injection**: Supports three signatures
  1. No context: `def tool(arg: str) -> str`
  2. RunContext: `def tool(context: RunContext, arg: str) -> str`
  3. ToolContext: `def tool(context: ToolContext, arg: str) -> str`
- **Schema Overrides**: `@function_tool(name_override=..., description_override=...)`
- **Dynamic Enablement**: `is_enabled: bool | Callable[[RunContext, Agent], bool]`
  - Tools can be conditionally visible based on context/state
- **Hosted Tools**: `FileSearchTool`, `WebSearchTool`, `ComputerTool` (OpenAI-native)

### Error Handling Mentions
  - Extensive `__post_init__` validation (lines 257-388 in agent.py)
  - Includes `@model_validator` for cross-field validation
  - Strength: Explicit validation in `__post_init__` makes contract clear
  - Weakness: Manual validation code is verbose (130+ lines in Agent.__post_init__)
#### Error Handling: Structured Exceptions with Run Context

## Tool-Relevant Files

Priority files for tool interface analysis:

- `examples/agent_patterns/agents_as_tools.py`
- `examples/agent_patterns/agents_as_tools_conditional.py`
- `examples/agent_patterns/agents_as_tools_streaming.py`
- `examples/agent_patterns/forcing_tool_use.py`
- `examples/basic/image_tool_output.py`
- `examples/basic/stream_function_call_args.py`
- `examples/basic/tool_guardrails.py`
- `examples/basic/tools.py`
- `examples/tools/apply_patch.py`
- `examples/tools/code_interpreter.py`
- `examples/tools/computer_use.py`
- `examples/tools/file_search.py`
- `examples/tools/image_generator.py`
- `examples/tools/local_shell.py`
- `examples/tools/shell.py`
- `examples/tools/web_search.py`
- `examples/tools/web_search_filters.py`
- `src/agents/function_schema.py`
- `src/agents/strict_schema.py`
- `src/agents/tool.py`
- `examples/reasoning_content/runner_example.py`
- `src/agents/exceptions.py`
- `src/agents/models/default_models.py`
- `src/agents/realtime/_default_tracker.py`
- `src/agents/realtime/runner.py`
- `src/agents/util/_error_tracing.py`
- `src/agents/voice/exceptions.py`
- `tests/mcp/test_runner_calls_mcp.py`
- `tests/mcp/test_server_errors.py`
- `tests/models/test_default_models.py`
- `tests/realtime/test_runner.py`
- `tests/test_agent_runner.py`
- `tests/test_agent_runner_streamed.py`
- `tests/test_agent_runner_sync.py`
- `tests/test_computer_action.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support