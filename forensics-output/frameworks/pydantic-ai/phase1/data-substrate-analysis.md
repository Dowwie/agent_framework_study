# Data Substrate Analysis: pydantic-ai

## Summary

- **Typing Strategy**: Pydantic V2 + Dataclasses with comprehensive generic types
- **Immutability**: Mixed approach - frozen dataclasses for configuration, mutable for state tracking
- **Serialization**: Pydantic JSON schema generation with OpenTelemetry integration
- **Classification**: **Strongly-typed with runtime validation**

## Detailed Analysis

### Type System Architecture

**Core Pattern**: Generic dataclasses with Pydantic validation

The framework uses a sophisticated combination of:
1. **`@dataclass`** from Python's standard library for structure
2. **Pydantic V2** for validation and JSON schema generation
3. **Generic types** extensively throughout (`Generic[AgentDepsT, OutputDataT]`)

Key type parameters:
- `AgentDepsT`: Type variable for dependency injection
- `OutputDataT`: Covariant type variable for output data (defaults to `str`)

**Example from `result.py`:**
```python
@dataclass(kw_only=True)
class AgentStream(Generic[AgentDepsT, OutputDataT]):
    _raw_stream_response: models.StreamedResponse
    _output_schema: OutputSchema[OutputDataT]
    _model_request_parameters: models.ModelRequestParameters
    _output_validators: list[OutputValidator[AgentDepsT, OutputDataT]]
    _run_ctx: RunContext[AgentDepsT]
    _usage_limits: UsageLimits | None
    _tool_manager: ToolManager[AgentDepsT]
```

### Immutability Strategy

**Mixed approach based on usage:**

1. **Configuration data**: Uses frozen dataclasses or Pydantic models
2. **Runtime state**: Mutable dataclasses for efficiency (e.g., `AgentStream`)
3. **Messages**: Uses `dataclass(kw_only=True)` with `replace()` for updates

**Pattern**: Leverage `dataclasses.replace()` for pseudo-immutability:
```python
# From result.py line 60
self._initial_run_ctx_usage = deepcopy(self._run_ctx.usage)
```

### Serialization & Validation

**Pydantic Integration:**
- Uses `TypeAdapter` for runtime validation
- Generates JSON schemas via `TypeAdapter(return_type).json_schema(mode='serialization')`
- Custom schema transformers (`InlineDefsJsonSchemaTransformer`)

**OpenTelemetry Integration:**
- Custom message types integrate with OpenTelemetry LogRecord
- Provider-agnostic message format with rich content types

**Media Type System:**
```python
# From messages.py
AudioMediaType: TypeAlias = Literal['audio/wav', 'audio/mpeg', 'audio/ogg', ...]
ImageMediaType: TypeAlias = Literal['image/jpeg', 'image/png', 'image/gif', 'image/webp']
DocumentMediaType: TypeAlias = Literal['application/pdf', 'text/plain', ...]
VideoMediaType: TypeAlias = Literal['video/x-matroska', 'video/quicktime', ...]
```

### Type Safety Features

1. **Covariant/Contravariant types** for proper variance
   - `OutputDataT = TypeVar('OutputDataT', default=str, covariant=True)`
   - Enables type-safe subtyping

2. **Runtime type checking** via Pydantic
   - Validation during streaming: `yield await self.validate_response_output(response, allow_partial=True)`
   - Handles ValidationError gracefully during streaming

3. **Union types for output modes**:
   ```python
   OutputMode = Literal['text', 'tool', 'native', 'prompted', 'tool_or_text', 'image', 'auto']
   StructuredOutputMode = Literal['tool', 'native', 'prompted']
   ```

### Mutation Patterns

**State Management:**
- Graph-based execution uses mutable state (`GraphAgentState`)
- Deep copying for state snapshots: `self._initial_run_ctx_usage = deepcopy(self._run_ctx.usage)`
- Usage tracking accumulates mutations

**Message Flow:**
- Immutable message parts (ABC with abstractmethods)
- Message collections managed via sequences

## Code References

- `pydantic_ai_slim/pydantic_ai/messages.py` - Core message types with media support
- `pydantic_ai_slim/pydantic_ai/result.py:46` - AgentStream generic dataclass
- `pydantic_ai_slim/pydantic_ai/output.py:38` - OutputDataT covariant type variable
- `pydantic_ai_slim/pydantic_ai/agent/abstract.py:78` - AbstractAgent generic base
- `pydantic_ai_slim/pydantic_ai/run.py:27` - AgentRun with graph integration

## Implications for New Framework

1. **Adopt**: Pydantic V2 for validation + dataclasses for structure
   - Best of both worlds: clean syntax + runtime safety
   - Avoid over-engineering with pure Pydantic models for everything

2. **Adopt**: Generic type parameters for dependency injection
   - Enables compile-time type safety for tools and outputs
   - Pattern: `Agent[DepsType, OutputType]`

3. **Consider**: Mixed mutability strategy
   - Frozen for config, mutable for runtime state
   - Use `deepcopy` strategically for snapshots

4. **Adopt**: TypeAlias for domain-specific literal types
   - Better than string constants
   - Provides IDE autocomplete and type checking

## Anti-Patterns Observed

1. **Minor**: Inconsistent use of kw_only across dataclasses
   - Some use `@dataclass(kw_only=True)`, others don't
   - Recommendation: Always use kw_only for clarity

2. **None observed**: Overall excellent type hygiene with comprehensive generics
