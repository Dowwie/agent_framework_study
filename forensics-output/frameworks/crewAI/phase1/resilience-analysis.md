# Resilience Analysis: crewAI

## Summary
- **Error Handling**: Catch-and-reraise with custom error handlers
- **Retry Patterns**: RPM limiting via backoff, no explicit retry on LLM failures
- **Sandboxing**: None observed - tools execute in same process
- **Resource Limits**: Token counting, max iterations, RPM limits, optional max execution time

## Detailed Analysis

### Error Handling Patterns

**Primary Pattern**: **Catch, handle, reraise**

**Executor Error Handling** (crew_agent_executor.py:L191-201):
```python
try:
    formatted_answer = self._invoke_loop()
except AssertionError:
    self._printer.print(content="Agent failed to reach a final answer...", color="red")
    raise  # Propagate after logging
except Exception as e:
    handle_unknown_error(self._printer, e)
    raise  # Always propagate
```

**Loop Error Handling** (crew_agent_executor.py:L279):
```python
except OutputParserError as e:
    formatted_answer = handle_output_parser_exception(
        e=e, printer=self._printer, i18n=self._i18n, messages=self.messages, llm=self.llm, callbacks=self.callbacks
    )
    # Continues loop with formatted error message
```

**Action Types**:
1. **Propagate** - AssertionError, general Exception raised after logging
2. **Convert to AgentAction** - OutputParserError converted to error message fed back to LLM
3. **Self-correction** - LLM receives tool errors and can retry

**Crew-Level Errors** (crew.py:L728-733):
```python
except Exception as e:
    crewai_event_bus.emit(self, CrewKickoffFailedEvent(error=str(e), crew_name=self.name))
    raise  # Emit event, then propagate
```

**Memory Errors** (short_term_memory.py - pattern inferred):
- Events: `MemorySaveFailedEvent`, `MemoryQueryFailedEvent`
- Emit failure events but likely propagate exceptions

### Retry Patterns

**RPM Limiting** (crew_agent_executor.py:L231):
```python
enforce_rpm_limit(self.request_within_rpm_limit)
```
- Blocks execution if requests-per-minute limit exceeded
- Uses `RPMController` shared across agents (crew.py:L99, L446)
- Backoff mechanism implied in utility

**Context Window Handling** (crew_agent_executor.py:L36):
```python
from crewai.utilities.agent_utils import handle_context_length, is_context_length_exceeded
```
- Detects context length exceeded errors
- Likely truncates or summarizes message history

**No Explicit LLM Retry**:
- No `tenacity` or retry decorators observed
- Failures propagate to caller
- Agent loop continues on OutputParserError but not on LLM API errors

**Max Iterations** (crew_agent_executor.py:L220-228):
```python
if has_reached_max_iterations(self.iterations, self.max_iter):
    formatted_answer = handle_max_iterations_exceeded(
        formatted_answer, printer=self._printer, i18n=self._i18n,
        messages=self.messages, llm=self.llm, callbacks=self.callbacks
    )
    break
```
- Terminates gracefully with best-effort answer

### Sandboxing

**Code Execution**: **No sandboxing observed**
- Tools execute in same Python process
- No subprocess isolation or Docker containers
- CodeInterpreterTool mentioned (agent/core.py:L81) but implementation not examined

**Network Access**: **Open**
- No network restrictions visible
- MCP server connections use HTTP/SSE/stdio transports (agent/core.py:L52-60)
- Timeout constants defined (agent/core.py:L90-94):
  - `MCP_CONNECTION_TIMEOUT = 10s`
  - `MCP_TOOL_EXECUTION_TIMEOUT = 30s`

**Filesystem Access**: **Open**
- Task output files written directly (task.py:L76)
- Training data files accessed (agent/core.py:L71)
- No chroot or restricted directory access

**Risk**: High for untrusted tool code or LLM-generated actions

### Resource Limits

**Token Management**:
1. **Token Counting** (agent/core.py:L76):
```python
from crewai.utilities.token_counter_callback import TokenCalcHandler
```
- Tracks tokens via callback handler
- Accumulated in `UsageMetrics` (crew_output.py:L26)

2. **Context Window Respect** (crew_agent_executor.py:L90):
```python
respect_context_window: bool = False
```
- Optional truncation if context exceeds LLM limits

**Iteration Limits** (base_agent.py:L75):
```python
max_iter: int  # Maximum iterations for task execution
```
- Prevents infinite loops
- Default value not specified in excerpts

**Time Limits** (agent/core.py:L131):
```python
max_execution_time: int | None = Field(default=None, description="Maximum execution time for an agent to execute a task")
```
- Optional timeout per agent
- Enforcement not visible in excerpts but utility exists (agent/core.py:L32):
  - `validate_max_execution_time` imported

**RPM Limits** (base_agent.py:L72):
```python
max_rpm: int | None  # Maximum requests per minute
```
- Prevents API rate limit violations
- Enforced via `RPMController` backoff

**Tool Usage Limits** (base_tool.py:L88-95):
```python
max_usage_count: int | None = Field(default=None)
current_usage_count: int = Field(default=0)
```
- Per-tool usage caps
- Incremented on each invocation (not shown but field exists)

### Fault Tolerance

**Event-Driven Observability**:
- All failures emit events before propagating
- Enables external monitoring/alerting
- Example: `CrewKickoffFailedEvent`, `TaskFailedEvent`, `MemorySaveFailedEvent`

**Graceful Degradation**:
- Max iterations → best-effort answer instead of exception
- OutputParserError → LLM self-correction attempt
- Context overflow → truncation (if enabled)

**No Circuit Breakers**:
- Repeated tool failures don't trigger circuit breaker
- No automatic fallback LLMs

**No Checkpointing**:
- Long-running crews can't resume from checkpoint
- Failure requires full re-execution

## Implications for New Framework

**Adopt**:
1. **Event emission on failures** - enables observability and monitoring
2. **RPM limiting with backoff** - prevents API quota exhaustion
3. **Max iterations with graceful termination** - avoids infinite loops
4. **LLM self-correction on parser errors** - tool error feedback loop
5. **Per-tool usage limits** - prevents runaway tool costs
6. **Optional max execution time** - protects against hangs

**Avoid**:
1. **No sandboxing** - major security risk for untrusted code
2. **No retry on LLM failures** - transient network errors cause full failure
3. **No checkpointing** - wastes resources on long-running task failures
4. **No circuit breakers** - repeated failures to same tool continue indefinitely

**Improve**:
1. Add subprocess/Docker sandboxing for tool execution
2. Use `tenacity` for exponential backoff on LLM API calls
3. Implement checkpointing for long-running crews (save after each task)
4. Add circuit breaker pattern for tools (fail fast after N failures)
5. Add fallback LLM support (try GPT-4, fall back to Claude)
6. Restrict filesystem access to designated directories
7. Add resource quotas (CPU, memory, disk)

## Code References

- Executor error handling: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L191-201`
- Parser error recovery: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L279`
- Crew error emission: `lib/crewai/src/crewai/crew.py:L728-733`
- RPM enforcement: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L231`
- Max iterations: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L220`
- Max execution time: `lib/crewai/src/crewai/agent/core.py:L131`
- Tool usage limits: `lib/crewai/src/crewai/tools/base_tool.py:L88-95`
- MCP timeouts: `lib/crewai/src/crewai/agent/core.py:L90-94`
- Token counting: `lib/crewai/src/crewai/agent/core.py:L76`
- Context window handling: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L36`

## Anti-Patterns Observed

1. **No sandboxing**: Tools execute with full process privileges
2. **No LLM retry**: Transient API errors cause immediate failure
3. **Catch-and-reraise without recovery**: Error handling is mostly logging, not recovery
4. **No checkpointing**: Long-running crews must restart from beginning on failure
5. **No circuit breakers**: Failing tools continue to be called
6. **Open filesystem access**: No restrictions on file operations
7. **Synchronous backoff**: RPM limiting blocks entire agent instead of queuing
