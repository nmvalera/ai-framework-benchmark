# Eino (Go) — Benchmark Study

> **Repo**: https://github.com/cloudwego/eino (core), https://github.com/cloudwego/eino-ext (extensions)
> **Commit studied (eino)**: `5e1305506c4fa89ef5d786035a947258e29a7593` (Apr 29 2026 — "fix(adk): preserve full ToolsNodeConfig fields on runtime tool updates")
> **Commit studied (eino-ext)**: `176d453b133a7b4c8c337450aba744d1e0ab38b7` (May 14 2026 — "feat(agentkit/local): add MultiModalRead for images and PDFs")
> **Branch**: `main` (both)
> **Framework paths**: `frameworks/eino/` (core), `frameworks/eino-ext/` (extensions)
> **Studied on**: 2026-05-16

## TL;DR

- **What is this stack architecturally**: Eino is a Go-native **library** (no daemon, no CLI, no HTTP server) split into two layers stacked in the same binary: (1) a low-level **graph / chain orchestration engine** (`compose/`) that compiles `Graph[I, O]` / `Chain[I, O]` into a `Runnable[I, O]` with Pregel-style super-steps and DAG modes, and (2) a higher-level **ADK** (`adk/`) sitting on top of the graph engine that ships `ChatModelAgent` (built-in ReAct loop), `WorkflowAgent` (Sequential/Parallel/Loop), `Runner`, `AsyncIterator[AgentEvent]`, plus prebuilt patterns (`deep`, `planexecute`, `supervisor`). The ADK is the "Claude-Code-shaped" layer; the graph engine is the LangGraph-shaped layer. Both live in your Go process.
- **Where the agent loop actually executes**: in-process, in your Go binary. There is **no subprocess, no vendor daemon, no hosted service**. `ChatModelAgent.Run` (`adk/chatmodel.go:948`) returns an `*AsyncIterator[*AgentEvent]`; the loop runs in a goroutine that drives a compiled `compose.Graph` internally (`adk/react.go:302`). `Runner.Query` and `Runner.Run` (`adk/runner.go:75,102`) are the public surface.
- **Strongest architectural choice for our use case**: **Interrupt + Resume + CheckPointStore with gob serialization is first-class and granular**. `ResumableAgent` (`adk/interface.go:267`), `Runner.ResumeWithParams` (`adk/runner.go:138`), and per-call address segments (`AppendAddressSegment`) let you suspend mid-tool-call, persist the full ADK state tree (including parallel sub-agent lanes) and resume **any specific component** by its address. The `CompositeInterrupt` model (`adk/interrupt.go:120`) cleanly propagates interrupts across nested workflow agents and agent-tools. This is the closest thing in the Go ecosystem to LangGraph's `Pregel.put_writes` durability and *better* than Claude Agent SDK / Mastra at fan-out resume.
- **Weakest / biggest gap**: **No CheckPointStore implementation ships with eino or eino-ext**. The interface is two methods (`Get`, `Set` on `[]byte`); the framework hands you the gob blob and you persist it. Combined with: no HTTP server, no built-in tenant model, no auth, no Resource Manager, no eval framework, no Chat UI, no per-tenant cost/budget — Eino gives you the runtime, you assemble the platform. This matches Ray's current Eino usage where Ray's `pkg/conversation/` owns persistence; for a greenfield Predict service it means 6–10× more host-side scaffolding than Mastra TS or LangGraph Platform.
- **Most surprising finding (bad — and the decision-relevant blocker for cross-team contribution)**: **English documentation is materially thinner than Chinese**. The [official docs landing](https://www.cloudwego.io/docs/eino/) has English pages for every concept, but many middleware-specific guides, examples, and v0.8+ changelogs are richer or only complete in `README.zh_CN.md` / Chinese-only docs sub-pages. Code comments in newer middlewares (`reduction/`, `summarization/`, `plantask/`) ship parallel `_chinese.go` prompt strings and a `LanguageChinese` global (`adk/config.go:28`) — the prompts and tool descriptions themselves are bilingual at runtime. **For Predict, this is a hard blocker for Product / non-engineer authors** writing SKILL.md or tool descriptions without an engineer's help, and a soft blocker for any docs-driven onboarding flow. The matrix flag holds.
- **Most surprising finding (good)**: **`adk/middlewares/skill/` is a real, working SKILL.md loader with fork / fork-with-context sub-agent modes**, parses YAML frontmatter (`name`, `description`, `context`, `agent`, `model`), supports custom skill-tool name (default `"skill"`), inline mode (system-prompt injection) vs. agent fork mode (spawn a sub-agent with this skill's content as instructions), and a pluggable `Backend` interface so you can load skills from filesystem (`NewBackendFromFilesystem`) or anything else. Co-located `dynamictool/toolsearch` middleware implements the regex-`tool_search` meta-tool that Claude Code exposes. These two middlewares **alone** put Eino architecturally ahead of every other Go SDK we benchmarked for skill / large-toolset workflows.
- **Recent activity (since the previous study)**: eino-ext landed a new **`adk/backend/local/`** local-filesystem backend (commit `176d453`, May 14 2026) that ships **`MultiModalRead` for images and PDFs** (renders PDF pages via `go-fitz` at configurable DPI, with bounded size and per-request page caps). This is the Go-ecosystem closest analog of Claude Code's multi-modal `Read` tool. Core eino's latest fix (`5e13055`, Apr 29 2026) preserves `ToolsNodeConfig` fields when middlewares rewrite tools at runtime — small but relevant for the dynamic-tools / `toolsearch` pattern.
- **Per-stack one-liners**:
  - **Sessions / persistence**: `runSession` is a runtime in-memory struct with `Values map[string]any` + `Events []*agentEventWrapper`; persistence is **interface-only via `CheckPointStore`** (`internal/core/interrupt.go:27`); BYO store implementation.
  - **Skills**: First-class via `adk/middlewares/skill/`. Filesystem backend ships; fork / fork-with-context / inline modes; pluggable `Backend` / `AgentHub` / `ModelHub`.
  - **Resource manager**: **Not provided — BYO**. `Backend` / `AgentHub` / `ModelHub` interfaces are the seam; you'd implement registry-side scoping yourself.
  - **Sub-agents**: Three first-class mechanisms: `SetSubAgents` (transfer-based, with `transfer_to_agent` tool), `NewAgentTool` (agents-as-tools), and `NewSequentialAgent` / `NewParallelAgent` / `NewLoopAgent`. Parallel uses a real `sync.WaitGroup` (`adk/workflow.go:471-516`).
  - **Multi-tenancy**: **No first-class tenant primitive**. `WithSessionValues(map[string]any)` (`adk/call_option.go:51`) gets you `tenantId` propagation but it's untyped; tool-argument injection requires writing a `ToolMiddleware` yourself. `_inject_tool_args`-style strip-then-inject is **not** built-in.
  - **Hooks / middleware**: Two parallel systems — old `AgentMiddleware` (struct, deprecated for new code) and `ChatModelAgentMiddleware` (interface, 7 methods incl. `BeforeAgent`, `BeforeModelRewriteState`, `AfterModelRewriteState`, `Wrap{Invokable,Streamable,EnhancedInvokable,EnhancedStreamable}ToolCall`, `WrapModel`). Plus `compose.ToolMiddleware` at the graph layer. Three-tier composability with documented ordering (`adk/chatmodel.go:250-303`).
  - **API**: Library-only. **No HTTP server, no SSE protocol, no resume endpoint**. The `AsyncIterator[*AgentEvent]` is in-process Go-channel-based.
  - **Observability**: `callbacks.Handler` framework + `RunInfo`. Eino-ext ships **Langfuse**, **LangSmith**, **APMPlus** (OTel) handlers as separate Go modules. Token counts on `schema.Message.ResponseMeta.Usage`. **No USD cost computation, no per-tenant rollup.**
- **Production-readiness verdict for multi-tenant server-side deployment**: **High runtime maturity, low platform maturity**. Eino's runtime (graph + ADK + checkpoint) is well-tested, used at ByteDance scale, and the v0.8 ADK middlewares are clean. But everything *around* the runtime — HTTP, auth, tenancy, persistence backend, resource registry, eval, dev sandbox — is yours to build. **Verdict**: defensible choice if Predict already has the platform layers (Ray does), risky greenfield choice if you're starting from zero and need to ship in <2 quarters. Plus the EN/ZH documentation imbalance is a real cross-team contribution blocker.

---

## 0. Architectural Overview & Deployment Model

### Deployment diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  Your Go process (e.g. Predict long-running-agent binary)                 │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  YOUR HTTP / gRPC layer  (gin, hertz, fiber, gorilla/mux, ...)   │  │
│  │  YOUR auth (Okta JWT, ...)  YOUR tenant routing                  │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  adk.Runner  (adk/runner.go:32)                                  │  │
│  │    ├─ runner.Run / runner.Query / runner.Resume                  │  │
│  │    ├─ returns *AsyncIterator[*AgentEvent]                        │  │
│  │    └─ owns CheckPointStore (BYO)                                 │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  adk.ChatModelAgent (ReAct)  +  adk.WorkflowAgent (Seq/Par/Loop) │  │
│  │  adk.AgentTool (agents-as-tools)                                 │  │
│  │  prebuilt/{deep,supervisor,planexecute}                          │  │
│  │  middlewares/{filesystem,skill,toolsearch,summarization,...}     │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │ delegates to                           │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  compose.Graph[I, O] / compose.Chain[I, O]                       │  │
│  │   ├─ AddChatModelNode / AddToolsNode / AddRetrieverNode / ...    │  │
│  │   ├─ Pregel + DAG run modes                                      │  │
│  │   └─ checkpoint serializer (gob default)                         │  │
│  └────────┬───────────────────┬───────────────────────────┬─────────┘  │
│           │                   │                           │            │
│  ┌────────▼─────────┐ ┌───────▼────────┐  ┌───────────────▼─────────┐  │
│  │ components/model │ │ components/tool│  │ components/{retriever,  │  │
│  │ (eino-ext: ark,  │ │ (eino-ext: mcp,│  │ indexer,embedding,      │  │
│  │  openai, claude, │ │ duckduckgo,    │  │ document, prompt}       │  │
│  │  gemini, ollama, │ │ commandline,   │  │ (eino-ext: qdrant,      │  │
│  │  deepseek, ...)  │ │ httprequest,   │  │ milvus, redis, es,      │  │
│  │                  │ │ wikipedia,...) │  │ opensearch, ...)        │  │
│  └────────┬─────────┘ └────────────────┘  └─────────────────────────┘  │
│           │                                                            │
└───────────┼────────────────────────────────────────────────────────────┘
            │ HTTPS
   ┌────────▼─────────┐
   │ LLM Providers    │  Anthropic / OpenAI / Vertex / Bedrock / Ark (ByteDance) / Ollama (local)
   └──────────────────┘

   YOUR persistent stores (NOT shipped):
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  CheckPointStore │  │  Tenant DB       │  │  Eval / Trace    │
   │  (Postgres / S3 /│  │  Auth / RBAC     │  │  store (Langfuse,│
   │  Redis - BYO)    │  │  (BYO)           │  │  LangSmith - via │
   └──────────────────┘  └──────────────────┘  │  eino-ext)       │
                                               └──────────────────┘
```

### 0.1 What is this stack?

A **Go library + ecosystem of adapters**. Two Go modules:
- `github.com/cloudwego/eino` — graph runtime, schema, ADK, callbacks interface, in-tree middlewares
- `github.com/cloudwego/eino-ext` — provider adapters (chat models, tools, retrievers, indexers), tracing exporters (Langfuse, LangSmith, APMPlus), each as its own Go module (so you import only what you need)

No daemon, no CLI subcommand exposes "run agent server". Everything is `import` + call.

### 0.2 Where does the agent loop actually execute?

**In your Go process, in a goroutine spawned by `ChatModelAgent.Run`** (`adk/chatmodel.go:948-995`):

```go
// adk/chatmodel.go:948
func (a *ChatModelAgent) Run(ctx context.Context, input *AgentInput, opts ...AgentRunOption) *AsyncIterator[*AgentEvent] {
    iterator, generator := NewAsyncIteratorPair[*AgentEvent]()
    ctx, run, bc, err := a.getRunFunc(ctx)
    // ...
    go func() {
        defer func() {
            panicErr := recover()
            // ...
            generator.Close()
        }()
        run(ctx, input, generator, newBridgeStore(), instruction, returnDirectly, co...)
    }()
    return iterator
}
```

The `runFunc` it delegates to is built by `buildReactRunFunc` (`adk/chatmodel.go:757`) which compiles a 3-node `compose.Graph` (`Init → ChatModel → ToolNode` with a branch back to `ChatModel`) and runs it via `compose.Runnable.Invoke` / `Runnable.Stream`. The graph runtime itself executes in your process, no subprocess.

For workflow agents, the loop is a literal `for i := range a.subAgents` over goroutine-spawned `agent.Run()` calls coordinated by `sync.WaitGroup` (`adk/workflow.go:471-516`).

### 0.3 Runtime dependencies

- **Go 1.25** (from `eino/go.mod:3`)
- Direct dependencies (`go.mod`):
  - `github.com/bytedance/sonic` — fast JSON (used heavily for tool-arg parsing)
  - `github.com/eino-contrib/jsonschema` — JSON Schema generation from Go structs
  - `github.com/getkin/kin-openapi` — OpenAPI schema helpers
  - `github.com/google/uuid`
  - `github.com/nikolalohinski/gonja` — Jinja2 templates for `prompt`
  - `github.com/slongfield/pyfmt` — Python f-string formatting
  - `github.com/stretchr/testify`
- **No bundled binaries**, no native libs, no required external process
- **Optional add-ons** (each is its own Go module under `eino-ext`):
  - LLM providers: OpenAI, Anthropic Claude, Gemini, Ark (ByteDance Volcengine), Qwen, DeepSeek, Ollama, OpenRouter, Qianfan
  - Vector stores: Qdrant, Milvus (v1 / v2), Redis, OpenSearch (v2 / v3), Elasticsearch (v7 / v8 / v9), Volc VikingDB, Dify
  - Tools: MCP (`mark3labs/mcp-go` or official `modelcontextprotocol/go-sdk`), DuckDuckGo, Wikipedia, Google Search, Bing Search, SearxNG, BrowserUse, CommandLine, HTTPRequest, SequentialThinking
  - Tracing: Langfuse, LangSmith, APMPlus (OTel), CozeLoop

### 0.4 Recommended deployment topology

There is no vendor-recommended topology document — this is a library, not a platform. The CloudWeGo docs implicitly assume "one-process-many-tenants" with horizontal Pod scaling and BYO ingress; the multi-tenancy guidance in the official docs is minimal.

Inside Dailymotion's Ray service (this repo's `pkg/eino/`, `src/ray/targeting/`), Eino runs **embedded in a single Go process per pod**, behind `gorilla/mux`, with persistence in our own Postgres via `pkg/conversation/`. Multiple Ray pods serve the same conversation pool with shared Postgres state. This works; it's the de-facto recommended pattern.

### 0.5 Cold-start cost & instance footprint

- **Startup latency**: negligible (it's a Go binary; `Runner` construction is just struct allocation — `adk/runner.go:63-69`). No model warm-up, no checkpoint hydration, no plugin loading.
- **RAM baseline**: depends entirely on your binary, but the Eino runtime itself is small (the `eino` package is ~12k LOC of Go code excluding tests). Per-session memory is dominated by `runSession.Events` (`adk/runctx.go:30-37`) which accumulates `agentEventWrapper` for every event during a run.
- **Disk baseline**: zero (no on-disk cache, no JSONL persistence, no skill cache unless you build one).

Compared with Claude Agent SDK Python (issue #333: 20–30 s startup), Eino has a **massive cold-start advantage** for serverless / horizontally-scaled deployments.

### 0.6 Vendor lock-in

| Axis | Score | Notes |
|---|---|---|
| LLM provider | **Low** | All providers behind `model.BaseChatModel` / `model.ToolCallingChatModel` interfaces (`components/model/interface.go:53-91`). Adapters in eino-ext for 11+ providers; trivial to add your own. |
| Hosting platform | **None** | Library only. Deploy wherever Go runs. |
| Eval platform | **None** | Eino does not ship any eval framework; you BYO. |
| Tracing platform | **Low** | OTel via APMPlus, or first-party Langfuse / LangSmith / CozeLoop. You can write your own `callbacks.Handler`. |
| Persistence | **None** | `CheckPointStore` is two methods on `[]byte`. |

Cloud-vendor lock-in: zero. Conceptually the closest equivalent of a vendor in Eino is **CloudWeGo / ByteDance** — they own the project and their internal use case (Volcengine Ark, APMPlus) drives the roadmap, so non-Chinese language coverage trails Chinese.

### 0.7 Framework weight / footprint

**Medium-heavy library; lean platform**:
- 12k+ LOC across `compose/`, `adk/`, `schema/`, `callbacks/`, `components/`
- ADK alone is ~40 files in `adk/` plus 7 middlewares + 3 prebuilts
- *But* zero platform code (no HTTP server, no UI, no eval, no marketplace)

Compared to LangGraph (which ships the OSS runtime in `libs/langgraph` and a separate closed-source `langgraph_api` for the platform), Eino is closer to "OSS runtime, no platform at all." Compared to Mastra TS (heavy framework with built-in storage, dev UI, plugin system), Eino is the opposite philosophy: rich runtime primitives, you assemble the application.

### 0.8 Documentation depth & cross-team contributor accessibility

**Official docs language(s)**: English + Simplified Chinese. The English landing page exists for every section, but:

- The Chinese pages frequently include longer code examples, more middleware-specific guidance, and faster-updated v0.8 ADK content (release notes for v0.7 and v0.8 are in `eino/llms.txt` as links to `cloudwego.io/docs/eino/release_notes_and_migration/*`; the English versions are short).
- Source-code-level docs are bilingual: many middlewares ship parallel `*_chinese.go` prompt files (e.g. `adk/middlewares/skill/prompt.go` has `systemPromptChinese`; `summarization/prompt.go`; `plantask/`). Tool descriptions are bilingual via `internal.SelectPrompt` (`adk/middlewares/filesystem/prompt.go:36-58`):

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
- Runtime language is selectable via `adk.SetLanguage(adk.LanguageChinese)` (`adk/config.go:33`), driving which version of internal prompts ships to the LLM.

**Can a non-engineer (Product / Data) author content without engineering hand-holding?**

- **No, not easily**. SKILL.md authoring (via `adk/middlewares/skill/`) is technically achievable by a non-engineer (markdown + YAML frontmatter), but **the Chinese-richer docs gap means**: when a Product author wants to understand "what does `context: fork_with_context` mean", the depth-first explanation only exists in the Chinese ADK middleware docs. The English page exists but is shorter. This is the matrix-flagged hard blocker.
- Tool authoring requires writing Go (`tool.BaseTool` + `InvokableTool`), which is engineering work regardless of language.

**For Predict**: Engineers can read both languages or use machine translation, so day-to-day development is unblocked. **Cross-team contribution from Product / Data is materially harder than Mastra TS (English-only, deep docs) or Claude Agent SDK (English-only).**

### 0.9 Documentation entry points

Required URLs (English first, Chinese in parens where richer):

- **Official docs landing**: <https://www.cloudwego.io/docs/eino/> · ZH: same URL serves both languages via the `cloudwego.io` language switcher (top-right `EN / 中文`)
- **Overview**: <https://www.cloudwego.io/docs/eino/overview/>
- **Graph or Agent — when to use which**: <https://www.cloudwego.io/docs/eino/overview/graph_or_agent/> ⭐ critical first read for new adopters
- **Quickstart — Simple LLM Application**: <https://www.cloudwego.io/docs/eino/quick_start/simple_llm_application/>
- **Quickstart — Agent with Tools**: <https://www.cloudwego.io/docs/eino/quick_start/agent_llm_with_tools/>
- **Eino Cookbook (recipes)**: <https://www.cloudwego.io/docs/eino/eino-cookbook/>
- **ADK overview**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/>
- **ADK Agent quickstart**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_quickstart/>
- **ADK Agent interface**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_interface/>
- **ChatModelAgent**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_implementation/chat_model/>
- **DeepAgents**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_implementation/deepagents/>
- **HITL (interrupt/resume)**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/agent_hitl/>
- **ChatModelAgent middleware index**: <https://www.cloudwego.io/docs/eino/core_modules/eino_adk/eino_adk_chatmodelagentmiddleware/> (skill, filesystem, summarization, plan-task, tool-search, tool-reduction, patch-toolcalls)
- **Checkpoint & interrupt/resume (compose layer)**: <https://www.cloudwego.io/docs/eino/core_modules/chain_and_graph_orchestration/checkpoint_interrupt/>
- **Callback system**: <https://www.cloudwego.io/docs/eino/core_modules/chain_and_graph_orchestration/callback_manual/>
- **API reference (godoc)**: <https://pkg.go.dev/github.com/cloudwego/eino> and <https://pkg.go.dev/github.com/cloudwego/eino-ext> — auto-generated, **English-only by definition** (Go doc comments)
- **Hosting / deployment / production guide**: **Not provided** — there is no production deployment page; Eino is library-only
- **Examples / demos repo**: <https://github.com/cloudwego/eino-examples>
- **Changelog**: <https://www.cloudwego.io/docs/eino/release_notes_and_migration/> (v0.1 through v0.8)
- **GitHub issues — core**: <https://github.com/cloudwego/eino/issues> (note: many issue threads are in Chinese)
- **GitHub issues — ext**: <https://github.com/cloudwego/eino-ext/issues>
- **Community**: CloudWeGo Discord / Lark (Feishu) — the main community runs on Lark, which is itself a Chinese-language platform. There is a Discord at <https://discord.gg/jceZSE7DsW> but activity is lower than Lark.

**Documentation language imbalance flag**: every section has English coverage; depth-of-coverage and example richness skew toward Chinese, especially for v0.7+ features. Non-Chinese readers should expect to read source code (the Go source is heavily commented in English) for the latest middleware patterns.

---

## 1. Agent Harness (Run Loop) & Message Taxonomy

### 1.1 Run loop entrypoint(s)

Three layered entrypoints, top-to-bottom:

1. **`adk.Runner`** — the public-facing entrypoint for an end-user-driven session:

   ```go
   // adk/runner.go:32-99
   type Runner struct {
       a               Agent
       enableStreaming bool
       store           CheckPointStore  // BYO; nil = no checkpointing
   }

   func (r *Runner) Run(ctx context.Context, messages []Message,
       opts ...AgentRunOption) *AsyncIterator[*AgentEvent]

   func (r *Runner) Query(ctx context.Context,
       query string, opts ...AgentRunOption) *AsyncIterator[*AgentEvent]

   func (r *Runner) Resume(ctx context.Context, checkPointID string,
       opts ...AgentRunOption) (*AsyncIterator[*AgentEvent], error)

   func (r *Runner) ResumeWithParams(ctx context.Context, checkPointID string,
       params *ResumeParams, opts ...AgentRunOption) (*AsyncIterator[*AgentEvent], error)
   ```

2. **`Agent.Run` interface** — what every agent implementation (chat model, workflow, custom) must satisfy:

   ```go
   // adk/interface.go:247-258
   type Agent interface {
       Name(ctx context.Context) string
       Description(ctx context.Context) string

       // Run runs the agent.
       // The returned AgentEvent within the AsyncIterator must be safe to modify.
       Run(ctx context.Context, input *AgentInput, options ...AgentRunOption) *AsyncIterator[*AgentEvent]
   }
   ```

3. **`compose.Runnable[I, O]`** — the underlying graph engine's run interface (what `ChatModelAgent` internally compiles to):

   ```go
   // compose/runnable.go:32-37
   type Runnable[I, O any] interface {
       Invoke(ctx context.Context, input I, opts ...Option) (output O, err error)
       Stream(ctx context.Context, input I, opts ...Option) (output *schema.StreamReader[O], err error)
       Collect(ctx context.Context, input *schema.StreamReader[I], opts ...Option) (output O, err error)
       Transform(ctx context.Context, input *schema.StreamReader[I], opts ...Option) (output *schema.StreamReader[O], err error)
   }
   ```

The "agent harness" for our purposes is `Runner` + `ChatModelAgent`; the Runnable layer is what you'd hand-build with `compose.NewGraph` if you wanted full control.

### 1.2 Per-iteration behavior

`ChatModelAgent` compiles a `compose.Graph[*reactInput, Message]` with three nodes: `Init`, `ChatModel`, `ToolNode`. The loop trip is:

```
START → Init → ChatModel → (branch on tool calls?)
                              ├─ yes → ToolNode → (branch on returnDirectly?)
                              │            ├─ yes → END
                              │            └─ no  → ChatModel (loop)
                              └─ no  → END
```

See `adk/react.go:302-437` (`newReact`). Each trip:

1. `genModelInput` (`adk/chatmodel.go:128-154`) merges instruction (system prompt) + input messages, optionally formatting f-string placeholders against `SessionValues`.
2. `modelPreHandle` decrements `RemainingIterations` (default max 20, configurable via `MaxIterations`); errors with `ErrExceedMaxIterations` if exhausted (`adk/react.go:326-332`).
3. Wrapped `ChatModel.Generate` / `Stream` is called. Wrapper chain: retry → event-sender → user `WrapModel` middlewares → callback injector → raw model.
4. Branch checks `chunk.ToolCalls` length — if 0, route to END.
5. `toolPreHandle` parses tool-call IDs, sets `ReturnDirectlyToolCallID` for tools marked return-directly (`adk/react.go:336-353`).
6. `ToolNode` (`compose/tool_node.go:200+`) dispatches calls — **parallel by default** (`ExecuteSequentially: false`), spawning a goroutine per call.
7. Branch on `ReturnDirectlyToolCallID` — if set, route to END via `ToolNodeToEndConverter`; otherwise feed results back to `ChatModel`.

Tool dispatch + result handling is one `compose.ToolsNode` step per super-step; per-call middleware order is precisely documented at `adk/chatmodel.go:283-291`.

### 1.3 ReAct loop

**Built-in.** `ChatModelAgent` ships ReAct as the default loop. You configure it via `ChatModelAgentConfig` (`adk/chatmodel.go:195-311`) — no graph-building required.

Legacy ReAct also exists at `flow/agent/react/react.go:284` (`react.NewAgent`) for backward compatibility with pre-ADK code; new code should use `adk.NewChatModelAgent`.

If you don't want ReAct, you bypass `ChatModelAgent` entirely and build your own `compose.Graph[I, O]` or implement the `Agent` interface yourself.

### 1.4 Tool dispatch + result handling

Handled by `compose.ToolsNode` (`compose/tool_node.go:63-72`):

```go
// compose/tool_node.go:63-72
type ToolsNode struct {
    tuple                             *toolsTuple
    unknownToolHandler                func(ctx context.Context, name, input string) (string, error)
    executeSequentially               bool
    toolArgumentsHandler              func(ctx context.Context, name, input string) (string, error)
    toolCallMiddlewares               []InvokableToolMiddleware
    streamToolCallMiddlewares         []StreamableToolMiddleware
    enhancedToolCallMiddlewares       []EnhancedInvokableToolMiddleware
    enhancedStreamToolCallMiddlewares []EnhancedStreamableToolMiddleware
}
```

The node receives an `*schema.Message` (assistant message with `ToolCalls`), dispatches each call to the matching tool (looked up by `ToolCalls[i].Function.Name`), and returns `[]*schema.Message` (one tool message per call, ordered by input order). Results are matched back to LLM expectations via `ToolMessage.ToolCallID == ToolCall.ID`. The framework handles JSON decoding/encoding when using `utils.InferTool` / `utils.NewTool`.

`UnknownToolsHandler` (`compose/tool_node.go:159-169`) is a graceful-degradation hook for LLM hallucinations of non-existent tool names.

### 1.5 Explicit turn concept

**No first-class "Turn" type.** A turn boundary is implicit — defined by the loop branch from `ChatModel` to either `ToolNode` or `END`. If a tool is `returnDirectly`, the turn ends after that tool's result; otherwise the loop continues until the model emits no tool calls.

The closest thing to a turn-event is the `AgentEvent` (`adk/interface.go:223-239`), which is the smallest unit emitted from the iterator.

### 1.6 Event emission mechanism (in-process)

**`*AsyncIterator[*AgentEvent]` backed by an unbounded Go channel**:

```go
// adk/utils.go:31-56
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

func NewAsyncIteratorPair[T any]() (*AsyncIterator[T], *AsyncGenerator[T]) {
    ch := internal.NewUnboundedChan[T]()
    return &AsyncIterator[T]{ch}, &AsyncGenerator[T]{ch}
}
```

Consumer side:

```go
iter := runner.Query(ctx, "hello")
for {
    event, ok := iter.Next()
    if !ok { break }   // generator was closed
    if event.Err != nil { /* handle error */ }
    // event.Output, event.Action, event.AgentName, event.RunPath
}
```

Network-side streaming is **not provided** — see Q6.

### 1.7 Message layers

Eino has **three distinct vocabularies**:

1. **Wire / LLM provider** — `*schema.Message` (`schema/message.go:653-687`). The canonical OpenAI-shaped message with `Role`, `Content`, `MultiContent` / `UserInputMultiContent` / `AssistantGenMultiContent`, `ToolCalls`, `ToolCallID`, `ResponseMeta`. This is what every chat model adapter produces and consumes. Compatible with all major providers via the adapter normalization.
2. **Graph layer** — `*schema.StreamReader[*schema.Message]` (or `[]*schema.Message` for tool node outputs). Chunks for streaming generation; reducer in `schema/message.go` concatenates them.
3. **ADK layer** — `*AgentEvent` (`adk/interface.go:223-239`), which wraps a `*MessageVariant` (`adk/interface.go:38-47`) that itself wraps `*schema.Message` or `*schema.StreamReader[*schema.Message]`. The ADK adds `AgentName`, `RunPath []RunStep`, `Action`, and `Err`.

Conversion path:

```
LLM HTTP response (provider-specific JSON)
        ↓ (eino-ext adapter)
*schema.Message (or *schema.StreamReader[*schema.Message] for streaming)
        ↓ (graph reducer for streaming; pass-through for non-streaming)
ToolsNode produces []*schema.Message (one per tool call)
        ↓
ChatModelAgent wraps last assistant message into a MessageVariant + AgentEvent
        ↓
generator.Send(event)  →  AsyncIterator.Next()  →  YOUR CODE
```

### 1.8 Concrete message types

| Type | File | One-line purpose |
|---|---|---|
| `schema.Message` | `schema/message.go:653` | Canonical chat message (role, content, tool calls, multimodal parts, response meta) |
| `schema.RoleType` | `schema/message.go:99` | `assistant` / `user` / `system` / `tool` |
| `schema.ToolCall` | `schema/message.go:123` | One LLM-generated tool invocation (id, type, function) |
| `schema.FunctionCall` | `schema/message.go:114` | `{Name, Arguments string (JSON)}` inside a ToolCall |
| `schema.ChatMessagePart` | `schema/message.go:~257` | Deprecated multi-content part type |
| `schema.MessageInputPart` | `schema/message.go:199` | User multimodal input part (text/image/audio/video/file) |
| `schema.MessageOutputPart` | `schema/message.go:257` | Assistant multimodal output part |
| `schema.MessageOutputReasoning` | `schema/message.go:238` | Reasoning trace from o1/Claude/Gemini |
| `schema.ResponseMeta` | `schema/message.go:603` | `{FinishReason, Usage, LogProbs}` |
| `schema.TokenUsage` | `schema/message.go:690` | `PromptTokens` / `CompletionTokens` / `TotalTokens` + caching/reasoning breakdowns |
| `schema.ToolInfo` | `schema/tool.go` | Tool descriptor (name, description, params schema) sent to the LLM |
| `schema.ToolResult` | `schema/tool.go` | Multimodal tool result used by `EnhancedInvokableTool` |
| `schema.ToolArgument` | `schema/tool.go` | Multimodal tool argument used by `EnhancedInvokableTool` |
| `schema.StreamReader[T]` | `schema/stream.go` | Pull-based stream of T chunks |
| `adk.Message` | `adk/interface.go:35` | Type alias for `*schema.Message` |
| `adk.MessageStream` | `adk/interface.go:36` | Type alias for `*schema.StreamReader[*schema.Message]` |
| `adk.MessageVariant` | `adk/interface.go:38` | Wrapper around message OR stream with `Role` + `ToolName` metadata |
| `adk.AgentEvent` | `adk/interface.go:223` | Outermost event in the iterator (`AgentName`, `RunPath`, `Output`, `Action`, `Err`) |
| `adk.AgentInput` | `adk/interface.go:241` | `{Messages []Message, EnableStreaming bool}` — input to `Agent.Run` |
| `adk.AgentOutput` | `adk/interface.go:141` | `{MessageOutput *MessageVariant, CustomizedOutput any}` |
| `adk.AgentAction` | `adk/interface.go:168` | `{Exit, Interrupted, TransferToAgent, BreakLoop, CustomizedAction}` |
| `adk.RunStep` | `adk/interface.go:182` | One agent in the `RunPath` (name only; opaque to user) |
| `adk.InterruptInfo` | `adk/interrupt.go:48` | `{Data, InterruptContexts []*InterruptCtx}` carried in `AgentAction.Interrupted` |
| `adk.InterruptCtx` | `adk/interrupt.go:168` (= `core.InterruptCtx`) | User-facing view of one interrupted component |
| `adk.AgentCallbackInput` | `adk/callback.go:29` | OnStart payload (`Input *AgentInput` or `ResumeInfo *ResumeInfo`) |
| `adk.AgentCallbackOutput` | `adk/callback.go:41` | OnEnd payload (`Events *AsyncIterator[*AgentEvent]`) |
| `adk.HistoryEntry` | `adk/flow.go:34` | `{IsUserInput, AgentName, Message}` — used by history rewriters |
| `adk.ChatModelAgentState` | `adk/chatmodel.go:158` | State carried into `Before/AfterModelRewriteState` middleware hooks |
| `adk.ChatModelAgentContext` | `adk/handler.go:66` | Mutable runtime config (Instruction / Tools / ReturnDirectly) in `BeforeAgent` |
| `adk.WorkflowInterruptInfo` | `adk/workflow.go:161` | Workflow-level interrupt payload (sequential index, loop count, parallel-branch dict) |

### 1.9 Messages vs. events

**Two separate taxonomies, surfaced through one iterator.** The single `*AsyncIterator[*AgentEvent]` is the user-facing channel; each `AgentEvent` may carry:
- a *message-event* via `event.Output.MessageOutput` (a wrapped `*schema.Message`)
- an *action-event* via `event.Action` (Exit / TransferToAgent / Interrupted / BreakLoop / CustomizedAction)
- an *error-event* via `event.Err`

Hook / callback events are a **separate** subsystem (`callbacks.Handler`) and *not* multiplexed onto the agent event stream.

### 1.10 Event categories

| Category | Surfaces via | Notes |
|---|---|---|
| Stream events (per-token) | inside `MessageVariant.MessageStream` (`*schema.StreamReader[*schema.Message]`) | One `AgentEvent` per *assistant message*; the message body is a stream you iterate |
| Message events | `AgentEvent.Output.MessageOutput` | One per finished assistant/tool message |
| Turn / iteration events | implicit (one ChatModel→ToolNode trip = one iteration; max controlled by `MaxIterations`) | No explicit `TurnStart` / `TurnEnd` event type |
| Tool events | `AgentEvent` with `MessageOutput.Role = schema.Tool` | Emitted via internal `eventSenderToolHandler` (`adk/chatmodel.go:365-373`) |
| Session lifecycle | **Not in the agent stream** — use `callbacks.Handler.OnStart` / `OnEnd` on `ComponentOfAgent` | `AgentCallbackInput` / `AgentCallbackOutput` |
| Hook events | `callbacks.CallbackTiming` (`TimingOnStart`, `TimingOnEnd`, `TimingOnError`, `TimingOnStartWithStreamInput`, `TimingOnEndWithStreamOutput`) | Separate event bus, not on `AgentEvent` |
| Sub-agent events | Same `AgentEvent` stream when `ToolsConfig.EmitInternalEvents: true` (`adk/chatmodel.go:111-122`) | RunPath disambiguates parent vs. child events |
| Interrupt events | `AgentEvent.Action.Interrupted != nil` | Saved to CheckPointStore before being sent to the consumer (`adk/runner.go:233-245`) |

### 1.11 Canonical type-definition file(s)

- Messages: `schema/message.go` (~2000 lines, source of truth)
- Tool info / arguments / results: `schema/tool.go` (~200 lines)
- Streams: `schema/stream.go`
- Agent events & interface: `adk/interface.go`
- Interrupt types: `adk/interrupt.go`
- Hook interface: `callbacks/interface.go`, `internal/callbacks/`

### 1.12 Live agentic event stream taxonomy

Sample frames the consumer receives (Go-side, not JSON — there is no wire format):

```go
// frame 1: streamed assistant message (token-by-token)
event := &AgentEvent{
    AgentName: "long-running agent-supervisor",
    RunPath:   []RunStep{{agentName: "long-running agent-supervisor"}},
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
    AgentName: "long-running agent-supervisor",
    RunPath:   []RunStep{{agentName: "long-running agent-supervisor"}},
    Output: &AgentOutput{
        MessageOutput: &MessageVariant{
            IsStreaming: false,
            Message: &schema.Message{
                Role:       schema.Tool,
                Content:    `{"topics":["fitness","travel"]}`,
                ToolCallID: "call_xyz123",
                ToolName:   "topicSearch",
            },
            Role:     schema.Tool,
            ToolName: "topicSearch",
        },
    },
}

// frame 3: transfer-to-agent action (mid-flight; sub-agent will then emit its own events)
event := &AgentEvent{
    AgentName: "long-running agent-supervisor",
    Action: &AgentAction{
        TransferToAgent: &TransferToAgentAction{DestAgentName: "audience-builder"},
    },
}

// frame 4: interrupt (HITL; saved to CheckPointStore first, then sent to consumer)
event := &AgentEvent{
    AgentName: "long-running agent-supervisor",
    Action: &AgentAction{
        Interrupted: &InterruptInfo{
            Data: "human approval required for tool 'audienceCreate'",
            InterruptContexts: []*InterruptCtx{ /* address chain */ },
        },
    },
}

// frame 5: exit (clean termination)
event := &AgentEvent{
    AgentName: "long-running agent-supervisor",
    Action:    &AgentAction{Exit: true},
}

// frame 6: error
event := &AgentEvent{
    AgentName: "long-running agent-supervisor",
    Err:       fmt.Errorf("model rate-limited"),
}
```

There is no `start` frame analogue to LangGraph's `metadata` frame — the first event on the stream is the first message or action the agent emits.

---

## 2. Agent Runtime (Multi-session Host)

### 2.1 Multi-session host architecture

**No first-party multi-session runtime ships.** Eino is library-only. "Runtime" in Eino vocabulary means the in-process `compose.Runnable` execution; multi-session hosting is your job.

The pattern Dailymotion uses in Ray:
- One Go process (one pod) hosts N concurrent agent sessions
- Per-request `Runner` instances (or a shared `Runner` with per-request `checkPointID`)
- `pkg/conversation/` owns persistence; the agent is constructed per request from the conversation state

Eino itself does not enforce or even know about "session" as a runtime concept — `runSession` (`adk/runctx.go:30-37`) is a *run-scoped* struct (one per `Runner.Run` call), not a persisted multi-call session.

### 2.2 Concurrent session isolation

Isolation is enforced **by context, not by registry**:
- `ctxWithNewRunCtx` (`adk/runctx.go:387-401`) seeds a fresh `runContext` with its own `runSession` on every `Runner.Run` call.
- The `runContext` lives in `context.Context` (`runCtxKey{}`); concurrent calls each get their own ctx tree.
- `runSession.valuesMtx`, `runSession.mtx` guard the maps inside (`adk/runctx.go:30-37`).
- Parallel sub-agents fork the context (`forkRunCtx`, `adk/runctx.go:328-358`) into a per-lane `runContext` with a `laneEvents` linked list — committed back to the parent via `joinRunCtxs` only after all lanes finish.

Risk: any *shared* state outside `runSession.Values` (e.g. a closure capturing a tenant-scoped map at agent construction time) is **not** isolated by the framework. If a tool implementation reaches into a singleton, you'll leak across sessions.

### 2.3 Horizontal scaling / multi-instance

Stateless. Pods scale horizontally trivially (it's a Go binary). For shared state across pods, **your `CheckPointStore` implementation is the seam**:
- If you point all pods at the same Postgres `CheckPointStore`, then any pod can resume any session.
- Leader election, locking, partition assignment — **not provided**. You'd need to layer optimistic concurrency / advisory locks on top of your store.

### 2.4 Background / async / scheduled tasks

**Not provided — BYO.** Eino has no cron, no webhook trigger system, no scheduled-job framework. Use Go's stdlib (`time.AfterFunc`, `time.Ticker`) or a job library (Asynq, Temporal, Cloud Tasks) in your host.

### 2.5 Worker pool / queue model

**Not provided — BYO.** The framework assumes short-lived calls into `Runner.Run` from your HTTP handler. Long-running background work is your responsibility (typical pattern: enqueue, then have a worker pool call `Runner.Run`).

---

## 3. Sessions & Persistence

### 3.1 Session / chat data model

There is no `Session` *type* per se. The closest things:

1. **`runSession` (run-scoped, not session-scoped)** — `adk/runctx.go:30-37`:

   ```go
   type runSession struct {
       Values    map[string]any
       valuesMtx *sync.Mutex

       Events     []*agentEventWrapper
       LaneEvents *laneEvents
       mtx        sync.Mutex
   }
   ```

   This is created per `Runner.Run` call and lives until the run ends (or is checkpointed mid-flight). It carries:
   - `Values` — k-v map (filled by `WithSessionValues` and `AddSessionValue` from inside agents)
   - `Events` — append-only log of `AgentEvent`s emitted on the main path
   - `LaneEvents` — linked list of in-flight events for parallel-fork lanes

2. **`runContext` (the context.Context-stored wrapper)** — `adk/runctx.go:220-225`:

   ```go
   type runContext struct {
       RootInput *AgentInput
       RunPath   []RunStep
       Session   *runSession
   }
   ```

3. **`serialization` (the persisted checkpoint payload)** — `adk/interrupt.go:190-197`:

   ```go
   type serialization struct {
       RunCtx              *runContext
       Info                *InterruptInfo  // deprecated, kept for back-compat
       EnableStreaming     bool
       InterruptID2Address map[string]Address
       InterruptID2State   map[string]core.InterruptState
   }
   ```

What you'd traditionally call a "session" (`tenant_id`, `user_id`, `created_at`, `model`, `summary`) is **not in the framework**. You build that around the framework, persist it in your DB, and re-construct the `Runner` + `Agent` from it per request.

### 3.2 What's stored on a session

- Messages (history): not stored directly on the run session — they live inside `State.Messages` (the `compose.Graph` per-run local state, `adk/react.go:40-53`) and are reconstructed from `runSession.Events` by `flowAgent.genAgentInput` (`adk/flow.go:258-311`).
- Tool call history: implicit in `Events` (each tool call is an event).
- Scratchpad files: none — see `filesystem.Backend` (`adk/filesystem/backend.go`) for an opt-in filesystem the `filesystem` middleware uses; not part of the session itself.
- Embedded memory: none.
- Attachments: messages can carry multimodal parts (`UserInputMultiContent`); no separate attachment store.
- Usage / cost rollup: not on the session; on each `schema.Message.ResponseMeta.Usage` only.

### 3.3 Granularity

- One conversation per session (per `Runner.Run` invocation that uses the same `checkPointID`).
- **No fork/branch model** (you cannot `session.fork()` LangGraph-style). The thread-of-execution is linear; only parallel sub-agents inside one run get lanes.
- A new `checkPointID` = a new session. You're responsible for the ID scheme.

### 3.4 Built-in persistence stores

**None. Interface-only.** The `CheckPointStore` interface (`internal/core/interrupt.go:27-30`) is:

```go
type CheckPointStore interface {
    Get(ctx context.Context, checkPointID string) ([]byte, bool, error)
    Set(ctx context.Context, checkPointID string, checkPoint []byte) error
}
```

The framework hands you raw `[]byte` (gob-serialized) and you decide where it lives. **eino-ext does not ship an implementation** — verified by `grep -rln "CheckPointStore" frameworks/eino-ext` (only docs/`SKILL.md` references, no Go implementation).

Possibilities you'd build (none are provided):
- Postgres (the typical Ray pattern — `bun` + a `checkpoints` table)
- Redis / Memcached
- S3 / GCS for cold storage
- BoltDB / SQLite for local dev
- In-memory (for tests; `bridgeStore` in `adk/interrupt.go:289-316` is the de-facto in-memory implementation but it's framework-internal)

### 3.5 Persistence timing

**Persistence fires on interrupt only**, not on every message or tool result.

The fire point in code:

```go
// adk/runner.go:189-247  Runner.handleIter
for {
    event, ok := aIter.Next()
    if !ok { break }
    if event.Action != nil && event.Action.internalInterrupted != nil {
        // ...
        if checkPointID != nil {
            // save checkpoint first before sending interrupt event,
            // so when end-user receives interrupt event, they can resume from this checkpoint
            err := r.saveCheckPoint(ctx, *checkPointID, &InterruptInfo{Data: legacyData}, interruptSignal)
            // ...
        }
    }
    gen.Send(event)
}
```

And the save itself (`adk/interrupt.go:263-285`):

```go
func (r *Runner) saveCheckPoint(ctx context.Context, key string, info *InterruptInfo, is *core.InterruptSignal) error {
    runCtx := getRunCtx(ctx)
    id2Addr, id2State := core.SignalToPersistenceMaps(is)
    buf := &bytes.Buffer{}
    err := gob.NewEncoder(buf).Encode(&serialization{
        RunCtx:              runCtx,
        Info:                info,
        InterruptID2Address: id2Addr,
        InterruptID2State:   id2State,
        EnableStreaming:     r.enableStreaming,
    })
    if err != nil { return fmt.Errorf("failed to encode checkpoint: %w", err) }
    return r.store.Set(ctx, key, buf.Bytes())
}
```

There is **no equivalent of LangGraph's per-task `put_writes`**: Eino does not durably commit after every super-step. A crash mid-tool-call (with no interrupt fired) loses everything since the last interrupt. If you want LangGraph-style durability, you'd have to manually emit `Interrupt()` events as durability checkpoints, which abuses the interrupt API.

Sync vs. async: synchronous only — `saveCheckPoint` is called inline before the interrupt event is forwarded to the user, so the user can rely on "I saw the interrupt → checkpoint is on disk".

### 3.6 Mid-run checkpointing (durable)

Mid-tool-call resume **is supported when you explicitly call `Interrupt` / `StatefulInterrupt` inside the tool** (`adk/interrupt.go:60-112`). After such a call:
- The interrupt signal propagates up through `CompositeInterrupt` for any wrapping workflow / agent-tool boundaries.
- `Runner.handleIter` catches it, saves the checkpoint, sends it to the user.
- Resume via `Runner.Resume` or `Runner.ResumeWithParams` re-enters the agent at the same `Address` and restores any saved state via `core.GetInterruptState` / `core.GetResumeContext`.

A crash *without* a deliberate interrupt = lost progress.

### 3.7 Session ID format

**You choose.** `checkPointID` is just a string passed to `CheckPointStore.Get` / `Set` (`internal/core/interrupt.go:27-30`). No format constraints, no tenant prefixing built in. If you want `tenant:user:conversation-uuid`, build it yourself.

The internal `bridgeCheckpointID = "adk_react_mock_key"` (`adk/interrupt.go:287`) is a sentinel for the internal "bridge" store used by `agentTool` boundaries; users never set it.

### 3.8 Pluggable store interface

The `CheckPointStore` interface (`internal/core/interrupt.go:27-30`, re-exported as `adk.CheckPointStore` and `compose.CheckPointStore`) is **the** integration point. You implement two methods on `[]byte`. There is no schema, no migration helper, no versioning hook.

Example in-memory implementation (the framework-internal `bridgeStore`, useful as a reference):

```go
// adk/interrupt.go:300-316
type bridgeStore struct {
    Data  []byte
    Valid bool
}

func (m *bridgeStore) Get(_ context.Context, _ string) ([]byte, bool, error) {
    if m.Valid {
        return m.Data, true, nil
    }
    return nil, false, nil
}

func (m *bridgeStore) Set(_ context.Context, _ string, checkPoint []byte) error {
    m.Data = checkPoint
    m.Valid = true
    return nil
}
```

### 3.9 Schema evolution / migration

**No general migration helper for user state.** The framework migrates *its own* internal state types across versions — for example `preprocessADKCheckpoint` (`adk/interrupt.go:247-261`) byte-patches v0.8.0–v0.8.3 gob names back to v0.7-compatible names, and `preprocessComposeCheckpoint` (`adk/chatmodel.go:1138-1165`) routes them through a compat decoder. There is also `compose.MigrateCheckpointState` (`compose/checkpoint.go:231-244`) which lets framework code apply a `migrate(state any) (any, bool, error)` to all nested states in a checkpoint tree.

But for **your** custom Go types stored in `runSession.Values` or `state.Extra`, the rules are:
- Types must implement `gob.GobEncoder` / `gob.GobDecoder` (or use the default reflection-based gob support).
- Register custom types with `schema.RegisterName[T]("a_unique_name")` (`adk/handler.go:340-356` enforces this with a useful error message at `SetRunLocalValue` time).
- **Removing or renaming fields breaks old checkpoints** unless you write a compat decoder yourself.

### 3.10 Export / replay

- **Export**: yes — `r.store.Get(ctx, checkPointID)` returns the gob blob. You can save it elsewhere or replay.
- **Replay**: yes — `Runner.Resume(ctx, checkPointID)` re-enters from the saved point. For *deterministic* replay (debugging mode), Eino does not ship a "replay from start with frozen RNG / frozen LLM responses" framework like LangSmith provides; you'd build it yourself by mocking the `model.BaseChatModel` against recorded outputs.

### 3.11 Cross-session memory

**Not provided.** No long-term memory / vector recall is bundled. You can compose `components/retriever` adapters yourself (eino-ext has Qdrant, Milvus, Redis, OpenSearch, ES, Volc VikingDB, Dify) as RAG nodes in a graph or as tool wrappers — see Q15.

---

## 4. Multi-tenancy & Arbitrary Context ⭐ THE KEY QUESTION

### 4.1 Full run-loop input struct

Inputs to `Runner.Run`:

```go
// adk/runner.go:75-99
func (r *Runner) Run(ctx context.Context, messages []Message,
    opts ...AgentRunOption) *AsyncIterator[*AgentEvent]
```

- `ctx` — Go `context.Context`. Carries everything you want available at every layer (your tenant ID, request ID, trace span). The agent framework piggybacks on this — `getRunCtx`, `getSession`, `core.GetCurrentAddress` all read from `context.Context`.
- `messages` — input messages.
- `opts ...AgentRunOption` — option fan-in. Common options (`adk/call_option.go`):

  ```go
  // adk/call_option.go:21-77
  type options struct {
      sharedParentSession  bool
      sessionValues        map[string]any   // ← typical place to stash tenant id, locale, today's date
      checkPointID         *string
      skipTransferMessages bool
      handlers             []callbacks.Handler
  }
  ```

  Plus impl-specific (`adk/chatmodel.go:65-71`):

  ```go
  type chatModelAgentRunOptions struct {
      chatModelOptions []model.Option
      toolOptions      []tool.Option
      agentToolOptions map[string][]AgentRunOption
      historyModifier  func(context.Context, []Message) []Message
  }
  ```

There is **no typed `Spec T` / `Context T` field** like LangGraph's `Runtime[ContextT]` — everything goes through `WithSessionValues(map[string]any)` or `context.Context`.

### 4.2 Context propagation into a tool call

Two parallel mechanisms:

1. **`context.Context`** — the simplest and recommended path. Everything you set via `context.WithValue` in your host code reaches `tool.InvokableRun(ctx, argumentsInJSON, opts...)`. Tools can read `getRunCtx(ctx)` (internal) or do their own context-key lookup.

2. **`tool.Option`** — when you need to pass tool-specific options through the harness. Set on `compose.WithToolsNodeOption(compose.WithToolOption(opts...))` (see `adk/chatmodel.go:1107`). Each tool can use `tool.GetImplSpecificOptions[T]` to extract its own typed config.

Sample call path: `Runner.Run` → `flowAgent.Run` → `ChatModelAgent.Run` → `compose.Runnable.Invoke` → `ToolsNode` super-step → `tool.InvokableRun(ctx, args, opts...)`. The ctx is the same one passed in (with added internal keys for address segments, run context, callbacks).

### 4.3 Tool call interface

`tool.InvokableTool` (`components/tool/interface.go:42-47`):

```go
type InvokableTool interface {
    BaseTool
    InvokableRun(ctx context.Context, argumentsInJSON string, opts ...Option) (string, error)
}
```

Note: `argumentsInJSON` is a raw JSON string — the framework does **not** parse it for you unless you use `utils.InferTool` / `utils.NewTool` which JSON-decode into a typed struct via `sonic`. Your tool body unmarshals; this is the seam where you'd inject server-side fields *before* unmarshalling.

For multimodal tools, `EnhancedInvokableTool` (`components/tool/interface.go:67-70`):

```go
type EnhancedInvokableTool interface {
    BaseTool
    InvokableRun(ctx context.Context, toolArgument *schema.ToolArgument, opts ...Option) (*schema.ToolResult, error)
}
```

### 4.4 Forcing tool arguments from the harness

**Not first-class. You build it yourself, two patterns**:

**Pattern A — `ToolsNodeConfig.ToolArgumentsHandler`** (`compose/tool_node.go:176-185`):

```go
ToolArgumentsHandler: func(ctx context.Context, name, arguments string) (string, error) {
    if name == "topicSearch" {
        var args map[string]any
        if err := sonic.UnmarshalString(arguments, &args); err != nil { return "", err }
        args["tenantId"] = ctx.Value("tenantId").(string)   // STRIP-AND-INJECT here
        b, _ := sonic.Marshal(args)
        return string(b), nil
    }
    return arguments, nil
},
```

This runs **once per tool call**, before the tool's `InvokableRun`. It's the right hook for the strip-and-inject pattern. *Caveat: it sees the raw JSON, so you can override any field the LLM tried to set.*

**Pattern B — `compose.ToolMiddleware.Invokable`** (per-tool middleware, more powerful):

```go
mw := compose.ToolMiddleware{
    Invokable: func(next compose.InvokableToolEndpoint) compose.InvokableToolEndpoint {
        return func(ctx context.Context, in *compose.ToolInput) (*compose.ToolOutput, error) {
            if in.Name == "topicSearch" {
                var args map[string]any
                _ = sonic.UnmarshalString(in.Arguments, &args)
                args["tenantId"] = ctx.Value("tenantId")
                b, _ := sonic.Marshal(args)
                in.Arguments = string(b)
            }
            return next(ctx, in)
        }
    },
}
// then: tc.ToolCallMiddlewares = append(tc.ToolCallMiddlewares, mw)
```

Or, via the ADK `ChatModelAgentMiddleware` interface, `WrapInvokableToolCall` (`adk/handler.go:151`):

```go
func (h *MyHandler) WrapInvokableToolCall(ctx context.Context, endpoint adk.InvokableToolCallEndpoint, tCtx *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tCtx.Name != "topicSearch" { return endpoint, nil }
    return func(ctx context.Context, argumentsInJSON string, opts ...tool.Option) (string, error) {
        var args map[string]any
        _ = sonic.UnmarshalString(argumentsInJSON, &args)
        args["tenantId"] = ctx.Value("tenantId")
        b, _ := sonic.Marshal(args)
        return endpoint(ctx, string(b), opts...)
    }, nil
}
```

**Honesty**: the LangGraph `InjectedToolArg` story (declared at tool definition time, stripped from LLM-visible schema, injected from `Runtime.context`) is **strictly cleaner** than Eino's approach. Eino requires you to write middleware and remember to omit the field from the tool's JSON schema yourself.

### 4.5 Filtering visible tools

**Yes — via `ChatModelAgentMiddleware.BeforeAgent`** (`adk/handler.go:117`), which gets a mutable `ChatModelAgentContext` with the `Tools []tool.BaseTool` slice you can replace:

```go
func (h *TenantFilter) BeforeAgent(ctx context.Context, runCtx *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
    tenantID := ctx.Value("tenantId").(string)
    var filtered []tool.BaseTool
    for _, t := range runCtx.Tools {
        info, _ := t.Info(ctx)
        if isToolAllowedForTenant(info.Name, tenantID) {
            filtered = append(filtered, t)
        }
    }
    runCtx.Tools = filtered
    return ctx, runCtx, nil
}
```

`BeforeAgent` is called **once per run** (not per turn), and the modified tool list is used both for the LLM-visible schema and for dispatch (`adk/chatmodel.go:294-303`).

For **per-turn** filtering (LangGraph's `prepareStep`-style), you wrap the chat model via `WrapModel` and apply `model.WithTools(filteredToolInfos)` per request — example in `adk/middlewares/dynamictool/toolsearch/toolsearch.go:90-115`:

```go
func (w *wrapper) Generate(ctx context.Context, input []*schema.Message, opts ...model.Option) (*schema.Message, error) {
    tools, err := removeTools(ctx, w.allTools, w.dynamicTools, input)
    if err != nil { return nil, fmt.Errorf("failed to load dynamic tools: %w", err) }
    return w.cm.Generate(ctx, input, append(opts, model.WithTools(tools))...)
}
```

### 4.6 Tenant scope on session

**Not a first-class field.** Tenancy lives in (a) `context.Context` (the recommended idiom), (b) `runSession.Values` via `WithSessionValues(map[string]any{"tenantId": "acme"})`. You can read it back inside any handler / tool via `adk.GetSessionValue(ctx, "tenantId")` or `ctx.Value(...)`.

No type safety, no validation, no "session.tenant_id" property.

### 4.7 Per-tool-call auth propagation

**Not built-in.** The caller's identity reaches the tool only because **you** put it on `context.Context`. There is no automatic Okta-token-pass-through or per-tool-call STS / impersonation.

If you want tools to execute under per-user permissions (e.g. BigQuery queries as the requester), you instrument it: hook in `BeforeAgent` to extract identity from ctx → set on the BQ client used by each tool's `InvokableRun`.

### 4.8 Resource scoping primitives

**Runtime filtering only.** Scopes (global / tenant / user) at registration are **not provided** — you can't say "register skill X as tenant=acme only at registry layer." You'd build that yourself by writing a custom `skill.Backend` that returns different `FrontMatter` lists per ctx tenant — see Q9.

### 4.9 Per-tenant rate limit + budget cap

**Not provided.** No USD budget enforcement, no per-tenant token ceiling. You can read token counts off `ResponseMeta.Usage` per assistant message and enforce yourself in a `callbacks.Handler.OnEnd` that aborts via `context.CancelFunc`.

---

### ⭐ Required — light usage example

Show how to: (1) pass tenant/strategy/user; (2) restrict visible tools; (3) force `tenantId` server-side on `topicSearch` even if the LLM tries to override it.

```go
// 1. Build the agent with a tenant-aware middleware
type TenantMW struct{ *adk.BaseChatModelAgentMiddleware }

func (m *TenantMW) BeforeAgent(ctx context.Context, runCtx *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
    // (2) restrict visible tools to topicSearch / iabSearch / audienceCreate
    allowed := map[string]bool{"topicSearch": true, "iabSearch": true, "audienceCreate": true}
    filtered := runCtx.Tools[:0]
    for _, t := range runCtx.Tools {
        info, _ := t.Info(ctx)
        if allowed[info.Name] {
            filtered = append(filtered, t)
        }
    }
    runCtx.Tools = filtered
    return ctx, runCtx, nil
}

func (m *TenantMW) WrapInvokableToolCall(ctx context.Context, ep adk.InvokableToolCallEndpoint, tCtx *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tCtx.Name != "topicSearch" { return ep, nil }
    return func(ctx context.Context, argumentsInJSON string, opts ...tool.Option) (string, error) {
        // (3) FORCE tenantId from session values, overriding any LLM-supplied value
        var args map[string]any
        _ = sonic.UnmarshalString(argumentsInJSON, &args)
        args["tenantId"] = adk.MustGetSessionValue(ctx, "tenantId") // strip-and-inject
        b, _ := sonic.Marshal(args)
        return ep(ctx, string(b), opts...)
    }, nil
}

agent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "long-running agent-supervisor", Model: cm,
    ToolsConfig: adk.ToolsConfig{
        ToolsNodeConfig: compose.ToolsNodeConfig{
            Tools: []tool.BaseTool{topicSearch, iabSearch, audienceCreate, bashExec, webFetch},
        },
    },
    Handlers: []adk.ChatModelAgentMiddleware{&TenantMW{}},
})

runner := adk.NewRunner(ctx, adk.RunnerConfig{Agent: agent, EnableStreaming: true, CheckPointStore: pgStore})

// (1) pass tenant / strategy / user via WithSessionValues
iter := runner.Query(ctx, "build me a travel audience",
    adk.WithSessionValues(map[string]any{
        "tenantId":            "acme",
        "targetingStrategyId": "strat-42",
        "userId":              "u-123",
    }),
    adk.WithCheckPointID("conv-789"),
)
```

This works. The main rough edges vs. LangGraph: (a) tool-arg injection is hand-rolled middleware, not declarative; (b) the LLM still sees the `tenantId` field in `topicSearch`'s JSON schema unless you scrub it out at tool-info generation time.

---

## 5. Hook & Middleware Capabilities (Context Engineering)

### 5.1 Enumerate every hook / middleware / lifecycle callback

Three layers, each with multiple hook points.

**Layer 1 — `callbacks.Handler` (graph-level, applies to every component invocation)**:

| Name | Fires when | Capabilities |
|---|---|---|
| `OnStart` | Just before any component begins (non-streaming input) | Read input, **mutate context** (passed to OnEnd), inject context values |
| `OnEnd` | After component returns successfully (non-streaming output) | Read output, instrument metrics |
| `OnError` | Component returned non-nil error | Read error |
| `OnStartWithStreamInput` | Component receives streaming input | Read+copy stream (must close copy) |
| `OnEndWithStreamOutput` | Component returns streaming output | Read+copy stream (must close copy) |

Implemented at `callbacks/interface.go:85` + `callbacks/aspect_inject.go`. Per-handler context propagation (`OnStart` ctx → `OnEnd` of same handler) lets a handler stash state for itself (`callbacks/interface.go:65-71`). **There is NO guaranteed handler order**, so handlers must be order-independent. `TimingChecker.Needed(timing)` lets the framework skip stream-copy overhead for unused timings.

**Layer 2 — `AgentMiddleware` struct (deprecated for new code; struct-based)** (`adk/chatmodel.go:175-193`):

| Field | Fires when | Capabilities |
|---|---|---|
| `AdditionalInstruction string` | At agent build | Appends to system prompt |
| `AdditionalTools []tool.BaseTool` | At agent build | Appends to tool list |
| `BeforeChatModel func(ctx, *State) error` | Before each model invocation | Mutate state (in place); can't change ctx |
| `AfterChatModel func(ctx, *State) error` | After each model invocation | Mutate state |
| `WrapToolCall compose.ToolMiddleware` | Around each tool dispatch | Full wrap (invokable/streamable/enhanced) |

**Layer 3 — `ChatModelAgentMiddleware` interface (new in v0.8+, recommended)** (`adk/handler.go:114-200`):

| Method | Fires when | Capabilities |
|---|---|---|
| `BeforeAgent(ctx, *ChatModelAgentContext) (ctx, *ChatModelAgentContext, error)` | Once before run | Mutate Instruction / Tools / ReturnDirectly; can return modified ctx |
| `BeforeModelRewriteState(ctx, *ChatModelAgentState, *ModelContext) (ctx, *state, error)` | Before each model call | Mutate the message list that will be sent to the model; can return modified ctx |
| `AfterModelRewriteState(ctx, *ChatModelAgentState, *ModelContext) (ctx, *state, error)` | After each model call | Mutate the post-call state (model response is last message) |
| `WrapInvokableToolCall(ctx, endpoint, *ToolContext) (endpoint, error)` | Around invokable tool call | Wrap the endpoint with custom pre/post |
| `WrapStreamableToolCall(...)` | Around streamable tool call | Same, streaming variant |
| `WrapEnhancedInvokableToolCall(...)` | Around enhanced invokable | Same, multimodal variant |
| `WrapEnhancedStreamableToolCall(...)` | Around enhanced streamable | Same, multimodal streaming |
| `WrapModel(ctx, m model.BaseChatModel, *ModelContext) (model.BaseChatModel, error)` | Around the model itself | Replace model entirely (e.g. for routing, retry, mid-stream tool filtering) |

Helper: embed `*adk.BaseChatModelAgentMiddleware` (`adk/handler.go:216-247`) for default no-op implementations of all 8 methods, so you only override what you need.

Plus three utility functions for middlewares:
- `adk.SendEvent(ctx, *AgentEvent)` (`adk/handler.go:325`) — emit a custom event into the iterator
- `adk.SetRunLocalValue(ctx, key, value)` / `GetRunLocalValue` / `DeleteRunLocalValue` — per-run state, persisted across interrupt/resume

### 5.2 Hook concurrency model

- **`callbacks.Handler`s fire in registration order**, but with NO inter-handler context flow — handler 1's `OnStart` mutated ctx does not visibly affect handler 2's `OnStart`. So users should treat them as independent observers.
- **`ChatModelAgentMiddleware.WrapModel` / `WrapToolCall` form a chain**: first registered is the outermost wrapper. So `[A, B, C]` produces `A(B(C(model)))`. Each wrapper can pass a modified ctx to `next`.
- **`BeforeAgent` / `BeforeModelRewriteState` run sequentially in registration order**, with the modified ctx + state passed through.
- **Tool dispatch within one super-step is parallel by default** (`ToolsNodeConfig.ExecuteSequentially: false`). Middlewares around tool calls run per-call, in goroutines.

### 5.3 Specific capability tests

- **Inject system message at session start**: ✅ via `BeforeAgent` mutating `runCtx.Instruction` (string concat). Or via `WithSessionValues(map[string]any{"Time": "2026-05-16", ...})` if your instruction has f-string placeholders.
- **Expand user input (slash commands, timestamp, attachments)**: ✅ via `BeforeModelRewriteState` mutating the message list, OR a `GenModelInput` function on `ChatModelAgentConfig`.
- **Mutate messages list before each LLM call (prompt cache, redaction)**: ✅ via `BeforeModelRewriteState` (`adk/handler.go:128`) or `WrapModel` which gets `input []*schema.Message`.
- **Mutate tool input before dispatch (inject `tenantId`)**: ✅ via `WrapInvokableToolCall` or `compose.ToolsNodeConfig.ToolArgumentsHandler` — see Q4.4.
- **Mutate tool result before it returns to LLM (redact, summarize, truncate)**: ✅ via `WrapInvokableToolCall` — call `endpoint(...)` then mutate the returned string. The `summarization` middleware (`adk/middlewares/summarization/summarization.go`) is a real-world example that does this at the message-list level when token count exceeds a threshold.
- **Emit additional tool calls in response to a tool result (PostToolUse with additional_messages)**: **Partial** ❌. You can emit a *custom event* via `adk.SendEvent`, but you cannot append synthetic ToolMessages that the LLM will see on the next turn without going through the message list mutation. There is no direct `additional_messages` analogue. Workaround: `WrapInvokableToolCall` can call `endpoint` multiple times, or do the work inline and concatenate results — but the LLM only sees one tool result per tool call. **Genuine gap vs. Claude Agent SDK / LangGraph.**

### 5.4 Auto-compaction

**Yes — `adk/middlewares/summarization/`** ships a built-in summarization middleware:

```go
// adk/middlewares/summarization/summarization.go:50-89
type Config struct {
    Model        model.BaseChatModel
    ModelOptions []model.Option
    TokenCounter TokenCounterFunc  // default: ~4 chars/token estimator
    Trigger      *TriggerCondition // default: trigger when tokens > 190k
    EmitInternalEvents bool
    UserInstruction string
    TranscriptFilePath string
    GenModelInput GenModelInputFunc
    Finalize FinalizeFunc
    // ...
}
```

Configurable trigger (token threshold), pluggable token counter, customizable summary prompt, optional transcript-file pointer in the summary so the model can re-read full history on demand. Fires inside `BeforeModelRewriteState` — checks token count, runs summarization model, replaces the message list.

There is also a separate `adk/middlewares/reduction/` middleware for tool-result reduction (truncate large tool outputs in-place).

### 5.5 Prompt cache optimization

- **Provider-cache-aware**: indirectly. The framework preserves message-list stability (it does not reshuffle history), so Anthropic / OpenAI prompt caching can land naturally when the same prefix is sent repeatedly. There is **no first-class `cache_control` breakpoint placement helper** — you write it yourself by setting Anthropic-specific fields on the `*schema.Message.Extra` via the Claude adapter's hooks.
- **Stable-prefix preservation**: yes, by default — `BeforeModelRewriteState` middlewares should append rather than prepend; otherwise the cache breaks.
- **Automatic vs. manual**: manual. Eino does not insert cache breakpoints for you.

The `PromptTokenDetails.CachedTokens` field on `schema.TokenUsage` (`schema/message.go:710-714`) lets you observe cache hit rate.

### 5.6 Tool result clearing / progressive disclosure

**Yes — `adk/middlewares/reduction/`** + the **filesystem offloading pattern** (`adk/middlewares/filesystem/large_tool_result.go`):

- `reduction/` truncates oversized tool outputs in the message list, leaving a summary.
- The filesystem middleware automatically stashes oversized tool results into the configured `filesystem.Backend` and replaces the tool message with a short reference + first-10-lines preview, suggesting the LLM use `read_file` with offset/limit to retrieve more (`adk/middlewares/filesystem/prompt.go:28-42`).

This is the closest match to Claude Code's "progressive disclosure" pattern in any Go framework benchmarked.

### 5.7 Architectural diagram of hook fire-points

```
Runner.Run(ctx, messages)
   │
   ▼
flowAgent.Run                       ─── callbacks.OnStart (component=Agent)
   │
   ▼
ChatModelAgent.Run
   │
   ▼  BeforeAgent (ChatModelAgentMiddleware, in registration order)
   │  → mutate Instruction, Tools, ReturnDirectly
   ▼
LOOP (until no tool calls or MaxIterations exhausted):
   │
   │  ┌──────────── ChatModel super-step ──────────────────┐
   │  │                                                    │
   │  │  AgentMiddleware.BeforeChatModel (deprecated)      │
   │  │  ChatModelAgentMiddleware.BeforeModelRewriteState  │
   │  │     → mutate Messages                              │
   │  │                                                    │
   │  │  retryModelWrapper (internal, if retry configured) │
   │  │  eventSenderModelWrapper (internal)                │
   │  │  WrapModel (user middlewares, outermost first)     │
   │  │  callbackInjectionModelWrapper (internal)          │
   │  │  ─────────► model.Generate / model.Stream          │
   │  │              callbacks.OnStart (component=ChatModel)
   │  │              callbacks.OnEnd / OnError
   │  │                                                    │
   │  │  AfterModelRewriteState                            │
   │  │  AgentMiddleware.AfterChatModel                    │
   │  └────────────────────────────────────────────────────┘
   │
   │  branch on ToolCalls
   │
   │  ┌──────────── Tools super-step (parallel goroutines) ┐
   │  │  For each tool call:                               │
   │  │   eventSenderToolHandler (internal)                │
   │  │   ToolsConfig.ToolCallMiddlewares (user)           │
   │  │   AgentMiddleware.WrapToolCall (deprecated)        │
   │  │   ChatModelAgentMiddleware.WrapToolCall            │
   │  │   callbackInjectedToolCall (internal)              │
   │  │   ────► tool.InvokableRun / StreamableRun          │
   │  │           callbacks.OnStart (component=Tool)       │
   │  │           callbacks.OnEnd                          │
   │  └────────────────────────────────────────────────────┘
   │
   ▼  back to ChatModel super-step (or END if no calls)

END ─── callbacks.OnEnd (component=Agent)
```

### ⭐ Required — light usage example

```go
type PredictMW struct{ *adk.BaseChatModelAgentMiddleware }

// (1) SessionStart hook — inject "tenant=acme, locale=fr-FR, today=2026-05-16" as system message
func (m *PredictMW) BeforeAgent(ctx context.Context, rc *adk.ChatModelAgentContext) (context.Context, *adk.ChatModelAgentContext, error) {
    tenant := adk.MustGetSessionValue(ctx, "tenantId").(string)
    rc.Instruction += fmt.Sprintf("\n\nContext: tenant=%s, locale=fr-FR, today=2026-05-16.", tenant)
    return ctx, rc, nil
}

// (2) PreToolUse on topicSearch — inject tenantId server-side
func (m *PredictMW) WrapInvokableToolCall(ctx context.Context, ep adk.InvokableToolCallEndpoint, tCtx *adk.ToolContext) (adk.InvokableToolCallEndpoint, error) {
    if tCtx.Name != "topicSearch" { return ep, nil }
    return func(ctx context.Context, args string, opts ...tool.Option) (string, error) {
        var a map[string]any
        _ = sonic.UnmarshalString(args, &a)
        a["tenantId"] = ctx.Value("tenantId")
        b, _ := sonic.Marshal(a)
        // (3) PostToolUse — if result has > 50 topics, summarize in place
        out, err := ep(ctx, string(b), opts...)
        if err != nil { return out, err }
        var res struct{ Topics []string `json:"topics"` }
        _ = sonic.UnmarshalString(out, &res)
        if len(res.Topics) > 50 {
            summary := summarizeTopics(res.Topics)  // your code
            out, _ = sonic.MarshalString(map[string]any{"summary": summary, "count": len(res.Topics)})
        }
        return out, nil
    }, nil
}

agent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "long-running agent-supervisor", Model: cm,
    Handlers: []adk.ChatModelAgentMiddleware{&PredictMW{}},
    ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{Tools: tools}},
})
```

---

## 6. Agent API Exposition (HTTP/network surface)

### 6.1 Does the stack ship an HTTP/network server?

**No.** Eino has no `Server`, no `ListenAndServe`, no `cmd/server`. Grep confirms: outside of `callbacks/interface.go`'s mentions of HTTP-shaped tracing, the core eino repo does not import `net/http` for serving purposes. You bring your own HTTP layer (gin, hertz, fiber, gorilla/mux, chi, stdlib).

### 6.2 Streaming transport

**Not provided — BYO.** Inside the process, the runtime uses `*AsyncIterator[*AgentEvent]` (Go channel). For network exposure, you serialize each frame yourself. Typical pattern: SSE.

### 6.3 Endpoints that start an agent run

**Not provided — BYO.** You write the handler:

```go
http.HandleFunc("/v1/runs", func(w http.ResponseWriter, r *http.Request) {
    tenant := r.Header.Get("X-Tenant-Id")
    var body struct{ Message string `json:"message"` }
    json.NewDecoder(r.Body).Decode(&body)
    ctx := context.WithValue(r.Context(), "tenantId", tenant)
    iter := runner.Query(ctx, body.Message, adk.WithSessionValues(map[string]any{"tenantId": tenant}))
    w.Header().Set("Content-Type", "text/event-stream")
    flusher, _ := w.(http.Flusher)
    for {
        event, ok := iter.Next()
        if !ok { break }
        json.NewEncoder(w).Encode(toWireEvent(event))
        flusher.Flush()
    }
})
```

### 6.4 Live agentic event stream format

**Not provided.** Whatever you write in your handler. Ray uses an internal SSE format defined in `pkg/ai/agent/session.go`.

### 6.5 Auth termination at API boundary

**Not provided.** Auth is your host's responsibility.

### 6.6 Resume / replay endpoint

The `Runner.Resume(ctx, checkPointID)` method exists at the Go API level. You expose it as an HTTP endpoint yourself — e.g. `POST /v1/runs/{id}/resume` calls `runner.Resume(ctx, runID)`.

### 6.7 Interrupt / cancel via API

**Not first-class.** You cancel via `context.CancelFunc` in your host code — when the HTTP request is aborted, `r.Context().Done()` fires, your goroutine sees the cancel, and the agent's in-flight model / tool calls receive the cancellation through ctx propagation. The framework doesn't ship a separate "abort run" API.

### 6.8 Tool-arg streaming (partial JSON)

**Partial.** Tool-call deltas come through in the model's streamed `*schema.Message` chunks (each chunk has `ToolCalls` partial fields with `Index` for merging). The merge logic is in `schema.ConcatMessages`. There's no separate "tool-arg-fragment" event type — you'd extract it from the streamed message chunks yourself.

### 6.9 HITL approval workflow

**Not first-class as an API.** At the runtime level:
- Tool code calls `adk.Interrupt(ctx, info)` or `adk.StatefulInterrupt(ctx, info, state)` to pause.
- Runner saves checkpoint, sends `InterruptedAgentEvent` to the iterator.
- Caller stores the human's verdict somewhere and calls `runner.ResumeWithParams(ctx, checkpointID, &adk.ResumeParams{Targets: map[string]any{"<interrupt-address>": <approval-data>}})`.

You expose this as an HTTP endpoint yourself: `POST /v1/runs/{id}/approve` reads the verdict, calls `ResumeWithParams`. There is no shipped HITL HTTP route.

### 6.10 Tool-call state reconstruction

`tool_use` (assistant message with `ToolCalls`) and `tool_result` (tool message with `ToolCallID`) are linked by **explicit `ToolCallID`**. The assistant's `ToolCall.ID` becomes the tool message's `ToolCallID`. The framework guarantees ordering: when multiple tool calls run in parallel, the resulting `[]*schema.Message` from `ToolsNode` has tool messages in the same order as the input tool calls (`compose/tool_node.go:60-62`).

```go
// schema/message.go:123-136
type ToolCall struct {
    Index    *int   `json:"index,omitempty"`     // for streaming chunk merging
    ID       string `json:"id"`                  // ← linkage key
    Type     string `json:"type"`
    Function FunctionCall `json:"function"`
    Extra    map[string]any `json:"extra,omitempty"`
}
```

```go
// schema/message.go:676-678
ToolCallID string `json:"tool_call_id,omitempty"`  // ← linkage key on tool message
ToolName   string `json:"tool_name,omitempty"`
```

### 6.11 Health checks / graceful shutdown

**Not provided.** Your HTTP host owns this.

### ⭐ Required — light usage example

Since there's no HTTP layer, the "usage" is what *you* build:

```bash
# (1) start a run — what your host endpoint would look like
curl -N -X POST https://predict.dailymotion.com/v1/runs \
  -H 'X-Tenant-Id: acme' \
  -H 'Content-Type: application/json' \
  -d '{"message":"build a travel audience","conversationId":"conv-789"}'

# (2) sample SSE frames (your serialization)
event: message
data: {"agentName":"long-running agent-supervisor","output":{"role":"assistant","content":"Looking at travel topics..."}}

event: tool_use
data: {"agentName":"long-running agent-supervisor","toolCallId":"call_xyz","toolName":"topicSearch","args":{"theme":"travel"}}

event: tool_result
data: {"agentName":"long-running agent-supervisor","toolCallId":"call_xyz","content":"{\"topics\":[\"beach\",\"hiking\",...]}"}

event: done
data: {"agentName":"long-running agent-supervisor"}

# (3) cancel — close the connection, or call your own endpoint
curl -X DELETE https://predict.dailymotion.com/v1/runs/conv-789

# (4) approve a paused tool call (HITL) — your endpoint reads the verdict, calls ResumeWithParams
curl -X POST https://predict.dailymotion.com/v1/runs/conv-789/approve \
  -H 'Content-Type: application/json' \
  -d '{"interruptAddress":"agent:long-running agent-supervisor/tool:audienceCreate","approved":true,"comment":"OK"}'
```

**None of these endpoints exist in Eino. You write all four.**

---

## 7. Sub-agents

### 7.1 Mechanism

Three first-class mechanisms (all live in your process):

1. **Transfer-based (handoff)** via `SetSubAgents` (`adk/flow.go:71-73`). Sub-agents are siblings; the LLM uses a `transfer_to_agent` tool (`adk/chatmodel.go:404`) to hand off control. Hierarchical: a sub-agent can transfer back to parent unless `disallowTransferToParent` is set. This matches Anthropic's "swarm" pattern.

2. **Agents-as-tools** via `NewAgentTool` (`adk/agent_tool.go:93-104`). Wraps an `Agent` as a `tool.BaseTool` that the LLM calls like any other tool. The inner agent runs in its own context (with `withSharedParentSession` so shared session values are visible); its events optionally bubble up via `EmitInternalEvents` (`adk/chatmodel.go:111-122`).

3. **Workflow agents** — `NewSequentialAgent`, `NewParallelAgent`, `NewLoopAgent` (`adk/workflow.go:599-612`). Pre-built deterministic orchestrators.

Plus prebuilt patterns: `supervisor.New` (`adk/prebuilt/supervisor/supervisor.go:99`), `deep.NewDeepAgent` (`adk/prebuilt/deep/deep.go`), `planexecute.New` (`adk/prebuilt/planexecute/plan_execute.go:862`).

### 7.2 Configuration

- **Struct-registered at boot**: yes — `ChatModelAgentConfig` + `ParallelAgentConfig` + `SupervisorConfig` are all Go structs assembled in code.
- **Markdown file**: yes, via the `skill` middleware (`adk/middlewares/skill/`): SKILL.md files can specify `agent: <name>` and `context: fork_with_context`, causing the skill to spawn a sub-agent via the configured `AgentHub`.
- **Inlined per call**: no — sub-agents must be constructed before `Runner.Run`.
- **LLM-generated at runtime**: **no — not supported**. The parent LLM cannot generate a sub-agent config on the fly with a custom prompt; configs are static at the Go struct level.

### 7.3 LLM-generated configs

**Not supported.** This is a deliberate-feel: the static-typing of `Agent` configuration is enforced by Go. The closest workaround is the `taskTool` pattern (`adk/prebuilt/deep/task_tool.go:125-174`) where the LLM picks a `subagent_type` from a fixed registry and supplies a free-text `description`, but the sub-agent itself is pre-registered.

### 7.4 Output handling

- Single result string (the last assistant message content) returned via `agentTool.InvokableRun` (`adk/agent_tool.go:236-248`).
- Optionally: all sub-agent events streamed up to the parent's iterator via `ToolsConfig.EmitInternalEvents: true` — useful for end-user UI streaming, NOT recorded in parent's session (`adk/chatmodel.go:115-122`).
- Linked back to the parent's `tool_use.id` via the `tool_call_id` on the wrapping tool message.

### 7.5 Concurrency model

- Sequential: `runSequential` (`adk/workflow.go:172+`)
- Parallel: `runParallel` (`adk/workflow.go:427-551`) — **here's the actual `sync.WaitGroup` + goroutine fan-out**:

  ```go
  // adk/workflow.go:471-516
  for i := range a.subAgents {
      wg.Add(1)
      go func(idx int, agent *flowAgent) {
          defer func() {
              panicErr := recover()
              if panicErr != nil { /* ... */ }
              wg.Done()
          }()

          var iterator *AsyncIterator[*AgentEvent]
          if _, ok := agentNames[agent.Name(ctx)]; ok {
              iterator = agent.Resume(childContexts[idx], &ResumeInfo{...}, opts...)
          } else if parState != nil {
              return
          } else {
              iterator = agent.Run(childContexts[idx], nil, opts...)
          }

          for {
              event, ok := iterator.Next()
              if !ok { break }
              if event.Action != nil && event.Action.internalInterrupted != nil {
                  mu.Lock()
                  subInterruptSignals = append(subInterruptSignals, event.Action.internalInterrupted)
                  dataMap[idx] = event.Action.Interrupted
                  mu.Unlock()
                  break
              }
              generator.Send(event)
          }
      }(i, a.subAgents[i])
  }
  wg.Wait()
  ```

  After all goroutines `wg.Done`, the parent commits child events back via `joinRunCtxs(ctx, childContexts...)`.

- Loop: `runLoop` (`adk/workflow.go:~350`).

For agents-as-tools (`NewAgentTool`), parallel execution comes for free because `ToolsNode` runs tool calls in parallel goroutines by default — so an LLM that emits N agent-tool calls in one assistant message gets N parallel sub-agent runs.

### 7.6 Context isolation

- For workflow `Parallel`: each branch forks the `runContext` via `forkRunCtx` (`adk/runctx.go:328-358`), creating a per-lane `runSession` that **shares Values + valuesMtx** with the parent but has its own `LaneEvents` slice. So sibling parallel agents see each other's session values but NOT each other's events until commit.
- For `agentTool`: `withSharedParentSession()` (`adk/call_option.go:64-68`) keeps the session Values shared; the inner agent runs with its own `runContext` but shares the parent's session for k-v.
- For `transfer_to_agent` handoff: the destination agent inherits the same `runContext`; transfer messages are added to history (`adk/agent_tool.go:293-325`).

You can explicitly isolate by calling `ClearRunCtx(ctx)` (`adk/runctx.go:383-385`) — useful when nesting an entire multi-agent system inside a tool and you don't want context leakage.

### 7.7 Lifecycle events

- `callbacks.Handler.OnStart` / `OnEnd` fire once per agent boundary (parent + each sub-agent). The `RunInfo.Component = ComponentOfAgent` and `RunInfo.Type = "ChatModel"` / `"Sequential"` / `"Parallel"` / `"Loop"` / `"Supervisor"` distinguishes types (`adk/callback.go:130-135`).
- Sub-agent **events** (per-message, per-tool-call) are NOT in the parent iterator by default — opt in via `ToolsConfig.EmitInternalEvents: true`.

### ⭐ Required — light usage example

```go
// 3 persona sub-agents, each with its own system prompt and topicSearch tool
makePersona := func(name, prompt string) adk.Agent {
    a, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
        Name: name, Description: name + " persona researcher",
        Model: cm, Instruction: prompt,
        ToolsConfig: adk.ToolsConfig{ToolsNodeConfig: compose.ToolsNodeConfig{
            Tools: []tool.BaseTool{topicSearch},
        }},
    })
    return a
}

youngMom  := makePersona("persona-young-mom",  "You are a 32-year-old mother of two...")
techBro   := makePersona("persona-tech-bro",   "You are a 28-year-old SF software engineer...")
retiree   := makePersona("persona-retiree",    "You are a 68-year-old retired teacher...")

// Parent runs them in PARALLEL via NewParallelAgent
parallel, _ := adk.NewParallelAgent(ctx, &adk.ParallelAgentConfig{
    Name: "persona-fanout", Description: "fan out to 3 personas in parallel",
    SubAgents: []adk.Agent{youngMom, techBro, retiree},
})

runner := adk.NewRunner(ctx, adk.RunnerConfig{Agent: parallel, EnableStreaming: false})
iter := runner.Query(ctx, "Suggest 5 video topics for our travel campaign.")
for {
    e, ok := iter.Next()
    if !ok { break }
    // each persona's events stream here; tag by e.AgentName / e.RunPath
    fmt.Printf("[%s] %s\n", e.AgentName, summarize(e))
}
```

Alternative — agents-as-tools (parent LLM decides which persona to invoke):

```go
parent, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "long-running agent-supervisor", Model: cm,
    Instruction: "Use the persona-* tools to gather feedback before suggesting topics.",
    ToolsConfig: adk.ToolsConfig{
        ToolsNodeConfig: compose.ToolsNodeConfig{
            Tools: []tool.BaseTool{
                adk.NewAgentTool(ctx, youngMom),
                adk.NewAgentTool(ctx, techBro),
                adk.NewAgentTool(ctx, retiree),
            },
        },
        EmitInternalEvents: true, // bubble persona events up
    },
})
```

**Where the parent receives each result**: in the agents-as-tools pattern, each persona's final message becomes the tool message content for the corresponding `tool_use_id` the LLM emitted. In the `ParallelAgent` pattern, each persona's events stream into the parent iterator tagged with `e.AgentName` and `e.RunPath`.

---

## 8. Skills

### 8.1 First-class concept?

**Yes — first-class via `adk/middlewares/skill/`.** Loaded as a `ChatModelAgentMiddleware`; surfaces a `skill` (renameable) tool to the LLM. Closest match in any Go framework benchmarked to Claude Code's SKILL.md model.

### 8.2 File format

`SKILL.md` with **YAML frontmatter** (`adk/middlewares/skill/skill.go:48-54`):

```yaml
---
name: Generate-Audience-From-Brief
description: Turn a brief long-running agent description into a Predict audience.
context: fork_with_context     # "fork" | "fork_with_context" | "" (inline)
agent: audience-builder        # OPTIONAL — agent name to fetch from AgentHub
model: gpt-4o                  # OPTIONAL — model name to fetch from ModelHub
---
# Markdown body becomes the skill instructions / sub-agent prompt
```

Schema fields:

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
    Content       string  // markdown body
    BaseDirectory string  // absolute dir where SKILL.md lives
}
```

### 8.3 Loader mechanism

**Pluggable `Backend` interface** (`adk/middlewares/skill/skill.go:66-69`):

```go
type Backend interface {
    List(ctx context.Context) ([]FrontMatter, error)
    Get(ctx context.Context, name string) (Skill, error)
}
```

**`filesystemBackend`** ships (`adk/middlewares/skill/filesystem_backend.go:49-64`):

```go
backend, _ := skill.NewBackendFromFilesystem(ctx, &skill.BackendFromFilesystemConfig{
    Backend: fsBackend,        // adk/filesystem.Backend
    BaseDir: "/skills",        // each subdirectory has its own SKILL.md
})
```

The filesystem backend scans **first-level subdirectories** for `SKILL.md` (not recursive). You can also implement `Backend` against Postgres, S3, an HTTP API, etc.

### 8.4 Invocation

**Tool call.** The LLM sees a `skill` tool (or whatever you renamed it to via `SkillToolName`). It invokes the skill by name; the middleware loads the skill content and either:
- **Inline mode** (`context: ""` blank): returns the markdown body as the tool result → next turn the LLM has the skill content in its context.
- **Fork mode** (`context: fork`): spawns a sub-agent (via `AgentHub.Get(ctx, frontMatter.Agent, opts)`) with the skill content as its system message, runs it, returns the sub-agent's final message as the tool result.
- **Fork-with-context mode** (`context: fork_with_context`): same as fork but the parent's message history is replayed into the sub-agent's input (`adk/middlewares/skill/skill.go:511-517`).

If `model: <name>` is set in frontmatter and the skill runs inline, `setActiveModel` (`adk/middlewares/skill/skill.go:414-416`) stores the model name in a run-local value, and `WrapModel` swaps the model for subsequent calls.

### 8.5 Loading mode

**Lazy.** The tool description sent to the LLM enumerates available skills (name + 1-line description from frontmatter) via `renderToolDescription` (`adk/middlewares/skill/skill.go:610-623`). The full markdown body is only fetched when the LLM invokes the skill. This keeps initial context small even with hundreds of skills.

### 8.6 Runtime scoping (global / tenant / user)

**Possible but you build it.** The `Backend` interface gets `ctx context.Context` on every `List` and `Get`, so you can filter by tenant from ctx:

```go
type tenantBackend struct{ base skill.Backend }

func (b *tenantBackend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    tenant := ctx.Value("tenantId").(string)
    all, _ := b.base.List(ctx)
    return filterByTenantPolicy(all, tenant), nil
}
```

There is **no first-class skill-scope field** in `FrontMatter`. You add it in your backend's metadata or in a sidecar file.

### 8.7 Skill composition

- A skill in fork mode can have its own sub-agent that itself has tools, sub-agents, skills, etc. — full recursion.
- The skill body is markdown; it can reference files in the skill's `BaseDirectory` (the directory containing SKILL.md is passed to the sub-agent's instruction context via `userContent` template — `adk/middlewares/skill/skill.go:457-479`). So you can bundle scripts, JSON examples, prompt templates alongside SKILL.md.
- A skill can **call other skills** if the spawned sub-agent has the skill middleware installed. No first-class `skill: <name>` reference; just normal tool invocation.

### ⭐ Required — light usage example

```go
// 1. Author /skills/generate-audience-from-brief/SKILL.md:
//
//    ---
//    name: Generate-Audience-From-Brief
//    description: Turn a long-running agent brief into a Predict audience JSON.
//    context: fork_with_context
//    agent: audience-builder
//    ---
//    # Generate Audience From Brief
//
//    Given a long-running agent brief, produce a Predict audience definition as JSON.
//    Steps:
//      1. Identify the campaign's primary theme (topicSearch)
//      2. Identify IAB categories (iabSearch)
//      3. Combine into an Audience object via audienceCreate
//
//    Output format:
//      { "audienceId": "...", "rules": [...] }

// 2. Configure the skill middleware at agent build time
fsBack, _ := localfs.NewBackend(ctx, &localfs.Config{Root: "/skills"})
skillBack, _ := skill.NewBackendFromFilesystem(ctx, &skill.BackendFromFilesystemConfig{
    Backend: fsBack, BaseDir: "/skills",
})

agentHub := &myAgentHub{audienceBuilder: audienceBuilderAgent}
modelHub := &myModelHub{cm: cm}

skillMW, _ := skill.NewMiddleware(ctx, &skill.Config{
    Backend:  skillBack,
    AgentHub: agentHub,
    ModelHub: modelHub,
})

supervisor, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "long-running agent-supervisor", Model: cm,
    Instruction: "Use the `skill` tool to discover and run available workflows.",
    Handlers: []adk.ChatModelAgentMiddleware{skillMW},
})

// 3. The agent discovers the skill via the `skill` tool description (enumerates all skills),
//    invokes via tool_call:  {"skill": "Generate-Audience-From-Brief"}.
//    The middleware loads SKILL.md, spawns audienceBuilderAgent with the parent's history
//    + skill content as instructions, runs it, returns its final message as the tool result.
runner := adk.NewRunner(ctx, adk.RunnerConfig{Agent: supervisor})
iter := runner.Query(ctx, "Take this brief and build an audience: 'Travel enthusiasts in fr-FR'.")
```

**What the LLM sees**: a `skill` tool whose description enumerates `- Generate-Audience-From-Brief: Turn a long-running agent brief into a Predict audience JSON.`. When the LLM calls `skill({"skill":"Generate-Audience-From-Brief"})`, the middleware loads the skill and either returns content inline (next LLM turn sees full markdown) or spawns the sub-agent.

---

## 9. Resource Manager

### 9.1 First-class Resource Manager?

**No — BYO.** There is no `Registry`, no `SkillSource`, no versioning, no publishing workflow. The closest seams are the pluggable interfaces:

- `skill.Backend` (`adk/middlewares/skill/skill.go:66`) — skill source
- `skill.AgentHub` (`adk/middlewares/skill/skill.go:79`) — agent source
- `skill.ModelHub` (`adk/middlewares/skill/skill.go:86`) — model source

You build a Resource Manager *on top of* these. None are layered, none are scoped at the platform level, none have versioning.

### 9.2 Loading sources

| Source | Provided | How configured |
|---|---|---|
| Local filesystem | ✅ via `filesystemBackend` (`adk/middlewares/skill/filesystem_backend.go`) | `NewBackendFromFilesystem(ctx, &Config{Backend, BaseDir})` |
| Git / GitHub | ❌ Not provided | BYO — write a `Backend` that shells `git`, or use `go-git` to clone-then-scan |
| OCI / container registries | ❌ Not provided | BYO |
| Cloud object storage (S3, GCS, R2) | ❌ Not provided | BYO — write a `Backend` that fetches via `cloud.google.com/go/storage` |
| Postgres / relational DB | ❌ Not provided | BYO — `Backend.List` runs `SELECT name, frontmatter FROM skills WHERE tenant_id=$1` |
| Vendor managed registry | ❌ Not provided (no CloudWeGo Hub) | BYO |
| HTTP fetch | ❌ Not provided | BYO — simple `http.Get` in a custom backend |

**The skill middleware ships only the filesystem backend; everything else is wired by you.** Same for agents (only your in-process Go agents can be in an `AgentHub` you implement) and models.

### 9.3 Source composition / priority

**Not provided.** You'd implement a `Backend` that composes multiple backends with your priority logic:

```go
type layeredBackend struct{ tenants, global skill.Backend }
func (b *layeredBackend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    t, _ := b.tenants.List(ctx)
    g, _ := b.global.List(ctx)
    return mergeWithTenantWinning(t, g), nil
}
```

### 9.4 Versioning model

**Not provided.** Skills are mutable files (or rows in your store); no semver, no content-hash refs, no rollback. If you want versioning, your backend produces it.

### 9.5 Scoping at the registry layer

**Not provided at framework level.** Your `Backend` implementation does the scoping (see Q8.6).

### 9.6 Publishing workflow

**Not provided.** No draft / review / promote / multi-environment workflow. Build with git tags + your own CI.

### 9.7 Lifecycle / governance

**Not provided.** No lifecycle states (`draft`, `active`, `deprecated`, `retired`), no RBAC at the resource layer.

### 9.8 Programmatic API

**Not provided as a top-level Resource Manager API.** The `Backend` interface (`List` + `Get`) IS the programmatic API at the skill layer. There is no cross-resource registry.

### 9.9 Caching & sync model

**Not provided.** Your `Backend.List` runs on every tool-description-generation. You add caching, watchers, sync intervals yourself.

### ⭐ Required — light usage example

Since Eino has no Resource Manager, the example is "what you'd build" — a layered `Backend` with tenant winning over global, and tenant-scoped active set:

```go
type s3Backend struct{ bucket, prefix string; storage *storage.Client }
func (b *s3Backend) List(ctx context.Context) ([]skill.FrontMatter, error) {
    tenant := ctx.Value("tenantId").(string)
    // GCS list: gs://predict-skills/tenants/{tenant}/
    objs, _ := b.storage.Bucket(b.bucket).Objects(ctx, &storage.Query{Prefix: fmt.Sprintf("%s/tenants/%s/", b.prefix, tenant)}).All()
    var fms []skill.FrontMatter
    for _, o := range objs {
        if !strings.HasSuffix(o.Name, "/SKILL.md") { continue }
        fm := parseFrontmatter(b.fetch(ctx, o.Name))
        if fm.LifecycleState != "active" { continue }       // (2) only active for this tenant
        fms = append(fms, fm)
    }
    return fms, nil
}

// (1) layered backend: git source as global default, S3 tenant overrides win
gitGlobal, _ := newGitBackend(ctx, "git+https://github.com/dailymotion/predict-skills")
s3Tenant   := &s3Backend{bucket: "predict-skills", prefix: ""}

layered := &layeredBackend{tenant: s3Tenant, global: gitGlobal}

skillMW, _ := skill.NewMiddleware(ctx, &skill.Config{Backend: layered, AgentHub: agentHub, ModelHub: modelHub})

// (2) promote draft → active for tenant 'acme' only — done out-of-band in your CI / admin UI
//     by editing the S3 object's frontmatter `lifecycle: active` and the S3 backend honors it.

// (3) list active skills visible to a request — implicit in the tool description for the LLM
ctx = context.WithValue(ctx, "tenantId", "acme")
runner := adk.NewRunner(ctx, adk.RunnerConfig{Agent: agentUsingSkillMW})
iter := runner.Query(ctx, "...")  // skill tool desc will only enumerate acme's active skills
```

This is **100% custom code**. Eino provides the seam (`Backend`); the platform is yours.

---

## 10. Observability: Usage, Cost, Tracing, Audit

### 10.1 Where tokens are surfaced

On each assistant message's `ResponseMeta.Usage` (`schema/message.go:603-611`):

```go
type ResponseMeta struct {
    FinishReason string
    Usage        *TokenUsage   // ← here
    LogProbs     *LogProbs
}

type TokenUsage struct {
    PromptTokens     int
    PromptTokenDetails PromptTokenDetails  // .CachedTokens
    CompletionTokens int
    TotalTokens      int
    CompletionTokensDetails CompletionTokensDetails  // .ReasoningTokens
}
```

You read it off `message.ResponseMeta.Usage` after a generation. Per-turn / per-session aggregation is your responsibility.

### 10.2 Per-call / per-turn / per-session / per-tenant rollups

**Per-call**: yes (on `ResponseMeta.Usage`). **Per-turn / per-session / per-tenant**: not provided as rollups; build with `callbacks.Handler.OnEnd` summing into your metric sink.

### 10.3 USD cost computation

**Not provided.** Eino reports tokens; you convert to USD using a price table you maintain (it's a simple lookup since `RunInfo.Type` tells you the model adapter).

### 10.4 Per-tenant / per-conversation cost

**Not provided.** First-party rollup absent. BYO via metadata-tagged tracing: every `callbacks.Handler.OnStart` knows the ctx (which holds tenantId via `WithSessionValues`), emit metrics tagged by tenant.

### 10.5 LLM / tool tracing

Three first-party tracing exporters (all in eino-ext as separate Go modules):

- **Langfuse**: `callbacks/langfuse/langfuse.go` — batched event submission, configurable threads/queue/flush, mask function for sensitive data, sampling.
- **LangSmith**: `callbacks/langsmith/` — `Run` / `RunPatch` schema, `flow_trace.go` for full trace assembly, hierarchical `dotted_order` for nested runs.
- **APMPlus**: `callbacks/apmplus/apmplus.go` — OpenTelemetry-native (uses `go.opentelemetry.io/otel`), emits OTel spans + metrics, native runtime metrics.

Plus **CozeLoop** for ByteDance's internal tracing platform.

All are wired in via `callbacks.AppendGlobalHandlers(handler)` at process boot, after which **every** component invocation (Graph, ChatModel, Tool, Retriever, Indexer, Embedding, Lambda) is automatically traced.

### 10.6 Audit logging (who / when / what)

**Not first-class as separate from tracing.** You'd write a `callbacks.Handler` (or use the agent-level `WithCallbacks` option) that emits structured audit events to your sink. Tamper-evident logging (hash chain, signed events) is not provided.

### 10.7 Canonical "where do I read token counts" code path

```go
// schema/message.go:680  (Message struct)
ResponseMeta *ResponseMeta `json:"response_meta,omitempty"`

// schema/message.go:603-611  (ResponseMeta)
type ResponseMeta struct {
    FinishReason string `json:"finish_reason,omitempty"`
    Usage        *TokenUsage `json:"usage,omitempty"`
    LogProbs     *LogProbs `json:"logprobs,omitempty"`
}

// schema/message.go:690-708  (TokenUsage)
type TokenUsage struct {
    PromptTokens     int `json:"prompt_tokens"`
    PromptTokenDetails PromptTokenDetails `json:"prompt_token_details"`
    CompletionTokens int `json:"completion_tokens"`
    TotalTokens      int `json:"total_tokens"`
    CompletionTokensDetails CompletionTokensDetails `json:"completion_token_details"`
}
```

### ⭐ Required — light usage example

```go
// (1) Read tokens / compute USD for one completed run
iter := runner.Query(ctx, "...")
var promptTokens, completionTokens int
for {
    e, ok := iter.Next()
    if !ok { break }
    if e.Output == nil || e.Output.MessageOutput == nil { continue }
    msg, _ := e.Output.MessageOutput.GetMessage()
    if msg != nil && msg.ResponseMeta != nil && msg.ResponseMeta.Usage != nil {
        promptTokens     += msg.ResponseMeta.Usage.PromptTokens
        completionTokens += msg.ResponseMeta.Usage.CompletionTokens
    }
}
costUSD := float64(promptTokens) * 3.0e-6 + float64(completionTokens) * 15.0e-6  // Claude 3.5 Sonnet pricing
log.Printf("run tokens_in=%d tokens_out=%d cost_usd=%.4f", promptTokens, completionTokens, costUSD)

// (2) Push per-tenant token usage to OTel via a custom callbacks.Handler
type TokenMetricHandler struct{ inHist, outHist metric.Int64Histogram }

func (h *TokenMetricHandler) OnEnd(ctx context.Context, info *callbacks.RunInfo, out callbacks.CallbackOutput) context.Context {
    if info.Component != model.ComponentOfChatModel { return ctx }
    cb := model.ConvCallbackOutput(out)
    if cb == nil || cb.Message == nil || cb.Message.ResponseMeta == nil || cb.Message.ResponseMeta.Usage == nil { return ctx }
    tenant := ctx.Value("tenantId").(string)
    attrs := metric.WithAttributes(attribute.String("tenant", tenant), attribute.String("model", info.Name))
    h.inHist.Record(ctx, int64(cb.Message.ResponseMeta.Usage.PromptTokens), attrs)
    h.outHist.Record(ctx, int64(cb.Message.ResponseMeta.Usage.CompletionTokens), attrs)
    return ctx
}
func (h *TokenMetricHandler) OnStart(ctx context.Context, _ *callbacks.RunInfo, _ callbacks.CallbackInput) context.Context { return ctx }
// ... implement OnError, OnStartWithStreamInput, OnEndWithStreamOutput (or use NewHandlerBuilder)

callbacks.AppendGlobalHandlers(&TokenMetricHandler{inHist: ..., outHist: ...})
```

---

## 11. Built-in Tools & Tool Authoring API

### 11.1 Built-in tools shipped in the box

**Core repo (`eino`)**: zero shipped tool implementations. The `filesystem` middleware bundles 7 tools but only if you wire it in:

| Tool | Purpose |
|---|---|
| `ls` | List files (`adk/middlewares/filesystem/prompt.go:44`) |
| `read_file` | Read file with offset/limit (Claude-Code-shaped) |
| `write_file` | Create / overwrite file |
| `edit_file` | Anchor-based edit |
| `glob` | Glob match files |
| `grep` | Grep in files |
| `execute` | Shell (configurable: blocking via `Shell`, streaming via `StreamingShell`) |

**`eino-ext` tools** (each its own Go module under `components/tool/`):

| Module | Purpose |
|---|---|
| `mcp` | MCP client (community SDK `mark3labs/mcp-go`) |
| `mcp/officialmcp` | MCP client (official SDK `modelcontextprotocol/go-sdk`) |
| `duckduckgo` | DuckDuckGo search |
| `googlesearch` | Google Search (Custom Search API) |
| `bingsearch` | Bing Search |
| `searxng` | Self-hosted SearxNG search |
| `wikipedia` | Wikipedia lookup |
| `httprequest` | Generic HTTP GET/POST |
| `commandline` | Shell command (similar to Claude Code's `bash`) |
| `browseruse` | Browser automation (chromedp) |
| `sequentialthinking` | Anthropic's "sequential thinking" pattern as a tool |

There is no `Monitor` (stream events from a background process), no `Edit` with rich anchor matching (the filesystem `edit_file` is simpler than Claude Code's), no `Read` with auto-snippet line-numbering. **The catalog is broader by name but shallower by depth than Claude Agent SDK's bundled tools.**

### 11.2 Built-in tool quality

- **Filesystem middleware**: medium. `read_file` supports offset/limit and ships an oversize-result-stash-to-FS pattern (`large_tool_result.go`). `edit_file` does single-anchor string replace. There's no `Edit` analogue with multi-anchor / replace-all / smart whitespace handling.
- **MCP tools**: thin client wrappers around `mcp-go` / `go-sdk`; quality depends on the SDK.
- **Search tools**: thin REST wrappers.

### 11.3 Tool authoring API

The simplest possible tool (`components/tool/utils/invokable_func.go:46-53`):

```go
type GetWeatherInput struct {
    City string `json:"city" jsonschema:"description=City name"`
}
type GetWeatherOutput struct {
    Temp int `json:"temp"`
}

weatherTool, _ := utils.InferTool(
    "get_weather",
    "Get current weather for a city",
    func(ctx context.Context, in *GetWeatherInput) (*GetWeatherOutput, error) {
        return &GetWeatherOutput{Temp: 22}, nil
    },
)
// JSON-schema generation is automatic from struct tags via `eino-contrib/jsonschema`
```

For options-aware tools: `utils.InferOptionableTool`. For manual schema control: `utils.NewTool(toolInfo, fn)`. For full control: implement `tool.InvokableTool` directly.

### 11.4 Typed tool I/O

`utils.InferTool` runtime-validates LLM-generated args by unmarshalling into the typed struct via `sonic`. **Unmarshal errors propagate to the model** as tool errors. There is no Pydantic-level validation (you can layer `go-playground/validator/v10` yourself — Ray does this in `pkg/conversation/`).

### 11.5 Streaming tools

**Yes** — `StreamableTool` returns `*schema.StreamReader[string]` (`components/tool/interface.go:53-57`). The tool can yield chunks; the framework concatenates / forwards them. `EnhancedStreamableTool` does the same for multimodal results.

---

## 12. MCP (Model Context Protocol) Support

### 12.1 MCP client support

**Yes — first-class via two parallel adapters in eino-ext**:

- `components/tool/mcp/` — uses `mark3labs/mcp-go` (community SDK).
- `components/tool/mcp/officialmcp/` — uses `modelcontextprotocol/go-sdk` (official SDK).

Pattern: `mcp.GetTools(ctx, &mcp.Config{Cli: mcpClient, ToolNameList: ["search"]})` returns `[]tool.BaseTool` you append to your `ToolsConfig.Tools`. The tools' JSON schema is auto-translated from MCP `InputSchema` via `jsonschema.Schema` (`components/tool/mcp/mcp.go:80-101`).

### 12.2 MCP server support

**Not provided in eino-ext.** You can expose Eino tools as MCP servers by using `mark3labs/mcp-go`'s server API yourself, but there's no `eino.NewMCPServer` helper.

### 12.3 Transports

Whatever the underlying SDK supports. `mark3labs/mcp-go` supports stdio, SSE, HTTP; the official `go-sdk` supports stdio + Streamable HTTP. In-process / SDK transport: yes (in-process clients are trivial).

### 12.4 In-process MCP

Possible — you create an in-process `client.MCPClient` that bridges directly to a server in your Go code. Not a dedicated Eino API; just normal MCP client usage.

### 12.5 Auth / lifecycle

`Config.CustomHeaders` (`components/tool/mcp/mcp.go:46-47`) lets you pass Bearer tokens or any headers on every MCP call. `Config.Meta` (`mcp.Meta`) lets you pass custom metadata. Reconnection / health / version negotiation are delegated to the underlying SDK. The framework does not wrap them.

Bonus: `components/prompt/mcp/` exposes MCP **prompts** as `prompt.ChatTemplate` you can wire into a `compose.Chain`, so MCP prompt servers become re-usable prompt templates.

---

## 13. Multi-model Routing & Fallback

### 13.1 Multi-provider support

Eleven first-party adapters in eino-ext (`components/model/`):

| Adapter | Provider |
|---|---|
| `openai` | OpenAI (also compatible with Azure OpenAI via OpenAI-compatible endpoint) |
| `claude` | Anthropic Claude |
| `gemini` | Google Gemini (Vertex AI + AI Studio) |
| `ollama` | Ollama (local) |
| `deepseek` | DeepSeek |
| `qwen` | Alibaba Qwen |
| `qianfan` | Baidu Qianfan |
| `ark` | ByteDance Volcengine Ark |
| `arkbot` | ByteDance Ark assistant variant |
| `openrouter` | OpenRouter (LLM proxy) |

Any provider implementing `model.BaseChatModel` / `model.ToolCallingChatModel` can be plugged in. No LiteLLM-style gateway is bundled; OpenRouter or BYO is the workaround.

### 13.2 Per-task model selection

**Not first-party as a router.** Achievable per pattern:
- Different sub-agents with different `Model` (e.g. supervisor on Claude Opus, workers on Claude Haiku) — see Q13.5.
- The `skill` middleware can specify `model: <name>` per skill, fetched from `ModelHub` (`adk/middlewares/skill/skill.go:79-88`) — gives per-skill model selection.
- Inside a single agent, `WrapModel` can swap models per turn based on the current message list.

No central registry / cost router ships.

### 13.3 Automatic fallback chain

**Not provided as model-fallback.** What ships is **`ModelRetryConfig`** (`adk/chatmodel.go:307`) — retries on the *same* model with backoff. To fall back to a different model on outage, you write a `WrapModel` that catches `next.Generate(...)` errors and dispatches to a backup.

### 13.4 Mid-stream model switching

Not within a single LLM call (you can't switch the LLM mid-stream). At turn boundaries: yes, via `WrapModel`. The `skill` middleware's `setActiveModel` (`adk/middlewares/skill/skill.go:414-416`) is a real example of mid-run model switching at a turn boundary.

### 13.5 Sub-agent model overrides

**Yes — first-class.** Each `ChatModelAgentConfig.Model` is independent. So:

```go
supervisor, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "supervisor", Model: claudeOpus, ...,
})
worker, _ := adk.NewChatModelAgent(ctx, &adk.ChatModelAgentConfig{
    Name: "worker", Model: claudeHaiku, ...,
})
adk.SetSubAgents(ctx, supervisor, []adk.Agent{worker})
```

Or via the `supervisor` prebuilt (`adk/prebuilt/supervisor/supervisor.go`).

---

## 14. Chat UI Layer

### 14.1 Streaming chat hook

**Not provided.** Eino is a Go backend. Frontend hooks (React `useChat`, Vue equivalents) are not part of the framework. Your frontend connects to *your* HTTP layer and parses *your* SSE format.

### 14.2 Tool call rendering primitives

**Not provided.**

### 14.3 Generative UI components

**Not provided.**

### 14.4 BYO pattern

Standard. You serialize each `AgentEvent` to JSON over SSE, your React/Vue frontend parses it. Vercel AI SDK protocol is a popular target; nothing in Eino assumes it.

---

## 15. Memory & Knowledge

### 15.1 Long-term memory / semantic recall

**Not built-in.** No `Memory` type, no `MemoryStore`, no auto-recall. You can build cross-session memory by combining `components/retriever` (vector search) + a custom system-message-injection middleware.

### 15.2 RAG / knowledge retrieval integration

**First-class retrieval primitives**:

- `components.retriever.Retriever` interface (`components/retriever/interface.go`)
- `components.indexer.Indexer` interface (`components/indexer/interface.go`)
- `components.embedding.Embedder` interface
- `components.document.{Loader,Parser,Transformer}` interfaces for ingestion
- Eino-ext shipped retriever / indexer adapters: **Qdrant**, **Milvus** (v1, v2), **Redis**, **OpenSearch** (v2, v3), **Elasticsearch** (v7, v8, v9), **Volc VikingDB**, **Dify**, **Volc Knowledge**

Wire pattern via graph:

```go
g := compose.NewGraph[string, string]()
g.AddEmbeddingNode("emb", embedder)
g.AddRetrieverNode("ret", retriever, compose.WithStatePreHandler(...))
g.AddChatModelNode("llm", cm)
// edges: START -> emb -> ret -> llm -> END
```

Or wrap a retriever as a tool the agent can call.

### 15.3 Per-tenant memory scoping

**Not automatic.** The retriever interface's `Retrieve(ctx, query, opts...)` receives ctx, so you pass tenant scope in ctx, and the retriever adapter's `Options.SubIndexes` or query filter respects it. The framework does not enforce — your adapter does.

---

## 16. Safety, Guardrails & Tool Sandboxing

### 16.1 Input/output guardrails

**Not first-party.** PII redaction, prompt-injection detection, hallucination detection: BYO. Write a `ChatModelAgentMiddleware` that runs a regex / classifier / LLM-judge over input and output messages.

### 16.2 Tool sandboxing / permission model

- **Allow/deny lists**: BYO via `BeforeAgent` middleware filtering `runCtx.Tools` (see Q4.5).
- **`canUseTool`-style hook**: closest analogue is `WrapInvokableToolCall` returning an error from the wrapper to deny a call.
- **Per-tool ACL**: BYO.

There is no built-in tool-execution sandbox (chroot, container, V8 isolate). Tools run with the same OS permissions as your Go process.

### 16.3 Sandbox provider integrations

eino-ext ships two `filesystem.Backend` implementations under `adk/backend/`:

- **`adk/backend/agentkit/`** (`frameworks/eino-ext/adk/backend/agentkit/`) — a sandboxed-Python-runtime backend (Docker-shelled Python interpreter executing `read_file` / `write_file` / `edit_file` / `glob` / `grep` via base64-encoded Python templates, `code_template.go`). This is the filesystem analog of E2B / Daytona, but only for the filesystem middleware's needs.
- **`adk/backend/local/`** (`frameworks/eino-ext/adk/backend/local/local.go`) — a local-filesystem backend with **multi-modal read for images and PDFs** (added May 14 2026 in commit `176d453`, "feat(agentkit/local): add MultiModalRead for images and PDFs"). Uses `go-fitz` for PDF page rendering at configurable DPI; bounded by `defaultMaxImageSizeMB=10`, `defaultMaxPDFSizeMB=20`, `defaultMaxPagedPDFSizeMB=100`, `defaultMaxPDFPagesPerRequest=20`. This is the closest in-tree analog of Claude Code's multi-modal `Read` for PDFs/screenshots.

No E2B / Daytona / Modal / code-interpreter direct integration.

### 16.4 Default-deny vs. default-allow

**Default-allow.** All registered tools are visible to the LLM unless you explicitly filter them. The skill middleware enumerates all available skills by default. No "you must call `agent.allowTool('X')` before the LLM can use it" gate.

---

## 17. Eval, Testing & CI Gates

### 17.1 Golden datasets / regression suites

**Not provided — BYO.** No `Dataset`, no `Evaluator`, no `EvalRun`. Roll your own with Go's `testing` package + recorded `model.BaseChatModel` mocks.

### 17.2 LLM-as-judge scoring

**Not provided — BYO.** Write a function that calls an LLM with a rubric prompt over the agent's output. Eino itself does not ship a judge framework.

### 17.3 CI eval gates / pre-merge

**Not provided.** What you can do: in CI, run the agent against a fixture set, assert outputs match expected (or judge-score above a threshold), block PR on failure.

### 17.4 Trace replay for skill iteration

**Not provided locally.** Traces in Langfuse / LangSmith / APMPlus give you remote viewing; there is no local trace viewer / step-through TUI.

---

## 18. Local Sandbox & Dev UX

### 18.1 Local agent runner

**Not first-party.** No `eino dev` CLI, no playground, no TUI. The CloudWeGo team ships a **DevOps tooling** suite that includes an IDE plugin + visual orchestration plugin + visual debug plugin (referenced in `llms.txt`):

- [IDE plugin guide](https://www.cloudwego.io/docs/eino/core_modules/devops/ide_plugin_guide/)
- [Visual orchestration plugin](https://www.cloudwego.io/docs/eino/core_modules/devops/visual_orchestration_plugin_guide/)
- [Visual debug plugin](https://www.cloudwego.io/docs/eino/core_modules/devops/visual_debug_plugin_guide/)

These plugins are JetBrains/IntelliJ-targeted (the docs assume IntelliJ) and primarily Chinese-documented. There is no web-based playground equivalent to Mastra's or LangGraph's.

### 18.2 Trace inspection

Local: none built-in. Remote: Langfuse / LangSmith / APMPlus / CozeLoop dashboards.

### 18.3 Tenant / org switching

**Not provided** (there's no local sandbox to switch in).

### 18.4 Hot reload

For Go code: standard Go tooling (`air`, `reflex`). For SKILL.md: the filesystem `Backend` re-reads files on every `List` / `Get`, so editing a SKILL.md and re-running picks up changes without restart. Same for any custom `Backend` you write.

---

## Architectural diagram

```mermaid
flowchart TB
    subgraph host[Your Go process]
        api[Your HTTP/SSE layer<br/>auth, tenant routing] --> runner
        runner[adk.Runner] --> agent[adk.ChatModelAgent<br/>ReAct loop]
        runner --> wagent[adk.WorkflowAgent<br/>Seq/Par/Loop]
        runner --> sub[adk.AgentTool<br/>agents-as-tools]
        agent --> graph[compose.Graph<br/>Init → ChatModel → ToolNode]
        wagent --> graph
        graph --> tools[components/tool<br/>InvokableTool /<br/>StreamableTool /<br/>EnhancedInvokableTool]
        graph --> model[components/model<br/>BaseChatModel /<br/>ToolCallingChatModel]
        graph --> retriever[components/retriever]

        subgraph hooks[Hooks & middleware]
            cb[callbacks.Handler<br/>OnStart/OnEnd/OnError/Stream]
            am[AgentMiddleware<br/>struct, deprecated]
            cmm[ChatModelAgentMiddleware<br/>interface, recommended]
            tm[compose.ToolMiddleware<br/>graph-level wrap]
        end
        agent -.uses.-> cmm
        agent -.uses.-> am
        graph -.fires.-> cb
        graph -.uses.-> tm

        subgraph mw[Shipped middlewares]
            skill[skill/<br/>SKILL.md loader]
            fs[filesystem/<br/>7 file tools]
            ts[dynamictool/toolsearch/<br/>regex tool_search]
            sum[summarization/<br/>auto-compact]
            red[reduction/<br/>tool-result truncation]
            pt[plantask/]
            ptc[patchtoolcalls/]
        end
        cmm -.implements.-> skill
        cmm -.implements.-> ts
        cmm -.implements.-> sum
        cmm -.implements.-> red
        agent -.composes.-> mw

        runner --> store[CheckPointStore<br/>interface only — BYO]
    end

    model -.HTTPS.-> openai[(OpenAI)]
    model -.HTTPS.-> anthropic[(Anthropic)]
    model -.HTTPS.-> vertex[(Vertex)]
    model -.HTTPS.-> ark[(ByteDance Ark)]
    model -.local.-> ollama[(Ollama)]

    tools -.HTTPS.-> mcp[(MCP servers<br/>via eino-ext mcp/officialmcp)]
    retriever -.network.-> vec[(Qdrant / Milvus /<br/>Redis / ES / OpenSearch)]

    cb -.via eino-ext.-> lf[(Langfuse)]
    cb -.via eino-ext.-> ls[(LangSmith)]
    cb -.via eino-ext.-> apm[(APMPlus / OTel)]

    store -.YOU build.-> pg[(Postgres / Redis / S3)]
```

---

## Appendix — Files worth reading first

For an engineer diving in, read these in order:

1. **`adk/interface.go`** — `Agent`, `AgentEvent`, `AgentInput`, `AgentAction`, `ResumableAgent` definitions. The ADK's vocabulary in one file.
2. **`adk/chatmodel.go`** (lines 195–311, 880–995) — `ChatModelAgentConfig` documenting the *entire* middleware execution order (the long comment at 250–303 is the canonical reference) and how `Run` / `Resume` actually dispatch.
3. **`adk/react.go`** (lines 302–437) — the compiled `compose.Graph` that *is* the ReAct loop. Three nodes; this is "what is actually executing".
4. **`adk/runner.go`** — top-level entrypoint, `Run` / `Query` / `Resume` / `ResumeWithParams` semantics; where checkpoints fire (lines 189–247).
5. **`adk/interrupt.go`** — the full Interrupt + CompositeInterrupt model with addresses; the serialization payload structure.
6. **`adk/handler.go`** — `ChatModelAgentMiddleware` interface (the 8 methods), `BaseChatModelAgentMiddleware` (no-op base), `SetRunLocalValue` / `GetRunLocalValue`, `SendEvent`.
7. **`adk/workflow.go`** (lines 427–551, 599–612) — `Parallel`, `Sequential`, `Loop` constructors and the actual `sync.WaitGroup` fan-out implementation.
8. **`adk/agent_tool.go`** — agents-as-tools, the bridge pattern that links the sub-iterator to the parent (and where the interrupt forwarding lives).
9. **`adk/middlewares/skill/skill.go`** — SKILL.md loader, frontmatter schema, fork / fork-with-context / inline modes, `Backend` / `AgentHub` / `ModelHub` interfaces.
10. **`adk/middlewares/dynamictool/toolsearch/toolsearch.go`** — `tool_search` meta-tool implementation, dynamic tool filtering via `WrapModel`.
11. **`compose/checkpoint.go`** — `CheckPointStore` + serializer abstractions; how interrupt state gets persisted.
12. **`internal/core/interrupt.go`** — `InterruptSignal`, `Address`, `InterruptCtx` underlying types (the public ones are type-aliased in `adk/interrupt.go`).
13. **`compose/tool_node.go`** — `ToolsNode`, `ToolsNodeConfig`, the `ToolMiddleware` and tool call endpoints / wrappers. The parallel-by-default dispatch + middleware chain lives here.
14. **`schema/message.go`** — `Message`, `ToolCall`, `ResponseMeta`, `TokenUsage` definitions.
15. **`llms.txt`** — the index of all official documentation URLs (English) — handy for context-jumping.
