# Tool Interface Synthesis Report

## Executive Summary

This report synthesizes findings from analyzing tool interfaces across 14 agent frameworks. The analysis reveals distinct architectural patterns, common best practices, and anti-patterns to avoid when designing tool systems for AI agents.

**Key Takeaways:**
1. **Pydantic dominates** schema generation (11/14 frameworks use it)
2. **Dual-interface pattern** (decorator + class) provides best DX
3. **Error-as-feedback** (not exceptions) enables LLM self-correction
4. **Parallel execution** via asyncio.gather is standard
5. **Context injection** patterns vary significantly in complexity

---

## Comparison Matrix

### Tool Modeling Approaches

| Framework | Primary Abstraction | Schema Generation | Built-in Tools | Parallel Exec |
|-----------|---------------------|-------------------|----------------|---------------|
| **LangGraph** | LangChain BaseTool | Pydantic introspection | 0 (delegates) | ✅ asyncio.gather |
| **pydantic-ai** | Tool[AgentDepsT] dataclass | Pydantic + docstring | 9 builtin + 2 common | ✅ asyncio.gather |
| **google-adk** | BaseTool ABC + FunctionTool | Pydantic model_json_schema | 40+ | ✅ async/await |
| **openai-agents** | FunctionTool dataclass + Union | Pydantic + strict mode | 10+ | ✅ asyncio.gather |
| **autogen** | Protocol + ABC hybrid | Pydantic model_validate | 20+ | ✅ asyncio.gather |
| **crewAI** | BaseTool + @tool decorator | inspect.signature + Pydantic | 90+ | ✅ ThreadPoolExecutor |
| **camel** | FunctionTool + BaseToolkit | Pydantic + docstring parsing | 70+ | ✅ ThreadPoolExecutor |
| **MetaGPT** | Pydantic Tool model | AST parsing + introspection | 18+ | ❌ LLM code gen |
| **aws-strands** | AgentTool ABC + @tool | inspect.signature | 0 (minimal) | ✅ via model API |
| **llama_index** | BaseTool + FunctionTool | Pydantic model_json_schema | 0 (ecosystem) | ✅ adapter pattern |
| **agno** | Function Pydantic model | Pydantic + Field metadata | 100+ | ✅ asyncio.gather |
| **ms-agent-framework** | ToolProtocol + BaseTool | Annotated[type, desc] | 0 (templates) | ✅ via orchestrator |
| **agent-zero** | Abstract Tool class | Manual markdown | 18 | ❌ Sequential |
| **swarm** | Plain callables | Hardcoded type map | 0 | ❌ (API flag ignored) |

### Context Injection Patterns

| Framework | Mechanism | Complexity | Type Safety |
|-----------|-----------|------------|-------------|
| **LangGraph** | InjectedState, InjectedStore, ToolRuntime | High (3 mechanisms) | ✅ Annotated types |
| **pydantic-ai** | RunContext[DepsT] auto-detection | Medium | ✅ Generic types |
| **google-adk** | ToolContext parameter | Low | ✅ Dataclass |
| **openai-agents** | RunContext/ToolContext signatures | Medium | ✅ Annotated |
| **autogen** | CancellationToken | Low | ✅ Protocol |
| **crewAI** | Fingerprint metadata injection | Low | ❌ Dict-based |
| **camel** | Agent reference via mixin | Medium | ⚠️ Optional |
| **MetaGPT** | None (code generation) | None | N/A |
| **aws-strands** | ToolContext dataclass | Low | ✅ Dataclass |
| **llama_index** | ToolOutput with context | Low | ✅ Pydantic |
| **agno** | Session state + dependencies | Medium | ✅ Pydantic |
| **ms-agent-framework** | Kwargs injection | Medium | ⚠️ Runtime |
| **agent-zero** | Agent reference in constructor | Low | ❌ Implicit |
| **swarm** | context_variables magic param | Low | ❌ Magic string |

### Error Handling Strategies

| Framework | Strategy | Self-Correction | Retry Mechanism |
|-----------|----------|-----------------|-----------------|
| **LangGraph** | ToolInvocationError + filtered errors | ✅ Detailed feedback | wrap_tool_call |
| **pydantic-ai** | ValidationError → RetryPromptPart | ✅ Structured errors | Per-tool max_retries |
| **google-adk** | {'error': message} dict | ✅ Natural language | LLM-driven |
| **openai-agents** | ModelBehaviorError + guardrails | ✅ Three-tier | failure_error_function |
| **autogen** | ToolException hierarchy | ✅ Structured | Agent-level iterations |
| **crewAI** | Error events + retry counter | ✅ Format reminders | 3 attempts default |
| **camel** | Exception → error string | ✅ Error message | LLM self-correction |
| **MetaGPT** | Python exceptions (natural) | ✅ Execution output | Agent loop |
| **aws-strands** | Unstructured error strings | ⚠️ Basic | None built-in |
| **llama_index** | ToolOutput.is_error flag | ✅ Error-as-data | LLM decides |
| **agno** | Structured error types | ✅ Detailed | Hook-based |
| **ms-agent-framework** | Circuit breakers | ✅ Limits enforced | max_invocations |
| **agent-zero** | Exception propagation | ⚠️ Basic | None |
| **swarm** | Asymmetric (graceful/crash) | ❌ Crashes on error | None |

---

## Common Patterns Identified

### 1. Dual-Interface Tool Definition

**Pattern**: Support both function-based and class-based tool definitions

**Frameworks**: pydantic-ai, google-adk, crewAI, camel, aws-strands, llama_index

```python
# Function-based (decorator)
@tool
def search(query: str) -> str:
    """Search the web."""
    return results

# Class-based (inheritance)
class SearchTool(BaseTool):
    def _run(self, query: str) -> str:
        return results
```

**Benefits**:
- Simple functions stay simple
- Complex tools get full class power
- Both converge to same internal representation

### 2. Pydantic-Based Schema Generation

**Pattern**: Use Pydantic's `model_json_schema()` for automatic schema generation

**Frameworks**: 11/14 (all except swarm, agent-zero, MetaGPT partially)

```python
# From function signature
def tool(query: str, limit: int = 10) -> list[str]: ...

# Generates
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "limit": {"type": "integer", "default": 10}
  },
  "required": ["query"]
}
```

**Benefits**:
- Zero manual schema writing
- Type validation at runtime
- Automatic nested model support

### 3. Error-as-Feedback Pattern

**Pattern**: Return structured errors to LLM instead of raising exceptions

**Frameworks**: LangGraph, pydantic-ai, google-adk, llama_index, autogen

```python
# Instead of raising
raise ToolError("Invalid input")

# Return structured error
return ToolOutput(
    is_error=True,
    content="Invalid input: query cannot be empty"
)
```

**Benefits**:
- LLM can self-correct
- No agent crash on tool failure
- Enables reflection-based retry

### 4. Context Injection via Annotated Types

**Pattern**: Use `Annotated[T, Injection]` to inject framework context

**Frameworks**: LangGraph, pydantic-ai, openai-agents, autogen

```python
from typing import Annotated

@tool
def search(
    query: str,
    state: Annotated[dict, InjectedState("messages")]
) -> str:
    # query visible to LLM, state injected by framework
    ...
```

**Benefits**:
- Clean separation of LLM-visible vs system parameters
- Type-safe injection
- Schema excludes injected params

### 5. Toolset/Toolkit Abstraction

**Pattern**: Group related tools with shared state/configuration

**Frameworks**: pydantic-ai, google-adk, camel, crewAI, autogen

```python
class DatabaseToolset(BaseToolset):
    def __init__(self, connection_string: str):
        self.db = connect(connection_string)

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.query),
            Tool(self.insert),
            Tool(self.update),
        ]
```

**Benefits**:
- Shared resources (connections, auth)
- Coherent tool namespacing
- Dynamic tool availability

### 6. Parallel Execution via asyncio.gather

**Pattern**: Execute multiple tool calls concurrently

**Frameworks**: 10/14 support parallel execution

```python
# Multiple tool calls in single turn
results = await asyncio.gather(
    tool1.invoke(args1),
    tool2.invoke(args2),
    tool3.invoke(args3),
)
```

**Benefits**:
- Significant speedup for independent tools
- Non-blocking I/O
- Resource efficiency

---

## Best Practices to Adopt

### 1. Auto-Conversion of Callables

**From**: llama_index, google-adk, autogen

```python
# User passes plain function
agent = Agent(tools=[my_function])

# Framework auto-wraps
if callable(tool) and not isinstance(tool, BaseTool):
    tool = FunctionTool.from_defaults(tool)
```

**Recommendation**: Always auto-wrap functions to reduce friction.

### 2. Filtered Validation Errors

**From**: LangGraph

```python
def _filter_validation_errors(error, injected_args):
    """Exclude injected args from error messages to LLM."""
    return [e for e in error.errors()
            if e["loc"][0] not in injected_args]
```

**Recommendation**: LLM should only see errors for parameters it controls.

### 3. Dynamic Tool Availability

**From**: pydantic-ai, openai-agents

```python
@agent.tool(
    is_enabled=lambda ctx, agent: ctx.user.role == "admin"
)
def delete_user(user_id: str) -> str:
    ...
```

**Recommendation**: Support runtime tool visibility based on context.

### 4. Per-Tool Timeout Configuration

**From**: pydantic-ai, camel

```python
@tool(timeout=5.0)
async def slow_api_call(query: str) -> str:
    ...
```

**Recommendation**: Allow individual tools to specify execution limits.

### 5. Strict Mode for Structured Output

**From**: openai-agents, autogen, crewAI

```python
def ensure_strict_json_schema(schema):
    # All properties required
    # additionalProperties: false
    # No defaults allowed
    ...
```

**Recommendation**: Support OpenAI strict mode for reliable JSON generation.

### 6. Hook System for Cross-Cutting Concerns

**From**: crewAI, agno

```python
@before_tool_call
def log_tool_usage(context: ToolCallContext):
    logger.info(f"Calling {context.tool_name}")

@after_tool_call
def sanitize_output(context: ToolCallContext):
    return redact_pii(context.result)
```

**Recommendation**: Hooks enable monitoring, security, caching without modifying tools.

### 7. Tool Wrapper for Retry/Caching

**From**: LangGraph

```python
def cache_wrapper(request, execute):
    if cached := get_cache(request.args):
        return cached
    result = execute(request)
    set_cache(request.args, result)
    return result

ToolNode(tools, wrap_tool_call=cache_wrapper)
```

**Recommendation**: Wrapper pattern enables middleware without tool modification.

### 8. Usage Limits Per Tool

**From**: crewAI, ms-agent-framework

```python
@tool(max_usage_count=10)
def expensive_api_call(query: str) -> str:
    """Limit calls to prevent cost overruns."""
    ...
```

**Recommendation**: Prevent infinite loops and control costs with per-tool limits.

---

## Anti-Patterns to Avoid

### 1. Silent Exception Suppression

**Observed in**: MetaGPT, agent-zero

```python
# BAD
try:
    validate_schema(tool)
except Exception:
    pass  # Tool registered anyway
```

**Problem**: Debugging becomes impossible when errors are silently swallowed.

**Fix**: Log warnings, provide verbose mode, or fail-fast option.

### 2. Global Mutable State

**Observed in**: MetaGPT (TOOL_REGISTRY), crewAI (hooks), camel (executor)

```python
# BAD
TOOL_REGISTRY = ToolRegistry()  # Global singleton
```

**Problem**: Precludes isolated testing, unpredictable in concurrent scenarios.

**Fix**: Dependency injection, scoped registries per agent/session.

### 3. Hardcoded Type Mappings

**Observed in**: swarm, agent-zero

```python
# BAD
TYPE_MAP = {
    "str": "string",
    "int": "integer",
    # Only 7 types supported
}
```

**Problem**: Breaks for complex types (List, Dict, Union, Pydantic models).

**Fix**: Use Pydantic's type system for comprehensive coverage.

### 4. String-Based Tool Identification

**Observed in**: Most frameworks

```python
# BAD
tools = ["search", "calculate"]  # Typo-prone
```

**Problem**: No IDE autocomplete, refactoring-unfriendly, runtime errors.

**Fix**: Typed identifiers, enums, or direct function references.

### 5. Mutation of Input Schemas

**Observed in**: openai-agents, crewAI, camel

```python
# BAD
def ensure_strict_json_schema(schema: dict) -> dict:
    schema["additionalProperties"] = False  # Mutates input!
    return schema
```

**Problem**: Side effects if schema reused, hard to debug.

**Fix**: Return new dict, never mutate input.

### 6. Dual Usage Counter Tracking

**Observed in**: crewAI

```python
# BAD
self.current_usage_count += 1
if self._original_tool:
    self._original_tool.current_usage_count = self.current_usage_count
```

**Problem**: Must synchronize state between wrapper and original.

**Fix**: Single source of truth for mutable state.

### 7. No Tool Versioning

**Observed in**: All 14 frameworks

```python
# Missing
class Tool:
    version: str  # Not present
```

**Problem**: Schema changes break deployed agents, no rollback capability.

**Fix**: Add version field, support multiple versions concurrently.

### 8. Description Length Check as Optional

**Observed in**: llama_index

```python
# BAD
def to_openai_tool(self, skip_length_check: bool = False):
    if not skip_length_check and len(self.description) > 1024:
        raise ValueError(...)
```

**Problem**: Runtime errors at API call time instead of registration.

**Fix**: Always validate, no escape hatch.

### 9. Manual JSON Schema Field Filtering

**Observed in**: llama_index, MetaGPT

```python
# BAD
parameters = {
    k: v for k, v in parameters.items()
    if k in ["type", "properties", "required", "$defs"]
}
```

**Problem**: Brittle, misses new fields, breaks on schema evolution.

**Fix**: Use Pydantic's JSON Schema configuration options.

### 10. Asymmetric Error Handling

**Observed in**: swarm

```python
# BAD - graceful for missing tools, crash for execution errors
if name not in tools:
    return f"Tool {name} not found"  # Graceful

result = tool(**args)  # Crashes on error
```

**Problem**: Inconsistent behavior, hard for LLM to predict.

**Fix**: Consistent error handling for all failure modes.

---

## Framework-Specific Innovations

### LangGraph: State Injection Architecture
- Three-tier injection: InjectedState, InjectedStore, ToolRuntime
- Pre-analyzed at initialization for runtime efficiency
- Filtered validation errors exclude injected args

### pydantic-ai: Validation-as-Feedback
- ValidationError → RetryPromptPart → LLM self-correction
- Three retry layers: graph, tool, and ModelRetry exception
- ToolDefinition.kind system (function/output/external/unapproved)

### google-adk: Toolset Dynamic Discovery
- BaseToolset.get_tools() returns context-dependent tool list
- tool_filter for whitelist/predicate filtering
- HITL via ToolConfirmation request/response

### openai-agents: Guardrail System
- Input/output guardrails with three behaviors (allow/reject/raise)
- Dynamic enablement via is_enabled callback
- Strict mode conversion for OpenAI compatibility

### autogen: Workbench Abstraction
- Workbench groups tools with shared lifecycle
- StaticStreamWorkbench for streaming results
- Tool overrides for name/description customization

### crewAI: Usage Limits & Hooks
- max_usage_count prevents infinite loops
- result_as_answer for early termination
- Before/after tool call hooks

### camel: LLM Schema Synthesis
- synthesize_schema=True uses LLM to generate missing docstrings
- Progressive streaming with parallel execution
- Secure result store for masking sensitive outputs

### MetaGPT: Dual Schema Generation
- Introspection-based (runtime) + AST-based (static)
- Tag-based discovery and BM25 recommendation
- Selective method exposure (ClassName:method1,method2)

### agno: Comprehensive Hook System
- pre_hook, post_hook, tool_hooks
- File-based caching with MD5 keys and TTL
- 100+ built-in tools across 15+ categories

### ms-agent-framework: Circuit Breakers
- max_invocations, max_invocation_exceptions
- Kwargs injection for runtime context
- Approval flow with content types

---

## Recommendations for New Framework

### Core Architecture

1. **Use Protocol + ABC Hybrid**
   - Protocol for duck typing (external tools satisfy interface)
   - ABC for shared implementation (common validation, serialization)

2. **Pydantic for Everything**
   - Tool input validation
   - Schema generation
   - Configuration management

3. **Dual-Interface Tool Definition**
   - `@tool` decorator for simple functions
   - `BaseTool` class for complex stateful tools
   - Auto-conversion for plain callables

4. **Error-as-Data Pattern**
   - ToolResult with is_error flag
   - Structured error details for LLM
   - Never crash on tool execution failure

### Schema Generation

5. **Automatic from Type Hints**
   - Use `model_json_schema()` for all schema generation
   - Parse docstrings for parameter descriptions
   - Support Google, NumPy, Sphinx docstring formats

6. **Strict Mode Support**
   - Optional strict mode per tool
   - All properties required, no additionalProperties
   - Automatic conversion for OpenAI compatibility

7. **Schema Validation at Registration**
   - Fail-fast on invalid schemas
   - Validate description length limits
   - Enforce required field completeness

### Execution

8. **Parallel by Default**
   - `asyncio.gather` for concurrent tool calls
   - Per-tool sequential flag for stateful operations
   - Automatic sync-to-async bridging

9. **Configurable Timeouts**
   - Per-tool timeout configuration
   - Default timeout with override capability
   - Graceful timeout → retry message to LLM

10. **Wrapper/Middleware Pattern**
    - Pre/post execution hooks
    - Retry, caching, logging via wrappers
    - Immutable request pattern

### Context & State

11. **Clean Context Injection**
    - Single RunContext type with typed dependencies
    - Annotated types for injected parameters
    - Exclude injected params from LLM-visible schema

12. **Toolset for Grouped Tools**
    - Shared state and configuration
    - Dynamic tool availability
    - Lifecycle management (start/stop)

### Observability

13. **Structured Tool Events**
    - ToolCallStarted, ToolCallCompleted, ToolCallFailed
    - Include timing, arguments, results
    - Correlation IDs for tracing

14. **Usage Tracking**
    - Per-tool invocation counts
    - Optional usage limits
    - Cost estimation support

### Safety

15. **Human-in-the-Loop**
    - requires_approval flag
    - Approval request/response protocol
    - Timeout for pending approvals

16. **Input/Output Guardrails**
    - Pre-execution validation hooks
    - Post-execution output filtering
    - Allow/reject/raise behaviors

---

## Conclusion

The agent framework ecosystem has converged on several patterns:
- **Pydantic** is the de facto standard for schema generation and validation
- **Error feedback** (not exceptions) enables LLM self-correction
- **Parallel execution** is expected for production use
- **Context injection** via annotations provides clean separation

Key differentiators between frameworks:
- **Sophistication of error handling** (LangGraph, pydantic-ai excel)
- **Built-in tool breadth** (crewAI, agno, camel lead)
- **Context injection complexity** (LangGraph most complex, swarm simplest)
- **Dynamic tool management** (pydantic-ai, google-adk most flexible)

For a new framework, prioritize:
1. Developer experience (auto-conversion, zero-boilerplate)
2. LLM self-correction (structured error feedback)
3. Production reliability (timeouts, retries, observability)
4. Extensibility (hooks, wrappers, toolsets)
