# HMP Context: llama_index

## Quick Facts

- **Repository**: https://github.com/run-llama/llama_index
- **Primary language**: Python
- **Architecture style**: Modular monorepo with plugin-based integrations
- **Lines of Code**: 4,074 Python files across core + integrations
- **Maturity**: Production-grade, widely adopted RAG/agent framework

### Schema Generation (from tool-interface-analysis)
**Approach**: Reflection on Pydantic models

**OpenAI Tool Schema** (tools/types.py:L76-90):
```python
def to_openai_tool(self, skip_length_check: bool = False) -> Dict[str, Any]:
    if not skip_length_check and len(self.description) > 1024:

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `llama-datasets/eval_llm_survey_paper/llamaindex_baseline.py`
- `llama-index-core/llama_index/core/base/llms/__init__.py`
- `llama-index-core/llama_index/core/base/llms/base.py`
- `llama-index-core/llama_index/core/base/llms/generic_utils.py`
- `llama-index-core/llama_index/core/base/llms/types.py`
- `llama-index-core/llama_index/core/base/response/__init__.py`
- `llama-index-core/llama_index/core/base/response/schema.py`
- `llama-index-core/llama_index/core/callbacks/simple_llm_handler.py`
- `llama-index-core/llama_index/core/chat_engine/__init__.py`
- `llama-index-core/llama_index/core/chat_engine/condense_plus_context.py`
- `llama-index-core/llama_index/core/chat_engine/condense_question.py`
- `llama-index-core/llama_index/core/chat_engine/context.py`
- `llama-index-core/llama_index/core/chat_engine/multi_modal_context.py`
- `llama-index-core/llama_index/core/chat_engine/simple.py`
- `llama-index-core/llama_index/core/chat_engine/types.py`
- `llama-index-core/llama_index/core/chat_engine/utils.py`
- `llama-index-core/llama_index/core/chat_ui/__init__.py`
- `llama-index-core/llama_index/core/chat_ui/events.py`
- `llama-index-core/llama_index/core/chat_ui/models/__init__.py`
- `llama-index-core/llama_index/core/chat_ui/models/artifact.py`
- `llama-index-core/llama_index/core/embeddings/mock_embed_model.py`
- `llama-index-core/llama_index/core/indices/property_graph/sub_retrievers/llm_synonym.py`
- `llama-index-core/llama_index/core/indices/property_graph/transformations/dynamic_llm.py`
- `llama-index-core/llama_index/core/indices/property_graph/transformations/schema_llm.py`
- `llama-index-core/llama_index/core/indices/property_graph/transformations/simple_llm.py`
- `llama-index-core/llama_index/core/instrumentation/events/chat_engine.py`
- `llama-index-core/llama_index/core/instrumentation/events/llm.py`
- `llama-index-core/llama_index/core/langchain_helpers/streaming.py`
- `llama-index-core/llama_index/core/llms/__init__.py`
- `llama-index-core/llama_index/core/llms/callbacks.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy