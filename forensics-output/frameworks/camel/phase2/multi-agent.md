# Multi-Agent Analysis: CAMEL

## Multi-Agent Philosophy

CAMEL's name stands for "**Communicative Agents for Mind Exploration of Large-Scale Language Model Society**" - multi-agent collaboration is core to the framework.

**Design Philosophy:**
- Agents communicate via messages, not shared state
- Societies orchestrate agent interactions
- Role-based specialization (assistant, user, critic, planner)
- Flexible coordination patterns (role-playing, workforce, BabyAGI)

## Society Patterns

### 1. Role-Playing Pattern

**Two-agent conversational collaboration:**

```python
class RolePlaying:
    def __init__(
        self,
        assistant_role_name: str,  # e.g., "Python Programmer"
        user_role_name: str,        # e.g., "Product Manager"
        task_prompt: str,
        with_task_specify: bool = True,
        with_task_planner: bool = False,
        with_critic_in_the_loop: bool = False,
        ...
    ):
        # Create assistant agent
        self.assistant_agent = ChatAgent(
            system_message=self._gen_sys_msg(assistant_role_name),
            ...
        )

        # Create user agent
        self.user_agent = ChatAgent(
            system_message=self._gen_sys_msg(user_role_name),
            ...
        )

        # Optional: Task specification agent
        if with_task_specify:
            self.task_specify_agent = TaskSpecifyAgent(...)

        # Optional: Task planning agent
        if with_task_planner:
            self.task_planner_agent = TaskPlannerAgent(...)

        # Optional: Critic agent
        if with_critic_in_the_loop:
            if critic_role_name == "human":
                self.critic = Human()  # Human-in-the-loop
            else:
                self.critic = CriticAgent(...)
```

**Execution Flow:**
```python
def init_chat(self) -> Tuple[BaseMessage, List[BaseMessage]]:
    # 1. Optionally specify task
    if self.with_task_specify:
        task = self.task_specify_agent.run(self.task_prompt)
    else:
        task = self.task_prompt

    # 2. Optionally plan task
    if self.with_task_planner:
        plan = self.task_planner_agent.run(task)
    else:
        plan = task

    # 3. Create initial message
    init_msg = BaseMessage.make_assistant_message(
        role_name=self.assistant_role_name,
        content=plan,
    )

    return init_msg, []

def step(
    self,
    assistant_msg: BaseMessage,
) -> Tuple[ChatAgentResponse, ChatAgentResponse]:
    # 1. User agent responds to assistant
    user_response = self.user_agent.step(assistant_msg)

    # 2. Optional critic evaluation
    if self.with_critic_in_the_loop:
        critic_msg = self.critic.step(user_response.msg)
        # User refines based on critique
        user_response = self.user_agent.step(critic_msg)

    # 3. Assistant responds to user
    assistant_response = self.assistant_agent.step(user_response.msg)

    return assistant_response, user_response
```

**Communication Pattern:**
```
[Task Specification]
    ↓
[Task Planning]
    ↓
Assistant → User → (Critic) → User → Assistant
             ↑_____________________________|
                   (repeat until done)
```

**Use Cases:**
- Collaborative problem solving
- Iterative refinement
- Debate/discussion
- Code review (programmer + reviewer)

**Specializations:**
- **TaskSpecifyAgent:** Clarifies vague tasks
- **TaskPlannerAgent:** Breaks tasks into steps
- **CriticAgent:** Evaluates quality and provides feedback

### 2. Workforce Pattern

**Scalable multi-agent orchestration:**

```python
class Workforce:
    def __init__(
        self,
        mode: WorkforceMode,  # PARALLEL, PIPELINE, LOOP
        workers: List[Worker],
        failure_handling: FailureHandlingConfig = ...,
        workflow_memory_manager: Optional[WorkflowMemoryManager] = None,
    ):
        self.mode = mode
        self.workers = workers
        self.failure_handling = failure_handling
        self.memory_manager = workflow_memory_manager
```

**Worker Types:**

```python
class SingleAgentWorker:
    """Worker wrapping a single ChatAgent."""
    def __init__(self, agent: ChatAgent, role: str):
        self.agent = agent
        self.role = role

    async def execute(self, task: str) -> str:
        response = await self.agent.astep(task)
        return response.msg.content

class RolePlayingWorker:
    """Worker wrapping a RolePlaying society."""
    def __init__(self, role_playing: RolePlaying):
        self.role_playing = role_playing

    async def execute(self, task: str) -> str:
        # Run role-playing until convergence
        init_msg, _ = self.role_playing.init_chat()
        for _ in range(max_iterations):
            assistant_resp, user_resp = self.role_playing.step(init_msg)
            if assistant_resp.terminated or user_resp.terminated:
                break
            init_msg = assistant_resp.msg
        return assistant_resp.msg.content
```

**Execution Modes:**

**PARALLEL Mode:**
```python
async def run_parallel(self, tasks: List[Task]):
    # Each worker executes its task independently
    results = await asyncio.gather(*[
        worker.execute(task) for worker, task in zip(self.workers, tasks)
    ])
    return results
```

**PIPELINE Mode:**
```python
async def run_pipeline(self, initial_task: Task):
    # Sequential execution, output feeds next worker
    result = initial_task
    for worker in self.workers:
        result = await worker.execute(result)
    return result
```

**LOOP Mode:**
```python
async def run_loop(self, task: Task):
    # Iterative refinement until convergence
    result = task
    iteration = 0

    while not self._is_converged(result) and iteration < self.max_iterations:
        for worker in self.workers:
            result = await worker.execute(result)
        iteration += 1

    return result
```

**Failure Handling:**
```python
@dataclass
class FailureHandlingConfig:
    recovery_strategy: RecoveryStrategy  # RETRY, SKIP, FALLBACK, TERMINATE
    max_retries: int = 3
    retry_delay: float = 1.0
    fallback_workers: Optional[List[Worker]] = None
    on_failure: Optional[Callable] = None

class RecoveryStrategy(Enum):
    RETRY = "retry"        # Retry same worker
    SKIP = "skip"          # Skip failed worker, continue workflow
    FALLBACK = "fallback"  # Try fallback workers
    TERMINATE = "terminate" # Stop entire workflow
```

**Workflow Memory:**
```python
class WorkflowMemoryManager:
    """Tracks workflow execution state and results."""
    def __init__(self, selection_method: WorkflowSelectionMethod):
        self.execution_history: List[Dict] = []
        self.selection_method = selection_method

    def record_execution(self, worker: Worker, task: Task, result: Any):
        self.execution_history.append({
            "worker": worker.role,
            "task": task,
            "result": result,
            "timestamp": time.time(),
        })

    def select_next_worker(self) -> Worker:
        # Select based on past performance
        if self.selection_method == WorkflowSelectionMethod.BEST_PERFORMANCE:
            # Choose worker with highest success rate
            ...
        elif self.selection_method == WorkflowSelectionMethod.ROUND_ROBIN:
            # Rotate through workers
            ...
```

### 3. BabyAGI Pattern

**Task-driven autonomous agent:**

```python
class BabyAGI:
    """Autonomous task completion system inspired by BabyAGI."""
    def __init__(
        self,
        assistant_role_name: str,
        user_role_name: str,
        task_prompt: str,
        task_type: TaskType = TaskType.AI_SOCIETY,
    ):
        # Similar to RolePlaying but with task list management
        self.task_list: List[str] = []
        self.completed_tasks: List[str] = []

    def run(self, max_iterations: int = 10):
        # 1. Generate initial task list
        self.task_list = self._generate_initial_tasks()

        for iteration in range(max_iterations):
            if not self.task_list:
                break  # All tasks complete

            # 2. Get next task
            current_task = self.task_list.pop(0)

            # 3. Execute task via role-playing
            result = self._execute_task(current_task)

            # 4. Mark complete
            self.completed_tasks.append(current_task)

            # 5. Generate new tasks based on result
            new_tasks = self._generate_new_tasks(result)
            self.task_list.extend(new_tasks)

            # 6. Prioritize task list
            self.task_list = self._prioritize_tasks(self.task_list)

        return self.completed_tasks
```

**Task Management:**
- Dynamic task generation based on results
- Task prioritization
- Completion tracking

## Agent Communication

### Message Passing

**Primary communication mechanism:**

```python
class BaseMessage:
    role_name: str
    role_type: RoleType
    content: str
    meta_dict: Optional[Dict[str, Any]]

# Agent A sends to Agent B
msg_to_b = BaseMessage.make_user_message(
    role_name="Agent A",
    content="Please analyze this data..."
)

response = agent_b.step(msg_to_b)

# Agent B responds to Agent A
msg_to_a = response.msg  # BaseMessage
```

**No Shared State:**
- Agents don't access each other's memory directly
- All communication via message passing
- Clean isolation and independence

### Agent Communication Toolkit

**Inter-agent messaging as a tool:**

```python
class AgentCommunicationToolkit(BaseToolkit, RegisteredAgentToolkit):
    """Toolkit for agents to communicate with other agents."""

    def __init__(self, agent_registry: Dict[str, ChatAgent]):
        super().__init__()
        self.agent_registry = agent_registry

    def send_message(self, target_agent: str, message: str) -> str:
        """Send a message to another agent.

        Args:
            target_agent: Name of the target agent
            message: Message to send

        Returns:
            Response from target agent
        """
        if target_agent not in self.agent_registry:
            return f"Error: Agent '{target_agent}' not found"

        agent = self.agent_registry[target_agent]
        response = agent.step(message)
        return response.msg.content

    def broadcast(self, message: str, exclude: Optional[List[str]] = None) -> Dict[str, str]:
        """Broadcast message to all agents.

        Args:
            message: Message to broadcast
            exclude: Agent names to exclude

        Returns:
            Dict mapping agent names to their responses
        """
        responses = {}
        for name, agent in self.agent_registry.items():
            if exclude and name in exclude:
                continue
            response = agent.step(message)
            responses[name] = response.msg.content
        return responses

    def get_tools(self) -> List[FunctionTool]:
        return [
            FunctionTool(self.send_message),
            FunctionTool(self.broadcast),
        ]
```

**Usage:**
```python
# Create agents
analyst = ChatAgent(system_message="You are a data analyst")
researcher = ChatAgent(system_message="You are a researcher")

# Create registry
registry = {
    "analyst": analyst,
    "researcher": researcher,
}

# Give coordinator the communication toolkit
coordinator = ChatAgent(
    system_message="You coordinate between agents",
    tools=[*AgentCommunicationToolkit(registry).get_tools()],
)

# Coordinator can now communicate with other agents via tools
coordinator.step("Ask the analyst to summarize the data, then have the researcher verify it")
```

## Coordination Patterns

### Shared Context

**Workflow memory for coordination:**

```python
class WorkflowMemoryManager:
    def __init__(self):
        self.shared_context: Dict[str, Any] = {}
        self.execution_log: List[Dict] = []

    def update_context(self, key: str, value: Any):
        """Update shared context visible to all workers."""
        self.shared_context[key] = value

    def get_context(self, key: str) -> Any:
        """Retrieve from shared context."""
        return self.shared_context.get(key)
```

**Pattern:**
```python
# Worker 1 stores result
workflow_memory.update_context("data_analysis", analysis_result)

# Worker 2 retrieves result
previous_analysis = workflow_memory.get_context("data_analysis")
```

### Termination Coordination

**Coordinated stopping:**

```python
class RolePlaying:
    def __init__(self, ..., stop_event: Optional[threading.Event] = None):
        self.stop_event = stop_event

    def step(self, ...):
        if self.stop_event and self.stop_event.is_set():
            # External signal to stop
            return None
```

**Usage:**
```python
stop_event = threading.Event()

role_playing = RolePlaying(
    assistant_role_name="Developer",
    user_role_name="Reviewer",
    stop_event=stop_event,
)

# Run in thread
thread = threading.Thread(target=role_playing.run)
thread.start()

# Stop from outside
time.sleep(60)  # Let it run for 1 minute
stop_event.set()  # Signal to stop
thread.join()
```

## Human-in-the-Loop

### Human Agent

**Human as a special agent type:**

```python
class Human:
    """Represents a human participant in multi-agent system."""

    def step(self, input_message: BaseMessage) -> ChatAgentResponse:
        # Display message to human
        print(f"{input_message.role_name}: {input_message.content}")

        # Get human input
        human_input = input("Your response: ")

        # Create response message
        response_msg = BaseMessage.make_user_message(
            role_name="Human",
            content=human_input,
        )

        return ChatAgentResponse(
            msgs=[response_msg],
            terminated=False,
        )
```

**Integration:**
```python
role_playing = RolePlaying(
    assistant_role_name="AI Assistant",
    user_role_name="Product Manager",
    critic_role_name="human",  # Human critic!
)

# During execution, human will be prompted for input
```

## Multi-Agent Score

**Overall: 8/10**

**Breakdown:**
- Society Patterns: 9/10 (RolePlaying + Workforce + BabyAGI)
- Communication: 8/10 (Message passing, agent communication toolkit)
- Coordination: 7/10 (Workflow memory, but limited)
- Failure Handling: 9/10 (Excellent recovery strategies)
- Human-in-the-Loop: 8/10 (Human as agent is elegant)
- Scalability: 7/10 (Works well, but no distribution)

## Patterns to Adopt

1. **Society abstraction:** High-level patterns (RolePlaying, Workforce, BabyAGI)
2. **Worker pattern:** Wrap agents for flexible composition
3. **Execution modes:** PARALLEL, PIPELINE, LOOP for different workflows
4. **Failure recovery:** Comprehensive `FailureHandlingConfig` with strategies
5. **Human-as-agent:** Treat humans as special agents, not external entities
6. **Agent communication toolkit:** Tools for inter-agent messaging
7. **Stop events:** Graceful shutdown via threading.Event

## Patterns to Avoid

1. **No distributed execution:** All agents run in same process
2. **Limited convergence detection:** LOOP mode needs better criteria
3. **No agent discovery:** Registry is manual, not automatic
4. **Shared context without locks:** Race conditions possible
5. **No agent lifecycle management:** Can't pause/resume agents

## Recommendations

1. **Add distributed coordination:** Celery, Ray, or similar for multi-node
2. **Agent discovery service:** Auto-register agents, query capabilities
3. **Better convergence metrics:** Define when LOOP should stop
4. **Agent state snapshots:** Save/restore agent state during workflows
5. **Message queues:** Async message passing for scalability
6. **Agent monitoring:** Track health, performance, resource usage
7. **Dynamic worker selection:** Choose workers based on task requirements
8. **Agent marketplace:** Discover and compose pre-built agent roles
