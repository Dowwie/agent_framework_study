# Resilience Analysis: pydantic-ai

## Summary

- **Retry Strategy**: Multi-level - graph-level retries, tool-level retries, HTTP-level retries (tenacity)
- **Error Propagation**: Structured exception hierarchy with context preservation
- **Usage Limits**: Token-based limits with pre/post request checking
- **Classification**: **Layered resilience with graceful degradation**

## Detailed Analysis

### Exception Hierarchy

**Structured error types**:

```python
# Top-level errors
class UserError(RuntimeError): ...  # User mistakes (bad config, etc.)
class AgentRunError(RuntimeError): ...  # Runtime failures

# Specialized agent errors
class UsageLimitExceeded(AgentRunError): ...  # Token limits hit
class UnexpectedModelBehavior(AgentRunError): ...  # Model violated expectations
class ModelAPIError(AgentRunError): ...  # Provider API failures
class ModelHTTPError(ModelAPIError): ...  # HTTP-specific failures

# Control flow exceptions (not errors)
class ModelRetry(Exception): ...  # Tool requests retry
class CallDeferred(Exception): ...  # Tool needs external execution
class ApprovalRequired(Exception): ...  # Human-in-the-loop required
class ToolRetryError(Exception): ...  # Internal retry signaling

# Fallback handling
class FallbackExceptionGroup(ExceptionGroup[Any]): ...  # Multiple fallback failures
```

**Key design**: Separation of user errors, runtime errors, and control flow exceptions.

### Three-Layer Retry System

#### Layer 1: Graph-Level Retries (Output Validation)

Managed by `GraphAgentState.retries`:
```python
@dataclasses.dataclass(kw_only=True)
class GraphAgentState:
    retries: int = 0

    def increment_retries(
        self,
        max_result_retries: int,
        error: BaseException | None = None,
        model_settings: ModelSettings | None = None,
    ) -> None:
        self.retries += 1
        if self.retries > max_result_retries:
            # Special case: incomplete tool call due to token limit
            if (model_response.finish_reason == 'length'
                and isinstance(tool_call.args, incomplete)):
                raise exceptions.IncompleteToolCall(
                    f'Model token limit ({max_tokens}) exceeded while generating tool call...'
                )
            # Generic retry exhausted
            raise exceptions.UnexpectedModelBehavior(
                f'Exceeded maximum retries ({max_result_retries}) for output validation'
            ) from error
```

**Triggers**:
- ValidationError during output processing
- Empty model responses
- Invalid tool call formats

#### Layer 2: Tool-Level Retries

Tools can request retries via `ModelRetry` exception:
```python
# From tool code
raise ModelRetry('Retry this tool call with corrected arguments')

# Framework catches and adds retry prompt to next request
```

**Tool retry mechanism**:
- Tool throws `ModelRetry` with message
- Framework captures error context
- Adds `RetryPromptPart` to next model request
- Model sees error feedback and retries

**Max retries per tool**:
```python
@dataclass(kw_only=True)
class ToolsetTool(Generic[AgentDepsT]):
    max_retries: int  # Per-tool retry limit
```

#### Layer 3: HTTP-Level Retries (Tenacity)

Optional httpx transport wrapper:
```python
from pydantic_ai.retries import TenacityTransport, RetryConfig

transport = TenacityTransport(
    RetryConfig(
        retry=retry_if_exception_type(HTTPStatusError),
        wait=wait_retry_after(max_wait=300),  # Respects Retry-After header
        stop=stop_after_attempt(5),
        reraise=True
    ),
    wrapped=HTTPTransport(),
    validate_response=lambda r: r.raise_for_status()
)

client = httpx.Client(transport=transport)
```

**Features**:
- Respects HTTP Retry-After headers
- Exponential backoff
- Configurable via tenacity strategies

### Usage Limits & Circuit Breaking

**Token limit enforcement**:

```python
@dataclass(repr=False, kw_only=True)
class UsageLimits:
    input_tokens_limit: int | None = None
    output_tokens_limit: int | None = None
    total_tokens_limit: int | None = None
    request_limit: int | None = None
    count_tokens_before_request: bool = False  # Pre-flight check

    def check_before_request(self, usage: Usage) -> None:
        """Check limits before making a request."""
        if self.count_tokens_before_request:
            self._check_tokens(usage)
            self._check_requests(usage)

    def check_tokens(self, usage: Usage) -> None:
        """Check token limits after receiving response."""
        if self.input_tokens_limit and usage.input_tokens > self.input_tokens_limit:
            raise UsageLimitExceeded(
                f'Input token limit of {self.input_tokens_limit} exceeded, used {usage.input_tokens}'
            )
        # Similar for output_tokens_limit, total_tokens_limit
```

**Two-phase checking**:
1. **Before request**: Estimate tokens (if `count_tokens_before_request` enabled)
2. **After response**: Verify actual usage

**Progressive limit enforcement**:
- First check: `check_before_request()`
- After model response: `check_tokens()`
- Raises `UsageLimitExceeded` if violated

### Error Propagation & Context

**Context preservation via exception chaining**:
```python
raise exceptions.UnexpectedModelBehavior(message) from error
```

**Detailed error messages**:
- `IncompleteToolCall`: Includes `max_tokens` setting hint
- `ModelRetry`: Includes retry message for model context
- `ToolRetryError`: Formats validation errors for tool call arguments

**Example error message construction**:
```python
# From ToolRetryError
error_messages: list[str] = []
for err in errors:
    if 'loc' in err and 'msg' in err:
        location = '.'.join(str(loc) for loc in err['loc'])
        error_messages.append(f'{location}: {err["msg"]}')

message = f'Tool call validation failed for tool {tool_name!r}:\n' + '\n'.join(f'- {msg}' for msg in error_messages)
```

### Graceful Degradation Patterns

**Empty response handling**:
```python
# From CallToolsNode._run_stream
if not self.model_response.parts:
    if self.model_response.finish_reason == 'length':
        # Token limit - fail fast with clear error
        raise UnexpectedModelBehavior(...)

    # Retry with previous text if available
    if text_processor:
        for message in reversed(ctx.state.message_history):
            if text := extract_text(message):
                try:
                    return await self._handle_text_response(ctx, text, text_processor)
                except ToolRetryError:
                    pass  # Ignore invalid text from previous response

    # Last resort: retry with empty request
    ctx.state.increment_retries(...)
    self._next_node = ModelRequestNode(ModelRequest(parts=[], instructions=...))
```

**Fallback model support**:
```python
class FallbackExceptionGroup(ExceptionGroup[Any]):
    """Raised when all fallback models fail."""

# Usage: Try model A, then B, then C
# If all fail, raise FallbackExceptionGroup with all errors
```

### Deferred Tool Execution (Manual Retry)

**Human-in-the-loop pattern**:
```python
raise ApprovalRequired("This tool requires approval")

# Agent returns DeferredToolRequests
deferred = await agent.run(prompt)
if isinstance(deferred, DeferredToolRequests):
    # Show to user, get approval
    approved_results = get_user_approval(deferred)
    # Resume with approved results
    final = await agent.run(prompt, deferred_tool_results=approved_results)
```

**Deferred execution flow**:
1. Tool raises `CallDeferred` or `ApprovalRequired`
2. Agent pauses and returns `DeferredToolRequests`
3. External system executes/approves tools
4. Resume via `run(..., deferred_tool_results=...)`
5. Graph skips ModelRequestNode, goes directly to CallToolsNode

### Observability & Error Tracking

**OpenTelemetry integration**:
- Token usage tracked and exported
- Error details in span attributes
- Run IDs for correlation

**Usage tracking across retries**:
```python
# Usage accumulates across retries
ctx.state.usage.requests += 1
ctx.state.usage.incr(response.usage)
```

## Code References

- `pydantic_ai_slim/pydantic_ai/exceptions.py` - Exception hierarchy
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:95` - GraphAgentState.increment_retries
- `pydantic_ai_slim/pydantic_ai/retries.py` - Tenacity HTTP retry transport
- `pydantic_ai_slim/pydantic_ai/usage.py:18` - UsageLimits implementation
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:600` - Empty response fallback logic

## Implications for New Framework

1. **Adopt**: Three-layer retry system
   - Graph-level: Output validation retries
   - Tool-level: Tool-specific retries with feedback
   - HTTP-level: Transport retries for transient failures
   - Each layer addresses different failure modes

2. **Adopt**: Structured exception hierarchy
   - Separate user errors from runtime errors
   - Use control flow exceptions for non-error conditions
   - Enable targeted exception handling

3. **Adopt**: Two-phase token limit checking
   - Pre-flight estimation (optional, expensive)
   - Post-flight verification (required, accurate)
   - Fail fast before wasting tokens

4. **Adopt**: Graceful degradation for empty responses
   - Fall back to previous text responses
   - Retry with empty request as last resort
   - Provide clear error messages for token limit issues

5. **Consider**: Deferred execution pattern
   - Excellent for human-in-the-loop workflows
   - Enables external tool execution
   - Requires careful state management

6. **Adopt**: Usage tracking across retries
   - Cumulative usage in mutable state
   - OpenTelemetry export for observability
   - Helps debug retry storms

## Anti-Patterns Observed

1. **Minor**: Silent fallback in empty response handling
   - Tries previous text response without logging
   - `except ToolRetryError: pass` - silent failure
   - **Recommendation**: Log fallback attempts for debugging

2. **Minor**: Implicit retry via empty request
   - `ModelRequest(parts=[], instructions=...)` is confusing
   - Not obvious this triggers a retry
   - **Recommendation**: Explicit retry node type or comment

3. **Good practice**: Exception chaining for context
   - `raise ... from error` preserves stack traces
   - Detailed error messages with actionable hints
   - No context is lost

## Notable Patterns Worth Adopting

1. **Retry-After header respect**:
   - `wait_retry_after()` custom wait strategy
   - Honors server-provided backoff times
   - Reduces unnecessary retry load

2. **Tool retry with model feedback**:
   - Don't just retry silently
   - Give model the error message
   - Enables model to self-correct

3. **Per-tool max_retries**:
   - Different tools have different reliability
   - Prevents infinite loops on broken tools
   - Configurable at tool level

4. **Incomplete tool call detection**:
   - Detect `finish_reason == 'length'` + incomplete tool args
   - Provide specific error message about `max_tokens`
   - Much better UX than generic "invalid JSON"
