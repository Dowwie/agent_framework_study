# Multi-Agent Analysis: crewAI

## Summary
- **Coordination Model**: Hierarchical (manager-worker) + Sequential (peer collaboration)
- **Handoff Mechanism**: Explicit delegation via AgentTools
- **State Sharing**: Shared crew context + task outputs as input to subsequent tasks
- **Communication**: Tool-based (ask_question, delegate_work)

## Detailed Analysis

### Coordination Models

**Two Modes**:

1. **Sequential Process** (process.py:L9):
```python
class Process(str, Enum):
    sequential = "sequential"
```
- Tasks executed in predefined order
- Each agent completes assigned task before next starts
- Output of Task N becomes context for Task N+1
- Peer-to-peer collaboration via delegation tools

2. **Hierarchical Process** (process.py:L10):
```python
hierarchical = "hierarchical"
```
- Manager agent coordinates worker agents
- Manager delegates tasks dynamically based on goals
- Workers report results back to manager
- Manager synthesizes final output

**Selection** (crew.py:L713-716):
```python
if self.process == Process.sequential:
    result = self._run_sequential_process()
elif self.process == Process.hierarchical:
    result = self._run_hierarchical_process()
```

**Validation** (crew.py:L404-425):
```python
@model_validator(mode="after")
def check_manager_llm(self) -> Self:
    if self.process == Process.hierarchical:
        if not self.manager_llm and not self.manager_agent:
            raise PydanticCustomError(...)
        if self.manager_agent in self.agents:
            raise PydanticCustomError("manager_agent_in_agents", ...)
```
- Hierarchical requires manager LLM or manager agent
- Manager cannot also be in worker agent list

### Handoff Mechanism

**Type**: **Tool-based explicit delegation**

**AgentTools** (base_agent.py:L93-94):
```python
@abstractmethod
def get_delegation_tools(agents: list["BaseAgent"]):
    # Creates tools for delegation and asking questions
```

**Implementation** (agent/core.py:L64):
```python
from crewai.tools.agent_tools.agent_tools import AgentTools
```

**Delegation Tools**:
1. **delegate_work**: Assign task to specific agent
2. **ask_question**: Request information from specific agent

**Execution**:
- Delegation tool selected by LLM like any other tool
- Tool executes target agent with subtask
- Result returned as observation
- Original agent continues with result

**Handoff Protocol**: Message passing
- Delegating agent constructs task description
- Target agent receives task + context
- Target agent executes and returns result
- No shared mutable state during handoff

### State Sharing

**Shared State**:

1. **Crew Context** (crew.py:L705-708):
```python
baggage_ctx = baggage.set_baggage(
    "crew_context", CrewContext(id=str(self.id), key=self.key)
)
token = attach(baggage_ctx)
# OpenTelemetry baggage for cross-agent context
```

2. **Task Context** (task.py:L73):
```python
context: list[Task] | None = Field(
    default=None, description="List of Task instances providing context"
)
```
- Previous task outputs injected as context
- Sequential composition via context chain

3. **Memory** (crew.py:L72):
```python
memory: bool = False  # Shared crew memory
```
- If enabled, all agents share memory subsystems
- Short-term, long-term, entity, external memory

**Isolated State**:
- Agent-specific: `_times_executed`, `_last_messages` (agent/core.py:L128-130)
- Task-specific: `used_tools`, `tools_errors`, `delegations` (task.py:L90-92)

**Memory Scope** (memory/memory.py:L22-23):
```python
_agent: Agent | None = None
_task: Task | None = None
# Memory tagged with current agent/task for retrieval
```

### Agent Discovery

**Agent List** (crew.py:L113):
```python
agents: list[BaseAgent] = Field(default=[], description="List of agents")
```
- Agents known at crew construction time
- No dynamic agent discovery
- Manager can delegate to any agent in list

**Tool-Based Routing**:
- LLM decides which agent to delegate to
- Based on agent role, goal, backstory in prompt
- No automatic routing based on capabilities

### Communication Patterns

**1. Sequential Handoff** (implicit):
```
Agent1 (Task1) → output → Agent2 (Task2 context) → output → Agent3 (Task3 context)
```

**2. Hierarchical Delegation** (explicit):
```
Manager → delegate_work(worker1, subtask1) → Worker1 executes → result → Manager
       → delegate_work(worker2, subtask2) → Worker2 executes → result → Manager
       → synthesize results → final output
```

**3. Peer Collaboration** (explicit):
```
Agent1 → ask_question(Agent2, question) → Agent2 responds → Agent1 continues
```

**Message Format**:
- Tool-based: Structured as tool calls with arguments
- No direct agent-to-agent messaging
- All communication mediated by tool execution

### Task Output Propagation

**Task Output** (task_output.py:L12):
```python
class TaskOutput(BaseModel):
    description: str
    raw: str
    pydantic: BaseModel | None
    json_dict: dict[str, Any] | None
    agent: str
    output_format: OutputFormat
```

**Context Injection** (crew.py:L43):
```python
from crewai.crews.utils import prepare_task_execution
# Injects previous task outputs into current task context
```

**Aggregation** (crew.py:L91-93):
```python
from crewai.utilities.formatter import (
    aggregate_raw_outputs_from_task_outputs,
    aggregate_raw_outputs_from_tasks,
)
```
- Combines outputs from multiple tasks
- Used in crew final output

## Implications for New Framework

**Adopt**:
1. **Dual coordination modes** - sequential for simple workflows, hierarchical for complex
2. **Tool-based delegation** - explicit, auditable, LLM-driven routing
3. **Task output as context** - natural flow of information
4. **Shared memory** - enables multi-agent learning
5. **OpenTelemetry baggage** - distributed tracing across agents

**Avoid**:
1. **Static agent list** - no dynamic agent spawning
2. **Manager in workers constraint** - unnecessarily restrictive
3. **LLM-based routing only** - no capability-based matching
4. **No direct messaging** - all via tool calls (overhead)

**Improve**:
1. Add capability-based agent discovery (match task requirements to agent skills)
2. Support dynamic agent spawning (create specialists on demand)
3. Add agent pools for load balancing
4. Implement direct agent-to-agent messaging channel (not just tool calls)
5. Add consensus mechanisms for multi-agent decision making
6. Support agent hierarchies deeper than 2 levels (manager → team lead → worker)
7. Add agent registry for lookup by capability tags
8. Implement work stealing for load balancing

## Code References

- Process enum: `lib/crewai/src/crewai/process.py:L4`
- Process selection: `lib/crewai/src/crewai/crew.py:L713-716`
- Manager validation: `lib/crewai/src/crewai/crew.py:L404-425`
- AgentTools: `lib/crewai/src/crewai/tools/agent_tools/agent_tools.py`
- Delegation interface: `lib/crewai/src/crewai/agents/agent_builder/base_agent.py:L93`
- Task context: `lib/crewai/src/crewai/task.py:L73`
- Crew context: `lib/crewai/src/crewai/crew.py:L705-708`
- Memory scope: `lib/crewai/src/crewai/memory/memory.py:L22-23`
- Output aggregation: `lib/crewai/src/crewai/utilities/formatter.py`
- Task preparation: `lib/crewai/src/crewai/crews/utils.py` (prepare_task_execution)

## Anti-Patterns Observed

1. **Static agent topology**: Agents defined at construction, can't add/remove dynamically
2. **No capability matching**: LLM must know which agent to delegate to
3. **Tool call overhead**: All communication requires tool execution
4. **Two-level hierarchy limit**: Manager → workers, no deeper nesting
5. **No load balancing**: Multiple capable agents can't share work
6. **Synchronous delegation**: Delegating agent blocks until subtask completes
