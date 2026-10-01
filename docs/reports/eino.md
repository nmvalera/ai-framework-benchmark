# Eino (Go) — Benchmark Analysis

> **Repo**: https://github.com/cloudwego/eino (core), https://github.com/cloudwego/eino-ext (extensions)
> **Commit analysed**: eino `58d184303f4e73413c454a9626f79c17af0fd9fb` (v0.9.21+1, Sep 29 2026 — "docs: fix README diagram links"); eino-ext `3603a39473c3e7b2aa3bfc11216487c94b8c7fd9` (Sep 24 2026 — "feat: propagate cache write token usage")
> **Branch**: `main` (both)
> **Framework path**: `frameworks/eino/` (core), `frameworks/eino-ext/` (extensions)
> **Analysed on**: 2026-10-01

## TL;DR

- **What is this stack architecturally**: Eino is a Go-native **library** (no daemon, no CLI, no first-party HTTP server) split into two layers stacked in the same binary: (1) a low-level **graph / chain orchestration engine** (`compose/`) that compiles `Graph[I, O]` / `Chain[I, O]` into a `Runnable[I, O]` with Pregel-style super-steps and DAG modes, and (2) a higher-level **ADK** (`adk/`) on top of the graph engine that ships `ChatModelAgent` (built-in ReAct loop), `Runner`, `AsyncIterator[AgentEvent]`, agents-as-tools, prebuilt patterns (`deep`, `planexecute`, `supervisor`) and, since v0.9, a long-lived **`TurnLoop`** runtime and a first-class **cancel** API. The ADK is the "Claude-Code-shaped" layer; the graph engine is the LangGraph-shaped layer. Both live in your Go process.
- **Ecosystem**: **Go** (single-language). Core `eino/go.mod:3` declares `go 1.18`; several eino-ext modules require newer toolchains (e.g. `adk/backend/local/go.mod` declares `go 1.25.0`).
- **Open-source / support**: Apache-2.0, owned by CloudWeGo (ByteDance). Community support only (GitHub issues + Lark group); no managed cloud.
- **Maturity / adoption (captured 2026-10-01)**: ~22 months old (repo created Dec 4 2024). Still pre-v1: v0.9.0 shipped May 24 2026 and 22 v0.9.x patch tags followed through v0.9.21 (Sep 23 2026); a v0.10 line is in parallel alpha (`v0.10.0-alpha.35`, branch `alpha/10`, not on `main`). `cloudwego/eino`: 13.2k stars, 1.1k forks, 41 contributors. `cloudwego/eino-ext`: 815 stars, 372 forks, 82 contributors.
- **Where the agent loop actually executes**: in-process, in your Go binary. No subprocess, vendor daemon or hosted service. `TypedChatModelAgent.Run` (`adk/chatmodel.go:1446`) returns an `*AsyncIterator[*TypedAgentEvent[M]]`; the loop runs in a goroutine that drives a compiled `compose.Graph` (`adk/react.go:354`). `Runner.Run` / `Query` / `Resume` / `ResumeWithParams` (`adk/runner.go:102-149`) are the public surface.
- **Strongest architectural choice for our use case**: **durable interrupt / resume / cancel is first-class and granular**. `ResumableAgent`, `Runner.ResumeWithParams` (`adk/runner.go:147`) and per-call address segments let you suspend mid-tool-call, persist the full ADK state tree (including parallel sub-agent lanes) and resume any specific component by its address. v0.9 adds `WithCancel()` (`adk/cancel.go:239`) with safe-point modes (`CancelAfterChatModel`, `CancelAfterToolCalls`, immediate, recursive, timeout escalation) that **checkpoints on cancel** (`adk/runner.go:293-303`), and `TurnLoop` (`adk/turn_loop.go:896`) which turns one-shot runs into a push-driven multi-turn session loop with preemption, between-turn checkpoints and automatic checkpoint deletion on clean exit.
- **Weakest / biggest gap**: **No `CheckPointStore` implementation ships with eino or eino-ext**. The interface is still two methods on `[]byte` (`internal/core/interrupt.go:31-34`) plus an optional `Delete` (`CheckPointDeleter`, `internal/core/interrupt.go:44-46`). Add: no HTTP server, no tenant model, no auth, no Resource Manager, no eval framework, no chat UI, no per-tenant cost/budget. Eino gives you the runtime; you assemble the platform. The official v0.9 quickstart states it plainly: "Memory, Session, and Store ... are business-layer concepts, not core Eino framework components".
- **Most surprising finding (good)**: the v0.9 context-engineering kit is the most complete in the Go ecosystem: `skill` (SKILL.md loader with inline / fork / fork-with-context modes), `agentsmd` (AGENTS.md injection with `@import`, byte budgets, transient injection excluded from summarization), `toolsearch` (Claude-Code-style `tool_search` with `select:` syntax, plus provider-native deferred tool search via `ChatModelAgentState.DeferredToolInfos`), `summarization`, `reduction` (truncate + offload-and-clear tool results to a backend), `filesystem` (7 tools, multimodal image/PDF read).
- **Most surprising finding (bad)**: the maintainers now mark **agent transfer and the workflow agents (`NewSequentialAgent` / `NewParallelAgent` / `NewLoopAgent`) as "NOT RECOMMENDED"** in code comments (`adk/workflow.go:630-655`, `adk/chatmodel.go:292-300`), steering users to `ChatModelAgent` + `AgentTool` or `DeepAgent`. Code written against the v0.7/v0.8 multi-agent primitives is on a deprecation path. Separately, the English/Chinese documentation imbalance persists in issue threads and some middleware docs, although the v0.9 quickstart is fully available in English.
- **Per-stack one-liners**:
  - **Sessions / persistence**: `runSession` is a run-scoped in-memory struct (`Values` + `Events`); persistence is **interface-only via `CheckPointStore`**; fires on interrupt and on cancel; `TurnLoop` adds between-turn checkpoints of queued input. BYO store implementation.
  - **Skills**: First-class via `adk/middlewares/skill/`. Filesystem backend ships; inline / fork / fork-with-context; pluggable `Backend` / `AgentHub` / `ModelHub`. `agentsmd` adds AGENTS.md-style project instructions.
  - **Resource manager**: **Not provided — BYO**. `Backend` / `AgentHub` / `ModelHub` interfaces are the seam.
  - **Sub-agents**: Recommended path is `NewAgentTool` (agents-as-tools, parallel via `ToolsNode` goroutines) or `deep.New` (task tool). `SetSubAgents` transfer and workflow agents still exist but are marked NOT RECOMMENDED.
  - **Multi-tenancy**: **No first-class tenant primitive**. `WithSessionValues(map[string]any)` (`adk/call_option.go:52`) + `context.Context`; tool-argument injection requires a `WrapInvokableToolCall` middleware or `ToolArgumentsHandler`. No declarative injected-arg mechanism.
  - **Hooks / middleware**: `ChatModelAgentMiddleware` interface with 9 methods (v0.9 adds `AfterAgent`), plus deprecated struct `AgentMiddleware`, `compose.ToolMiddleware`, and graph-level `callbacks.Handler`. Ordering documented at `adk/chatmodel.go:323-399`.
  - **API**: Library-only. **No first-party HTTP server or SSE protocol**. eino-ext now ships an **ACP (Agent Client Protocol) bridge** (`acp/`) that converts `AgentEvent` to ACP session updates; transports come from `eino-contrib/acp` (stdio, HTTP example on Hertz).
  - **Observability**: `callbacks.Handler` + `RunInfo`. eino-ext ships Langfuse (v1 and new OTLP-native v2), LangSmith, APMPlus (OTel), CozeLoop and Volcengine TLS handlers. Token counts on `schema.Message.ResponseMeta.Usage`, now including `CacheWriteTokens`. **No USD cost computation, no per-tenant rollup.**
  - **Model routing**: v0.9 adds **`ModelFailoverConfig`** (`adk/failover_chatmodel.go:128`) for automatic fallback to alternate models, alongside a richer `ModelRetryConfig.ShouldRetry`.
- **Production-readiness verdict for multi-tenant server-side deployment**: **High runtime maturity, low platform maturity**. The runtime (graph + ADK + checkpoint + cancel + TurnLoop) is well-tested and moving fast (v0.9 is a large, mostly additive release with generic `TypedXxx[M]` APIs). Everything around the runtime — HTTP, auth, tenancy, persistence backend, resource registry, eval, dev sandbox — is yours to build. **Verdict**: defensible if the platform layers already exist (Ray's case); risky greenfield if you need to ship in under two quarters. Pin minor versions: the 0.9 → 0.10 alpha line is already rewriting session events, memory and background tasks.

---

## 0. General

### 0.1 What is this stack?

A **Go library + ecosystem of adapters**. Two Go module families:
- `github.com/cloudwego/eino` — graph runtime, schema (including the new `AgenticMessage`), ADK, callbacks interface, in-tree middlewares
- `github.com/cloudwego/eino-ext` — provider adapters (chat models, agentic models, tools, retrievers, indexers), tracing exporters (Langfuse, LangSmith, APMPlus, CozeLoop, TLS), filesystem backends, an ACP bridge; each is its own Go module so you import only what you need

No daemon and no CLI subcommand runs an agent server. Everything is `import` + call.

### 0.2 Ecosystem

**Go** (primary, single-language). Core `eino/go.mod:3` declares `go 1.18`; individual eino-ext modules set their own minimums (e.g. `eino-ext/adk/backend/local/go.mod` declares `go 1.25.0`; `callbacks/langfuse/v2` documents Go 1.23+). No Python / TypeScript / Rust bindings.

### 0.3 Project status & governance

- **License**: Apache 2.0 (both `eino` and `eino-ext`).
- **Owner / maintainers**: [CloudWeGo](https://www.cloudwego.io/), an open-source initiative inside ByteDance / Volcengine. Maintainers are ByteDance engineers (commit history confirms). CloudWeGo also owns Kitex (RPC), Hertz (HTTP) and Volo (Rust RPC).
- **Commercial backing**: ByteDance, with Volcengine offering paid Ark LLM endpoints, APMPlus tracing and TLS (log/trace service), all of which have first-party eino-ext integrations.
- **Support model**: community support via GitHub issues + a Lark (Feishu) group. No paid SaaS or enterprise support around eino itself and no managed "Eino Cloud".

### 0.4 Project maturity / age

- **Initial public release**: GitHub repo created 2024-12-04; the oldest public tags (`v0.1.x`) date from that period. The framework is about 22 months old.
- **Current major version**: `v0.9.x` (v0.9.0 tagged 2026-05-24; latest v0.9.21 on 2026-09-23). A `v0.10.0-alpha.*` line (35 alphas through 2026-09-20) is developed on branch `alpha/10` and is not merged into `main`.
- **Stability signals**: still pre-`v1`, so APIs are not frozen. The v0.9 theme is "agentic-runtime": a new `AgenticMessage` content-block protocol, generic `Typed*[M]` versions of every ADK type, cancel, retry/failover and `TurnLoop`. The default `*schema.Message` path is preserved through type aliases (`type Runner = TypedRunner[*schema.Message]`, `adk/runner.go:62`), so v0.8 code mostly compiles.
- **APIs marked experimental / deprecated**: struct `AgentMiddleware` is deprecated in favour of `ChatModelAgentMiddleware` (`adk/chatmodel.go:235-237`); `ModelContext.Tools` is deprecated in favour of `ChatModelAgentState.ToolInfos` (`adk/handler.go:58-63`); agent transfer, `RunPath` and the workflow agents carry a "NOT RECOMMENDED" advisory (`adk/interface.go:313-339,425`, `adk/workflow.go:630-655`). Legacy `flow/agent/react` (`flow/agent/react/react.go:284`) remains for back-compat.

### 0.5 Adoption & community signal

Captured on **2026-10-01** via the GitHub API:
- `cloudwego/eino`: **13,219 stars**, 1,119 forks, 79 watchers, 41 contributors; 123 open issues, 103 open PRs, 300 closed issues. Last push 2026-09-29.
- `cloudwego/eino-ext`: **815 stars**, 372 forks, 9 watchers, 82 contributors; 50 open issues, 85 open PRs, 179 closed issues. Last push 2026-09-24.
- **Release cadence**: very high. 126 commits on eino `main` and 115 on eino-ext `main` between 2026-04-29 and 2026-09-29; 22 v0.9.x patch tags in four months plus a parallel alpha stream. Releases on GitHub are mostly auto-generated one-line PR lists.
- **Maintainer responsiveness**: PRs are merged within days; a notable fraction of issue conversations are in Chinese.
- **Community channels**: Lark (Feishu) group is the primary forum. A Discord exists but is materially less active.

(The previous capture on 2026-05-19 reported "~14k / ~2k stars"; those figures were estimates and are superseded by the API numbers above.)

### 0.6 Ecosystem fit

- **Package**: `github.com/cloudwego/eino` (core) and `github.com/cloudwego/eino-ext/...` (per-adapter sub-modules). Go modules on `pkg.go.dev`.
- **Registry links**:
  - <https://pkg.go.dev/github.com/cloudwego/eino>
  - <https://pkg.go.dev/github.com/cloudwego/eino-ext>
- **Examples / templates**: <https://github.com/cloudwego/eino-examples> (the v0.9 quickstart "ChatWithEino" lives under `quickstart/chatwitheino` there).
- **Use shape**: predominantly a **library** — `go get` + `import`. No hosted platform, no `eino dev` CLI, no app framework. The IDE plugin is an IntelliJ helper, not a runtime.
- **Download signal**: hard to verify for Go modules; `pkg.go.dev` import counts show several hundred importing public modules.

### 0.7 Documentation depth & cross-team contributor accessibility

**Official docs language(s)**: English + Simplified Chinese.

- The English site now has the full v0.9 quickstart (11 chapters, rewritten around `AgenticMessage`), the v0.9 release-notes page, a Cancel + TurnLoop quick start and a ChatModel failover guide. Older middleware-specific pages and many issue threads are still richer in Chinese.
- Source-code-level prompts are bilingual: middlewares ship parallel English/Chinese prompt strings selected via `internal.SelectPrompt` (e.g. `adk/middlewares/filesystem/prompt.go:28-58`, `adk/middlewares/skill/skill.go:497-507`, `adk/middlewares/dynamictool/toolsearch/toolsearch.go:416-424`):

```go
// adk/middlewares/filesystem/prompt.go:44-58
ListFilesToolDesc = `Lists all files in the filesystem, filtering by directory.

Usage:
- The path parameter must be an absolute path, not a relative path
...`

ListFilesToolDescChinese = `列出文件系统中的所有文件，按目录过滤。

使用方法：
- path 参数必须是绝对路径，不能是相对路径
...`
```

- READMEs ship in both languages (`README.md` + `README.zh_CN.md` in both repos and in every eino-ext sub-module).
- Runtime language is selectable via `adk.SetLanguage(adk.LanguageChinese)` (`adk/config.go:33`), driving which internal prompts ship to the LLM.
- eino-ext ships four agent-facing skill packs under `skills/` (`eino-guide`, `eino-component`, `eino-compose`, `eino-agent`), updated for v0.9 (eino-ext commit `22812b7`). They are documentation for coding assistants, not runtime code.

**Can a non-engineer (Product / Data) author content without engineering hand-holding?**

- **Partially**. SKILL.md (via `adk/middlewares/skill/`) and AGENTS.md (via `adk/middlewares/agentsmd/`) are plain markdown + YAML frontmatter that a non-engineer can author. Semantics such as `context: fork_with_context` are documented in Go doc comments and in the middleware docs, which are thinner in English.
- Tool authoring requires writing Go (`tool.BaseTool` + `InvokableTool`), which is engineering work regardless of language.

Cross-team contribution from Product / Data is still harder than Mastra TS or Claude Agent SDK (English-only, deeper docs), but the gap narrowed with the English v0.9 quickstart.

### 0.8 Documentation entry points

- **Official docs landing**: <https://www.cloudwego.io/docs/eino/>
- **Quickstart (v0.9, 11 chapters)**: <https://www.cloudwego.io/docs/eino/quick_start/> (e.g. [Ch. 2 ChatModelAgent / Runner / AgentEvent](https://www.cloudwego.io/docs/eino/quick_start/chapter_02_chatmodelagent_runner_agentevent/), [Ch. 3 Memory and Session](https://www.cloudwego.io/docs/eino/quick_start/chapter_03_memory_and_session/), [Ch. 11 TurnLoop](https://www.cloudwego.io/docs/eino/quick_start/chapter_11_turnloop/)). The pre-v0.9 quickstart URLs (`simple_llm_application`, `agent_llm_with_tools`) now return 404.
- **API reference (godoc)**: <https://pkg.go.dev/github.com/cloudwego/eino> and <https://pkg.go.dev/github.com/cloudwego/eino-ext>
- **Hosting / deployment / production guide**: **Not provided** — Eino is library-only.
- **Examples / demos repo**: <https://github.com/cloudwego/eino-examples>
- **Changelog / release notes**: <https://www.cloudwego.io/docs/eino/release_notes_and_migration/> (v0.1 through [v0.9 agentic-runtime](https://www.cloudwego.io/docs/eino/release_notes_and_migration/eino_v0.9._agentic-runtime/))
- **GitHub Releases**: <https://github.com/cloudwego/eino/releases> and <https://github.com/cloudwego/eino-ext/releases>
- **GitHub issues — core**: <https://github.com/cloudwego/eino/issues> (many threads in Chinese)
- **GitHub issues — ext**: <https://github.com/cloudwego/eino-ext/issues>
- **Discord / community forum**: <https://discord.gg/jceZSE7DsW> (low activity; main community is on Lark/Feishu)

Additional high-signal pages:
- **Overview**: <https://www.cloudwego.io/docs/eino/overview/>
- **Graph or Agent — when to use which**: <https://www.cloudwego.io/docs/eino/overview/graph_or_agent/>
- **ADK overview**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/>
- **Agent Cancel and TurnLoop quick start**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_cancel_and_turnloop_quickstart/>
- **ChatModel failover guide**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_implementation/chat_model/chatmodel_failover_guide/>
- **HITL (interrupt/resume)**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_hitl/>
- **ChatModelAgent middleware index**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/eino_adk_chatmodelagentmiddleware/>
- **Checkpoint & interrupt/resume (compose layer)**: <https://www.cloudwego.io/docs/eino/core_modules/chain_and_graph_orchestration/checkpoint_interrupt/>
- **Callback system**: <https://www.cloudwego.io/docs/eino/core_modules/chain_and_graph_orchestration/callback_manual/>

---

## 1. High Level Architecture

### Deployment diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  Your Go process (e.g. Predict long-running-agent binary)              │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  YOUR HTTP / gRPC / ACP layer (gin, hertz, mux; or eino-ext/acp) │  │
│  │  YOUR auth (Okta JWT, ...)  YOUR tenant routing                  │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  adk.TurnLoop (optional, per session: Push / Stop / preempt)     │  │
│  │    └─ adk.Runner  (adk/runner.go:55)                             │  │
│  │         ├─ Run / Query / Resume / ResumeWithParams               │  │
│  │         ├─ WithCancel() → AgentCancelFunc                        │  │
│  │         ├─ returns *AsyncIterator[*TypedAgentEvent[M]]           │  │
│  │         └─ owns CheckPointStore (BYO)                            │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  adk.ChatModelAgent (ReAct, retry, failover)                     │  │
│  │  adk.AgentTool (agents-as-tools)  prebuilt/{deep,supervisor,...} │  │
│  │  middlewares/{skill,agentsmd,toolsearch,filesystem,              │  │
│  │               summarization,reduction,plantask,patchtoolcalls}   │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │ delegates to                           │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  compose.Graph[I, O] / compose.Chain[I, O]                       │  │
│  │   ├─ ChatModel / ToolsNode / AgenticToolsNode / Retriever ...    │  │
│  │   ├─ Pregel + DAG run modes                                      │  │
│  │   └─ checkpoint serializer (gob default)                         │  │
│  └────────┬───────────────────┬───────────────────────────┬─────────┘  │
│           │                   │                           │            │
│  ┌────────▼─────────┐ ┌───────▼────────┐  ┌───────────────▼─────────┐  │
│  │ components/model │ │ components/tool│  │ components/{retriever,  │  │
│  │ (eino-ext: ark,  │ │ (eino-ext: mcp,│  │ indexer,embedding,      │  │
│  │  openai, claude, │ │ officialmcp,   │  │ document, prompt}       │  │
│  │  gemini, ollama, │ │ duckduckgo,    │  │ (eino-ext: qdrant,      │  │
│  │  agentic* ...)   │ │ commandline..) │  │ milvus, redis, es, ...) │  │
│  └────────┬─────────┘ └────────────────┘  └─────────────────────────┘  │
│           │                                                            │
└───────────┼────────────────────────────────────────────────────────────┘
            │ HTTPS
   ┌────────▼─────────┐
   │ LLM Providers    │  Anthropic / OpenAI (Chat + Responses) / Gemini / Bedrock /
   └──────────────────┘  Vertex / Ark / DeepSeek / Qwen / Ollama (local) ...

   YOUR persistent stores (NOT shipped):
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  CheckPointStore │  │  Tenant DB       │  │  Eval / Trace    │
   │  (Postgres / S3 /│  │  Auth / RBAC     │  │  store (Langfuse,│
   │  Redis - BYO)    │  │  (BYO)           │  │  LangSmith, OTel │
   └──────────────────┘  └──────────────────┘  │  via eino-ext)   │
                                               └──────────────────┘
```

### 1.1 Where does the agent loop actually execute?

**In your Go process, in a goroutine spawned by `TypedChatModelAgent.Run`** (`adk/chatmodel.go:1446-1533`):

```go
// adk/chatmodel.go:1446 (abridged)
func (a *TypedChatModelAgent[M]) Run(ctx context.Context, input *TypedAgentInput[M], opts ...AgentRunOption) *AsyncIterator[*TypedAgentEvent[M]] {
    iterator, generator := NewAsyncIteratorPair[*TypedAgentEvent[M]]()
    o := getCommonOptions(nil, opts...)
    cancelCtx, cancelCtxOwned := resolveRunCancelContext(ctx, o)
    // ...
    ctx, run, bc, err := a.getRunFunc(ctx)
    // ...
    go func() {
        defer func() { /* recover panic → send error event */ generator.Close() }()
        run(ctx, &typedRunParams[M]{
            input: input, generator: generator, store: newBridgeStore(),
            instruction: instruction, returnDirectly: returnDirectly,
            cancelCtx: cancelCtx, composeOpts: co, afterToolCallsHook: runOps.afterToolCallsHook,
        })
    }()
    if cancelCtxOwned { return wrapIterWithCancelCtx(iterator, cancelCtx) }
    return iterator
}
```

The run function is built by `buildReActRunFunc` (`adk/chatmodel.go:1097`), which compiles the ReAct `compose.Graph` (`newReact`, `adk/react.go:354-562`) and runs it via `compose.Runnable.Invoke` / `Stream`. A parallel `newAgenticReact` (`adk/react.go:607`) does the same for `AgenticMessage`. The graph runtime executes in your process; no subprocess.

For the (now NOT RECOMMENDED) parallel workflow agent, the loop is a literal `for i := range a.subAgents` over goroutine-spawned `agent.Run()` calls coordinated by `sync.WaitGroup` (`adk/workflow.go:519-570`).

### 1.2 Runtime dependencies

**External runtimes / binaries / services** (high level — language packages excluded):

- **Go toolchain** — core declares `go 1.18` (`eino/go.mod:3`); some eino-ext modules need Go 1.23–1.25. The only mandatory runtime.
- **No bundled binaries** at the framework level. The eino-ext `adk/backend/local` backend now renders PDFs with `go-pdfium` compiled to WebAssembly (eino-ext commit `9473ae2`, replacing the cgo `go-fitz` dependency), so it no longer needs a native MuPDF.
- **No required infrastructure services** — Postgres / Redis / vector DBs only if your application wires them in via eino-ext adapters.
- **No required vendor services** — any LLM provider behind `model.BaseModel[M]`.
- **Optional external services** (each opt-in via an eino-ext sub-module):
  - LLM providers: OpenAI, Anthropic Claude (direct, Bedrock, Vertex), Gemini, Ark, Qwen, DeepSeek, Ollama, OpenRouter, Qianfan, plus `agentic*` variants for OpenAI Responses, Claude, Gemini, Ark, DeepSeek, Qwen.
  - Vector stores (RAG): Qdrant, Milvus (v1 / v2), Redis, OpenSearch (v2 / v3), Elasticsearch (v7 / v8 / v9), Volc VikingDB, Dify.
  - MCP servers: any over stdio / SSE / Streamable HTTP (via `mark3labs/mcp-go` or official `modelcontextprotocol/go-sdk`).
  - Tracing backends: Langfuse, LangSmith, APMPlus (OTel), CozeLoop, Volcengine TLS.
  - ACP clients (editors such as Zed) via `eino-ext/acp`.

Net deployment story is **light** — one Go binary, no daemons.

### 1.3 Recommended deployment topology

There is no vendor-recommended topology document — this is a library. The v0.9 quickstart's web chapter (Ch. 10) runs one Go process with a Hertz server and file-backed sessions, and explicitly labels sessions, memory and UI protocol as business-layer code.

In practice (and in Dailymotion's Ray service, which runs Eino in production), Eino runs **embedded in a single Go process per pod**, behind your own HTTP router, with persistence in your own Postgres. Multiple pods serve the same conversation pool with shared DB state. `TurnLoop` is a per-session object; a pod hosting N sessions holds N `TurnLoop`s (or N in-flight `Runner` calls).

### 1.4 Cold-start cost & instance footprint

- **Startup latency**: negligible (Go binary; `NewRunner` is struct allocation, `adk/runner.go:89-100`). No model warm-up, no checkpoint hydration, no plugin loading. The local PDF backend lazily initialises a pdfium WASM worker pool on first use (`eino-ext/adk/backend/local/local.go:73-91`).
- **RAM baseline**: depends on your binary. Eino core is now ~60k non-test LOC (up from ~44k at v0.8.13), of which `adk/` is ~29k. Per-session memory is dominated by `runSession.Events` (`adk/runctx.go:34-46`), which accumulates every event during a run.
- **Disk baseline**: zero (no on-disk cache, no JSONL persistence, no skill cache unless you build one).

Compared with Claude Agent SDK Python (issue #333: 20–30 s startup), Eino has a **large cold-start advantage** for horizontally scaled deployments.

### 1.5 Vendor lock-in

| Axis | Score | Notes |
|---|---|---|
| LLM provider | **Low** | All providers behind `model.BaseModel[M]` (`components/model/interface.go:36-39`), aliased as `BaseChatModel` / `AgenticModel` (`:71`, `:109`). Adapters in eino-ext for 10 providers plus 6 `agentic*` variants. Using `AgenticMessage` + provider-hosted server tools (web search, code interpreter, remote MCP) increases provider coupling. |
| Hosting platform | **None** | Library only. Deploy wherever Go runs. |
| Eval platform | **None** | Eino ships no eval framework; BYO. |
| Tracing platform | **Low** | OTel via APMPlus / Langfuse v2 (OTLP) / TLS, or LangSmith / CozeLoop. You can write your own `callbacks.Handler`. |
| Persistence | **None** | `CheckPointStore` is two methods on `[]byte`. |

Cloud-vendor lock-in: zero. The closest equivalent of a vendor is **CloudWeGo / ByteDance**: their internal use case (Volcengine Ark, APMPlus, TLS) drives the roadmap.

### 1.6 Framework weight / footprint

**Heavy library; no platform**:
- ~60k non-test LOC across `compose/`, `adk/`, `schema/`, `callbacks/`, `components/`; `adk/` alone is ~29k LOC (cancel, TurnLoop, retry/failover and the generic typed layer added ~14k in v0.9)
- 8 in-tree middlewares (`agentsmd`, `dynamictool/toolsearch`, `filesystem`, `patchtoolcalls`, `plantask`, `reduction`, `skill`, `summarization`) + 3 prebuilts
- Zero platform code (no HTTP server, no UI, no eval, no marketplace)

Compared to LangGraph (OSS runtime + closed-source `langgraph_api` platform), Eino is "OSS runtime, no platform at all". Compared to Mastra TS (built-in storage, dev UI, plugin system), Eino is the opposite philosophy: rich runtime primitives, you assemble the application.

### 1.7 Release-history signal

Eino does **not** ship an in-repo `CHANGELOG.md`. Releases are documented on the CloudWeGo docs site (<https://www.cloudwego.io/docs/eino/release_notes_and_migration/>, now including v0.9) and as auto-generated GitHub Releases.

**v0.8.13 → v0.9.21 (Apr 29 → Sep 29 2026, 126 commits, +57.8k / −3.4k lines)** — the "agentic-runtime" release:
- **`AgenticMessage` + `AgenticModel`** (`schema/agentic_message.go`, `components/model/interface.go:109`): a content-block message model (reasoning, function tool call/result, server tool call/result, MCP tool call/result/approval, multimodal) for OpenAI Responses / Claude / Gemini-style protocols. Every ADK type gained a `Typed*[M MessageType]` generic form; the old names are aliases.
- **Cancel** (`adk/cancel.go`, 1.1k LOC): `WithCancel()` returns an `AgentCancelFunc`; safe-point modes, recursive propagation, timeout escalation, checkpoint on cancel.
- **`TurnLoop`** (`adk/turn_loop.go`, 2k LOC): push-based multi-turn runtime with preemption, stop, between-turn checkpoints.
- **Model retry / failover**: `ModelRetryConfig.ShouldRetry` returns a `RetryDecision` that can rewrite input or reject output (`adk/retry_chatmodel.go:222-256`); new `ModelFailoverConfig` (`adk/failover_chatmodel.go:128-167`).
- **Middleware**: `AfterAgent` hook; `ChatModelAgentState.ToolInfos` / `DeferredToolInfos` as the primary path for per-call tool visibility; new `agentsmd` middleware; `toolsearch` rewritten (keyword + `select:` search, provider-native deferred tools); summarization gets `Summarize` method, retry/failover, default trigger lowered to 160k tokens; reduction preserves streaming output.
- **compose**: `AgenticToolsNode`; `ToolsNode` tool-name and argument aliases (`compose/tool_node.go:174-195`); several nested-stream checkpoint fixes (v0.9.16–v0.9.20).
- **Advisories**: agent transfer and workflow agents marked NOT RECOMMENDED (commit `538c3c2`).
- **Usage**: `PromptTokenDetails.CacheWriteTokens` (v0.9.21, `schema/message.go:556-561`).

**eino-ext (May 14 → Sep 24 2026, 115 commits)**: six `agentic*` model adapters; ACP bridge (`acp/`); Langfuse v2 (OTLP, Langfuse v4 data model); Volcengine TLS callback; Claude `AutoCacheControl` config, Vertex service-account auth, structured output, adaptive thinking, per-request timeout; `officialmcp` reconnecting sessions and custom transport factories; `go-fitz` → `go-pdfium` (WASM) for multimodal PDF read.

**What's next**: the `alpha/10` branch (177 commits ahead of `main`) carries session events with turn IDs, an "automemory" middleware, durable background tasks and a background-task manager. None of it is in the analysed commit; treat it as roadmap.

Eino is in an **active pre-v1 phase**. Production users should pin minor versions and read migration pages before bumping; checkpoint compatibility across versions is handled with explicit gob shims (`adk/interrupt.go:252-288`).

---

## 2. Agent Loop

### 2.1 Run loop entrypoint(s)

Four layered entrypoints, top-to-bottom:

1. **`adk.TurnLoop[T, M]`** (new in v0.9) — a long-lived, push-driven loop over many turns of one session (`adk/turn_loop.go:562-634`, `:1312-1565`):

   ```go
   // adk/turn_loop.go (abridged)
   type TurnLoopConfig[T any, M MessageType] struct {
       GenInput     func(ctx context.Context, loop *TurnLoop[T, M], items []T) (*GenInputResult[T, M], error)          // required
       GenResume    func(ctx context.Context, loop *TurnLoop[T, M], interruptedItems, unhandledItems, newItems []T) (*GenResumeResult[T, M], error)
       PrepareAgent func(ctx context.Context, loop *TurnLoop[T, M], consumed []T) (TypedAgent[M], error)             // required
       OnAgentEvents func(ctx context.Context, tc *TurnContext[T, M], events *AsyncIterator[*TypedAgentEvent[M]]) error
       Store        CheckPointStore
       CheckpointID string
   }

   func NewTurnLoop[T any, M MessageType](cfg TurnLoopConfig[T, M]) *TurnLoop[T, M]
   func (l *TurnLoop[T, M]) Run(ctx context.Context)
   func (l *TurnLoop[T, M]) Push(item T, opts ...PushOption[T, M]) (bool, <-chan struct{})
   func (l *TurnLoop[T, M]) Stop(opts ...StopOption)
   func (l *TurnLoop[T, M]) Wait() *TurnLoopExitState[T, M]
   ```

2. **`adk.TypedRunner[M]`** (alias `adk.Runner` for `*schema.Message`) — the entrypoint for one agent run:

   ```go
   // adk/runner.go:55-149
   type TypedRunner[M MessageType] struct {
       a               TypedAgent[M]
       enableStreaming bool
       store           CheckPointStore // BYO; nil = no checkpointing
   }
   type Runner = TypedRunner[*schema.Message]

   func (r *TypedRunner[M]) Run(ctx context.Context, messages []M, opts ...AgentRunOption) *AsyncIterator[*TypedAgentEvent[M]]
   func (r *TypedRunner[M]) Query(ctx context.Context, query string, opts ...AgentRunOption) *AsyncIterator[*TypedAgentEvent[M]]
   func (r *TypedRunner[M]) Resume(ctx context.Context, checkPointID string, opts ...AgentRunOption) (*AsyncIterator[*TypedAgentEvent[M]], error)
   func (r *TypedRunner[M]) ResumeWithParams(ctx context.Context, checkPointID string, params *ResumeParams, opts ...AgentRunOption) (*AsyncIterator[*TypedAgentEvent[M]], error)
   ```

3. **`TypedAgent[M]` interface** — what every agent implementation must satisfy:

   ```go
   // adk/interface.go:453-467
   type TypedAgent[M MessageType] interface {
       Name(ctx context.Context) string
       Description(ctx context.Context) string
       // Run runs the agent.
       // The returned AgentEvent within the AsyncIterator must be safe to modify.
       Run(ctx context.Context, input *TypedAgentInput[M], options ...AgentRunOption) *AsyncIterator[*TypedAgentEvent[M]]
   }
   type Agent = TypedAgent[*schema.Message]
   ```

4. **`compose.Runnable[I, O]`** — the graph engine's run interface (what `ChatModelAgent` compiles to):

   ```go
   // compose/runnable.go:32-37
   type Runnable[I, O any] interface {
       Invoke(ctx context.Context, input I, opts ...Option) (output O, err error)
       Stream(ctx context.Context, input I, opts ...Option) (output *schema.StreamReader[O], err error)
       Collect(ctx context.Context, input *schema.StreamReader[I], opts ...Option) (output O, err error)
       Transform(ctx context.Context, input *schema.StreamReader[I], opts ...Option) (output *schema.StreamReader[O], err error)
   }
   ```

The "agent harness" for our purposes is `Runner` + `ChatModelAgent`, optionally wrapped by `TurnLoop` for a long-running session; the Runnable layer is what you'd hand-build with `compose.NewGraph` for full control. `M` is `*schema.Message` (full feature set) or `*schema.AgenticMessage` (content-block path). The doc comment at `adk/interface.go:446-451` says that for `AgenticMessage` "single-agent execution works but cancel monitoring on the model stream and retry are not yet wired"; later commits generified retry and wired failover into the agentic ReAct path (`9d2d84b`, `1e551e6`), so the comment may be partly stale. Multi-agent orchestration (flowAgent, transfer) remains `*schema.Message`-only.

### 2.2 Per-iteration behavior

`ChatModelAgent` compiles a `compose.Graph[*reactInput, Message]` (`adk/react.go:354-562`). v0.9 added cancel-check and after-tool-calls nodes:

```
START → Init → ChatModel → (branch: tool calls?)
                              ├─ no  → [AfterAgent] → END
                              └─ yes → CancelCheck → ToolNode → AfterToolCalls → AfterToolCallsCancelCheck
                                                                   ├─ returnDirectly → ToolNodeToEndConverter → [AfterAgent] → END
                                                                   └─ else → ChatModel (loop)
```

Each trip:

1. `GenModelInput` (default `defaultGenModelInput`, `adk/chatmodel.go:167-194`) merges instruction (system prompt) + input messages, optionally formatting f-string placeholders against session values.
2. The ChatModel state pre-handler decrements the remaining-iteration counter (default `MaxIterations` 20, `adk/chatmodel.go:305-308`); returns `ErrExceedMaxIterations` when exhausted (`adk/react.go:393`).
3. `BeforeModelRewriteState` middlewares rewrite `Messages`, `ToolInfos` and `DeferredToolInfos` in the persisted agent state.
4. The wrapped model is called. Wrapper chain (outermost → innermost, documented at `adk/chatmodel.go:325-336`): failover wrapper → retry wrapper → event sender → user `WrapModel` middlewares → callback injector → failover proxy / raw model.
5. `AfterModelRewriteState` runs; the branch checks for tool calls.
6. A cancel safe-point check runs (`CancelAfterChatModel`).
7. `ToolsNode` (`compose/tool_node.go:81-92`) dispatches calls — **parallel by default** (`ExecuteSequentially: false`), one goroutine per call. Name / argument aliases are resolved first (`compose/tool_node.go:190-195`).
8. `AfterToolCalls` runs the per-run `WithAfterToolCallsHook` (`adk/chatmodel.go:130-134`), then a second cancel safe-point check (`CancelAfterToolCalls`).
9. Branch on return-directly; otherwise loop back to `ChatModel`.

Per-call middleware order for tools is documented at `adk/chatmodel.go:356-362`.

### 2.3 ReAct loop

**Built-in.** `ChatModelAgent` ships ReAct as the default loop, configured via `TypedChatModelAgentConfig` (`adk/chatmodel.go:260-415`) — no graph-building required. If no tools are configured, a simpler chain is used (`buildNoToolsRunFunc`, `adk/chatmodel.go:1002`).

Legacy ReAct also exists at `flow/agent/react/react.go:284` (`react.NewAgent`) for pre-ADK code; new code should use `adk.NewChatModelAgent`.

If you don't want ReAct, build your own `compose.Graph[I, O]` or implement the `TypedAgent` interface yourself.

### 2.4 Tool dispatch + result handling

Handled by `compose.ToolsNode` (`compose/tool_node.go:81-92`):

```go
// compose/tool_node.go:81-92
type ToolsNode struct {
    tuple                             *toolsTuple
    tools                             []tool.BaseTool
    unknownToolHandler                func(ctx context.Context, name, input string) (string, error)
    executeSequentially               bool
    toolArgumentsHandler              func(ctx context.Context, name, input string) (string, error)
    toolCallMiddlewares               []InvokableToolMiddleware
    streamToolCallMiddlewares         []StreamableToolMiddleware
    enhancedToolCallMiddlewares       []EnhancedInvokableToolMiddleware
    enhancedStreamToolCallMiddlewares []EnhancedStreamableToolMiddleware
    toolAliasConfigs                  map[string]ToolAliasConfig
}
```

The node receives an assistant `*schema.Message` with `ToolCalls`, resolves name aliases, dispatches each call to the matching tool, and returns `[]*schema.Message` (one tool message per call, ordered by input order — `compose/tool_node.go:72-79`). Results link back via `ToolMessage.ToolCallID == ToolCall.ID`. `utils.InferTool` / `utils.NewTool` handle JSON decode/encode. For the `AgenticMessage` path, `compose.AgenticToolsNode` (`compose/agentic_tools_node.go:32-40`) does the same over content blocks.

`UnknownToolsHandler` (`compose/tool_node.go:197-208`) is a graceful-degradation hook for hallucinated tool names; `ToolAliases` (`compose/tool_node.go:174-195`) maps alternate tool names and argument keys to canonical ones before `ToolArgumentsHandler` runs.

### 2.5 Explicit turn concept

Two levels:

- **Inside one run**: no first-class "Turn" type. The boundary is implicit — the branch from `ChatModel` to `ToolNode` or `END`. One `ChatModel → ToolNode` trip is one iteration (bounded by `MaxIterations`).
- **Across runs (new in v0.9)**: `TurnLoop` makes the **turn** explicit. One turn = one `GenInput` decision → one `PrepareAgent` → one agent run → `OnAgentEvents`. `TurnContext` (`adk/turn_loop.go:845-886`) carries the consumed items and `Preempted` / `Stopped` channels for the current turn. `GenInput` decides at each boundary which buffered items to consume and which to keep, so consecutive user inputs can be merged or batched.

The smallest unit emitted on the iterator is still the `AgentEvent` (`adk/interface.go:419-436`).

### 2.6 Event emission mechanism (in-process)

**`*AsyncIterator[T]` backed by an unbounded Go channel**:

```go
// adk/utils.go:31-60
type AsyncIterator[T any] struct {
    ch *internal.UnboundedChan[T]
}

func (ai *AsyncIterator[T]) Next() (T, bool) {
    return ai.ch.Receive()
}

type AsyncGenerator[T any] struct {
    ch *internal.UnboundedChan[T]
}

func (ag *AsyncGenerator[T]) Send(v T) { ag.ch.Send(v) }
func (ag *AsyncGenerator[T]) Close()    { ag.ch.Close() }

func NewAsyncIteratorPair[T any]() (*AsyncIterator[T], *AsyncGenerator[T]) { ... }
```

Consumer side:

```go
iter := runner.Query(ctx, "hello")
for {
    event, ok := iter.Next()
    if !ok { break }   // generator was closed
    if event.Err != nil { /* handle error; errors.As(event.Err, &cancelErr) for cancels */ }
    // event.Output, event.Action, event.AgentName, event.RunPath
}
```

With `TurnLoop`, the same iterator is handed to your `OnAgentEvents` callback once per turn. Network-side streaming is **not provided** — see Q8.

---

## 3. Message & Event Taxonomy

### 3.1 Message layers

Eino now has **four** vocabularies:

1. **Classic wire / LLM message** — `*schema.Message` (`schema/message.go:498-532`). OpenAI-chat-shaped: `Role`, `Content`, `UserInputMultiContent` / `AssistantGenMultiContent`, `ToolCalls`, `ToolCallID`, `ResponseMeta`, `ReasoningContent`, `Extra`. Default ADK path.
2. **Agentic message (new in v0.9)** — `*schema.AgenticMessage` (`schema/agentic_message.go:71-83`): `Role` + ordered `[]*ContentBlock` + `AgenticResponseMeta`. Content blocks cover reasoning, user input (text/image/audio/video/file), assistant output, function tool call/result, **server-side** tool call/result, **MCP** tool call/result/list/approval, and tool-search results (`schema/agentic_message.go:38-60`). Designed for OpenAI Responses, Claude and Gemini protocols; provider-specific fields live in `schema/{openai,claude,gemini}/extension.go`.
3. **Graph layer** — `*schema.StreamReader[M]` (or `[]M` for tool node outputs). Chunks for streaming; concat reducers in `schema/`.
4. **ADK layer** — `*TypedAgentEvent[M]` (`adk/interface.go:419-436`), wrapping a `*TypedMessageVariant[M]` (`adk/interface.go:73-98`) that wraps a message or a stream. The ADK adds `AgentName`, `RunPath`, `Action` and `Err`. v0.9 also stamps an eino-internal message ID into `Extra["_eino_msg_id"]` (`adk/internal/message_id.go:23-58`, read with `adk.GetMessageID`, `adk/wrappers.go:496`).

Conversion path:

```
LLM HTTP response (provider-specific JSON)
        ↓ (eino-ext adapter: chat model → *schema.Message; agentic model → *schema.AgenticMessage)
M  (or *schema.StreamReader[M] for streaming)
        ↓ (graph reducer for streaming; pass-through for non-streaming)
ToolsNode / AgenticToolsNode produces []M (one per tool call)
        ↓
ChatModelAgent wraps each message into a TypedMessageVariant + TypedAgentEvent
        ↓
generator.Send(event)  →  AsyncIterator.Next()  →  YOUR CODE (or TurnLoop.OnAgentEvents)
```

### 3.2 Concrete message types

| Type | File | One-line purpose |
|---|---|---|
| `schema.Message` | `schema/message.go:498` | Canonical chat message (role, content, tool calls, multimodal parts, response meta) |
| `schema.RoleType` | `schema/message.go:109` | `assistant` / `user` / `system` / `tool` |
| `schema.ToolCall` | `schema/message.go:133` | One LLM-generated tool invocation (id, type, function) |
| `schema.FunctionCall` | `schema/message.go:124` | `{Name, Arguments string (JSON)}` inside a ToolCall |
| `schema.ChatMessagePart` | `schema/message.go:391` | Deprecated multi-content part type |
| `schema.MessageInputPart` | `schema/message.go:208` | User multimodal input part (text/image/audio/video/file) |
| `schema.MessageOutputPart` | `schema/message.go:269` | Assistant multimodal output part |
| `schema.MessageOutputReasoning` | `schema/message.go:250` | Reasoning trace |
| `schema.ResponseMeta` | `schema/message.go:448` | `{FinishReason, Usage, LogProbs}` |
| `schema.TokenUsage` | `schema/message.go:535` | Prompt / completion / total tokens + cached, cache-write and reasoning breakdowns |
| `schema.AgenticMessage` | `schema/agentic_message.go:71` | Content-block message for agentic models (new in v0.9) |
| `schema.ContentBlock` | `schema/agentic_message.go:102` | One typed block (reasoning, text, function/server/MCP tool call or result, ...) |
| `schema.AgenticResponseMeta` | `schema/agentic_message.go:85` | Token usage + OpenAI / Gemini / Claude extensions |
| `schema.ToolInfo` | `schema/tool.go` | Tool descriptor (name, description, params schema) sent to the LLM |
| `schema.ToolResult` / `schema.ToolArgument` | `schema/tool.go` | Multimodal tool result / argument used by `EnhancedInvokableTool` |
| `schema.StreamReader[T]` | `schema/stream.go` | Pull-based stream of T chunks |
| `adk.MessageType` | `adk/interface.go:43` | Type constraint: `*schema.Message` or `*schema.AgenticMessage` |
| `adk.Message` / `adk.AgenticMessage` | `adk/interface.go:47,50` | Aliases for the two message pointer types |
| `adk.TypedMessageVariant[M]` | `adk/interface.go:73` | Wrapper around message OR stream with `Role` + `ToolName` metadata |
| `adk.TypedAgentEvent[M]` | `adk/interface.go:419` | Outermost event in the iterator (`AgentName`, `RunPath`, `Output`, `Action`, `Err`) |
| `adk.TypedAgentInput[M]` | `adk/interface.go:440` | `{Messages []M, EnableStreaming bool}` |
| `adk.TypedAgentOutput[M]` | `adk/interface.go:320` | `{MessageOutput *TypedMessageVariant[M], CustomizedOutput any}` |
| `adk.AgentAction` | `adk/interface.go:357` | `{Exit, Interrupted, TransferToAgent, BreakLoop, CustomizedAction}` |
| `adk.RunStep` | `adk/interface.go:377` | One agent in the `RunPath` (NOT RECOMMENDED outside transfer/workflow) |
| `adk.InterruptInfo` | `adk/interrupt.go:49` | `{Data, InterruptContexts []*InterruptCtx}` carried in `AgentAction.Interrupted` |
| `adk.InterruptCtx` | `adk/interrupt.go:183` (= `core.InterruptCtx`) | User-facing view of one interrupted component |
| `adk.CancelError` | `adk/cancel.go:180` | Sent via `AgentEvent.Err` when a run is cancelled; carries `InterruptContexts` for resume |
| `adk.AgentCallbackInput` / `Output` | `adk/callback.go:29,41` | OnStart / OnEnd payloads |
| `adk.HistoryEntry` | `adk/flow.go:34` | `{IsUserInput, AgentName, Message}` — used by history rewriters |
| `adk.TypedChatModelAgentState[M]` | `adk/chatmodel.go:216` | `Messages`, `ToolInfos`, `DeferredToolInfos` passed to state-rewrite hooks |
| `adk.ChatModelAgentContext` | `adk/handler.go:87` | Mutable `Instruction` / `Tools` / `ReturnDirectly` / `ToolSearchTool` in `BeforeAgent` |
| `adk.WorkflowInterruptInfo` | `adk/workflow.go:166` | Workflow-level interrupt payload |
| `adk.TurnLoopExitState[T, M]` | `adk/turn_loop.go:794` | Exit reason, unhandled / interrupted items, checkpoint outcome |

### 3.3 Messages vs. events

**Two separate taxonomies, surfaced through one iterator.** The single `*AsyncIterator[*TypedAgentEvent[M]]` is the user-facing channel; each event may carry:
- a *message-event* via `event.Output.MessageOutput`
- an *action-event* via `event.Action` (Exit / TransferToAgent / Interrupted / BreakLoop / CustomizedAction)
- an *error-event* via `event.Err` (including `*CancelError`)

Hook / callback events are a **separate** subsystem (`callbacks.Handler`) and are not multiplexed onto the agent event stream.

### 3.4 Event categories

| Category | Surfaces via | Notes |
|---|---|---|
| Stream events (per-token) | inside `MessageVariant.MessageStream` | One `AgentEvent` per *message*; the body is a stream you iterate |
| Message events | `AgentEvent.Output.MessageOutput` | One per finished assistant/tool message; each carries a stable eino message ID in `Extra` |
| Turn / iteration events | implicit inside a run; `TurnLoop` callbacks across runs | No `TurnStart` / `TurnEnd` event type on the iterator (the `alpha/10` branch adds session events with turn IDs) |
| Tool events | `AgentEvent` with `MessageOutput.Role = schema.Tool` | Emitted by the internal event-sender tool wrapper (`adk/wrappers.go:541-975`); position is configurable via `NewEventSenderToolWrapper()` (`adk/wrappers.go:559`) |
| Session lifecycle | **Not in the agent stream** — `callbacks.Handler.OnStart` / `OnEnd` on `ComponentOfAgent` | `AgentCallbackInput` / `AgentCallbackOutput` |
| Hook events | `callbacks.CallbackTiming` (`TimingOnStart`, `TimingOnEnd`, `TimingOnError`, stream variants) | Separate event bus |
| Sub-agent events | Same stream when `ToolsConfig.EmitInternalEvents: true` (`adk/chatmodel.go:141-155`) | `RunPath` / `AgentName` disambiguate |
| Interrupt events | `AgentEvent.Action.Interrupted != nil` | Saved to `CheckPointStore` before being sent (`adk/runner.go:310-337`) |
| Cancel events | `AgentEvent.Err` is `*CancelError` | Checkpoint saved first if a store and ID are configured (`adk/runner.go:293-303`) |
| Custom events | `adk.SendEvent` / `TypedSendEvent` from middleware (`adk/handler.go:409-430`) | Arbitrary payload |

### 3.5 Canonical type-definition file(s)

- Classic messages: `schema/message.go` (~1.9k lines)
- Agentic messages: `schema/agentic_message.go` (~2.3k lines) + `schema/{openai,claude,gemini}/extension.go`
- Tool info / arguments / results: `schema/tool.go`
- Streams: `schema/stream.go`
- Agent events & interface: `adk/interface.go`
- Interrupt types: `adk/interrupt.go`, `internal/core/interrupt.go`
- Cancel types: `adk/cancel.go`
- Hook interface: `callbacks/interface.go`, `internal/callbacks/`

### 3.6 Live agentic event stream taxonomy

Sample frames the consumer receives (Go-side, not JSON — there is no wire format):

```go
// frame 1: streamed assistant message (token-by-token)
event := &AgentEvent{
    AgentName: "supervisor",
    Output: &AgentOutput{
        MessageOutput: &MessageVariant{
            IsStreaming:   true,
            MessageStream: <*schema.StreamReader[*schema.Message]>, // iterate to receive token chunks
            Role:          schema.Assistant,
        },
    },
}

// frame 2: tool call result
event := &AgentEvent{
    AgentName: "supervisor",
    Output: &AgentOutput{
        MessageOutput: &MessageVariant{
            IsStreaming: false,
            Message: &schema.Message{
                Role:       schema.Tool,
                Content:    `{"topics":["fitness","travel"]}`,
                ToolCallID: "call_xyz123",
                ToolName:   "topicSearch",
                Extra:      map[string]any{"_eino_msg_id": "6f1c..."},
            },
            Role:     schema.Tool,
            ToolName: "topicSearch",
        },
    },
}

// frame 3: interrupt (HITL; saved to CheckPointStore first, then sent to consumer)
event := &AgentEvent{
    AgentName: "supervisor",
    Action: &AgentAction{
        Interrupted: &InterruptInfo{
            Data:              "human approval required for tool 'audienceCreate'",
            InterruptContexts: []*InterruptCtx{ /* address chain; use .ID as ResumeParams.Targets key */ },
        },
    },
}

// frame 4: cancel (from WithCancel / TurnLoop.Stop / preempt)
event := &AgentEvent{
    Err: &CancelError{
        Info:              &AgentCancelInfo{Mode: CancelAfterToolCalls},
        InterruptContexts: []*InterruptCtx{ /* resumable */ },
    },
}

// frame 5: exit (clean termination via ExitTool)
event := &AgentEvent{AgentName: "supervisor", Action: &AgentAction{Exit: true}}

// frame 6: error
event := &AgentEvent{AgentName: "supervisor", Err: fmt.Errorf("model rate-limited")}
```

There is no `start` frame analogue to LangGraph's `metadata` frame — the first event on the stream is the first message or action the agent emits. `TransferToAgentAction` frames still exist but belong to the NOT RECOMMENDED transfer path.

---

## 4. Agent Runtime (Multi-session Host)

### 4.1 Multi-session host architecture

**No first-party multi-session host ships.** Eino is library-only; multi-session hosting is your job.

What changed in v0.9: **`TurnLoop` is a first-party per-session runtime** (`adk/turn_loop.go:896`). One `TurnLoop` owns one session's input buffer, runs turns back-to-back in a goroutine, supports `Push` (with optional preemption of the running turn), `Stop` (graceful, immediate, idle-timeout via `UntilIdleFor`, `adk/turn_loop.go:1188`) and checkpoint-based resume. It is not a registry: a host serving N sessions creates and tracks N `TurnLoop`s itself (e.g. a `map[sessionID]*TurnLoop` guarded by a mutex, or one loop per WebSocket).

The pattern Dailymotion uses in Ray (pre-v0.9):
- One Go process (one pod) hosts N concurrent agent sessions
- Per-request `Runner` instances (or a shared `Runner` with per-request `checkPointID`)
- `pkg/conversation/` owns persistence; the agent is constructed per request from the conversation state

`runSession` (`adk/runctx.go:34-46`) remains a *run-scoped* struct (one per `Runner.Run` call), not a persisted multi-call session.

### 4.2 Concurrent session isolation

Isolation is enforced **by context, not by registry**:
- `ctxWithNewTypedRunCtx` (`adk/runctx.go:537-558`) seeds a fresh `runContext` with its own `runSession` on every `Runner.Run` call.
- The `runContext` lives in `context.Context` (`runCtxKey{}`); concurrent calls each get their own ctx tree.
- `runSession.valuesMtx` and `runSession.mtx` guard the maps (`adk/runctx.go:34-46`).
- Parallel sub-agents fork the context (`forkRunCtx`, `adk/runctx.go:478-511`) into per-lane `runContext`s committed back via `joinRunCtxs` (`adk/runctx.go:423`) after all lanes finish.
- Cancel scopes are per run: `WithCancel()` creates a fresh `cancelContext` per call (`adk/cancel.go:239-247`); child agents derive checkpoint-aware child scopes (`adk/workflow.go:540-552`).

Risk: any *shared* state outside `runSession.Values` (e.g. a closure capturing a tenant-scoped map at agent construction time) is **not** isolated by the framework. If a tool reaches into a singleton, you leak across sessions. v0.9 fixed one framework-internal race of this kind (copy-on-write `SetMessageID`, commit `e8832e2`).

### 4.3 Horizontal scaling / multi-instance

Stateless. Pods scale horizontally. For shared state across pods, **your `CheckPointStore` implementation is the seam**:
- Point all pods at the same Postgres-backed store and any pod can resume any session (`Runner.Resume`) or restart a `TurnLoop` from its `CheckpointID`.
- Leader election, session-to-pod affinity, locking — **not provided**. A `TurnLoop` is in-memory; two pods running a `TurnLoop` for the same `CheckpointID` would race. Add optimistic concurrency / advisory locks in your store.

### 4.4 Background / async / scheduled tasks

**Not provided — BYO.** No cron, webhook triggers or scheduled-job framework on `main`. `TurnLoop.Push` gives you a clean entry point for externally triggered work (a webhook handler can `Push` into the session's loop), but scheduling and durability across pods are yours. A background-task manager and durable background tasks exist only on the `alpha/10` branch.

### 4.5 Worker pool / queue model

**Partially provided.** `TurnLoop` is an in-process, per-session queue: `Push` buffers items (`adk/turn_buffer.go`), `GenInput` decides which to consume per turn, and unprocessed items are returned in `TurnLoopExitState.UnhandledItems` and persisted in the TurnLoop checkpoint (`adk/turn_loop.go:942-950`). There is no cross-session worker pool, priority queue or distributed queue; long-running work across pods still needs Asynq / Temporal / Cloud Tasks in your host.

---

## 5. Sessions & Persistence

### 5.1 Session / chat data model

There is no `Session` *type*. The closest things:

1. **`runSession` (run-scoped)** — `adk/runctx.go:34-46`:

   ```go
   type runSession struct {
       Values    map[string]any
       valuesMtx *sync.Mutex

       Events     []*agentEventWrapper
       LaneEvents *laneEvents
       mtx        sync.Mutex

       // TypedEvents stores *[]*typedAgentEventWrapper[M] for M != *schema.Message.
       TypedEvents any
   }
   ```

   Created per `Runner.Run` call and lives until the run ends (or is checkpointed). It carries `Values` (filled by `WithSessionValues` / `AddSessionValue`), the append-only `Events` log, and per-lane in-flight events.

2. **`runContext`** — `adk/runctx.go:346-353`:

   ```go
   type runContext struct {
       RootInput *AgentInput
       RunPath   []RunStep
       AgenticRootInput any
       Session   *runSession
   }
   ```

3. **`serialization` (the persisted Runner checkpoint payload)** — `adk/interrupt.go:210-221`:

   ```go
   type serialization struct {
       RunCtx *runContext
       Info   *InterruptInfo // deprecated, kept for back-compat
       InfoDataSourceInterruptID string
       EnableStreaming           bool
       InterruptID2Address       map[string]Address
       InterruptID2State         map[string]core.InterruptState
   }
   ```

4. **`turnLoopCheckpoint` (new, the persisted TurnLoop payload)** — `adk/turn_loop.go:942-950`: `RunnerCheckpoint []byte`, `HasRunnerState bool`, `UnhandledItems []T`, interrupted items.

What you'd traditionally call a "session" (`tenant_id`, `user_id`, `created_at`, `model`, `summary`, `title`) is **not in the framework**. The v0.9 quickstart (Ch. 3) builds it as a business-layer `mem/store.go` and says so explicitly.

### 5.2 What's stored on a session

- Messages (history): live in the ReAct graph's per-run state (`typedState.Messages`, `adk/react.go:35-62`) and are reconstructed from `runSession.Events` by `flowAgent.genAgentInput` (`adk/flow.go:275`).
- Tool call history: implicit in `Events`.
- Scratchpad files: none on the session — see `filesystem.Backend` (`adk/filesystem/backend.go:243-283`), used by the `filesystem` and `reduction` middlewares.
- Embedded memory: none.
- Attachments: messages carry multimodal parts; no separate attachment store.
- Usage / cost rollup: not on the session; per message in `ResponseMeta.Usage`.
- Queued user input (TurnLoop only): `UnhandledItems` and interrupted items in the TurnLoop checkpoint.

### 5.3 Granularity

- One conversation per `checkPointID` / `CheckpointID`.
- **No fork/branch model** (no LangGraph-style `session.fork()`). Execution is linear; only parallel sub-agents get lanes.
- A new ID = a new session. You own the ID scheme.

### 5.4 Built-in persistence stores

**None. Interface-only.** `internal/core/interrupt.go:31-46`:

```go
type CheckPointStore interface {
    Get(ctx context.Context, checkPointID string) ([]byte, bool, error)
    Set(ctx context.Context, checkPointID string, checkPoint []byte) error
}

// CheckPointDeleter is an optional interface that CheckPointStore implementations
// can implement to support explicit checkpoint deletion.
type CheckPointDeleter interface {
    Delete(ctx context.Context, checkPointID string) error
}
```

The framework hands you gob-serialized `[]byte`. **eino-ext ships no implementation** (verified: no Go type implementing `CheckPointStore` outside tests and docs). `TurnLoop` calls `Delete` on clean exit when the store implements `CheckPointDeleter` (`adk/turn_loop.go:979-987`); otherwise stale checkpoints stay until you expire them.

Possibilities you'd build: Postgres (the Ray pattern), Redis, S3 / GCS, BoltDB / SQLite for local dev. The framework-internal `bridgeStore` (`adk/interrupt.go:380-407`) is a mutex-guarded in-memory map you can copy for tests.

### 5.5 Persistence timing

Checkpoints fire at three moments, all **synchronous** (saved before the triggering event is forwarded):

1. **On interrupt** (`adk/runner.go:310-337`):

   ```go
   // adk/runner.go:310-337 (abridged)
   if event.Action != nil && event.Action.internalInterrupted != nil {
       interruptSignal = event.Action.internalInterrupted
       // ...
       if checkPointID != nil {
           err := runnerSaveCheckPointImpl(enableStreaming, store, ctx, *checkPointID, &InterruptInfo{Data: legacyData}, interruptSignal)
           // ...
       }
   }
   gen.Send(event)
   ```

2. **On cancel (new in v0.9)** — when a `*CancelError` arrives and a checkpoint ID is set (`adk/runner.go:293-303`). A cancelled run is therefore resumable with `Runner.Resume` / `ResumeWithParams`.

3. **On `TurnLoop` exit (new in v0.9)** — when `Store` + `CheckpointID` are set, the loop saves a checkpoint on `Stop()` or business interrupt (including between-turn state: queued items), and deletes it on clean exit (`adk/turn_loop.go:613-633`, `:968-987`). Business interrupts during a turn are also persisted (commit `2532693`).

The save itself (`adk/interrupt.go:290-320`) gob-encodes `serialization` and calls `store.Set`.

There is still **no equivalent of LangGraph's per-task `put_writes`**: Eino does not durably commit after every super-step. A crash mid-tool-call with no interrupt or cancel loses everything since the last checkpoint.

### 5.6 Mid-run checkpointing (durable)

Mid-tool-call resume is supported when you explicitly call `Interrupt` / `StatefulInterrupt` inside the tool (`adk/interrupt.go:59-127`; tools typically use `tool.Interrupt` / `compose` equivalents) **or when the run is cancelled** at a safe point / immediately:
- The signal propagates up through `CompositeInterrupt` for wrapping agent-tool boundaries.
- `Runner` catches it, saves the checkpoint, forwards the event.
- `Runner.Resume` / `ResumeWithParams` re-enters at the same `Address`; state is restored via `compose.GetInterruptState` / `GetResumeContext` (`compose/resume.go:32,77`).
- During an active cancel, business interrupts are absorbed into the `CancelError`; on resume they re-fire naturally (`adk/cancel.go:163-191`).

A crash (process death) without a prior interrupt or cancel = lost progress.

### 5.7 Session ID format

**You choose.** `checkPointID` is any string (`internal/core/interrupt.go:31-34`). No format constraints, no tenant prefixing. `bridgeCheckpointID = "adk_react_mock_key"` (`adk/interrupt.go:367`) is an internal sentinel for agent-tool boundaries.

### 5.8 Pluggable store interface

`CheckPointStore` (+ optional `CheckPointDeleter`), re-exported as `adk.CheckPointStore` (`adk/runner.go:64-66`) and `compose.CheckPointStore` (`compose/checkpoint.go:53`), is **the** integration point. No schema, no migration helper, no versioning hook. Reference in-memory implementation:

```go
// adk/interrupt.go:380-407 (abridged)
type bridgeStore struct {
    mu   sync.Mutex
    data map[string][]byte
}

func (m *bridgeStore) Get(_ context.Context, key string) ([]byte, bool, error) {
    m.mu.Lock(); defer m.mu.Unlock()
    if v, ok := m.data[key]; ok { return append([]byte{}, v...), true, nil }
    return nil, false, nil
}

func (m *bridgeStore) Set(_ context.Context, key string, checkPoint []byte) error {
    m.mu.Lock(); defer m.mu.Unlock()
    if m.data == nil { m.data = make(map[string][]byte) }
    m.data[key] = append([]byte{}, checkPoint...)
    return nil
}
```

### 5.9 Schema evolution / migration

**No general migration helper for user state.** The framework migrates its own types: `preprocessADKCheckpoint` (`adk/interrupt.go:252-288`) byte-patches v0.8.0–v0.8.3 gob names; `preprocessComposeCheckpoint` (`adk/chatmodel.go:1728`) routes them through a compat decoder; `compose.MigrateCheckpointState` (`compose/checkpoint.go:285`) applies a `migrate(state any)` to nested states. v0.9 types carry `CheckpointSchema:` comments marking fields that must stay backward compatible (e.g. `adk/interrupt.go:208-209`, `adk/interface.go:375`), and several v0.9.x patch releases fixed checkpoint-compat bugs (commits `30f5961`, `60e1d99`, `b9539ec`).

For **your** types in `runSession.Values`, run-local values or TurnLoop items `T`:
- Types must be gob-encodable; `SetRunLocalValue` checks this up front (`adk/handler.go:338-365`, `checkGobEncodability` at `:433`).
- Register custom types with `schema.RegisterName[T]("a_unique_name")`.
- **Removing or renaming fields breaks old checkpoints** unless you write a compat decoder.

### 5.10 Export / replay

- **Export**: `store.Get(ctx, checkPointID)` returns the gob blob.
- **Replay**: `Runner.Resume` re-enters from the saved point. Deterministic replay from the start (frozen LLM responses) is not shipped; mock `model.BaseModel[M]` against recorded outputs yourself. v0.9's stable per-message IDs (`adk.GetMessageID`) make de-duplicating replayed events in a UI easier.

### 5.11 Cross-session memory

**Not provided on `main`.** No long-term memory / vector recall. Compose `components/retriever` adapters yourself — see Q17. (An "automemory" middleware exists only on the `alpha/10` branch.)

---

## 6. Multi-tenancy & Tenant Identity ⭐ THE KEY QUESTION

### 6.1 Run-loop tenant identity

Inputs to `Runner.Run` (`adk/runner.go:102-105`):

```go
func (r *TypedRunner[M]) Run(ctx context.Context, messages []M, opts ...AgentRunOption) *AsyncIterator[*TypedAgentEvent[M]]
```

- `ctx` — Go `context.Context`. Carries anything you want at every layer (tenant ID, request ID, trace span). The framework itself reads run context, addresses and cancel scopes from it.
- `messages` — input messages.
- `opts ...AgentRunOption` — common options (`adk/call_option.go:21-28`):

  ```go
  type options struct {
      sharedParentSession  bool
      sessionValues        map[string]any   // ← typical place for tenantId, locale, today's date
      checkPointID         *string
      skipTransferMessages bool
      handlers             []callbacks.Handler
      cancelCtx            *cancelContext   // new in v0.9 (WithCancel)
  }
  ```

  Plus ChatModelAgent-specific options (`adk/chatmodel.go:86-94`): chat-model options, tool options, per-agent-tool run options, the deprecated history modifier, and the new `afterToolCallsHook`.

- With `TurnLoop`, `GenInputResult.RunCtx` lets you derive a per-turn context (e.g. from the pushed item's tenant) and `RunOpts` carries per-turn options (`adk/turn_loop.go:636-668`).

There is **no typed `Context T` field** like LangGraph's `Runtime[ContextT]`. Tenant identity is **not a first-class field**: it lives in `context.Context` or in `WithSessionValues(map[string]any{"tenantId": "acme"})`, read back via `adk.GetSessionValue(ctx, "tenantId")` (`adk/runctx.go:234`). No type safety, no validation.

### 6.2 Tenant identity propagation into tool calls

Two mechanisms:

1. **`context.Context`** — the recommended path. Everything you set via `context.WithValue` reaches `tool.InvokableRun(ctx, argumentsInJSON, opts...)`. Session values are also readable from the tool's ctx via `adk.GetSessionValue`.
2. **`tool.Option`** — pass tool-specific options via `adk.WithToolOptions` (`adk/chatmodel.go:104`); each tool extracts its typed config with `tool.GetImplSpecificOptions[T]`.

Call path: `Runner.Run` → `flowAgent.Run` → `ChatModelAgent.Run` → `compose.Runnable.Invoke` → `ToolsNode` super-step → middleware chain → `tool.InvokableRun(ctx, args, opts...)`. The ctx is the one passed in, plus internal keys (address segments, run context, callbacks, cancel scope).

### 6.3 Tool call interface

`tool.InvokableTool` (`components/tool/interface.go:42-47`):

```go
type InvokableTool interface {
    BaseTool
    InvokableRun(ctx context.Context, argumentsInJSON string, opts ...Option) (string, error)
}
```

`argumentsInJSON` is a raw JSON string — the framework does not parse it unless you use `utils.InferTool` / `utils.NewTool`. That is the seam for server-side field injection.

For multimodal tools, `EnhancedInvokableTool` (`components/tool/interface.go:67-70`):

```go
type EnhancedInvokableTool interface {
    BaseTool
    InvokableRun(ctx context.Context, toolArgument *schema.ToolArgument, opts ...Option) (*schema.ToolResult, error)
}
```

Middleware wrappers see a `*adk.ToolContext{Name, CallID}` (`adk/handler.go:45-48`).

### 6.4 Forcing tool arguments from the harness

**Not first-class. You build it yourself; three hooks**:

**Pattern A — `ToolsNodeConfig.ToolArgumentsHandler`** (`compose/tool_node.go:215-224`). Runs once per call, after argument-alias remapping and before the tool:

```go
ToolArgumentsHandler: func(ctx context.Context, name, arguments string) (string, error) {
    if name == "topicSearch" {
        var args map[string]any
        if err := sonic.UnmarshalString(arguments, &args); err != nil { return "", err }
        args["tenantId"] = ctx.Value(tenantKey{}).(string)   // STRIP-AND-INJECT
        b, _ := sonic.Marshal(args)
        return string(b), nil
    }
    return arguments, nil
},
```

**Pattern B — `compose.ToolMiddleware.Invokable`** via `ToolsConfig.ToolCallMiddlewares`:

```go
mw := compose.ToolMiddleware{
    Invokable: func(next compose.InvokableToolEndpoint) compose.InvokableToolEndpoint {
        return func(ctx context.Context, in *compose.ToolInput) (*compose.ToolOutput, error) {
            if in.Name == "topicSearch" {
                var args map[string]any
                _ = sonic.UnmarshalString(in.Arguments, &args)
                args["tenantId"] = ctx.Value(tenantKey{})
                b, _ := sonic.Marshal(args)
                in.Arguments = string(b)
            }
            return next(ctx, in)
        }
    },
}
```

**Pattern C — `ChatModelAgentMiddleware.WrapInvokableToolCall`** (`adk/handler.go:193`), the recommended ADK path:

```go
func (h *MyHandler) WrapInvokableToolCall(ctx context.Context, endpoint adk.InvokableToolCallEndpoint, tCtx *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tCtx.Name != "topicSearch" { return endpoint, nil }
    return func(ctx context.Context, argumentsInJSON string, opts ...tool.Option) (string, error) {
        var args map[string]any
        _ = sonic.UnmarshalString(argumentsInJSON, &args)
        tenant, _ := adk.GetSessionValue(ctx, "tenantId")
        args["tenantId"] = tenant
        b, _ := sonic.Marshal(args)
        return endpoint(ctx, string(b), opts...)
    }, nil
}
```

**Honesty**: LangGraph's `InjectedToolArg` (declared at tool definition, stripped from the LLM-visible schema, injected from `Runtime.context`) is strictly cleaner. In Eino you write middleware and must also remove the field from the tool's JSON schema yourself (e.g. omit it from the `InferTool` input struct and read it from ctx inside the tool instead — usually the simpler option).

### 6.5 Tenant-aware visible tool selection

**Yes, two mechanisms with different security properties**:

1. **`BeforeAgent`** (once per run, `adk/handler.go:142`) gets a mutable `ChatModelAgentContext.Tools`. Changes affect **both** the LLM-visible schema **and** dispatch (`adk/chatmodel.go:390-392`; the filtered list is pushed into the ToolsNode via `WithToolList`, `adk/chatmodel.go:1487-1489`). Use this for tenant entitlements — a removed tool cannot be executed even if the model hallucinates its name.

   ```go
   func (h *TenantFilter) BeforeAgent(ctx context.Context, rc *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
       tenantID, _ := adk.GetSessionValue(ctx, "tenantId")
       var filtered []tool.BaseTool
       for _, t := range rc.Tools {
           info, _ := t.Info(ctx)
           if isToolAllowedForTenant(info.Name, tenantID.(string)) { filtered = append(filtered, t) }
       }
       rc.Tools = filtered
       return ctx, rc, nil
   }
   ```

2. **`BeforeModelRewriteState`** (before every model call, `adk/handler.go:171`) can rewrite `state.ToolInfos` and `state.DeferredToolInfos` (`adk/chatmodel.go:216-231`). Changes are persisted in agent state and are the recommended v0.9 path for per-turn filtering (`adk/chatmodel.go:394-397`); `toolsearch` uses it (`adk/middlewares/dynamictool/toolsearch/toolsearch.go:277-322`). This controls **visibility only**: the tool remains dispatchable, so pair it with a `WrapInvokableToolCall` guard if hidden tools must not run.

Filtering inside `WrapModel` via `model.WithTools` still works but is now explicitly discouraged (not persisted, breaks prompt cache; `adk/chatmodel.go:399-400`).

**Registry-side scoping** (register a skill or tool as tenant=acme only) is not provided — see Q11.5.

### 6.6 Per-tool-call auth propagation

**Not built-in.** The caller's identity reaches the tool only because **you** put it on `context.Context`. No automatic token pass-through, no per-tool STS / impersonation. To run tools under per-user permissions (e.g. BigQuery as the requester), extract identity in your handler, attach it to ctx, and have each tool build its client from ctx. For MCP tools, `officialmcp/session.TransportConfig.HTTPClient` lets you install a `RoundTripper` that resolves auth per request (eino-ext `components/tool/mcp/officialmcp/session/session.go:52-74`), which is the closest thing to automatic propagation.

### 6.7 Per-tenant rate limit + budget cap

**Not provided.** No USD budget enforcement, no per-tenant token ceiling. Read token counts from `ResponseMeta.Usage` (or `model.CallbackOutput.TokenUsage` in a callback) and enforce yourself. v0.9 gives a cleaner stop mechanism than raw `context.CancelFunc`: call the `AgentCancelFunc` from `WithCancel()` with `CancelAfterChatModel` so the run stops at a safe point and leaves a resumable checkpoint.

### ⭐ Required — light usage example

Show how to: (1) pass tenant/strategy/user; (2) restrict visible tools; (3) force `tenantId` server-side on `topicSearch` even if the LLM tries to override it.

```go
type TenantMW struct{ *adk.BaseChatModelAgentMiddleware }

// (2) restrict visible AND executable tools to topicSearch / iabSearch / audienceCreate
func (m *TenantMW) BeforeAgent(ctx context.Context, rc *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
    allowed := map[string]bool{"topicSearch": true, "iabSearch": true, "audienceCreate": true}
    var filtered []tool.BaseTool
    for _, t := range rc.Tools {
        if info, _ := t.Info(ctx); allowed[info.Name] { filtered = append(filtered, t) }
    }
    rc.Tools = filtered
    return ctx, rc, nil
}

// (3) FORCE tenantId from session values, overriding any LLM-supplied value
func (m *TenantMW) WrapInvokableToolCall(ctx context.Context, ep adk.InvokableToolCallEndpoint, tc *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tc.Name != "topicSearch" { return ep, nil }
    return func(ctx context.Context, argsJSON string, opts ...tool.Option) (string, error) {
        var args map[string]any
        _ = sonic.UnmarshalString(argsJSON, &args)
        args["tenantId"], _ = adk.GetSessionValue(ctx, "tenantId")
        b, _ := sonic.Marshal(args)
        return ep(ctx, string(b), opts...)
    }, nil
}

agent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: cm,
    ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{
        Tools: []tool.BaseTool{topicSearch, iabSearch, audienceCreate, bashExec, webFetch},
    }},
    Handlers: []adk.ChatModelAgentMiddleware{&TenantMW{BaseChatModelAgentMiddleware: &adk.BaseChatModelAgentMiddleware{}}},
})
runner := adk.NewRunner(ctx, adk.RunnerConfig{Agent: agent, EnableStreaming: true, CheckPointStore: pgStore})

// (1) pass tenant / strategy / user via WithSessionValues
iter := runner.Query(ctx, "build me a travel audience",
    adk.WithSessionValues(map[string]any{"tenantId": "acme", "targetingStrategyId": "strat-42", "userId": "u-123"}),
    adk.WithCheckPointID("conv-789"),
)
```

This works. Rough edges vs. LangGraph: (a) tool-arg injection is hand-rolled middleware, not declarative; (b) the LLM still sees `tenantId` in `topicSearch`'s schema unless you remove it from the tool's input struct.

---

## 7. Hook & Middleware Capabilities (Context Engineering)

### 7.1 Enumerate every hook / middleware / lifecycle callback

Four layers.

**Layer 1 — `callbacks.Handler` (graph-level, every component invocation)**:

| Name | Fires when | Capabilities |
|---|---|---|
| `OnStart` | Before any component begins (non-streaming input) | Read input, mutate context (passed to OnEnd), inject context values |
| `OnEnd` | After component returns (non-streaming output) | Read output, instrument metrics |
| `OnError` | Component returned an error | Read error |
| `OnStartWithStreamInput` | Component receives streaming input | Read+copy stream (must close copy) |
| `OnEndWithStreamOutput` | Component returns streaming output | Read+copy stream (must close copy) |

Implemented at `callbacks/interface.go:85` + `callbacks/aspect_inject.go`. Per-handler context propagation (OnStart ctx → OnEnd of the same handler) is at `callbacks/interface.go:65-71`. **No guaranteed handler order**. v0.9 adds agentic callback payloads (`components/model/agentic_callback_extra.go`, `components/prompt/agentic_callback_extra.go`) and `ComponentOfAgenticAgent` (`adk/callback.go:194`).

**Layer 2 — `AgentMiddleware` struct (deprecated)** (`adk/chatmodel.go:235-258`):

| Field | Fires when | Capabilities |
|---|---|---|
| `AdditionalInstruction string` | At agent build | Appends to system prompt |
| `AdditionalTools []tool.BaseTool` | At agent build | Appends to tool list |
| `BeforeChatModel func(ctx, *ChatModelAgentState) error` | Before each model invocation | Mutate state in place; can't change ctx |
| `AfterChatModel func(ctx, *ChatModelAgentState) error` | After each model invocation | Mutate state |
| `WrapToolCall compose.ToolMiddleware` | Around each tool dispatch | Full wrap |

**Layer 3 — `TypedChatModelAgentMiddleware[M]` interface (recommended)** (`adk/handler.go:139-257`):

| Method | Fires when | Capabilities |
|---|---|---|
| `BeforeAgent(ctx, *ChatModelAgentContext)` | Once before run | Mutate Instruction / Tools / ReturnDirectly / ToolSearchTool; return modified ctx |
| `AfterAgent(ctx, *TypedChatModelAgentState[M])` **(new v0.9)** | After successful terminal state (final answer or return-directly) | Read final state; cleanup; not called on errors |
| `BeforeModelRewriteState(ctx, state, *TypedModelContext[M])` | Before each model call | Rewrite `Messages`, `ToolInfos`, `DeferredToolInfos` (persisted); return modified ctx |
| `AfterModelRewriteState(ctx, state, mc)` | After each model call | Rewrite post-call state |
| `WrapInvokableToolCall(ctx, endpoint, *ToolContext)` | Around invokable tool call | Wrap endpoint (pre/post, deny, retry) |
| `WrapStreamableToolCall(...)` | Around streamable tool call | Same, streaming |
| `WrapEnhancedInvokableToolCall(...)` | Around enhanced invokable | Same, multimodal |
| `WrapEnhancedStreamableToolCall(...)` | Around enhanced streamable | Same, multimodal streaming |
| `WrapModel(ctx, model.BaseModel[M], mc)` | Around the model | Replace / wrap the model |

Embed `*adk.BaseChatModelAgentMiddleware` (`adk/handler.go:261-313`) for no-op defaults.

**Layer 4 — per-run hooks and built-in wrappers**:
- `adk.WithAfterToolCallsHook(fn)` (`adk/chatmodel.go:130`) — fires synchronously after each tool round, before the next model call (used with `TurnLoop` push + preempt).
- `NewEventSenderModelWrapper()` / `NewEventSenderToolWrapper()` (`adk/wrappers.go:266,559`) — place event emission at a chosen depth in the handler chain.
- `ModelRetryConfig.ShouldRetry` / `ModelFailoverConfig.ShouldFailover` / `GetFailoverModel` — callback-style hooks around model errors (Q15.2).
- `TurnLoopConfig.GenInput` / `GenResume` / `PrepareAgent` / `OnAgentEvents` — per-turn hooks.

Utilities: `adk.SendEvent(ctx, *AgentEvent)` (`adk/handler.go:425`); `adk.SetRunLocalValue` / `GetRunLocalValue` / `DeleteRunLocalValue` (`adk/handler.go:338-407`) for per-run state persisted across interrupt/resume; `adk.SendToolGenAction` (`adk/react.go:274`) to attach an `AgentAction` to a tool result.

### 7.2 Hook concurrency model

- **`callbacks.Handler`s** fire in registration order with no inter-handler context flow; treat them as independent observers.
- **`WrapModel` / `Wrap*ToolCall` form a chain**: first registered is outermost (`[A, B, C]` → `A(B(C(x)))`, `adk/chatmodel.go:349,379`). Each wrapper can pass a modified ctx to `next`.
- **`BeforeAgent` / `AfterAgent` / `BeforeModelRewriteState` / `AfterModelRewriteState`** run sequentially in registration order, fail-fast on error (`adk/handler.go:152-157`).
- **Tool dispatch within one super-step is parallel by default**; tool middlewares run per call in goroutines.

### 7.3 Specific capability tests

- **Inject system message at session start**: ✅ `BeforeAgent` appending to `rc.Instruction`, or f-string placeholders in `Instruction` filled from session values. For project-level instructions, `agentsmd` injects AGENTS.md content transiently before every model call (`adk/middlewares/agentsmd/agentsmd.go:17-20`).
- **Expand user input (slash commands, timestamp, attachments)**: ✅ `BeforeModelRewriteState` mutating `state.Messages`, or a custom `GenModelInput`. With `TurnLoop`, `GenInput` can merge/transform queued inputs before the run.
- **Mutate messages before each LLM call (prompt cache, redaction)**: ✅ `BeforeModelRewriteState` (`adk/handler.go:171`) or `WrapModel`.
- **Mutate tool input before dispatch (inject `tenantId`)**: ✅ `WrapInvokableToolCall`, `ToolArgumentsHandler` or `ToolAliases` (key remapping) — see Q6.4.
- **Mutate tool result before it returns to the LLM**: ✅ `WrapInvokableToolCall` — call `endpoint(...)`, mutate the string. `reduction` does this for oversized results.
- **Emit additional tool calls in response to a tool result**: ❌ **Not provided**. `adk.SendEvent` emits a custom event to the consumer, and `SendToolGenAction` attaches an action, but neither appends synthetic messages the LLM sees. Closest workaround: `AfterModelRewriteState` / `BeforeModelRewriteState` can append messages to state before the next call, or `WithAfterToolCallsHook` + `TurnLoop.Push(..., WithPreempt)` starts a new turn with extra input. **Genuine gap vs. Claude Agent SDK's `additional_messages`.**

### 7.4 Auto-compaction

**Yes — `adk/middlewares/summarization/`**:

```go
// adk/middlewares/summarization/summarization.go:56-152 (fields only)
type TypedConfig[M adk.MessageType] struct {
    Model              model.BaseModel[M]
    ModelOptions       []model.Option
    TokenCounter       TypedTokenCounterFunc[M] // default: improved char-based estimator (commit 4654826)
    Trigger            *TriggerCondition        // ContextTokens and/or ContextMessages; default 160k tokens
    EmitInternalEvents bool
    UserInstruction    string
    TranscriptFilePath string
    GenModelInput      TypedGenModelInputFunc[M]
    Finalize           TypedFinalizeFunc[M]
    Callback           TypedCallbackFunc[M]
    Retry              *TypedRetryConfig[M]     // retry summary generation
    Failover           *TypedFailoverConfig[M]  // fall back to another summarizer model
}
```

Fires inside `BeforeModelRewriteState` when the counter exceeds the trigger (default `160000` tokens, `summarization.go:373-379`; was 170k in v0.8.13). v0.9 adds a `TypedMiddleware.Summarize` method for on-demand summarization, `PopulateUserMessages` helpers and finalizer builders (`finalizer_builder.go`). A transcript file path can be embedded in the summary so the model can re-read full history.

### 7.5 Prompt cache optimization

- **Provider-cache-aware**: yes, in the adapters. The eino-ext Claude adapter supports explicit breakpoints (`claude.SetMessageBreakpoint`, `SetToolInfoBreakpoint`, `components/model/claude/message_extra.go:63-68`), per-request `WithAutoCacheControl` (`components/model/claude/option.go:89`) and, new since the last refresh, a `Config.AutoCacheControl` field that places breakpoints on system, tools and the last user message of each turn on every request (`components/model/claude/claude.go:302-305`). The agentic adapters (Claude, Ark, OpenAI Responses, Gemini) gained cache-control support (eino-ext commit `1372ee4`); `agenticopenai` exposes `WithResponsesPromptCacheKey` (`components/model/agenticopenai/option.go:97`). (The previous report said no breakpoint helper existed; that was incorrect even at v0.8.13.)
- **Stable-prefix preservation**: the framework does not reshuffle history. v0.9 guidance pushes tool-list changes into `BeforeModelRewriteState` (persisted, stable across calls) and warns that changing tools in `WrapModel` breaks the cache (`adk/chatmodel.go:399-400`); `agentsmd` injects transiently so it does not pollute the summarized history; `toolsearch` warns its client-side mode may invalidate KV-cache and offers provider-native deferred tools instead (`toolsearch.go:41-49`).
- **Automatic vs. manual**: automatic for Claude when `AutoCacheControl` is set; manual elsewhere.

`PromptTokenDetails.CachedTokens` and the new `CacheWriteTokens` (`schema/message.go:556-561`) let you observe hit rate and write cost.

### 7.6 Tool result clearing

**Yes — `adk/middlewares/reduction/`** (`reduction.go:38-149`), two phases:

1. **Truncation** (right after a tool returns): if output exceeds `MaxLengthForTrunc`, the full content is written to the configured `Backend` and the tool message is replaced with a truncated notice that now names the read tool to use (commit `922b6a8`). `TruncExcludeTools` opts tools out.
2. **Clear** (in `BeforeModelRewriteState`): if total tokens exceed `MaxTokensForClear`, older tool-call arguments and results (outside the last `ClearRetentionSuffixLimit` messages) are offloaded to the backend and replaced with stubs; `ClearAtLeastTokens` and `ClearExcludeTools` tune it; custom `TruncHandler` / `ClearHandler` give full control.

v0.9 fixes preserve streaming tool output during reduction (commit `747023b`). The older filesystem-middleware `large_tool_result.go` path is superseded by `reduction` (`reduction/legacy.go:40,65` marks the old constructors deprecated).

### 7.7 Progressive disclosure

Several mechanisms, the most complete set in any Go framework benchmarked:
- **Filesystem stash + on-demand re-read**: `reduction` offloads to a `filesystem.Backend`; the model retrieves via `read_file` with offset/limit (`adk/middlewares/filesystem/prompt.go:28-42,60`).
- **Lazy skills**: the `skill` tool lists names + descriptions; bodies load on invocation (Q10.5).
- **Lazy tools**: `toolsearch` hides `DynamicTools` until the model calls `tool_search` (keyword search or `select:a,b`, `toolsearch.go:416-470`), or hands them to the provider as deferred tools when `UseModelToolSearch` is true (`toolsearch.go:283-289`).
- **Transcript pointer**: summarization can embed `TranscriptFilePath` so the model can re-read raw history.

### 7.8 Architectural diagram

```
TurnLoop (optional): Push → GenInput → PrepareAgent → [Runner.Run] → OnAgentEvents → next turn
                                                          │
Runner.Run(ctx, messages)                                 ▼
   │
flowAgent.Run                       ─── callbacks.OnStart (component=Agent)
   │
ChatModelAgent.Run
   │  BeforeAgent (handlers, registration order) → Instruction, Tools, ReturnDirectly, ToolSearchTool
   ▼
LOOP (until no tool calls / MaxIterations / cancel):
   │  ┌──────────── ChatModel super-step ────────────────────┐
   │  │  AgentMiddleware.BeforeChatModel (deprecated)        │
   │  │  BeforeModelRewriteState → Messages, ToolInfos,      │
   │  │                            DeferredToolInfos         │
   │  │  failoverModelWrapper (if configured)                │
   │  │  retryModelWrapper (if configured)                   │
   │  │  eventSenderModelWrapper                             │
   │  │  WrapModel (user, outermost first)                   │
   │  │  callbackInjectionModelWrapper                       │
   │  │  ─────► failoverProxyModel / model.Generate|Stream   │
   │  │           callbacks.OnStart/OnEnd (component=ChatModel)
   │  │  AfterModelRewriteState                              │
   │  │  AgentMiddleware.AfterChatModel                      │
   │  └──────────────────────────────────────────────────────┘
   │  cancel safe-point (CancelAfterChatModel)
   │  ┌──────────── Tools super-step (parallel goroutines) ──┐
   │  │  alias resolution → ToolArgumentsHandler             │
   │  │  eventSenderToolWrapper                              │
   │  │  ToolsConfig.ToolCallMiddlewares                     │
   │  │  AgentMiddleware.WrapToolCall (deprecated)           │
   │  │  ChatModelAgentMiddleware.Wrap*ToolCall              │
   │  │  callbackInjectedToolCall                            │
   │  │  ────► tool.InvokableRun / StreamableRun             │
   │  └──────────────────────────────────────────────────────┘
   │  AfterToolCalls (WithAfterToolCallsHook)
   │  cancel safe-point (CancelAfterToolCalls)
   ▼  back to ChatModel (or END)
AfterAgent (on success) ─── callbacks.OnEnd (component=Agent)
```

### ⭐ Required — light usage example

```go
type PredictMW struct{ *adk.BaseChatModelAgentMiddleware }

// (1) SessionStart hook — inject "tenant=acme, locale=fr-FR, today=2026-05-16"
func (m *PredictMW) BeforeAgent(ctx context.Context, rc *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
    tenant, _ := adk.GetSessionValue(ctx, "tenantId")
    rc.Instruction += fmt.Sprintf("\n\nContext: tenant=%v, locale=fr-FR, today=2026-05-16.", tenant)
    return ctx, rc, nil
}

// (2) PreToolUse on topicSearch — inject tenantId; (3) PostToolUse — summarize >50 results in place
func (m *PredictMW) WrapInvokableToolCall(ctx context.Context, ep adk.InvokableToolCallEndpoint, tc *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tc.Name != "topicSearch" { return ep, nil }
    return func(ctx context.Context, args string, opts ...tool.Option) (string, error) {
        var a map[string]any
        _ = sonic.UnmarshalString(args, &a)
        a["tenantId"], _ = adk.GetSessionValue(ctx, "tenantId")
        b, _ := sonic.Marshal(a)
        out, err := ep(ctx, string(b), opts...)
        if err != nil { return out, err }
        var res struct{ Topics []string `json:"topics"` }
        _ = sonic.UnmarshalString(out, &res)
        if len(res.Topics) > 50 {
            out, _ = sonic.MarshalString(map[string]any{"summary": summarizeTopics(res.Topics), "count": len(res.Topics)})
        }
        return out, nil
    }, nil
}

agent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: cm,
    Handlers:    []adk.ChatModelAgentMiddleware{&PredictMW{BaseChatModelAgentMiddleware: &adk.BaseChatModelAgentMiddleware{}}},
    ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{Tools: tools}},
})
```

---

## 8. HTTP API

### 8.1 Does the framework ship an HTTP server?

**No first-party HTTP server.** Core eino has no `Server`, no route package and no `ListenAndServe`. You bring your own HTTP layer (gin, hertz, fiber, mux, chi, stdlib).

New since the last refresh: **eino-ext `acp/`** bridges ADK agents to the [Agent Client Protocol](https://agentclientprotocol.com) (JSON-RPC sessions used by editors such as Zed). It ships two functions — `AgentEventToSessionUpdate` (`eino-ext/acp/conv.go:99`) converts each `AgentEvent` into ACP `SessionUpdate` notifications (text / thought / tool call / tool call update / interrupt), and `NewClientToolsMiddleware` (`eino-ext/acp/backend.go:143`) maps the filesystem middleware's tools onto the ACP client's filesystem and terminal. The transports come from `github.com/eino-contrib/acp`; the example (`eino-ext/acp/examples/main.go:43-87`) serves stdio or mounts an ACP HTTP server on Hertz. You still implement the ACP agent methods (`Initialize`, `NewSession`, `Prompt`; `acp/examples/agent.go:71-129`) yourself. This is a protocol adapter, not a multi-tenant HTTP API.

### 8.2 HTTP streaming protocol (SSE/WS)

**Not provided — BYO** for HTTP/SSE. In-process the runtime uses `*AsyncIterator[*AgentEvent]`; you serialize each frame. The only shipped wire mapping is ACP session updates (JSON-RPC notifications) via `eino-ext/acp`. The v0.9 quickstart's Ch. 10 shows a business-layer "A2UI" event stream to a web page, explicitly outside the framework.

### 8.3 HTTP endpoints that start an agent run

**Not provided — BYO.** Typical handler:

```go
http.HandleFunc("/v1/runs", func(w http.ResponseWriter, r *http.Request) {
    tenant := r.Header.Get("X-Tenant-Id")
    var body struct{ Message, ConversationID string }
    json.NewDecoder(r.Body).Decode(&body)
    runOpt, cancel := adk.WithCancel()
    registerCancel(body.ConversationID, cancel) // your registry, used by the DELETE handler
    iter := runner.Query(r.Context(), body.Message,
        adk.WithSessionValues(map[string]any{"tenantId": tenant}),
        adk.WithCheckPointID(body.ConversationID), runOpt)
    w.Header().Set("Content-Type", "text/event-stream")
    flusher, _ := w.(http.Flusher)
    for { e, ok := iter.Next(); if !ok { break }; writeSSE(w, toWireEvent(e)); flusher.Flush() }
})
```

### 8.4 Interrupt / cancel in-flight run

**No HTTP route; first-class in-process cancel API (new in v0.9).** `adk.WithCancel()` (`adk/cancel.go:239-247`) returns an `AgentRunOption` and an `AgentCancelFunc`:

```go
// adk/cancel.go:96-150 (abridged)
type AgentCancelFunc func(...AgentCancelOption) (*CancelHandle, bool)
func WithAgentCancelMode(mode CancelMode) AgentCancelOption      // CancelImmediate | CancelAfterChatModel | CancelAfterToolCalls
func WithAgentCancelTimeout(timeout time.Duration) AgentCancelOption // escalate to immediate after timeout
func WithRecursive() AgentCancelOption                            // propagate to nested agents
func (h *CancelHandle) Wait() error                               // nil | ErrCancelTimeout | ErrExecutionEnded
```

The run terminates with a `*CancelError` event and, if a checkpoint ID is set, a resumable checkpoint (`adk/runner.go:293-303`). `TurnLoop.Stop(WithGraceful()|WithImmediate()|WithGracefulTimeout(d))` and `Push(item, WithPreempt(AfterToolCalls))` use the same machinery. Cancelling the request `context.Context` still works but leaves no checkpoint. You expose `cancel()` behind your own `DELETE /runs/{id}`.

### 8.5 Resume / replay endpoint

**BYO.** `Runner.Resume(ctx, checkPointID)` / `ResumeWithParams` exist at the Go level; `TurnLoop` resumes automatically from `CheckpointID` on `Run()` and calls `GenResume` with interrupted / unhandled / new items (`adk/turn_loop.go:571-584`). You expose these as endpoints. Replaying past events to a reopened tab requires your own event log (eino does not persist the event stream itself, only the checkpoint).

### 8.6 HITL approval workflow

**Not first-class over HTTP.** At the runtime level:
- Tool code calls an interrupt (`adk.Interrupt` / `StatefulInterrupt`, or tool/compose interrupt helpers) to pause.
- `Runner` saves the checkpoint and emits an event with `Action.Interrupted.InterruptContexts`.
- Caller stores the verdict and calls `runner.ResumeWithParams(ctx, checkpointID, &adk.ResumeParams{Targets: map[string]any{interruptCtx.ID: approval}})`.

The paused state is observable only through the interrupt event your serializer emits (or, over ACP, the `_meta["eino:interrupted"]` chunk produced by the default converter, customizable via `EventConverterOption.InterruptConverter`). Agentic models also surface provider-side MCP approval requests as `mcp_tool_approval_request` content blocks (`schema/agentic_message.go:540-560`).

### 8.7 Token streaming

- **Text delta**: each assistant `AgentEvent` with `IsStreaming: true` carries a `*schema.StreamReader[M]`; iterate and forward each chunk's `Content` (or content blocks for `AgenticMessage`).
- **Partial tool arguments**: tool-call deltas arrive in streamed assistant chunks (`ToolCalls[i].Index` + partial `Function.Arguments`, `schema/message.go:133-145`); merge via `schema.ConcatMessages`. No separate "tool-arg-fragment" event. The ACP converter shows one buffering strategy (accumulate per index, flush on EOF; `acp/conv_test.go` "StreamingToolCallAccumulation").
- **Agent activity**: tool results arrive as tool-role events; sub-agent events when `EmitInternalEvents` is on; custom events via `SendEvent`.

Sample frames (your serialization):

```
event: text_delta
data: {"msgId":"6f1c…","agent":"supervisor","delta":"Looking at travel"}

event: tool_args_delta
data: {"msgId":"6f1c…","index":0,"toolCallId":"call_xyz","name":"topicSearch","argsDelta":"{\"theme\":\"tra"}

event: tool_result
data: {"agent":"supervisor","toolCallId":"call_xyz","name":"topicSearch","content":"{\"topics\":[…]}"}
```

### 8.8 Authentication & Authorisation

**Not provided.** JWT validation, tenant extraction and resource authorization happen in your router middleware before `runner.Run`. Eino has no notion of route-, thread- or resource-level authz.

### 8.9 Tool-call state reconstruction

Linked by **explicit `ToolCallID`**. The assistant's `ToolCall.ID` becomes the tool message's `ToolCallID`; parallel results keep input order (`compose/tool_node.go:72-79`). Middleware sees the ID as `ToolContext.CallID` (`adk/handler.go:45-48`). For `AgenticMessage`, function tool call and result blocks carry the call ID (`schema/agentic_message.go:294-389`).

```go
// schema/message.go:133-145
type ToolCall struct {
    Index    *int           `json:"index,omitempty"` // for streaming chunk merging
    ID       string         `json:"id"`              // ← linkage key
    Type     string         `json:"type"`
    Function FunctionCall   `json:"function"`
    Extra    map[string]any `json:"extra,omitempty"`
}

// schema/message.go:521-523 (Message fields)
ToolCallID string `json:"tool_call_id,omitempty"` // ← linkage key on tool message
ToolName   string `json:"tool_name,omitempty"`
```

v0.9 also stamps a stable eino message ID per message (`adk.GetMessageID`), useful to reconcile streamed chunks with the final message in a client.

### 8.10 Health checks / graceful shutdown

**Not provided** at the HTTP level. For drain, v0.9 gives you building blocks: `TurnLoop.Stop(WithGraceful())` + `Wait()` returns `UnhandledItems` / `InterruptedItems` and attempts a checkpoint (`adk/turn_loop.go:794-843`), and `AgentCancelFunc` with `CancelAfterToolCalls` stops a single run at a safe point. Wiring SIGTERM to those is your job; `/healthz`, `/readyz`, `/metrics` are yours.

### ⭐ Required — light usage example

Since there's no HTTP layer, the "usage" is what *you* build:

```bash
# (1) start a run — your host endpoint
curl -N -X POST https://predict.example.com/v1/runs \
  -H 'X-Tenant-Id: acme' -H 'Content-Type: application/json' \
  -d '{"message":"build a travel audience","conversationId":"conv-789"}'

# (2) sample SSE frames (your serialization of AgentEvent)
event: start
data: {"conversationId":"conv-789"}

event: tool_use
data: {"agent":"supervisor","toolCallId":"call_xyz","toolName":"topicSearch","args":{"theme":"travel"}}

event: done
data: {"agent":"supervisor"}

# (3) cancel — your endpoint calls the AgentCancelFunc from adk.WithCancel()
curl -X DELETE 'https://predict.example.com/v1/runs/conv-789?mode=after_tool_calls'

# (4) approve a paused tool call — your endpoint calls runner.ResumeWithParams
curl -X POST https://predict.example.com/v1/runs/conv-789/approve \
  -H 'Content-Type: application/json' \
  -d '{"interruptId":"<InterruptCtx.ID>","approved":true}'
```

**None of these endpoints exist in Eino. You write all four.** Recommended host pattern: wrap `Runner` (or one `TurnLoop` per session) behind your router, serialize `AgentEvent` to SSE, keep a `conversationID → AgentCancelFunc` map for cancel, surface `ResumeWithParams` for HITL. If your clients speak ACP, `eino-ext/acp` covers the event mapping.

---

## 9. Sub-agents

### 9.1 Mechanism

Three mechanisms, all in-process. v0.9 ranks them explicitly:

1. **Agents-as-tools (recommended)** via `NewAgentTool` / `NewTypedAgentTool` (`adk/agent_tool.go:93-118`). Wraps an agent as a `tool.BaseTool`; the inner agent runs with a shared parent session; events optionally bubble up via `EmitInternalEvents`. Options: `WithFullChatHistoryAsInput()`, `WithAgentInputSchema(...)` (`adk/agent_tool.go:50-61`).
2. **`DeepAgent` (recommended)** — `deep.New` / `deep.NewTyped` (`adk/prebuilt/deep/deep.go:116-173`) builds a `ChatModelAgent` with a `task` tool over registered sub-agents, write-todos, and filesystem/shell middlewares.
3. **Transfer-based handoff** via `SetSubAgents` (`adk/flow.go:75`) with the `transfer_to_agent` tool (`adk/chatmodel.go:584-591`), and **workflow agents** `NewSequentialAgent` / `NewParallelAgent` / `NewLoopAgent` (`adk/workflow.go:694-712`). Both are marked **NOT RECOMMENDED**: "Agent transfer with full context sharing between agents has not proven to be more effective empirically" (`adk/chatmodel.go:292-300`, `adk/workflow.go:630-655`).

Prebuilt patterns: `supervisor.New` (`adk/prebuilt/supervisor/supervisor.go:101`, built on transfer), `deep.New`, `planexecute.New` (`adk/prebuilt/planexecute/plan_execute.go:862`).

### 9.2 Configuration

- **Struct-registered at boot**: `ChatModelAgentConfig`, `deep.Config`, `ParallelAgentConfig`, `supervisor.Config` are Go structs.
- **Markdown file**: via the `skill` middleware — SKILL.md with `agent: <name>` and `context: fork | fork_with_context` spawns a sub-agent from your `AgentHub`.
- **Inlined per call**: no — sub-agents are constructed before the run. With `TurnLoop`, `PrepareAgent` builds the agent per turn, so the sub-agent set can vary by turn.
- **LLM-generated at runtime**: no.

### 9.3 LLM-generated configs

**Not supported.** The closest pattern is `deep`'s task tool (`adk/prebuilt/deep/task_tool.go:126-175`): the LLM picks a `subagent_type` from a fixed registry and supplies a free-text description. A custom `AgentHub` could construct agents dynamically from a name the LLM chooses, but that is your code.

### 9.4 Output handling

- Agents-as-tools: a single string — the text of the last message — becomes the tool result (`adk/agent_tool.go:266-281`), linked to the parent's `tool_call_id`. Inner interrupts propagate as `tool.CompositeInterrupt` (`adk/agent_tool.go:250-261`).
- Optionally all sub-agent events stream up via `ToolsConfig.EmitInternalEvents: true` (`adk/chatmodel.go:141-155`) — for UI only; not recorded in the parent session. v0.9 fixed this for the agentic path (commit `72796c1`).
- Skill fork mode: `FormatForkResult` lets you shape the returned string (`adk/middlewares/skill/skill.go:135-188`).

### 9.5 Concurrency model

- **Agents-as-tools**: parallel for free — `ToolsNode` runs the N agent-tool calls of one assistant message in N goroutines (`ExecuteSequentially: false`, `compose/tool_node.go:210-213`).
- **Parallel workflow (NOT RECOMMENDED)**: `runParallel` (`adk/workflow.go:466-606`) — the actual fan-out:

  ```go
  // adk/workflow.go:519-570 (abridged)
  for i := range a.subAgents {
      wg.Add(1)
      go func(idx int, agent *flowAgent) {
          defer func() { /* recover */ wg.Done() }()
          childCancelCtx := deriveCheckpointAwareSubAgentCancelContext(childContexts[idx], opts)
          childOpts := appendCancelContextOption(opts, childCancelCtx)
          iterator := agent.Run(childContexts[idx], nil, childOpts...) // or Resume
          for {
              event, ok := iterator.Next()
              if !ok { break }
              if event.Action != nil && event.Action.internalInterrupted != nil { /* collect */ break }
              generator.Send(event)
          }
      }(i, a.subAgents[i])
  }
  wg.Wait()
  ```

  then `joinRunCtxs(ctx, childContexts...)` (`adk/workflow.go:574`).
- Sequential: `runSequential` (`adk/workflow.go:177`). Loop: `runLoop` (`adk/workflow.go:323`).
- Cancel with `WithRecursive()` propagates into checkpoint-aware sub-agent boundaries (`adk/cancel.go:44-63`).

### 9.6 Context isolation

- `agentTool`: runs a fresh `TypedRunner` over the inner agent (`adk/agent_tool.go:400`) with a shared parent session (k-v values), its own run context and events; input is the tool argument (or full history with `WithFullChatHistoryAsInput`).
- Parallel workflow: each branch forks the `runContext` (`forkRunCtx`, `adk/runctx.go:478`), sharing Values but not events until commit.
- Transfer handoff: the destination inherits the same `runContext`; transfer messages are added to history.
- Skill fork modes: `fork` starts from the skill content only; `fork_with_context` replays the parent's messages (`adk/middlewares/skill/skill.go:510-575`).
- `ClearRunCtx(ctx)` (`adk/runctx.go:533`) explicitly isolates a nested system.

### 9.7 Lifecycle events

- `callbacks.Handler.OnStart` / `OnEnd` fire per agent boundary; `RunInfo.Component = ComponentOfAgent` (`adk/callback.go:120`) and `RunInfo.Type` distinguishes `ChatModel` / `Sequential` / `Parallel` / `Loop` / `Supervisor`.
- Per-message sub-agent events are not in the parent iterator by default — opt in with `EmitInternalEvents: true`.

### 9.8 Sub-agent model override

**Yes — first-class.** Each `ChatModelAgentConfig.Model` is independent, and v0.9 adds per-agent `ModelRetryConfig` / `ModelFailoverConfig`:

```go
worker, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "worker", Description: "cheap worker", Model: claudeHaiku,
})
supervisor, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: claudeOpus,
    ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{
        Tools: []tool.BaseTool{adk.NewAgentTool(ctx, worker)},
    }},
})
```

Skills can also pin a model per skill via frontmatter `model:` resolved through `ModelHub` (`adk/middlewares/skill/skill.go:92-97`, `:516-525`).

### ⭐ Required — light usage example

Recommended v0.9 pattern — agents-as-tools, parallel via the ToolsNode:

```go
makePersona := func(name, prompt string) adk.Agent {
    a, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
        Name: name, Description: name + " persona researcher",
        Model: cm, Instruction: prompt,
        ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{Tools: []tool.BaseTool{topicSearch}}},
    })
    return a
}
youngMom := makePersona("persona-young-mom", "You are a 32-year-old mother of two...")
techBro  := makePersona("persona-tech-bro",  "You are a 28-year-old SF software engineer...")
retiree  := makePersona("persona-retiree",   "You are a 68-year-old retired teacher...")

parent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: cm,
    Instruction: "Call all three persona-* tools in ONE response, then merge their suggestions.",
    ToolsConfig: adk.ToolsConfig{
        ToolsNodeConfig: compose.ToolsNodeConfig{Tools: []tool.BaseTool{
            adk.NewAgentTool(ctx, youngMom), adk.NewAgentTool(ctx, techBro), adk.NewAgentTool(ctx, retiree),
        }}, // ExecuteSequentially=false (default) → 3 goroutines
        EmitInternalEvents: true, // stream persona events to the caller
    },
})
iter := adk.NewRunner(ctx, adk.RunnerConfig{Agent: parent}).Query(ctx, "Suggest 5 video topics for our travel campaign.")
for { e, ok := iter.Next(); if !ok { break }; fmt.Printf("[%s] %v\n", e.AgentName, e.Output) }
```

**Where the parent receives each result**: each persona's final message text becomes the tool message for the `tool_call_id` the LLM emitted; the parent LLM sees all three on its next iteration. Deterministic fan-out (no LLM choice) is still possible with `adk.NewParallelAgent(ctx, &adk.ParallelAgentConfig{SubAgents: []adk.Agent{youngMom, techBro, retiree}})`, but that API is marked NOT RECOMMENDED.

---

## 10. Skills

### 10.1 First-class concept?

**Yes — first-class via `adk/middlewares/skill/`.** A `ChatModelAgentMiddleware` that surfaces a `skill` tool (renameable via `SkillToolName`). Generified in v0.9 (`NewTyped[M]`, `skill.go:199`) for the `AgenticMessage` path; behaviour unchanged. The closest match in any Go framework benchmarked to Claude Code's SKILL.md model. The companion **`agentsmd`** middleware (new) covers the always-on AGENTS.md / CLAUDE.md style of instructions.

### 10.2 File format

`SKILL.md` with **YAML frontmatter** (`adk/middlewares/skill/skill.go:48-63`):

```yaml
---
name: Generate-Audience-From-Brief
description: Turn a brief into a Predict audience.
context: fork_with_context     # "fork" | "fork_with_context" | "" (inline)
agent: audience-builder        # OPTIONAL — agent name resolved via AgentHub
model: gpt-4o                  # OPTIONAL — model name resolved via ModelHub
---
# Markdown body becomes the skill instructions / sub-agent prompt
```

```go
// adk/middlewares/skill/skill.go:48-63
type FrontMatter struct {
    Name        string      `yaml:"name"`
    Description string      `yaml:"description"`
    Context     ContextMode `yaml:"context"`
    Agent       string      `yaml:"agent"`
    Model       string      `yaml:"model"`
}

type Skill struct {
    FrontMatter
    Content       string // markdown body
    BaseDirectory string // absolute dir where SKILL.md lives
}
```

No validators beyond YAML parsing; no version or scope fields.

### 10.3 Loader mechanism

**Pluggable `Backend` interface** (`adk/middlewares/skill/skill.go:66-69`):

```go
type Backend interface {
    List(ctx context.Context) ([]FrontMatter, error)
    Get(ctx context.Context, name string) (Skill, error)
}
```

`NewBackendFromFilesystem` (`adk/middlewares/skill/filesystem_backend.go:49`) scans **first-level subdirectories** of `BaseDir` for `SKILL.md` over any `filesystem.Backend` (in-memory `filesystem.NewInMemoryBackend()`, eino-ext `local`, `agentkit` sandbox, or the ACP client backend). Implement `Backend` against Postgres, S3 or HTTP yourself.

### 10.4 Invocation

**Tool call.** The LLM calls `skill({"skill": "<name>"})`; the middleware loads the skill and:
- **Inline** (`context: ""`): returns the markdown body (wrapped with the base directory, `skill.go:497-507`) as the tool result.
- **Fork** (`context: fork`): resolves an agent via `AgentHub.Get(ctx, frontMatter.Agent, opts)` (optionally with a `ModelHub` model), runs it with the skill content as input, returns its final message (`skill.go:510-575`).
- **Fork-with-context**: same, but the parent's message history and tool-call ID are passed along (`skill.go:538-547`).

Hooks: `BuildContent`, `BuildForkMessages`, `FormatForkResult`, `CustomToolDescription`, `CustomToolParams`, `CustomSystemPrompt` (`skill.go:135-188`). If `model:` is set and the skill runs inline, `setActiveModel` (`skill.go:443`) stores it in a run-local value and the middleware's `WrapModel` (`skill.go:281`) swaps the model for subsequent calls.

### 10.5 Loading mode

**Lazy.** The tool description enumerates name + description per skill (`renderToolDescription`, `skill.go:698`); bodies load on invocation.

### 10.6 Skill composition

- A fork-mode skill runs a sub-agent that can itself have tools, sub-agents and the skill middleware — full recursion.
- The skill body can reference files in `BaseDirectory` (passed in the injected content), so scripts, JSON examples and `reference/*.md` can be bundled alongside SKILL.md and read with the filesystem tools. The v0.9 quickstart's Ch. 9 uses exactly this layout (`SKILL.md` + `reference/*.md`) with the eino-ext skill packs.
- No first-class `include:` of another skill; a skill calls others via normal tool invocation if the spawned agent has the middleware.
- `agentsmd` supports `@import` of other files (max depth 5) with byte budgets (`adk/middlewares/agentsmd/agentsmd.go:32-62`), which is composition for always-on instructions rather than for skills.

### ⭐ Required — light usage example

```go
// 1. Author /skills/generate-audience-from-brief/SKILL.md:
//    ---
//    name: Generate-Audience-From-Brief
//    description: Turn a brief into a Predict audience JSON.
//    context: fork_with_context
//    agent: audience-builder
//    ---
//    # Generate Audience From Brief
//    1. Identify the primary theme (topicSearch)  2. IAB categories (iabSearch)
//    3. Combine via audienceCreate. Output: { "audienceId": "...", "rules": [...] }

// 2. Load at runtime from the filesystem
fsBack, _ := local.NewBackend(ctx, &local.Config{}) // eino-ext/adk/backend/local
skillBack, _ := skill.NewBackendFromFilesystem(ctx, &skill.BackendFromFilesystemConfig{Backend: fsBack, BaseDir: "/skills"})

skillMW, _ := skill.NewMiddleware(ctx, &skill.Config{
    Backend:  skillBack,
    AgentHub: &myAgentHub{"audience-builder": audienceBuilderAgent},
    ModelHub: &myModelHub{cm: cm},
})

supervisor, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: cm,
    Instruction: "Use the `skill` tool to discover and run available workflows.",
    Handlers:    []adk.ChatModelAgentMiddleware{skillMW},
})

// 3. The LLM sees a `skill` tool whose description lists
//    "- Generate-Audience-From-Brief: Turn a brief into a Predict audience JSON."
//    and calls skill({"skill":"Generate-Audience-From-Brief"}); the middleware forks
//    audienceBuilderAgent with parent history + skill body and returns its final answer.
iter := adk.NewRunner(ctx, adk.RunnerConfig{Agent: supervisor}).
    Query(ctx, "Take this brief and build an audience: 'Travel enthusiasts in fr-FR'.")
```

---

## 11. Resource Manager

### 11.1 First-class Resource Manager?

**No — BYO.** No `Registry`, `SkillSource`, versioning or publishing workflow. The seams:

- `skill.Backend` (`adk/middlewares/skill/skill.go:66`) — skill source
- `skill.TypedAgentHub[M]` (`adk/middlewares/skill/skill.go:82`) — agent source
- `skill.TypedModelHub[M]` (`adk/middlewares/skill/skill.go:92`) — model source
- `agentsmd.Backend` (`adk/middlewares/agentsmd/loader.go:70-77`) — AGENTS.md file source
- `toolsearch.Config.DynamicTools` — a static list of deferred tools

None are layered, scoped or versioned.

### 11.2 Loading sources

| Source | Provided | How configured |
|---|---|---|
| Local filesystem | ✅ `NewBackendFromFilesystem` over any `filesystem.Backend` (in-memory, eino-ext `local`, `agentkit`, ACP client) | `BackendFromFilesystemConfig{Backend, BaseDir}` |
| Git / GitHub | ❌ Not provided | BYO `Backend` (go-git clone, then scan) |
| OCI / container registries | ❌ Not provided | BYO |
| Cloud object storage (S3, GCS, R2) | ❌ Not provided | BYO `Backend` (or a `filesystem.Backend` over a bucket) |
| Postgres / relational DB | ❌ Not provided | BYO — `List` runs a `SELECT ... WHERE tenant_id=$1` |
| Vendor managed registry | ❌ Not provided | BYO |
| HTTP fetch | ❌ Not provided | BYO `http.Get` backend |

### 11.3 Source composition / priority

**Not provided.** Implement a composing `Backend`:

```go
type layeredBackend struct{ tenant, global skill.Backend }
func (b *layeredBackend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    t, _ := b.tenant.List(ctx)
    g, _ := b.global.List(ctx)
    return mergeWithTenantWinning(t, g), nil
}
```

### 11.4 Versioning model

**Not provided.** No semver, content hashes or rollback.

### 11.5 Scoping

**Not provided at the framework level, on either side.** `FrontMatter` has no scope field and there is no publish-time scoping. Runtime visibility can be derived per request because `Backend.List` / `Get` receive `ctx`:

```go
type tenantBackend struct{ base skill.Backend }
func (b *tenantBackend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    tenant, _ := adk.GetSessionValue(ctx, "tenantId")
    all, _ := b.base.List(ctx)
    return filterByTenantPolicy(all, tenant.(string)), nil
}
```

`Get` must enforce the same policy, otherwise a model that guesses a hidden skill name can still load it. Tools follow the same pattern via `BeforeAgent` (Q6.5).

### 11.6 Deployment workflow

**Not provided.** No draft / review / promote, no environments, no approval gates. Build with git tags + CI.

### 11.7 Lifecycle / governance

**Not provided.** No lifecycle states, no RBAC on publish/retire.

### 11.8 Programmatic API

**Not provided** as a cross-resource API. `Backend.List` + `Get` are the skill-level API.

### 11.9 Caching & sync model

**Not provided.** The filesystem backend re-reads on every `List` / `Get`; `agentsmd` reloads files on every model call (`agentsmd.go:64-66`, `BeforeModelRewriteState` at `:103`). Caching, watchers and sync intervals are yours.

### ⭐ Required — light usage example

Eino has no Resource Manager; this is what you'd build on the `Backend` seam:

```go
type gcsTenantBackend struct{ bucket string; cli *storage.Client }
func (b *gcsTenantBackend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    tenant, _ := adk.GetSessionValue(ctx, "tenantId")
    it := b.cli.Bucket(b.bucket).Objects(ctx, &storage.Query{Prefix: fmt.Sprintf("tenants/%s/", tenant)})
    var fms []skill.FrontMatter
    for o, err := it.Next(); err == nil; o, err = it.Next() {
        if !strings.HasSuffix(o.Name, "/SKILL.md") { continue }
        fm, meta := parseFrontmatter(b.fetch(ctx, o.Name))
        if meta["lifecycle"] != "active" { continue } // (2) only active skills for this tenant
        fms = append(fms, fm)
    }
    return fms, nil
}

// (1) git global default + bucket tenant overrides, tenant wins
gitGlobal, _ := newGitBackend(ctx, "git+https://github.com/dailymotion/predict-skills")
layered := &layeredBackend{tenant: &gcsTenantBackend{bucket: "predict-skills"}, global: gitGlobal}
skillMW, _ := skill.NewMiddleware(ctx, &skill.Config{Backend: layered, AgentHub: agentHub, ModelHub: modelHub})

// (2) promote draft → active for acme: your CI/admin UI rewrites `lifecycle: active` in the tenant object.
// (3) list active skills visible to tenant acme
active, _ := layered.List(context.WithValue(ctx, /* run ctx with */ "tenantId", "acme"))
```

This is **100% custom code**. Eino provides the seam; the platform is yours.

---

## 12. Observability: Usage, Cost, Tracing, Audit

### 12.1 Where tokens are surfaced

On each assistant message's `ResponseMeta.Usage` (`schema/message.go:448-456`, `:535-561`):

```go
type ResponseMeta struct {
    FinishReason string
    Usage        *TokenUsage
    LogProbs     *LogProbs
}

type TokenUsage struct {
    PromptTokens            int
    PromptTokenDetails      PromptTokenDetails      // .CachedTokens, .CacheWriteTokens (new v0.9.21)
    CompletionTokens        int
    TotalTokens             int
    CompletionTokensDetails CompletionTokensDetails // .ReasoningTokens
}
```

For `AgenticMessage`, usage is on `AgenticResponseMeta.TokenUsage` (`schema/agentic_message.go:85-87`). In callbacks, `model.CallbackOutput.TokenUsage` (`components/model/callback_extra.go:82-91`) carries the same breakdown. eino-ext adapters were updated to report cache-write tokens (OpenAI ACL, Claude, agentic Claude), thinking tokens (Claude) and streaming usage (Claude, DeepSeek).

### 12.2 Per-call / per-turn / per-session / per-tenant rollups

**Per-call**: yes. **Per-turn / per-session / per-tenant**: not provided; sum in a `callbacks.Handler.OnEnd` or in `TurnLoop.OnAgentEvents`.

### 12.3 USD cost computation

**Not provided.** Eino reports tokens; convert with your own price table. Langfuse (server-side) can compute cost from the usage the eino-ext handler exports.

### 12.4 Per-tenant / per-conversation cost

**Not provided first-party.** BYO via metadata-tagged tracing: the Langfuse v2 handler propagates `user`, `session`, tags and metadata to child observations (`eino-ext/callbacks/langfuse/v2/trace.go:150-212`), and the TLS handler has `SetSession(ctx, WithSessionID, WithUserID)`, so per-tenant cost can be rolled up in those backends if you map tenant → user/tag.

### 12.5 LLM / tool tracing

First-party exporters in eino-ext (separate Go modules):

- **Langfuse v1**: `callbacks/langfuse/` — batched ingestion API, mask function, sampling; v0.9-era fixes map `ResponseMeta` usage and preserve agent outcomes through retries.
- **Langfuse v2 (new)**: `callbacks/langfuse/v2/` — OTLP/HTTP to `/api/public/otel/v1/traces` targeting Langfuse v4's observation model; ADK agents, tools, retrievers get typed observations; batching, sampling, masking, size limits, graceful shutdown.
- **LangSmith**: `callbacks/langsmith/` — hierarchical runs with `dotted_order`.
- **APMPlus**: `callbacks/apmplus/` — OpenTelemetry spans + metrics.
- **CozeLoop**: ByteDance's tracing platform (now `AgenticMessage`-aware).
- **Volcengine TLS (new)**: `callbacks/tls/` — OTLP exporter to Volcengine's log/trace service, session-scoped tracing.

All register via `callbacks.AppendGlobalHandlers(handler)`; every component invocation is then traced. v0.9 separated the failover wrapper span from the inner model span (commit `28537fa`).

### 12.6 Audit logging (who / when / what)

**Not first-class.** Write a `callbacks.Handler` (or per-run `adk.WithCallbacks`, `adk/call_option.go:78`) emitting structured audit events to your sink. No tamper-evident logging.

### 12.7 Canonical "where do I read token counts" code path

```go
// schema/message.go:525  (Message field)
ResponseMeta *ResponseMeta `json:"response_meta,omitempty"`

// schema/message.go:448-456  (ResponseMeta)
type ResponseMeta struct {
    FinishReason string      `json:"finish_reason,omitempty"`
    Usage        *TokenUsage `json:"usage,omitempty"`
    LogProbs     *LogProbs   `json:"logprobs,omitempty"`
}

// schema/message.go:535-561  (TokenUsage + details)
type TokenUsage struct {
    PromptTokens            int                     `json:"prompt_tokens"`
    PromptTokenDetails      PromptTokenDetails      `json:"prompt_token_details"`
    CompletionTokens        int                     `json:"completion_tokens"`
    TotalTokens             int                     `json:"total_tokens"`
    CompletionTokensDetails CompletionTokensDetails `json:"completion_token_details"`
}
type PromptTokenDetails struct {
    CachedTokens     int `json:"cached_tokens"`
    CacheWriteTokens int `json:"cache_write_tokens"`
}
```

### ⭐ Required — light usage example

```go
// (1) Read tokens / compute USD for one completed run
iter := runner.Query(ctx, "...")
var in, out, cachedIn int
for {
    e, ok := iter.Next()
    if !ok { break }
    if e.Output == nil || e.Output.MessageOutput == nil { continue }
    msg, _ := e.Output.MessageOutput.GetMessage()
    if msg != nil && msg.ResponseMeta != nil && msg.ResponseMeta.Usage != nil {
        u := msg.ResponseMeta.Usage
        in, out, cachedIn = in+u.PromptTokens, out+u.CompletionTokens, cachedIn+u.PromptTokenDetails.CachedTokens
    }
}
costUSD := float64(in-cachedIn)*3e-6 + float64(cachedIn)*0.3e-6 + float64(out)*15e-6 // your price table
log.Printf("tokens_in=%d tokens_out=%d cost_usd=%.4f", in, out, costUSD)

// (2) Push per-tenant token usage to OTel via a callbacks handler
h := callbacks.NewHandlerBuilder().OnEndFn(func(ctx context.Context, info *callbacks.RunInfo, o callbacks.CallbackOutput) context.Context {
    if info.Component != components.ComponentOfChatModel { return ctx }
    cb := model.ConvCallbackOutput(o)
    if cb == nil || cb.TokenUsage == nil { return ctx }
    tenant, _ := adk.GetSessionValue(ctx, "tenantId")
    attrs := metric.WithAttributes(attribute.String("tenant", fmt.Sprint(tenant)), attribute.String("model", info.Name))
    inHist.Record(ctx, int64(cb.TokenUsage.PromptTokens), attrs)
    outHist.Record(ctx, int64(cb.TokenUsage.CompletionTokens), attrs)
    return ctx
}).Build()
callbacks.AppendGlobalHandlers(h)
```

---

## 13. Built-in Tools & Tool Authoring API

### 13.1 Built-in tools shipped in the box

**Core repo (`eino`)**: no standalone tool implementations, but middlewares bundle tools when you wire them in:

| Tool | Source | Purpose |
|---|---|---|
| `ls` / `read_file` / `write_file` / `edit_file` / `glob` / `grep` / `execute` | `filesystem` middleware (`adk/middlewares/filesystem/filesystem.go:40-46`) | Claude-Code-shaped file tools over a `filesystem.Backend`; `read_file` has offset/limit and, with `UseMultiModalRead`, reads images and PDFs (page ranges, max 20 pages/request) when the backend implements `MultiModalReader` (`adk/filesystem/backend.go:235-237`); `execute` via `Shell` or `StreamingShell` |
| `skill` | `skill` middleware | Load / fork skills |
| `tool_search` | `toolsearch` middleware | Keyword or `select:` search over deferred tools |
| `write_todos` / `task` | `deep` prebuilt | Todo list; dispatch to sub-agents |
| task create/get/list/update | `plantask` middleware | Structured plan/task tracking |
| `transfer_to_agent` / `exit` | ADK | Handoff (NOT RECOMMENDED) / exit |

**`eino-ext` tools** (each its own module under `components/tool/`): `mcp` (mark3labs SDK), `mcp/officialmcp` (official SDK), `duckduckgo`, `googlesearch`, `bingsearch`, `searxng`, `wikipedia`, `httprequest`, `commandline`, `browseruse` (chromedp), `sequentialthinking`.

**Provider-hosted server tools (new via `agentic*` adapters)**: `agenticopenai` exposes OpenAI Responses server tools — `web_search`, `file_search`, `code_interpreter`, `image_generation`, `shell` — and remote MCP; `agenticclaude` / `agenticgemini` expose their providers' server tools. These run on the vendor's side and come back as `server_tool_call` / `server_tool_result` content blocks.

**Quality**: `edit_file` does exact string replacement with replace-all; no multi-anchor edit. `read_file` returns line-numbered content and now reports out-of-range offsets (commit `ebd616c`). No `Monitor`-style background-process streaming on `main`. Search tools and MCP wrappers are thin. The catalog is broad by name and shallower by depth than Claude Agent SDK's bundled tools, but the filesystem + reduction + toolsearch combination encodes real agent-aware patterns.

### 13.2 Tool authoring API

Smallest tool (`components/tool/utils/invokable_func.go:46-53`):

```go
type GetWeatherInput struct {
    City string `json:"city" jsonschema:"description=City name"`
}
type GetWeatherOutput struct{ Temp int `json:"temp"` }

weatherTool, _ := utils.InferTool("get_weather", "Get current weather for a city",
    func(ctx context.Context, in *GetWeatherInput) (*GetWeatherOutput, error) {
        return &GetWeatherOutput{Temp: 22}, nil
    })
// JSON schema is generated from struct tags via eino-contrib/jsonschema
```

`utils.InferOptionableTool` for options-aware tools; `utils.NewTool(toolInfo, fn)` for manual schema; implement `tool.InvokableTool` / `EnhancedInvokableTool` for full control. Typed I/O: `InferTool` unmarshals LLM args into the struct via `sonic`; unmarshal errors propagate to the model as tool errors. No Pydantic-level validation (layer `go-playground/validator`). v0.9 adds `ToolAliases` to tolerate model-specific name / argument variants without changing the tool (`compose/tool_node.go:174-195`), and fixes `ToolInfo` JSON round-trip of empty params (commit `1bffbe6`).

### 13.3 Streaming tools

**Yes** — `StreamableTool` returns `*schema.StreamReader[string]` (`components/tool/interface.go:53-57`); `EnhancedStreamableTool` streams `*schema.ToolResult`. Chunks are forwarded as a streaming tool event to the consumer; the model sees the concatenated result. v0.9 preserves checkpoints when a tool stream is cancelled (commit `b9539ec`).

### 13.4 Tool sandboxing / permission model

- **Allow/deny lists**: BYO via `BeforeAgent` filtering `rc.Tools` (removes from both schema and dispatch, Q6.5).
- **`canUseTool`-style hook**: `WrapInvokableToolCall` returning an error (or an interrupt for human approval) denies a call.
- **Per-tool ACL**: BYO.
- **Execution sandbox**: none in core — tools run with your process's OS permissions. Backends in eino-ext:
  - **`adk/backend/agentkit/`** — sandboxed Python runtime (Volcengine AgentKit) executing filesystem operations via base64-encoded Python templates (`code_template.go`).
  - **`adk/backend/local/`** — local filesystem with multimodal read (images, PDFs rendered via `go-pdfium` WASM at 150 DPI by default; limits `defaultMaxImageSizeMB=10`, `defaultMaxPDFSizeMB=20`, `defaultMaxPagedPDFSizeMB=100`, `defaultMaxPDFPagesPerRequest=20`, `local.go:52-59`) and an optional `ValidateCommand` hook for shell commands (`local.go:242-243`).
  - **`acp/` client backend (new)** — routes file and terminal operations to the ACP client (the user's editor), which owns permission prompts.
  - Provider-hosted `code_interpreter` / `shell` via `agentic*` adapters run in the vendor's sandbox.
  - No E2B / Daytona / Modal integration.
- **Default posture**: **default-allow**. Every registered tool is visible and executable unless filtered; the skill middleware lists all skills the backend returns.

---

## 14. MCP (Model Context Protocol) Support

### 14.1 MCP client support

**Yes — first-class via two eino-ext adapters**:

- `components/tool/mcp/` — `mark3labs/mcp-go`.
- `components/tool/mcp/officialmcp/` — `modelcontextprotocol/go-sdk`. Substantially extended since the last refresh: `ServerName` + `ToolNameMapper` for multi-server name collisions, `ListToolsMode` pagination, `DescriptionPolicy` / `ResultPolicy` (truncate descriptions and results, include structured content / `_meta`), typed `Error` kinds, `ToolCallResultHandlerV2` (`officialmcp/mcp.go:36-190`).

Pattern: `mcp.GetTools(ctx, &mcp.Config{Cli: client, ToolNameList: []string{"search"}})` returns `[]tool.BaseTool` for `ToolsConfig.Tools` (or for `toolsearch.Config.DynamicTools` to defer large MCP catalogs).

Separately, the `agentic*` adapters support **provider-side remote MCP** (the model provider calls the MCP server; results come back as `mcp_tool_call` / `mcp_tool_result` / `mcp_list_tools_result` / approval content blocks, `schema/agentic_message.go:435-560`).

### 14.2 MCP server support

**Not provided.** Expose Eino tools via `mcp-go` / `go-sdk` server APIs yourself; there is no `eino.NewMCPServer`. (The ACP bridge exposes an agent to ACP clients, which is a different protocol.)

### 14.3 Transports

Whatever the SDK supports: `mcp-go` (stdio, SSE, Streamable HTTP); official `go-sdk` (stdio, SSE, Streamable HTTP). `officialmcp/session.TransportConfig` (`session/session.go:52-74`) selects by `Type` and accepts a custom `Factory func(ctx) (mcp.Transport, error)` (eino-ext commit `b9cfa8f`), which also covers in-memory transports.

### 14.4 In-process MCP

Possible via the SDKs' in-memory transports or a custom `Factory`; not a dedicated Eino API.

### 14.5 Auth / lifecycle

- `mcp.Config.CustomHeaders` / `Meta` (`components/tool/mcp/mcp.go:46-50`) for static headers and metadata.
- **New `officialmcp/session` package** (eino-ext commit `c9a5dc9`): `session.Connect(ctx, ServerConfig)` returns a `Session` that **transparently reconnects** on connection-level errors (not on protocol or tool errors), with concurrent-safe reconnect and a `StartupError` type (`session/session.go:78-190`). `TransportConfig.HTTPClient` lets you install a `RoundTripper` that resolves auth per request and survives reconnects.
- Version negotiation and health are delegated to the SDK.

Bonus: `components/prompt/mcp/` exposes MCP prompts as `prompt.ChatTemplate`.

---

## 15. Multi-model Routing & Fallback

### 15.1 Multi-provider support

First-party adapters in eino-ext `components/model/`:

| Adapter | Provider |
|---|---|
| `openai` | OpenAI Chat Completions (Azure via compatible endpoint) |
| `claude` | Anthropic direct, Bedrock, Vertex (now with service-account JSON); structured output, adaptive thinking, per-request timeout |
| `gemini` | Google Gemini (Vertex + AI Studio); request labels, logprobs |
| `ollama` | Ollama (local) |
| `deepseek`, `qwen`, `qianfan` | DeepSeek, Alibaba Qwen, Baidu Qianfan |
| `ark`, `arkbot` | ByteDance Volcengine Ark |
| `openrouter` | OpenRouter (LLM proxy) |
| `agenticopenai` / `agenticclaude` / `agenticgemini` / `agenticark` / `agenticdeepseek` / `agenticqwen` **(new)** | `AgenticModel` implementations (OpenAI Responses API, Claude, Gemini, Ark Responses, DeepSeek, Qwen) with server tools and cache control |

Any `model.BaseModel[M]` implementation plugs in. No LiteLLM-style gateway bundled.

### 15.2 Automatic fallback chain

**Yes — new in v0.9.** `ChatModelAgentConfig.ModelFailoverConfig` (`adk/chatmodel.go:409-414`; type at `adk/failover_chatmodel.go:128-167`):

```go
type ModelFailoverConfig[M MessageType] struct {
    MaxRetries       uint
    ShouldFailover   func(ctx context.Context, outputMessage M, outputErr error) bool
    GetFailoverModel func(ctx context.Context, failoverCtx *FailoverContext[M]) (
        failoverModel model.BaseModel[M], failoverModelInputMessages []M, failoverErr error)
}

agent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Model: claudeSonnet, // primary; later calls start from the last model that succeeded
    ModelRetryConfig: &adk.ModelRetryConfig{MaxRetries: 2},
    ModelFailoverConfig: &adk.ModelFailoverConfig[*schema.Message]{
        MaxRetries:     2,
        ShouldFailover: func(ctx context.Context, _ *schema.Message, err error) bool { return isOutageOr429(err) },
        GetFailoverModel: func(ctx context.Context, fc *adk.FailoverContext[*schema.Message]) (model.BaseModel[*schema.Message], []*schema.Message, error) {
            return []model.BaseModel[*schema.Message]{gpt4o, gemini}[fc.FailoverAttempt-1], nil, nil
        },
    },
})
```

Semantics: retry wraps each model attempt; failover sits outside retry and sees `*RetryExhaustedError`; partial streamed output is passed to `ShouldFailover`; failover stops on context cancellation and skips when the error carries interrupt info (commit `c2334bc`); `GetFailoverModel` can rewrite input for the backup model. `ModelRetryConfig.ShouldRetry` now returns a `RetryDecision` that can reject valid-but-bad output, modify the next input, append model options and override backoff (`adk/retry_chatmodel.go:115-256`). The summarization middleware has its own retry/failover for the summarizer model.

### 15.3 Mid-stream model switching

Not within one LLM call. At iteration boundaries: yes — failover keeps the last successful model for subsequent calls, `WrapModel` can swap models per call based on state, and the `skill` middleware's `setActiveModel` (`adk/middlewares/skill/skill.go:443`) switches model when an inline skill with `model:` is loaded. With `TurnLoop`, `PrepareAgent` can pick a different model for each turn. No central cost router ships. (Sub-agent model override: see Q9.8.)

---

## 16. Chat UI Layer

### 16.1 Generative UI components

**Not provided.** The v0.9 quickstart's Ch. 10 implements an "A2UI" subset (streaming UI components) as business-layer example code in eino-examples and states that A2UI "does not belong to the Eino framework itself".

### 16.2 Tool call rendering primitives

**Not provided.** ACP clients (e.g. editors) render tool calls from the `ToolCall` / `ToolCallUpdate` session updates produced by `eino-ext/acp`, which is the only shipped rendering-adjacent mapping.

### 16.3 Streaming chat hook

**Not provided.** No React / Vue hook. Your frontend connects to your HTTP layer.

### 16.4 BYO pattern

Serialize each `AgentEvent` to JSON over SSE / WebSocket and parse it into frontend state (Vercel AI SDK data-stream protocol is a common target; the eino message ID helps de-duplicate). For editor-style clients, expose the agent over ACP with `eino-ext/acp`.

---

## 17. Memory & Knowledge

### 17.1 Long-term memory / semantic recall

**Not built-in on `main`.** No `Memory` type or auto-recall. Combine `components/retriever` with a `BeforeAgent` / `BeforeModelRewriteState` middleware that injects recalled facts. (`alpha/10` has an "automemory" middleware with memory stores; not in the analysed commit.)

### 17.2 RAG / knowledge retrieval integration

**First-class retrieval primitives**:

- `retriever.Retriever` (`components/retriever/interface.go`), `indexer.Indexer` (`components/indexer/interface.go`; v0.9 adds a call-time index option, `components/indexer/option.go`), `embedding.Embedder`, `document.{Loader,Parser,Transformer}`
- eino-ext adapters: **Qdrant**, **Milvus** (v1, v2), **Redis**, **OpenSearch** (v2, v3), **Elasticsearch** (v7, v8, v9), **Volc VikingDB**, **Dify**, **Volc Knowledge**; S3 document loader gained custom endpoints

Wire via graph:

```go
g := compose.NewGraph[string, string]()
g.AddEmbeddingNode("emb", embedder)
g.AddRetrieverNode("ret", retriever, compose.WithStatePreHandler(...))
g.AddChatModelNode("llm", cm)
// edges: START -> emb -> ret -> llm -> END
```

Or wrap a retriever (or a whole graph — quickstart Ch. 8 "graph tool") as a tool.

### 17.3 Per-tenant memory scoping

**Not automatic.** `Retrieve(ctx, query, opts...)` receives ctx; pass tenant scope in ctx and have the adapter's sub-index / filter options respect it. The framework does not enforce it.

---

## 18. Safety & Policy

### 18.1 Input/output guardrails

**Not first-party.** PII redaction, prompt-injection detection and hallucination detection are BYO: write a `ChatModelAgentMiddleware` that runs a regex / classifier / LLM judge in `BeforeModelRewriteState` (input) and `AfterModelRewriteState` or `WrapModel` (output). `ModelRetryConfig.ShouldRetry` can now reject an output that fails a check and retry with modified input (`adk/retry_chatmodel.go:145-218`), which is a usable hook for output guardrails. `patchtoolcalls` repairs dangling tool calls (assistant tool calls without results) before model calls, a robustness rather than safety feature.

(Tool sandboxing and default posture are covered in Q13.4.)

---

## 19. Eval, Testing & CI Gates

### 19.1 Golden datasets / regression suites

**Not provided — BYO.** No `Dataset`, `Evaluator` or `EvalRun`. Use Go's `testing` package with recorded `model.BaseModel` mocks.

### 19.2 LLM-as-judge scoring

**Not provided — BYO.**

### 19.3 CI eval gates / pre-merge

**Not provided.** Run the agent against fixtures in CI and assert or judge-score outputs yourself.

### 19.4 Trace replay for skill iteration

**Not provided locally.** Langfuse / LangSmith / APMPlus / CozeLoop / TLS give remote trace viewing; no local step-through viewer.

---

## 20. Local Sandbox & Dev UX

### 20.1 Local agent runner

**Not first-party.** No `eino dev` CLI, playground or TUI. CloudWeGo ships IntelliJ-targeted DevOps plugins:

- [IDE plugin guide](https://www.cloudwego.io/docs/eino/core_modules/devops/ide_plugin_guide/)
- [Visual orchestration plugin](https://www.cloudwego.io/docs/eino/core_modules/devops/visual_orchestration_plugin_guide/)
- [Visual debug plugin](https://www.cloudwego.io/docs/eino/core_modules/devops/visual_debug_plugin_guide/)

The v0.9 quickstart's "ChatWithEino" example (eino-examples `quickstart/chatwitheino`) is the closest thing to a local runner: a console app per chapter and a local web page in Ch. 10. Exposing an agent over ACP (`eino-ext/acp`) also lets you drive it from an ACP-capable editor locally.

### 20.2 Trace inspection

Local: none built-in. Remote: Langfuse / LangSmith / APMPlus / CozeLoop / TLS dashboards (Langfuse can be self-hosted locally).

### 20.3 Tenant / org switching

**Not provided.**

### 20.4 Hot reload

Go code: standard tooling (`air`, `reflex`). SKILL.md: the filesystem skill backend re-reads on every `List` / `Get`; `agentsmd` re-reads AGENTS.md on every model call — edits apply without restart.

---

## Architectural diagram

```mermaid
flowchart TB
    subgraph host[Your Go process]
        api[Your HTTP/SSE layer or eino-ext/acp<br/>auth, tenant routing] --> tl
        tl[adk.TurnLoop<br/>per session: Push / Stop / preempt] --> runner
        api --> runner
        runner[adk.Runner<br/>Run / Resume / WithCancel] --> agent[adk.ChatModelAgent<br/>ReAct + retry + failover]
        runner -.not recommended.-> wagent[adk.WorkflowAgent<br/>Seq/Par/Loop, transfer]
        agent --> sub[adk.AgentTool / deep task tool<br/>agents-as-tools]
        agent --> graph[compose.Graph<br/>Init → ChatModel → ToolNode → AfterToolCalls]
        graph --> tools[components/tool<br/>Invokable / Streamable / Enhanced]
        graph --> model[components/model<br/>BaseModel of Message or AgenticMessage]
        graph --> retriever[components/retriever]

        subgraph hooks[Hooks & middleware]
            cb[callbacks.Handler<br/>OnStart/OnEnd/OnError/Stream]
            am[AgentMiddleware<br/>struct, deprecated]
            cmm[ChatModelAgentMiddleware<br/>Before/AfterAgent, state rewrite, Wrap*]
            tm[compose.ToolMiddleware<br/>+ ToolArgumentsHandler / aliases]
        end
        agent -.uses.-> cmm
        agent -.uses.-> am
        graph -.fires.-> cb
        graph -.uses.-> tm

        subgraph mw[Shipped middlewares]
            skill[skill/]
            amd[agentsmd/]
            fs[filesystem/]
            ts[toolsearch/]
            sum[summarization/]
            red[reduction/]
            pt[plantask/]
            ptc[patchtoolcalls/]
        end
        cmm -.implements.-> mw

        runner --> store[CheckPointStore + optional Deleter<br/>interface only — BYO]
        tl --> store
    end

    model -.HTTPS.-> openai[(OpenAI Chat / Responses)]
    model -.HTTPS.-> anthropic[(Anthropic / Bedrock / Vertex)]
    model -.HTTPS.-> gem[(Gemini)]
    model -.HTTPS.-> ark[(ByteDance Ark)]
    model -.local.-> ollama[(Ollama)]

    tools -.stdio/HTTP.-> mcp[(MCP servers<br/>mcp / officialmcp)]
    retriever -.network.-> vec[(Qdrant / Milvus /<br/>Redis / ES / OpenSearch)]

    cb -.eino-ext.-> lf[(Langfuse v1/v2)]
    cb -.eino-ext.-> ls[(LangSmith)]
    cb -.eino-ext.-> apm[(APMPlus / TLS / OTel)]

    store -.YOU build.-> pg[(Postgres / Redis / S3)]
```

---

## Appendix — Files worth reading first

1. **`adk/interface.go`** — `TypedAgent`, `TypedAgentEvent`, `TypedAgentInput`, `AgentAction`, `TypedResumableAgent`, `MessageType`. The ADK vocabulary, including the NOT RECOMMENDED advisories.
2. **`adk/chatmodel.go`** (lines 260–415, 1446–1533) — `TypedChatModelAgentConfig` with the canonical middleware execution-order comment (323–399), retry/failover fields, and how `Run` dispatches.
3. **`adk/react.go`** (lines 354–562) — the compiled `compose.Graph` that *is* the ReAct loop, including cancel-check and after-tool-calls nodes.
4. **`adk/runner.go`** — `Run` / `Query` / `Resume` / `ResumeWithParams`; where checkpoints fire on interrupt and cancel (lines 271–342).
5. **`adk/cancel.go`** — `WithCancel`, cancel modes, `CancelError`, interrupt absorption semantics.
6. **`adk/turn_loop.go`** — `TurnLoopConfig`, `Push` / `Stop` / preempt options, TurnLoop checkpoint format.
7. **`adk/handler.go`** — `TypedChatModelAgentMiddleware` (9 methods), `ToolContext`, `ChatModelAgentContext`, run-local values, `SendEvent`.
8. **`adk/failover_chatmodel.go`** + **`adk/retry_chatmodel.go`** — model failover and retry decisions.
9. **`adk/interrupt.go`** + **`internal/core/interrupt.go`** — interrupt model, addresses, `CheckPointStore` / `CheckPointDeleter`, serialization payload, back-compat shims.
10. **`adk/agent_tool.go`** — agents-as-tools and interrupt forwarding (the recommended sub-agent path).
11. **`adk/middlewares/skill/skill.go`**, **`adk/middlewares/agentsmd/agentsmd.go`**, **`adk/middlewares/dynamictool/toolsearch/toolsearch.go`**, **`adk/middlewares/reduction/reduction.go`** — the context-engineering kit.
12. **`compose/tool_node.go`** — `ToolsNode`, `ToolsNodeConfig` (aliases, `ToolArgumentsHandler`), parallel dispatch.
13. **`schema/message.go`** and **`schema/agentic_message.go`** — the two message models and `TokenUsage`.
14. **`eino-ext/acp/conv.go`** — the only shipped mapping from `AgentEvent` to a wire protocol.
