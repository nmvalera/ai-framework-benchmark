# LlamaIndex Python — Benchmark Analysis

> **Repo**: https://github.com/run-llama/llama_index
> **Commit analysed**: 7e2c60a78ec27e8d146dfdd596778aea83c041d5
> **Branch**: main
> **Framework path**: frameworks/llamaindex
> **Analysed on**: 2026-10-01

## TL;DR

- ⭐ **What is this stack architecturally?** A large Python monorepo (`llama-index-core` + ~300 separately-versioned integration packages on PyPI). The agent piece is `llama-index-core/agent/workflow/`, which is a thin layer of step-decorated classes built on top of the external **`workflows`** package (`pip install llama-index-workflows>=2.14,<3`, now developed in the `run-llama/llama-agents` monorepo). Agents are event-driven workflows: `FunctionAgent` / `ReActAgent` / `AgentWorkflow` are subclasses of `Workflow` whose `@step` methods emit/consume events through an in-memory queue. RAG/ingestion is the dominant historical use case but is not relevant for this benchmark.
- **Ecosystem**: Python (>=3.10).
- Open-source MIT, owned by LlamaIndex Inc. (Jerry Liu); commercial offerings exist (LlamaParse, formerly "LlamaCloud", and the LlamaAgents managed runtime).
- Core is v0.14.25 (`llama-index-core/pyproject.toml:37`); the framework dates to late 2022; APIs are stable but the **agent layer was rebuilt in 2025** when workflow primitives were spun out into the `workflows` package (`llama-index-core/llama_index/core/workflow/workflow.py:1` is a one-line re-export).
- ⚠️ **Most surprising (new since the last analysis)**: the repository README now states that the company's primary focus "has shifted towards LlamaParse" and that the OSS framework remains "available as an open toolkit" (`README.md:10-15`). Commit volume dropped from ~114/month (Jan–Mar 2026) to ~32/month (Jun–Sep 2026) and core releases slowed to every 4–8 weeks. Treat the framework as maintained but no longer the vendor's strategic product.
- The agent loop runs **in your Python process** as an asyncio coroutine. No subprocess, no separate runtime.
- Strongest fit for our use case: the event-graph workflow runtime gives clean hand-offs, parallel sub-agents (agents-as-tools), HITL via `wait_for_event`, and `Context.to_dict / from_dict` for durable resume. Tools can accept the `Context` as a typed parameter, giving first-class tenant-identity propagation. Since 0.14.23, `initial_state` is deep-copied per run, which closes a cross-run state-bleed bug that mattered for multi-tenant hosting.
- Weakest gap: **no resource manager, no skill concept** in the Anthropic sense, **no first-party HTTP server in this repo** (only the AG-UI integration router; the vendor's server is `llama-agents-server` in a separate repo, and `llama_deploy` is now deprecated), **no USD cost roll-up**, **no per-tenant budget enforcement**.
- Other notable primitive: `Context.wait_for_event(EventType, requirements=…, waiter_id=…)` pauses a step until the matching event is sent back (used for HITL approvals), and the whole `Context` (with running state) is serializable to JSON.
- One-line verdicts:
  - sessions/persistence: BYO (`Context.to_dict` + serializer); 1st-party `Memory` class, SQLAlchemy by default and since 0.14.24 any `AsyncDBChatStore` via `chat_store=`.
  - skills: Not provided — BYO.
  - resource manager: Not provided — BYO.
  - sub-agents: First-class via `AgentWorkflow` + `can_handoff_to`, or "agents-as-tools" pattern.
  - multi-tenancy: BYO; `Context` and `FunctionTool.partial_params` give the building blocks.
  - hooks: No hook system; closest equivalents are workflow steps you override and `FunctionTool` `callback=` / `async_callback=`.
  - API: Library-only in this repo, plus an AG-UI FastAPI router integration; production serving goes through the external `llama-agents-server` or your own FastAPI.
  - observability: 1st-party `llama-index-instrumentation` dispatcher + OTel exporter package; ~10 callback integrations (Arize, Langfuse, Opik, Phoenix…). LLM payloads in instrumentation events no longer include credentials (`to_payload`, 0.14.23).
- Production-readiness verdict for multi-tenant server-side deployment: **medium**. Core primitives are present and battle-tested, but you build the multi-tenant glue (sessions store, tenant identity propagation, skill catalog, HITL endpoints) yourself. The vendor's strategic shift to LlamaParse adds a long-term maintenance risk that was not visible in May 2026.

## 0. General

### 0.1 What is this stack?

A Python library + a constellation of integration packages. The agent layer is built on the **Workflow** abstraction (`Workflow` class + `@step` decorator + `Event`/`Context`/`Handler` primitives). `Workflow` itself was extracted from `llama-index-core` into a separate `llama-index-workflows` PyPI package — `llama-index-core` re-exports it (`llama-index-core/llama_index/core/workflow/workflow.py:1`). That package now lives in the `run-llama/llama-agents` monorepo (formerly `workflows-py`), next to `llama-agents-server`, `llama-agents-client`, `llama-agents-dbos` and `llamactl`.

### 0.2 Ecosystem

**Python** (>=3.10, `<4.0`) — `llama-index-core/pyproject.toml:40`. A separate TypeScript port (`LlamaIndex.TS`) exists in a sibling repo but is out of scope here.

### 0.3 Project status & governance

- **License**: MIT (`LICENSE:1`, `pyproject.toml:57`).
- **Owner/maintainers**: LlamaIndex Inc., founded by Jerry Liu. Maintainers listed in `pyproject.toml:58-65` (Jerry Liu, Logan Markewich, Simon Suo, Andrei Fajardo, Haotian Zhang, Sourabh Desai).
- **Commercial backing**: Yes — LlamaParse (Parse / Extract / Classify / Split / Index; the hosted platform formerly called LlamaCloud was renamed LlamaParse, see `docs/src/content/docs/framework/index.mdx` "LlamaCloud is now LlamaParse") and LlamaAgents (managed deployment) are paid offerings; the OSS framework remains free.
- **Strategic status (new)**: the README now carries a note that "our primary focus has shifted towards LlamaParse" and that the framework is still "available as an open toolkit" (`README.md:10-15`, PR #23020). The docs landing page was retitled "LlamaIndex Framework, by the makers of LlamaParse" and calls it "our original open-source toolkit for RAG and agents" (`docs/src/content/docs/framework/index.mdx:1-5`, PR #23204). No deprecation or end-of-life notice exists; this is a de-prioritisation signal, not an archive.
- **Support model**: GitHub issues, Discord (https://discord.gg/dGcwcsnxhU), paid LlamaParse support contracts.

### 0.4 Project maturity / age

- **Initial public release**: November 2022 (originally "GPT Index"; repo created 2022-11-02). Renamed to LlamaIndex shortly after.
- **Current major version**: `llama-index-core` 0.14.25 (`llama-index-core/pyproject.toml:37`), released 2026-09-21. Still pre-1.0.
- **Stability**: Stable. Most APIs are non-experimental. The agent layer was substantially rewritten in 2025 to live on top of `workflows` and the `Memory` API is marked as the replacement for deprecated `ChatMemoryBuffer` / `SimpleComposableMemory` (`llama-index-core/llama_index/core/memory/__init__.py:21-25`). The legacy positional `agent.run(user_msg, chat_history, memory, ctx)` overload is marked `@deprecated` in favour of the standard `Workflow.run(ctx, start_event, **kwargs)` signature (`llama-index-core/llama_index/core/agent/workflow/base_agent.py:736-760`).

### 0.5 Adoption & community signal

GitHub numbers captured 2026-10-01 (`gh api repos/run-llama/llama_index`):
- Stars: 52,378.
- Forks: 8,258.
- Watchers: 289.
- Contributors: ~475 listed by the GitHub contributors API (~2,000 including anonymous commit identities); 85 distinct commit authors between 2026-05-15 and 2026-09-28.
- Open issues + PRs: 831. PR numbers have reached ~23,300.
- Commit cadence: declining. Monthly commits on `main`: 83 / 119 / 140 (Jan–Mar 2026) vs. 14 / 36 / 46 / 33 (Jun–Sep 2026). 175 commits between the previous analysed commit (2026-05-15) and this one (2026-09-28).
- Release cadence: core 0.14.13 → 0.14.22 shipped roughly every 1–3 weeks (Jan–May 2026); 0.14.23 (2026-06-24), 0.14.24 (2026-08-19) and 0.14.25 (2026-09-21) are 4–8 weeks apart (https://github.com/run-llama/llama_index/releases).
- `llama-index-workflows` (the runtime under the agents) ships independently and more often: 2.20 → 2.25.0 between May and 2026-09-25 (https://github.com/run-llama/llama-agents/releases).
- Discord: Active (link in README badge row).

### 0.6 Ecosystem fit

- **Packages**: `llama-index` (starter, `pyproject.toml:66-69`), `llama-index-core` (lean), and ~300 `llama-index-<category>-<provider>` integration packages on PyPI (602 `pyproject.toml` files under `llama-index-integrations/` at this commit, down from 622 after a dependabot cleanup that removed stale packages, e.g. `llama-index-llms-palm`, `llama-index-callbacks-agentops`, `llama-index-callbacks-aim`).
- **LLM integrations**: 101 directories under `llama-index-integrations/llms/` (Anthropic, OpenAI, Bedrock, Bedrock Converse, Vertex, Google GenAI, Azure, Cohere, Mistral, Groq, Together, vLLM, Ollama, etc.).
- **Discovery**: LlamaHub links were retired from the docs (PR #23070); the README now points to the integrations page instead (`README.md:30`).
- **Used mostly as**: A library imported into your own service; not a CLI, not a hosted platform (LlamaParse is for parsing/ingestion, not for serving your agents).

### 0.7 Documentation depth & cross-team contributor accessibility

- Docs language: Markdown (Starlight static site). Source under `docs/src/content/docs/framework/`.
- Depth: Extensive — Concepts, Getting Started, Understanding (Agent, RAG, Workflows, Evaluation, Tracing, Deployment), Module Guides per provider, Use Cases. The "Understanding Agent" subdirectory is ~1100 lines across 7 files. Workflow docs moved under the LlamaAgents section (https://developers.llamaindex.ai/python/llamaagents/workflows/).
- Non-engineer accessibility: Low. Pages are code-walkthroughs in Python; no GUI or markdown-file authoring model.

### 0.8 Documentation entry points ⭐

- Official docs: https://developers.llamaindex.ai/python/framework/
- Quickstart: https://developers.llamaindex.ai/python/framework/getting_started/starter_example/
- API reference: https://developers.llamaindex.ai/python/framework/api_reference (generated from docstrings)
- Workflows (runtime under the agents): https://developers.llamaindex.ai/python/llamaagents/workflows/
- Hosting / deployment: https://developers.llamaindex.ai/python/llamaagents/workflows/deployment/ (`llama-agents-server`) and https://developers.llamaindex.ai/python/llamaagents/overview/ (LlamaAgents). `llama_deploy` (https://github.com/run-llama/llama_deploy) is deprecated.
- Examples: https://github.com/run-llama/llama_index/tree/main/docs/src/content/docs/framework/examples
- Changelog: `CHANGELOG.md` at repo root; rendered at https://developers.llamaindex.ai/python/framework/CHANGELOG
- GitHub Releases: https://github.com/run-llama/llama_index/releases (framework), https://github.com/run-llama/llama-agents/releases (workflows runtime, server)
- Issues: https://github.com/run-llama/llama_index/issues
- Discord: https://discord.gg/dGcwcsnxhU
- Integrations directory: https://developers.llamaindex.ai/python/framework/community/integrations (replaces LlamaHub links)
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
│   │  Memory (SQLAlchemyChatStore — sqlite/pg/mysql,  │      │
│   │          or any AsyncDBChatStore)                │      │
│   └──────────────────────────────────────────────────┘      │
│                                                             │
│   ┌──────────────────────────────────────────────────┐      │
│   │  llama_index_instrumentation dispatcher          │      │
│   │   → OTel / Arize / Langfuse / Opik / Phoenix …   │      │
│   └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘

   For HTTP: BYO (FastAPI/Flask), the AG-UI router integration,
   or the external `llama-agents-server` (separate repo).
```

### 1.1 Where does the agent loop actually execute?

**In your Python process**, as an asyncio coroutine. There is no bundled binary, no subprocess, no vendor cloud round-trip. The `FunctionAgent.run(...)` call resolves into `Workflow.run(...)` which schedules `@step` methods on the running asyncio event loop. See `llama-index-core/llama_index/core/agent/workflow/base_agent.py:393-446` (the `init_run`, `setup_agent`, `run_agent_step` steps) and `llama-index-core/llama_index/core/agent/workflow/base_agent.py:770-836` (the `run()` entrypoint).

### 1.2 Runtime dependencies

- Python 3.10+ (`llama-index-core/pyproject.toml:40`).
- Core deps: `SQLAlchemy[asyncio]`, `httpx`, `pydantic>=2.8`, `tiktoken`, `aiohttp`, `nltk`, `tenacity`, `wrapt`, `banks`, `aiosqlite`, **`llama-index-workflows>=2.14,<3`** (`llama-index-core/pyproject.toml:57-87`, workflows pin at line 83). The pin range did not change between 0.14.22 and 0.14.25; core's lockfile moved from workflows 2.20.0 to 2.24.0 and `llama-index-instrumentation` from 0.5.0 to 0.6.0. A fresh install resolves the newest 2.x (2.25.0 at capture date).
- No bundled binaries. Tokenizer is `tiktoken`.
- Required infrastructure services: none for in-process use; only the LLM provider HTTP endpoint. The default `Memory` uses SQLite via `aiosqlite`; production deploys typically swap for Postgres (any SQLAlchemy-supported DB) or a custom `AsyncDBChatStore`.
- Required vendor services: none (LlamaParse is optional and for parsing/ingestion, not agent serving).
- Optional: each LLM/store/tool integration adds its own provider SDK dependency.

### 1.3 Recommended deployment topology

Not opinionated in this repo. The official "deployment" tutorial is a single stub: `docs/src/content/docs/framework/understanding/deployment/deployment.md:1-6` literally says `TODO`. `docs/src/content/docs/framework/module_guides/llama_deploy/README.txt:1-2` still points at `llama_deploy`, but that project's README now says "This project is deprecated. To serve workflows, use llama-agents instead." The vendor's current path is the **`llama-agents`** monorepo: `llama-agents-server` (Starlette app that wraps any `Workflow` as a REST API with streaming, persistence and HITL), `llamactl` (CLI to init, serve locally and deploy to LlamaParse, AWS Bedrock AgentCore or your own infra), plus control-plane/operator packages. Its README describes the progression "library → server → coordination backend for durability → replication". That repo is outside this submodule and was only read at README level.

### 1.4 Cold-start cost & instance footprint

Pure-Python import overhead (`llama-index-core` pulls in SQLAlchemy, pydantic, tiktoken, nltk, banks, httpx, aiohttp — non-trivial). No published baseline RAM figure. Cold start is dominated by your LLM SDK warm-up, not the framework.

### 1.5 Vendor lock-in

- **LLM-provider lock-in**: None — pluggable `LLM` abstraction with ~100 implementations. 🟢
- **Hosting lock-in**: None for the OSS framework. 🟢 (`llama-agents-server` is OSS too; LlamaParse is for parse/ingest; LlamaAgents managed deployment is optional.)
- **Eval-platform lock-in**: None — bring your own (LangSmith, Arize, Langfuse, Opik, Phoenix all have official integrations under `llama-index-integrations/callbacks/`). 🟢

### 1.6 Framework weight / footprint

Heavy ecosystem (300+ integration packages) but core is modular — you install only what you need. The agent layer itself (`llama-index-core/llama_index/core/agent/workflow/`) is ~2,900 lines:

```
36   __init__.py
57   agent_context.py
836  base_agent.py
400  codeact_agent.py
196  function_agent.py
900  multi_agent_workflow.py
19   prompts.py
330  react_agent.py
146  workflow_events.py
```

### 1.7 Release-history signal

- `CHANGELOG.md` has a single combined log across all packages. Three core releases since the last analysis:
  - **0.14.23** (2026-06-24, `CHANGELOG.md:903-921`): "fix(workflow): deep copy initial_state to prevent mutation leaks across runs" (#21780), "simplify serialized payloads to instrumentation" (#22130, no credentials in LLM event payloads), "Add tool calling mock LLM" (#21732), multimodal synthesis/query engines.
  - **0.14.24** (2026-08-19, `CHANGELOG.md:685-704`): "honor agent structured_output_fn/output_cls inside AgentWorkflow" (#22162), "allow Memory to accept any AsyncDBChatStore" (#22541), "don't mark *args/**kwargs as required tool parameters" (#22135), FactExtractionMemoryBlock condense-prompt fix (#22213). Same date range: `llama-index-tools-mcp` migrated to the `mcp` 2.x SDK (#22557, `CHANGELOG.md:848`), OTel span-ID handling fix (#22485, `CHANGELOG.md:765`).
  - **0.14.25** (2026-09-21, `CHANGELOG.md:55-61`): "avoid retrying failed function tools" (#22841), security-alert dependency sweep (#22855), removal of deprecated IPEX integrations.
  - After 0.14.25 (unreleased on `main`): Claude Opus 5.5 / Sonnet 5.5 and GPT-6 model registrations in the Anthropic, Bedrock Converse and OpenAI integrations (#23208, #23214, #23223, #23304, #23305).
- Earlier (`CHANGELOG.md:5336`): "feat: support custom span processor; refactor: use llama-index-instrumentation instead of llama-index-core" (#20732) — the instrumentation extraction.
- Workflows runtime (separate repo, `llama-index-workflows` 2.21–2.25): `JsonSerializer(allowed_types=…)` type allow-listing for deserialisation (2.21, 2.24), lockless read-committed state reads (2.21), `list[E]` fan-out/fan-in and multi-event step parameters (2.22), state storage keyed by run id + namespace with automatic migration of existing rows (2.23), `Workflow(serializer=…)` (2.24), and workflow timeouts that accumulate across resumes instead of resetting (2.25 — a behaviour change for long-suspended HITL runs).
- The agent layer's most decision-relevant breaking change remains the move to the external `workflows` package and the deprecation of the older `OpenAIAgent` / `ReActAgent.from_tools` flavour in favour of `FunctionAgent` / `AgentWorkflow`. No breaking agent-API changes in this window.

## 2. Agent Loop

### 2.1 Run loop entrypoint(s)

`BaseWorkflowAgent.run(...)` returns a `WorkflowHandler` (an awaitable that's also an async iterator over events). Two overloads exist; the agent-specific positional one is `@deprecated`:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:742-769
@overload
@deprecated("Use the standard workflow signature instead: "
            "agent.run(user_msg='hello') or "
            "agent.run(ctx=ctx, start_event=event, user_msg='hello'). ...")
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

@overload
def run(
    self,
    ctx: Optional[Context] = None,
    start_event: Optional[StartEvent] = None,
    **kwargs: Any,
) -> WorkflowHandler: ...
```

Keyword use (`agent.run(user_msg="hello")`) is the supported form.

Usage:

```python
handler = workflow.run(user_msg="hello")        # returns WorkflowHandler immediately
async for event in handler.stream_events():     # iterate events
    ...
final = await handler                            # await for terminal result
```

The "loop" inside is the workflow event graph: `init_run → setup_agent → run_agent_step → parse_agent_output → (call_tool* → aggregate_tool_results) → setup_agent → … → StopEvent`. Each `@step` method emits one event and is dispatched by the upstream `workflows` runtime when its input event type is produced.

### 2.2 Per-iteration behavior

One "iteration" in `AgentWorkflow` is a single LLM call followed by N parallel tool calls. Decoration of the steps (`@step` in `base_agent.py:393, 447, 475, 530, 634, 671`):

1. `init_run(AgentWorkflowStartEvent) -> AgentInput` — load memory, set up `state` (deep copy of `initial_state`, line 303), emit user message.
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
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:621-630
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
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:357-391
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

Then `aggregate_tool_results` does the fan-in via `ctx.collect_events(...)` (`base_agent.py:680-682`).

(The separate `llama_index.core.tools.calling.call_tool` / `acall_tool` helpers, used by `LLM.predict_and_call` rather than the workflow agents, no longer re-invoke a failed single-argument `FunctionTool` with kwargs after a first failure — `llama-index-core/llama_index/core/tools/calling.py:13-24, 64-70`, #22841. This removed a double-execution risk for side-effecting tools on that path.)

### 2.5 Explicit turn concept

A "turn" is "one LLM call → N parallel tool calls → fan-in → next LLM call". The framework caps the count via `max_iterations` (default 20, `base_agent.py:67`) and surfaces an `early_stopping_method` choice of `"force"` (raise `WorkflowRuntimeError`) or `"generate"` (one final LLM call with a stopping prompt) — see `base_agent.py:530-552`.

### 2.6 Event emission mechanism (in-process)

Two complementary mechanisms inside one workflow:

1. **Step-routing events**: emitted via `return` from a `@step` method (or `ctx.send_event(ev)` to fan out). The workflow runtime delivers them to whatever step matches the type signature. The fan-in primitive is `ctx.collect_events(ev, expected=[T, T, T])`. Workflows 2.22 added `list[E]` fan-out returns and `list[E]` fan-in joins as an alternative.
2. **Stream events to consumer**: `ctx.write_event_to_stream(event)` puts the event onto the handler's external stream. `handler.stream_events()` is an async iterator over these:

```python
# example from docs/src/content/docs/framework/understanding/agent/streaming.mdx:54-60
handler = workflow.run(user_msg="What's the weather like in San Francisco?")

async for event in handler.stream_events():
    if isinstance(event, AgentStream):
        print(event.delta, end="", flush=True)
```

The `_get_llm_response` method writes `AgentStream` events as tokens arrive: `base_agent.py:340-350`.

## 3. Message & Event Taxonomy

### 3.1 Message layers

LlamaIndex distinguishes:

- **`ChatMessage`** — provider-agnostic LLM message (the wire format toward the LLM). Defined in `llama-index-core/llama_index/core/base/llms/types.py:1159`.
- **`Event` subclasses** — internal workflow events (the wire format between `@step` methods, and on the stream to the consumer).
- **`ChatResponse`** — the LLM's reply object, with `.message: ChatMessage`, `.raw`, `.delta`, `.additional_kwargs`.

There is no separate "UI message" type in core; consumers consume `Event`s directly (or a sub-selection like `AgentStream`). The AG-UI integration (Q8) adds a fourth vocabulary: AG-UI protocol events (`TextMessageStart/Content/End`, `ToolCallStart/Args/End`, `StateSnapshot/Delta`, `RunStarted/Finished/Error`) in `llama-index-integrations/protocols/llama-index-protocols-ag-ui/llama_index/protocols/ag_ui/events.py`.

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

- Agent workflow events: `llama-index-core/llama_index/core/agent/workflow/workflow_events.py:1-146`.
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

The vendor offering is `llama-agents-server` in the separate `run-llama/llama-agents` repo (`WorkflowServer().add_workflow(name, wf)`, Starlette-based, built-in SQLite store or BYO `AbstractWorkflowStore`). `llama_deploy`, which the previous analysis pointed to, is deprecated. Neither is in scope of this submodule.

### 4.2 Concurrent session isolation

Each `workflow.run(...)` call creates a new `Context` (unless you pass `ctx=existing_ctx` to resume). The `Context.store` is a per-context KV store with no global sharing.

**Change since 0.14.22**: agent `initial_state` used to be shallow-copied into each run (`self.initial_state.copy()`) by single agents and **not copied at all** by `AgentWorkflow` (`await ctx.store.set("state", self.initial_state)`). A tool that mutated a nested value in `state` therefore mutated the shared template, and the change leaked into every later run on the same agent instance. This is a real cross-tenant bleed if one agent instance serves many tenants. Both paths now deep-copy:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:302-303
if not await ctx.store.get("state", default=None):
    await ctx.store.set("state", copy.deepcopy(self.initial_state))

# llama-index-core/llama_index/core/agent/workflow/multi_agent_workflow.py:287-288
if not await ctx.store.get("state", default=None):
    await ctx.store.set("state", copy.deepcopy(self.initial_state))
```

(#21780, `CHANGELOG.md:916`; the AG-UI integration got the same fix in #22189.) Agents also gained identity-based `__hash__` (`base_agent.py:144-152`) because the workflows runtime keys serializer caches on the workflow instance. Isolation is still enforced only by "one `Context` per run"; anything you put on the agent object itself (tools with closures, LLM clients) is shared across runs.

### 4.3 Horizontal scaling / multi-instance

In the OSS framework: BYO. You serialize a `Context` (`ctx.to_dict(serializer=JsonSerializer())`, `docs/src/content/docs/framework/understanding/agent/state.md:62-64`), stash it in your store (Postgres/Redis/…), and re-hydrate on the next request from any worker. The external `llama-agents` stack adds a coordination backend (`llama-agents-dbos`) and replication; not analysed here.

### 4.4 Background / async / scheduled tasks

Not provided — BYO (Celery, Temporal, RQ, your own asyncio task).

### 4.5 Worker pool / queue model

Not provided — BYO. The external `llama-agents` control plane provides this in a separate project.

## 5. Sessions & Persistence

### 5.1 Session / chat data model

There's no formal `Session` type. What persists is:

1. The `Context` of a workflow run — a serializable bag of state. Contains the workflow's running state, pending events, the `store` (KV), and the queue position.
2. The `Memory` (`llama-index-core/llama_index/core/memory/memory.py:188`) — the message history with its `session_id`.

`Memory` schema (`memory.py:188-260`):

```python
class Memory(BaseMemory):
    token_limit: int = 30000
    token_flush_size: int = 3000
    chat_history_token_ratio: float = 0.7
    memory_blocks: List[BaseMemoryBlock] = []  # extensible "memory block" mechanism
    insert_method: InsertMethod = InsertMethod.SYSTEM   # SYSTEM | USER
    tokenizer_fn: Callable
    sql_store: AsyncDBChatStore      # storage adapter (was SQLAlchemyChatStore before 0.14.24)
    session_id: str                  # the conversation key
```

### 5.2 What's stored on a session

- Full message history in the chat store (default `SQLAlchemyChatStore`: one table, rows = messages keyed by `session_id`, with `ACTIVE`/`ARCHIVED` status).
- Optional "memory blocks" (`StaticMemoryBlock`, `VectorMemoryBlock`, `FactExtractionMemoryBlock`) for cross-session / long-term recall.
- Workflow `Context.store` if you serialize it: any KV state your tools / steps stashed via `await ctx.store.set(key, value)`.

### 5.3 Granularity

One `session_id` per conversation; no fork/branch primitive in the OSS framework. (Workflow `Context` resume after pause is the closest mechanic.)

### 5.4 Built-in persistence stores

- `Memory` uses `SQLAlchemyChatStore` by default (`llama-index-core/llama_index/core/memory/memory.py:315`) — any SQLAlchemy-supported DB (SQLite default, Postgres, MySQL).
- Since 0.14.24, `Memory.from_defaults(chat_store=...)` accepts any `AsyncDBChatStore` implementation (`memory.py:305, 315`). Core ships only the SQLAlchemy implementation; no integration package implements `AsyncDBChatStore` yet.
- `Context` serialization is BYO storage: `ctx.to_dict(serializer=JsonSerializer())` → write to your store.
- Legacy `BaseChatStore` implementations (for the deprecated `ChatMemoryBuffer`): `SimpleChatStore` and `SQLAlchemy`-based stores in `llama-index-core/llama_index/core/storage/chat_store/`, plus 13 integration packages under `llama-index-integrations/storage/chat_store/` (Postgres, Redis, DynamoDB, Mongo, Azure, Upstash, …).

### 5.5 Persistence timing

`Memory.aput(...)` is called explicitly at three points in the run loop:
- After receiving the user message: `init_run` calls `memory.aput(user_msg)` (`base_agent.py:414`).
- After tool results: `FunctionAgent.handle_tool_call_results` appends tool messages to the scratchpad, and `FunctionAgent.finalize` does `memory.aput_messages(scratchpad)` at the end of a turn (`function_agent.py:148-178, 180-196`).
- The `Context.store` is in-memory only; you serialize on demand.

There is no automatic per-token or per-tool checkpoint of the `Context` itself in the in-process runtime.

### 5.6 Mid-run checkpointing (durable)

Not automatic in-process. The workflow can be **paused** at `ctx.wait_for_event(...)` (HITL), at which point you can `ctx.to_dict(...)` and resume later — but a crash mid-tool-call loses the in-flight tool result. Compared to LangGraph's `_runner.commit() → put_writes()` per-task, this is weaker.

The `workflows` runtime has been moving toward durable execution: its 2.21–2.25 releases mention "durable ticks", "snapshot tick replay", preserving retry state across serialized context resume, and state storage keyed by run id. Those features surface through `llama-agents-server` / `llama-agents-dbos` (separate repo). I have not verified at code level whether they give per-step crash recovery for agents built with `FunctionAgent`; treat this as an open question.

### 5.7 Session ID format

A `Memory` `session_id` defaults to `str(uuid.uuid4())` (`llama-index-core/llama_index/core/memory/memory.py:93-95`). You can pass any string. No tenant-prefix convention.

### 5.8 Pluggable store interface

- `BaseMemory` is the interface (`llama-index-core/llama_index/core/memory/types.py`).
- **`AsyncDBChatStore`** is now the pluggable backend for `Memory` (`llama-index-core/llama_index/core/storage/chat_store/base_db.py:19-99`): abstract async `get_messages`, `count_messages`, `add_message(s)`, `set_messages`, `delete_message(s)`, `delete_oldest_messages`, `archive_oldest_messages`, `get_keys`. Documented in `docs/src/content/docs/framework/module_guides/deploying/agents/memory.mdx:273-293`:

```python
from llama_index.core.storage.chat_store.base_db import AsyncDBChatStore

class MyChatStore(AsyncDBChatStore):
    ...  # implement the FIFO-queue methods against your DB

memory = Memory.from_defaults(session_id="acme:u-123:conv-9", chat_store=MyChatStore())
```

- `BaseChatStore` remains the interface for legacy memory classes; community chat stores (`RedisChatStore`, `PostgresChatStore`, `AzureChatStore`, …) implement that one, not `AsyncDBChatStore`.

### 5.9 Schema evolution / migration

Not provided for `Memory` — BYO. SQLAlchemy migrations are your responsibility. (The external workflows server store migrated its own rows automatically in workflows 2.23 when it moved to run-id + namespace keys; that is outside this repo.)

### 5.10 Export / replay

- `Context.to_dict(serializer=JsonSerializer())` / `Context.from_dict(workflow, ctx_dict, serializer=…)` — the canonical export/import pattern (`docs/src/content/docs/framework/understanding/agent/state.md:62-77`).
- Workflows 2.21/2.24 added `JsonSerializer(allowed_types=[...], allow_unknown_types=...)` to allow-list the types that can be deserialized, and `Workflow(serializer=...)` to set one serializer for context state, durable ticks and replay. Relevant if you rehydrate `Context` from a shared store: without an allow-list, deserialization imports classes by name.
- For deterministic replay, you would re-feed `chat_history` to a new run with mocked LLM responses (`MockFunctionCallingLLM` can now replay `ToolCallBlock`s, `llama-index-core/llama_index/core/llms/mock.py:294-360`); no built-in record/replay harness.

### 5.11 Cross-session memory

Yes — `VectorMemoryBlock` and `FactExtractionMemoryBlock` (`llama-index-core/llama_index/core/memory/memory_blocks/`) implement semantic / extracted-facts long-term memory. See Q17.

## 6. Multi-tenancy & Tenant Identity ⭐ THE KEY QUESTION

### 6.1 Run-loop tenant identity

`AgentWorkflowStartEvent` fields (`llama-index-core/llama_index/core/agent/workflow/workflow_events.py:116-146`) plus the kwargs threaded into `Workflow.run` (`base_agent.py:751-836`):

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

There is **no first-class `tenant_id` / `user_id` / `locale` / `metadata`** field on the start event, on `Context`, or on `Memory`. Tenant identity goes in one of:

- `initial_state={...}` on the agent → copied (deep copy since 0.14.23) into `ctx.store["state"]` at run start (`base_agent.py:302-303`).
- `await ctx.store.set(...)` on a `Context` you create and pass with `ctx=`.
- `**kwargs` that the start event captures.
- `Memory.session_id` — a single string you can encode `tenant:user:conversation` into.

Because `initial_state` lives on the agent instance, per-tenant identity via `initial_state` means one agent instance per request (cheap: agents are Pydantic objects). Passing a pre-populated `Context` lets you reuse one agent instance.

### 6.2 Tenant identity propagation into tool calls

If your tool function declares `ctx: Context` as a parameter, the workflow injects the live `Context`:

```python
# llama-index-core/llama_index/core/agent/workflow/base_agent.py:357-374
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

The tenant-identity object is the `Context` (if declared). Note the merge order: `{**self._field_defaults, **self.partial_params, **kwargs}` means **LLM-provided `kwargs` win over `partial_params`**. So `partial_params` is a default, not an override. This is a critical gotcha for 6.4.

### 6.4 Forcing tool arguments from the harness

⚠️ **Partial workaround only.**

LlamaIndex provides `FunctionTool(partial_params={...})` (`function_tool.py:87`). Those parameters are removed from the JSON schema the LLM sees (`function_tool.py:240`), but `call`/`acall` merges `{**_field_defaults, **partial_params, **kwargs}` (line 376), so **if the LLM still emits the field (hallucination, prompt injection), the LLM value wins**. `partial_params` is therefore a hidden default-filler, not a force-override. The same applies to the MCP integration's `global_partial_params` / `partial_params_by_tool` (`llama-index-integrations/tools/llama-index-tools-mcp/llama_index/tools/mcp/base.py:42-49, 143-150`), which feed `FunctionTool.partial_params`.

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

Pattern B is the idiomatic LlamaIndex answer. It's effective but it's still **convention**, not enforcement — a forgetful tool author can read `tenant_id` from the LLM-provided args by accident. A universal override is possible by subclassing the agent and overriding the `call_tool` step (`base_agent.py:634`) to rewrite `ev.tool_kwargs` before dispatch.

### 6.5 Tenant-aware visible tool selection

Done at construction or via `tool_retriever`:

- **Static**: pass only the allowed tools to the agent: `FunctionAgent(tools=[topic_search, iab_search, audience_create], ...)`.
- **Dynamic at session start**: build a per-request agent instance with a tenant-filtered `tools` list.
- **Dynamic per turn**: pass a `tool_retriever: ObjectRetriever` (`base_agent.py:105-108`) that LlamaIndex calls each turn with the current `user_msg_str`:
  ```python
  # base_agent.py:283-292
  async def get_tools(self, input_str=None):
      tools = [*self.tools] if self.tools else []
      if self.tool_retriever is not None:
          retrieved_tools = await self.tool_retriever.aretrieve(input_str or "")
          tools.extend(retrieved_tools)
      return self._ensure_tools_are_async(cast(List[BaseTool], tools))
  ```
  `get_tools` receives only the input string, not the `Context`, so a per-tenant retriever must be bound at agent construction time.
- **MCP**: `McpToolSpec(allowed_tools=[...])` filters what an MCP server exposes.

There is no registry-level "tenant X may see tool Y" primitive — Not provided — BYO.

### 6.6 Per-tool-call auth propagation

Auth identity is whatever you stash in `ctx.store` and read inside the tool. There is no built-in identity propagation from an outer HTTP handler, and no per-tool credential binding.

### 6.7 Per-tenant rate limit + budget cap

`TokenCountingHandler` has a `token_budget` parameter (`llama-index-core/llama_index/core/callbacks/token_counting.py:153, 167, 195-199`) that raises `ValueError` if exceeded — but it's per *handler instance*, not per tenant, and it counts tokens (not USD). Individual LLM classes accept a `rate_limiter` (checked in `llama-index-core/llama_index/core/llms/callbacks.py`), again per LLM instance. 🔴 **No USD budget cap, no per-tenant quota.**

### ⭐ Light usage example (Q6)

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.workflow import Context
from llama_index.llms.openai import OpenAI

# Step 1: pass tenantId / userId / targetingStrategyId via initial_state
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

`initial_state` is deep-copied into `ctx.store["state"]` (`base_agent.py:303`). Tools read tenant from there. The LLM never sees `tenant_id` in the tool schema because `Context` params are excluded by `function_tool.py:204-247`. Step 3 is enforced by convention inside the tool body, not by the harness.

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
| `FunctionTool(partial_params={...})` | Before each tool call | Provide hidden default kwargs (LLM-provided values still win) |
| `llama-index-instrumentation` dispatcher (`Dispatcher.event_handlers` + `span_handlers`) | Every event / every span | Read-only — for tracing, not mutation |
| `system_prompt` on the agent | Once per LLM call (prepended) | Inject system context |
| `state_prompt` template + `initial_state` | Format `{state}` into the last user message before the first LLM call (`base_agent.py:458-468`) | Inject runtime state into the LLM input |

### 7.2 Hook concurrency model

There's no formal hook fan-out. Workflow `@step` methods run on the asyncio event loop and are scheduled deterministically by the upstream `workflows` runtime. Dispatcher event handlers fire synchronously when an event is dispatched.

### 7.3 Specific capability tests

- **Inject system messages at session start**: ✅ Via `system_prompt=` on the agent (`base_agent.py:99, 452-457`) or by overriding `setup_agent` step.
- **Expand user input** (slash, timestamp, attachments): ✅ Override `init_run` to mutate `user_msg`.
- **Mutate messages list before each LLM call**: ✅ Override `setup_agent` or `run_agent_step`. No first-class "preStep" hook though — you subclass.
- **Mutate tool input before dispatch**: ⚠️ `FunctionTool.partial_params` only acts as a default-filler; for a true override you wrap in a closure or read from `Context`. Override `call_tool` step for the universal version.
- **Mutate tool result before it returns to the LLM**: ✅ `FunctionTool(callback=...)` returning a new `ToolOutput` (`function_tool.py:151-169`); or override `aggregate_tool_results`.
- **Emit additional tool calls from a `PostToolUse` hook**: ❌ Not as a first-class hook — but workflows can `ctx.send_event(ToolCall(...))` from any `@step`, which the runtime will route. You'd subclass `aggregate_tool_results` to do this.

### 7.4 Auto-compaction

`Memory` has a token-budget-driven FIFO flush (`memory.py:205-220` fields; `_manage_queue` at `memory.py:672`): when the chat history exceeds `chat_history_token_ratio * token_limit`, oldest messages are flushed into the memory blocks. `ChatSummaryMemoryBuffer` (deprecated) does explicit summarization. `Memory.memory_blocks` lets you plug in `FactExtractionMemoryBlock` to summarize ejected messages; since 0.14.24 its condense step no longer wipes stored facts on an empty/unparsable LLM response (`memory_blocks/fact.py:160-166`).

### 7.5 Prompt cache optimization

Not first-class. `ChatMessage` supports a `CachePoint` content block (`llama-index-core/llama_index/core/base/llms/types.py:28` import + class), which providers like Anthropic / OpenAI honor — but the framework does not auto-place breakpoints; the developer inserts them.

### 7.6 Tool result clearing

Not provided — BYO. There is no API to remove or stub an earlier tool result in `Memory`; you would subclass `Memory` / write to the chat store directly (`AsyncDBChatStore.set_messages`, `base_db.py:68`) to rewrite history.

### 7.7 Progressive disclosure

Not provided — BYO. You can return a summary string from a `FunctionTool` `async_callback` and stash the full payload elsewhere (e.g. in `ctx.store` or a blob store), then expose a second tool to re-read it.

### 7.8 Architectural diagram

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

**Not in `llama-index-core`** — core is library-only. Two vendor options exist:

- **In this repo**: `llama-index-protocols-ag-ui` (v0.5.0) — a FastAPI `APIRouter` that exposes one `POST /run` endpoint speaking the AG-UI protocol over SSE (`llama-index-integrations/protocols/llama-index-protocols-ag-ui/llama_index/protocols/ag_ui/router.py:48-132`). It runs its own `AGUIChatWorkflow` (a function-calling loop with backend and frontend tools, `agent.py:150`), not `FunctionAgent`/`AgentWorkflow`, unless you pass a `workflow_factory` returning a workflow that emits AG-UI events.
- **Separate repo**: `llama-agents-server` (Starlette; REST API for running, streaming and managing workflows; NDJSON or SSE; HITL; SQLite or BYO store; debugger UI at `/`). Not analysed at code level.

`llama_deploy` is deprecated. For most teams with custom auth/tenancy needs the path is still: wrap `workflow.run(...)` in your own FastAPI route and expose `handler.stream_events()` over SSE.

### 8.2 HTTP streaming protocol (SSE/WS)

- Core: BYO. Common pattern is FastAPI + SSE reading `handler.stream_events()`.
- AG-UI router: SSE (`StreamingResponse(..., media_type="text/event-stream")`, `router.py:96`), one AG-UI event per frame via `workflow_event_to_sse` (`utils.py`).
- `llama-agents-server`: NDJSON or SSE (per its README).

### 8.3 HTTP endpoints that start an agent run

- Core: BYO. No defined API contract.
- AG-UI router: `POST /run` with an AG-UI `RunAgentInput` body (`thread_id`, `run_id`, `messages`, `tools`, `state`, …) (`router.py:52-59`). No tenant header handling.

### 8.4 Interrupt / cancel in-flight run

`WorkflowHandler` (from `workflows`) exposes `cancel_run()`. Core: wire it to your own endpoint. AG-UI router: no cancel endpoint; it calls `handler.cancel_run()` only when the stream errors (`router.py:85-94`).

### 8.5 Resume / replay endpoint

Pattern: serialize `Context` to your store keyed by `session_id`, look it up on the next request, pass `ctx=` to `workflow.run(...)`. See `docs/src/content/docs/framework/understanding/agent/state.md:60-77`. The AG-UI router is stateless per request (the client sends full `messages` and `state` each call). No replay endpoint in this repo.

### 8.6 HITL approval workflow

First-class in-process via `Context.wait_for_event(...)`:

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

The client receives the `InputRequiredEvent` on the stream and replies via `handler.ctx.send_event(HumanResponseEvent(response="yes", user_name="Laurie"))`. The tool resumes. Over HTTP the host routes the approval verdict to that `send_event(...)` call (BYO in core). The AG-UI router models approvals as **frontend tools**: the run ends after emitting the frontend tool call, and the client sends the result back in the next `POST /run` (`agent.py:299-345, 453-457`). Since workflows 2.25, a run's timeout accumulates across resumes, so long HITL pauses with many resumes can now time out.

### 8.7 Token streaming

- Text delta: `AgentStream.delta` per token (`base_agent.py:340-350`).
- Partial tool args: `AgentStream.tool_calls` carries the tool calls as the LLM integration parses them during streaming; granularity depends on the integration. The default AG-UI workflow does **not** stream partial args: it emits one `ToolCallChunk` per call with the complete JSON args after the LLM turn ends (`agent.py:327-333`). Text is streamed as `TextMessageChunk` per token (`agent.py:282`).
- Agent activity: `ToolCall`, `ToolCallResult`, `AgentInput`/`AgentOutput` events (Q3.6). On the wire, BYO serialization via `event.model_dump_json()` (each `Event` is a Pydantic model). The AG-UI router encodes events with the AG-UI SDK's `EventEncoder` (`utils.py:434-435`) and adds `StateSnapshot` / `MessagesSnapshot` frames.

Illustrative AG-UI frames (router output; field set abbreviated):

```
data: {"type":"RUN_STARTED","threadId":"t1","runId":"r1",...}
data: {"type":"TEXT_MESSAGE_CHUNK","messageId":"m1","delta":"Looking"}
data: {"type":"TOOL_CALL_CHUNK","toolCallId":"call_abc","toolCallName":"topicSearch","delta":"{\"query\":\"sports\"}"}
data: {"type":"RUN_FINISHED","threadId":"t1","runId":"r1"}
```

### 8.8 Authentication & Authorisation

Not provided — BYO. Neither core nor the AG-UI router terminates auth or extracts tenant identity; you add FastAPI dependencies yourself.

### 8.9 Tool-call state reconstruction

⭐ Events carry `tool_id`. `ToolCall.tool_id` and `ToolCallResult.tool_id` match (`workflow_events.py` `ToolCall` / `ToolCallResult` types). The client links them by explicit `tool_id`; no positional dependency. AG-UI frames carry `toolCallId`; the integration now raises instead of fabricating a missing `tool_call_id` (#22103).

### 8.10 Health checks / graceful shutdown

Not provided — BYO.

### ⭐ Light usage example (Q8)

Because core is library-only, this is illustrative of the BYO pattern (FastAPI):

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

Alternative with the in-repo AG-UI integration (no tenant header handling, no cancel, HITL via frontend tools):

```python
from llama_index.protocols.ag_ui.router import get_ag_ui_workflow_router
app.include_router(get_ag_ui_workflow_router(llm=llm, backend_tools=[topic_search],
                                             frontend_tools=[approve_audience]))
# curl -N -X POST http://host/run -d '{"threadId":"t1","runId":"r1","messages":[...],...}'
```

Cancel and HITL approval endpoints: Not provided — BYO. You plumb `handler.cancel_run()` and `handler.ctx.send_event(HumanResponseEvent(...))` into your own routes.

## 9. Sub-agents

### 9.1 Mechanism

Both supported:

1. **First-class `AgentWorkflow` + `can_handoff_to`** — declare a set of `FunctionAgent`s, configure who can hand off to whom, and `AgentWorkflow` injects an auto-generated `handoff(to_agent, reason)` tool (`multi_agent_workflow.py:73-92, 216-246`). The active agent can stop the chain or call `handoff`.

2. **Agents-as-tools** — each sub-agent's `.run(...)` is wrapped in a function and registered as a `FunctionTool` on a parent (`docs/src/content/docs/framework/understanding/agent/multi_agent.md:86-184`).

### 9.2 Configuration

Python objects only. No markdown manifest. Each agent is a `FunctionAgent` / `ReActAgent` / `CodeActAgent` instance with `name`, `description`, `system_prompt`, `tools`, `can_handoff_to`, `llm`, and optionally `output_cls` / `structured_output_fn`.

### 9.3 LLM-generated configs

Not first-class. You can build a `FunctionAgent` dynamically inside a tool, but there's no markdown-loader analogue to Claude's `Task` tool.

### 9.4 Output handling

For `AgentWorkflow`: handoff returns a string from the `handoff` tool, which causes the workflow to switch `current_agent_name` (`multi_agent_workflow.py:87-92`) and re-enter `setup_agent` with the new active agent. The final `StopEvent.result` is an `AgentOutput`. Since 0.14.24, if the `AgentWorkflow` defines no `output_cls`/`structured_output_fn`, the active agent's own structured-output config is used, so `AgentOutput.structured_response` is populated per agent (`multi_agent_workflow.py:579-590`, #22162).

For agents-as-tools: the sub-agent's `.run(...)` is awaited; its result string is returned to the parent LLM as a normal tool result. The sub-agent's `ToolCallResult` is linked back to the parent via `tool_id`.

### 9.5 Concurrency model

`AgentWorkflow` is **serial** — only one agent active at a time (it's a sequential hand-off swarm).

Parallel sub-agents happen with the **agents-as-tools** pattern: the parent LLM emits multiple tool calls, and `parse_agent_output` fans them out via `ctx.send_event(ToolCall(...))` (`base_agent.py:621-630`). The `workflows` runtime executes them in parallel; `ctx.collect_events(...)` fans them back in (`base_agent.py:680-682`). For three persona sub-agents called concurrently, the parallelism point is **`base_agent.py:624` (the for-loop emitting one event per call)** plus the runtime's parallel `@step` execution.

### 9.6 Context isolation

Each sub-agent invocation via `.run(...)` gets its own `Context` (default) — fresh memory, fresh state (deep-copied `initial_state`). Or you can pass `ctx=parent_ctx` to share state.

### 9.7 Lifecycle events

When `AgentWorkflow` hands off, `AgentInput` / `AgentOutput` / `AgentStream` events tagged with the new `current_agent_name` are emitted on the stream. The parent stream sees each sub-agent's tokens. For agents-as-tools, the parent stream only sees the `ToolCall`/`ToolCallResult` pair unless you forward the child handler's events yourself (`ctx.write_event_to_stream` inside the wrapper tool).

### 9.8 Sub-agent model override

✅ Each agent has its own `llm` field (`base_agent.py:112-114`). In `AgentWorkflow`, `self.agents = {cfg.name: cfg for cfg in agents}` (`multi_agent_workflow.py:141`) and each `cfg.llm` is independent, so a Sonnet orchestrator with Haiku workers is a matter of passing different `llm=` objects. Same for agents-as-tools.

### ⭐ Light usage example (Q9)

Three persona sub-agents invoked in parallel via the agents-as-tools pattern:

```python
from llama_index.core.agent.workflow import FunctionAgent, ToolCallResult
from llama_index.core.workflow import Context

def make_persona(name, prompt):
    return FunctionAgent(
        name=name,
        description=f"Persona: {name}",
        system_prompt=prompt,
        llm=worker_llm,                  # can differ from the parent's llm (Q9.8)
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

Not provided — BYO. The closest first-party mechanism is `tool_retriever: ObjectRetriever` on a `FunctionAgent` (`base_agent.py:105-108`), which lets you dynamically retrieve tools from a vector store per request — but those are tools, not skills.

### 10.4 Invocation

N/A.

### 10.5 Loading mode

N/A.

### 10.6 Skill composition

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

### 11.5 Scoping

Not provided — BYO. No publish-time tenant scope and no runtime enforcement; you either pass tenant-scoped tool lists at agent construction or filter in your `tool_retriever` (Q6.5).

### 11.6 Deployment workflow

Not provided — BYO. LlamaHub was a directory of community packs with no draft/review/promote workflow, and its links have now been retired from the docs (PR #23070). `llamactl` (separate repo) deploys whole agent apps, not individual resources.

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

- **`llama-index-instrumentation`** (extracted from core in 2025 — `CHANGELOG.md:5336` "feat: support custom span processor; refactor: use llama-index-instrumentation instead of llama-index-core" #20732; now 0.6.0 in core's lockfile). Dispatcher tree with event/span handlers (`llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py:50`). Async-task and thread safe — preserves trace trees across coroutines.
- **OTel exporter**: `llama-index-observability-otel` (`llama-index-integrations/observability/llama-index-observability-otel/`) — bridges spans to any OTel-compatible backend (Datadog, Honeycomb, Jaeger, etc.). Span-ID / parent-context handling was fixed in #22485 (`otel/base.py:112-136`: `capture_propagation_context` / `restore_propagation_context` / `_get_parent_context`).
- **First-party integrations** (callback packages): Arize Phoenix, Langfuse, Opik, OpenInference, PromptLayer, UpTrain, W&B, HoneyHive, Literal AI, Argilla — 10 in `llama-index-integrations/callbacks/` (AgentOps and AIM were removed in this window) plus the OTel package.

### 12.6 Audit logging (who / when / what)

Not first-class. The instrumentation event stream + your own sink (Postgres / S3) is the recommended approach. Not tamper-evident out of the box. Since 0.14.23, LLM start events and callback payloads use `BaseLLM.to_payload()` (`llama-index-core/llama_index/core/base/llms/base.py:58-66`; used at `llms/callbacks.py:57, 158, 321`), a non-sensitive model/metadata dict, instead of the full serialized LLM with only `api_key` popped. Before this, other auth fields (custom headers, secondary keys) could reach trace sinks. This matters if traces go to a shared backend.

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

For real tools, you install integration packages from `llama-index-integrations/tools/` (67 packages):

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

Quality: the web/file tools are thin wrappers around vendor APIs. There is no equivalent to Claude Code's `Edit` (anchor matching), `Read` (line numbers), `Monitor` (line-event streaming). For our use case (agent piloting skills), you would write your own.

### 13.2 Tool authoring API

The smallest possible tool is a typed Python function:

```python
# Method 1 — pass a callable, framework wraps it
async def topic_search(query: str) -> list[str]:
    """Search topics by keyword.

    Args:
        query: free-text keyword to match against topic names.
    """
    return await db.search(query)

agent = FunctionAgent(tools=[topic_search], llm=llm)
# Internally: FunctionTool.from_defaults(fn=topic_search) — see base_agent.py:217-242
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
    partial_params={"k": 10},             # hidden default arg (not a force-override)
)
```

JSON schema is auto-generated from the function signature + type hints via `create_schema_from_function` (`llama-index-core/llama_index/core/tools/function_tool.py:242` + `llama-index-core/llama_index/core/tools/utils.py:23-110`). Two fixes in this window improve the generated schema: docstring `Args:` descriptions now actually reach the JSON schema (they were previously assigned after model creation and silently dropped; `utils.py:37-41, 76-77, 98-105`, #22552), and `*args`/`**kwargs` are no longer emitted as required parameters (`utils.py:52-56`, #22135).

Typed I/O: runtime validation via Pydantic. `create_schema_from_function` builds a `BaseModel` subclass; on invalid LLM args the call raises a Pydantic `ValidationError`, which is caught by `_call_tool` and wrapped in a `ToolOutput(is_error=True, content=str(e), ...)` (`base_agent.py:375-391`).

### 13.3 Streaming tools

Tools can write to the event stream via `ctx.write_event_to_stream(...)` inside the tool body (because they receive the live `Context`):

```python
async def long_task(ctx: Context) -> str:
    for i in range(10):
        ctx.write_event_to_stream(ProgressEvent(pct=i*10))
        await asyncio.sleep(1)
    return "done"
```

This emits custom events to the consumer mid-tool-execution. Tools don't *yield* partial results back to the LLM mid-call though — the tool returns once.

### 13.4 Tool sandboxing / permission model

- **Permission model**: No `canUseTool`-style hook. Permission is enforced by what tools you put in the `tools=[...]` list at agent construction (and `allowed_tools=` for MCP). Inside a tool, you can `raise` to refuse — but no declarative ACL. A universal gate is possible by overriding the `call_tool` step.
- **Default posture**: Default-allow. Whatever you pass to `tools=[...]` is callable.
- **Sandbox providers**:
  - `llama-index-tools-code-interpreter` — local Python (not sandboxed by default).
  - `llama-index-tools-azure-code-interpreter` — Azure-hosted sandbox.
  - `llama-index-tools-aws-bedrock-agentcore` — Bedrock AgentCore.
  - E2B / Daytona / Modal: no first-party packages found.

## 14. MCP (Model Context Protocol) Support

### 14.1 MCP client support

✅ First-party via `llama-index-tools-mcp` (v0.6.0, `llama-index-integrations/tools/llama-index-tools-mcp/`), now built on the **`mcp` 2.x SDK** (`pyproject.toml:44` `mcp>=2.0.0,<3`; migration in #22557). `McpToolSpec` consumes any `mcp.ClientSession` and exposes its tools as `FunctionTool`s (`base.py:19`):

```python
# llama-index-integrations/tools/llama-index-tools-mcp/llama_index/tools/mcp/utils.py:66-74
client = client or BasicMCPClient(command_or_url)
tool_spec = McpToolSpec(
    client,
    allowed_tools=allowed_tools,
    global_partial_params=global_partial_params,
    partial_params_by_tool=partial_params_by_tool,
    include_resources=include_resources,
)
return await tool_spec.to_tool_list_async()
```

The 2.x migration is a breaking dependency change for hosts that also pin `mcp` 1.x elsewhere.

### 14.2 MCP server support

✅ `workflow_as_mcp(workflow)` (`utils.py:77-141`) wraps any `Workflow` (including an `AgentWorkflow`) as an MCP server (now the `mcp` SDK's `MCPServer` class, previously `FastMCP`), exposing it as a single tool. Streams workflow events as MCP log messages (`utils.py:135-137`).

### 14.3 Transports

stdio, SSE, streamable_http — all supported by `BasicMCPClient` (`client.py:21-23`):

```python
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
```

The client picks based on URL: `…/sse` → SSE, `?transport=sse` → SSE, otherwise streamable_http; command-line strings → stdio (`client.py:53-65, 229-274`). The streamable-HTTP client uses `httpx2` since the 2.x migration.

### 14.4 In-process MCP

✅ via `workflow_as_mcp(workflow)` — a Python function or workflow becomes an MCP tool without spawning a subprocess (it runs in the same `MCPServer` process).

### 14.5 Auth / lifecycle

OAuth is supported through `OAuthClientProvider` and a `TokenStorage` interface (`client.py:24-25, 68-...`). `DefaultInMemoryTokenStorage` is the default; production deployments implement their own to persist tokens. Custom `headers=` and a caller-supplied `http_client` are accepted for SSE / streamable HTTP. A new session is opened per call (`client.py:229-274`); no pooled reconnection or health checks.

## 15. Multi-model Routing & Fallback

### 15.1 Multi-provider support

✅ Extensive. 101 LLM integration packages under `llama-index-integrations/llms/` — Anthropic, OpenAI, Azure OpenAI, Bedrock, Bedrock Converse, Vertex, Google GenAI, Cohere, Mistral, Groq, Together, Fireworks, DeepSeek, Cerebras, Databricks, Cloudflare AI Gateway, Heroku, HuggingFace, IBM, Ollama, vLLM, and many more. New-model support continues to land quickly in the main provider packages (e.g. Claude Opus 5.5 / Sonnet 5.5 and GPT-6 in late September 2026). Each agent has its own `llm:` field, so per-task model selection is "pick a different `LLM` object per agent"; there is no first-party `Router` abstraction (cheap-for-triage / expensive-for-hard).

### 15.2 Automatic fallback chain

Not first-class in core. There is `llama-index-llms-cloudflare-ai-gateway` (integration) which Cloudflare's AI Gateway provides; for general fallback you wrap an `LLM` with retry/fallback logic yourself.

### 15.3 Mid-stream model switching

Per-turn switch supported — change the `llm` attribute on the agent (or use sub-agents on different models). Mid-token switch is not supported.

## 16. Chat UI Layer

### 16.1 Generative UI components

Not first-party in Python. `llama_index.core.chat_ui` contains only typed events and an artifact model (`chat_ui/events.py:1-19`: `UIEvent`, `SourceNodesEvent`, `ArtifactEvent`; `chat_ui/models/artifact.py`), which you forward to your own UI. The separate `@llamaindex/chat-ui` npm package (https://github.com/run-llama/chat-ui) renders them (out of scope here).

### 16.2 Tool call rendering primitives

Not provided in core — BYO. With the AG-UI integration (Q8.1) the stream conforms to the AG-UI protocol, so any AG-UI client (e.g. CopilotKit, whose guide is linked from the docs' full-stack apps page) can render tool-call start/args/end frames.

### 16.3 Streaming chat hook

Not first-party in this repo. Via `@llamaindex/chat-ui` (separate repo) or an AG-UI client consuming the AG-UI router.

### 16.4 BYO pattern

Parse `handler.stream_events()` server-side into SSE; render in your own React (or Vue/HTMX) frontend. Or mount the AG-UI router and use an AG-UI-compatible frontend.

## 17. Memory & Knowledge

### 17.1 Long-term memory / semantic recall

✅ First-class. `Memory.memory_blocks` (`memory.py:217-220`) accepts `BaseMemoryBlock` subclasses:

- `StaticMemoryBlock` — fixed system content (e.g. tenant facts).
- `VectorMemoryBlock` — vector search over past messages (`memory_blocks/vector.py`).
- `FactExtractionMemoryBlock` — LLM-extracted facts (`memory_blocks/fact.py`). Its condense prompt now asks for a full snapshot and the block keeps existing facts if the condense response is empty (`fact.py:38-60, 160-166`, #22213).

Blocks are processed in priority order; ejected short-term messages are pushed into blocks (`memory.py:151-165`). The memory-blocks template now also renders URL-backed video and document blocks (`memory.py:71-78`).

### 17.2 RAG / knowledge retrieval integration

This is LlamaIndex's historical core competency. Vector stores: ~78 integrations under `llama-index-integrations/vector_stores/`. Index types: VectorStoreIndex, SummaryIndex, TreeIndex, KeywordTableIndex, KnowledgeGraphIndex, PropertyGraphIndex, ComposableIndex. Retrieval primitives: `BaseRetriever`, `RouterRetriever`, `FusionRetriever`. Citations: built-in via `CitableBlock` / `CitationBlock`; `CitationQueryEngine` now gives each citation node its own id and offsets (#22537). Multimodal query engines were added in 0.14.23. The vendor now positions LlamaParse as the ingestion front-end for these indexes (`docs/src/content/docs/framework/index.mdx`).

For agent use: expose retrieval as a `QueryEngineTool` and let the LLM call it.

### 17.3 Per-tenant memory scoping

`Memory.session_id` is the only first-class scoping key. For per-tenant separation, encode `tenant:user:session` in `session_id`, use a per-tenant `SQLAlchemyChatStore` instance (different DB, table, or schema via `db_schema=`, `memory.py:310`), or pass a tenant-aware `AsyncDBChatStore` via `chat_store=` (`memory.py:305`).

## 18. Safety & Policy

### 18.1 Input/output guardrails

Not first-party in core. The `llama-index-integrations` ecosystem includes `llama-index-guardrails` (PyPI) and integrations with Guardrails AI, NeMo Guardrails, etc. No first-party PII redaction, prompt-injection or hallucination detection on the agent loop. (Tool sandboxing and default posture: see Q13.4.)

## 19. Eval, Testing & CI Gates

### 19.1 Golden datasets / regression suites

✅ Built-in evaluation primitives in `llama-index-core/llama_index/core/evaluation/`. Includes:
- `RetrieverEvaluator`, `RelevancyEvaluator`, `FaithfulnessEvaluator`, `CorrectnessEvaluator`, `AnswerRelevancyEvaluator`, `GuidelineEvaluator`, `SemanticSimilarityEvaluator`, `BatchEvalRunner`.
- Dataset generation: `RagDatasetGenerator`, `LabelledRagDataset`.

These are heavily RAG-oriented; for agent-behavior eval you mostly compose primitives yourself or use Phoenix/Langfuse/Opik. For unit tests, `MockFunctionCallingLLM` can now emit tool calls (`llama-index-core/llama_index/core/llms/mock.py:294-360`, #21732), which makes deterministic agent-loop tests possible without a provider.

### 19.2 LLM-as-judge scoring

✅ Each of the above evaluators uses an LLM as judge against a rubric.

### 19.3 CI eval gates / pre-merge

Not provided — BYO. You wire `BatchEvalRunner` into your CI.

### 19.4 Trace replay for skill iteration

Not provided — BYO. Phoenix/Langfuse/Arize integrations provide their own UIs.

## 20. Local Sandbox & Dev UX

### 20.1 Local agent runner

Not provided as a CLI/playground in `llama-index-core`. You run agents in a Jupyter notebook or a script. The `llama-index-cli` package exists (separate) but is focused on document indexing, not agent chatting. The external `llamactl serve` (llama-agents repo) runs workflow apps locally, and `llama-agents-server` mounts a debugger UI at `/`.

### 20.2 Trace inspection

Via the OTel exporter into your tracing backend (Phoenix, Jaeger, Langfuse, etc.). No local TUI viewer in this repo.

### 20.3 Tenant / org switching

Not provided — BYO.

### 20.4 Hot reload

Not provided in this repo. Python reload is standard `importlib.reload` / `jurigged` if you want it. `llamactl` (external) advertises local development with hot reload.

## Architectural diagram

```mermaid
flowchart TB
    subgraph host["Host Python process (asyncio)"]
        api["BYO HTTP server (FastAPI / Flask)<br/>or AG-UI router or llama-agents-server"] -->|workflow.run| handler[WorkflowHandler]
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
        mem --> sql[AsyncDBChatStore<br/>default SQLAlchemyChatStore]
        wf -->|write_event_to_stream| dispatcher[llama_index_instrumentation<br/>Dispatcher]
        dispatcher --> otel[OTel exporter / Langfuse /<br/>Arize / Opik / Phoenix]
    end

    sql -->|asyncpg/aiosqlite| db[(Postgres / SQLite / MySQL / custom)]
    otel --> backend[(Tracing backend)]
    llm --> providers["~100 LLM integration packages<br/>(OpenAI, Anthropic, Bedrock, …)"]
    call --> mcp["MCP client (mcp 2.x) → external MCP servers<br/>(stdio / SSE / streamable_http)"]
```

## Appendix — Files worth reading first

- `llama-index-core/llama_index/core/agent/workflow/base_agent.py:393-735` — the run loop's `@step` graph (init_run → setup_agent → run_agent_step → parse_agent_output → call_tool → aggregate_tool_results). This is the heart of the agent.
- `llama-index-core/llama_index/core/agent/workflow/function_agent.py:101-196` — `FunctionAgent.take_step` / `handle_tool_call_results` / `finalize`.
- `llama-index-core/llama_index/core/agent/workflow/multi_agent_workflow.py:73-92, 216-246` — handoff tool generation; multi-agent orchestration.
- `llama-index-core/llama_index/core/agent/workflow/workflow_events.py:1-146` — all agent-level event types (`AgentInput`, `AgentOutput`, `AgentStream`, `ToolCall`, `ToolCallResult`, `AgentWorkflowStartEvent`).
- `llama-index-core/llama_index/core/workflow/__init__.py:1-22` — the thin re-export from the upstream `workflows` package.
- `llama-index-core/llama_index/core/tools/function_tool.py:71-411` — `FunctionTool`, `partial_params`, `callback`, Context injection.
- `llama-index-core/llama_index/core/memory/memory.py:188-342` — `Memory` class with `memory_blocks`, pluggable `AsyncDBChatStore`, session_id.
- `llama-index-core/llama_index/core/storage/chat_store/base_db.py:19-99` — `AsyncDBChatStore` interface for custom memory backends.
- `llama-index-integrations/tools/llama-index-tools-mcp/llama_index/tools/mcp/base.py:19-160` — MCP client; `client.py:229-274` for transports; `utils.py:77-141` for `workflow_as_mcp` server.
- `llama-index-integrations/protocols/llama-index-protocols-ag-ui/llama_index/protocols/ag_ui/router.py:48-132` — the only HTTP route shipped in this repo (AG-UI over SSE).
- `llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py:36-80` — instrument_tags + Dispatcher (the OTel-friendly tracing layer).
- `llama-index-integrations/observability/llama-index-observability-otel/llama_index/observability/otel/base.py:48-...` — OTel span handler.
- `docs/src/content/docs/framework/understanding/agent/human_in_the_loop.md:1-90` — HITL pattern via `ctx.wait_for_event` + `InputRequiredEvent` / `HumanResponseEvent`.
- `docs/src/content/docs/framework/understanding/agent/multi_agent.md:1-413` — the three multi-agent patterns (AgentWorkflow, orchestrator, custom planner).
- `README.md:10-15` and `CHANGELOG.md:55-61, 685-704, 903-921` — the strategic-focus note and the three releases since 0.14.22.
