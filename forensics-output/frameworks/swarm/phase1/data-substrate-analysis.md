# Data Substrate Analysis: Swarm

## Summary
- **Primary Approach**: Pydantic V2 with minimal validation
- **Mutability**: Mixed - deep copy for isolation, mutable list operations in loop
- **Validation**: None at boundaries (relies on OpenAI types)
- **Serialization**: Pydantic model_dump_json() for OpenAI compatibility

## Typing Strategy

**Primary Approach**: Pydantic BaseModel
- **Key Files**: `swarm/types.py`
- **Pydantic Version**: V2 (uses `BaseModel` without V1 compatibility imports)
- **Nesting Depth**: Shallow (max 2 levels)
- **Validation**: Minimal - relies on type hints, no custom validators

### Evidence
```python
# types.py:14-21
class Agent(BaseModel):
    name: str = "Agent"
    model: str = "gpt-4o"
    instructions: Union[str, Callable[[], str]] = "You are a helpful agent."
    functions: List[AgentFunction] = []
    tool_choice: str = None
    parallel_tool_calls: bool = True
```

## Core Primitives

| Type | Location | Purpose | Mutability | Notes |
|------|----------|---------|------------|-------|
| `Agent` | types.py:L14 | Agent configuration | Immutable (Pydantic default) | Allows callable instructions |
| `Response` | types.py:L23 | Run result container | Immutable | Mutable list field `messages` |
| `Result` | types.py:L29 | Tool return value | Immutable | Encapsulates agent handoff |
| `AgentFunction` | types.py:L11 | Tool type alias | N/A | `Callable[[], Union[str, Agent, dict]]` |

### Type Design Observations

**Flexible Function Return Types**:
- `AgentFunction` can return `str`, `Agent`, or `dict`
- Pattern-matched in `core.py:L71-87` using Python 3.10 `match` statement
- Agent return triggers handoff, str/dict becomes tool result

**OpenAI Type Reuse**:
- Imports `ChatCompletionMessage`, `ChatCompletionMessageToolCall` from OpenAI SDK
- No custom wrapper types - direct dependency on vendor types
- Risk: Breaking changes in OpenAI SDK propagate directly

**Default Values as Mutation Risk**:
```python
# types.py:L18 - mutable default (but Pydantic handles this safely)
functions: List[AgentFunction] = []
```
Pydantic creates new instances per model, avoiding shared mutable default issues.

## Mutation Analysis

**Pattern**: Mixed - defensive copying with in-place operations

### Defensive Copying (Safe)
```python
# core.py:L150-151, L253-254
context_variables = copy.deepcopy(context_variables)
history = copy.deepcopy(messages)
```
**Purpose**: Prevent caller's state mutation by isolating input data

### In-Place Mutation (Controlled)
```python
# core.py:L196 - append to history
history.append(message)

# core.py:L218-219 - extend history with tool results
history.extend(partial_response.messages)
context_variables.update(partial_response.context_variables)
```
**Context**: Mutations occur on locally deep-copied state, safe from external side effects

### Context Variables Pattern
```python
# core.py:L41
context_variables = defaultdict(str, context_variables)
```
Converts dict to defaultdict for safe key access, but mutates structure. Original protected by L150 deep copy.

## Serialization

### Method: Pydantic + Manual JSON

**Pydantic Serialization**:
```python
# core.py:L272-273
history.append(
    json.loads(message.model_dump_json())  # Convert OpenAI type to dict
)
```
**Rationale (comment)**: "to avoid OpenAI types (?)" - suggests uncertainty about why needed
**Likely reason**: Ensure history is JSON-serializable dicts, not Pydantic models

**Tool Result Serialization**:
```python
# core.py:L78-79 - agent handoff serialized
return Result(
    value=json.dumps({"assistant": agent.name}),  # Manual JSON
    agent=agent,
)
```

**Schema Generation**:
```python
# util.py:L31-87 - function_to_json()
```
Uses `inspect.signature()` to generate OpenAI function calling schemas from Python functions. Simple type mapping (str→"string", int→"integer", etc.).

### Serialization Characteristics

| Aspect | Approach | Trade-offs |
|--------|----------|------------|
| **Model → JSON** | `model_dump_json()` | Automatic, type-safe |
| **Function schemas** | `inspect.signature()` | Manual mapping, limited type support |
| **Round-trip testing** | Not evident | Unknown reliability |
| **Unknown fields** | Not handled | Would raise Pydantic validation error |

## Implications for New Framework

### Adopt
1. **Deep copy at entry points** - Prevents accidental state mutation across calls
2. **Pydantic for config/results** - Clean typed interface, good DX
3. **Type aliases for complex signatures** - `AgentFunction` is self-documenting

### Avoid
1. **Direct vendor type dependencies** - Wrapping OpenAI types would insulate from SDK changes
2. **Manual JSON serialization** - Comment "(?)" suggests confusion; centralize serialization logic
3. **Minimal validation** - No boundary validation on `messages` structure could cause runtime errors

### Risks Identified
- **No message structure validation**: Assumes messages list is well-formed, could fail with malformed input
- **Defaultdict conversion**: Silent behavior change from dict to defaultdict could surprise users
- **Uncertain serialization**: L272 comment indicates unclear reason for serialization approach

## Concurrency Safety

**Assessment**: Single-threaded safe, async-unsafe

- Deep copy pattern prevents shared state issues
- No locks or async primitives
- Mutable `history` and `context_variables` would cause races if run concurrently without external synchronization

## Code References

- `swarm/types.py:11` - AgentFunction type alias
- `swarm/types.py:14-21` - Agent model
- `swarm/types.py:23-26` - Response model
- `swarm/types.py:29-42` - Result model
- `swarm/core.py:71-87` - Pattern matching on function results
- `swarm/core.py:150-151` - Defensive deep copy
- `swarm/core.py:272-273` - Uncertain serialization
- `swarm/util.py:31-87` - Schema generation from inspection
