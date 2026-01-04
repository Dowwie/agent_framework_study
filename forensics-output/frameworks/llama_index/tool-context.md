# Tool Interface Context: llama_index

## Quick Facts

- **Repository**: https://github.com/run-llama/llama_index
- **Primary language**: Python
- **Architecture style**: Modular monorepo with plugin-based integrations
- **Lines of Code**: 4,074 Python files across core + integrations
- **Maturity**: Production-grade, widely adopted RAG/agent framework

### Error Handling Mentions
- **Tradeoffs**: Excellent validation and serialization, but adds complexity (metaclass composition, PrivateAttr workarounds)
**Error Handling**: Error-as-data with LLM-driven self-correction
- **Tradeoffs**: Elegant recovery without retry logic, but lacks structured error taxonomy
- **Strength**: `retry_messages` pattern enables LLM to fix parse errors by seeing formatting instructions
- **Weakness**: No retry limits — LLM can loop indefinitely on the same mistake

## Tool-Relevant Files

Priority files for tool interface analysis:

- `llama-index-core/llama_index/core/agent/workflow/function_agent.py`
- `llama-index-core/llama_index/core/base/response/schema.py`
- `llama-index-core/llama_index/core/callbacks/schema.py`
- `llama-index-core/llama_index/core/indices/common/struct_store/schema.py`
- `llama-index-core/llama_index/core/indices/property_graph/transformations/schema_llm.py`
- `llama-index-core/llama_index/core/indices/query/schema.py`
- `llama-index-core/llama_index/core/langchain_helpers/agents/toolkits.py`
- `llama-index-core/llama_index/core/langchain_helpers/agents/tools.py`
- `llama-index-core/llama_index/core/llms/function_calling.py`
- `llama-index-core/llama_index/core/objects/tool_node_mapping.py`
- `llama-index-core/llama_index/core/program/function_program.py`
- `llama-index-core/llama_index/core/query_engine/flare/schema.py`
- `llama-index-core/llama_index/core/schema.py`
- `llama-index-core/llama_index/core/tools/__init__.py`
- `llama-index-core/llama_index/core/tools/calling.py`
- `llama-index-core/llama_index/core/tools/download.py`
- `llama-index-core/llama_index/core/tools/eval_query_engine.py`
- `llama-index-core/llama_index/core/tools/function_tool.py`
- `llama-index-core/llama_index/core/tools/ondemand_loader_tool.py`
- `llama-index-core/llama_index/core/tools/query_engine.py`
- `llama-index-core/llama_index/core/bridge/pydantic.py`
- `llama-index-core/llama_index/core/bridge/pydantic_core.py`
- `llama-index-core/llama_index/core/bridge/pydantic_settings.py`
- `llama-index-core/llama_index/core/data_structs/registry.py`
- `llama-index-core/llama_index/core/evaluation/batch_runner.py`
- `llama-index-core/llama_index/core/indices/registry.py`
- `llama-index-core/llama_index/core/instrumentation/events/exception.py`
- `llama-index-core/llama_index/core/output_parsers/pydantic.py`
- `llama-index-core/llama_index/core/prompts/default_prompt_selectors.py`
- `llama-index-core/llama_index/core/prompts/default_prompts.py`
- `llama-index-core/llama_index/core/selectors/pydantic_selectors.py`
- `llama-index-core/llama_index/core/storage/docstore/registry.py`
- `llama-index-core/llama_index/core/workflow/errors.py`
- `llama-index-core/tests/evaluation/test_batch_runner.py`
- `llama-index-core/tests/output_parsers/test_pydantic.py`

## Analysis Focus

When analyzing this framework for tool interface, determine:
1. Tool modeling (base class, protocol, decorated function, Pydantic)
2. Schema generation method (introspection, Pydantic, decorator, manual)
3. Built-in tool inventory (categories and count)
4. Registration pattern (declarative, registry, discovery, factory)
5. Execution flow (validation, invocation, error feedback)
6. Retry/self-correction mechanisms
7. Parallel execution support