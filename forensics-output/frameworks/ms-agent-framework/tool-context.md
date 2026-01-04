# Tool Interface Context: ms-agent-framework

## Quick Facts

- **Repository**: microsoft/agent-framework
- **Primary Languages**: C#/.NET and Python (dual-language framework)
- **Architecture Style**: Modular, protocol-based with graph-based workflow orchestration
- **Version Analyzed**: Python packages (core implementation)
- **Key Innovation**: Graph-based workflows with streaming, checkpointing, and time-travel capabilities

### Tool Interface Overview
- **Schema Generation**:
  - `AIFunction` wrapper with automatic schema extraction
  - `@ai_function` decorator for function registration
  - Pydantic `create_model` for dynamic tool schemas
  - MCP (Model Context Protocol) integration for external tool servers
- **Ergonomics**:
  - Automatic function signature parsing
  - Type hints become tool schemas
  - Docstrings become tool descriptions
  - `ToolProtocol` for custom tool implementations
- **Error Feedback**: Function results included in chat history for self-correction

### Error Handling Mentions
  - **Cons**: Less automatic validation than Pydantic-heavy approaches
  - Protocol-based validation: `isinstance(custom_agent, AgentProtocol)` works
#### Error Handling
- **Pattern**: Exception-based with custom exception hierarchy
- **Key Exceptions**:

## Tool-Relevant Files

Priority files for tool interface analysis:

- `python/packages/ag-ui/agent_framework_ag_ui/_orchestration/_tooling.py`
- `python/packages/ag-ui/agent_framework_ag_ui_examples/server/api/backend_tool_rendering.py`
- `python/packages/ag-ui/tests/test_backend_tool_rendering.py`
- `python/packages/ag-ui/tests/test_tooling.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/__init__.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_app.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_callbacks.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_constants.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_durable_agent_state.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_entities.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_errors.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_models.py`
- `python/packages/azurefunctions/agent_framework_azurefunctions/_orchestration.py`
- `python/packages/azurefunctions/tests/integration_tests/__init__.py`
- `python/packages/azurefunctions/tests/integration_tests/conftest.py`
- `python/packages/azurefunctions/tests/integration_tests/test_01_single_agent.py`
- `python/packages/azurefunctions/tests/integration_tests/test_02_multi_agent.py`
- `python/packages/azurefunctions/tests/integration_tests/test_03_callbacks.py`
- `python/packages/azurefunctions/tests/integration_tests/test_04_single_agent_orchestration_chaining.py`
- `python/packages/azurefunctions/tests/integration_tests/test_05_multi_agent_orchestration_concurrency.py`
- `python/packages/core/agent_framework/_pydantic.py`
- `python/packages/core/agent_framework/_workflows/_agent_executor.py`
- `python/packages/core/agent_framework/_workflows/_edge_runner.py`
- `python/packages/core/agent_framework/_workflows/_executor.py`
- `python/packages/core/agent_framework/_workflows/_runner.py`
- `python/packages/core/agent_framework/_workflows/_runner_context.py`
- `python/packages/core/agent_framework/_workflows/_validation.py`
- `python/packages/core/agent_framework/_workflows/_workflow_executor.py`
- `python/packages/core/agent_framework/exceptions.py`
- `python/packages/core/agent_framework/openai/_exceptions.py`
- `python/packages/core/tests/workflow/test_agent_executor.py`
- `python/packages/core/tests/workflow/test_checkpoint_validation.py`
- `python/packages/core/tests/workflow/test_executor.py`
- `python/packages/core/tests/workflow/test_runner.py`
- `python/packages/core/tests/workflow/test_validation.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support