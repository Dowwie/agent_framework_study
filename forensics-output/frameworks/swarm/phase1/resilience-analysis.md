# Resilience Analysis: Swarm

## Summary
- **Error Handling**: Minimal - single try/catch in schema generation, propagates elsewhere
- **Retry Logic**: None
- **Sandboxing**: None - tools run in main process
- **Resource Limits**: `max_turns` only, no timeout or token limits
- **Failure Modes**: Fail-fast with unhandled exceptions

## Error Handling Patterns

### Schema Generation (Only Try/Catch Block)

```python
# util.py:L53-58
try:
    signature = inspect.signature(func)
except ValueError as e:
    raise ValueError(
        f"Failed to get signature for function {func.__name__}: {str(e)}"
    )
```

**Pattern**: Catch-and-re-raise with context
- **Purpose**: Add function name to error message
- **Action**: Propagate (re-raise)
- **Effect**: Better debugging, but still crashes

### Type Conversion Error Handling

```python
# util.py:L62-67
try:
    param_type = type_map.get(param.annotation, "string")
except KeyError as e:
    raise KeyError(
        f"Unknown type annotation {param.annotation} for parameter {param.name}: {str(e)}"
    )
```

**Issue**: `dict.get()` with default never raises `KeyError`, so this catch block is **dead code**.

### Result Type Coercion

```python
# core.py:L82-87
case _:  # Default case for unknown types
    try:
        return Result(value=str(result))
    except Exception as e:
        error_message = f"Failed to cast response to string: {result}. ..."
        debug_print(debug, error_message)
        raise TypeError(error_message)
```

**Pattern**: Last-resort string conversion
- **Fallback**: Attempt `str()` conversion
- **Failure**: Raise `TypeError` with debug context
- **Implication**: Any tool return value that can't stringify crashes the agent

## Missing Tool Handling

```python
# core.py:L103-113
if name not in function_map:
    debug_print(debug, f"Tool {name} not found in function map.")
    partial_response.messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "tool_name": name,
            "content": f"Error: Tool {name} not found.",
        }
    )
    continue  # Skip to next tool, don't crash
```

**Pattern**: Graceful degradation
- **Detection**: Check function name in map before calling
- **Action**: Send error message to LLM, continue with other tools
- **Strength**: Allows agent to self-correct or ask user

**This is the ONLY graceful error handling in the framework.**

## Retry Patterns

**None**: No retry logic anywhere

### LLM API Failures
```python
# core.py:L69
return self.client.chat.completions.create(**create_params)
```

**No retry**: If OpenAI API throws exception (rate limit, network error, timeout), entire `run()` fails immediately.

### Tool Execution Failures
```python
# core.py:L122
raw_result = function_map[name](**args)
```

**No try/catch**: If tool raises exception, it propagates up and crashes the agent run.

**Implication**: A single failing tool (network error, file not found, etc.) kills the entire conversation.

## Sandboxing

**None**: All code runs in main process

### Code Execution Sandbox
- **Mechanism**: None
- **Risk**: Tools have full Python interpreter access
- **Example**: If a tool executes `os.system()`, it runs unrestricted

### Network Access
- **Restrictions**: None
- **Tools can**: Make arbitrary HTTP requests, open sockets

### Filesystem Access
- **Restrictions**: None
- **Tools can**: Read/write any file the process has permissions for

### Resource Consumption
```python
# core.py:L146, L239
max_turns: int = float("inf")
```

**Default**: Infinite turns
- **Risk**: Runaway loop if agent never terminates naturally
- **Mitigation**: User must set `max_turns` manually

**No protection against**:
- Infinite loops in tools
- Memory exhaustion
- CPU exhaustion
- Disk space exhaustion

## Resource Limits

| Resource | Limit | Configuration |
|----------|-------|---------------|
| **Turns** | Configurable | `max_turns` parameter (default: infinity) |
| **Timeout** | None | Not implemented |
| **Tokens** | None | No budget tracking |
| **Tool execution time** | None | Tool can run forever |
| **Memory** | None | Unbounded history growth |

### Turn Limit Implementation
```python
# core.py:L154, L257
while len(history) - init_len < max_turns and active_agent:
```

**Only safeguard**: Prevents infinite message loops, but not infinite time.

### Missing Limits

**No timeout**:
```python
# If LLM API hangs, process hangs forever
completion = self.get_chat_completion(...)  # Blocks indefinitely
```

**No token budget**:
```python
# History grows unbounded
history.append(message)  # No eviction, no summarization
```

**Impact**: Long conversations can hit context limits with cryptic OpenAI API errors.

## Failure Modes

### 1. LLM API Failure
**Trigger**: OpenAI API error (rate limit, network, authentication)
**Behavior**: Exception propagates, entire `run()` fails
**Recovery**: None - caller must handle

### 2. Tool Execution Exception
**Trigger**: Tool raises any exception
**Behavior**: Exception propagates, entire `run()` fails
**Recovery**: None

### 3. Tool Not Found
**Trigger**: LLM calls non-existent tool
**Behavior**: Error message sent to LLM, execution continues
**Recovery**: ✅ Graceful - LLM can retry or ask for help

### 4. Invalid Tool Arguments
**Trigger**: LLM provides wrong argument types
**Behavior**: Depends on tool implementation
**Recovery**: None at framework level

### 5. Context Overflow
**Trigger**: History exceeds model's context window
**Behavior**: OpenAI API returns error
**Recovery**: None - no automatic truncation or summarization

### 6. Infinite Loop
**Trigger**: Agent never returns non-tool response, `max_turns=inf`
**Behavior**: Runs forever (until process killed or API rate limit)
**Recovery**: User must set `max_turns`

## Error Propagation Strategy

**Philosophy**: Fail-fast

```
Exception in tool
    ↓
Propagates through function_map[name](**args)
    ↓
Propagates through handle_tool_calls()
    ↓
Propagates through run()
    ↓
Caller receives exception
```

**No intermediate handling**, **no logging**, **no cleanup**.

## Implications for New Framework

### Adopt
1. **Graceful tool-not-found handling** - Send error to LLM, allow self-correction
2. **max_turns limit** - Prevent runaway loops

### Critical Additions Needed
1. **Retry logic with exponential backoff** - Handle transient API failures
2. **Tool execution timeout** - Prevent hung tools from blocking agent
3. **Tool execution sandboxing** - Subprocess or container isolation
4. **Token budget tracking** - Prevent context overflow
5. **Comprehensive error handling** - Try/catch around tool execution
6. **Circuit breaker** - Stop calling repeatedly failing tools
7. **Timeout for entire run** - User-configurable wall-clock limit

### Anti-Patterns Observed
1. **No retry on transient errors** - Production agents need resilience
2. **Uncaught tool exceptions crash agent** - Should be caught and reported to LLM
3. **Unbounded resource consumption** - No timeout, no memory limit, no token budget
4. **Silent failure modes** - No logging, only debug prints
5. **No health checks** - Can't detect degraded state (e.g., slow API)

## Resilience Score

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| **API failure handling** | 1/10 | No retry, no fallback |
| **Tool error handling** | 2/10 | Only missing tool handled gracefully |
| **Resource limits** | 2/10 | Only turn count, no timeout/budget |
| **Sandboxing** | 0/10 | No isolation, full process access |
| **Observability** | 1/10 | Only debug prints, no structured logging |

**Overall**: 1.2/10 - **Not production-ready**

## Production Readiness Assessment

**Blocking issues for production**:
- ❌ No retry logic (API rate limits will crash agent)
- ❌ No tool sandboxing (security risk)
- ❌ No timeout (hung tools hang entire process)
- ❌ No token budget (context overflow is silent until API error)
- ❌ No structured logging (debugging production issues is impossible)
- ❌ No circuit breaker (repeated failures waste API quota)

**Verdict**: Educational/prototype framework only. Requires significant hardening for production.

## Code References

- `swarm/util.py:53-58` - Only try/catch (schema generation)
- `swarm/util.py:62-67` - Dead code (unreachable KeyError)
- `swarm/core.py:82-87` - Result type coercion error
- `swarm/core.py:103-113` - Graceful missing tool handling
- `swarm/core.py:122` - Unguarded tool execution
- `swarm/core.py:146` - max_turns (only resource limit)
- `swarm/core.py:69` - Unguarded API call
