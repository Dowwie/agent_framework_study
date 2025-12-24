# Control Loop Extraction: crewAI

## Summary
- **Reasoning Pattern**: ReAct-style (Thought-Action-Observation)
- **Loop Structure**: While-not-finished with AgentAction/AgentFinish discrimination
- **Termination**: Max iterations OR AgentFinish signal from LLM
- **State Management**: Message accumulation with continuation logic

## Detailed Analysis

### Reasoning Pattern Classification

**Pattern**: **ReAct (Reasoning + Acting)**

**Evidence** (crew_agent_executor.py:L211-277):

```python
def _invoke_loop(self) -> AgentFinish:
    formatted_answer = None
    while not isinstance(formatted_answer, AgentFinish):
        # 1. Get LLM response (Thought + Action)
        answer = get_llm_response(llm=self.llm, messages=self.messages, ...)
        formatted_answer = process_llm_response(answer, self.use_stop_words)

        # 2. Execute action if not finished
        if isinstance(formatted_answer, AgentAction):
            # Execute tool
            result = execute_tool_and_check_finality(...)
            # 3. Append observation to messages
            self._append_message(result.text)
```

**ReAct Components**:
1. **Thought**: LLM generates reasoning and action plan
2. **Action**: Parsed as `AgentAction` with tool name and arguments
3. **Observation**: Tool result appended to message history
4. **Loop**: Continues until `AgentFinish` (final answer)

**Parser** (crew_agent_executor.py:L19):
```python
from crewai.agents.parser import AgentAction, AgentFinish, OutputParserError
```
- Discriminates between intermediate actions and final answers
- On parse error, feedback loop allows LLM self-correction

### Step Function Mechanics

**Step Function**: `CrewAgentExecutor._invoke_loop()`

**Signature** (inferred):
- **Inputs**: `self.messages` (accumulated history), `self.llm`, `self.tools`
- **Outputs**: `AgentFinish` (final answer with output string)

**Pure/Impure**: **Impure**
- Mutates `self.messages` list
- Mutates `self.iterations` counter
- Performs I/O (LLM API calls, tool execution)
- Side effects: event emissions, memory writes

**Step Breakdown**:

1. **Check termination** (crew_agent_executor.py:L220):
```python
if has_reached_max_iterations(self.iterations, self.max_iter):
    formatted_answer = handle_max_iterations_exceeded(...)
    break
```

2. **Enforce rate limits** (crew_agent_executor.py:L231):
```python
enforce_rpm_limit(self.request_within_rpm_limit)
```

3. **Get LLM response** (crew_agent_executor.py:L233):
```python
answer = get_llm_response(llm=self.llm, messages=self.messages, callbacks=self.callbacks, ...)
```

4. **Parse response** (crew_agent_executor.py:L243):
```python
formatted_answer = process_llm_response(answer, self.use_stop_words)
# Returns AgentAction or AgentFinish
```

5. **Execute action** (crew_agent_executor.py:L245+):
```python
if isinstance(formatted_answer, AgentAction):
    result = handle_agent_action_core(formatted_answer, tools_handler, ...)
    self._append_message(result.text)
    self.iterations += 1
```

6. **Handle errors** (crew_agent_executor.py:L279):
```python
except OutputParserError as e:
    formatted_answer = handle_output_parser_exception(...)
    # Continues loop with error feedback
```

### Termination Conditions

**Condition 1: Max Iterations** (crew_agent_executor.py:L220):
- Checked at start of each loop iteration
- Calls `has_reached_max_iterations(self.iterations, self.max_iter)`
- Triggers `handle_max_iterations_exceeded()` which generates best-effort answer

**Condition 2: AgentFinish** (crew_agent_executor.py:L218):
- Loop continues `while not isinstance(formatted_answer, AgentFinish)`
- LLM must emit finish signal (specific format in prompt)
- Extracted by output parser from LLM response

**Condition 3: Exception** (crew_agent_executor.py:L193, L199):
- AssertionError or unhandled Exception breaks loop
- Logged and re-raised to caller

**No Timeout in Loop**:
- Max execution time likely enforced at higher level
- `agent.max_execution_time` field exists but enforcement not in executor loop

### Loop Mechanics

**Style**: **While-predicate loop**

```python
def _invoke_loop(self) -> AgentFinish:
    formatted_answer = None
    while not isinstance(formatted_answer, AgentFinish):
        # Loop body
    return formatted_answer
```

**Continuation Logic**:
- Loop continues as long as `formatted_answer` is not `AgentFinish`
- Initially `None`, becomes `AgentAction` after first LLM call
- Repeatedly `AgentAction` until LLM emits finish signal

**State Evolution**:
```
None → AgentAction (tool call) → AgentAction (tool call) → ... → AgentFinish
         ↓                            ↓
    Observation appended         Observation appended
```

**Message Accumulation** (crew_agent_executor.py:L138):
```python
self.messages: list[LLMMessage] = []
```
- System prompt + user prompt added at start (crew_agent_executor.py:L181-185)
- Tool observations appended after each action (via `_append_message`)
- Grows unbounded unless context window handling truncates

**Iteration Counter** (crew_agent_executor.py:L139):
```python
self.iterations = 0
```
- Incremented after each action execution
- Used for max iteration check

## Prompt Structure

**System Prompt**: `prompt.get("system")` (crew_agent_executor.py:L175)
- Agent role, goal, backstory
- Tool descriptions
- Output format instructions

**User Prompt**: `prompt.get("user")` or `prompt.get("prompt")` (crew_agent_executor.py:L178, L184)
- Task description
- Expected output
- Context from previous tasks

**Formatted via** (crew_agent_executor.py:L34):
```python
format_message_for_llm(prompt_text, role="system" | "user")
```

## Comparison to Other Patterns

| Aspect | crewAI | Pure ReAct | Plan-and-Solve | Reflection |
|--------|--------|-----------|----------------|------------|
| Planning phase | No | No | Yes | No |
| Action-observation loop | Yes | Yes | Yes | Yes |
| Self-critique | Via error feedback | No | No | Yes |
| State mutation | Yes (messages) | Varies | Varies | Yes |
| Termination | Max iter OR finish | Finish signal | Plan complete | Converged |

**Classification**: **ReAct with error self-correction**

## Implications for New Framework

**Adopt**:
1. **ReAct loop** - proven effective for tool-using agents
2. **AgentAction/AgentFinish discrimination** - clear separation of intermediate vs final
3. **Error feedback to LLM** - enables self-correction on parser/tool errors
4. **Max iterations failsafe** - prevents infinite loops

**Avoid**:
1. **While-isinstance loops** - harder to reason about than explicit state machine
2. **Unbounded message accumulation** - can exceed context limits
3. **Mutation-heavy approach** - makes reasoning about state difficult
4. **Lack of explicit planning step** - complex tasks benefit from planning

**Improve**:
1. Separate pure step function from I/O (functional core, imperative shell)
2. Use explicit state machine: `State = Thinking | Acting | Observing | Finished`
3. Add planning phase before execution (Plan-and-Solve hybrid)
4. Implement sliding window or summarization for message history
5. Make iteration limit adaptive based on task complexity
6. Add reflection step after task completion (critique and improve)

## Code References

- Main loop: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L211`
- Max iteration check: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L220`
- LLM call: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L233`
- Response parsing: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L243`
- Action execution: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L245+`
- Error handling: `lib/crewai/src/crewai/agents/crew_agent_executor.py:L279`
- Parser types: `lib/crewai/src/crewai/agents/parser.py` (referenced)
- Message formatting: `lib/crewai/src/crewai/utilities/agent_utils.py` (format_message_for_llm)

## Anti-Patterns Observed

1. **While-isinstance predicate**: Harder to audit than explicit state machine
2. **Unbounded message list**: No automatic truncation or summarization
3. **In-place mutation**: `self.messages.append()` couples state and logic
4. **Iteration counter separate from state**: Could be part of typed State object
5. **No planning phase**: Jumps directly to action without task decomposition
6. **No reflection**: Doesn't critique output before returning
