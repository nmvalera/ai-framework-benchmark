# LangGraph Py — Benchmark Study

> **Repo**: https://github.com/langchain-ai/langgraph
> **Commit studied**: `076e2a3627206f5a1aef573aaca4a01e5af897ca`
> **Cloned at**: `benchmarked-stacks/langgraph/`
> **Studied on**: 2026-05-16

## TL;DR

- **The mental model is "stateful graph", not "ReAct loop".** Every primitive — message lists, the LLM call, the tool call, even the HITL pause — is just a node on a `StateGraph` whose channel writes are reduced into shared state at the end of each super-step. The prebuilt `create_react_agent` is a thin factory that wires `agent`, `tools`, and optional `pre_model_hook` / `post_model_hook` nodes; underneath, it is the same Pregel loop as any other graph (`libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:867-990`). Engineers building a "simple ReAct agent" still inherit the full graph runtime — checkpointer, channels, super-steps, Send API, durability mode — whether they touch them or not. **In v1.0 (the studied tree), `create_react_agent` and `AgentState` are now `@deprecated` in favor of `langchain.agents.create_agent`** (`chat_agent_executor.py:53-117`, `274-277`) — the surface we're benchmarking is in maintenance mode.
- **Mid-run durability is the genuine USP and the architecture earns it.** Persistence fires after every super-step on `BaseCheckpointSaver.put` (`libs/langgraph/langgraph/pregel/_loop.py:697`) AND on every task write via `put_writes` (`_loop.py:450-489`, called from `_runner.py:583/591/603/613`). For a `create_react_agent` run, the granularity is: every LLM streaming token can checkpoint (`durability="async"` default), the agent node persists when the AIMessage completes, then each tool call in v2 is its own `Send`-dispatched task and `put_writes` runs per-tool, durable before the next super-step. A process crash mid-tool-call resumes from the last persisted task write — not from the start of the turn. Three durability modes: `"sync"` (block on persist), `"async"` (default; persist concurrently with next step), `"exit"` (only at run end) — `libs/langgraph/langgraph/types.py:87-93`.
- **Multi-tenancy is solved at two layers, and only one is in this repo.** Inside the graph, `Runtime[ContextT]` (`libs/langgraph/langgraph/runtime.py:124-282`) carries a typed `context` (e.g. `tenant_id`) into every node and tool; tool authors declare `runtime: ToolRuntime` and the harness injects it from outside the LLM-controlled args, with `_inject_tool_args` explicitly stripping any LLM-supplied values for injected keys to prevent injection attacks (`libs/prebuilt/langgraph/prebuilt/tool_node.py:1421-1429`). Outside the graph, the **LangGraph Server** (closed-source `langgraph_api` package, see Q5) exposes `@auth.on.<resource>.<action>` decorators that return `FilterType` dicts which the server applies to every Postgres query — owner-scoping is one decorator (`libs/sdk-py/langgraph_sdk/auth/__init__.py:74-93`).
- **The HTTP server is NOT in this repo.** `make dev-langgraph` (the analogue) shells out to `langgraph_api.cli.run_server`, which is a separate distribution behind `pip install "langgraph-cli[inmem]"` (`libs/cli/langgraph_cli/cli.py:746-777`). The cloud product (`langgraph-runtime-inmem`, LangGraph Platform) is the canonical deployment target; self-hosting is offered but it is closed source code under a free tier. For Predict's long-running-agent use case this is a real fork in the road — we either adopt the cloud server (and lose direct control of auth, persistence config, scaling) or BYO an HTTP layer around the OSS graph runtime.
- **Hooks via prebuilt are `pre_model_hook` / `post_model_hook` only.** Two node insertion points around the LLM call (`chat_agent_executor.py:296-297`, `876-963`). Anything richer — mutating tool input, decorating tool output, emitting additional tool calls after a result — lives at the lower `ToolNode` layer via the `wrap_tool_call` interceptor (`tool_node.py:202-277`), which receives a `ToolCallRequest` + an `execute` callable that the wrapper can call zero, one, or many times. **`wrap_tool_call` covers Claude Agent SDK's PostToolUse-with-additional-messages story**: a wrapper can call `execute()`, inspect the result, and decide to call `execute()` again with a different request, or short-circuit with a synthetic ToolMessage.
- **Sub-agents are subgraphs, period.** No first-class `SubAgent` / `handoff` primitive in OSS LangGraph. A "sub-agent" is a compiled `StateGraph` added as a node (`workflow.add_node("researcher", compiled_subgraph)`); the parent can dispatch via the `Send` API for parallel fan-out (`types.py:654-743`). Supervisor and swarm patterns are documented in `examples/multi_agent/` notebooks but ship as third-party packages (`langgraph-supervisor`, `langgraph-swarm`) or are hand-rolled.
- **Skills (à la Claude Code SKILL.md) are not a concept here.** The closest analogue is `BaseStore` (`libs/checkpoint/langgraph/store/base/__init__.py:700`) — a namespaced key-value store with optional vector search — but it is a memory primitive, not a workflow loader. The `langgraph-deepagents` template (template URL in `libs/cli/langgraph_cli/templates.py:11-14`) lives in the separate `langchain-ai/deep-agent-template` repo and is what would provide a skill-shaped bundle if needed.
- **Per-stack one-liners**:
  - **Skills**: Not provided — BYO. Closest primitive is `BaseStore` namespaces.
  - **Sub-agents**: Subgraphs only. Parallel via `Send` API. Inline runtime-generated configs not supported.
  - **Multi-tenancy**: `Runtime.context` propagation is excellent; LLM-supplied args for `InjectedToolArg` keys are stripped; tenant-scoped filters are first-class via `@auth.on` (server-side).
  - **Hooks**: `pre_model_hook` + `post_model_hook` from prebuilt; `wrap_tool_call` from ToolNode; `GraphCallbackHandler.on_interrupt`/`on_resume` for lifecycle.
  - **API**: Not in OSS repo — `langgraph_api` package required. SDK ships an HTTP client only (`libs/sdk-py`).
  - **Observability**: Token counts piggyback on LangChain `AIMessage.usage_metadata`. Cost: not provided — BYO.

## 1. Message Types & Event Taxonomy

LangGraph has **three taxonomies layered on top of each other**, and they don't share a vocabulary — this is the biggest cognitive load for a newcomer:

1. **State channels (graph layer)** — Every shared state key is a `BaseChannel` (`libs/langgraph/langgraph/channels/`). The reducer for that channel decides how concurrent writes are merged. For the prebuilt ReAct agent, there is one channel of interest: `messages: Annotated[Sequence[BaseMessage], add_messages]` (`chat_agent_executor.py:57-62`).
2. **Messages (content layer)** — Re-used from `langchain_core.messages`. Concrete types: `HumanMessage`, `AIMessage`, `AIMessageChunk` (streaming variant), `SystemMessage`, `ToolMessage`, `ToolMessageChunk`, `RemoveMessage` (a sentinel that the `add_messages` reducer interprets as "delete this id"; `RemoveMessage(id=REMOVE_ALL_MESSAGES)` wipes the channel — `libs/langgraph/langgraph/graph/message.py:33-39`). Each `AIMessage` carries `tool_calls: list[ToolCall]` with `id` for matching against subsequent `ToolMessage.tool_call_id`. Each `AIMessage` may carry `usage_metadata: UsageMetadata` with `input_tokens`/`output_tokens`/`total_tokens` plus optional `input_token_details` (`cache_creation`, `cache_read`, `audio`) and `output_token_details` (`reasoning`, `audio`).
3. **Stream parts (transport layer)** — When you call `graph.stream(input, stream_mode=...)`, what is yielded depends on `stream_mode`. Seven concrete `StreamPart` TypedDicts (`libs/langgraph/langgraph/types.py:252-355`):

| Stream mode | StreamPart type | Data shape | Purpose |
|---|---|---|---|
| `"values"` | `ValuesStreamPart` | full state after each step (`OutputT`) | replicate state snapshots |
| `"updates"` | `UpdatesStreamPart` | `{node_name: writes}` per step | observe what each node returned |
| `"messages"` | `MessagesStreamPart` | `(message, metadata)` per token | token-by-token streaming of LLM output |
| `"custom"` | `CustomStreamPart` | whatever was passed to `StreamWriter` | nodes can push arbitrary frames |
| `"checkpoints"` | `CheckpointStreamPart` | `CheckpointPayload` per checkpoint | observe persistence |
| `"tasks"` | `TasksStreamPart` | `TaskPayload` / `TaskResultPayload` | per-node start/finish |
| `"debug"` | `DebugStreamPart` | union of the above two | dev observability |

`stream_mode` can be a list — yielded tuples become `(mode, data)` or `(ns, mode, data)` if `subgraphs=True` (`pregel/main.py:2666-2691`).

There is also a **fourth, internal taxonomy** for the cloud SSE protocol (`libs/langgraph/langgraph/stream/_types.py:14-42`):

```python
class ProtocolEvent(TypedDict):
    type: Literal["event"]
    eventId: NotRequired[str]
    seq: NotRequired[int]
    method: str  # StreamMode value: "values", "messages", "custom", etc.
    params: _ProtocolEventParams
```

These wrap stream parts in an envelope with monotonic `seq` numbers — but consumers of `graph.stream()` directly never see them; they're for `langgraph_api`'s SSE output.

**Lifecycle events** are separate again (`libs/langgraph/langgraph/callbacks.py:42-79`):

```python
@dataclass(frozen=True)
class GraphInterruptEvent:
    run_id: UUID | None
    status: GraphLifecycleStatus  # "input"|"pending"|"done"|"interrupt_before"|"interrupt_after"|"out_of_steps"
    checkpoint_id: str
    checkpoint_ns: tuple[str, ...]
    interrupts: tuple[Interrupt, ...]

@dataclass(frozen=True)
class GraphResumeEvent:
    run_id: UUID | None
    status: GraphLifecycleStatus
    checkpoint_id: str
    checkpoint_ns: tuple[str, ...]
```

These are dispatched to `GraphCallbackHandler` subclasses you pass via `config["callbacks"]` (`callbacks.py:87-112`) — not to the stream.

**Canonical type-definition files**:
- `libs/langgraph/langgraph/types.py` (969 lines) — stream parts, `Interrupt`, `Command`, `Send`, `StateSnapshot`, `RetryPolicy`, `TimeoutPolicy`, `CachePolicy`, `Durability`
- `libs/langgraph/langgraph/callbacks.py` (395 lines) — `GraphCallbackHandler`, `GraphInterruptEvent`, `GraphResumeEvent`
- `libs/langgraph/langgraph/graph/message.py` (~330 lines) — `add_messages`, `MessagesState`, `REMOVE_ALL_MESSAGES`
- `libs/checkpoint/langgraph/checkpoint/base/__init__.py` — `Checkpoint`, `CheckpointTuple`, `CheckpointMetadata`, `BaseCheckpointSaver`

## 2. Agent Run Loop

### Architectural overview

The run loop is a **Pregel-style super-step iterator** (`libs/langgraph/langgraph/pregel/_loop.py:583-665`). Each super-step:

1. `tick()` calls `prepare_next_tasks` to figure out which nodes are runnable, based on which channels have been updated since the last super-step.
2. The runner executes those tasks (potentially in parallel via a thread/process executor or async gather).
3. After all tasks finish, `after_tick()` calls `apply_writes` to reduce per-task writes into the channels, then `_put_checkpoint({"source": "loop"})` persists.

A prebuilt `create_react_agent` wires three nodes — `agent` (LLM call), `tools` (parallel tool dispatch, one `Send` per tool call in v2), and optionally `pre_model_hook` / `post_model_hook`. One ReAct "iteration" (one model call + its tool calls) is **3 super-steps** in v2: `agent` runs, then `tools` runs (parallel `Send`s, all in the same super-step), then back to `agent`.

### Entrypoints

`CompiledStateGraph.stream` / `astream` / `invoke` / `ainvoke` (`pregel/main.py:2587-3279`, `3750+`):

```python
def stream(
    self,
    input: InputT | Command | None,
    config: RunnableConfig | None = None,
    *,
    context: ContextT | None = None,
    stream_mode: StreamMode | Sequence[StreamMode] | None = None,
    print_mode: StreamMode | Sequence[StreamMode] = (),
    output_keys: str | Sequence[str] | None = None,
    interrupt_before: All | Sequence[str] | None = None,
    interrupt_after: All | Sequence[str] | None = None,
    durability: Durability | None = None,           # "sync" | "async" | "exit"
    control: RunControl | None = None,              # cooperative drain handle
    subgraphs: bool = False,
    debug: bool | None = None,
    version: Literal["v1", "v2"] = "v1",
) -> Iterator[dict[str, Any] | Any]:
```

`config` carries `{"configurable": {"thread_id": "...", "checkpoint_ns": "...", "checkpoint_id": "..."}}` and `callbacks`. `context` is the typed `ContextT` from `StateGraph(context_schema=Context)`; resolved into `Runtime.context` and forwarded into every node and tool. `input` can be either the initial state or a `Command(resume=...)` for HITL resumption.

### Per-iteration behavior (one super-step)

`PregelLoop.tick()` (`_loop.py:583-665`):

```python
def tick(self) -> bool:
    if self.step > self.stop:
        self.status = "out_of_steps"
        return False
    self.tasks = prepare_next_tasks(...)
    if not self.tasks:
        self.status = "done"
        return False
    if self.control is not None and self.control.drain_requested:
        self.status = "draining"
        return False
    if self.interrupt_before and should_interrupt(...):
        self.status = "interrupt_before"
        raise GraphInterrupt()
    self._emit("tasks", map_debug_tasks, self.tasks.values())
    return True
```

And `after_tick()` (`_loop.py:667-705`):

```python
def after_tick(self) -> None:
    writes = [w for t in self.tasks.values() for w in t.writes]
    self.updated_channels = apply_writes(
        self.checkpoint, self.channels, self.tasks.values(),
        self.checkpointer_get_next_version, self.trigger_to_nodes,
    )
    # emit values output
    if not self.updated_channels.isdisjoint(...):
        self._emit("values", map_output_values, ...)
    self.checkpoint_pending_writes.clear()
    self.is_replaying = False
    self._put_checkpoint({"source": "loop"})   # ← per-super-step persistence
    if self.interrupt_after and should_interrupt(...):
        self.status = "interrupt_after"
        raise GraphInterrupt()
```

### Turn concept

There is **no explicit "turn" object**. A "turn" in ReAct semantics is roughly "one execution of the `agent` node + any tool dispatch it triggered" — but the graph layer doesn't name this. The closest first-class boundary is the super-step. Practically: one super-step where the runnable node is `agent` ≈ one LLM call ≈ one assistant message.

### Sessions / threads — what's stored

`thread_id` is the primary key for persistence (`libs/checkpoint/langgraph/checkpoint/base/__init__.py:176-207`). Per thread, the checkpointer stores:

- **Checkpoints** (one per super-step): `Checkpoint = {v, id, ts, channel_values, channel_versions, versions_seen, updated_channels}` plus `CheckpointMetadata` (`{source, step, parents, writes}`).
- **Pending writes**: per-task `(task_id, channel, value)` tuples, persisted via `put_writes` so they are durable BEFORE the next super-step starts and before `apply_writes` reduces them.
- **Channel values**: the actual state. For the prebuilt agent, this is just `{"messages": [...], "remaining_steps": N}`.

Backends: `InMemorySaver` (`checkpoint/memory`), `PostgresSaver` / `AsyncPostgresSaver` (`checkpoint-postgres`), `SqliteSaver` (`checkpoint-sqlite`). All implement `BaseCheckpointSaver` (`__init__.py:176-318`).

### Persistence timing — the critical detail

**Two persistence points per super-step, both gated on `durability`** (`_loop.py:175`, `Durability = Literal["sync", "async", "exit"]`):

1. **`put_writes` runs per-task as `_runner.commit()` is called** (`_runner.py:574-613`):
   ```python
   def commit(self, task: PregelExecutableTask, exception: BaseException | None) -> None:
       if isinstance(exception, GraphInterrupt):
           writes = [(INTERRUPT, exception.args[0])]
           if resumes := [w for w in task.writes if w[0] == RESUME]:
               writes.extend(resumes)
           self.put_writes()(task.id, writes)   # ← persists the interrupt
       ...
       else:
           if not task.writes:
               task.writes.append((NO_WRITES, None))
           self.put_writes()(task.id, task.writes)   # ← persists tool result
   ```
   And `put_writes` itself (`_loop.py:407-489`) submits the durable write to the checkpointer **immediately** when `durability != "exit"`:
   ```python
   if self.durability != "exit" and self.checkpointer_put_writes is not None:
       fut = self.submit(
           self.checkpointer_put_writes, config, writes_to_save, task_id, ...
       )
   ```

2. **`_put_checkpoint` runs once per super-step at the end** (`_loop.py:697`). Under `durability="async"` (the default), the next super-step starts while the previous checkpoint persists in the background; under `durability="sync"` the stream loop calls `loop._put_checkpoint_fut.result()` (`pregel/main.py:2956-2957`) to block before the next iteration.

**What this means for a ReAct turn under default `durability="async"`**:
- LLM streaming tokens flow through `StreamMessagesHandler.on_llm_new_token` (`pregel/_messages.py:150-163`) and are emitted on the stream channel — they do NOT persist mid-stream.
- When the `agent` node returns its `AIMessage`, that's a task write. `commit()` calls `put_writes` → durable.
- The `agent` super-step ends → `_put_checkpoint` → durable.
- Each tool call (v2) runs in its own `Send`-dispatched task in the `tools` super-step. As each tool finishes, its `commit()` calls `put_writes` → durable. **So if you have 4 parallel tool calls and the process crashes after 3 finished, on resume the 3 completed tool results are already in `checkpoint_pending_writes` and will not re-execute.**
- The `tools` super-step ends → `_put_checkpoint` → durable.

**This is the genuine durability story — and as far as the comparison goes, the only stack with it natively.** Mid-tool-call recovery (where a single tool's HTTP call mid-flight crashes) is NOT covered; the tool re-executes from scratch on resume. But mid-turn recovery (across the LLM call and the parallel tool fan-out) is robust.

### Event emission

A **per-call `SyncQueue` / async equivalent** (`pregel/main.py:2719`). The Pregel loop holds a `StreamProtocol(stream.put, stream_modes)` and nodes / callbacks push frames to it; the `stream()` generator yields from the queue between super-step ticks. Token-level streaming comes from `StreamMessagesHandler` (a LangChain callback handler) installed at run start (`pregel/main.py:2782-2798`):

```python
if "messages" in stream_modes:
    run_manager.inheritable_handlers.append(
        messages_handler_cls(stream.put, subgraphs, parent_ns=...)
    )
```

This handler's `on_llm_new_token` (`_messages.py:150-163`) emits `(ns, "messages", (chunk.message, meta))` for each token.

### HITL pause / resume

Two mechanisms, neither uses traditional "await a future":

**A. `interrupt()` from inside a node** — first-class HITL primitive (`libs/langgraph/langgraph/types.py:801-924`):

```python
def node(state: State):
    answer = interrupt("what is your age?")
    return {"human_value": answer}
```

The first call inside a node raises `GraphInterrupt(Interrupt(value=...))`. The runner's `commit()` catches it and writes the interrupt payload via `put_writes` (`_runner.py:585-591`). The loop then unwinds, `stream()` yields a final value frame, and the run ends with the interrupt visible on `StateSnapshot.interrupts`.

To resume, the client calls `stream(Command(resume="some answer"), config)` (or HTTP `POST /threads/{id}/runs/stream` with `{"command": {"resume": "..."}}`). The loop restarts from the **start of the node**, re-executing it — `interrupt()` now finds a previous resume value in the scratchpad and returns it instead of raising (`types.py:891-915`):

```python
if scratchpad.resume:
    if idx < len(scratchpad.resume):
        conf[CONFIG_KEY_SEND]([(RESUME, scratchpad.resume)])
        return scratchpad.resume[idx]
```

**Note**: "resumes from the start of the node, re-executing all logic" (`types.py:813-815`). So any side effects done before `interrupt()` happen twice. This is a documented sharp edge.

**B. `interrupt_before` / `interrupt_after`** — graph-level node-based interruption (`pregel/main.py:2674-2675`, `_loop.py:650-655`, `_loop.py:698-703`). The loop checks before/after running a node and raises `GraphInterrupt()` if the node is in the list. The client resumes by calling `stream(None, config)` with the same `thread_id`. State updates can also be applied via `graph.update_state(config, values)` between the interrupt and the resume — this is the "edit-and-resume" pattern used for HITL approve-with-modification.

### Interrupt / cancel an in-flight run

Two layers:

- **Per-process via `RunControl`** (`runtime.py:79-104`): `control.request_drain("reason")` flips a flag that `tick()` checks (`_loop.py:641-643`); the loop returns False with `status="draining"`, in-flight tasks complete, and `stream()` raises `GraphDrained`. Cooperative — does not abort an in-flight LLM call.
- **Async cancellation**: `asyncio.CancelledError` is caught in `_runner.commit()` (`_runner.py:579-583`) and persisted as an error write, so the task is marked done and the loop can finish the super-step. Cancelling the outer `astream()` coroutine cancels the inflight node tasks via asyncio.
- **Over HTTP** (when using LangGraph Server): `POST /threads/{thread_id}/runs/{run_id}/cancel?action=interrupt|rollback&wait=0|1` (`libs/sdk-py/langgraph_sdk/_async/runs.py:936-992`). `action=interrupt` writes an interrupt to the checkpoint (so the run is in `interrupted` state); `action=rollback` discards the run and reverts to the pre-run checkpoint.

## 3. Multi-tenancy & Arbitrary Context

**This is the highest-leverage answer for our use case, and LangGraph's story is the strongest in the comparison — but it splits across two layers.**

### Full run-loop input

```python
def stream(
    self,
    input: InputT | Command | None,                            # initial state OR resume command
    config: RunnableConfig | None = None,                       # configurable + callbacks
    *,
    context: ContextT | None = None,                            # ← typed harness context
    stream_mode: StreamMode | Sequence[StreamMode] | None = None,
    output_keys: str | Sequence[str] | None = None,
    interrupt_before: All | Sequence[str] | None = None,
    interrupt_after: All | Sequence[str] | None = None,
    durability: Durability | None = None,
    control: RunControl | None = None,
    subgraphs: bool = False,
    debug: bool | None = None,
    version: Literal["v1", "v2"] = "v1",
) -> Iterator[...]
```

The harness has three injection points beyond the input messages:

1. **`context: ContextT`** — typed dataclass / TypedDict declared on the graph via `StateGraph(state_schema=..., context_schema=Context)` (`graph/state.py:215-269`). This is the "run dependencies" channel: `tenant_id`, `db_conn`, `user_id`, `feature_flags`. Resolved into `Runtime.context` and frozen for the duration of the run (`runtime.py:198-201`):
   ```python
   context: ContextT = field(default=None)
   """Static context for the graph run, like `user_id`, `db_conn`, etc.
   Can also be thought of as 'run dependencies'."""
   ```
2. **`config["configurable"]`** — untyped dict-shaped escape hatch (`thread_id`, `checkpoint_ns`, custom keys). Still functional but discouraged for typed fields since v0.6 in favor of `context_schema`.
3. **`config["callbacks"]`** — a list of `BaseCallbackHandler` / `GraphCallbackHandler` instances. Captured by the run for the duration.

### Propagating context into a tool call

Two equivalent shapes for tool authors:

**A. Typed `runtime: ToolRuntime` parameter (recommended)** — `libs/prebuilt/langgraph/prebuilt/tool_node.py:1663-1730`:

```python
@dataclass
class ToolRuntime(_DirectlyInjectedToolArg, Generic[ContextT, StateT]):
    state: StateT
    context: ContextT
    config: RunnableConfig
    stream_writer: StreamWriter
    tool_call_id: str | None
    store: BaseStore | None
    tools: list[BaseTool] = field(default_factory=list)
    execution_info: ExecutionInfo | None = None
    server_info: ServerInfo | None = None

@tool
def search_videos(query: str, runtime: ToolRuntime) -> str:
    tenant_id = runtime.context.tenant_id   # ← injected from harness, NOT from LLM
    return our_db.search(tenant=tenant_id, q=query)
```

**B. `Annotated[..., InjectedState(...)]` / `Annotated[..., InjectedStore()]`** for tools that only need a slice (`tool_node.py:1753-1903`).

In both cases the corresponding parameter is **excluded from the JSON schema sent to the LLM** (`_DirectlyInjectedToolArg` / `InjectedToolArg` from langchain-core).

### Forcing tool arguments from the harness — **YES, with a guarantee**

The `ToolNode._inject_tool_args` method (`tool_node.py:1315-1430`) constructs the final `tool_call.args` by:

1. Injecting trusted values for declared `InjectedState`, `InjectedStore`, `ToolRuntime` parameters from the runtime.
2. **Then stripping any LLM-supplied values for those same keys before merging**:

```python
# Strip any caller-supplied values for injected args, then add
# back only trusted values. This prevents an LLM from forging
# hidden InjectedToolArg fields via ToolCall.args.
stripped_args = {
    k: v
    for k, v in tool_call_copy["args"].items()
    if k not in injected.all_injected_keys
}
tool_call_copy["args"] = {**stripped_args, **injected_args}
return tool_call_copy
```

So an LLM that hallucinates `{"query": "...", "tenant_id": "evil"}` against a tool with `tenant_id: Annotated[str, InjectedState("tenant_id")]` will have the `tenant_id` key silently overwritten with the harness value. **This is the cleanest "forced arg" mechanism in the comparison** — strict, declarative, type-checked, and impossible for the LLM to forge.

A second mechanism for arbitrary modification is the `wrap_tool_call` interceptor (`tool_node.py:1014-1067`):

```python
ToolCallWrapper = Callable[
    [ToolCallRequest, Callable[[ToolCallRequest], ToolMessage | Command]],
    ToolMessage | Command,
]

def my_wrapper(request: ToolCallRequest, execute: Callable) -> ToolMessage:
    # Override args before execution
    new_call = {**request.tool_call, "args": {**request.tool_call["args"], "tenant_id": "abc"}}
    return execute(request.override(tool_call=new_call))

tool_node = ToolNode(tools, wrap_tool_call=my_wrapper)
```

`ToolCallRequest` (`tool_node.py:132-199`) exposes `tool_call`, `tool` (the BaseTool — `None` if unregistered), `state`, and `runtime: ToolRuntime`. The `execute` callable can be invoked multiple times for retry, or zero times for cache short-circuit.

### Filtering visible tools per session / turn

Three mechanisms:

**A. `bind_tools` on the model upstream of `create_react_agent`** — the model is given a subset:
```python
model = init_chat_model("anthropic:claude-sonnet-4").bind_tools([tool_a, tool_b])
graph = create_react_agent(model, tools=[tool_a, tool_b, tool_c])  # c is dispatchable but not visible
```
(`chat_agent_executor.py:173-217`).

**B. Dynamic model selection** (`chat_agent_executor.py:325-356`, `598-618`): pass a callable for `model` that takes `(state, runtime)` and returns a `BaseChatModel` with different tools bound per turn:

```python
def select_model(state: AgentState, runtime: Runtime[Context]) -> ChatOpenAI:
    if runtime.context.tier == "free":
        return base_model.bind_tools([search_tool])
    return premium_model.bind_tools([search_tool, premium_tool])

graph = create_react_agent(select_model, tools=[search_tool, premium_tool])
```

The wired runtime is resolved before every LLM call (`chat_agent_executor.py:599-618`), so the toolset can change turn-by-turn based on `Runtime.context`.

**C. `wrap_tool_call` short-circuit** — if a tool *was* shown to the LLM but is forbidden for this tenant, the wrapper returns a synthetic ToolMessage without calling `execute()`.

There is no first-class "per-session registry of dynamically generated tools". Tools must be registered up-front at graph compile time (or via the dynamic-model `.bind_tools()` path).

### Resource scoping primitives (global / tenant / user)

**For state** — `BaseStore.put((namespace_tuple,), key, value)` (`libs/checkpoint/langgraph/store/base/__init__.py:700-820`). Namespace is a tuple of strings, so `("acme", "user-123", "preferences")` is a natural per-tenant-per-user namespace. Tools that take `runtime: ToolRuntime` can read `runtime.store` and prefix every namespace with `runtime.context.tenant_id`. The pattern is documented but the enforcement is convention — there is no built-in `scoped_store(tenant=...)` factory.

**For HTTP (LangGraph Server only)** — `@auth.on` decorators (`libs/sdk-py/langgraph_sdk/auth/__init__.py:13-302`):

```python
my_auth = Auth()

@my_auth.authenticate
async def authenticate(authorization: str) -> Auth.types.MinimalUserDict:
    user = await verify_token(authorization)
    return {"identity": user["id"], "permissions": user["permissions"]}

@my_auth.on.threads.create
async def allow_thread_create(ctx, value):
    metadata = value.setdefault("metadata", {})
    metadata["owner"] = ctx.user.identity   # stamp tenant on creation

@my_auth.on.threads.read
async def allow_thread_read(ctx, value) -> Auth.types.FilterType:
    return {"owner": ctx.user.identity}     # ← filter forces all queries

@my_auth.on.store
async def scope_store(ctx, value):
    ns = tuple(value["namespace"]) if value.get("namespace") else ()
    if not ns or ns[0] != ctx.user.identity:
        ns = (ctx.user.identity, *ns)
    value["namespace"] = ns
```

`FilterType` (`auth/types.py:58-109`) is a dict shape `{field: value | {"$eq": ...} | {"$contains": ...}}` that the server applies as a SQL filter. Resources covered: `threads`, `runs`, `assistants`, `crons`, `store`. Actions: `create`, `read`, `update`, `delete`, `search`, `create_run`, plus `put`/`get`/`list_namespaces` for `store`. Specific handlers take precedence over generic ones (`auth/__init__.py:96-106`).

**This is the single most powerful tenant-scoping primitive in the comparison** — but it only fires when the run is mediated by `langgraph_api`. For direct OSS graph execution, scoping is BYO via `Runtime.context` + `BaseStore` namespace conventions.

## 4. Hook Capabilities

### Hook surface, full enumeration

**At the prebuilt agent layer (`create_react_agent`)** — two hook points (`chat_agent_executor.py:296-297`, `876-963`):

| Hook | When it fires | Read | Mutate | Block | Branch |
|---|---|---|---|---|---|
| `pre_model_hook` | Before every `agent` (LLM) call | state | yes — emit `messages` (update channel) or `llm_input_messages` (one-shot) | no | no (always falls through to `agent`) |
| `post_model_hook` | After every `agent` call, before tool dispatch | state including last `AIMessage` | yes — emit any state update | yes (return without tool_calls → END) | yes — emit additional tool_calls, route to `tools`, or short-circuit |

`pre_model_hook` shape (`chat_agent_executor.py:398-410`):

```python
# At least one of `messages` or `llm_input_messages` MUST be provided
{
    "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), ...],   # UPDATES state
    "llm_input_messages": [...],                                  # one-shot, NOT persisted to state
    # ... other state keys
}
```

This is the **prompt-cache breakpoint / history-trim / system-prompt-injection slot**. The `llm_input_messages` form is the closest LangGraph has to "redact PII before sending to LLM but keep it in state".

`post_model_hook` is gated on `version="v2"` (`chat_agent_executor.py:430`). The `post_model_hook_router` (`chat_agent_executor.py:919-956`) inspects the resulting state and routes:
- If new `tool_calls` are pending → dispatch to `tools` via `Send`
- If the last message is a `ToolMessage` → loop back to `agent`
- If `response_format` is set → `generate_structured_response`
- Else → `END`

**Crucially**: a `post_model_hook` that appends new `AIMessage(tool_calls=[...])` entries can effectively "emit additional tool calls". The router will dispatch them. This is the LangGraph equivalent of Claude Agent SDK's `PostToolUse` with `additional_messages`.

**At the `ToolNode` layer** — one hook point per tool dispatch (`tool_node.py:743-771`, `1014-1067`):

| Hook | When it fires | Read | Mutate | Block | Branch / Re-execute |
|---|---|---|---|---|---|
| `wrap_tool_call` | Around every tool execution | `ToolCallRequest` (tool, args, state, runtime) | yes via `request.override(...)` | yes (return synthetic ToolMessage without `execute()`) | yes — call `execute()` zero, one, or many times |
| `awrap_tool_call` | Same, async lane | same | same | same | same |

```python
ToolCallWrapper = Callable[
    [ToolCallRequest, Callable[[ToolCallRequest], ToolMessage | Command]],
    ToolMessage | Command,
]
```

`execute()` can be called **multiple times with potentially modified requests** (`tool_node.py:206-217`): "The execute callable can be invoked multiple times for retry logic, with potentially modified requests each time. Each call to execute is independent and stateless." This is more flexible than Claude Agent SDK's `PreToolUse` / `PostToolUse` because the wrapper *owns* the retry loop instead of relying on event order.

**At the graph lifecycle layer** — `GraphCallbackHandler` (`libs/langgraph/langgraph/callbacks.py:87-112`):

| Hook | When it fires | Capability |
|---|---|---|
| `on_interrupt(GraphInterruptEvent)` | When graph pauses for interrupts | observe only — no return value affects flow |
| `on_resume(GraphResumeEvent)` | When graph resumes from checkpoint | observe only |

**At the LangChain callbacks layer** (inherited from `BaseCallbackHandler`, propagated via `config["callbacks"]`):

`on_chain_start`, `on_chain_end`, `on_chain_error`, `on_chat_model_start`, `on_llm_new_token`, `on_llm_end`, `on_llm_error`, `on_tool_start`, `on_tool_end`, `on_tool_error`, `on_text`, `on_retry`. All observe-only (the standard LangChain callback protocol).

### Scenario matrix

| Scenario | Supported? | How |
|---|---|---|
| Inject system messages at session start ("current date is X, tenant is Y") | YES | `pre_model_hook` returns `{"messages": [SystemMessage(...), ...]}` or `{"llm_input_messages": ...}` |
| Expand user input (slash commands, attachments) | YES | `pre_model_hook`, or a `pre_model_hook`-style node added by the user upstream of `agent` |
| Mutate messages list before each LLM call | YES | `pre_model_hook` — this is its documented purpose ("message trimming, summarization") |
| Mutate tool input before dispatch (inject tenantId server-side) | YES | Two paths: `InjectedState` / `ToolRuntime` annotations strip LLM values and inject harness values; `wrap_tool_call` for ad-hoc rewrites |
| Mutate tool result before it returns to LLM | YES | `wrap_tool_call` — call `execute()`, modify the resulting `ToolMessage`, return |
| Emit additional tool calls in response to a tool result | YES | `post_model_hook` appends an `AIMessage` with new `tool_calls`; the router dispatches them. Alternatively, `wrap_tool_call` can return a `Command(goto=Send("tools", ...))` to fan out from inside the wrapper. |

### Architectural diagram (ReAct prebuilt with all hooks active)

```text
graph.stream(input, config, context)
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PregelLoop super-step #N                                              │
│  ┌──────────────┐                                                       │
│  │ pre_model_   │  ◀── reads state; writes {messages | llm_input_msg}  │
│  │ hook (node)  │                                                       │
│  └──────┬───────┘                                                       │
│         ▼                                                                │
│  ┌──────────────┐                                                       │
│  │ agent (node) │  ◀── LLM call; tokens stream via StreamMessages-     │
│  │              │      Handler.on_llm_new_token → SyncQueue            │
│  │              │      writes AIMessage to messages channel             │
│  └──────┬───────┘                                                       │
│         ▼                                                                │
│  ┌──────────────┐                                                       │
│  │ post_model_  │  ◀── inspects last AIMessage; may add tool_calls,    │
│  │ hook (node)  │      block, or route                                  │
│  └──────┬───────┘                                                       │
└─────────┼──────────────────────────────────────────────────────────────┘
          │  (super-step boundary — `_put_checkpoint` fires)
          ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PregelLoop super-step #N+1 (only if tool_calls present)                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ tools (node, dispatched via Send per tool_call in v2)            │  │
│  │   ┌──────────────────────────────────────────────────────────┐   │  │
│  │   │ wrap_tool_call(request, execute)                          │   │  │
│  │   │   ▼                                                       │   │  │
│  │   │ _inject_tool_args(call, runtime, tool)                    │   │  │
│  │   │   - strips LLM-supplied keys for InjectedState/Store/    │   │  │
│  │   │     ToolRuntime params                                    │   │  │
│  │   │   - re-merges trusted runtime values                     │   │  │
│  │   │   ▼                                                       │   │  │
│  │   │ tool.invoke(injected_call, config)                        │   │  │
│  │   │   ▼                                                       │   │  │
│  │   │ ToolMessage                                               │   │  │
│  │   │ ◀── put_writes(task_id, [(messages, ToolMessage)])       │   │  │
│  │   │     DURABLE here (durability != "exit")                  │   │  │
│  │   └──────────────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└─────────┼──────────────────────────────────────────────────────────────┘
          │  (super-step boundary — `_put_checkpoint` fires)
          ▼
        loop back to pre_model_hook
```

`GraphCallbackHandler.on_interrupt` fires when any super-step raises `GraphInterrupt` (either via `interrupt()` inside a tool/node, or `interrupt_before`/`interrupt_after`); `on_resume` fires when the loop's `__enter__` finds a persisted parent checkpoint and resumes from it.

## 5. API Exposition

### Does the stack ship an HTTP server?

**Not in this repository.** This is a critical distinction. `libs/cli/langgraph_cli/cli.py:746-777` shows that `langgraph dev` imports `langgraph_api.cli.run_server`, which is a separate package:

```python
try:
    from langgraph_api.cli import run_server  # type: ignore
except ImportError:
    ...
    raise click.UsageError(
        "Required package 'langgraph-api' is not installed.\n"
        "Please install it with:\n\n"
        '    pip install -U "langgraph-cli[inmem]"'
    )
```

The `langgraph-api` (a.k.a. `langgraph-runtime-inmem` for dev, `langgraph-runtime-postgres` for prod) package is the actual HTTP server. **It is not in this monorepo and ships as closed-source / source-available code with a free-tier license**. The OSS surface in this repo ships:

- The graph runtime (`libs/langgraph`)
- The checkpointer interfaces and Postgres/Sqlite/in-mem implementations (`libs/checkpoint*`)
- The prebuilt agent factory (`libs/prebuilt`)
- The HTTP client SDK (`libs/sdk-py`, `libs/sdk-js`)
- The CLI that shells out to the closed-source server (`libs/cli`)

### Transport (assuming the server is in use)

**Server-Sent Events** (`libs/sdk-py/langgraph_sdk/sse.py:1-100+`). The client's `SSEDecoder` parses standard SSE: `event:`, `data:`, `id:`, `retry:` fields, decoded into `StreamPart(event, data, id)` NamedTuples (`schema.py:595-603`):

```python
class StreamPart(NamedTuple):
    event: str
    data: dict
    id: str | None = None
```

### Endpoints

From `libs/sdk-py/langgraph_sdk/_async/runs.py`:

**Start a run (streaming)**: `POST /threads/{thread_id}/runs/stream` (stateless: `POST /runs/stream`) — `_async/runs.py:339-360`. Body:

```jsonc
{
  "assistant_id": "agent",
  "input": {"messages": [{"role": "user", "content": "..."}]},
  "command": null,
  "config": {...},
  "context": {...},
  "metadata": {...},
  "stream_mode": ["values", "messages"],
  "stream_subgraphs": false,
  "stream_resumable": false,
  "interrupt_before": null,
  "interrupt_after": null,
  "multitask_strategy": "interrupt",
  "if_not_exists": "create",
  "on_disconnect": "cancel",
  "checkpoint": null,
  "checkpoint_id": null,
  "durability": "async"
}
```

**Background run**: `POST /threads/{thread_id}/runs` (or `/runs`) — `_async/runs.py:599`.

**Wait for run**: `POST /threads/{thread_id}/runs/wait` (or `/runs/wait`) — `_async/runs.py:824`.

**Join (block until done)**: `GET /threads/{thread_id}/runs/{run_id}/join` — `_async/runs.py:1084`.

**Join stream (re-attach)**: `GET /threads/{thread_id}/runs/{run_id}/stream?last_event_id=...` — `_async/runs.py:1138`. This is the **stream-resumption** endpoint that requires `stream_resumable: true` at run creation.

**Cancel**: `POST /threads/{thread_id}/runs/{run_id}/cancel?action=interrupt|rollback&wait=0|1` — `_async/runs.py:981-991`.

**Delete**: `DELETE /threads/{thread_id}/runs/{run_id}` — `_async/runs.py:1179`.

**State endpoints** (`_async/threads.py`):
- `GET /threads/{thread_id}/state` — current `ThreadState` snapshot
- `GET /threads/{thread_id}/state/{checkpoint_id}` — historical snapshot
- `POST /threads/{thread_id}/state` — `update_state` (apply patch as a synthetic node)

### Event frame format

The server emits SSE frames like:

```text
event: metadata
data: {"run_id":"1ef4a9b8-d7da-679a-a45a-872054341df2","attempt":1}

event: values
data: {"messages":[{"content":"how are you?","type":"human","id":"fe0a..."}]}

event: messages/partial
data: [{"content":"I'm","type":"AIMessageChunk","id":"run-..."},{"langgraph_node":"agent","langgraph_step":1}]

event: updates
data: {"agent":{"messages":[{"content":"I'm doing well","type":"ai","tool_calls":[],"usage_metadata":{"input_tokens":12,"output_tokens":7,"total_tokens":19}}]}}

event: end
data: null
```

(Reconstructed from `runs.py:299-301` example and the `StreamMode` taxonomy. Actual exact event names per stream mode: `values`, `updates`, `messages`, `messages/partial`, `messages/complete`, `checkpoints`, `tasks`, `tasks/result`, `custom`, `debug`, `error`, `metadata`, `end`, `feedback`.)

### HITL via API

To send an approval verdict, the client uses the **`command` field of the same `runs.stream` endpoint** (instead of `input`):

```jsonc
POST /threads/{thread_id}/runs/stream
{
  "assistant_id": "agent",
  "command": {
    "resume": "approved",
    "update": {...},
    "goto": null
  }
}
```

(`schema.py:890-915`). The server creates a new run on the existing thread that resumes from the persisted interrupt; the `interrupt()` call inside the node returns the `resume` value.

For multi-interrupt threads, `resume` can be a mapping of `interrupt_id -> value`. The state-edit pattern uses `POST /threads/{thread_id}/state` first to write edits, then `POST .../runs/stream` with `command: {"resume": ...}` to continue.

### Interrupt via API

**`POST /threads/{thread_id}/runs/{run_id}/cancel?action=interrupt`** (`runs.py:936-991`). `action=interrupt` halts the in-flight run and persists an interrupt marker; `action=rollback` discards the run entirely and reverts state.

Disconnecting the SSE stream does NOT cancel the run unless `on_disconnect: "cancel"` was set at creation (`runs.py:248-249`).

### Reconstructing tool-call state from the stream — explicit linkage

`AIMessage.tool_calls[*].id` is the universal correlation key. The stream emits:

1. An `AIMessage` (or `AIMessageChunk` sequence assembled) on the `messages` channel from the `agent` node, containing `tool_calls=[{"name":"...","args":{...},"id":"call_abc","type":"tool_call"}]`. This is matched on `type: "ai"` in the data.
2. After the `tools` super-step, one `ToolMessage` per tool with `tool_call_id="call_abc"`, on the `messages` channel from the `tools` node.

So linkage is **explicit and universal** — `tool_call_id` is required by every LLM provider for parallel tool calls and is preserved through the stream. The `_validate_chat_history` function (`chat_agent_executor.py:243-271`) actually raises if any `AIMessage.tool_calls` has no corresponding `ToolMessage` — the contract is enforced.

For `version="v2"` of the stream, the typed envelope (`StreamPartV2 = ValuesStreamPart | UpdatesStreamPart | MessagesStreamPart | ...`) makes the message-to-step linkage explicit via `metadata["langgraph_node"]`, `langgraph_step`, and `langgraph_checkpoint_ns`.

## 6. Sub-agents

### How are sub-agents represented?

LangGraph has **no first-class sub-agent / handoff primitive**. A sub-agent is just **a compiled `StateGraph` used as a node** in a parent graph. Two patterns:

**Pattern A: Subgraph as node** (canonical):
```python
research_agent = create_react_agent(model_a, tools=[search])
review_agent = create_react_agent(model_b, tools=[fact_check])

parent = (
    StateGraph(ParentState)
    .add_node("research", research_agent)
    .add_node("review", review_agent)
    .add_edge(START, "research")
    .add_edge("research", "review")
    .add_edge("review", END)
    .compile(checkpointer=checkpointer)
)
```

The parent's super-step that runs the `research` node will invoke the subgraph's full Pregel loop to completion (or until interrupt); the subgraph's checkpoints are namespaced under the parent's `checkpoint_ns` (`pregel/_loop.py:359-363`).

**Pattern B: Subgraph as tool** (agents-as-tools): wrap the subgraph in a `BaseTool` that invokes it. The supervisor LLM then "calls" sub-agents via tool calls. This is what `langgraph-supervisor` does. Not provided in OSS as a primitive.

### Configuration

Sub-agents are **statically registered at parent graph compile time**. There is no inline-per-call config and no runtime-generated config:
- Pattern A requires `parent.add_node("research", research_agent)` at build time
- Pattern B requires `parent.add_node("tools", ToolNode([research_as_tool]))` at build time

The parent LLM **cannot** dynamically construct a "new sub-agent with this system prompt and these tools" mid-run. The closest workaround is dynamic-model selection inside an existing sub-agent (`chat_agent_executor.py:325-356`).

### Output to parent

For Pattern A (subgraph-as-node), the sub-agent's final state is returned as the node's writes. The reducer on the parent's channels merges them. So if both parent and subgraph have a `messages` channel with `add_messages` reducer, the sub-agent's messages append to the parent's. If you want isolation, declare a different channel name in the subgraph (e.g. `subagent_messages`) and write only a summary to the parent's `messages`.

For Pattern B (subgraph-as-tool), output is a `ToolMessage.content` string — the sub-agent must serialize its result.

### Concurrency model

**Parallel fan-out via the `Send` API** (`libs/langgraph/langgraph/types.py:654-743`). A node's conditional edge can return `[Send("subagent", state_a), Send("subagent", state_b), ...]`; the runner dispatches all in the same super-step:

```python
def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

builder.add_conditional_edges(START, continue_to_jokes)
```

(`types.py:686-697`). The `tools` node in `create_react_agent v2` uses exactly this pattern for parallel tool execution (`chat_agent_executor.py:849-859`).

For Pattern B (subgraph-as-tool) under `create_react_agent v2`, multiple sub-agent tool calls naturally execute in parallel because each `tool_call` becomes its own `Send` to the `tools` node.

Serial sub-agents are the default for `add_edge(...)`-only graphs.

### Context isolation

**Not enforced — depends entirely on state schema design.**
- If the subgraph uses the **same `state_schema`** as the parent (or no schema), it sees the parent's full messages list. This is the "shared scratchpad" pattern.
- If the subgraph declares its **own `state_schema`**, the parent's state is invisible to the subgraph except via explicit channel mapping at the node boundary.

There is no equivalent of Claude Agent SDK's enforced "sub-agent gets a fresh context window" — that's an application-level design decision.

`Command(graph=Command.PARENT, update={...}, goto=...)` (`types.py:797-798`) lets a subgraph write to its parent's state explicitly — used for handoff-style flows where a sub-agent transitions control back to the supervisor.

## 7. Skills

**Skills (à la Claude Code's `SKILL.md`) are NOT a first-class concept in LangGraph.** A grep for `SKILL.md`, `loadSkills`, `class Skill` across the entire `libs/` tree returns zero matches.

The closest analogues:

1. **`BaseStore` + namespaced memory** (`libs/checkpoint/langgraph/store/base/__init__.py:700-820`). Engineers commonly use the store to hold workflow descriptions, RAG-indexed docs, or "playbooks" keyed by tenant/user namespace. A tool can `runtime.store.search(("playbooks", tenant_id), query=...)` to look up workflow guidance and inject it into the prompt. This is a memory pattern, not a skill loader.

2. **The `langgraph-deepagents` template** (referenced in `libs/cli/langgraph_cli/templates.py:11-14`):
   ```python
   "Deep Agent": {
       "description": "An opinionated deployment template for a Deep Agent.",
       "python": "https://github.com/langchain-ai/deep-agent-template/archive/refs/heads/main.zip",
       ...
   }
   ```
   This downloads a separate repo (`langchain-ai/deep-agent-template`, with sibling `langchain-ai/deepagents` SDK) that adds skill-shaped bundles, file-isolation, and a "compress" tool. **It is not in the LangGraph monorepo and is a separately-versioned package**. For Predict, adopting Deep Agents means adding a third-party dependency on top of LangGraph; the OSS LangGraph runtime studied here doesn't ship a SKILL.md loader.

3. **Prebuilt agent prompt strategies** — `pre_model_hook` can dynamically swap or expand the prompt based on state/context, which is what a "skill activation" would do, but without a markdown loader or registry.

**Verdict for the comparison matrix**: Skills support is **Not provided — BYO** for vanilla LangGraph; **Convention via add-on (`langgraph-deepagents`)** if you want the Claude Code experience.

## 8. Usage & Cost Monitoring

### Where token counts surface

LangGraph **delegates entirely to LangChain `AIMessage.usage_metadata`**. There is no LangGraph-native token aggregation. The `UsageMetadata` schema (visible in test snapshots like `libs/langgraph/tests/__snapshots__/test_large_cases.ambr`):

```python
class UsageMetadata(TypedDict):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_token_details: InputTokenDetails    # {audio, cache_creation, cache_read}
    output_token_details: OutputTokenDetails  # {audio, reasoning}
```

Each `AIMessage` in the `messages` channel carries this. To get per-turn usage, read the last `AIMessage` from the messages channel after a super-step. To get per-session usage, sum across all `AIMessage` instances on the thread (`graph.get_state(config).values["messages"]`).

### Per LLM call? Per turn? Per session? Per tenant?

| Granularity | Available? | How |
|---|---|---|
| Per LLM call | YES | `AIMessage.usage_metadata` after `agent` node returns; visible on `updates` stream |
| Per turn | YES | last `AIMessage` per super-step where `agent` ran |
| Per session (thread) | YES — BYO aggregation | sum `usage_metadata` across all `AIMessage` in `thread.state.values["messages"]` |
| Per tenant | NO — BYO | join thread metadata (`{"owner": tenant_id}`) with per-message usage in your own aggregator |

### Mechanism

**Events**: token metadata rides on the messages stream. `stream_mode="messages"` yields `(AIMessageChunk, metadata)` per token, and the final `AIMessage` carries the cumulative usage. `stream_mode="updates"` yields `{node_name: state_update}` which includes the full `AIMessage` with `usage_metadata`.

**Callbacks**: `BaseCallbackHandler.on_llm_end(response: LLMResult, ...)` (LangChain) receives `response.generations[0][0].message.usage_metadata`. This is the canonical hook for OTel exporters and per-turn cost trackers.

**Result objects**: `graph.invoke(...)` returns the final state; the final `AIMessage` carries its `usage_metadata`. There is no aggregated `{input_tokens: N, output_tokens: N}` on the return.

### Cost (USD)

**Not provided — BYO.** LangGraph does NOT compute cost from tokens. There is no built-in price table, no `total_cost_usd` field, no `max_budget_usd` cap. This is materially different from Claude Agent SDK which has both `total_cost_usd` on every `ResultMessage` and a `max_budget_usd` enforcement.

In practice, cost computation is offloaded to **LangSmith** (LangChain's hosted observability product). LangSmith's `UsageMetadata` extends LangChain's with cost fields ("LangSmith's `UsageMetadata` has additional fields to capture cost information used by the LangSmith platform" — quoted from langchain-core's UsageMetadata docstring visible in the test snapshot). For self-hosted OSS-only deployments, the engineering team must wire a price-table mapping `model_name + token_type -> $` into a custom callback handler.

### Canonical code path

```python
# Per-call usage from a callback handler
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

class UsageTracker(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs):
        for generation in response.generations[0]:
            msg = generation.message  # AIMessage
            usage = msg.usage_metadata  # UsageMetadata | None
            if usage:
                emit_otel_metric(
                    tokens_in=usage["input_tokens"],
                    tokens_out=usage["output_tokens"],
                    model=msg.response_metadata.get("model_name"),
                )

graph.invoke(input, config={"callbacks": [UsageTracker()]})
```

For per-session aggregation:

```python
state = graph.get_state(config)
total_in = sum(m.usage_metadata["input_tokens"]
               for m in state.values["messages"]
               if hasattr(m, "usage_metadata") and m.usage_metadata)
```

## Architectural diagram

```text
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              LangGraph Platform (cloud / self-hosted)             │
│                                                                                   │
│  HTTP Client (libs/sdk-py)                  langgraph_api (CLOSED SOURCE)         │
│  ──────────────────────                     ───────────────────────────           │
│  POST /runs/stream      ─SSE──▶  ┌──────────────────────────────────────────┐    │
│  POST /runs/{id}/cancel          │  HTTP layer (Starlette / Uvicorn)         │    │
│  POST /threads/{id}/state        │  Auth handlers: @my_auth.on.threads.*     │    │
│  GET  /threads/{id}/state        │  Auth handlers: @my_auth.on.store         │    │
│                                  │  Multitask strategies, webhooks, crons    │    │
│                                  │  Run queue, background runner             │    │
│                                  └────────────┬─────────────────────────────┘    │
└───────────────────────────────────────────────┼───────────────────────────────────┘
                                                │
                                                │  invokes
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                          LangGraph OSS runtime (libs/langgraph)                   │
│                                                                                   │
│  CompiledStateGraph.stream(input, config, context=ContextT, durability=...)       │
│      ▼                                                                            │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  PregelLoop (pregel/_loop.py)                                              │  │
│  │  ┌────────────────────────────────────────────────────────────────────┐    │  │
│  │  │ while tick():                                                       │    │  │
│  │  │   prepare_next_tasks → channels diff → runnable nodes              │    │  │
│  │  │   PregelRunner.tick(): execute tasks in parallel                    │    │  │
│  │  │     each task.commit() → put_writes() ←─ DURABLE PER TASK         │    │  │
│  │  │   after_tick(): apply_writes → _put_checkpoint() ←─ DURABLE PER   │    │  │
│  │  │                                                       SUPER-STEP   │    │  │
│  │  │   if interrupt_before/after: raise GraphInterrupt                  │    │  │
│  │  └────────────────────────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  Nodes:                                                                           │
│    agent (LLM)         pre_model_hook                                             │
│       ▲                       ▲                                                   │
│       │                       │  - prompt cache breakpoints                       │
│       │                       │  - history trim                                   │
│       │                       │  - llm_input_messages (one-shot)                 │
│       │                                                                           │
│    tools (Send-fan-out per tool_call in v2)                                       │
│       │                                                                           │
│       ▼                                                                           │
│    ToolNode (libs/prebuilt/langgraph/prebuilt/tool_node.py)                      │
│       │  wrap_tool_call(request, execute)  ◀── retry / cache / args override     │
│       │  _inject_tool_args() ◀── strips LLM args for InjectedState keys           │
│       │  tool.invoke(injected_args, config)                                       │
│       │                                                                           │
│       └─▶ Runtime[ContextT] (runtime.py)                                          │
│             - context: ContextT  (tenant_id, db_conn, user_id)                    │
│             - store: BaseStore  (namespaced KV)                                   │
│             - execution_info: ExecutionInfo (checkpoint_id, thread_id, run_id)    │
│             - server_info: ServerInfo (assistant_id, graph_id, user)              │
│                                                                                   │
│  Persistence:                                                                     │
│    BaseCheckpointSaver (libs/checkpoint)                                          │
│      ├─ InMemorySaver                                                             │
│      ├─ PostgresSaver / AsyncPostgresSaver (libs/checkpoint-postgres)            │
│      └─ SqliteSaver (libs/checkpoint-sqlite)                                      │
│                                                                                   │
│  Stream output:                                                                   │
│    SyncQueue / asyncio.Queue ◀── StreamMessagesHandler (on_llm_new_token)        │
│                              ◀── _emit("values"|"updates"|"checkpoints"|"tasks")  │
│                              ◀── StreamWriter (custom)                            │
└───────────────────────────────────────────────────────────────────────────────────┘
```

## Appendix — Files worth reading first

For a future engineer who needs to deep-dive themselves:

- `libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py` — the ReAct agent factory; start at `create_react_agent` (`:278`) and follow the conditional-edges wiring.
- `libs/prebuilt/langgraph/prebuilt/tool_node.py` — tool dispatch, `_inject_tool_args` (`:1315`) for the LLM-arg-stripping guarantee, `wrap_tool_call` (`:743-771`) for the interceptor.
- `libs/langgraph/langgraph/runtime.py` — `Runtime[ContextT]`, `ExecutionInfo`, `ServerInfo`, `RunControl`. This is the type you read from inside tools to get tenant context.
- `libs/langgraph/langgraph/pregel/_loop.py` — super-step machinery; `tick()` (`:583`), `after_tick()` (`:667`), `put_writes()` (`:407`), `_put_checkpoint` (`:1055`) — the persistence-timing answers live here.
- `libs/langgraph/langgraph/pregel/_runner.py` — task scheduling and `commit()` (`:574`) — this is where per-task durability fires.
- `libs/langgraph/langgraph/types.py` — `StreamMode`, `StreamPart` variants, `Interrupt`, `Command`, `Send`, `Durability`. Canonical for the API contract.
- `libs/langgraph/langgraph/graph/state.py` — `StateGraph` builder, `add_node`/`add_edge`/`add_conditional_edges`/`compile`.
- `libs/checkpoint/langgraph/checkpoint/base/__init__.py` — `BaseCheckpointSaver`, `Checkpoint`, `CheckpointTuple`. Implement this to plug a custom persistence backend.
- `libs/checkpoint/langgraph/store/base/__init__.py` — `BaseStore`. Namespaced KV with optional vector search; the closest thing to "skills storage".
- `libs/sdk-py/langgraph_sdk/auth/__init__.py` and `auth/types.py` — `@auth.on.<resource>.<action>` decorators, `FilterType`, `AuthContext`. Multi-tenancy at the HTTP layer.
- `libs/sdk-py/langgraph_sdk/_async/runs.py` — HTTP client; canonical reference for `/threads/.../runs/stream`, `/cancel`, `/join_stream` endpoint shapes.
- `libs/cli/langgraph_cli/cli.py` — `dev` command (`:732`) shows the closed-source `langgraph_api` import; useful to verify the OSS/server split.
