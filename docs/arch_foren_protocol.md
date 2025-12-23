# The Architectural Forensics Protocol

## Mission
To deconstruct target agent frameworks to inform the architecture of a derivative system. This strategy prioritizes distinguishing between **software engineering decisions** (how it runs) and **cognitive architecture decisions** (how it thinks).

## Phase 1: The Engineering Chassis (Software Foundations)
**Goal:** Analyze the substrate. Determine the scalability, reliability, and developer experience (DX) costs of the underlying architecture.

### 1.1 The Data Substrate (Types & State)
*   **Core Primitives:** Locate the fundamental units of data (Messages, State).
    *   *Analysis:* Strict Schemas (Pydantic/Dataclasses) vs. Flexible Dicts.
    *   *Analysis:* Immutability. Are objects modified in place (risk of side effects) or copied-on-write (safer for concurrency)?
*   **Serialization Strategy:**
    *   *Analysis:* How is the application state persisted to disk? Look for `json()`, `dict()`, or `pickle` implementations. Is serialization implicit (automatic) or explicit (manual)?

### 1.2 The Execution Engine (Control Flow)
*   **Concurrency Model:**
    *   *Analysis:* Is the core engine `async/await` native, or synchronous with thread wrappers? This dictates future scalability.
    *   *Analysis:* Graph vs. Chain. Is the execution modeled as a DAG (Directed Acyclic Graph), a Finite State Machine (FSM), or a linear procedural chain?
*   **Event Architecture:**
    *   *Analysis:* How does the system emit signals? Look for `Callbacks`, `Listeners`, or `Async Generators` (`yield`).
    *   *Analysis:* Observability. How deep are the hooks? Can you intercept a specific tool call input before it executes?

### 1.3 The Component Model (Extensibility)
*   **Abstraction Layers:**
    *   *Analysis:* Inspect Base Classes (`BaseLLM`, `BaseTool`). Are they "Thick" (lots of logic/methods) or "Thin" (interfaces only)?
    *   *Analysis:* Dependency Injection. How are tools and memories injected? (Constructor injection vs. Global registries).
*   **Configuration:**
    *   *Analysis:* Code-first (Python classes) vs. Config-first (YAML/JSON).

### 1.4 Resilience & Boundaries
*   **Error Propagation:**
    *   *Analysis:* Do crashes inside a tool bring down the whole agent? Look for `try/except` blocks in the execution runner.
*   **Sandboxing:**
    *   *Analysis:* How does the code isolate dangerous operations (e.g., executing Python code or bash commands)?

---

## Phase 2: The Cognitive Architecture (Agent Capabilities)
**Goal:** Extract the "business logic" of agency. These are the patterns we will port onto our new Engineering Chassis.

### 2.1 The Cognitive Control Loop
*   **Reasoning Topology:**
    *   *Analysis:* Identifying the pattern. ReAct, Plan-and-Solve, Reflection, or Tree-of-Thoughts.
    *   *Analysis:* The "Step" Function. Locate the exact code block that parses LLM output and decides the next move (Tool vs. Finish).
*   **Loop Mechanics:**
    *   *Analysis:* Termination conditions. How does it detect infinite loops? (Token limits, step counts, or heuristic detection).

### 2.2 Memory & Context Orchestration
*   **Context Management:**
    *   *Analysis:* The Assembler. How are System Prompts, History, and Tool Results concatenated?
    *   *Analysis:* Eviction Policies. How does it handle context overflow? (FIFO, Summarization chains, or Vector-store swapping).
*   **State Continuity:**
    *   *Analysis:* How is "Short-term" memory (RAM) promoted to "Long-term" memory (Vector DB/SQL)?

### 2.3 The Tooling Interface (Sensory/Motor)
*   **Schema Generation:**
    *   *Analysis:* How does the framework translate Python functions to LLM-readable JSON schemas? (Introspection via `inspect` vs. manual definition).
*   **Feedback Loops:**
    *   *Analysis:* Self-Correction. If a tool fails, is the `stderr` or Exception message fed back to the LLM for a retry?

### 2.4 Multi-Agent Choreography
*   **Coordination:**
    *   *Analysis:* Handoffs. How does Agent A transfer control to Agent B? (Router implementation).
    *   **Shared State:** Do agents read from a "Blackboard" (global state) or use "Message Passing" (isolated state)?

---

## Phase 3: Synthesis & Output (The Deliverables)

For each framework analyzed, produce the following artifacts to guide the new architecture.

### 3.1 The "Best of Breed" Matrix
Create a table comparing the frameworks on key dimensions to select the "Golden Path" for the new tool.

| Dimension | Framework A Approach | Framework B Approach | **Decision for New Framework** |
| :--- | :--- | :--- | :--- |
| **Typing** | Heavy Pydantic usage | Loose Dicts | *Decision: Use Pydantic V2 for safety but minimize nesting.* |
| **Async** | Wrapper around Sync | Native Async | *Decision: Native Async is non-negotiable for scale.* |
| **Prompts** | Hardcoded f-strings | Jinja2 Templates | *Decision: Jinja2 for separation of code/text.* |

### 3.2 The Anti-Pattern Catalog
A "Do Not Repeat" list of technical debt observed in the studied frameworks.
*   *Example:* "Framework X uses deep inheritance trees (6 layers deep) for Agents, making it impossible to debug. We will use Composition instead."
*   *Example:* "Framework Y hides the raw LLM response object, preventing usage of token usage metadata. We must expose raw outputs."

### 3.3 The Reference Architecture Spec
A diagram and text document defining the new framework:
1.  **Core Primitives:** Define the `Message`, `State`, and `Result` objects.
2.  **Interface Definitions:** Define the `Protocol` for Tools and LLMs.
3.  **The Loop Algorithm:** Pseudocode for the main execution logic, incorporating the best reasoning patterns found in Phase 2.

## Study Process Execution
1.  **Clone & Map:** Download source; generate a file tree/dependency map.
2.  **Phase 1 Audit:** Walk the code from `types.py` up to `agent.py`. Record engineering trade-offs.
3.  **Phase 2 Extraction:** Trace a complex execution (e.g., "Write a file") to map the reasoning flow.
4.  **Synthesize:** Populate the Matrix and Anti-Pattern catalog.
