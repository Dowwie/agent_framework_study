# Multi-Agent Analysis: pydantic-ai

## Summary

- **Multi-Agent Support**: Yes - Agent-to-Agent (A2A) handoffs
- **Coordination Model**: Agent as tool - delegate via tool calls
- **State Sharing**: Shared message history + dependencies
- **Classification**: **Hierarchical delegation via tool calls**

## Detailed Analysis

### Agent-to-Agent (A2A) Pattern

**Core concept**: An agent can be registered as a tool on another agent.

```python
from pydantic_ai import Agent

# Child agent - specialist
weather_agent = Agent('openai:gpt-4o', name='weather_agent')

@weather_agent.tool
def get_weather(city: str) -> dict:
    return {"temp": 72, "condition": "sunny"}

# Parent agent - orchestrator
main_agent = Agent('openai:gpt-4o', name='main_agent')

# Register child agent as a tool
from pydantic_ai import a2a
a2a.add_agent_as_tool(main_agent, weather_agent, description="Get weather information")

# Now main_agent can delegate to weather_agent
result = await main_agent.run("What's the weather in NYC?")
# main_agent calls weather_agent tool -> weather_agent runs -> returns result
```

### Implementation

**add_agent_as_tool function**:
```python
def add_agent_as_tool(
    parent: AbstractAgent[ParentDepsT, Any],
    child: AbstractAgent[ChildDepsT, ChildOutputDataT],
    *,
    description: str | None = None,
    prepare: ToolPrepareFunc[ParentDepsT] | None = None,
) -> None:
    """Add an agent as a tool on another agent."""
```

**Tool wrapper**:
- Child agent's name becomes tool name
- Child agent's description becomes tool description
- Tool arguments: `{"prompt": str}` - the prompt to send to child
- Tool execution: Runs child agent with prompt, returns output

**Dependency mapping**:
```python
async def run_child_agent(
    ctx: RunContext[ParentDepsT],
    prompt: str
) -> ChildOutputDataT:
    # Map parent deps to child deps via user-provided function
    child_deps = deps_mapper(ctx.deps) if deps_mapper else ctx.deps

    # Run child agent
    result = await child.run(prompt, deps=child_deps)
    return result.output
```

### State Sharing

**Message history**:
- Each agent maintains its own message history
- No automatic history sharing
- Parent sees tool call + result, not child's internal messages

**Dependencies**:
- Can share deps if types match
- Or provide `deps_mapper` to transform parent deps → child deps
- Type-safe via generics

**Example with deps mapping**:
```python
@dataclass
class ParentDeps:
    db: Database
    api_key: str

@dataclass
class ChildDeps:
    api_key: str

def map_deps(parent: ParentDeps) -> ChildDeps:
    return ChildDeps(api_key=parent.api_key)

add_agent_as_tool(
    parent,
    child,
    deps_mapper=map_deps
)
```

### Handoff Flow

1. **Parent agent receives prompt**
2. **Parent decides to delegate** (via model selecting child tool)
3. **Child agent tool called**:
   - Maps dependencies
   - Runs child agent with delegated prompt
   - Returns child output
4. **Parent receives tool result**
5. **Parent can** continue reasoning or return result

**Example**:
```
User: "Check the weather in SF and recommend an activity"

main_agent thinks: "I need weather info first"
main_agent calls: weather_agent(prompt="weather in SF")
weather_agent runs: "72F, sunny"
main_agent receives: {"temp": 72, "condition": "sunny"}
main_agent thinks: "Nice weather, recommend outdoor activity"
main_agent returns: "It's sunny and 72F - perfect for a hike!"
```

### No Built-in Orchestration Patterns

**Observations**:
- No supervisor/worker pattern
- No round-robin or voting
- No automatic routing
- No shared working memory
- No agent communication protocol

**Trade-off**: Simplicity vs. features
- Users implement custom patterns via tools
- A2A is a building block, not a full framework

### Parallel Agent Execution

**Not directly supported**, but can be built:
```python
import asyncio

@main_agent.tool
async def consult_experts(ctx: RunContext, question: str) -> list[str]:
    # Run multiple agents in parallel
    results = await asyncio.gather(
        weather_agent.run(question, deps=ctx.deps),
        sports_agent.run(question, deps=ctx.deps),
        news_agent.run(question, deps=ctx.deps),
    )
    return [r.output for r in results]
```

### Integration with Fast-A2A

**Optional integration** with Fast-A2A library:
```python
# Fast-A2A provides more sophisticated multi-agent patterns
# pydantic-ai agents can be wrapped for Fast-A2A compatibility
```

**Note**: Not deeply integrated - interop layer only.

## Code References

- `pydantic_ai_slim/pydantic_ai/_a2a.py` - Agent-to-agent implementation
- `pydantic_ai_slim/pydantic_ai/agent/abstract.py` - AbstractAgent interface

## Implications for New Framework

1. **Adopt**: Agent-as-tool pattern
   - Simple, composable
   - Natural delegation via tool calls
   - Type-safe with generics

2. **Consider**: Built-in orchestration patterns
   - pydantic-ai is too minimal
   - Add supervisor, router, voting patterns
   - Make them optional, not mandatory

3. **Consider**: Shared working memory
   - Enable agents to share context beyond tool results
   - Useful for collaborative problem-solving
   - Trade-off: Complexity vs. capability

4. **Adopt**: Dependency mapping for handoffs
   - Clean way to control what child sees
   - Prevents leaking sensitive parent deps
   - Type-safe transformation

5. **Consider**: Agent communication protocol
   - Structured messages between agents
   - Beyond just prompt strings
   - Enables richer interactions

## Anti-Patterns Observed

1. **Too minimal**: No built-in orchestration
   - Users must build everything from scratch
   - Common patterns (supervisor, router) should be provided
   - **Recommendation**: Add built-in patterns library

2. **No history sharing**: Child agent's internal reasoning hidden
   - Parent only sees tool call result
   - Limits debugging and observability
   - **Recommendation**: Optional history bubbling

3. **Good pattern**: Type-safe delegation
   - Generic types ensure correct deps mapping
   - Compile-time safety for handoffs
   - Clean API

## Notable Patterns Worth Adopting

1. **Agent registration via add_agent_as_tool**:
   - Declarative multi-agent setup
   - No special coordinator class
   - Agents are just tools

2. **Dependency isolation with mapping**:
   - Child doesn't automatically see all parent deps
   - Explicit mapping required
   - Good security practice

3. **Prompt-based delegation**:
   - Simple API: `agent(prompt="...")`
   - No complex message types needed
   - Easy to understand
