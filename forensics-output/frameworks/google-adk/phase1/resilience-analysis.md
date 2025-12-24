# Resilience Analysis: Google ADK

## Summary
- **Key Finding 1**: Minimal custom error hierarchy - relies on Pydantic validation errors
- **Key Finding 2**: Error propagation via LlmResponse error fields (error_code, error_message)
- **Classification**: Fail-fast with structured error responses, no retry logic at framework level

## Detailed Analysis

### Error Handling Architecture

The framework uses a **hybrid error model**:

1. **Pydantic validation errors**: Automatic at data boundaries
2. **Custom domain errors**: Limited (AlreadyExistsError, NotFoundError, InputValidationError)
3. **LLM error responses**: Captured in LlmResponse.error_code/error_message
4. **Framework errors**: Mostly uncaught, propagated to caller

### Custom Error Types

| Error | Location | Usage |
|-------|----------|-------|
| AlreadyExistsError | errors/already_exists_error.py | Resource conflicts |
| NotFoundError | errors/not_found_error.py | Missing resources |
| InputValidationError | errors/input_validation_error.py | User input validation |

**Note**: Only 3 custom error types - framework prefers **letting errors bubble up**

### Error Propagation Pattern

**LLM Errors**:
```python
LlmResponse(
    error_code='UNKNOWN_ERROR',
    error_message='Unknown error.',
    ...
)
```

- Errors from LLM captured in response object (not thrown)
- Allows graceful handling without try/except
- Response always returned, even on error

**Tool Errors**:
- Tool execution errors bubble up to BaseLlmFlow
- No automatic retry for failed tools
- Agent may retry via LLM decision (not framework-enforced)

**Session/Memory Errors**:
- Service errors (DB, network) propagate to caller
- No circuit breaker pattern
- No automatic fallback to in-memory storage

### Resilience Mechanisms

| Mechanism | Implementation | Strength |
|-----------|----------------|----------|
| **Validation** | Pydantic at all boundaries | Strong |
| **Retries** | None (left to LLM) | Weak |
| **Timeouts** | None (except queue timeout) | Weak |
| **Circuit Breaker** | None | None |
| **Fallback** | None | None |
| **Sandboxing** | Yes (code_executors/) | Strong |

### Code Execution Sandboxing

The framework has **strong sandboxing** for code execution:

- `code_executors/agent_engine_sandbox_code_executor.py` - Vertex AI sandbox
- `code_executors/base_code_executor.py` - Execution abstraction
- Code runs in isolated environment

### Connection Handling

**WebSocket Resilience**:
```python
except ConnectionClosed:
    # Handle gracefully
except ConnectionClosedOK:
    # Normal closure
```

- Proper handling of connection lifecycle
- Distinguishes normal vs abnormal closure

### State Consistency

**Session Management**:
- Database transactions for session state
- No distributed locking (race condition risk in multi-instance)
- Session rewind feature for recovery

**Memory Management**:
- Vertex AI Memory Bank for persistence
- No consistency guarantees across agents
- No eventual consistency model

## Implications for New Framework

### Positive Patterns
- **Error in response**: LlmResponse carries errors (no exceptions for LLM failures)
- **Sandboxed execution**: Code execution properly isolated
- **Validation at boundaries**: Pydantic catches malformed data early
- **Session rewind**: Allows recovery from bad state

### Considerations
- **No retry policy**: Tools that fail stay failed (no exponential backoff)
- **No timeout decorator**: Long-running operations can hang
- **No circuit breaker**: Failing external services can cascade
- **Weak error types**: Only 3 custom errors (most errors are generic Python exceptions)

## Code References
- `errors/input_validation_error.py` - Custom validation error
- `errors/already_exists_error.py` - Resource conflict error
- `errors/not_found_error.py` - Missing resource error
- `models/llm_response.py:86` - Error fields in response
- `flows/llm_flows/base_llm_flow.py` - Connection error handling
- `code_executors/agent_engine_sandbox_code_executor.py` - Sandboxing
- `sessions/database_session_service.py` - Session persistence

## Anti-Patterns Observed
- **Silent failures**: LLM errors returned in response (not logged centrally)
- **No structured logging**: Errors logged but not categorized
- **No error budget**: No mechanism to track error rates
- **No degraded mode**: Framework has no fallback when services unavailable
- **Race conditions**: No distributed locking for multi-instance session writes
