# Multi-Agent Analysis: Agno

## Summary
- **Key Finding 1**: Hierarchical team model - Team is itself an agent that coordinates member agents
- **Key Finding 2**: Multiple delegation modes - leader decides subset, all members, or respond directly
- **Key Finding 3**: Team member interaction sharing - members can see each other's work
- **Classification**: Leader-worker pattern with optional collaboration

## Coordination Model
- **Pattern**: Leader-follower with delegation
- **Communication**: Leader receives task, delegates to members, aggregates responses
- **State Sharing**: Optional via session_state and member interaction sharing
- **Hierarchy**: Teams can contain agents or other teams (recursive composition)

## Task Distribution Strategy
- **Mode 1** (default): Leader determines which members to delegate to
- **Mode 2** (`delegate_to_all_members=True`): Broadcast to all members
- **Mode 3** (`respond_directly=True`): Members work independently, no leader processing

## Detailed Analysis

### Team Structure

**Evidence** (`team/team.py:192-227`):
```python
@dataclass(init=False)
class Team:
    """A class representing a team of agents."""

    members: List[Union[Agent, "Team"]]  # Recursive: teams can contain teams
    model: Optional[Model] = None

    # --- Team execution settings ---
    # If True, the team leader won't process responses from the members
    respond_directly: bool = False
    # If True, the team leader will delegate the task to all members
    delegate_to_all_members: bool = False
    # Set to false to send run input directly to member agents
    determine_input_for_members: bool = True
```

**Recursive Composition**: `Union[Agent, "Team"]` allows nested teams
- Teams can delegate to sub-teams
- Creates organizational hierarchy
- Mirrors real organizational structures

### Delegation Modes

**Mode 1: Selective Delegation (Default)**
- Leader model decides which members to involve
- Based on member descriptions/roles
- Most flexible, highest coordination overhead

**Mode 2: Broadcast** (`delegate_to_all_members=True`)
- All members receive the task
- Parallel execution
- Leader aggregates all responses
- Good for diverse perspectives (e.g., code review team)

**Mode 3: Direct Response** (`respond_directly=True`)
- Members respond directly without leader processing
- Minimal coordination
- Fast but no synthesis

**Evidence** (`team/team.py:220-226`):
```python
# If True, the team leader won't process responses from members
# Should not be used in combination with delegate_to_all_members
respond_directly: bool = False
# If True, delegate task to all members
delegate_to_all_members: bool = False
# Set to false to send run input directly to members
determine_input_for_members: bool = True
```

### Member Interaction Sharing

**Evidence** (`team/team.py:246-251`):
```python
# Add team-level history to members (not agent-level)
add_team_history_to_members: bool = False
# Number of historical runs to include
num_team_history_runs: int = 3
# If True, send all member interactions (request/response) during current run
share_member_interactions: bool = False
```

**Collaboration Pattern**: If `share_member_interactions=True`:
- Member A completes task
- Member B sees Member A's work when starting
- Enables sequential collaboration
- Members build on each other's output

**Without Sharing**: Members work in parallel without seeing each other's results

### Team as Agent

**Pattern**: Team inherits from same interface as Agent
- Has own model for coordination
- Can be a member of another team
- Can be a step in a workflow

**Evidence** (`team/team.py:198-201, 208-217`):
```python
members: List[Union[Agent, "Team"]]

# If this team is part of a team itself
role: Optional[str] = None
parent_team_id: Optional[str] = None

# If this Team is part of a workflow
workflow_id: Optional[str] = None
```

**Composability**: Teams can be nested in:
- Other teams (hierarchy)
- Workflows (orchestration)
- Direct API calls (standalone)

### Session State for Coordination

**Evidence** (`team/team.py:234-244`):
```python
# Session state (stored in database to persist across runs)
session_state: Optional[Dict[str, Any]] = None
# Set to True to add the session_state to the context
add_session_state_to_context: bool = False
# Set to True to give the team tools to update the session_state dynamically
enable_agentic_state: bool = False
```

**Coordination Mechanism**: Team-level session state
- Shared state across all members
- Persisted between runs
- Can be updated by team leader or members (if `enable_agentic_state=True`)

**Use Cases**:
- Track work division ("Member A handled X, Member B should do Y")
- Store partial results
- Coordinate access to shared resources

### Input Determination

**Evidence** (`team/team.py:225-226`):
```python
# Set to false if you want to send the run input directly to the member agents
determine_input_for_members: bool = True
```

**Two Modes**:
1. **Leader determines input** (default): Leader model rewrites task for each member
   - "Analyze codebase" → "Review Python files" (to Python expert)
   - "Analyze codebase" → "Review tests" (to QA expert)

2. **Direct input**: Same task sent to all members
   - Faster (no LLM call to reformulate)
   - Less flexible

### Team History

**Evidence** (`team/team.py:246-249`):
```python
# Send team-level history to members, not agent-level history
add_team_history_to_members: bool = False
# Number of historical runs to include
num_team_history_runs: int = 3
```

**Distinction**:
- **Agent-level history**: Individual agent's past conversations
- **Team-level history**: Team's past runs (visible to all members)

If enabled, members see team's previous work for context.

### Member Tools in Context

**Evidence** (`team/team.py:281-282`):
```python
# If True, add the tools available to team members to the context
add_member_tools_to_context: bool = False
```

**Coordination Aid**: Leader model can see what tools members have
- Helps decide which member to delegate to
- "Member A has web search, delegate research to A"

### Chat History Access

**Evidence** (`team/team.py:258-259`):
```python
# If True, adds a tool to allow the team to read the chat history
read_chat_history: bool = False
```

**Team Introspection**: Team leader can query past conversations
- Review previous member interactions
- Check what was already done
- Avoid redundant work

### Team Run Context Utilities

**Evidence** (`team/team.py:179-188` imports):
```python
from agno.utils.team import (
    add_interaction_to_team_run_context,
    format_member_agent_task,
    get_member_id,
    get_team_member_interactions_str,
    get_team_run_context_audio,
    get_team_run_context_images,
    get_team_run_context_videos,
    get_team_run_context_files,
)
```

**Run Context Tracking**: Utilities for managing team execution
- Track which members did what
- Aggregate media artifacts from members
- Format member interactions for display

### Remote Teams

**Evidence** (`team/__init__.py:18`):
```python
from agno.team.remote import RemoteTeam
```

**Distributed Execution**: Teams can run remotely
- Members in different processes/machines
- RPC-style coordination
- Scales beyond single machine

## Implications for New Framework

1. **Hierarchical teams are powerful** - Recursive Team composition mirrors real organizations
2. **Multiple delegation modes needed** - One size doesn't fit all; provide broadcast, selective, direct
3. **Member interaction sharing is key** - Sequential collaboration requires visibility
4. **Team as Agent abstraction** - Unifies single and multi-agent under same interface
5. **Explicit input determination** - Leader reformulating tasks is useful but expensive
6. **Shared state for coordination** - Session state enables stateful collaboration
7. **Remote teams for scale** - Distribution is essential for production

## Anti-Patterns Observed

1. **Too many configuration flags** - 20+ team settings duplicates Agent's complexity
2. **Boolean mode switches** - `respond_directly`, `delegate_to_all_members`, `determine_input_for_members` create 8 combinations; use explicit mode enum
3. **No task queue** - All delegation is synchronous; no work queue for load balancing
4. **No failure handling** - What happens if member fails? No retry or fallback specified
5. **No parallel execution control** - Can't limit concurrent members (resource constraints)
6. **No member selection strategy** - Leader decides but no configurable strategies (round-robin, load-based, etc.)
7. **State mutation risks** - Shared session_state without locking (same issue as Agent)

## Code References
- `libs/agno/agno/team/__init__.py:18-39` - Team module exports
- `libs/agno/agno/team/team.py:192-199` - Team dataclass with recursive member composition
- `libs/agno/agno/team/team.py:220-226` - Delegation mode configuration
- `libs/agno/agno/team/team.py:246-251` - Member interaction sharing and team history
- `libs/agno/agno/team/team.py:234-244` - Session state for coordination
- `libs/agno/agno/team/team.py:281-282` - Member tools in context
- `libs/agno/agno/team/team.py:258-259` - Chat history access
- `libs/agno/agno/team/team.py:179-188` - Team run context utilities
