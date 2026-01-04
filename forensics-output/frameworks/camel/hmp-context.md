# HMP Context: camel

## Quick Facts

- **Repository:** https://github.com/camel-ai/camel
- **Version Analyzed:** 0.2.82
- **Primary Language:** Python
- **Architecture Style:** Modular monolith with society-based multi-agent orchestration
- **Core Philosophy:** Communicative Agents for Mind Exploration (role-playing, multi-agent collaboration)

### Async/Streaming Model
**Pattern:**
- Dual APIs: `step()` / `astep()`, `summarize()` / `asummarize()`
- Sync methods delegate to async via `asyncio.run()`
- ThreadPoolExecutor (64 workers) for sync tools to avoid blocking event loop
- Parallel tool execution via `asyncio.gather()`

**Critical Implementation:**
```python

### Streaming Mentions
**Concurrent Tool + Streaming Innovation:**
- Execute tools in background while streaming content
- Reasoning-aware streaming (separate reasoning from final answer)
**Score: 9/10** - Excellent async design with innovative streaming
- Streaming-aware (content streams while tools execute in background)

## HMP-Relevant Files

Priority files for harness-model protocol analysis:

- `camel/agents/chat_agent.py`
- `camel/bots/slack/models.py`
- `camel/configs/anthropic_config.py`
- `camel/configs/gemini_config.py`
- `camel/configs/litellm_config.py`
- `camel/configs/modelscope_config.py`
- `camel/configs/openai_config.py`
- `camel/configs/vllm_config.py`
- `camel/datagen/source2synth/models.py`
- `camel/datahubs/models.py`
- `camel/datasets/models.py`
- `camel/embeddings/gemini_embedding.py`
- `camel/embeddings/openai_compatible_embedding.py`
- `camel/embeddings/openai_embedding.py`
- `camel/environments/models.py`
- `camel/memories/blocks/chat_history_block.py`
- `camel/messages/__init__.py`
- `camel/messages/base.py`
- `camel/messages/conversion/__init__.py`
- `camel/messages/conversion/alpaca.py`
- `camel/messages/conversion/conversation_models.py`
- `camel/messages/conversion/sharegpt/__init__.py`
- `camel/messages/conversion/sharegpt/function_call_formatter.py`
- `camel/messages/conversion/sharegpt/hermes/__init__.py`
- `camel/messages/conversion/sharegpt/hermes/hermes_function_formatter.py`
- `camel/messages/func_message.py`
- `camel/models/__init__.py`
- `camel/models/_utils.py`
- `camel/models/aihubmix_model.py`
- `camel/models/aiml_model.py`

## Analysis Focus

When analyzing this framework for HMP, determine:
1. Wire format family (OpenAI-compatible, Anthropic, custom)
2. Tool call encoding (function calling API vs prompt injection)
3. Streaming protocol (SSE events, partial tool calls)
4. Agentic primitives (scratchpad, interrupt, HITL)
5. Provider abstraction strategy