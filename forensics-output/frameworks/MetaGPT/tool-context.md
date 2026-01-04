# Tool Interface Context: MetaGPT

## Quick Facts

- Repository: /Users/dgordon/my_projects/agent_framework_study/repos/MetaGPT
- Primary language: Python
- Architecture style: Role-based multi-agent framework with environment orchestration
- Total files: 1,255 (890 Python files)
- Focus: Software development automation through specialized agent roles

### Tool Interface Overview
- **Schema Generation**:
  - `@register_tool` decorator (tool_registry.py:94-118)
  - Reflection-based: `inspect.getsource()` + `inspect.getfile()` (tool_registry.py:99-105)
  - AST parsing for automatic schema extraction: `convert_code_to_tool_schema_ast()` (tool_registry.py:172)
- **Method**:
  - Tools can be functions or classes with methods
  - Supports selective method exposure: `Editor:read,write` syntax (tool_registry.py:140-155)
  - YAML schema generation for validation (tool_registry.py:46-56)
- **Ergonomics**:
  - Excellent: Zero-boilerplate tool registration
  - Flexible: Tag-based categorization for discovery
  - Strong: Validation via ToolSchema Pydantic model

### Error Handling Mentions
#### Typing Strategy: Pydantic V2 with Strict Validation
  - Pros: Strong runtime validation, automatic JSON serialization, excellent DX for type safety
  - Cons: Performance overhead from validation, tightly coupled to Pydantic ecosystem
#### Error Handling: Decorator-Based Exception Swallowing
- **Pattern**: `@handle_exception` decorator throughout codebase

## Tool-Relevant Files

Priority files for tool interface analysis:

- `examples/di/custom_tool.py`
- `examples/di/machine_learning_with_tools.py`
- `examples/di/sd_tool_usage.py`
- `metagpt/exp_pool/schema.py`
- `metagpt/ext/android_assistant/utils/schema.py`
- `metagpt/ext/cr/utils/schema.py`
- `metagpt/ext/werewolf/schema.py`
- `metagpt/rag/schema.py`
- `metagpt/schema.py`
- `metagpt/strategy/tot_schema.py`
- `metagpt/tools/__init__.py`
- `metagpt/tools/azure_tts.py`
- `metagpt/tools/iflytek_tts.py`
- `metagpt/tools/libs/__init__.py`
- `metagpt/tools/libs/browser.py`
- `metagpt/tools/libs/cr.py`
- `metagpt/tools/libs/data_preprocess.py`
- `metagpt/tools/libs/deployer.py`
- `metagpt/tools/libs/editor.py`
- `metagpt/tools/libs/email_login.py`
- `metagpt/actions/__init__.py`
- `metagpt/actions/action.py`
- `metagpt/actions/action_graph.py`
- `metagpt/actions/action_node.py`
- `metagpt/actions/action_outcls_registry.py`
- `metagpt/actions/action_output.py`
- `metagpt/actions/add_requirement.py`
- `metagpt/actions/analyze_requirements.py`
- `metagpt/actions/debug_error.py`
- `metagpt/actions/design_api.py`
- `metagpt/actions/design_api_an.py`
- `metagpt/actions/design_api_review.py`
- `metagpt/actions/di/__init__.py`
- `metagpt/actions/di/ask_review.py`
- `metagpt/actions/di/execute_nb_code.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support