# Tool Interface Context: crewAI

## Quick Facts

- **Repository**: https://github.com/crewAIInc/crewAI
- **Primary Language**: Python
- **Architecture Style**: Monolithic with modular subsystems (agents, tasks, memory, tools)
- **Design Philosophy**: Code-first with optional configuration overlays
- **Target Use Case**: Multi-agent workflow orchestration for business automation

### Tool Interface Overview
- **Schema Generation**: Automatic via `inspect.signature()` for decorated functions
- **Definition Methods**:
  - `@tool` decorator - function → tool with auto-schema
  - `BaseTool` inheritance - manual schema specification
- **Error Feedback**: Tool errors converted to observations, fed back to LLM
- **Features**:
  - Usage limits per tool (prevent cost overruns)
  - Result-as-answer flag (early termination)
  - Declarative environment variables
  - Cache control per tool
  - MCP integration for dynamic tool discovery
- **Strengths**:

### Error Handling Mentions
  - Strong type validation at runtime
- **Trade-offs**: Runtime overhead for validation vs. developer experience and safety
- **Pattern**: Abstract base classes define contracts, Pydantic provides validation
#### Error Handling: Catch-and-Reraise with Event Emission
- **Pattern**: Catch exceptions, log/emit events, reraise

## Tool-Relevant Files

Priority files for tool interface analysis:

- `lib/crewai-tools/src/crewai_tools/__init__.py`
- `lib/crewai-tools/src/crewai_tools/adapters/__init__.py`
- `lib/crewai-tools/src/crewai_tools/adapters/crewai_rag_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/enterprise_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/lancedb_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/mcp_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/rag_adapter.py`
- `lib/crewai-tools/src/crewai_tools/adapters/tool_collection.py`
- `lib/crewai-tools/src/crewai_tools/adapters/zapier_adapter.py`
- `lib/crewai-tools/src/crewai_tools/aws/__init__.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/__init__.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/agents/__init__.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/agents/invoke_agent_tool.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/browser/__init__.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/browser/browser_session_manager.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/browser/browser_toolkit.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/browser/utils.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/code_interpreter/__init__.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/code_interpreter/code_interpreter_toolkit.py`
- `lib/crewai-tools/src/crewai_tools/aws/bedrock/exceptions.py`
- `lib/crewai/src/crewai/a2a/extensions/registry.py`
- `lib/crewai/src/crewai/agents/agent_builder/base_agent_executor_mixin.py`
- `lib/crewai/src/crewai/agents/crew_agent_executor.py`
- `lib/crewai/src/crewai/experimental/evaluation/experiment/runner.py`
- `lib/crewai/src/crewai/rag/core/base_embeddings_callable.py`
- `lib/crewai/src/crewai/rag/core/exceptions.py`
- `lib/crewai/src/crewai/rag/embeddings/providers/custom/embedding_callable.py`
- `lib/crewai/src/crewai/rag/embeddings/providers/ibm/embedding_callable.py`
- `lib/crewai/src/crewai/rag/embeddings/providers/voyageai/embedding_callable.py`
- `lib/crewai/src/crewai/utilities/errors.py`
- `lib/crewai/src/crewai/utilities/exceptions/__init__.py`
- `lib/crewai/src/crewai/utilities/exceptions/context_window_exceeding_exception.py`
- `lib/crewai/tests/agents/test_async_agent_executor.py`
- `lib/crewai/tests/experimental/evaluation/test_experiment_runner.py`
- `lib/crewai/tests/rag/test_error_handling.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support