# Resilience Analysis: LlamaIndex

## Summary
- **Key Finding 1**: Error-as-data pattern via `retry_messages` for LLM self-correction
- **Key Finding 2**: ToolOutput with `is_error` flag and exception storage for graceful degradation
- **Key Finding 3**: Minimal retry infrastructure - relies on workflow timeout rather than explicit retry logic
- **Classification**: Propagate-and-recover with LLM-in-the-loop error correction

## Detailed Analysis

### Error Handling

**Primary Pattern**: Error-as-data with retry messages

LlamaIndex's agent framework captures parse errors and converts them into retry messages that guide the LLM to fix its own mistakes.

**Example from ReactAgent** (react_agent.py:L162-195):
```python
try:
    reasoning_step = output_parser.parse(message_content, is_streaming=False)
except ValueError as e:
    error_msg = (
        f"Error while parsing the output: {e!s}\n\n"
        "The output should be in one of the following formats:\n"
        "1. To call a tool:\n```\nThought: <thought>\nAction: <action>\nAction Input: <action_input>\n```\n"
        "2. To answer the question:\n```\nThought: <thought>\nAnswer: <answer>\n```\n"
    )

    # Return with retry messages to let the LLM fix the error
    return AgentOutput(
        response=last_chat_response.message,
        retry_messages=[
            last_chat_response.message,
            ChatMessage(role="user", content=error_msg),
        ],
    )
```

**Recovery Flow**:
1. Parse error occurs (ValueError)
2. Error message includes formatting instructions
3. Return `AgentOutput` with `retry_messages` field
4. Multi-agent workflow checks for `retry_messages` (multi_agent_workflow.py:L241-245)
5. Messages appended to memory for next LLM call
6. LLM attempts correction

**Why This Works**: The LLM can self-correct based on error feedback, reducing the need for hand-coded retry logic.

| Error Type | Location | Action | Recovery |
|------------|----------|--------|----------|
| Parse error | react_agent.py:L164 | Return retry_messages | LLM self-corrects |
| Empty message | react_agent.py:L160 | raise ValueError | Propagates (no recovery) |
| Invalid tool name | (not explicit) | Pass to LLM as tool error | LLM tries different tool |
| Schema validation | tools/types.py:L51, L58, L79 | raise ValueError | Propagates |
| Reserved tool name | base_agent.py:L194-196 | raise ValueError | Fails fast at init |

### Tool Error Handling

**ToolOutput Error Representation** (tools/types.py:L93-153):

```python
class ToolOutput(BaseModel):
    blocks: List[ContentBlock]
    tool_name: str
    raw_input: Dict[str, Any]
    raw_output: Any
    is_error: bool = False  # Error flag

    _exception: Optional[Exception] = PrivateAttr(default=None)  # Exception storage

    @property
    def exception(self) -> Optional[Exception]:
        return self._exception
```

**Error Propagation Strategy**:
- Tools mark output as `is_error=True`
- Exception stored in `_exception` (not serialized)
- Error content added to `blocks` as text
- Agent can observe error via `tool_output.content` and retry

**Example Flow**:
```
Tool execution fails
    → ToolOutput(is_error=True, exception=exc, content=str(exc))
    → ObservationReasoningStep(observation=str(tool_output.content))
    → LLM sees error in observation
    → LLM decides to retry with different input or different tool
```

### Retry Patterns

**No Explicit Retry Infrastructure**

LlamaIndex does NOT use retry decorators (like `tenacity`) in the core framework. Instead:

1. **Workflow Timeout**: Agents have a global timeout (base_agent.py:L51, L136)
   ```python
   WORKFLOW_KWARGS = ("timeout", "verbose", ...)

   Workflow.__init__(self, timeout=timeout, ...)
   ```

2. **LLM-Driven Retry**: The agent loop naturally retries by:
   - Observing tool errors
   - Asking LLM to try again
   - Continuing until max iterations or completion

3. **Parsing Retry**: As shown above, parse errors generate retry_messages

**HTTP Timeouts** (external I/O):
- `requests.get(url, timeout=(60, 60))` (multi_modal_llms/generic_utils.py)
- API utils have configurable timeout (ingestion/api_utils.py:L60)

**No Backoff Strategy**: All retries are immediate (no exponential backoff).

### Sandboxing

**Code Execution**: Not present in core framework

**Network**: Open - tools can make arbitrary HTTP requests

**Filesystem**: Open - no restrictions on file I/O

**Sandboxing is delegated to tool implementations**, not enforced at the framework level.

### Resource Limits

| Resource | Limit | Location | Enforcement |
|----------|-------|----------|-------------|
| Workflow timeout | Configurable (default: None) | base_agent.py:L136 | Workflow executor |
| Embed batch size | Default: 10, max: 2048 | base/embeddings/base.py:L78-82 | Pydantic validator |
| Concurrent runs | Configurable (default: None) | workflow WORKFLOW_KWARGS | Workflow executor |
| HTTP timeout | 60s (hardcoded) | response/notebook_utils.py:L47 | requests library |
| Max iterations | Not at framework level | Agent-specific | User responsibility |

**No Token Limits**: No enforcement of max tokens or context window limits in the core framework.

### Instrumentation for Observability

**Event Dispatching** (instrumentation layer):
- All errors can be observed via `dispatcher.event()`
- QueryStartEvent/QueryEndEvent for query lifecycle
- RetrievalStartEvent/RetrievalEndEvent for retrieval
- EmbeddingStartEvent/EmbeddingEndEvent for embeddings
- AgentInput/AgentOutput for agent lifecycle

**Callback Manager**:
- Tracing via `callback_manager.as_trace("query")`
- Events: CBEventType (defined in callbacks.schema)
- Allows external observability without modifying core logic

## Code References

- `llama-index-core/llama_index/core/agent/workflow/react_agent.py:162` — Parse error to retry_messages
- `llama-index-core/llama_index/core/tools/types.py:93` — ToolOutput with is_error
- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:136` — Workflow timeout
- `llama-index-core/llama_index/core/base/embeddings/base.py:78` — Batch size validation
- `llama-index-core/llama_index/core/agent/workflow/multi_agent_workflow.py:241` — Retry message handling

## Implications for New Framework

1. **Error-as-data pattern**: Rather than using try/catch for every tool error, return error information in the data structure and let the LLM decide how to recover. This is elegant and leverages the LLM's reasoning ability.

2. **Retry messages for self-correction**: The `retry_messages` pattern is brilliant for parse errors - the LLM can see what went wrong and fix its output format without hand-coded logic.

3. **is_error flag over exceptions**: Using a boolean flag (`is_error`) for error state is simpler than exception handling and works well with serialization.

4. **Workflow timeout as circuit breaker**: Global timeout prevents infinite loops without needing per-step retry limits.

5. **Instrumentation separation**: Using dispatcher events rather than logging in business logic enables clean observability.

6. **Fail-fast validation**: Validating constraints at initialization (reserved tool names) prevents runtime errors.

## Anti-Patterns Observed

1. **No structured error taxonomy**: ValueError is used for all errors (parsing, validation, missing fields). A structured error hierarchy would enable better error handling.

2. **Silent PrivateAttr for exceptions**: Storing exceptions in `_exception` means they're lost during serialization. Either make errors first-class or don't store exceptions.

3. **No retry limits**: LLM-driven retry can loop indefinitely if the LLM keeps making the same mistake. Need a retry counter.

4. **Hardcoded HTTP timeouts**: `timeout=(60, 60)` is hardcoded rather than configurable, making it difficult to adjust for slow networks.

5. **No resource exhaustion protection**: No limits on memory usage, token counts, or tool execution time at the framework level.

6. **Mixed error handling strategies**: Some errors propagate (raise), some convert to data (retry_messages), some are silent (unpickleable attrs). Inconsistent.

7. **No sandboxing**: Tools run in the same process as the agent with full privileges - a malicious tool could read secrets or make arbitrary network calls.

## Recommendations

1. Create structured error hierarchy: `ParseError`, `ToolExecutionError`, `ValidationError`, etc.
2. Add retry counter to prevent infinite LLM retry loops
3. Make all errors serializable (no PrivateAttr for exceptions)
4. Add configurable resource limits: max tokens, max tool execution time, memory limits
5. Implement tool sandboxing via subprocess isolation or containers
6. Add exponential backoff for external I/O retries
7. Centralize error handling strategy - pick error-as-data OR exceptions, not both
8. Add circuit breaker pattern for flaky external services
