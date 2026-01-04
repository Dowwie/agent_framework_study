# HMP Context: MetaGPT

## Quick Facts

- Repository: /Users/dgordon/my_projects/agent_framework_study/repos/MetaGPT
- Primary language: Python
- Architecture style: Role-based multi-agent framework with environment orchestration
- Total files: 1,255 (890 Python files)
- Focus: Software development automation through specialized agent roles

### Async/Streaming Model
- **Implementation**: Full async/await pattern from top to bottom
- **Evidence**:
  - Role._think(), _act(), _observe(), _react() all async
  - Action.run() is async
  - Environment.run() is async coordinator
  - Memory operations are sync (list-based storage)
- **Implications**:
  - Clean concurrency model for I/O-bound LLM calls

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `examples/llm_vision.py`
- `examples/serialize_model.py`
- `examples/stream_output_via_api.py`
- `metagpt/configs/llm_config.py`
- `metagpt/configs/models_config.py`
- `metagpt/ext/spo/utils/llm_client.py`
- `metagpt/ext/stanford_town/actions/agent_chat_sum_rel.py`
- `metagpt/ext/stanford_town/actions/gen_iter_chat_utt.py`
- `metagpt/llm.py`
- `metagpt/provider/__init__.py`
- `metagpt/provider/anthropic_api.py`
- `metagpt/provider/ark_api.py`
- `metagpt/provider/azure_openai_api.py`
- `metagpt/provider/base_llm.py`
- `metagpt/provider/bedrock/__init__.py`
- `metagpt/provider/bedrock/base_provider.py`
- `metagpt/provider/bedrock/bedrock_provider.py`
- `metagpt/provider/bedrock/utils.py`
- `metagpt/provider/bedrock_api.py`
- `metagpt/provider/constant.py`
- `metagpt/provider/dashscope_api.py`
- `metagpt/provider/general_api_base.py`
- `metagpt/provider/general_api_requestor.py`
- `metagpt/provider/google_gemini_api.py`
- `metagpt/provider/human_provider.py`
- `metagpt/provider/llm_provider_registry.py`
- `metagpt/provider/metagpt_api.py`
- `metagpt/provider/ollama_api.py`
- `metagpt/provider/openai_api.py`
- `metagpt/provider/openrouter_reasoning.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy