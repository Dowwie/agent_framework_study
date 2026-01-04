# Tool Interface Context: pydantic-ai

## Quick Facts

- **Repository**: https://github.com/pydantic/pydantic-ai
- **Primary Language**: Python
- **Architecture Style**: Modular with graph-based execution engine
- **Key Strength**: Type-safe, production-ready agent framework with excellent async support
- **Target Use Case**: Production applications requiring reliability, observability, and multi-provider support

### Tool Interface Overview
- **Schema Generation**: Automatic from function signatures + docstrings (Google/Numpy/Sphinx)
- **Validation**: Pydantic TypeAdapter with detailed error messages to model
- **Context Injection**: RunContext[DepsT] auto-detected as first parameter
- **Ergonomics**: Excellent DX - just write normal functions, framework handles the rest
- **Preparation**: Dynamic tool availability via prepare functions

**Key Innovation**: Validation errors formatted and sent to model for self-correction.

### Error Handling Mentions
- **Approach**: Combination of `@dataclass` for structure + Pydantic V2 for validation
- **Runtime Validation**: Pydantic TypeAdapter for automatic validation
#### Error Handling: Three-Layer Retry System
- **Layer 1 (Graph)**: Output validation retries (max_result_retries)
- **Layer 2 (Tool)**: Per-tool retries with model feedback (ModelRetry exception)

## Tool-Relevant Files

Priority files for tool interface analysis:

- `examples/pydantic_ai_examples/ag_ui/api/tool_based_generative_ui.py`
- `examples/pydantic_ai_examples/slack_lead_qualifier/functions.py`
- `pydantic_ai_slim/pydantic_ai/_function_schema.py`
- `pydantic_ai_slim/pydantic_ai/_json_schema.py`
- `pydantic_ai_slim/pydantic_ai/_tool_manager.py`
- `pydantic_ai_slim/pydantic_ai/builtin_tools.py`
- `pydantic_ai_slim/pydantic_ai/common_tools/__init__.py`
- `pydantic_ai_slim/pydantic_ai/common_tools/duckduckgo.py`
- `pydantic_ai_slim/pydantic_ai/common_tools/tavily.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/dbos/_fastmcp_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/prefect/_function_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/prefect/_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_dynamic_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_fastmcp_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_function_toolset.py`
- `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_toolset.py`
- `pydantic_ai_slim/pydantic_ai/models/function.py`
- `pydantic_ai_slim/pydantic_ai/tools.py`
- `pydantic_ai_slim/pydantic_ai/toolsets/__init__.py`
- `pydantic_ai_slim/pydantic_ai/toolsets/_dynamic.py`
- `examples/pydantic_ai_examples/__main__.py`
- `examples/pydantic_ai_examples/ag_ui/__init__.py`
- `examples/pydantic_ai_examples/ag_ui/__main__.py`
- `examples/pydantic_ai_examples/ag_ui/api/__init__.py`
- `examples/pydantic_ai_examples/ag_ui/api/agentic_chat.py`
- `examples/pydantic_ai_examples/ag_ui/api/agentic_generative_ui.py`
- `examples/pydantic_ai_examples/ag_ui/api/human_in_the_loop.py`
- `examples/pydantic_ai_examples/ag_ui/api/predictive_state_updates.py`
- `examples/pydantic_ai_examples/ag_ui/api/shared_state.py`
- `examples/pydantic_ai_examples/bank_support.py`
- `examples/pydantic_ai_examples/chat_app.py`
- `examples/pydantic_ai_examples/data_analyst.py`
- `examples/pydantic_ai_examples/evals/__init__.py`
- `examples/pydantic_ai_examples/evals/agent.py`
- `examples/pydantic_ai_examples/evals/custom_evaluators.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support