# Control Loop Extraction: Swarm

## Summary
- **Reasoning Pattern**: Native OpenAI function calling (not ReAct)
- **Pattern Classification**: Tool-use loop (LLM-native)
- **Termination**: Natural completion (no tool calls) or max_turns
- **Step Function**: Inlined in main loop, not extracted

## Reasoning Pattern Classification

**Type**: LLM-Native Function Calling (OpenAI-specific)

**Not ReAct**: No explicit Thought/Action/Observation formatting
- No prompt engineering for reasoning traces
- No parsing of action/observation from LLM output
- Relies on OpenAI's native function calling API

**Pattern**:
```
1. LLM generates response (may include tool calls)
2. Framework executes called tools
3. Framework sends tool results back to LLM
4. LLM generates next response
5. Repeat until LLM returns non-tool response
```

### Evidence
```python
# core.py:L50 - Tools defined in API schema
tools = [function_to_json(f) for f in agent.functions]

# core.py:L58-64 - OpenAI function calling parameters
create_params = {
    "model": model_override or agent.model,
    "messages": messages,
    "tools": tools or None,
    "tool_choice": agent.tool_choice,
    "stream": stream,
}
```

**Key distinction**: Framework doesn't teach the LLM *how* to reason (ReAct), it uses the model's built-in tool use capability.

## Loop Structure

### Main Loop (Non-Streaming)

```python
# core.py:L257-286 (simplified)
while len(history) - init_len < max_turns and active_agent:
    # 1. Get completion from LLM
    completion = self.get_chat_completion(
        agent=active_agent,
        history=history,
        context_variables=context_variables,
        ...
    )
    message = completion.choices[0].message

    # 2. Append to history
    history.append(json.loads(message.model_dump_json()))

    # 3. Check termination
    if not message.tool_calls or not execute_tools:
        break

    # 4. Execute tools
    partial_response = self.handle_tool_calls(
        message.tool_calls,
        active_agent.functions,
        context_variables,
        debug
    )

    # 5. Update state
    history.extend(partial_response.messages)
    context_variables.update(partial_response.context_variables)
    if partial_response.agent:
        active_agent = partial_response.agent
```

**Loop Mechanics**:
- **Style**: `while` with compound condition
- **Location**: core.py:L257-286
- **Continuation Logic**:
  - Turn count under `max_turns`
  - `active_agent` is not None
  - LLM requested tool calls
  - `execute_tools` flag is True

## Step Function Analysis

**No extracted step function** - Logic is inlined in loop body

**Pseudo-step function**:
```python
def _step(agent, history, context_variables) -> (message, tool_results, new_agent):
    # 1. Get completion
    completion = get_chat_completion(agent, history, context_variables)

    # 2. Parse message
    message = completion.choices[0].message

    # 3. If no tool calls, return (terminal state)
    if not message.tool_calls:
        return message, None, agent

    # 4. Execute tools
    tool_results = handle_tool_calls(message.tool_calls, agent.functions, context_variables)

    # 5. Check for agent handoff
    new_agent = tool_results.agent or agent

    return message, tool_results, new_agent
```

**Step Inputs**:
- `agent` - Current active agent
- `history` - Full message history
- `context_variables` - Mutable dict of session state

**Step Outputs**:
- Updated `history` (mutated in place)
- Updated `context_variables` (mutated in place)
- Potentially new `active_agent`

**Pure**: No - mutates history and context_variables

## Termination Conditions

### 1. Natural Completion
```python
# core.py:L275-277
if not message.tool_calls or not execute_tools:
    debug_print(debug, "Ending turn.")
    break
```

**Trigger**: LLM returns response without tool calls
**Interpretation**: Agent has completed task or needs user input

### 2. Max Turns Limit
```python
# core.py:L257
while len(history) - init_len < max_turns and active_agent:
```

**Trigger**: Turn count reaches `max_turns`
**Default**: `float("inf")` (unlimited)
**Purpose**: Prevent infinite loops

### 3. Execute Tools Disabled
```python
# core.py:L240
execute_tools: bool = True
```

**Trigger**: User sets `execute_tools=False`
**Effect**: Agent makes one completion, returns (no tool execution)
**Use case**: Getting agent's response without side effects

### 4. Active Agent Becomes None
```python
# core.py:L257
while ... and active_agent:
```

**Trigger**: `active_agent` is None (edge case)
**Likelihood**: Low - framework doesn't set agent to None
**Weakness**: Not explicitly documented or tested

## Termination Tokens

**None**: No special "FINISH" or "FINAL_ANSWER" tokens

Termination is implicit:
- LLM stops calling tools → done
- No prompt engineering for explicit termination signals

## State Transitions

### Agent State Machine
```
Initial State: active_agent = provided agent
    ↓
LLM Turn: Generate response
    ↓
Decision Point: Tool calls present?
    ├─ No → Terminal State (return)
    └─ Yes → Execute Tools
             ↓
        Tool Result: Agent handoff?
             ├─ No → Continue with same agent
             └─ Yes → Transition: active_agent = new_agent
                      ↓
                  Loop back to LLM Turn
```

### Agent Handoff Mechanism
```python
# core.py:L134-135
if result.agent:
    partial_response.agent = result.agent

# core.py:L285-286
if partial_response.agent:
    active_agent = partial_response.agent
```

**Trigger**: Tool returns `Result(agent=new_agent)`
**Effect**: Next turn uses new agent's instructions and functions
**Persistence**: Handoff lasts until another tool returns different agent

### History State
```
Empty → User Message → LLM Response → [Tool Calls] → Tool Results → LLM Response → ...
```

Each turn adds:
1. LLM assistant message (with optional tool_calls)
2. Tool result messages (one per tool called)

## Context Variables Flow

```python
# core.py:L150 - Isolated at start
context_variables = copy.deepcopy(context_variables)

# core.py:L133 - Updated from tool results
partial_response.context_variables.update(result.context_variables)

# core.py:L219, L284 - Merged back into main context
context_variables.update(partial_response.context_variables)
```

**Scope**: Per-run (isolated by deep copy)
**Mutation**: Tools can update via `Result(context_variables={...})`
**Access**: Injected into tools that have `context_variables` parameter

## Instructions Handling

```python
# core.py:L42-46
instructions = (
    agent.instructions(context_variables)
    if callable(agent.instructions)
    else agent.instructions
)
messages = [{"role": "system", "content": instructions}] + history
```

**Dynamic instructions**: If `Agent.instructions` is callable, invoked each turn with current context_variables
**Use case**: Instructions that adapt based on context state
**Example**: "You are {context_variables['user_name']}'s assistant"

## Comparison to Standard Patterns

| Pattern | Swarm | Typical ReAct | Typical Plan-and-Solve |
|---------|-------|---------------|------------------------|
| **Reasoning trace** | Implicit (LLM-internal) | Explicit (Thought:...) | Explicit (Plan:...) |
| **Action format** | Native tool calls | Parsed from text | Structured plan object |
| **Observation** | Tool result | Appended to prompt | State update |
| **Planning** | None | Per-step | Upfront then execute |
| **Replanning** | Implicit (LLM decides) | On error | On plan failure |

**Classification**: LLM-Native Tool Use Loop (closest to OpenAI Assistants API pattern)

## Implications for New Framework

### Adopt
1. **LLM-native function calling** - Cleaner than prompt engineering for tool use
2. **Natural termination** - No magic tokens, LLM decides when done
3. **Dynamic instructions** - Callable instructions allow context-aware prompting
4. **Agent handoff via tool return** - Elegant multi-agent coordination

### Improve
1. **Extract step function** - Make loop body testable and reusable
2. **Add explicit state machine** - Document states and transitions formally
3. **Add planning phase option** - Support upfront planning for complex tasks
4. **Add reflection/self-correction** - No mechanism for agent to review and revise
5. **Add termination condition registry** - Pluggable termination logic beyond turn count

### Anti-Patterns Observed
1. **Inline loop logic** - Hard to test step function in isolation
2. **Implicit termination** - No way to force termination via instruction
3. **No step history** - Can't distinguish between turns (all messages flattened)
4. **No continuation/resume** - Can't pause and resume a run

## Advanced Loop Patterns Missing

**Not supported**:
- Tree-of-thought exploration
- Backtracking on failure
- Parallel hypothesis testing
- Checkpoint/resume
- Sub-agent delegation with aggregation

**Swarm is optimized for**: Linear tool-use conversations with optional agent handoffs

## Code References

- `swarm/core.py:42-46` - Dynamic instruction evaluation
- `swarm/core.py:50` - Tool schema generation
- `swarm/core.py:58-64` - OpenAI function calling setup
- `swarm/core.py:134-135` - Agent handoff detection
- `swarm/core.py:257-286` - Main control loop
- `swarm/core.py:275-277` - Natural termination check
- `swarm/core.py:285-286` - Agent switch
- `swarm/types.py:11` - AgentFunction return types (enable handoff)
