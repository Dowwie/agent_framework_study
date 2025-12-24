# Control Loop Extraction: Agno

## Summary
- **Key Finding 1**: Optional reasoning phase before main model call - delegated to ReasoningManager
- **Key Finding 2**: Chain-of-Thought reasoning via structured ReasoningStep schema with NextAction enum
- **Key Finding 3**: ReAct pattern implied - tools available during reasoning, multi-step iteration
- **Classification**: Flexible reasoning pattern - supports native model reasoning (DeepSeek, Claude) AND custom CoT

## Reasoning Pattern
- **Primary**: Chain-of-Thought with optional native model reasoning
- **Step Function**: ReasoningStep with title, action, result, reasoning, next_action, confidence
- **Termination**: NextAction enum (CONTINUE, VALIDATE, FINAL_ANSWER, RESET)
- **Tool Availability**: Tools available during reasoning phase

## Loop Structure

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Run Loop                        │
├─────────────────────────────────────────────────────────┤
│  1. Register run for cancellation                       │
│  2. Retry loop (configurable attempts)                  │
│     ├─ Execute pre-hooks                                │
│     ├─ Determine tools for model                        │
│     ├─ Prepare run messages (context assembly)          │
│     ├─ Start background memory creation                 │
│     ├─ Start background cultural knowledge creation     │
│     ├─ Cancellation checkpoint                          │
│     ├─ [OPTIONAL] Reasoning phase                       │
│     │   ├─ Create ReasoningManager                      │
│     │   ├─ Reasoning loop:                              │
│     │   │   ├─ Generate reasoning step                  │
│     │   │   ├─ Check next_action                        │
│     │   │   ├─ If CONTINUE: generate next step          │
│     │   │   ├─ If VALIDATE: verify result               │
│     │   │   ├─ If FINAL_ANSWER: exit reasoning          │
│     │   │   └─ If RESET: start over                     │
│     │   └─ Update run_messages with reasoning output    │
│     ├─ Cancellation checkpoint                          │
│     ├─ Generate model response                          │
│     │   └─ (includes tool execution loop)               │
│     ├─ Execute post-hooks                               │
│     ├─ Wait for memory future                           │
│     └─ Wait for cultural knowledge future               │
│  3. Cleanup run from cancellation registry              │
└─────────────────────────────────────────────────────────┘
```

## Detailed Analysis

### Reasoning Step Schema

**Evidence** (`reasoning/step.py:14-27`):
```python
class ReasoningStep(BaseModel):
    title: Optional[str] = Field(None, description="A concise title")
    action: Optional[str] = Field(
        None, description="The action. Talk in first person like I will ..."
    )
    result: Optional[str] = Field(
        None, description="The result. Talk in first person like I did this and got ..."
    )
    reasoning: Optional[str] = Field(
        None, description="The thought process behind this step"
    )
    next_action: Optional[NextAction] = Field(
        None,
        description="Continue, validate, final_answer, or reset"
    )
    confidence: Optional[float] = Field(
        None, description="Confidence score (0.0 to 1.0)"
    )
```

**Design**: Structured reasoning with explicit action/result/reasoning separation
- **action**: What the agent plans to do
- **result**: What happened when action was executed
- **reasoning**: Why this action was chosen

This mirrors human thought process documentation.

### Next Action Control Flow

**Evidence** (`reasoning/step.py:7-11`):
```python
class NextAction(str, Enum):
    CONTINUE = "continue"       # Generate another reasoning step
    VALIDATE = "validate"       # Verify the current result
    FINAL_ANSWER = "final_answer"  # Reasoning complete, proceed
    RESET = "reset"            # Start reasoning over
```

**Pattern**: Explicit termination control
- Model decides when reasoning is complete via `FINAL_ANSWER`
- Can request validation of work via `VALIDATE`
- Can restart reasoning via `RESET`
- Default is `CONTINUE` for multi-step chains

### Reasoning Manager Pattern

**Evidence** (`agent/agent.py:9807-9846`):
```python
def _reason(self, run_response, run_messages, stream_events):
    """
    Run reasoning using the ReasoningManager.

    Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
    default Chain-of-Thought reasoning with a clean, unified interface.
    """
    from agno.reasoning.manager import ReasoningManager

    # Use dedicated reasoning model OR copy of main model
    reasoning_model = self.reasoning_model
    if reasoning_model is None and self.model is not None:
        reasoning_model = deepcopy(self.model)

    # Create manager with config
    manager = ReasoningManager(
        ReasoningConfig(
            reasoning_model=reasoning_model,
            reasoning_agent=self.reasoning_agent,
            min_steps=self.reasoning_min_steps,
            max_steps=self.reasoning_max_steps,
            tools=self.tools,  # Tools available during reasoning
            tool_call_limit=self.tool_call_limit,
            # ... config
        )
    )

    # Run reasoning and convert events
    for event in manager.reason(run_messages, stream=stream_events):
        yield from self._handle_reasoning_event(event, run_response)
```

**Delegation Pattern**: Agent doesn't implement reasoning loop - delegates to ReasoningManager
- Separates reasoning logic from agent orchestration
- Allows different reasoning strategies (native vs CoT)
- Config-driven (min/max steps, tools, etc.)

### Native vs. Chain-of-Thought Reasoning

**Evidence**: Comment in `agent/agent.py:9813-9814`:
```python
"""
Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
default Chain-of-Thought reasoning with a clean, unified interface.
"""
```

**Strategy**:
1. **Native Reasoning**: Models like DeepSeek-R1, Claude Extended Thinking have built-in reasoning
2. **Chain-of-Thought**: Framework generates reasoning steps via structured prompting

The ReasoningManager abstracts this choice, providing a unified interface.

### Tool Availability During Reasoning

**Evidence**: `agent/agent.py:9832` passes `tools=self.tools` to ReasoningManager

**Implication**: Tools can be called during reasoning phase, not just after
- Reasoning can include information gathering
- This is closer to ReAct (Reason + Act) than pure CoT

### Reasoning-to-Execution Handoff

**Execution Flow** (`agent/agent.py:1083-1092`):
```python
# 5. Reason about the task
self._handle_reasoning(run_response=run_response, run_messages=run_messages)

# Check for cancellation
raise_if_cancelled(run_response.run_id)

# 6. Generate a response from the Model (includes running function calls)
model_response: ModelResponse = self.model.response(
    messages=run_messages.messages,  # Includes reasoning output
    tools=_tools,
    # ...
)
```

**Pattern**: Reasoning updates `run_messages`, then model generates response
- Reasoning output becomes part of context for main model call
- Main model sees the reasoning steps and continues from there

### Min/Max Steps Configuration

**Evidence**: `agent/agent.py:9831-9832, 9871-9872`:
```python
min_steps=self.reasoning_min_steps,
max_steps=self.reasoning_max_steps,
```

**Control**: User can constrain reasoning depth
- `min_steps`: Ensure at least N reasoning steps (prevent lazy shortcuts)
- `max_steps`: Cap reasoning to prevent infinite loops

### Optional Reasoning

**Pattern**: Reasoning phase is optional (controlled by config)
- If `enable_reasoning` is false, skip reasoning phase entirely
- Agent can run with or without explicit reasoning
- This is efficient for simple tasks

### Confidence Tracking

**Evidence**: `reasoning/step.py:27` has `confidence: Optional[float]`

**Pattern**: Each reasoning step can report confidence (0.0 to 1.0)
- Could be used for self-verification
- Could trigger validation when confidence is low
- Currently optional (not always populated)

## Implications for New Framework

1. **Separate reasoning from execution** - ReasoningManager pattern is clean separation
2. **Structured reasoning schema** - ReasoningStep with action/result/reasoning is clear
3. **Explicit termination control** - NextAction enum gives model control over loop exit
4. **Support both native and custom reasoning** - Abstraction layer works well
5. **Tools during reasoning** - ReAct pattern is more powerful than pure CoT
6. **Configurable depth** - Min/max steps prevent both laziness and infinite loops
7. **Optional reasoning** - Don't force reasoning for simple tasks

## Anti-Patterns Observed

1. **Confidence field underutilized** - Present but no automatic validation on low confidence
2. **VALIDATE action unclear** - What happens during validation isn't documented in schema
3. **RESET action risky** - Could cause infinite reasoning loops if misused
4. **Reasoning model deepcopy** - `deepcopy(self.model)` (line 9823) is expensive
5. **No reasoning timeout** - Only max_steps constraint, no wall-clock timeout
6. **Reasoning manager recreated per run** - Could be cached (lines 9826-9842)

## Code References
- `libs/agno/agno/reasoning/step.py:7-11` - NextAction enum for termination control
- `libs/agno/agno/reasoning/step.py:14-27` - ReasoningStep schema definition
- `libs/agno/agno/reasoning/step.py:30-31` - ReasoningSteps container
- `libs/agno/agno/agent/agent.py:9807-9846` - Sync reasoning implementation with ReasoningManager
- `libs/agno/agno/agent/agent.py:9848-9880` - Async reasoning implementation
- `libs/agno/agno/agent/agent.py:9818-9823` - Reasoning model selection (dedicated vs deepcopy)
- `libs/agno/agno/agent/agent.py:9826-9842` - ReasoningManager config with tools
- `libs/agno/agno/agent/agent.py:1083-1092` - Reasoning-to-execution handoff in main loop
