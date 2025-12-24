# Data Substrate Analysis: AWS Strands

## Summary
- **Key Finding 1**: Hybrid typing strategy with TypedDict for API boundaries and dataclasses for internal state
- **Key Finding 2**: Explicit serialization with base64 encoding for bytes values
- **Classification**: Structural typing with validation at boundaries

## Detailed Analysis

### Typing Strategy
- **Primary Approach**: TypedDict (structural typing)
- **Secondary Approach**: Dataclasses for state management
- **Key Files**:
  - `src/strands/types/tools.py` - Tool definitions using TypedDict + Protocol
  - `src/strands/types/content.py` - Message/Content using TypedDict
  - `src/strands/types/session.py` - Session state using @dataclass
- **Nesting Depth**: Medium (2-3 levels typical)
- **Validation**: At API boundaries (Bedrock compatibility)

### Core Primitives

| Type | Location | Purpose | Mutability |
|------|----------|---------|------------|
| Message | types/content.py:L178 | Conversation message | Immutable (TypedDict) |
| ContentBlock | types/content.py:L74 | Message content unit | Immutable (TypedDict) |
| ToolSpec | types/tools.py:L22 | Tool specification | Immutable (TypedDict) |
| ToolUse | types/tools.py:L52 | Tool invocation request | Immutable (TypedDict) |
| ToolResult | types/tools.py:L87 | Tool execution result | Immutable (TypedDict) |
| ToolContext | types/tools.py:L128 | Tool execution context | Mutable (dataclass) |
| SessionMessage | types/session.py:L59 | Persisted message | Mutable (dataclass) |
| SessionAgent | types/session.py:L108 | Persisted agent state | Mutable (dataclass) |
| Session | types/session.py:L192 | Session container | Mutable (dataclass) |
| AgentTool | types/tools.py:L218 | Tool base class | Mutable (ABC) |

### Key Type Patterns

#### 1. TypedDict for API Contracts
All Bedrock API-facing types use TypedDict for structural typing:
- Enables gradual typing without runtime overhead
- Compatible with AWS Bedrock API expectations
- Uses `total=False` for optional fields (e.g., ContentBlock)
- Explicit use of `NotRequired[]` from typing_extensions

#### 2. Dataclass for Internal State
Session management and state use dataclasses:
- `@dataclass` without frozen=True (mutable by default)
- Factory defaults for timestamps: `field(default_factory=lambda: datetime.now(timezone.utc).isoformat())`
- Explicit serialization methods: `to_dict()` / `from_dict()`

#### 3. Protocol for Interfaces
Tool functions defined as Protocol (structural):
```python
class ToolFunc(Protocol):
    __name__: str
    def __call__(...) -> Union[ToolResult, Awaitable[ToolResult]]: ...
```

#### 4. ABC for Extension Points
AgentTool uses ABC for class-based tools:
- Abstract properties: `tool_name`, `tool_spec`, `tool_type`
- Abstract method: `stream()`
- Concrete lifecycle management: `mark_dynamic()`, `is_dynamic`

### Mutation Analysis
- **Pattern**: Mixed (immutable TypedDicts for transport, mutable dataclasses for state)
- **Risk Areas**:
  - SessionAgent._internal_state (dict mutation)
  - SessionMessage.redact_message (optional mutation)
  - ToolContext (mutable dataclass passed to tools)
- **Concurrency Safe**: Partial (TypedDicts yes, dataclasses require external synchronization)

### Serialization

#### Method
Custom explicit serialization via `to_dict()` / `from_dict()` pattern

#### Key Implementation (session.py:L28-L56)
```python
def encode_bytes_values(obj: Any) -> Any:
    """Recursively encode any bytes values in an object to base64."""
    if isinstance(obj, bytes):
        return {"__bytes_encoded__": True, "data": base64.b64encode(obj).decode()}
    # ... recursive handling for dict/list

def decode_bytes_values(obj: Any) -> Any:
    """Recursively decode base64-encoded bytes values."""
    # ... symmetric decoding
```

#### Characteristics
- **Implicit/Explicit**: Explicit (manual calls to to_dict/from_dict)
- **Nested Objects**: Recursive traversal with base64 encoding for bytes
- **Round-trip Tested**: Likely (encode/decode are symmetric)
- **Special Handling**:
  - Bytes values converted to base64 for JSON compatibility
  - Timestamp fields auto-generated with ISO format
  - `inspect.signature()` used for forward-compatible deserialization (ignores unknown keys)

### Type Strategy Trade-offs

#### Strengths
1. **Bedrock API Alignment**: TypedDict matches AWS API structure exactly
2. **Gradual Typing**: Can add types incrementally without runtime cost
3. **Flexible State**: Dataclasses allow mutation for session persistence
4. **Forward Compatibility**: `from_dict()` methods ignore unknown keys

#### Weaknesses
1. **Inconsistent Mutability**: TypedDict (immutable) vs dataclass (mutable) creates confusion
2. **No Runtime Validation**: TypedDict doesn't validate at runtime (unlike Pydantic)
3. **Manual Serialization**: Custom encode/decode logic instead of built-in
4. **State Mutation Risks**: Mutable dataclasses require careful handling in async contexts

## Code References
- `src/strands/types/tools.py:22-37` - ToolSpec TypedDict with NotRequired fields
- `src/strands/types/tools.py:199-216` - ToolFunc Protocol for structural typing
- `src/strands/types/tools.py:218-307` - AgentTool ABC for class-based extension
- `src/strands/types/content.py:74-100` - ContentBlock with total=False pattern
- `src/strands/types/session.py:59-105` - SessionMessage dataclass with explicit serialization
- `src/strands/types/session.py:28-56` - Base64 encoding strategy for bytes

## Implications for New Framework
- **Adopt**: TypedDict for API boundaries (lightweight, structural typing)
- **Adopt**: Explicit from_dict methods with signature introspection for forward compatibility
- **Reconsider**: Use Pydantic for state that needs validation (stricter than dataclass)
- **Reconsider**: Make state objects frozen by default (`@dataclass(frozen=True)`)
- **Adopt**: Base64 encoding strategy for bytes in JSON serialization

## Anti-Patterns Observed
- **Mutable Dataclasses**: SessionAgent and SessionMessage are mutable by default, risking state corruption in async contexts
- **Mixed Typing Paradigms**: TypedDict + dataclass + Protocol + ABC creates cognitive overhead
- **Manual Serialization**: Reinventing JSON encoding instead of using Pydantic or similar
