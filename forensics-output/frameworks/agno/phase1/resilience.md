# Resilience Analysis: Agno

## Summary
- **Key Finding 1**: Rich exception hierarchy with control-flow exceptions (RetryAgentRun, StopAgentRun)
- **Key Finding 2**: Cancellation system with global registry and checkpoint pattern
- **Key Finding 3**: Silent error handling in tool connection - warns but continues
- **Classification**: Defensive error handling with explicit retry/stop semantics

## Error Propagation Pattern
- **Strategy**: Exception-based with structured exception types
- **Hierarchy**: AgnoError (base) → ModelProviderError, AgentRunException → RetryAgentRun, StopAgentRun
- **Control Flow**: Exceptions used for both errors AND flow control (retry/stop)

## Exception Taxonomy

### Operational Exceptions (recoverable)

| Exception | Purpose | Status Code | Recovery Action |
|-----------|---------|-------------|-----------------|
| RetryAgentRun | Trigger retry of current run | N/A | Retry with modified messages |
| RetryableModelProviderError | Model call failed, can retry | N/A | Retry with guidance message |
| ModelRateLimitError | Rate limit hit | 429 | Backoff (if implemented) |
| RunCancelledException | User cancelled execution | N/A | Clean up and exit |

### Fatal Exceptions (non-recoverable)

| Exception | Purpose | Status Code | Recovery Action |
|-----------|---------|-------------|-----------------|
| StopAgentRun | Stop execution entirely | N/A | Terminate run, return error |
| ModelAuthenticationError | Invalid credentials | 401 | User must fix config |
| ModelProviderError | Model API error | 502 | Surface to user |
| InputCheckError | Guardrail blocked input | N/A | Reject request |
| OutputCheckError | Guardrail blocked output | N/A | Reject response |
| RemoteServerUnavailableError | Server unreachable | 503 | Wait or fallback |

### Internal Exceptions

| Exception | Purpose | Status Code |
|-----------|---------|-------------|
| AgnoError | Generic internal error | 500 |
| EvalError | Evaluation failed | N/A |

## Detailed Analysis

### Control-Flow Exception Pattern

**Evidence** (`exceptions.py:26-56`):
```python
class RetryAgentRun(AgentRunException):
    """Exception raised when a tool call should be retried."""
    def __init__(self, exc, user_message, agent_message, messages):
        super().__init__(
            exc,
            user_message=user_message,
            agent_message=agent_message,
            messages=messages,
            stop_execution=False  # Signal: don't stop
        )

class StopAgentRun(AgentRunException):
    """Exception raised when an agent should stop executing entirely."""
    def __init__(self, exc, user_message, agent_message, messages):
        super().__init__(
            exc,
            user_message=user_message,
            agent_message=agent_message,
            messages=messages,
            stop_execution=True  # Signal: terminate now
        )
```

**Pattern**: Exceptions carry execution directives:
- `stop_execution` flag controls termination
- Can attach messages to inject into conversation
- Tool functions can raise `RetryAgentRun` to trigger model retry with context

This is **Python's exception system used as a state machine**.

### Cancellation System

**Evidence** (`agent/agent.py:1004, 1081, 1087`):
```python
# Register run for cancellation tracking
register_run(run_response.run_id)

# Strategic checkpoint before reasoning
raise_if_cancelled(run_response.run_id)

# Strategic checkpoint before model call
raise_if_cancelled(run_response.run_id)
```

**Pattern**:
1. Register run ID in global registry on start
2. Check cancellation at strategic points
3. Raise `RunCancelledException` if cancelled
4. Cleanup resources in finally block

**Checkpoint Locations**:
- Before reasoning phase (line 1081)
- Before model call (line 1087)

This prevents wasted compute but doesn't provide fine-grained cancellation (e.g., mid-tool-execution).

### Tool Connection Error Handling

**Evidence** (`agent/agent.py:888-892, 896-900`):
```python
try:
    await tool.connect()
    self._mcp_tools_initialized_on_run.append(tool)
except Exception as e:
    log_warning(f"Error connecting tool: {str(e)}")
    # Continues execution - tool won't be available

# Cleanup
for tool in self._mcp_tools_initialized_on_run:
    try:
        await tool.close()
    except Exception as e:
        log_warning(f"Error disconnecting tool: {str(e)}")
        # Continues cleanup - ensures other tools close
```

**Pattern**: **Silent failure with degraded functionality**
- Tool connection failures are logged but don't halt execution
- Agent runs with fewer tools than expected
- Cleanup failures don't prevent other cleanups

**Tradeoff**: Resilient to flaky tools but silently reduces capabilities.

### Guardrail Exception System

**Evidence** (`exceptions.py:122-173`):
```python
class CheckTrigger(Enum):
    OFF_TOPIC = "off_topic"
    INPUT_NOT_ALLOWED = "input_not_allowed"
    OUTPUT_NOT_ALLOWED = "output_not_allowed"
    VALIDATION_FAILED = "validation_failed"
    PROMPT_INJECTION = "prompt_injection"
    PII_DETECTED = "pii_detected"

class InputCheckError(Exception):
    def __init__(self, message: str, check_trigger: CheckTrigger, additional_data):
        self.error_id = check_trigger.value
        self.check_trigger = check_trigger
        self.additional_data = additional_data
```

**Pattern**: Typed error reasons via enum
- Machine-readable error IDs (`prompt_injection`)
- Human-readable messages
- Structured additional data (e.g., detected PII entities)

This enables **programmatic error handling** - clients can switch on `error_id`.

### Structured Error Data

**Evidence** (`exceptions.py:8-24`):
```python
class AgentRunException(Exception):
    def __init__(
        self,
        exc,
        user_message: Optional[Union[str, Message]] = None,
        agent_message: Optional[Union[str, Message]] = None,
        messages: Optional[List[Union[dict, Message]]] = None,
        stop_execution: bool = False,
    ):
        self.user_message = user_message
        self.agent_message = agent_message
        self.messages = messages
        self.stop_execution = stop_execution
        self.type = "agent_run_error"
        self.error_id = "agent_run_error"
```

**Rich Error Context**:
- Original exception preserved
- Messages to inject into conversation
- Execution control flag
- Typed error ID for programmatic handling

This supports **error recovery via conversation** - errors become learning opportunities.

### No Circuit Breaker Pattern

**Observation**: Retry logic in `agent/agent.py:1006-1011` is simple:
```python
num_attempts = self.retries + 1
for attempt in range(num_attempts):
    try:
        # Execute run
```

**Missing**:
- No exponential backoff
- No circuit breaker (prevent cascading failures)
- No jitter
- Immediate retry on failure

For production systems calling rate-limited APIs, this can exacerbate outages.

### Error Recovery Messages

**Pattern** (`exceptions.py:177-180`):
```python
@dataclass
class RetryableModelProviderError(Exception):
    original_error: Optional[str] = None
    retry_guidance_message: Optional[str] = None  # Tell model how to fix it
```

**Smart Pattern**: Errors can include guidance for the model:
- "Rate limit exceeded, please wait 60 seconds"
- "Invalid parameter 'xyz', use format ABC"

This enables **self-correction loops**.

## Implications for New Framework

1. **Control-flow exceptions are powerful** - Using exceptions for retry/stop is elegant but non-idiomatic Python
2. **Cancellation checkpoints are essential** - Strategic `raise_if_cancelled()` calls prevent waste
3. **Silent degradation can be dangerous** - Tool connection failures should at least warn users
4. **Rich exception context is valuable** - Attaching messages, guidance, and error IDs enables recovery
5. **Circuit breakers needed for production** - Simple retry without backoff is insufficient
6. **Typed error reasons** - CheckTrigger enum pattern is excellent for programmatic handling

## Anti-Patterns Observed

1. **Exception-based control flow** - Using exceptions for retry/stop is clever but obscures logic flow
2. **Silent tool failures** - Tools that fail to connect should at minimum warn user prominently
3. **No retry backoff** - Immediate retries can worsen rate limit situations
4. **Broad exception catching** - `except Exception` in tool cleanup (line 899) can hide bugs
5. **No timeout handling** - Cancellation is user-triggered, not timeout-based
6. **Cleanup errors ignored** - Tool disconnect failures logged but don't surface to user

## Code References
- `libs/agno/agno/exceptions.py:8` - AgentRunException base class
- `libs/agno/agno/exceptions.py:26-40` - RetryAgentRun control-flow exception
- `libs/agno/agno/exceptions.py:42-56` - StopAgentRun control-flow exception
- `libs/agno/agno/exceptions.py:58-64` - RunCancelledException
- `libs/agno/agno/exceptions.py:92-104` - ModelProviderError hierarchy
- `libs/agno/agno/exceptions.py:122-129` - CheckTrigger enum for guardrails
- `libs/agno/agno/exceptions.py:134-153` - InputCheckError with structured data
- `libs/agno/agno/exceptions.py:177-180` - RetryableModelProviderError with guidance
- `libs/agno/agno/agent/agent.py:888-900` - Silent tool connection failure pattern
- `libs/agno/agno/agent/agent.py:1004,1081,1087` - Cancellation checkpoint pattern
