# Multi-Agent Analysis: Google ADK

## Summary
- **Key Finding 1**: Hierarchical multi-agent via parent_agent/sub_agents composition
- **Key Finding 2**: Agent-as-tool pattern via AgentTool wrapper
- **Classification**: Tree-structured with delegation (not peer-to-peer)

## Detailed Analysis

### Multi-Agent Architecture

**Hierarchical Model**:
```
RootAgent
  ├─ SubAgent1
  │    ├─ SubAgent1A
  │    └─ SubAgent1B
  ├─ SubAgent2
  └─ SubAgent3
```

**Relationships**:
- Each agent has `parent_agent: Optional[BaseAgent]`
- Each agent has `sub_agents: list[BaseAgent]`
- Tree structure enforced (no cycles)

### Coordination Patterns

**1. Direct Sub-Agent Invocation**:
```python
agent = LlmAgent(
    name="orchestrator",
    sub_agents=[agent1, agent2, agent3]
)
```

Sub-agents automatically exposed as tools via `transfer_to_agent` function.

**2. Agent-as-Tool**:
```python
from google.adk.tools import AgentTool

agent_tool = AgentTool(agent=specialized_agent)
orchestrator = LlmAgent(
    name="orchestrator",
    tools=[agent_tool]
)
```

Agent wrapped as a tool - LLM invokes like any other tool.

**3. A2A Protocol** (Agent-to-Agent):
```python
# Remote agent invocation via A2A protocol
remote_agent_tool = A2ATool(
    agent_url="https://remote-agent.example.com"
)
```

Supports remote agent communication.

### Delegation Mechanism

**Transfer Flow**:
1. Parent agent LLM decides to delegate
2. LLM calls `transfer_to_agent` tool
3. Framework invokes sub-agent.run_async()
4. Sub-agent executes with own context
5. Sub-agent returns response
6. Parent agent receives response and continues

**Context Passing**:
```python
SubAgentContext:
  - invocation_id: str  # Unique invocation
  - branch: str         # Conversation branch
  - session: Session    # Shared session state
  - agent_states: dict  # Per-agent state
```

**State Sharing**:
- Session shared across all agents in tree
- Each agent has isolated `agent_states[agent_name]`
- Artifacts shared via session.artifacts

### Control Flow

**Parent-Child Execution**:
```
Parent LLM: "I need to search the web"
  ├─ Calls transfer_to_agent("search_agent")
  ├─ Framework invokes search_agent.run_async()
  │    └─ Search agent executes (can use own tools)
  ├─ Search agent returns results
  └─ Parent LLM receives results and continues
```

**No Parallel Execution**:
- Sub-agents execute sequentially
- No concurrent multi-agent collaboration
- Parent waits for child to complete

### Communication Patterns

**1. Hierarchical Delegation** (Primary):
- Parent delegates to child
- Child returns result to parent
- Parent decides next action

**2. Sibling Communication** (Indirect):
- No direct sibling communication
- Must go through parent orchestrator
- Parent routes messages between siblings

**3. Remote Agent (A2A)**:
- HTTP-based agent invocation
- Authentication via OAuth2 or service accounts
- Structured request/response protocol

### State Isolation

**Per-Agent State**:
```python
agent_states = {
    "orchestrator": {"plan": ["step1", "step2"]},
    "search_agent": {"last_query": "..."},
    "writer_agent": {"draft": "..."}
}
```

**Shared Resources**:
- Session history (all agents see conversation)
- Artifacts (files uploaded/created)
- Memory service (if configured)

### Agent Tree Management

**Sub-Agent Registration**:
```python
parent = LlmAgent(
    name="parent",
    sub_agents=[child1, child2]
)
# parent_agent field automatically set on children
```

**Dynamic Addition** (Not Supported):
- Sub-agents must be defined at agent creation
- Cannot dynamically add/remove sub-agents at runtime

### A2A Protocol Integration

**Remote Agent Tool**:
```python
A2ATool(
    name="remote_bigquery_agent",
    agent_url="https://bigquery-agent.example.com",
    auth_config=AuthConfig(...)
)
```

**Features**:
- Remote agent invocation
- Authentication handling
- Retry and timeout support
- Structured error handling

### Failure Handling

**Sub-Agent Failure**:
- If sub-agent raises exception, propagates to parent
- Parent agent sees error in function_response
- Parent LLM can retry or handle error

**Timeout**:
- No built-in timeout for sub-agent execution
- Long-running sub-agents can block parent

## Implications for New Framework

### Positive Patterns
- **Tree structure**: Clean hierarchical organization
- **Agent-as-tool**: Elegant abstraction (agents are tools)
- **State isolation**: Each agent has private state
- **A2A protocol**: Enables distributed agent systems
- **Shared session**: Conversation context preserved across agents

### Considerations
- **No parallelism**: Sequential execution only (no concurrent agents)
- **No peer-to-peer**: Must use parent orchestrator for sibling communication
- **Static topology**: Cannot dynamically restructure agent tree
- **No load balancing**: No mechanism to distribute work across agent instances

## Code References
- `agents/base_agent.py:124` - parent_agent field
- `agents/base_agent.py:133` - sub_agents field
- `tools/agent_tool.py` - AgentTool wrapper
- `tools/transfer_to_agent_tool.py` - transfer_to_agent function
- `a2a/executor/a2a_executor.py` - A2A protocol executor
- `a2a/converters/` - A2A request/response conversion
- `flows/llm_flows/agent_transfer.py` - Agent transfer logic

## Anti-Patterns Observed
- **No concurrent execution**: Cannot run multiple sub-agents in parallel
- **No supervisor pattern**: No built-in orchestration beyond simple delegation
- **No routing**: Parent must manually route to correct sub-agent (no auto-routing)
- **No consensus**: No mechanism for multiple agents to vote or agree
