# Tool Interface Context: google-adk

## Quick Facts

- **Repository**: https://github.com/google/adk-python
- **Primary Language**: Python
- **Architecture Style**: Modular with service-oriented design
- **Framework Philosophy**: Code-first, production-ready Google agent framework
- **Primary Use Case**: Enterprise-grade agentic applications optimized for Gemini

### Tool Interface Overview
**Type-introspection with automatic schema generation**

Ergonomics:
- **Primary Method**: @function_tool decorator (automatic schema from type hints + docstrings)
- **Schema Format**: Gemini FunctionDeclaration (OpenAPI-like JSON Schema)
- **Auto-conversion**: Python types → JSON Schema, Pydantic models → nested objects
- **Integration**: LangChain/CrewAI adapters, OpenAPI spec auto-generation, MCP protocol support

First-class features:
- **HITL (Human-in-the-Loop)**: ToolConfirmation for approval workflows
- **EUC (End-User Credentials)**: RequestAuth pattern for OAuth/API keys
- **Long-running tools**: is_long_running flag for async operations

### Error Handling Mentions
**Pydantic V2 BaseModel with strict validation**
- **Pros**: Type safety at boundaries, automatic validation, excellent IDE support, serialization included
#### Error Handling
**Fail-fast with structured error responses**
- **Strength**: Strong validation (Pydantic at boundaries), sandboxed code execution, error-in-response pattern (LlmResponse carries errors)

## Tool-Relevant Files

Priority files for tool interface analysis:

- `contributing/samples/adk_answering_agent/tools.py`
- `contributing/samples/adk_documentation/tools.py`
- `contributing/samples/authn-adk-all-in-one/adk_agents/agent_openapi_tools/__init__.py`
- `contributing/samples/authn-adk-all-in-one/adk_agents/agent_openapi_tools/agent.py`
- `contributing/samples/built_in_multi_tools/__init__.py`
- `contributing/samples/built_in_multi_tools/agent.py`
- `contributing/samples/core_callback_config/tools.py`
- `contributing/samples/crewai_tool_kwargs/__init__.py`
- `contributing/samples/crewai_tool_kwargs/agent.py`
- `contributing/samples/crewai_tool_kwargs/main.py`
- `contributing/samples/fields_output_schema/__init__.py`
- `contributing/samples/fields_output_schema/agent.py`
- `contributing/samples/gepa/voter_agent/tools.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/__init__.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/agent.py`
- `contributing/samples/hello_world_litellm_add_function_to_prompt/main.py`
- `contributing/samples/human_tool_confirmation/__init__.py`
- `contributing/samples/human_tool_confirmation/agent.py`
- `contributing/samples/jira_agent/tools.py`
- `contributing/samples/langchain_structured_tool_agent/__init__.py`
- `contributing/samples/api_registry_agent/__init__.py`
- `contributing/samples/api_registry_agent/agent.py`
- `contributing/samples/interactions_api/__init__.py`
- `contributing/samples/interactions_api/agent.py`
- `contributing/samples/interactions_api/main.py`
- `contributing/samples/pydantic_argument/__init__.py`
- `contributing/samples/pydantic_argument/agent.py`
- `contributing/samples/pydantic_argument/main.py`
- `contributing/samples/runner_debug_example/__init__.py`
- `contributing/samples/runner_debug_example/agent.py`
- `contributing/samples/runner_debug_example/main.py`
- `src/google/adk/a2a/executor/__init__.py`
- `src/google/adk/a2a/executor/a2a_agent_executor.py`
- `src/google/adk/a2a/executor/task_result_aggregator.py`
- `src/google/adk/apps/compaction.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support