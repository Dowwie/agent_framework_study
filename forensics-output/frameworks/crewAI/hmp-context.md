# HMP Context: crewAI

## Quick Facts

- **Repository**: https://github.com/crewAIInc/crewAI
- **Primary Language**: Python
- **Architecture Style**: Monolithic with modular subsystems (agents, tasks, memory, tools)
- **Design Philosophy**: Code-first with optional configuration overlays
- **Target Use Case**: Multi-agent workflow orchestration for business automation

### Async/Streaming Model
- **Approach**: Synchronous core with `asyncio.to_thread()` wrappers for async support
- **Patterns**:
  - `kickoff()` - sync primary entry point
  - `kickoff_async()` - wraps sync in thread
  - `akickoff()` - native async implementation (added later)
- **Strengths**: Backwards compatibility for sync-first users
- **Weaknesses**:
  - Thread wrapping defeats async benefits (context managers, cancellation)

### Schema Generation (from tool-interface-analysis)
**Approach**: **Reflection + Manual**

**Automatic (Decorator)**:
- Uses `inspect.signature()` to extract parameters (base_tool.py:L6)
- Type hints → Pydantic field types
- Default values preserved

### Streaming Mentions
**Why**: Flexibility for diverse consumers (humans, APIs, downstream agents)

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `lib/crewai-tools/src/crewai_tools/adapters/__init__.py`
- `lib/crewai-tools/src/crewai_tools/adapters/crewai_rag_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/enterprise_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/lancedb_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/mcp_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/rag_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/tool_collection.py`
- `lib/crewai-tools/src/crewai_tools/adapters/zapier_adapter.py`
- `lib/crewai-tools/tests/adapters/mcp_adapter_test.py`
- `lib/crewai/src/crewai/agents/agent_adapters/__init__.py`
- `lib/crewai/src/crewai/agents/agent_adapters/base_agent_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/base_converter_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/base_tool_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/langgraph/__init__.py`
- `lib/crewai/src/crewai/agents/agent_adapters/langgraph/langgraph_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/langgraph/langgraph_tool_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/langgraph/protocols.py`
- `lib/crewai/src/crewai/agents/agent_adapters/langgraph/structured_output_converter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/openai_agents/__init__.py`
- `lib/crewai/src/crewai/agents/agent_adapters/openai_agents/openai_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/openai_agents/openai_agent_tool_adapter.py`
- `lib/crewai/src/crewai/agents/agent_adapters/openai_agents/protocols.py`
- `lib/crewai/src/crewai/agents/agent_adapters/openai_agents/structured_output_converter.py`
- `lib/crewai/src/crewai/cli/authentication/providers/__init__.py`
- `lib/crewai/src/crewai/cli/authentication/providers/auth0.py`
- `lib/crewai/src/crewai/cli/authentication/providers/base_provider.py`
- `lib/crewai/src/crewai/cli/authentication/providers/entra_id.py`
- `lib/crewai/src/crewai/cli/authentication/providers/okta.py`
- `lib/crewai/src/crewai/cli/authentication/providers/workos.py`
- `lib/crewai/src/crewai/cli/crew_chat.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy