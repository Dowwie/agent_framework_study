# Control Loop Extraction: CAMEL

## Primary Control Pattern

### Tool-Calling Loop (Dominant Pattern)

CAMEL's primary control loop is **tool-calling with streaming:**

```python
class ChatAgent:
    async def astep(
        self,
        input_message: Union[BaseMessage, str],
        ...
    ) -> ChatAgentResponse:
        # 1. Add user message to context
        self._append_message(user_message)

        # 2. Get model response (may include tool calls)
        response = await self._aget_model_response(...)

        # 3. Execute tools if requested
        if response.tool_calls:
            tool_results = await self._execute_tools_async(response.tool_calls)

            # 4. Send tool results back to model
            self._append_message(tool_results)
            response = await self._aget_model_response(...)  # Get final answer

        # 5. Check termination conditions
        if self._should_terminate(response):
            self.terminated = True

        return ChatAgentResponse(
            msgs=response.messages,
            terminated=self.terminated,
            ...
        )
```

**Flow Diagram:**
```
User Input
   ↓
[Add to context]
   ↓
[Call Model] ← ─ ─ ─ ─ ─ ─ ┐
   ↓                       │
Tool calls? ─ No → [Return response]
   ↓ Yes                   │
[Execute tools in parallel]│
   ↓                       │
[Add tool results]         │
   ↓                       │
[Call Model again] ─ ─ ─ ─ ┘
   ↓
[Check terminators]
   ↓
[Return response]
```

**Key Characteristics:**
- **Single-turn tool resolution:** Tools execute once per step, then model gets final say
- **Parallel tool execution:** Multiple tool calls execute concurrently
- **Streaming-aware:** Can stream content while tools run in background
- **Terminator-based exit:** Pluggable termination conditions

## Iteration Control

### Tool Call Iterations

**Maximum iteration limit:**

```python
class ChatAgent:
    def __init__(
        self,
        ...,
        tool_call_max_iterations: int = 5,
    ):
        self.tool_call_max_iterations = tool_call_max_iterations

    async def astep(self, ...):
        iteration = 0
        while iteration < self.tool_call_max_iterations:
            response = await self._aget_model_response(...)

            if not response.tool_calls:
                break  # No more tools, exit loop

            # Execute tools
            await self._execute_tools_async(response.tool_calls)
            iteration += 1

        if iteration >= self.tool_call_max_iterations:
            logger.warning("Max tool call iterations reached")
```

**Design:**
- Prevents infinite tool calling loops
- Default: 5 iterations
- Configurable per agent

**Weakness:** No adaptive iteration (e.g., "keep going until task complete")

### Termination Conditions

**Pluggable termination logic:**

```python
class BaseTerminator(ABC):
    @abstractmethod
    def is_terminated(self, messages: List[BaseMessage]) -> bool:
        pass

# Built-in terminators:
class ResponseWordsTerminator(ResponseTerminator):
    def __init__(self, words: List[str]):
        self.words = words

    def is_terminated(self, messages: List[BaseMessage]) -> bool:
        last_message = messages[-1].content
        return any(word in last_message.lower() for word in self.words)

class TokenLimitTerminator(BaseTerminator):
    def __init__(self, token_limit: int, model: str):
        self.token_limit = token_limit
        self.encoding = get_model_encoding(model)

    def is_terminated(self, messages: List[BaseMessage]) -> bool:
        total_tokens = sum(len(self.encoding.encode(m.content)) for m in messages)
        return total_tokens >= self.token_limit
```

**Usage:**
```python
agent = ChatAgent(
    system_message=...,
    response_terminators=[
        ResponseWordsTerminator(["TERMINATE", "<DONE>"]),
        TokenLimitTerminator(token_limit=10000, model="gpt-4"),
    ]
)
```

**Termination Check:**
```python
def _should_terminate(self, response) -> bool:
    for terminator in self.response_terminators:
        if terminator.is_terminated(self.stored_messages):
            return True
    return False
```

## Multi-Agent Control Patterns

### Role-Playing Pattern

**Two-agent conversational loop:**

```python
class RolePlaying:
    def init_chat(self) -> Tuple[BaseMessage, List[BaseMessage]]:
        # Initialize with task
        return task_message, []

    def step(
        self,
        assistant_msg: BaseMessage,
    ) -> Tuple[ChatAgentResponse, ChatAgentResponse]:
        # User agent responds to assistant
        user_response = self.user_agent.step(assistant_msg)

        # Optional: Critic evaluates
        if self.with_critic_in_the_loop:
            critique = self.critic.step(user_response.msg)
            user_response = self.user_agent.step(critique.msg)

        # Assistant responds to user
        assistant_response = self.assistant_agent.step(user_response.msg)

        return assistant_response, user_response
```

**Flow:**
```
Task Prompt
    ↓
Assistant generates plan/question
    ↓
User provides answer/feedback
    ↓  (optional)
Critic evaluates
    ↓
User refines answer
    ↓
Assistant continues
    ↓
[Repeat until termination]
```

**Termination:**
- Either agent can terminate
- Critic can force refinement
- External stop_event for cancellation

### Workforce Pattern

**Complex multi-agent orchestration:**

```python
class Workforce:
    def __init__(
        self,
        mode: WorkforceMode,  # PARALLEL, PIPELINE, LOOP
        workers: List[Worker],
        failure_handling: FailureHandlingConfig,
    ):
        self.mode = mode
        self.workers = workers

    async def run(self, tasks: List[Task]):
        if self.mode == WorkforceMode.PARALLEL:
            # Execute all workers in parallel
            results = await asyncio.gather(*[
                worker.execute(task) for task in tasks
            ])

        elif self.mode == WorkforceMode.PIPELINE:
            # Sequential execution, output feeds next
            result = tasks[0]
            for worker in self.workers:
                result = await worker.execute(result)

        elif self.mode == WorkforceMode.LOOP:
            # Iterative refinement until convergence
            result = tasks[0]
            iteration = 0
            while not self._is_converged(result):
                for worker in self.workers:
                    result = await worker.execute(result)
                iteration += 1
                if iteration >= self.max_iterations:
                    break

        return result
```

**Modes:**

1. **PARALLEL:** Independent task execution
   ```
   Task A → Worker 1 → Result A
   Task B → Worker 2 → Result B
   Task C → Worker 3 → Result C
   ```

2. **PIPELINE:** Sequential data flow
   ```
   Input → Worker 1 → Worker 2 → Worker 3 → Output
   ```

3. **LOOP:** Iterative refinement
   ```
   Input → [Worker 1 → Worker 2 → Worker 3] → Check convergence
                ↑__________________________|
   ```

**Convergence Detection:**
```python
class Workforce:
    def _is_converged(self, result: Any) -> bool:
        # Check if output has stabilized
        # Could be: identical output, quality threshold, user approval
        ...
```

## Reasoning Patterns

### Deductive Reasoning Agent

**Model-based deductive reasoning:**

```python
class DeductiveReasonerAgent(ChatAgent):
    r"""Model of deductive reasoning:
        L: A ⊕ C -> q * B
        - A: Starting state
        - B: Target state
        - C: Conditions required for A → B
        - Q: Quality of transition
        - L: Path/process from A to B
    """

    def deduce_conditions_and_quality(
        self,
        starting_state: str,
        target_state: str,
        role_descriptions_dict: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Union[List[str], Dict[str, str]]]:
        # Prompt model to derive:
        # 1. Conditions needed to go from A to B
        # 2. Quality metrics for the transition
        # 3. Path/process steps

        prompt = self._build_deduction_prompt(starting_state, target_state)
        response = self.step(prompt)

        # Extract structured output
        return self._parse_deduction_response(response)
```

**Use Case:** Planning, task decomposition, constraint satisfaction

**Pattern:** Uses LLM for logical reasoning, not hard-coded rules

### No Explicit ReAct Pattern

**CAMEL does NOT implement ReAct** (Reasoning + Acting):

**What's missing:**
```python
# Hypothetical ReAct pattern (NOT in CAMEL):
class ReActAgent:
    def step(self, observation: str):
        # 1. Thought: Reason about observation
        thought = self.model.run(f"Thought: {observation}")

        # 2. Action: Decide what to do
        action = self.model.run(f"Action: {thought}")

        # 3. Execute action, get observation
        observation = self.execute(action)

        # 4. Loop until task complete
        ...
```

**CAMEL's approach:**
- Tool calling is implicit action
- No explicit "thought" vs "action" distinction
- Model decides whether to use tools without structured prompting

**Tradeoff:**
- **Pro:** Simpler, relies on model's native capabilities
- **Con:** Less explicit reasoning trace
- **Con:** Harder to debug why agent chose specific tools

## Streaming Control

### Dual-Phase Streaming

**Reasoning-aware streaming:**

```python
class StreamContentAccumulator:
    def __init__(self):
        self.reasoning_content = []      # Model's thinking
        self.current_content = []         # Final answer
        self.is_reasoning_phase = True

    def add_chunk(self, chunk):
        if chunk.is_reasoning:
            self.reasoning_content.append(chunk.content)
        else:
            if self.is_reasoning_phase:
                self.is_reasoning_phase = False
            self.current_content.append(chunk.content)
```

**Flow:**
```
Stream Start
    ↓
[Reasoning Phase] → Accumulate reasoning content
    ↓ (phase transition)
[Answer Phase] → Accumulate final answer
    ↓
[Tool Call Phase] → Execute tools
    ↓
[Continue streaming]
```

**Benefits:**
- Separate reasoning trace from final answer
- Can display reasoning to user while model thinks
- Supports models like o1 with explicit reasoning

### Concurrent Tool + Stream

**Execute tools while streaming continues:**

```python
async def _astream_response(self, ...):
    tool_task = None

    async for chunk in model_stream:
        # Yield content as it arrives
        yield chunk

        # If tool calls detected, start execution in background
        if chunk.tool_calls and not tool_task:
            tool_task = asyncio.create_task(
                self._execute_tools_async(chunk.tool_calls)
            )

    # Wait for tools to finish
    if tool_task:
        await tool_task
        # Stream final response after tools
        async for chunk in self._astream(...):
            yield chunk
```

**Innovation:** Tools don't block streaming - user sees partial response immediately

## Control Loop Score

**Overall: 7.5/10**

**Breakdown:**
- Tool Calling Loop: 8/10 (solid, but limited iteration)
- Termination Control: 9/10 (pluggable, flexible)
- Multi-Agent Patterns: 8/10 (RolePlaying + Workforce well-designed)
- Reasoning Patterns: 6/10 (no ReAct, limited explainability)
- Streaming Control: 9/10 (concurrent tool + stream is innovative)
- Iteration Control: 6/10 (fixed max, no adaptive)

## Patterns to Adopt

1. **Pluggable terminators:** `BaseTerminator` abstraction for flexible exit conditions
2. **Concurrent tool + stream:** Execute tools in background while streaming
3. **Workforce modes:** PARALLEL, PIPELINE, LOOP for multi-agent orchestration
4. **Reasoning-aware streaming:** Separate reasoning content from final answer
5. **Failure-tolerant workflows:** `FailureHandlingConfig` with recovery strategies

## Patterns to Avoid

1. **No ReAct pattern:** Makes reasoning implicit, harder to debug
2. **Fixed iteration limits:** Should adapt based on task complexity
3. **Single-turn tool resolution:** Some tasks need multiple tool-call rounds
4. **No convergence criteria:** LOOP mode needs better stopping conditions
5. **Implicit action selection:** Should structure thought → action → observation

## Recommendations

1. **Add ReAct support:** Explicit thought/action/observation pattern
2. **Adaptive iteration:** Continue until task complete, not fixed count
3. **Multi-turn tool loops:** Allow tools → model → tools → model cycles
4. **Convergence metrics:** For LOOP mode, define when "good enough"
5. **Structured reasoning:** Separate reasoning trace in all responses (not just streaming)
6. **Checkpointing:** Save agent state during long loops for recovery
