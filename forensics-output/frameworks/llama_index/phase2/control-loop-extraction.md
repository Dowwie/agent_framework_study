# Control Loop Extraction: LlamaIndex

## Summary
- **Key Finding 1**: Classic ReAct pattern - Thought → Action → Observation cycle
- **Key Finding 2**: Workflow-based orchestration via external workflows package, not explicit while loop
- **Key Finding 3**: State accumulation via context store with reasoning step history
- **Classification**: ReAct reasoning with event-driven workflow execution

## Detailed Analysis

### Reasoning Pattern

**Classification**: ReAct (Reason + Act)

LlamaIndex implements the classic ReAct pattern from the paper "ReAct: Synergizing Reasoning and Acting in Language Models" (Yao et al., 2023).

**Evidence**:
- ReActAgent class (react_agent.py:L36)
- ReActChatFormatter for prompt formatting (react_agent.py:L43-46)
- ReActOutputParser for parsing LLM output (react_agent.py:L40-42)
- Reasoning step types: ActionReasoningStep, ObservationReasoningStep, ResponseReasoningStep (react/types.py:L22-75)

**Reasoning Cycle**:
```
1. Thought: LLM reasons about what to do
2. Action: LLM decides which tool to call
3. Action Input: LLM provides tool arguments
4. Observation: Tool execution result is shown to LLM
5. Repeat steps 1-4 until LLM provides Answer
6. Answer: LLM's final response
```

### Step Function

**Name**: `take_step`

**Location**: react_agent.py:L116-232

**Signature**:
```python
async def take_step(
    self,
    ctx: Context,  # Workflow context for state storage
    llm_input: List[ChatMessage],  # Current conversation
    tools: Sequence[AsyncBaseTool],  # Available tools
    memory: BaseMemory,  # Conversation memory
) -> AgentOutput
```

**Inputs**:
- `ctx`: Workflow context (stores current_reasoning)
- `llm_input`: Chat history
- `tools`: Tool registry
- `memory`: Not used directly in step (managed externally)

**Outputs**: `AgentOutput` (Pydantic model)
```python
AgentOutput(
    response: ChatMessage,  # LLM's message
    tool_calls: Optional[List[ToolSelection]],  # Tools to execute (if any)
    raw: Any,  # Raw LLM response
    retry_messages: Optional[List[ChatMessage]],  # Error recovery
    current_agent_name: str,  # For multi-agent
)
```

**Pure**: No - has side effects:
- Writes to `ctx.store` (state accumulation)
- Calls LLM (external I/O)
- Emits events via `ctx.write_event_to_stream()`

### Step Function Logic Flow

1. **Retrieve Current Reasoning State** (L135-137):
   ```python
   current_reasoning: list[BaseReasoningStep] = await ctx.store.get(
       self.reasoning_key, default=[]
   )
   ```

2. **Format LLM Input** (L138-142):
   - Combines system prompt, chat history, and current reasoning steps
   - Uses ReActChatFormatter to add ReAct prompt template

3. **Call LLM** (L152-155):
   - Streaming or non-streaming based on config
   - Returns ChatResponse

4. **Parse Output** (L158-163):
   - Extract message content
   - Parse into ReasoningStep using ReActOutputParser

5. **Error Handling** (L164-195):
   - If parse fails, return retry_messages with format instructions
   - LLM will see error and try again

6. **Check Termination** (L207-212):
   - If `reasoning_step.is_done`, return AgentOutput with final response
   - ResponseReasoningStep has `is_done=True`

7. **Prepare Tool Call** (L214-232):
   - Convert ActionReasoningStep to ToolSelection
   - Return AgentOutput with tool_calls

8. **Update State** (L198-199):
   - Append reasoning step to current_reasoning
   - Store updated reasoning in context

### Termination Conditions

| Condition | Type | Location | Token/Value |
|-----------|------|----------|-------------|
| Response step | Semantic | react/types.py:L73-75 | `ResponseReasoningStep.is_done=True` |
| Return direct | Semantic | react/types.py:L53-55 | `ObservationReasoningStep.return_direct=True` |
| Workflow timeout | Resource | base_agent.py:L136 | Configurable (default: None) |
| Parse error | Error | react_agent.py:L164 | ValueError triggers retry |

**No Max Iterations**: Unlike traditional ReAct implementations, LlamaIndex does NOT have an explicit max_steps counter. This is delegated to the workflow timeout.

### Loop Mechanics

**Style**: Event-driven workflow (NOT explicit while loop)

**How It Works**:

The agent does NOT have a traditional `while True:` loop. Instead, the workflow system orchestrates execution:

1. Workflow receives input event
2. Calls `take_step()` once
3. If `tool_calls` in output, workflow executes tools
4. Tool results trigger another call to `take_step()`
5. Repeat until `AgentOutput` has no tool_calls and no retry_messages

**Implicit Loop via Workflow Events**:
```
AgentInput event
    → take_step() returns AgentOutput with tool_calls
    → ToolCall events emitted
    → Tools execute
    → ToolCallResult events emitted
    → handle_tool_call_results() processes results (L234-260)
    → Loop back to take_step()
```

**State Persistence** (L135, L199):
```python
# Read state
current_reasoning = await ctx.store.get(self.reasoning_key, default=[])

# Update state
current_reasoning.append(reasoning_step)
await ctx.store.set(self.reasoning_key, current_reasoning)
```

The `ctx.store` acts as a persistent key-value store that survives across step invocations.

**Continuation Logic**:
- If `tool_calls` is non-empty → continue
- If `retry_messages` is non-empty → continue
- If neither → workflow stops

### Reasoning Step Type Hierarchy

```
BaseReasoningStep (abstract)
    ├── ActionReasoningStep (thought + action + action_input) → is_done=False
    ├── ObservationReasoningStep (observation + return_direct) → is_done=return_direct
    └── ResponseReasoningStep (thought + response) → is_done=True
```

**Design Pattern**: Polymorphism via `is_done` property

Each reasoning step knows whether it represents a terminal state, eliminating the need for external state machines.

### ReAct Prompt Structure

**Formatter** (react_agent.py:L138-142):
```python
input_chat = react_chat_formatter.format(
    tools,  # Available tools
    chat_history=llm_input,  # Conversation
    current_reasoning=current_reasoning,  # Step history
)
```

**Prompt Components**:
1. System header (ReAct instructions)
2. Tool descriptions (generated from ToolMetadata)
3. Chat history
4. Current reasoning steps (Thought/Action/Observation sequence)
5. User query

**Example Formatted Prompt**:
```
You are a helpful AI assistant. Use the following tools:

Tools:
- search(query: str) - Search the web
- calculator(expression: str) - Perform calculation

Previous reasoning:
Thought: I need to find the population of France
Action: search
Action Input: {"query": "population of France 2024"}
Observation: The population of France is approximately 67 million.

Chat history:
User: What's the population of France times 2?

What's your next step?
```

## Code References

- `llama-index-core/llama_index/core/agent/workflow/react_agent.py:116` — take_step function
- `llama-index-core/llama_index/core/agent/react/types.py:9` — BaseReasoningStep
- `llama-index-core/llama_index/core/agent/react/types.py:22` — ActionReasoningStep
- `llama-index-core/llama_index/core/agent/react/types.py:58` — ResponseReasoningStep
- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:68` — BaseWorkflowAgent
- `llama-index-core/llama_index/core/agent/workflow/workflow_events.py` — AgentOutput structure

## Implications for New Framework

1. **ReAct as default**: The ReAct pattern is proven and well-understood. It should be the default reasoning pattern, with other patterns (Plan-and-Solve, Reflection) as alternatives.

2. **Event-driven execution**: Using workflows instead of explicit loops provides better observability, timeout handling, and composability. Consider this architecture.

3. **State accumulation via context store**: Storing reasoning history in a persistent store (rather than passing it as parameters) simplifies function signatures and enables state inspection.

4. **Polymorphic reasoning steps**: Having each step know if it's terminal (`is_done`) is cleaner than external state machines.

5. **Error-as-retry-messages**: Returning retry messages instead of raising exceptions enables LLM self-correction for parse errors.

6. **No max_steps**: Relying on global timeout instead of per-step counters simplifies logic and prevents premature termination.

## Anti-Patterns Observed

1. **No iteration limit**: Without max_steps, an agent could loop indefinitely if the workflow timeout is disabled. Need both timeout AND iteration limit.

2. **State mutation in step function**: `take_step()` has side effects (writes to ctx.store, calls LLM, emits events). A pure function would return new state rather than mutating.

3. **Implicit loop via events**: The workflow-based loop is harder to understand than an explicit `while` loop. Requires understanding the event system.

4. **No progress tracking**: No counter for number of steps taken, making it hard to detect loops or analyze performance.

5. **Reasoning state is append-only**: `current_reasoning.append()` grows unboundedly. No summarization or eviction strategy.

6. **Tool execution outside step function**: Tools are executed externally by the workflow, making it hard to understand the full execution flow from reading `take_step()` alone.

## Recommendations

- Add max_iterations limit in addition to timeout
- Make step function pure - return new state rather than mutating context
- Add step counter to reasoning state
- Implement reasoning step summarization when context grows large
- Consider making the loop explicit (while loop) rather than event-driven for simplicity
- Add progress metrics (steps taken, tools called, tokens used)
