# Multi-Agent Analysis: Swarm

## Summary
- **Coordination Model**: Handoff-based (one active agent at a time)
- **Architecture**: Sequential agent switching, not parallel
- **Handoff Mechanism**: Tool-based (tools return Agent to switch)
- **State Sharing**: Full sharing (history and context_variables)
- **Named Pattern**: "Swarm" refers to agent handoffs, not concurrent swarm behavior

## Coordination Model

**Type**: Sequential handoff (not true swarm/multi-agent parallel)

**Pattern**:
```
Agent A is active
    ↓
Agent A calls tool
    ↓
Tool returns Agent B (instead of string result)
    ↓
Agent B becomes active
    ↓
Agent B calls tool
    ↓
...
```

**Key insight**: Despite the name "Swarm", this is **not** a swarm architecture (no concurrent agents, no emergent behavior). It's a **handoff/routing** architecture.

## Architecture Classification

### Not a Swarm
- ❌ No concurrent agent execution
- ❌ No distributed decision-making
- ❌ No emergent collective behavior
- ❌ No agent-to-agent communication

### Actually: Sequential Router
- ✅ One agent active at a time
- ✅ Explicit handoffs via tool returns
- ✅ Linear conversation flow
- ✅ Centralized orchestration (Swarm class manages all agents)

### Comparison to True Multi-Agent Patterns

| Pattern | Swarm Framework | True Multi-Agent |
|---------|----------------|------------------|
| **Concurrent agents** | No (sequential) | Yes (parallel execution) |
| **Communication** | Via handoff only | Message passing, shared memory |
| **Decision-making** | Single active agent | Collaborative or competitive |
| **Coordination** | Tool-based routing | Supervisor, peer-to-peer, blackboard |
| **State** | Fully shared | Often isolated or selectively shared |

## Handoff Mechanism

### Tool-Based Handoff

**Method**: Tool returns `Agent` instead of string

```python
# Example from examples/basic/agent_handoff.py conceptually
def transfer_to_sales() -> Agent:
    """Transfer to sales agent"""
    return sales_agent

spanish_agent = Agent(
    name="Spanish Agent",
    functions=[transfer_to_sales]
)
```

### Detection
```python
# core.py:L76-80
case Agent() as agent:
    return Result(
        value=json.dumps({"assistant": agent.name}),
        agent=agent,
    )
```

**Pattern matching**: If tool returns `Agent` instance, wrap in `Result` with handoff

### Execution
```python
# core.py:L134-135
if result.agent:
    partial_response.agent = result.agent

# core.py:L285-286
if partial_response.agent:
    active_agent = partial_response.agent
```

**Effect**: Next loop iteration uses new agent's:
- Instructions
- Functions (tools)
- Model
- Tool choice preferences

### Message to LLM
```python
# core.py:L78
value=json.dumps({"assistant": agent.name})
```

**LLM sees**: `{"assistant": "Sales Agent"}` as tool result
**Purpose**: Inform LLM that handoff occurred (for context continuity)

## State Sharing

### Fully Shared: History
```python
# core.py:L254
history = copy.deepcopy(messages)  # Isolated from caller, but...

# core.py:L196, L271
history.append(message)  # All agents see all messages

# No per-agent history isolation
```

**Implication**: New agent sees entire conversation history, including:
- Messages from previous agents
- All tool calls and results
- User messages

**Benefit**: Continuity - new agent has full context
**Risk**: Privacy - sensitive info from one agent visible to all subsequent agents

### Fully Shared: Context Variables
```python
# core.py:L150
context_variables = copy.deepcopy(context_variables)

# core.py:L219, L284
context_variables.update(partial_response.context_variables)
```

**Scope**: Global across all agents in a run
**Use case**: Session state (user_id, preferences, accumulated data)

**Example flow**:
```
Agent A sets context_variables["user_tier"] = "premium"
    → Agent B can read context_variables["user_tier"]
        → Agent C can update context_variables["purchase_history"] = [...]
```

### No State Isolation
**Missing**: No per-agent private state

All state is shared:
- No agent-specific memory
- No agent-specific context
- No agent secrets

## Agent Switching Mechanics

### Switch Points
**Only during tool execution**: Agent switch only happens when:
1. Current agent calls a tool
2. Tool returns `Agent` instance
3. Framework updates `active_agent` for next turn

**Cannot switch**:
- Mid-turn (LLM completion is atomic)
- From user input (user can't directly request agent switch)
- Based on content analysis (no automatic routing)

### Switch Persistence
```python
# core.py:L285-286
if partial_response.agent:
    active_agent = partial_response.agent
```

**Duration**: Until another tool returns a different agent
**Reversal**: Can return to previous agent if tool returns it

**Example**:
```
Start with Agent A
    → Tool returns Agent B
        → Agent B active
            → Tool returns Agent A
                → Back to Agent A
```

## Coordination Patterns in Practice

### Pattern 1: Triage
```python
# Triage agent routes to specialists
triage_agent = Agent(
    name="Triage",
    functions=[transfer_to_sales, transfer_to_support, transfer_to_billing]
)
```

**Use case**: User message → Triage decides which specialist → Handoff

### Pattern 2: Escalation
```python
# L1 support escalates to L2
l1_agent = Agent(
    functions=[resolve_simple_issues, escalate_to_l2]
)
```

**Use case**: L1 can't solve → Escalate to L2 with full context

### Pattern 3: Specialization
```python
# Different languages
english_agent = Agent(functions=[switch_to_spanish])
spanish_agent = Agent(functions=[switch_to_english])
```

**Use case**: User switches language → Agent switches

### Pattern 4: Workflow Steps
```python
# Multi-step process
info_gathering_agent = Agent(functions=[proceed_to_validation])
validation_agent = Agent(functions=[proceed_to_execution])
execution_agent = Agent(functions=[finish])
```

**Use case**: Sequential workflow with hand-offs between stages

## Multi-Agent Challenges Not Addressed

### 1. Concurrent Execution
**Limitation**: Can't run multiple agents in parallel
**Missing**: No way to delegate sub-tasks to multiple agents simultaneously

### 2. Agent Communication
**Limitation**: Agents don't communicate directly
**Current**: Communication only via shared history
**Missing**: Direct messages, broadcasts, subscriptions

### 3. Conflict Resolution
**Limitation**: N/A (only one agent active)
**Missing**: No mechanism for resolving disagreements between agents

### 4. Resource Allocation
**Limitation**: All agents share same resources (API quota, context window)
**Missing**: Per-agent budgets, rate limiting

### 5. Agent Discovery
**Limitation**: Tools must explicitly return specific agents
**Missing**: Registry of available agents, dynamic selection

### 6. Supervision
**Limitation**: No supervisor agent can monitor or override
**Missing**: Hierarchical control, circuit breakers

## Implications for New Framework

### Adopt
1. **Tool-based handoff** - Elegant, explicit, type-safe
2. **Shared history** - Good default for continuity
3. **Context variables for session state** - Clean channel for non-LLM data
4. **Simple mental model** - Easy to understand "one agent at a time"

### Add for True Multi-Agent
1. **Parallel agent execution** - Use async to run multiple agents concurrently
2. **Message passing** - Agents send messages to each other, not just shared history
3. **Agent registry** - Discover and route to agents by capability, not hardcoded
4. **Supervisor layer** - Orchestrate multiple agents, aggregate results
5. **Per-agent budgets** - Isolate resource consumption
6. **State isolation options** - Private vs shared state per agent

### Improve Current Model
1. **Automatic routing** - Use LLM to decide which agent, not require explicit tool
2. **Return to previous agent** - Stack-based agent tracking for easy return
3. **Agent metadata** - Capabilities, descriptions for dynamic selection
4. **Handoff reasons** - Structured data on why handoff occurred
5. **Handoff history** - Track agent transition path

### Anti-Patterns Observed
1. **Misleading name** - "Swarm" implies parallel/emergent, but it's sequential routing
2. **No concurrency** - Misses key benefit of multi-agent systems
3. **No agent isolation** - All agents see everything (privacy risk)
4. **Manual routing only** - Requires explicit tool for each handoff
5. **No supervisor** - Can't override or monitor agent behavior

## Agent Handoff Protocol

### Handoff Data Structure
```python
# types.py:L29-42
class Result(BaseModel):
    value: str = ""
    agent: Optional[Agent] = None  # Handoff target
    context_variables: dict = {}   # Updated state
```

**Fields**:
- `value`: Tool result string (sent to LLM)
- `agent`: If present, switch to this agent
- `context_variables`: Merge into session state

### Handoff Example
```python
def transfer_to_sales(context_variables: dict) -> Result:
    # Could add handoff reason to context
    context_variables["handoff_reason"] = "customer wants to buy"

    return Result(
        value="Transferring to sales agent",
        agent=sales_agent,
        context_variables=context_variables
    )
```

**LLM sees**: "Transferring to sales agent" (the `value`)
**Framework does**: Switch to `sales_agent` for next turn

## Code References

- `swarm/types.py:29-42` - Result model with agent handoff
- `swarm/types.py:14-21` - Agent model
- `swarm/core.py:76-80` - Agent return detection (pattern match)
- `swarm/core.py:134-135` - Partial response agent handoff
- `swarm/core.py:220-221` - Agent switch execution (streaming)
- `swarm/core.py:285-286` - Agent switch execution (non-streaming)
- `examples/basic/agent_handoff.py` - Basic handoff example
- `examples/triage_agent/` - Triage routing example

## Recommended Terminology

**Current name**: Swarm (misleading)
**Better names**:
- Agent Router
- Agent Handoff Framework
- Sequential Multi-Agent Framework
- Agent Delegation Framework

**"Swarm" should be reserved for**: Frameworks with concurrent agents exhibiting emergent behavior.
