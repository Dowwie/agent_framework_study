# Data Substrate Analysis: Google ADK

## Summary
- **Key Finding 1**: Heavy reliance on Pydantic V2 BaseModel for all data structures with strict validation
- **Key Finding 2**: Immutability enforced selectively through Pydantic's ConfigDict (frozen models for state)
- **Classification**: Pydantic-first with Google GenAI types integration

## Detailed Analysis

### Typing Strategy
- **Primary Approach**: Pydantic V2 BaseModel
- **Key Files**:
  - `src/google/adk/models/llm_request.py`
  - `src/google/adk/models/llm_response.py`
  - `src/google/adk/agents/base_agent.py`
  - `src/google/adk/tools/base_tool.py`
- **Nesting Depth**: Medium (2-3 levels typical)
- **Validation**: At all boundaries - extensive use of Pydantic validators

### Core Primitives

| Type | Location | Purpose | Mutability |
|------|----------|---------|------------|
| LlmRequest | models/llm_request.py:49 | Request wrapper for LLM calls | Mutable |
| LlmResponse | models/llm_response.py:28 | Response wrapper from LLM | Immutable (extra='forbid') |
| BaseAgent | agents/base_agent.py:85 | Agent base class | Mutable |
| BaseAgentState | agents/base_agent.py:74 | Agent state container | Immutable (extra='forbid') |
| BaseTool | tools/base_tool.py:47 | Tool abstraction | Mutable (not Pydantic) |
| Content | google.genai.types | Message content | External (Google GenAI) |

### Mutation Analysis
- **Pattern**: Mixed - in-place for requests, copy-on-write for state
- **Risk Areas**:
  - LlmRequest allows field mutation via append_tools(), append_instructions()
  - Agent sub_agents list is mutable (default_factory=list)
  - BaseAgentState enforces immutability (extra='forbid')
- **Concurrency Safe**: Partial - state objects immutable, but agent structure is mutable

### Serialization
- **Method**: Pydantic model_dump() / model_dump_json()
- **Implicit/Explicit**: Implicit via Pydantic
- **Round-trip Tested**: Yes - extensive use in session persistence (database_session_service.py)
- **Integration**: Deep integration with Google GenAI types library for Content/Part serialization

## Implications for New Framework

### Positive Patterns
- **Strict validation boundaries**: Using Pydantic with extra='forbid' catches schema evolution bugs early
- **Type safety**: Full typing with ConfigDict(arbitrary_types_allowed=True) allows mixing Pydantic with Google types
- **Alias support**: LlmResponse uses alias_generators for camelCase/snake_case conversion (API boundary pattern)

### Considerations
- **Mixed mutability**: LlmRequest is mutable for builder pattern, but could cause confusion
- **Heavy dependency**: Tight coupling to google.genai.types creates vendor lock-in
- **No TypedDict**: Framework avoids lightweight TypedDict, always uses full Pydantic (performance cost for simple data)

## Code References
- `models/llm_request.py:49` - Mutable request builder with append methods
- `models/llm_response.py:28` - Immutable response with strict schema (extra='forbid')
- `agents/base_agent.py:74` - BaseAgentState immutability pattern
- `agents/base_agent.py:85` - BaseAgent uses arbitrary_types_allowed for flexibility

## Anti-Patterns Observed
- **Inconsistent immutability**: Some Pydantic models frozen, others not - no clear policy
- **In-place list modification**: BaseAgent.sub_agents uses default_factory=list (shared state risk)
- **Heavy tool wrapper**: BaseTool is not Pydantic (ABC only), inconsistent with rest of framework
