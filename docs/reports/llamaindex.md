# LlamaIndex Python — Benchmark Analysis

> **Repo**: https://github.com/run-llama/llama_index
> **Commit analysed**: 23bd65aaf79ffed587af35f325738b1580b35dea
> **Branch**: main
> **Framework path**: frameworks/llamaindex
> **Analysed on**: 2026-05-19

## TL;DR

- ⭐ **What is this stack architecturally?** A large Python monorepo (`llama-index-core` + ~300 separately-versioned integration packages on PyPI). The agent piece is `llama-index-core/agent/workflow/`, which is a thin layer of step-decorated classes built on top of the external **`workflows`** package (`pip install llama-index-workflows>=2.14,<3`). Agents are event-driven workflows: `FunctionAgent` / `ReActAgent` / `AgentWorkflow` are subclasses of `Workflow` whose `@step` methods emit/consume events through an in-memory queue. RAG/ingestion is the dominant historical use case but is not relevant for this benchmark.
- **Ecosystem**: Python (>=3.10).
- Open-source MIT, owned by LlamaIndex Inc. (Jerry Liu); commercial offerings exist (LlamaCloud/LlamaParse, LlamaAgents managed runtime).
- Core is v0.14.22 (pyproject.toml:37); the framework dates to late 2022; APIs are stable but the **agent layer was rebuilt in 2025** when workflow primitives were spun out into the `workflows` package — `llama-index-core/llama_index/core/workflow/workflow.py:1` is now a one-line re-export.
- The agent loop runs **in your Python process** as an asyncio coroutine. No subprocess, no separate runtime.
- Strongest fit for our use case: the event-graph workflow runtime gives clean hand-offs, parallel sub-agents (`AgentWorkflow`), HITL via `wait_for_event`, and `Context.to_dict / from_dict` for durable resume. Tools can accept the `Context` as a typed parameter, allowing first-class tenant/context propagation.
- Weakest gap: **no resource manager, no skill concept** in the Anthropic sense, **no first-party HTTP server** for agents (that lives in the separate `llama_deploy` repo), **no USD cost roll-up**, **no per-tenant budget enforcement**.
- Most surprising: the `Context` object exposes a `wait_for_event(EventType, requirements=…, waiter_id=…)` primitive that pauses a step until the matching event is sent back — used for HITL approvals — and the whole `Context` (with running state) is serializable to JSON.
- One-line verdicts:
  - sessions/persistence: BYO (Context.to_dict + serializer); 1st-party `Memory` class with SQLAlchemy backing.
  - skills: Not provided — BYO.
  - resource manager: Not provided — BYO.
  - sub-agents: First-class via `AgentWorkflow` + `can_handoff_to`, or "agents-as-tools" pattern.
  - multi-tenancy: BYO; `Context` and `FunctionTool.partial_params` give the building blocks.
  - hooks: No hook system; closest equivalents are workflow steps you override and `FunctionTool` `callback=` / `async_callback=`.
  - API: Library-only; production deploys go through external `llama_deploy` project or your own FastAPI.
  - observability: 1st-party `llama-index-instrumentation` dispatcher + OTel exporter package; ~25 callback integrations (Arize, Langfuse, Opik, Phoenix…).
- Production-readiness verdict for multi-tenant server-side deployment: **medium**. Core primitives are present and battle-tested, but you build the multi-tenant glue (sessions store, tenant context propagation, skill catalog, HITL endpoints) yourself. `llama_deploy` is an option for the runtime piece but is a separate project and not studied in this report.

## 0. General

### 0.1 What is this stack?

A Python library + a constellation of integration packages. The agent layer is built on the **Workflow** abstraction (`Workflow` class + `@step` decorator + `Event`/`Context`/`Handler` primitives). `Workflow` itself was extracted from `llama-index-core` into a separate `llama-index-workflows` PyPI package — `llama-index-core` re-exports it (`llama-index-core/llama_index/core/workflow/workflow.py:1`).

### 0.2 Ecosystem

**Python** (>=3.10, `<4.0`) — `llama-index-core/pyproject.toml:40`. A separate TypeScript port (`LlamaIndex.TS`) exists in a sibling repo but is out of scope here.

### 0.3 Project status & governance

- **License**: MIT (`LICENSE:1`, `pyproject.toml:57`).
- **Owner/maintainers**: LlamaIndex Inc., founded by Jerry Liu. Maintainers listed in `pyproject.toml:58-65` (Jerry Liu, Logan Markewich, Simon Suo, Andrei Fajardo, Haotian Zhang, Sourabh Desai).
- **Commercial backing**: Yes — LlamaCloud / LlamaParse / LlamaExtract / LlamaAgents (managed) are paid offerings; the OSS framework remains free.
- **Support model**: GitHub issues, Discord (https://discord.gg/dGcwcsnxhU), paid LlamaCloud support contracts.

### 0.4 Project maturity / age

- **Initial public release**: November 2022 (originally "GPT Index"). Renamed to LlamaIndex shortly after.
- **Current major version**: `llama-index-core` 0.14.22 (`llama-index-core/pyproject.toml:37`).
- **Stability**: Stable. Most APIs are non-experimental. The agent layer was substantially rewritten in 2025 to live on top of `workflows` and the `Memory` API is marked as the replacement for deprecated `ChatMemoryBuffer` / `SimpleComposableMemory` (`llama-index-core/llama_index/core/memory/__init__.py:21-25`).

### 0.5 Adoption & community signal

GitHub numbers captured 2026-05-19:
- Stars: ~39k+ (one of the largest in the agent/RAG space; exact figure not in-repo).
- Forks: ~6k+.
- Contributors: ~1000+ (badge in `README.md:5`).
- Commit cadence: Multiple commits per day; `CHANGELOG.md:5-30` shows mass version-bump rounds every 1–4 weeks across hundreds of packages.
- Issue/PR activity: Very high; the `CHANGELOG.md` references PR numbers in the 21,000+ range.
- Discord: Active (link in README badge row).

### 0.6 Ecosystem fit

- **Packages**: `llama-index` (starter, `pyproject.toml:69`), `llama-index-core` (lean), and ~300 `llama-index-<category>-<provider>` integration packages on PyPI.
- **LLM integrations**: 104 directories under `llama-index-integrations/llms/` (Anthropic, OpenAI, Bedrock, Vertex, Azure, Cohere, Mistral, Groq, Together, vLLM, Ollama, etc.).
- **Used mostly as**: A library imported into your own service; not a CLI, not a hosted platform (LlamaCloud is for parsing/ingestion, not for serving your agents).

### 0.7 Documentation depth & cross-team contributor accessibility

- Docs language: Markdown (Starlight static site). Source under `docs/src/content/docs/framework/`.
- Depth: Extensive — Concepts, Getting Started, Understanding (Agent, RAG, Workflows, Evaluation, Tracing, Deployment), Module Guides per provider, Use Cases. The "Understanding Agent" subdirectory is 1133 lines across 7 files.
- Non-engineer accessibility: Low. Pages are code-walkthroughs in Python; no GUI or markdown-file authoring model.

### 0.8 Documentation entry points ⭐

- Official docs: https://developers.llamaindex.ai/python/framework/
- Quickstart: https://developers.llamaindex.ai/python/framework/getting_started/starter_example
- API reference: https://developers.llamaindex.ai/python/framework/api_reference (generated from docstrings)
- Hosting / deployment: https://docs.llamaindex.ai (LlamaCloud) + https://github.com/run-llama/llama_deploy (for agent serving)
- Examples: https://github.com/run-llama/llama_index/tree/main/docs/src/content/docs/framework/examples
- Changelog: `CHANGELOG.md` at repo root; rendered at https://developers.llamaindex.ai/python/framework/CHANGELOG
- GitHub Releases: https://github.com/run-llama/llama_index/releases
- Issues: https://github.com/run-llama/llama_index/issues
- Discord: https://discord.gg/dGcwcsnxhU
- LlamaHub (community packs/tools): https://llamahub.ai/
- Twitter/X: https://x.com/llama_index

## 1. High Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Your Python process (asyncio loop)                         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Workflow (event-graph runtime, from `workflows`)   │    │
│  │   ├─ Context (KV store + event queue)               │    │
│  │   ├─ @step methods (init_run → setup_agent →        │    │
│  │   │   run_agent_step → parse_agent_output →         │    │
│  │   │   call_tool → aggregate_tool_results …)         │    │
│  │   └─ AgentWorkflow / FunctionAgent / ReActAgent     │    │
│  └─────────────────────────────────────────────────────┘    │
│           │                  │                              │
│           ▼                  ▼                              │
│   ┌──────────────┐    ┌──────────────┐                      │
│   │ LLM provider │    │ Tool exec    │                      │
│   │ (openai/anth │    │ (Python fn,  │                      │
│   │  /bedrock…)  │    │  MCP, RAG)   │                      │
│   └──────────────┘    └──────────────┘                      │
│                                                             │
│   ┌──────────────────────────────────────────────────┐      │
│   │  Memory (SQLAlchemyChatStore — sqlite/pg/mysql)  │      │
│   └──────────────────────────────────────────────────┘      │
│                                                             │
│   ┌──────────────────────────────────────────────────┐      │
│   │  llama_index_instrumentation dispatcher          │      │
│   │   → OTel / Arize / Langfuse / Opik / Phoenix …   │      │
│   └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘

   For HTTP: BYO (FastAPI/Flask) OR external `llama_deploy` repo.
```

### 1.1 Where does the agent loop actually execute?

**In your Python process**, as an asyncio coroutine. There is no bundled binary, no subprocess, no vendor cloud round-trip. The `FunctionAgent.run(...)` call resolves into `Workflow.run(...)` which schedules `@step` methods on the running asyncio event loop. See `llama-index-core/llama_index/core/agent/workflow/base_agent.py:382-435` (the `init_run`, `setup_agent`, `run_agent_step` steps) and `llama-index-core/llama_index/core/agent/workflow/base_agent.py:759-813` (the `run()` entrypoint).

### 1.2 Runtime dependencies

- Python 3.10+ (`llama-index-core/pyproject.toml:40`).
- Core deps: `SQLAlchemy[asyncio]`, `httpx`, `pydantic>=2.8`, `tiktoken`, `aiohttp`, `nltk`, `tenacity`, `wrapt`, `banks`, `aiosqlite`, **`llama-index-workflows>=2.14,<3`** (`llama-index-core/pyproject.toml:57-87`).
- No bundled binaries. Tokenizer is `tiktoken`.
- Required infrastructure services: none for in-process use; only the LLM provider HTTP endpoint. The default `Memory` uses SQLite via `aiosqlite`; production deploys typically swap for Postgres (any SQLAlchemy-supported DB).
- Required vendor services: none (LlamaCloud is optional and for parsing/ingestion, not agent serving).
- Optional: each LLM/store/tool integration adds its own provider SDK dependency.

### 1.3 Recommended deployment topology

Not opinionated. The official "deployment" tutorial is a single stub: `docs/src/content/docs/framework/understanding/deployment/deployment.md:1-6` literally says `TODO`. The vendor's recommended path for production multi-agent serving is the separate **`llama_deploy`** project (`docs/src/content/docs/framework/module_guides/llama_deploy/README.txt:1-2` — "Documentation content will be pulled from https://github.com/run-llama/llama_deploy"), which provides a microservice / message-queue runtime around `Workflow`. That project is out of this report's scope.

### 1.4 Cold-start cost & instance footprint

Pure-Python import overhead (`llama-index-core` pulls in SQLAlchemy, pydantic, tiktoken, nltk, banks, httpx, aiohttp — non-trivial). No published baseline RAM figure. Cold start is dominated by your LLM SDK warm-up, not the framework.

### 1.5 Vendor lock-in

- **LLM-provider lock-in**: None — pluggable `LLM` abstraction with 104 implementations. 🟢
- **Hosting lock-in**: None for the OSS framework. 🟢 (`llama_deploy` is OSS too; LlamaCloud is for parse/ingest, not serving.)
- **Eval-platform lock-in**: None — bring your own (LangSmith, Arize, Langfuse, Opik, Phoenix all have official integrations under `llama-index-integrations/callbacks/`). 🟢

### 1.6 Framework weight / footprint

Heavy ecosystem (300+ integration packages) but core is modular — you install only what you need. The agent layer itself (`llama-index-core/llama_index/core/agent/workflow/`) is ~2000 lines:

```
36   __init__.py
57   agent_context.py
825  base_agent.py
400  codeact_agent.py
196  function_agent.py
888  multi_agent_workflow.py
19   prompts.py
330  react_agent.py
146  workflow_events.py
```

### 1.7 Release-history signal

- `CHANGELOG.md` has a single combined log across all packages, regenerated regularly. Recent (`CHANGELOG.md:5-77`): `llama-index-core 0.14.22` (2026-05-14) includes "fix(instrumentation): let SparseEmbeddingStartEvent inherit EmbeddingStartEvent" (#21119), "feat(core): Multimodal synthesis" (#21374), "fix: propagate contextvars in sync_to_async for FunctionTool" (#21558).
- Earlier in the year (`CHANGELOG.md:3400`): "feat: support custom span processor; refactor: use llama-index-instrumentation instead of llama-index-core" (#20732) — the instrumentation extraction.
- The agent layer's most decision-relevant breaking change was the move to the external `workflows` package and the deprecation of the older `OpenAIAgent` / `ReActAgent.from_tools` flavour in favour of `FunctionAgent` / `AgentWorkflow`.

## 2. Agent Loop

### 2.1 Run loop entrypoint(s)

`BaseWorkflowAgent.run(...)` returns a `WorkflowHandler` (an awaitable that's also an async iterator over events):

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:740-758
def run(
    self,
    user_msg: Optional[Union[str, ChatMessage]] = None,
    chat_history: Optional[List[ChatMessage]] = None,
    memory: Optional[BaseMemory] = None,
    ctx: Optional[Context] = None,
    max_iterations: Optional[int] = None,
    early_stopping_method: Optional[Literal["force", "generate"]] = None,
    start_event: Optional[AgentWorkflowStartEvent] = None,
    **kwargs: Any,
) -> WorkflowHandler: ...
```

Usage:

```python
handler = workflow.run(user_msg="hello")        # returns WorkflowHandler immediately
async for event in handler.stream_events():     # iterate events
    ...
final = await handler                            # await for terminal result
```

The "loop" inside is the workflow event graph: `init_run → setup_agent → run_agent_step → parse_agent_output → (call_tool* → aggregate_tool_results) → setup_agent → … → StopEvent`. Each `@step` method emits one event and is dispatched by the upstream `workflows` runtime when its input event type is produced.

### 2.2 Per-iteration behavior

One "iteration" in `AgentWorkflow` is a single LLM call followed by N parallel tool calls. Decoration of the steps (`@step` in `base_agent.py:382, 436, 464, 519, 623, 660`):

1. `init_run(AgentWorkflowStartEvent) -> AgentInput` — load memory, set up `state`, emit user message.
2. `setup_agent(AgentInput) -> AgentSetup` — prepend system prompt; format state into the last user message via `state_prompt`.
3. `run_agent_step(AgentSetup) -> AgentOutput` — call `agent.take_step(...)` → LLM streaming chat with tools.
4. `parse_agent_output(AgentOutput) -> {StopEvent | AgentInput | ToolCall × N | None}` — increment iteration counter; if `tool_calls` is empty → finalize and stop; else emit one `ToolCall` event per parallel call.
5. `call_tool(ToolCall) -> ToolCallResult` — dispatch a single tool (one of N) in parallel.
6. `aggregate_tool_results(ToolCallResult) -> {AgentInput | StopEvent | None}` — `ctx.collect_events(ev, expected=[ToolCallResult]*N)` fans-in N parallel calls, writes them to memory, and goes back to `setup_agent`.

### 2.3 ReAct loop

Built in. `ReActAgent` (`llama-index-core/llama_index/core/agent/workflow/react_agent.py:38`) overrides `take_step` to do "Thought / Action / Observation" parsing for LLMs without native tool calling. It uses `ReActChatFormatter` and `ReActOutputParser` from `llama-index-core/llama_index/core/agent/react/`. `FunctionAgent` uses the LLM's native function-calling instead.

### 2.4 Tool dispatch + result handling

`parse_agent_output` emits one `ToolCall` event per generated tool call. The workflow runtime fans these out to parallel invocations of `call_tool`:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:610-619
await ctx.store.set("num_tool_calls", len(ev.tool_calls))

for tool_call in ev.tool_calls:
    ctx.send_event(
        ToolCall(
            tool_name=tool_call.tool_name,
            tool_kwargs=tool_call.tool_kwargs,
            tool_id=tool_call.tool_id,
        )
    )
```

`call_tool` resolves the tool by name from `self.get_tools(...)` and calls `_call_tool`. If the tool is a `FunctionTool` that declares a `Context` parameter, the workflow context is injected:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:346-380
async def _call_tool(self, ctx, tool, tool_input):
    if (isinstance(tool, FunctionTool)
        and tool.requires_context
        and tool.ctx_param_name is not None):
        new_tool_input = {**tool_input}
        new_tool_input[tool.ctx_param_name] = ctx
        tool_output = await tool.acall(**new_tool_input)
    else:
        tool_output = await tool.acall(**tool_input)
```

Then `aggregate_tool_results` does the fan-in via `ctx.collect_events(...)` (`base_agent.py:669-671`).

### 2.5 Explicit turn concept

A "turn" is "one LLM call → N parallel tool calls → fan-in → next LLM call". The framework caps the count via `max_iterations` (default 20, `base_agent.py:66`) and surfaces an `early_stopping_method` choice of `"force"` (raise `WorkflowRuntimeError`) or `"generate"` (one final LLM call with a stopping prompt) — see `base_agent.py:519-541`.

### 2.6 Event emission mechanism (in-process)

Two complementary mechanisms inside one workflow:

1. **Step-routing events**: emitted via `return` from a `@step` method (or `ctx.send_event(ev)` to fan out). The workflow runtime delivers them to whatever step matches the type signature. The fan-in primitive is `ctx.collect_events(ev, expected=[T, T, T])`.
2. **Stream events to consumer**: `ctx.write_event_to_stream(event)` puts the event onto the handler's external stream. `handler.stream_events()` is an async iterator over these:

```python
# example from docs/src/content/docs/framework/understanding/agent/streaming.mdx:54-60
handler = workflow.run(user_msg="What's the weather like in San Francisco?")

async for event in handler.stream_events():
    if isinstance(event, AgentStream):
        print(event.delta, end="", flush=True)
```

The `_get_llm_response` method writes `AgentStream` events as tokens arrive: `base_agent.py:329-339`.

## 3. Message & Event Taxonomy

### 3.1 Message layers

LlamaIndex distinguishes:

- **`ChatMessage`** — provider-agnostic LLM message (the wire format toward the LLM). Defined in `llama-index-core/llama_index/core/base/llms/types.py:1159`.
- **`Event` subclasses** — internal workflow events (the wire format between `@step` methods, and on the stream to the consumer).
- **`ChatResponse`** — the LLM's reply object, with `.message: ChatMessage`, `.raw`, `.delta`, `.additional_kwargs`.

There is no separate "UI message" type; consumers consume `Event`s directly (or a sub-selection like `AgentStream`).

### 3.2 Concrete message types

| Type | Purpose |
|---|---|
| `ChatMessage` | LLM input/output message (role, content blocks, tool_call_id) |
| `ContentBlock` (TextBlock, ImageBlock, AudioBlock, VideoBlock, DocumentBlock, CitableBlock, CitationBlock, CachePoint, ThinkingBlock, ToolCallBlock) | Multimodal pieces of a `ChatMessage` |
| `AgentWorkflowStartEvent` | Run-loop start event (`user_msg`, `chat_history`, `memory`, `max_iterations`, …) |
| `AgentInput` | Messages being routed to an agent |
| `AgentSetup` | Messages plus system prompt, ready for LLM call |
| `AgentOutput` | LLM reply (response message + tool_calls + structured_response) |
| `AgentStream` | Per-token streaming delta |
| `AgentStreamStructuredOutput` | Streaming structured output |
| `ToolCall` | A single tool invocation (tool_name, tool_kwargs, tool_id) |
| `ToolCallResult` | The result of one tool invocation (tool_output, return_direct) |
| `InputRequiredEvent` | HITL — workflow paused, awaiting input |
| `HumanResponseEvent` | HITL — caller's reply to the pause |
| `StartEvent` / `StopEvent` | Workflow lifecycle endpoints |

### 3.3 Messages vs. events

Same iterator. The consumer-facing stream is a stream of `Event`s; messages (`ChatMessage`) are carried inside specific events (`AgentInput.input`, `AgentOutput.response`, `ToolCallResult.tool_output`).

### 3.4 Event categories

- **Stream events**: `AgentStream`, `AgentStreamStructuredOutput` (token deltas).
- **Turn events**: `AgentInput`, `AgentSetup`, `AgentOutput`.
- **Tool events**: `ToolCall`, `ToolCallResult`.
- **HITL events**: `InputRequiredEvent`, `HumanResponseEvent`.
- **Lifecycle events**: `StartEvent`, `StopEvent`.
- **Sub-agent events**: surfaced via `current_agent_name` field on `AgentInput`/`AgentOutput`/`AgentStream`, not a separate type.
- **Hook events**: Not a separate concept (no hook system).

### 3.5 Canonical type-definition file(s)

- Agent workflow events: `llama-index-core/llama_index/core/agent/workflow/workflow_events.py:1-147`.
- Generic workflow events (re-exported from `workflows` package): `llama-index-core/llama_index/core/workflow/events.py:1-8`.
- `ChatMessage` and `ContentBlock`: `llama-index-core/llama_index/core/base/llms/types.py:1159`.
- `ToolCall` / `ToolOutput` / `ToolMetadata`: `llama-index-core/llama_index/core/tools/types.py:23-114`.

### 3.6 Live agentic event stream taxonomy

Sample frames consumers receive from `handler.stream_events()`:

```python
# Token stream
AgentStream(
    delta="The weather", response="The weather", tool_calls=[],
    current_agent_name="ResearchAgent", thinking_delta=None,
)

# Tool call
ToolCall(
    tool_name="search_web",
    tool_kwargs={"query": "weather San Francisco"},
    tool_id="call_abc123",
)

# Tool result
ToolCallResult(
    tool_name="search_web",
    tool_kwargs={"query": "weather San Francisco"},
    tool_id="call_abc123",
    tool_output=ToolOutput(blocks=[TextBlock(text="…")], tool_name="search_web", ...),
    return_direct=False,
)

# Final
AgentOutput(
    response=ChatMessage(role="assistant", content="The weather is …"),
    tool_calls=[...],
    current_agent_name="ResearchAgent",
)
```

## 4. Agent Runtime (Multi-session Host)

### 4.1 Multi-session host architecture

**Not provided in `llama-index-core`** — the framework gives you a `Workflow` you `run()` and you embed N concurrent runs in your own server (FastAPI, etc.). Each `run()` returns its own `WorkflowHandler` with its own `Context`.

The vendor offering is the separate **`llama_deploy`** repo, which provides a control-plane + queue runtime around `Workflow`s (out of scope here).

### 4.2 Concurrent session isolation

Each `workflow.run(...)` call creates a new `Context` (unless you pass `ctx=existing_ctx` to resume). Sessions are isolated by construction. The `Context.store` is a per-context KV store with no global sharing.

### 4.3 Horizontal scaling / multi-instance

In the OSS framework: BYO. You serialize a `Context` (`ctx.to_dict(serializer=JsonSerializer())`, `docs/src/content/docs/framework/understanding/agent/state.md:62-64`), stash it in your store (Postgres/Redis/…), and re-hydrate on the next request from any worker.

### 4.4 Background / async / scheduled tasks

Not provided — BYO (Celery, Temporal, RQ, your own asyncio task).

### 4.5 Worker pool / queue model

Not provided — BYO. `llama_deploy` provides this in a separate project.

## 5. Sessions & Persistence

### 5.1 Session / chat data model

There's no formal `Session` type. What persists is:

1. The `Context` of a workflow run — a serializable bag of state. Contains the workflow's running state, pending events, the `store` (KV), and the queue position.
2. The `Memory` (`llama-index-core/llama_index/core/memory/memory.py:179`) — the message history with its `session_id`.

`Memory` schema (`memory.py:179-249`):

```python
class Memory(BaseMemory):
    token_limit: int = 30000
    token_flush_size: int = 3000
    chat_history_token_ratio: float = 0.7
    memory_blocks: List[BaseMemoryBlock] = []  # extensible "memory block" mechanism
    insert_method: InsertMethod = InsertMethod.SYSTEM   # SYSTEM | USER
    tokenizer_fn: Callable
    sql_store: SQLAlchemyChatStore   # storage adapter
    session_id: str                  # the conversation key
```

### 5.2 What's stored on a session

- Full message history in `SQLAlchemyChatStore` (table per memory instance, rows = messages).
- Optional "memory blocks" (`StaticMemoryBlock`, `VectorMemoryBlock`, `FactExtractionMemoryBlock`) for cross-session / long-term recall.
- Workflow `Context.store` if you serialize it: any KV state your tools / steps stashed via `await ctx.store.set(key, value)`.

### 5.3 Granularity

One `session_id` per conversation; no fork/branch primitive in the OSS framework. (Workflow `Context` resume after pause is the closest mechanic.)

### 5.4 Built-in persistence stores

- `Memory` uses `SQLAlchemyChatStore` (`llama-index-core/llama_index/core/memory/memory.py:241`) — any SQLAlchemy-supported DB (SQLite default, Postgres, MySQL).
- `Context` serialization is BYO storage: `ctx.to_dict(serializer=JsonSerializer())` → write to your store.
- Additional chat stores under `llama-index-core/llama_index/core/storage/chat_store/` (Postgres, Redis, …).

### 5.5 Persistence timing

`Memory.aput(...)` is called explicitly at three points in the run loop:
- After receiving the user message: `init_run` calls `memory.aput(user_msg)` (`base_agent.py:403`).
- After tool results: `FunctionAgent.handle_tool_call_results` appends tool messages to the scratchpad, and `FunctionAgent.finalize` does `memory.aput_messages(scratchpad)` at the end of a turn (`function_agent.py:148-178, 180-196`).
- The `Context.store` is in-memory only; you serialize on demand.

There is no automatic per-token or per-tool checkpoint of the `Context` itself.

### 5.6 Mid-run checkpointing (durable)

Not automatic. The workflow can be **paused** at `ctx.wait_for_event(...)` (HITL), at which point you can `ctx.to_dict(...)` and resume later — but a crash mid-tool-call loses the in-flight tool result. Compared to LangGraph's `_runner.commit() → put_writes()` per-task, this is weaker.

### 5.7 Session ID format

A `Memory` `session_id` defaults to `str(uuid.uuid4())` (`llama-index-core/llama_index/core/memory/memory.py:84-86`). You can pass any string. No tenant-prefix convention.

### 5.8 Pluggable store interface

- `BaseMemory` is the interface (`llama-index-core/llama_index/core/memory/types.py`).
- `BaseChatStore` is the persistence interface for the message store.
- `SQLAlchemyChatStore` (`memory.py:241`) is the default; community chat stores include `RedisChatStore`, `PostgresChatStore`, `AzureChatStore`, etc.

### 5.9 Schema evolution / migration

Not provided — BYO. SQLAlchemy migrations are your responsibility.

### 5.10 Export / replay

- `Context.to_dict(serializer=JsonSerializer())` / `Context.from_dict(workflow, ctx_dict, serializer=…)` — the canonical export/import pattern (`docs/src/content/docs/framework/understanding/agent/state.md:62-77`).
- For deterministic replay, you would re-feed `chat_history` to a new run with mocked LLM responses; no built-in record/replay harness.

### 5.11 Cross-session memory

Yes — `VectorMemoryBlock` and `FactExtractionMemoryBlock` (`llama-index-core/llama_index/core/memory/memory_blocks/`) implement semantic / extracted-facts long-term memory. See Q17.

## 6. Multi-tenancy & Arbitrary Context

### 6.1 Full run-loop input struct

`AgentWorkflowStartEvent` fields (`llama-index-core/llama_index/core/agent/workflow/workflow_events.py:116-147`) plus the kwargs threaded into `Workflow.run` (`base_agent.py:740-813`):

```python
AgentWorkflowStartEvent(
    user_msg=…,                # str | ChatMessage
    chat_history=…,            # list[ChatMessage]
    memory=…,                  # BaseMemory
    max_iterations=…,          # int
    early_stopping_method=…,   # "force" | "generate"
    # plus arbitrary **kwargs that land in the event's `data`
)
```

There is **no first-class `tenant_id` / `user_id` / `metadata`** field on the start event. You inject these via `ctx.store.set(...)` after construction, or via `**kwargs` that the start event captures.

### 6.2 Context propagation into a tool call

If your tool function declares `ctx: Context` as a parameter, the workflow injects the live `Context`:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:346-363
async def _call_tool(self, ctx, tool, tool_input):
    if (isinstance(tool, FunctionTool)
        and tool.requires_context
        and tool.ctx_param_name is not None):
        new_tool_input = {**tool_input}
        new_tool_input[tool.ctx_param_name] = ctx
        tool_output = await tool.acall(**new_tool_input)
```

Inside your tool: `state = await ctx.store.get("state"); tenant_id = state["tenant_id"]`.

### 6.3 Tool call interface

`FunctionTool.acall(*args, **kwargs) -> ToolOutput` (`llama-index-core/llama_index/core/tools/function_tool.py:374`):

```python
async def acall(self, *args, **kwargs) -> ToolOutput:
    all_kwargs = {**self._field_defaults, **self.partial_params, **kwargs}
    if self.requires_context and self.ctx_param_name is not None:
        if self.ctx_param_name not in all_kwargs:
            raise ValueError("Context is required for this tool")
    raw_output = await self._async_fn(*args, **all_kwargs)
    ...
```

Note the merge order: `{**self._field_defaults, **self.partial_params, **kwargs}` means **LLM-provided `kwargs` win over `partial_params`**. So `partial_params` is a default, not an override. This is a critical gotcha for Q6.4.

### 6.4 Forcing tool arguments from the harness

⚠️ **Partial workaround only.**

LlamaIndex provides `FunctionTool(partial_params={...})` (`function_tool.py:87`), but its `call`/`acall` merges `{**_field_defaults, **partial_params, **kwargs}` (line 376), so **LLM-provided kwargs win over `partial_params`**. The `partial_params` field is therefore a *default-filler*, not a force-override.

To truly force, you have two BYO patterns:

- **Pattern A — wrap the tool with a closure that ignores LLM-provided values:**
  ```python
  def topic_search_factory(tenant_id: str):
      async def topic_search(query: str) -> str:  # no tenant_id in signature
          return await real_topic_search(tenant_id=tenant_id, query=query)
      return FunctionTool.from_defaults(async_fn=topic_search, name="topicSearch")
  ```
- **Pattern B — read tenant from `Context` inside the tool:**
  ```python
  async def topic_search(ctx: Context, query: str) -> str:
      state = await ctx.store.get("state")
      return await real_topic_search(tenant_id=state["tenant_id"], query=query)
  ```
  The LLM's tool schema will not include `tenant_id` because Context params are stripped from the schema (`function_tool.py:204-247`).

Pattern B is the idiomatic LlamaIndex answer. It's effective but it's still **convention**, not enforcement — a forgetful tool author can read `tenant_id` from the LLM-provided args by accident.

### 6.5 Filtering visible tools

Done at construction or via `tool_retriever`:

- **Static**: pass only the allowed tools to the agent: `FunctionAgent(tools=[topic_search, iab_search, audience_create], ...)`.
- **Dynamic at session start**: build a per-request agent instance with a filtered `tools` list.
- **Dynamic per turn**: pass a `tool_retriever: ObjectRetriever` (`base_agent.py:104-107`) that LlamaIndex calls each turn with the current `user_msg_str`:
  ```python
  # base_agent.py:272-281
  async def get_tools(self, input_str=None):
      tools = [*self.tools] if self.tools else []
      if self.tool_retriever is not None:
          retrieved_tools = await self.tool_retriever.aretrieve(input_str or "")
          tools.extend(retrieved_tools)
      return self._ensure_tools_are_async(cast(List[BaseTool], tools))
  ```

### 6.6 Tenant scope on session

No first-class `tenant_id` field on session or context. Stuffed in `ctx.store` (a generic KV) or `Memory.session_id` (a single string you can encode `tenant:user:conversation` into).

### 6.7 Per-tool-call auth propagation

Auth identity is whatever you stash in `ctx.store` and read inside the tool. There is no built-in identity propagation from an outer HTTP handler.

### 6.8 Resource scoping primitives

Not provided — BYO. You either pass tenant-scoped tool lists at agent construction or filter in your `tool_retriever`.

### 6.9 Per-tenant rate limit + budget cap

`TokenCountingHandler` has a `token_budget` parameter (`llama-index-core/llama_index/core/callbacks/token_counting.py:153, 167`) that raises `ValueError` if exceeded — but it's per *handler instance*, not per tenant, and it counts tokens (not USD). 🔴 **No USD budget cap.**

### ⭐ Light usage example (Q6)

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.workflow import Context
from llama_index.llms.openai import OpenAI

# Step 1: pass tenantId / userId / targetingStrategyId
# Step 2: only expose 3 tools (filter at agent construction)
# Step 3: force tenantId server-side via Context (pattern B above)

async def topic_search(ctx: Context, query: str) -> str:
    state = await ctx.store.get("state")
    # tenant_id comes from harness state, NOT from the LLM
    return await real_topic_search(tenant_id=state["tenant_id"], query=query)

async def iab_search(ctx: Context, term: str) -> str: ...
async def audience_create(ctx: Context, name: str) -> str: ...

agent = FunctionAgent(
    tools=[topic_search, iab_search, audience_create],   # bashExec/webFetch NOT registered
    llm=OpenAI(model="gpt-4o-mini"),
    initial_state={"tenant_id": "acme", "user_id": "u-123",
                   "targeting_strategy_id": "strat-42"},
)
handler = agent.run(user_msg="find topics about sports")
async for ev in handler.stream_events():
    print(ev)
final = await handler
```

`initial_state` lands in `ctx.store["state"]` (`base_agent.py:292`). Tools read tenant from there. The LLM never sees `tenant_id` in the tool schema because `Context` params are excluded by `function_tool.py:204-247`.

## 7. Hook & Middleware Capabilities (Context Engineering)

### 7.1 Enumerate every hook / middleware / lifecycle callback

LlamaIndex does not ship a Claude-Code-style hook system. The closest constructs are:

| Mechanism | Fires when | Can do what |
|---|---|---|
| Subclass a `@step` method in `BaseWorkflowAgent` | Replace any of `init_run`, `setup_agent`, `run_agent_step`, `parse_agent_output`, `call_tool`, `aggregate_tool_results` | Read / mutate / block / branch |
| `BaseWorkflowAgent.take_step(...)` | Once per LLM call | Read / mutate inputs and outputs |
| `BaseWorkflowAgent.handle_tool_call_results(...)` | After tool execution, before next LLM call | Mutate tool results before they hit memory |
| `BaseWorkflowAgent.finalize(...)` | At end of run | Final message/state cleanup |
| `FunctionTool(callback=..., async_callback=...)` | After each tool call | Read raw output; return `ToolOutput` to override, or `str` to override content (`function_tool.py:151-169, 360-371, 398-411`) |
| `FunctionTool(partial_params={...})` | Before each tool call | Provide default kwargs (LLM-provided values still win) |
| `llama-index-instrumentation` dispatcher (`Dispatcher.event_handlers` + `span_handlers`) | Every event / every span | Read-only — for tracing, not mutation |
| `system_prompt` on the agent | Once per LLM call (prepended) | Inject system context |
| `state_prompt` template + `initial_state` | Format `{state}` into the last user message before the first LLM call (`base_agent.py:447-457`) | Inject runtime state into the LLM input |

### 7.2 Hook concurrency model

There's no formal hook fan-out. Workflow `@step` methods run on the asyncio event loop and are scheduled deterministically by the upstream `workflows` runtime. Dispatcher event handlers fire synchronously when an event is dispatched.

### 7.3 Specific capability tests

- **Inject system messages at session start**: ✅ Via `system_prompt=` on the agent (`base_agent.py:98, 441-446`) or by overriding `setup_agent` step.
- **Expand user input** (slash, timestamp, attachments): ✅ Override `init_run` to mutate `user_msg`.
- **Mutate messages list before each LLM call**: ✅ Override `setup_agent` or `run_agent_step`. No first-class "preStep" hook though — you subclass.
- **Mutate tool input before dispatch**: ⚠️ `FunctionTool.partial_params` only acts as a default-filler; for a true override you wrap in a closure or read from `Context`. Override `call_tool` step for the universal version.
- **Mutate tool result before it returns to the LLM**: ✅ `FunctionTool(callback=...)` returning a new `ToolOutput` (`function_tool.py:151-169`); or override `aggregate_tool_results`.
- **Emit additional tool calls from a `PostToolUse` hook**: ❌ Not as a first-class hook — but workflows can `ctx.send_event(ToolCall(...))` from any `@step`, which the runtime will route. You'd subclass `aggregate_tool_results` to do this.

### 7.4 Auto-compaction

`Memory` has a token-budget-driven FIFO flush (`memory.py:196-211`): when the chat history exceeds `chat_history_token_ratio * token_limit`, oldest messages are flushed into the memory blocks. `ChatSummaryMemoryBuffer` (deprecated) does explicit summarization. New `Memory.memory_blocks` model lets you plug in `FactExtractionMemoryBlock` to summarize ejected messages.

### 7.5 Prompt cache optimization

Not first-class. `ChatMessage` supports a `CachePoint` content block (`llama-index-core/llama_index/core/base/llms/types.py:28` import + class), which providers like Anthropic / OpenAI honor — but the framework does not auto-place breakpoints; the developer inserts them.

### 7.6 Tool result clearing / progressive disclosure

Not provided — BYO. You can return a summary string from a `FunctionTool` `async_callback` and stash the full payload elsewhere.

### 7.7 Architectural diagram

```
                  ┌─────────────────────────────────────────────┐
                  │              workflow.run(...)              │
                  └─────────────────────┬───────────────────────┘
                                        │ AgentWorkflowStartEvent
                                        ▼
                  ┌──────────────────────────────────┐
                  │ @step init_run                   │  ← override here for SessionStart
                  │   (load Memory, set state)       │
                  └──────────────┬───────────────────┘
                                 │ AgentInput
                                 ▼
                  ┌──────────────────────────────────┐
                  │ @step setup_agent                │  ← override for system-prompt / state injection
                  │   (system_prompt + state_prompt) │
                  └──────────────┬───────────────────┘
                                 │ AgentSetup
                                 ▼
                  ┌──────────────────────────────────┐
                  │ @step run_agent_step             │  ← override for PreLLM
                  │   take_step → LLM stream         │
                  └──────────────┬───────────────────┘
                                 │ AgentOutput (with tool_calls)
                                 ▼
                  ┌──────────────────────────────────┐
                  │ @step parse_agent_output         │  ← override for turn-routing logic
                  │   emit N × ToolCall              │
                  └──────────────┬───────────────────┘
                                 │ ToolCall × N (parallel)
                                 ▼
                  ┌──────────────────────────────────┐
                  │ @step call_tool                  │  ← FunctionTool(callback=...) fires here
                  │   tool.acall(**tool_input)       │     also: partial_params merge
                  └──────────────┬───────────────────┘
                                 │ ToolCallResult × N
                                 ▼
                  ┌──────────────────────────────────┐
                  │ @step aggregate_tool_results     │  ← override for PostTool result-mutation
                  │   collect_events → memory        │
                  └──────────────┬───────────────────┘
                                 │ AgentInput (next turn) or StopEvent
                                 ▼
                              … loop …
```

### ⭐ Light usage example (Q7)

```python
from llama_index.core.agent.workflow import FunctionAgent, ToolCallResult
from llama_index.core.tools import FunctionTool, ToolOutput
from llama_index.core.workflow import Context

# 1. Session-start injection: use system_prompt + initial_state
SYSTEM_PROMPT = "tenant=acme, locale=fr-FR, today=2026-05-16. " \
                "You are a helpful assistant."

# 2. PreToolUse — read tenant from Context inside the tool (force pattern)
async def topic_search(ctx: Context, query: str) -> list[dict]:
    state = await ctx.store.get("state")
    return await real_topic_search(tenant_id=state["tenant_id"], query=query)

# 3. PostToolUse — summarize large results via FunctionTool callback
def summarize_if_large(raw: list[dict]) -> str | None:
    if isinstance(raw, list) and len(raw) > 50:
        return f"{len(raw)} topics returned; top 5: {raw[:5]}"
    return None  # leave default ToolOutput

topic_tool = FunctionTool.from_defaults(
    async_fn=topic_search,
    callback=summarize_if_large,         # PostTool hook (mutates content)
)

agent = FunctionAgent(
    tools=[topic_tool],
    system_prompt=SYSTEM_PROMPT,
    initial_state={"tenant_id": "acme", "locale": "fr-FR", "today": "2026-05-16"},
    llm=llm,
)
```

For more elaborate hooks (mutating messages before the LLM call), subclass `FunctionAgent` and override `setup_agent` or `take_step`.

## 8. HTTP API

### 8.1 Does the framework ship an HTTP server?

**No.** `llama-index-core` is library-only. The vendor's recommended runtime for production agent serving is the separate `llama_deploy` project. For most teams, the path is: wrap `workflow.run(...)` in a FastAPI route, expose `handler.stream_events()` over SSE.

### 8.2 HTTP streaming transport

BYO. Common pattern is FastAPI + SSE (Server-Sent Events) reading `handler.stream_events()`. There is a community helper `llama-index-server` package on PyPI but it's not in this monorepo.

### 8.3 HTTP endpoints that start an agent run

BYO. No defined API contract.

### 8.4 Live agentic event stream format

BYO. The Python event stream is `Event`-typed; you serialize via `event.model_dump_json()` (each `Event` is a Pydantic model).

### 8.5 Auth termination at the HTTP boundary

BYO.

### 8.6 Resume / replay endpoint

Pattern: serialize `Context` to your store keyed by `session_id`, look it up on the next request, pass `ctx=` to `workflow.run(...)`. See `docs/src/content/docs/framework/understanding/agent/state.md:60-77`.

### 8.7 Interrupt / cancel via HTTP

`WorkflowHandler` (from `workflows` package) exposes a `cancel_run()` method per upstream API. Wired up in the host's API endpoint by you.

### 8.8 Tool-arg streaming (partial JSON)

The LLM's streamed `delta` of a tool call comes through on `AgentStream.tool_calls` as the model emits it. The exact granularity depends on the underlying LLM integration.

### 8.9 HITL approval workflow over HTTP

First-class via `Context.wait_for_event(...)`:

```python
# docs/src/content/docs/framework/understanding/agent/human_in_the_loop.md:35-56
async def dangerous_task(ctx: Context) -> str:
    """A dangerous task that requires human confirmation."""
    response = await ctx.wait_for_event(
        HumanResponseEvent,
        waiter_id="confirm",
        waiter_event=InputRequiredEvent(prefix="Are you sure?", user_name="Laurie"),
        requirements={"user_name": "Laurie"},
    )
    return "ok" if response.response.strip().lower() == "yes" else "aborted"
```

The client receives the `InputRequiredEvent` on the stream and replies via `handler.ctx.send_event(HumanResponseEvent(response="yes", user_name="Laurie"))`. The tool resumes. Over HTTP the host routes the approval verdict to that `send_event(...)` call.

### 8.10 Tool-call state reconstruction

⭐ Events carry `tool_id`. `ToolCall.tool_id` and `ToolCallResult.tool_id` match (set on `workflow_events.py` `ToolCall` / `ToolCallResult` types). The client links them by explicit `tool_id`; no positional dependency.

### 8.11 Health checks / graceful shutdown

BYO.

### ⭐ Light usage example (Q8)

Because the SDK is library-only, this is illustrative of the BYO pattern (FastAPI):

```python
# server.py — your code
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()
agents_by_session: dict[str, tuple[FunctionAgent, Context]] = {}

@app.post("/runs")
async def start_run(tenant_id: str, user_msg: str):
    agent = build_agent(tenant_id=tenant_id)
    handler = agent.run(user_msg=user_msg)

    async def gen():
        async for ev in handler.stream_events():
            yield f"event: {type(ev).__name__}\ndata: {ev.model_dump_json()}\n\n"
        result = await handler
        yield f"event: done\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

# curl example:
# curl -N -H "X-Tenant-Id: acme" -d '{"user_msg":"hi"}' http://host/runs
#
# SSE stream sample:
#   event: AgentStream
#   data: {"delta":"Looking","response":"Looking", ...}
#
#   event: ToolCall
#   data: {"tool_name":"topicSearch","tool_kwargs":{...},"tool_id":"call_abc"}
#
#   event: done
#   data: {"response":{"role":"assistant","content":"..."}}
#
# Cancel: curl -X DELETE http://host/runs/{session_id}   (BYO — wires to handler.cancel_run())
# HITL verdict: curl -X POST http://host/runs/{session_id}/approve -d '{"approved":true}'
#               (BYO — wires to handler.ctx.send_event(HumanResponseEvent(...)))
```

Cancel and HITL approval endpoints: Not provided — BYO. You plumb `handler.cancel_run()` and `handler.ctx.send_event(HumanResponseEvent(...))` into your own routes.

## 9. Sub-agents

### 9.1 Mechanism

Both supported:

1. **First-class `AgentWorkflow` + `can_handoff_to`** — declare a set of `FunctionAgent`s, configure who can hand off to whom, and `AgentWorkflow` injects an auto-generated `handoff(to_agent, reason)` tool (`multi_agent_workflow.py:72-91, 215-245`). The active agent can stop the chain or call `handoff`.

2. **Agents-as-tools** — each sub-agent's `.run(...)` is wrapped in a function and registered as a `FunctionTool` on a parent (`docs/src/content/docs/framework/understanding/agent/multi_agent.md:86-184`).

### 9.2 Configuration

Python objects only. No markdown manifest. Each agent is a `FunctionAgent` / `ReActAgent` / `CodeActAgent` instance with `name`, `description`, `system_prompt`, `tools`, `can_handoff_to`.

### 9.3 LLM-generated configs

Not first-class. You can build a `FunctionAgent` dynamically inside a tool, but there's no markdown-loader analogue to Claude's `Task` tool.

### 9.4 Output handling

For `AgentWorkflow`: handoff returns a string from the `handoff` tool, which causes the workflow to switch `current_agent_name` (`multi_agent_workflow.py:86-91`) and re-enter `setup_agent` with the new active agent. The final `StopEvent.result` is an `AgentOutput`.

For agents-as-tools: the sub-agent's `.run(...)` is awaited; its result string is returned to the parent LLM as a normal tool result. The sub-agent's `ToolCallResult` is linked back to the parent via `tool_id`.

### 9.5 Concurrency model

`AgentWorkflow` is **serial** — only one agent active at a time (it's a sequential hand-off swarm).

Parallel sub-agents happen with the **agents-as-tools** pattern: the parent LLM emits multiple tool calls, and `parse_agent_output` fans them out via `ctx.send_event(ToolCall(...))` (`base_agent.py:610-619`). The `workflows` runtime executes them in parallel; `ctx.collect_events(...)` fans them back in (`base_agent.py:669-671`). For three persona sub-agents called concurrently, the parallelism point is **`base_agent.py:613` (the for-loop emitting one event per call)** plus the runtime's parallel `@step` execution.

### 9.6 Context isolation

Each sub-agent invocation via `.run(...)` gets its own `Context` (default) — fresh memory, fresh state. Or you can pass `ctx=parent_ctx` to share state.

### 9.7 Lifecycle events

When `AgentWorkflow` hands off, `AgentInput` / `AgentOutput` / `AgentStream` events tagged with the new `current_agent_name` are emitted on the stream. The parent stream sees each sub-agent's tokens.

### ⭐ Light usage example (Q9)

Three persona sub-agents invoked in parallel via the agents-as-tools pattern:

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.workflow import Context

def make_persona(name, prompt):
    return FunctionAgent(
        name=name,
        description=f"Persona: {name}",
        system_prompt=prompt,
        llm=llm,
        tools=[topic_search],
    )

young_mom = make_persona("persona-young-mom",  "You are a young mom shopping for diapers.")
tech_bro  = make_persona("persona-tech-bro",   "You are a tech bro who codes in Rust.")
retiree   = make_persona("persona-retiree",    "You are a 70-year-old retired teacher.")

async def call_young_mom(query: str) -> str:
    return str(await young_mom.run(user_msg=query))
async def call_tech_bro(query: str) -> str:
    return str(await tech_bro.run(user_msg=query))
async def call_retiree(query: str) -> str:
    return str(await retiree.run(user_msg=query))

parent = FunctionAgent(
    name="ParallelPersonaRunner",
    system_prompt="Call all three personas in parallel for any query.",
    llm=llm,
    tools=[call_young_mom, call_tech_bro, call_retiree],
    # allow_parallel_tool_calls=True is the default on FunctionAgent
)

handler = parent.run(user_msg="What topics interest you about cars?")
async for ev in handler.stream_events():
    if isinstance(ev, ToolCallResult):
        print(ev.tool_name, "→", ev.tool_output.content)
```

The parent LLM (function-calling-capable, with `allow_parallel_tool_calls=True`, default in `function_agent.py:27-30`) emits three `ToolCall`s; the workflow runtime runs them concurrently; the parent receives three `ToolCallResult` events.

## 10. Skills

### 10.1 First-class concept?

**No.** LlamaIndex has no `SKILL.md` analogue. There are "LlamaPacks" — community-shared, pip-installable templates — but those are codebases, not lightweight markdown skills.

### 10.2 File format

Not provided — BYO.

### 10.3 Loader mechanism

Not provided — BYO. The closest first-party mechanism is `tool_retriever: ObjectRetriever` on a `FunctionAgent` (`base_agent.py:104-107`), which lets you dynamically retrieve tools from a vector store per request — but those are tools, not skills.

### 10.4 Invocation

N/A.

### 10.5 Loading mode

N/A.

### 10.6 Runtime scoping (global / tenant / user)

N/A — BYO via your own loader feeding into `tool_retriever` or the `tools=[...]` constructor.

### 10.7 Skill composition

N/A.

### ⭐ Light usage example (Q10)

Since LlamaIndex has no skill concept, here's the *closest BYO pattern* — a markdown loader that turns a `SKILL.md` into a `FunctionTool`:

```python
# skills/generate-audience-from-brief/SKILL.md
# ---
# name: generate-audience-from-brief
# description: Turn a marketing brief into a targeted audience definition.
# parameters:
#   brief: str
# ---
# 1. Extract demographic signals from the brief.
# 2. Use topic_search to find related topics.
# 3. Call audience_create with the result.

import yaml, frontmatter
from pathlib import Path
from llama_index.core.tools import FunctionTool

def load_skill(path: Path) -> FunctionTool:
    post = frontmatter.load(path)
    meta = post.metadata
    body = post.content

    async def run_skill(brief: str) -> str:
        # Naive: feed the skill body + brief into the parent agent via a sub-agent
        sub = FunctionAgent(
            name=meta["name"],
            system_prompt=body,
            llm=llm,
            tools=[topic_search, audience_create],
        )
        return str(await sub.run(user_msg=brief))

    run_skill.__doc__ = meta["description"]
    return FunctionTool.from_defaults(async_fn=run_skill, name=meta["name"])

skill = load_skill(Path("skills/generate-audience-from-brief/SKILL.md"))
parent = FunctionAgent(tools=[skill], llm=llm)
# LLM sees one tool called "generate-audience-from-brief"; calling it spawns a sub-agent.
```

This is purely BYO. **Not provided — BYO** for any of: lazy loading, scoping, registry, versioning.

## 11. Resource Manager

### 11.1 First-class Resource Manager?

**No.** Not provided — BYO.

### 11.2 Loading sources

Not provided — BYO. The framework loads tools from Python imports (or from any retriever you wire in via `tool_retriever`). There is no concept of "load a skill from S3/GCS/Git".

### 11.3 Source composition / priority

Not provided — BYO.

### 11.4 Versioning model

For *integration packages* (PyPI), each `llama-index-<x>-<y>` has its own semver and is in the `CHANGELOG.md`. For agent resources (skills, sub-agents, tools), no versioning — they live in your codebase.

### 11.5 Scoping at the registry layer

Not provided — BYO.

### 11.6 Publishing workflow

The LlamaHub site (https://llamahub.ai/) is a directory of community LlamaPacks but offers no draft/review/promote workflow.

### 11.7 Lifecycle / governance

Not provided — BYO.

### 11.8 Programmatic API

Not provided — BYO.

### 11.9 Caching & sync model

Not provided — BYO.

### ⭐ Light usage example (Q11)

Not provided — BYO. Skeleton of a hand-rolled approach:

```python
# Pseudocode — no first-party support
from your_company.skills_registry import Registry

reg = Registry(
    sources=[
        ("git", "git+https://github.com/dailymotion/predict-skills"),
        ("s3-tenant", "s3://predict-skills/tenants/{tenant_id}/"),
    ],
    priority_by_tenant={"acme": ["s3-tenant", "git"]},
)

reg.promote("generate-audience-from-brief", env="active", tenant="acme")
tools = reg.list_active(tenant_id="acme")     # returns list[FunctionTool]
agent = FunctionAgent(tools=tools, llm=llm)
```

There is no LlamaIndex-shipped `reg.list_active(tenant_id=…)` equivalent; you build it on top of `ObjectRetriever` (`llama-index-core/llama_index/core/objects/`) which can be backed by your own vector store of tool descriptions.

## 12. Observability: Usage, Cost, Tracing, Audit

### 12.1 Where tokens are surfaced

- **Per LLM call**: token counts surface on the `ChatResponse.raw` payload (provider-dependent), and the `TokenCountingHandler` accumulates them across the run (`callbacks/token_counting.py:79-140, 143-...`).
- **Per event**: `AgentStream` carries the per-delta raw payload (`workflow_events.py:38-46`).
- **Per session**: read `TokenCountingHandler.total_llm_token_count` or query your tracing backend.

### 12.2 Per-call / per-turn / per-session / per-tenant rollups

- Per-call: from `ChatResponse.raw`.
- Per-session: `TokenCountingHandler` accumulates as long as the handler instance lives.
- Per-tenant: BYO. The `instrument_tags` context manager (`llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py:36-42`) lets you tag spans with arbitrary key/values — this is the recommended mechanism for per-tenant tagging.

### 12.3 USD cost computation

🔴 **Not provided.** Searching the entire core package for `cost_usd`, `cost_in_dollars`, or `usd` returns no results. You compute USD yourself from token counts × a provider price table.

### 12.4 Per-tenant / per-conversation cost

BYO via metadata-tagged spans.

### 12.5 LLM / tool tracing

Two paths:

- **`llama-index-instrumentation`** (extracted from core in 2025 — `CHANGELOG.md:3400` "feat: support custom span processor; refactor: use llama-index-instrumentation instead of llama-index-core" #20732). Dispatcher tree with event/span handlers (`llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py:50`). Async-task and thread safe — preserves trace trees across coroutines.
- **OTel exporter**: `llama-index-observability-otel` (`llama-index-integrations/observability/llama-index-observability-otel/`) — bridges spans to any OTel-compatible backend (Datadog, Honeycomb, Jaeger, etc.).
- **First-party integrations** (callback packages): Arize Phoenix, Langfuse, Opik, OpenInference, PromptLayer, UpTrain, W&B, HoneyHive, AgentOps, Literal AI, Argilla, AIM — about 20+ in `llama-index-integrations/callbacks/` and `…/observability/`.

### 12.6 Audit logging (who / when / what)

Not first-class. The instrumentation event stream + your own sink (Postgres / S3) is the recommended approach. Not tamper-evident out of the box.

### 12.7 Canonical "where do I read token counts" code path

```python
# llama-index-core/llama_index/core/callbacks/token_counting.py:79-140
def get_llm_token_counts(token_counter, payload, event_id="") -> TokenCountingEvent:
    ...
    return TokenCountingEvent(
        event_id=event_id,
        prompt=…,
        prompt_token_count=prompt_tokens,
        completion=…,
        completion_token_count=completion_tokens,
    )
```

Usage:
```python
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

token_counter = TokenCountingHandler()
Settings.callback_manager = CallbackManager([token_counter])

# ... run agent ...
print(token_counter.total_llm_token_count)
print(token_counter.prompt_llm_token_count, token_counter.completion_llm_token_count)
```

### ⭐ Light usage example (Q12)

```python
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index_instrumentation.dispatcher import instrument_tags
from llama_index.observability.otel import LlamaIndexOpenTelemetry

# Token counting
counter = TokenCountingHandler()
Settings.callback_manager = CallbackManager([counter])

# OTel — push spans to your backend
otel = LlamaIndexOpenTelemetry(service_name="agentic-service")
otel.start_registering()

# Per-tenant tagging
with instrument_tags({"tenant_id": "acme", "user_id": "u-123"}):
    handler = agent.run(user_msg="…")
    result = await handler

print("tokens_in =", counter.prompt_llm_token_count)
print("tokens_out =", counter.completion_llm_token_count)
# cost_usd = price_per_1k_input * tokens_in/1000 + price_per_1k_output * tokens_out/1000
# (you compute this yourself — no first-party USD)

# Datadog/OTel sink picks up the tagged spans automatically.
```

## 13. Built-in Tools & Tool Authoring API

### 13.1 Built-in tools shipped in the box

`llama-index-core` ships **no general-purpose tools** in the box (no `Read`/`Write`/`Edit`/`Bash`/`WebFetch`/`Grep` analogues). The starter package `llama-index` only pulls in OpenAI LLM + embeddings.

For real tools, you install integration packages from `llama-index-integrations/tools/` (~40+ tools):

| Tool | Purpose |
|---|---|
| `llama-index-tools-azure-code-interpreter` | Run code in Azure sandbox |
| `llama-index-tools-code-interpreter` | Local code execution |
| `llama-index-tools-arxiv` | Search arxiv |
| `llama-index-tools-bing-search`, `brave-search`, `google` | Web search |
| `llama-index-tools-tavily-research` | Tavily research |
| `llama-index-tools-brightdata`, `desearch` | Web scraping |
| `llama-index-tools-database` | SQL queries |
| `llama-index-tools-cassandra` | Cassandra |
| `llama-index-tools-box`, `airweave` | File ops on cloud drives |
| `llama-index-tools-artifact-editor` | Edit text artifacts |
| `llama-index-tools-aws-bedrock-agentcore` | Bedrock AgentCore |
| `llama-index-tools-agentql` | AgentQL web extraction |
| `llama-index-tools-mcp` | Generic MCP client |
| `llama-index-tools-mcp-discovery` | MCP server discovery |
| `llama-index-tools-azure-cv`, `azure-speech`, `azure-translate` | Azure AI services |

Core also has `QueryEngineTool`, `RetrieverTool`, `OnDemandLoaderTool` (`llama-index-core/llama_index/core/tools/`) for the RAG use case.

### 13.2 Built-in tool quality

The web/file tools are thin wrappers around vendor APIs. There is no equivalent to Claude Code's `Edit` (anchor matching), `Read` (line numbers), `Monitor` (line-event streaming). For our use case (agent piloting skills), you would write your own.

### 13.3 Tool authoring API

The smallest possible tool is a typed Python function:

```python
# Method 1 — pass a callable, framework wraps it
async def topic_search(query: str) -> list[str]:
    """Search topics by keyword."""
    return await db.search(query)

agent = FunctionAgent(tools=[topic_search], llm=llm)
# Internally: FunctionTool.from_defaults(fn=topic_search) — see base_agent.py:206-231
```

```python
# Method 2 — explicit FunctionTool with overrides
from llama_index.core.tools import FunctionTool

topic_search_tool = FunctionTool.from_defaults(
    async_fn=topic_search,
    name="topicSearch",
    description="Search advertising topics by keyword",
    return_direct=False,
    callback=my_post_callback,            # PostTool hook
    partial_params={"k": 10},             # default arg (not a force-override)
)
```

JSON schema is auto-generated from the function signature + type hints via `create_schema_from_function` (`llama-index-core/llama_index/core/tools/function_tool.py:242` + `…/tools/utils.py`).

### 13.4 Typed tool I/O

Runtime validation via Pydantic. `create_schema_from_function` builds a `BaseModel` subclass; on invalid LLM args the call raises a Pydantic `ValidationError`, which is caught by `_call_tool` and wrapped in a `ToolOutput(is_error=True, content=str(e), ...)` (`base_agent.py:364-378`).

### 13.5 Streaming tools

Tools can write to the event stream via `ctx.write_event_to_stream(...)` inside the tool body (because they receive the live `Context`):

```python
async def long_task(ctx: Context) -> str:
    for i in range(10):
        ctx.write_event_to_stream(ProgressEvent(pct=i*10))
        await asyncio.sleep(1)
    return "done"
```

This emits custom events to the consumer mid-tool-execution. Tools don't *yield* partial results back to the LLM mid-call though — the tool returns once.

## 14. MCP (Model Context Protocol) Support

### 14.1 MCP client support

✅ First-party via `llama-index-tools-mcp` (`llama-index-integrations/tools/llama-index-tools-mcp/`). `McpToolSpec` consumes any `mcp.ClientSession` and exposes its tools as `FunctionTool`s (`base.py:19`):

```python
# llama-index-integrations/tools/llama-index-tools-mcp/llama_index/tools/mcp/utils.py:66-74
client = client or BasicMCPClient(command_or_url)
tool_spec = McpToolSpec(client, allowed_tools=allowed_tools, ...)
return await tool_spec.to_tool_list_async()
```

### 14.2 MCP server support

✅ `workflow_as_mcp(workflow)` (`utils.py:77-141`) wraps any `Workflow` (including an `AgentWorkflow`) as a FastMCP server, exposing it as a single tool. Streams workflow events as MCP log messages (`utils.py:135-137`).

### 14.3 Transports

stdio, SSE, streamable_http — all supported by `BasicMCPClient` (`client.py:22-24`):

```python
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
```

The client picks based on URL: `…/sse` → SSE, `?transport=sse` → SSE, otherwise streamable_http; command-line strings → stdio (`client.py:54-66, 230-275`).

### 14.4 In-process MCP

✅ via `workflow_as_mcp(workflow)` — a Python function or workflow becomes an MCP tool without spawning a subprocess (it runs in the same FastMCP process).

### 14.5 Auth / lifecycle

OAuth is supported through `OAuthClientProvider` and a `TokenStorage` interface (`client.py:25-26, 69-...`). `DefaultInMemoryTokenStorage` is the default; production deployments implement their own to persist tokens.

## 15. Multi-model Routing & Fallback

### 15.1 Multi-provider support

✅ Extensive. 104 LLM integration packages under `llama-index-integrations/llms/` — Anthropic, OpenAI, Azure OpenAI, Bedrock, Bedrock Converse, Vertex, Google GenAI, Cohere, Mistral, Groq, Together, Fireworks, DeepSeek, Cerebras, Databricks, Cloudflare AI Gateway, Heroku, HuggingFace, IBM, Ollama, vLLM, and many more.

### 15.2 Per-task model selection

Each agent has its own `llm:` field (`base_agent.py:111-113`). You can give a different LLM to each sub-agent in an `AgentWorkflow` — e.g. orchestrator on Sonnet, workers on Haiku. There's no first-party `Router` (cheap-for-triage / expensive-for-hard) abstraction; you build it as a routing tool or as a custom step.

### 15.3 Automatic fallback chain

Not first-class in core. There is `llama-index-llms-cloudflare-ai-gateway` (integration) which Cloudflare's AI Gateway provides; for general fallback you wrap an `LLM` with retry/fallback logic yourself.

### 15.4 Mid-stream model switching

Per-turn switch supported — change the `llm` attribute on the agent (or use sub-agents on different models). Mid-token switch is not supported.

### 15.5 Sub-agent model overrides

✅ Each sub-agent in `AgentWorkflow` has its own `llm` (`multi_agent_workflow.py:140` builds `self.agents = {cfg.name: cfg for cfg in agents}`; each `cfg.llm` is independent).

## 16. Chat UI Layer

### 16.1 Streaming chat hook

Not first-party in `llama-index-core`. Community `llama-index-server` (separate PyPI) and `llama-index-chat-ui` (TS, separate repo) provide React/Next.js components.

### 16.2 Tool call rendering primitives

Not provided in core — BYO. The `llama_index.core.chat_ui` namespace exists but contains only event types (`chat_ui/events.py:1-19`: `UIEvent`, `SourceNodesEvent`, `ArtifactEvent`); no React.

### 16.3 Generative UI components

Via the separate `llama-index-chat-ui` npm package (out of scope here). In Python, `ArtifactEvent` is just a typed event you forward to your own UI.

### 16.4 BYO pattern

Parse `handler.stream_events()` server-side into SSE; render in your own React (or Vue/HTMX) frontend. The `ChatUI` reference frontend (https://github.com/run-llama/chat-ui) is the project's "official" demo.

## 17. Memory & Knowledge

### 17.1 Long-term memory / semantic recall

✅ First-class. `Memory.memory_blocks` (`memory.py:208-211`) accepts `BaseMemoryBlock` subclasses:

- `StaticMemoryBlock` — fixed system content (e.g. tenant facts).
- `VectorMemoryBlock` — vector search over past messages (`memory_blocks/vector.py`).
- `FactExtractionMemoryBlock` — LLM-extracted facts (`memory_blocks/fact.py`).

Blocks are processed in priority order; ejected short-term messages are pushed into blocks (`memory.py:142-156`).

### 17.2 RAG / knowledge retrieval integration

This is LlamaIndex's historical core competency. Vector stores: 60+ integrations under `llama-index-integrations/vector_stores/`. Index types: VectorStoreIndex, SummaryIndex, TreeIndex, KeywordTableIndex, KnowledgeGraphIndex, PropertyGraphIndex, ComposableIndex. Retrieval primitives: `BaseRetriever`, `RouterRetriever`, `FusionRetriever`. Citations: built-in via `CitableBlock` / `CitationBlock`.

For agent use: expose retrieval as a `QueryEngineTool` and let the LLM call it.

### 17.3 Per-tenant memory scoping

`Memory.session_id` is the only first-class scoping key. For per-tenant separation, encode `tenant:user:session` in `session_id` or use a per-tenant `SQLAlchemyChatStore` instance (different DB, table, or schema via `db_schema=`, `memory.py:298`).

## 18. Safety, Guardrails & Tool Sandboxing

### 18.1 Input/output guardrails

Not first-party in core. The `llama-index-integrations` ecosystem includes `llama-index-guardrails` (PyPI) and integrations with Guardrails AI, NeMo Guardrails, etc.

### 18.2 Tool sandboxing / permission model

No `canUseTool`-style hook. Permission is enforced by what tools you put in the `tools=[...]` list at agent construction. Inside a tool, you can `raise` to refuse — but no declarative ACL.

### 18.3 Sandbox provider integrations

- `llama-index-tools-code-interpreter` — local Python (not sandboxed by default).
- `llama-index-tools-azure-code-interpreter` — Azure-hosted sandbox.
- `llama-index-tools-aws-bedrock-agentcore` — Bedrock AgentCore.
- E2B / Daytona / Modal: no first-party packages found.

### 18.4 Default-deny vs. default-allow

Default-allow. Whatever you pass to `tools=[...]` is callable.

## 19. Eval, Testing & CI Gates

### 19.1 Golden datasets / regression suites

✅ Built-in evaluation primitives in `llama-index-core/llama_index/core/evaluation/`. Includes:
- `RetrieverEvaluator`, `RelevancyEvaluator`, `FaithfulnessEvaluator`, `CorrectnessEvaluator`, `AnswerRelevancyEvaluator`, `GuidelineEvaluator`, `SemanticSimilarityEvaluator`, `BatchEvalRunner`.
- Dataset generation: `RagDatasetGenerator`, `LabelledRagDataset`.

These are heavily RAG-oriented; for agent-behavior eval you mostly compose primitives yourself or use Phoenix/Langfuse/Opik.

### 19.2 LLM-as-judge scoring

✅ Each of the above evaluators uses an LLM as judge against a rubric.

### 19.3 CI eval gates / pre-merge

Not provided — BYO. You wire `BatchEvalRunner` into your CI.

### 19.4 Trace replay for skill iteration

Not provided — BYO. Phoenix/Langfuse/Arize integrations provide their own UIs.

## 20. Local Sandbox & Dev UX

### 20.1 Local agent runner

Not provided as a CLI/playground in `llama-index-core`. You run agents in a Jupyter notebook or a script. The `llama-index-cli` package exists (separate) but is focused on document indexing, not agent chatting.

### 20.2 Trace inspection

Via the OTel exporter into your tracing backend (Phoenix, Jaeger, Langfuse, etc.). No local TUI viewer.

### 20.3 Tenant / org switching

Not provided — BYO.

### 20.4 Hot reload

Not provided. Python reload is standard `importlib.reload` / `jurigged` if you want it.

## Architectural diagram

```mermaid
flowchart TB
    subgraph host["Host Python process (asyncio)"]
        api["BYO HTTP server<br/>(FastAPI / Flask / llama_deploy)"] -->|workflow.run| handler[WorkflowHandler]
        handler -->|stream_events| api

        subgraph wf["AgentWorkflow / FunctionAgent (Workflow subclass)"]
            init[init_run @step] --> setup[setup_agent @step]
            setup --> runstep[run_agent_step @step]
            runstep -->|take_step| llm[LLM.astream_chat]
            llm --> parse[parse_agent_output @step]
            parse -->|StopEvent| stop[StopEvent]
            parse -->|N × ToolCall| call[call_tool @step ×N]
            call -->|FunctionTool.callback| call
            call --> agg[aggregate_tool_results @step]
            agg --> setup
        end

        handler --> wf
        wf -->|ctx.store| ctx[Context KV + event queue]
        wf -->|memory.aput| mem[Memory]
        mem --> sql[SQLAlchemyChatStore]
        wf -->|write_event_to_stream| dispatcher[llama_index_instrumentation<br/>Dispatcher]
        dispatcher --> otel[OTel exporter / Langfuse /<br/>Arize / Opik / Phoenix]
    end

    sql -->|asyncpg/aiosqlite| db[(Postgres / SQLite / MySQL)]
    otel --> backend[(Tracing backend)]
    llm --> providers["104 LLM integration packages<br/>(OpenAI, Anthropic, Bedrock, …)"]
    call --> mcp["MCP client → external MCP servers<br/>(stdio / SSE / streamable_http)"]
```

## Appendix — Files worth reading first

- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:382-724` — the run loop's `@step` graph (init_run → setup_agent → run_agent_step → parse_agent_output → call_tool → aggregate_tool_results). This is the heart of the agent.
- `llama-index-core/llama_index/core/agent/workflow/function_agent.py:101-196` — `FunctionAgent.take_step` / `handle_tool_call_results` / `finalize`.
- `llama-index-core/llama_index/core/agent/workflow/multi_agent_workflow.py:72-91, 215-245` — handoff tool generation; multi-agent orchestration.
- `llama-index-core/llama_index/core/agent/workflow/workflow_events.py:1-147` — all agent-level event types (`AgentInput`, `AgentOutput`, `AgentStream`, `ToolCall`, `ToolCallResult`, `AgentWorkflowStartEvent`).
- `llama-index-core/llama_index/core/workflow/__init__.py:1-22` — the thin re-export from the upstream `workflows` package.
- `llama-index-core/llama_index/core/tools/function_tool.py:71-411` — `FunctionTool`, `partial_params`, `callback`, Context injection.
- `llama-index-core/llama_index/core/memory/memory.py:179-330` — `Memory` class with `memory_blocks`, `SQLAlchemyChatStore`, session_id.
- `llama-index-integrations/tools/llama-index-tools-mcp/llama_index/tools/mcp/base.py:19-160` — MCP client; `client.py:230-275` for transports; `utils.py:77-141` for `workflow_as_mcp` server.
- `llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py:36-80` — instrument_tags + Dispatcher (the OTel-friendly tracing layer).
- `llama-index-integrations/observability/llama-index-observability-otel/llama_index/observability/otel/base.py:48-...` — OTel span handler.
- `docs/src/content/docs/framework/understanding/agent/human_in_the_loop.md:1-90` — HITL pattern via `ctx.wait_for_event` + `InputRequiredEvent` / `HumanResponseEvent`.
- `docs/src/content/docs/framework/understanding/agent/multi_agent.md:1-413` — the three multi-agent patterns (AgentWorkflow, orchestrator, custom planner).
- `CHANGELOG.md:68-77` and around line 3400 — recent agent/instrumentation history.
