# Tool Interface Context: aws-strands

## Quick Facts

- **Repository**: https://github.com/awslabs/strands (AWS Labs)
- **Primary Language**: Python
- **Architecture Style**: Modular with experimental features
- **Target Use Case**: AWS Bedrock-focused agent framework with multi-modal support
- **Key Innovation**: Bidirectional streaming agents + graph-based multi-agent coordination

### Tool Interface Overview
**Schema Generation**: Hybrid declarative/imperative

- **Class-based**: Manual schema definition
- **Function-based**: Introspection from type annotations
- **Type Mapping**: str, int, float, bool, list, dict, Optional, Literal, Pydantic
- **ToolContext**: Framework-provided data (agent, invocation_state, interrupt support)

**Ergonomics**:
- ✅ Dual interface (class + decorator) for flexibility
- ✅ JSON Schema auto-generation
- ✅ Streaming tool results (incremental progress)
- ✅ Error status in ToolResult (errors as data)

### Error Handling Mentions
- ❌ No runtime validation (unlike Pydantic)
- ❌ Manual serialization (error-prone)
#### Error Handling
**Approach**: Fail-hard with explicit exceptions
- 8 custom exception types (EventLoopException, MaxTokensReachedException, etc.)

## Tool-Relevant Files

Priority files for tool interface analysis:

- `src/strands/experimental/bidi/tools/__init__.py`
- `src/strands/experimental/bidi/tools/stop_conversation.py`
- `src/strands/experimental/tools/__init__.py`
- `src/strands/experimental/tools/tool_provider.py`
- `src/strands/tools/__init__.py`
- `src/strands/tools/_caller.py`
- `src/strands/tools/_tool_helpers.py`
- `src/strands/tools/_validator.py`
- `src/strands/tools/decorator.py`
- `src/strands/tools/executors/__init__.py`
- `src/strands/tools/executors/_executor.py`
- `src/strands/tools/executors/concurrent.py`
- `src/strands/tools/executors/sequential.py`
- `src/strands/tools/loader.py`
- `src/strands/tools/mcp/__init__.py`
- `src/strands/tools/mcp/mcp_agent_tool.py`
- `src/strands/tools/mcp/mcp_client.py`
- `src/strands/tools/mcp/mcp_instrumentation.py`
- `src/strands/tools/mcp/mcp_types.py`
- `src/strands/tools/registry.py`
- `src/strands/_exception_notes.py`
- `src/strands/experimental/steering/core/action.py`
- `src/strands/hooks/registry.py`
- `src/strands/models/_validation.py`
- `src/strands/multiagent/a2a/executor.py`
- `src/strands/types/exceptions.py`
- `tests/strands/agent/hooks/test_hook_registry.py`
- `tests/strands/hooks/test_registry.py`
- `tests/strands/multiagent/a2a/test_executor.py`
- `tests/strands/test_exception_notes.py`
- `tests/strands/types/test_exceptions.py`
- `tests_integ/test_a2a_executor.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support