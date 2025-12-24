# Multi-Agent Analysis: LlamaIndex

## Summary
- **Key Finding 1**: Hierarchical coordination model with supervisor agent delegating to specialized agents
- **Key Finding 2**: Handoff mechanism via special "handoff" tool generated from can_handoff_to field
- **Key Finding 3**: Shared state via workflow context, isolated memory per agent
- **Classification**: Hierarchical multi-agent with tool-based handoffs

## Detailed Analysis

### Coordination Model

**Pattern**: Hierarchical (Supervisor-Worker)

LlamaIndex implements a supervisor pattern where one agent coordinates delegation to specialized sub-agents.

**Evidence** (multi_agent_workflow.py):
- `MultiAgentWorkflow` class orchestrates multiple agents
- `can_handoff_to: Optional[List[str]]` field on BaseWorkflowAgent (base_agent.py:L90-92)
- Handoff via generated "handoff" tool
- Root agent runs first, can delegate to named agents

**Architecture**:
```
MultiAgentWorkflow
    ├── Root Agent (supervisor)
    │   ├── tools: [search, calculate]
    │   └── can_handoff_to: ["research_agent", "math_agent"]
    ├── Research Agent (specialist)
    │   └── tools: [web_search, paper_search]
    └── Math Agent (specialist)
        └── tools: [calculator, plot]
```

### Handoff Mechanism

**Type**: Tool-based (explicit)

Handoffs are implemented as a special tool that the LLM can call to delegate work.

**Setup** (base_agent.py:L90-92):
```python
can_handoff_to: Optional[List[str]] = Field(
    default=None, description="The agent names that this agent can hand off to"
)
```

**Reserved Tool Name** (base_agent.py:L193-196):
```python
for tool in validated_tools:
    if tool.metadata.name == "handoff":
        raise ValueError("'handoff' is a reserved tool name.")
```

The framework auto-generates a "handoff" tool based on `can_handoff_to`.

**Handoff Flow**:
1. Root agent decides to delegate
2. Calls "handoff" tool with target agent name
3. MultiAgentWorkflow routes to target agent
4. Target agent runs until completion
5. Result returned to root agent
6. Root agent can continue or finish

**Protocol**: Message passing via workflow events

When an agent hands off, it emits an event that the workflow processes:
```python
# Hypothetical event structure
AgentOutput(
    current_agent_name="root_agent",
    tool_calls=[
        ToolSelection(tool_name="handoff", tool_kwargs={"agent": "research_agent", "task": "Find papers on RAG"})
    ]
)
```

### State Sharing

**Approach**: Hybrid - shared context, isolated memory

**Shared State** (via workflow context):
- `ctx.store` is shared across all agents
- Agents can read/write to shared state
- Used for passing data between agents

**Isolated State**:
- Each agent has its own `initial_state` (base_agent.py:L96-99)
- Each agent has its own memory instance
- Reasoning history is per-agent (stored in ctx.store under agent-specific key)

**Example**:
```python
# Shared state (all agents can access)
await ctx.store.set("shared_findings", findings)

# Per-agent state (isolated)
await ctx.store.set(f"{self.name}_reasoning", reasoning_steps)
```

**Scope**: Shared state is global to the workflow, but agents access it explicitly via keys.

### Agent Discovery and Routing

**Discovery**: Static (configured at initialization)

Agents are registered in `MultiAgentWorkflow`:
```python
workflow = MultiAgentWorkflow(
    agents={
        "root": root_agent,
        "research": research_agent,
        "math": math_agent,
    }
)
```

**Routing**: Name-based

When "handoff" tool is called with `agent="research"`, workflow looks up the agent by name and delegates.

**No Dynamic Discovery**: Agents cannot discover each other at runtime. All handoff targets must be declared in `can_handoff_to`.

### Retry Messages and Error Propagation

**Cross-Agent Error Handling** (multi_agent_workflow.py:L241-245):
```python
if ev.retry_messages:
    # Pass retry messages to next LLM call
    await memory.aput_messages([
        *ev.retry_messages,
    ])
```

If an agent encounters a parse error or tool error, retry messages are added to its memory so the next LLM call can self-correct.

**No Cross-Agent Error Forwarding**: Errors are handled within the agent that produced them. If a delegated agent fails, the root agent sees the final output, not the error details.

### Memory Isolation

Each agent has its own memory instance:
```python
class BaseWorkflowAgent:
    # Each agent has separate memory
    memory: BaseMemory = Field(default_factory=ChatMemoryBuffer)
```

**Implications**:
- Root agent doesn't see sub-agent's internal reasoning
- Sub-agent doesn't see root agent's history
- Communication is via tool results only

**Workaround**: Agents can access shared context via `ctx.store` for explicit data sharing.

### Current Agent Tracking

**AgentOutput includes agent name** (workflow_events.py):
```python
class AgentOutput(BaseModel):
    current_agent_name: str  # Which agent produced this output
    response: ChatMessage
    tool_calls: Optional[List[ToolSelection]]
    retry_messages: Optional[List[ChatMessage]]
```

This enables the workflow to track which agent is active and route events correctly.

## Code References

- `llama-index-core/llama_index/core/agent/workflow/multi_agent_workflow.py` — MultiAgentWorkflow orchestrator
- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:90` — can_handoff_to field
- `llama-index-core/llama_index/core/agent/workflow/workflow_events.py` — AgentOutput with current_agent_name
- `llama-index-core/llama_index/core/workflow/context.py` — Shared context store

## Implications for New Framework

1. **Tool-based handoffs are elegant**: Using the tool interface for handoffs means no special syntax - the LLM just "calls a tool" to delegate. This is more natural than custom control flow.

2. **can_handoff_to for explicit delegation**: Declaring which agents can delegate to which prevents infinite delegation loops and makes the graph explicit.

3. **Shared context + isolated memory**: Hybrid approach enables both data sharing (via context) and isolation (via memory). This is flexible.

4. **Agent name in output**: Tracking `current_agent_name` enables debugging and observability in multi-agent workflows.

5. **Hierarchical works for specialization**: Supervisor delegating to specialists is intuitive and maps well to real-world workflows.

## Anti-Patterns Observed

1. **No delegation graph visualization**: With multiple agents and handoff relationships, there's no built-in way to visualize the delegation graph. Hard to understand complex workflows.

2. **String-based agent references**: Agent names are strings, making typos easy. Typed agent IDs would be safer.

3. **No handoff history**: No tracking of which agent delegated to which. Hard to debug delegation chains.

4. **Memory isolation prevents learning**: If root agent delegates to specialist, the specialist's reasoning is lost. Root can't learn from specialist's approach.

5. **No agent capability discovery**: Agents must hardcode handoff targets. Dynamic capability-based routing (e.g., "find agent that can search papers") would be more flexible.

6. **No max delegation depth**: Agents could create infinite delegation chains (A → B → C → A). Need cycle detection.

7. **Shared context is unstructured**: `ctx.store` is a plain key-value store. No schema for shared data, leading to key collisions and type errors.

## Recommendations

- Add delegation depth limit (max hops)
- Implement delegation graph visualization
- Use typed agent IDs (enum or literal types)
- Track delegation history (who called whom, when, why)
- Add cycle detection in delegation chains
- Implement structured shared state (Pydantic models with namespacing)
- Consider peer-to-peer pattern as alternative to strict hierarchy
- Add capability-based agent discovery (agents register skills, others query)
- Enable optional memory sharing (root sees specialist's reasoning)
