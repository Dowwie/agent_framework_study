## Memory Orchestration Analysis: LangGraph

### Context Assembly
- **Order**: User-defined (no prescribed order)
- **Method**: State-based (channels hold all context)
- **Location**: N/A (framework doesn't assemble prompts - user nodes do)

### Core Insight

LangGraph is **not a prompt assembly framework**. It's a **state orchestration framework**. Context assembly happens in **user-defined nodes**, not the framework.

The framework provides:
1. **State persistence** (checkpoints)
2. **State updates** (channel writes)
3. **State reads** (channel reads)

**User nodes** are responsible for:
1. Reading from state
2. Assembling prompts
3. Calling LLMs
4. Writing results back to state

### State as Memory

LangGraph uses **channels** as memory tiers:

**Tier 1: Working Memory (Current Step)**
- Channels with current values
- Immediately available to nodes
- Example: `messages` channel with full conversation

**Tier 2: Checkpoint Memory (Persistent)**
- Saved to checkpointer after each step
- Enables resume after crash
- Example: Entire graph state in PostgreSQL

**Tier 3: External Memory (User-managed)**
- Vector stores, databases (not part of framework)
- User nodes explicitly query
- Example: Node calls Chroma for retrieval

### Typical Message Assembly Pattern

Users typically use `MessagesState` with LangChain models:

```python
from langgraph.graph import StateGraph, MessagesState
from langchain_openai import ChatOpenAI

class State(MessagesState):
    # MessagesState includes:
    # messages: Annotated[list[AnyMessage], add_messages]
    pass

def llm_node(state: State):
    # 1. State contains full message history
    messages = state["messages"]

    # 2. LLM sees all messages (model handles truncation)
    llm = ChatOpenAI()
    response = llm.invoke(messages)

    # 3. Return new message to append
    return {"messages": [response]}
```

**Key points**:
- **No explicit assembly**: Messages passed directly to LLM
- **No eviction**: Framework stores full history in state
- **Token management**: Delegated to LLM client or user code

### Eviction Policy
- **Strategy**: None (framework level)
- **Trigger**: N/A
- **Location**: User responsibility

**Rationale**: LangGraph focuses on **execution**, not **memory management**.

### User-Level Eviction Patterns

**Pattern 1: Truncate in node**
```python
def llm_with_truncation(state: State):
    messages = state["messages"]

    # Keep system message + last N messages
    truncated = [messages[0]] + messages[-10:]

    response = llm.invoke(truncated)
    return {"messages": [response]}
```

**Pattern 2: Summarize old messages**
```python
def llm_with_summarization(state: State):
    messages = state["messages"]

    if len(messages) > 50:
        # Summarize oldest messages
        old = messages[1:25]  # Skip system message
        summary_msg = llm.invoke([
            SystemMessage("Summarize this conversation"),
            *old
        ])

        # Replace old messages with summary
        new_messages = [
            messages[0],  # System message
            HumanMessage(f"Previous conversation summary: {summary_msg.content}"),
            *messages[25:]
        ]
        state = {"messages": new_messages}

    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

**Pattern 3: Token-aware sliding window**
```python
import tiktoken

def llm_with_token_limit(state: State, max_tokens: int = 8000):
    messages = state["messages"]
    enc = tiktoken.get_encoding("cl100k_base")

    # Count tokens from newest to oldest
    kept = []
    total_tokens = 0
    for msg in reversed(messages[1:]):  # Keep system message separate
        tokens = len(enc.encode(msg.content))
        if total_tokens + tokens > max_tokens:
            break
        kept.insert(0, msg)
        total_tokens += tokens

    # Always include system message
    truncated = [messages[0]] + kept

    response = llm.invoke(truncated)
    return {"messages": [response]}
```

**Pattern 4: Vector store swapping**
```python
from langchain.vectorstores import Chroma

class State(MessagesState):
    vector_store: Chroma  # External

def llm_with_rag(state: State):
    messages = state["messages"]

    # Archive old messages to vector store
    if len(messages) > 20:
        to_archive = messages[1:10]
        for msg in to_archive:
            state["vector_store"].add_texts([msg.content])

        # Keep recent only
        messages = [messages[0]] + messages[10:]

    # Retrieve relevant context
    current_query = messages[-1].content
    relevant_docs = state["vector_store"].similarity_search(current_query, k=3)
    context_msg = SystemMessage(f"Relevant context: {relevant_docs}")

    # Build prompt with retrieved context
    prompt = [messages[0], context_msg] + messages[1:]

    response = llm.invoke(prompt)
    return {"messages": [response]}
```

### Memory Tiers

| Tier | Storage | Capacity | Retrieval | Framework Support |
|------|---------|----------|-----------|------------------|
| Working | State channels | Unlimited* | Immediate | Full (channels) |
| Checkpoint | Checkpointer backend | Unlimited | By thread_id | Full (checkpointer protocol) |
| Vector Store | External DB | Unlimited | Semantic search | None (user integrates) |
| Long-term | External DB | Unlimited | SQL/NoSQL queries | None (user integrates) |

*Unlimited in framework, but memory-bound at runtime

### Checkpoint-Based Persistence

**Checkpoint structure** (from `checkpoint/base.py`):
```python
class Checkpoint(TypedDict):
    channel_values: dict[str, Any]  # Full state snapshot
    channel_versions: dict[str, int]
    # ... other metadata
```

**Save/Load**:
- **Save**: Automatic after each step (if checkpointer configured)
- **Load**: On graph invocation with `thread_id` in config
- **Purpose**: Resume conversations, crash recovery

**Usage**:
```python
from langgraph.checkpoint.memory import InMemorySaver

# Compile with checkpointer
graph = builder.compile(checkpointer=InMemorySaver())

# First conversation
config = {"configurable": {"thread_id": "user-123"}}
graph.invoke({"messages": [("user", "Hello")]}, config)

# Resume later (loads checkpoint)
graph.invoke({"messages": [("user", "Continue...")]}, config)
```

**Memory tier**: Tier 2 (persistent, but loaded entirely into memory when resumed)

### Token Management
- **Counting**: Not provided (user responsibility)
- **Budget Allocation**: Not provided
- **Overflow Handling**: User-defined

**Recommendation**: Use LangChain's `ConversationTokenBufferMemory` or similar in nodes.

### No Built-In Summarization

LangGraph does **not** provide automatic summarization. Users must:
1. Detect overflow (count tokens in node)
2. Call LLM to summarize
3. Update state with summary

**Why**: Framework is general-purpose, not LLM-specific.

### Integration with LangChain Memory

Users can integrate LangChain's memory classes:

```python
from langchain.memory import ConversationBufferWindowMemory

class State(TypedDict):
    langchain_memory: ConversationBufferWindowMemory
    messages: Annotated[list, add_messages]

def llm_node(state: State):
    memory = state["langchain_memory"]

    # LangChain memory handles truncation
    context = memory.load_memory_variables({})

    llm = ChatOpenAI()
    response = llm.invoke(context["history"])

    # Update memory
    memory.save_context({"input": state["messages"][-1].content}, {"output": response.content})

    return {"messages": [response]}
```

**Note**: This pattern is uncommon; most users use `MessagesState` directly.

### Store Integration (New in v0.6)

LangGraph v0.6 introduces **`BaseStore`** for external memory:

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()
graph = builder.compile(store=store)

def node_with_store(state: State, runtime: Runtime):
    # Access store via runtime
    store = runtime.store

    # Store long-term facts
    store.put(("user", state["user_id"]), "preference", {"theme": "dark"})

    # Retrieve later
    prefs = store.get(("user", state["user_id"]), "preference")
```

**Use case**: Long-term facts, user preferences, entity memory.

**Memory tier**: Tier 3 (persistent, external, query-on-demand)

### Managed Values

LangGraph provides **managed values** for automatic lifecycle management:

**Built-in**: `is_last_step`
```python
from langgraph.managed.is_last_step import IsLastStep

class State(TypedDict):
    is_last_step: Annotated[bool, IsLastStep]

def node(state: State):
    if state["is_last_step"]:
        # Last chance to do something
        pass
```

**Use case**: Conditional logic based on execution context (not user state).

### Scratchpad Pattern

No built-in scratchpad, but users implement via state field:

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]
    scratchpad: Annotated[list[str], lambda x, y: x + [y]]  # Append-only

def thinking_node(state: State):
    thought = llm.invoke("Let me think...")
    return {"scratchpad": [thought.content]}

def acting_node(state: State):
    # Access scratchpad for context
    thoughts = "\n".join(state["scratchpad"])
    action = llm.invoke(f"Based on thoughts: {thoughts}, take action...")
    return {"messages": [action]}
```

**Benefits**:
- Scratchpad persists across steps (in state)
- Checkpointed automatically
- Can be truncated/summarized like messages

### Context Assembly in Practice

**Example: Full ReAct loop with context**

```python
from langgraph.prebuilt import create_react_agent

# create_react_agent handles context assembly:
# 1. System message (optional)
# 2. Message history
# 3. Tool schemas (auto-generated)
# 4. User input

agent = create_react_agent(
    model=ChatOpenAI(),
    tools=[search_tool, calculator],
    system_message="You are a helpful assistant."
)

# State: MessagesState
# - messages: list of all messages (user, assistant, tool results)

# Node 1 (LLM):
#   - Reads state["messages"]
#   - Invokes model with full history + tool schemas
#   - Returns new message (possibly with tool calls)

# Node 2 (Tools):
#   - Executes tool calls from last message
#   - Returns ToolMessage results

# Conditional edge:
#   - If tool calls → loop back to LLM
#   - Else → END
```

**Context assembly happens in `model.invoke(messages)`**:
- LangChain model sees full message list
- Model's own context window management applies
- Tool schemas injected via `bind_tools()`

### Recommendations

**Strengths**:
- State persistence via checkpoints (crash recovery)
- Flexible: user controls context assembly
- No forced eviction policies
- Integration with LangChain memory classes
- Store abstraction for external memory

**Weaknesses**:
- No built-in token counting or budget management
- No automatic summarization
- No built-in eviction policies
- Users must implement memory management in nodes

**Best practices to adopt**:
1. **Checkpoint-based persistence**: Automatic state snapshots
2. **Store abstraction**: Separate interface for external memory
3. **User-controlled assembly**: Framework doesn't impose prompt structure
4. **State as memory**: All context lives in typed state schema
5. **Managed values**: Special fields with automatic lifecycle
6. **No magic**: Explicit over implicit (user implements eviction)

**For new framework**:
- Consider providing **optional** eviction helpers (token counter, summarizer)
- Keep core framework memory-agnostic
- Provide **examples** of common memory patterns (RAG, summarization)
- Checkpoint abstraction is excellent - adopt it
- Store abstraction is clean - consider similar interface
