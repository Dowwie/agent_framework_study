# Control Loop Extraction: pydantic-ai

## Summary

- **Pattern Classification**: Custom Graph-Based Loop (Not ReAct, not Plan-and-Solve)
- **Step Function**: Three-node state machine with branching
- **Termination**: End node or early exit on valid output
- **Loop Structure**: Iterative with automatic tool execution

## Detailed Analysis

### Control Loop Pattern

**Graph-based state machine** (not traditional ReAct):

```
UserPromptNode → ModelRequestNode → CallToolsNode
       ↑                                  |
       |                                  ↓
       +------- (tool calls) ←--------+ End (output validated)
                                       |
                                       ↓
                              (retry on validation error)
```

**Not ReAct because**:
- No explicit Thought/Action/Observation structure
- Tools execute automatically without separate reasoning step
- No forced "think then act" pattern

**Not Plan-and-Solve because**:
- No upfront planning phase
- No explicit plan storage or tracking
- Reactive rather than proactive

**Best described as**: **Iterative tool-augmented completion loop**

### Node Flow Details

#### 1. UserPromptNode

**Responsibilities**:
- Assemble user prompt, instructions, system prompts
- Handle deferred tool results (resume from pause)
- Re-evaluate dynamic prompts
- Decide next transition

**Transition logic**:
```python
async def run(self, ctx) -> ModelRequestNode | CallToolsNode:
    # Handle deferred tool results - skip model, go straight to execution
    if self.deferred_tool_results is not None:
        return await self._handle_deferred_tool_results(...)

    # If last message was model response with no new prompt:
    if isinstance(last_message, ModelResponse) and self.user_prompt is None:
        instructions = await ctx.deps.get_instructions(run_context)
        if not instructions:
            # No new input - go straight to CallToolsNode
            return CallToolsNode[DepsT, NodeRunEndT](last_message)
        # Has instructions - continue to model
        return ModelRequestNode(...)

    # Default: prepare request and go to model
    return ModelRequestNode(...)
```

**Key insight**: Can bypass model request if resuming or no new instructions.

#### 2. ModelRequestNode

**Responsibilities**:
- Make LLM request (streaming or non-streaming)
- Track usage
- Support both run() and stream() modes
- Prepare message history

**Execution**:
```python
async def run(self, ctx) -> CallToolsNode:
    if self._result is not None:
        return self._result  # Cached - prevent duplicate requests

    if self._did_stream:
        raise AgentRunError('You must finish streaming before calling run()')

    return await self._make_request(ctx)

async def _make_request(self, ctx) -> CallToolsNode:
    # Apply history processors
    message_history = await _process_message_history(...)

    # Check usage limits BEFORE request (optional)
    if ctx.deps.usage_limits.count_tokens_before_request:
        usage = await ctx.deps.model.count_tokens(...)
        ctx.deps.usage_limits.check_before_request(usage)

    # Make request
    model_response = await ctx.deps.model.request(message_history, ...)

    # Update usage and limits
    ctx.state.usage.incr(response.usage)
    ctx.deps.usage_limits.check_tokens(ctx.state.usage)

    # Always transition to CallToolsNode
    return CallToolsNode(model_response)
```

**Always transitions to CallToolsNode** - no branching here.

#### 3. CallToolsNode

**Responsibilities**:
- Process model response
- Execute tool calls (or validate output)
- Decide whether to loop or end

**Decision tree**:
```python
async def _run_stream(self, ctx) -> AsyncIterator[HandleResponseEvent]:
    if not self.model_response.parts:
        # Empty response - retry or error
        if self.model_response.finish_reason == 'length':
            raise UnexpectedModelBehavior(...)  # Token limit
        # Try previous text response or retry with empty request
        ctx.state.increment_retries(...)
        self._next_node = ModelRequestNode(ModelRequest(parts=[]))
        return

    # Extract text, tool calls, files from response parts
    text = ''
    tool_calls = []
    files = []
    for part in self.model_response.parts:
        if isinstance(part, TextPart): text += part.content
        elif isinstance(part, ToolCallPart): tool_calls.append(part)
        elif isinstance(part, FilePart): files.append(part.content)
        # ... handle builtin tools, thinking parts

    # Priority 1: Tool calls
    if tool_calls:
        async for event in self._handle_tool_calls(ctx, tool_calls):
            yield event
        # _handle_tool_calls sets self._next_node
        return

    # Priority 2: Image output (if allowed)
    if output_schema.allows_image:
        if image := next((file for file in files if isinstance(file, BinaryImage)), None):
            self._next_node = await self._handle_image_response(ctx, image)
            return

    # Priority 3: Text output (if allowed)
    if text_processor := output_schema.text_processor:
        if text:
            self._next_node = await self._handle_text_response(ctx, text, text_processor)
            return

    # No valid output - ask model to try again
    self._next_node = ModelRequestNode(...)
```

**Tool call handling**:
```python
async def _handle_tool_calls(self, ctx, tool_calls) -> AsyncIterator[HandleResponseEvent]:
    # Execute all tool calls
    tool_results = []
    for tool_call in tool_calls:
        try:
            result = await ctx.deps.tool_manager.call_tool(tool_call.name, tool_call.args_as_dict())
            tool_results.append(ToolReturnPart(tool_call_id=tool_call.id, content=result))
        except ModelRetry as e:
            tool_results.append(RetryPromptPart(tool_call_id=tool_call.id, content=str(e)))
        except Exception as e:
            # Handle errors...

    # Build next request with tool results
    parts = [*tool_results]
    if self.user_prompt:  # Optional user prompt alongside tool results
        parts.append(UserPromptPart(self.user_prompt))

    self._next_node = UserPromptNode(..., request=ModelRequest(parts=parts))
```

**Text output handling**:
```python
async def _handle_text_response(self, ctx, text, text_processor) -> End | ModelRequestNode:
    try:
        output = await text_processor.process(text, ctx)
        await self._validate_output(ctx, output)

        # Success - end the loop
        return End(data=FinalResult(output=output, ...))
    except (ValidationError, ToolRetryError) as e:
        # Validation failed - retry with error feedback
        ctx.state.increment_retries(ctx.deps.max_result_retries, error=e)
        self._next_node = ModelRequestNode(...)
```

### Loop Termination Conditions

**Success termination** (End node):
1. **Valid text output**: Output validated successfully
2. **Valid image output**: Image validated
3. **Early exit** (if `end_strategy == 'early'`):
   - Partial output validation passed
   - Terminate before all tool calls executed

**Loop continuation** (back to UserPromptNode or ModelRequestNode):
1. **Tool calls**: Execute tools, add results, go to UserPromptNode
2. **Validation error**: Increment retries, add error feedback, go to ModelRequestNode
3. **Empty response**: Retry with previous text or empty request
4. **No valid output**: Ask model to try again

**Failure termination** (raise exception):
1. **Max retries exceeded**: `UnexpectedModelBehavior`
2. **Usage limits exceeded**: `UsageLimitExceeded`
3. **Token limit hit**: `IncompleteToolCall` or `UnexpectedModelBehavior`

### End Strategy

**Two strategies**:
```python
EndStrategy = Literal['early', 'exhaustive']
```

1. **'exhaustive'** (default): Wait for all tools to complete, then validate
2. **'early'**: Terminate as soon as partial validation passes

**Implementation**:
```python
if ctx.deps.end_strategy == 'early':
    try:
        output = await self.validate_response_output(response, allow_partial=True)
        return End(data=FinalResult(output=output))
    except ValidationError:
        pass  # Continue loop
```

### Step Function Characteristics

**Input to step**:
- `GraphAgentState`: message_history, usage, retries, run_step, run_id
- `GraphAgentDeps`: user_deps, model, tool_manager, output_schema, etc.
- `Prompt`: User prompt (optional on subsequent steps)

**Output from step**:
- Next node: `UserPromptNode | ModelRequestNode | CallToolsNode | End`
- Updated state: message_history appended, usage incremented
- Events: Tool call start/end, partial outputs (if streaming)

**Side effects per step**:
- API call to LLM
- Tool executions
- Usage tracking
- Message history append
- Retry counter increment

### Dynamic Prompt Re-evaluation

**Feature**: System prompts can be dynamic
```python
async def _reevaluate_dynamic_prompts(self, messages, run_context):
    if self.system_prompt_dynamic_functions:
        for msg in messages:
            for part in msg.parts:
                if isinstance(part, SystemPromptPart) and part.dynamic_ref:
                    runner = self.system_prompt_dynamic_functions[part.dynamic_ref]
                    new_content = await runner.run(run_context)
                    part.content = new_content
```

**Enables**: Context-aware system prompts that change per step.

## Code References

- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:179` - UserPromptNode.run()
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:422` - ModelRequestNode.run()
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:554` - CallToolsNode.run()
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:592` - CallToolsNode._run_stream()
- `pydantic_ai_slim/pydantic_ai/_agent_graph.py:86` - GraphAgentState definition

## Implications for New Framework

1. **Adopt**: Graph-based state machine over implicit loops
   - Explicit state transitions
   - Easier to debug and extend
   - Supports pause/resume naturally

2. **Adopt**: Priority-based output handling
   - Tool calls > Image > Text
   - Clear, predictable behavior
   - Prevents ambiguity in mixed responses

3. **Consider**: Early vs. exhaustive termination strategies
   - Trade-off: Speed vs. completeness
   - 'early' risks incomplete tool execution
   - 'exhaustive' ensures all tools run
   - Let users choose based on use case

4. **Adopt**: Caching in nodes to prevent duplicate requests
   - `_result` field prevents re-execution
   - Important for streaming workflows
   - Reduces token waste

5. **Adopt**: Bypass optimization (UserPromptNode → CallToolsNode)
   - Skip model request if resuming from pause
   - Saves tokens and latency
   - Enables human-in-the-loop workflows

6. **Consider**: Dynamic prompt re-evaluation
   - Powerful for context-dependent system prompts
   - Adds complexity
   - May not be needed for most use cases

## Anti-Patterns Observed

1. **Good pattern**: No anti-patterns in core loop structure
   - Clean state machine
   - Well-defined transitions
   - Proper separation of concerns

2. **Minor complexity**: CallToolsNode._run_stream is very long (200+ lines)
   - Hard to follow all branches
   - **Recommendation**: Extract sub-methods for each output type

## Notable Patterns Worth Adopting

1. **Streaming-compatible control flow**:
   - Nodes support both `run()` and `stream()` modes
   - Same logic, different execution style
   - Enables progressive UI updates

2. **Tool retry with feedback loop**:
   - Don't just retry blindly
   - Add error message to next request
   - Model can self-correct

3. **Usage tracking integrated into loop**:
   - Every node updates usage
   - Limits checked at multiple points
   - Prevents runaway token usage

4. **Message history as mutable shared state**:
   - All nodes append to same list
   - Enables easy access to full context
   - Simplifies history processing
