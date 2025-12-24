# Control Loop Extraction: Google ADK

## Summary
- **Key Finding 1**: Function calling loop pattern (not ReAct text-based)
- **Key Finding 2**: Event-driven architecture with processor pipeline
- **Classification**: Gemini-style function calling with automatic execution (not ReAct)

## Detailed Analysis

### Reasoning Pattern Classification

**Pattern**: **Automatic Function Calling** (Gemini Native)

NOT ReAct - the framework uses native function calling:
- LLM receives function declarations in tool format
- LLM returns structured function_call objects
- Framework automatically executes and returns function_response
- No text-based "Thought, Action, Observation" pattern

### Control Loop Structure

```
Loop: Until no more function calls or agent transfer
  ├─ 1. Preprocessing
  │    ├─ Add instructions (system prompt)
  │    ├─ Add tools (function declarations)
  │    ├─ Add conversation history (contents)
  │    └─ Apply caching strategy
  │
  ├─ 2. Call LLM
  │    └─ Await LlmResponse
  │
  ├─ 3. Check Response Type
  │    ├─ Text response → Return to user
  │    ├─ Function calls → Execute tools (Step 4)
  │    ├─ Agent transfer → Delegate to sub-agent
  │    └─ Error → Return error response
  │
  ├─ 4. Execute Function Calls (if present)
  │    ├─ Parallel or sequential (based on function_call.id)
  │    ├─ Populate ToolContext (session, artifact, auth)
  │    ├─ Call BaseTool.run_async()
  │    ├─ Handle auth requests (EUC flow)
  │    ├─ Handle confirmations (HITL flow)
  │    └─ Generate function_response event
  │
  ├─ 5. Append to History
  │    ├─ Add function_call event
  │    └─ Add function_response event
  │
  └─ 6. Loop back to Step 2
```

### Step Function Signature

```python
async def run_async(
    self,
    invocation_context: InvocationContext,
) -> AsyncGenerator[Event, None]:
    """
    Main loop in BaseLlmFlow
    """
    while True:
        # Preprocessing
        llm_request = self._preprocess(...)

        # Call LLM
        llm_response = await llm.generate_content(llm_request)

        # Yield model response event
        yield model_response_event

        # Check if function calls present
        if model_response_event.get_function_calls():
            # Execute tools
            function_response_event = await handle_function_calls()
            yield function_response_event

            # Continue loop
            continue

        # No function calls - check for agent transfer
        if agent_transfer_detected:
            # Delegate to sub-agent
            async for event in sub_agent.run_async(...):
                yield event
            continue

        # Final response - exit loop
        break
```

### Termination Conditions

| Condition | Action |
|-----------|--------|
| **Text-only response** | Exit loop, return to user |
| **Agent transfer** | Delegate to sub-agent, continue in parent context |
| **Error** | Exit loop, return error |
| **Max iterations** | None (infinite loop possible) |
| **Timeout** | None at framework level |
| **Exit tool** | Special tool signals loop exit |

### Tool Execution Model

**Sequential by default**:
```python
async def handle_function_calls_async(
    invocation_context: InvocationContext,
    function_call_event: Event,
    tools_dict: dict[str, BaseTool],
) -> Event:
    for function_call in function_calls:
        # Execute one at a time
        result = await tool.run_async(args=..., tool_context=...)
```

**No built-in parallelism** for multiple function calls in single response

### Special Flows

**1. Human-in-the-Loop (HITL)**:
- Tool can request confirmation via `ToolConfirmation`
- Framework generates `adk_request_confirmation` function call
- LLM receives confirmation response
- Original tool execution resumes

**2. Authentication Flow (EUC)**:
- Tool can request credentials via `requested_auth_configs`
- Framework generates `adk_request_credential` function call
- User provides auth
- Original tool execution retries with credentials

**3. Long-Running Tools**:
- Tools marked `is_long_running=True`
- Return resource ID immediately
- Actual completion handled separately

### Event Stream

The loop yields **Event** objects:

| Event Type | Author | Content |
|------------|--------|---------|
| model_response | agent_name | LLM text or function calls |
| function_response | "adk" | Tool execution results |
| agent_state | agent_name | State updates |
| transfer_to_agent | source_agent | Delegation event |

### Memory Integration

**Conversation History**:
- Managed by `ContentsProcessor`
- All events appended to `llm_request.contents`
- Full history sent on each LLM call (no summarization)

**Context Caching**:
- `ContextCacheProcessor` optimizes repeated content
- Gemini context caching for static instructions/tools

## Implications for New Framework

### Positive Patterns
- **Event-driven**: Clean separation of concerns via Event objects
- **Processor pipeline**: Extensible preprocessing (instructions, tools, caching)
- **Streaming-first**: AsyncGenerator allows real-time updates
- **HITL built-in**: Tool confirmation is first-class feature

### Considerations
- **No max iterations**: Loop can run indefinitely (no safety limit)
- **No parallel tools**: Sequential execution is slow for independent tools
- **Full history**: No conversation summarization (token explosion for long chats)
- **No reflection**: Agent cannot review its own outputs before returning

## Code References
- `flows/llm_flows/base_llm_flow.py:87` - Main run_live() loop
- `flows/llm_flows/base_llm_flow.py:675` - handle_function_calls postprocessing
- `flows/llm_flows/functions.py:56` - Function call ID generation
- `flows/llm_flows/functions.py:108` - Auth event generation (EUC flow)
- `flows/llm_flows/functions.py:143` - Confirmation event generation (HITL)
- `flows/llm_flows/contents.py` - ContentsProcessor for history management
- `events/event.py` - Event structure

## Anti-Patterns Observed
- **Infinite loop risk**: No max_iterations parameter (agent can loop forever)
- **No token budget**: No mechanism to stop when context limit approaches
- **Sequential tools**: Cannot parallelize independent tool calls (performance)
- **No plan-then-execute**: Framework is purely reactive (no explicit planning phase)
