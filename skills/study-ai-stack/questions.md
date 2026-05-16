### Q0 — Architectural Overview & Deployment Model

**Why this is first**: stacks differ wildly at this layer and downstream questions depend on it. A library that runs in your process is fundamentally different from a wrapper that subprocesses a vendor binary, which is fundamentally different from a hosted REST service.

Answer:

- **0.1 What is this stack?** Library, framework, server, vendor-managed service, or hybrid? One sentence.
- **0.2 Where does the agent loop *actually* execute?** In your process, in a bundled subprocess, in a sister-repo server, in a vendor cloud? *This is the single most important architectural fact about the stack.* Be explicit. (Example: "The Python SDK is a ~10 kLOC wrapper around the Claude Code Node.js binary, which it subprocesses over stdio JSON-RPC; the actual loop runs in Node, not Python.")
- **0.3 Runtime dependencies** — what does a host need to run one instance? (Python 3.X, Node 18+, Go 1.X, bundled binaries, native libs, optional Postgres / Redis, optional vendor services like LangSmith, etc.)
- **0.4 Recommended deployment topology** — does the vendor recommend container-per-tenant, one-process-many-tenants, or worker-pool? Quote any vendor hosting doc.
- **0.5 Cold-start cost & instance footprint** — startup latency, RAM baseline, disk baseline. (E.g. Claude Agent SDK's open issue #333: 20–30 s startup per instance.)
- **0.6 Vendor lock-in** — LLM-provider lock-in, hosting-platform lock-in, eval-platform lock-in. Score each independently.
- **0.7 Framework weight / footprint** — thin SDK (a few hundred LOC of glue) vs. heavy framework (bundles storage, eval, dev UI, plugin system).
- **0.8 Documentation depth & cross-team contributor accessibility** — official docs language(s)? Pages thin or deep? Can a non-engineer (Product/Data) author content without engineering hand-holding?
- **0.9 Documentation entry points** ⭐ — list **real URLs** the reader can click. Required:
  - Official docs landing page
  - Quickstart / getting-started
  - API reference
  - Hosting / deployment / production guide (if separate)
  - Examples / demos repo
  - Changelog
  - GitHub issues tracker (and link to any open issues that matter for our use case, e.g. multi-tenant / scaling / cost / HITL)
  - Discord / community forum (if active)

⭐ **Required**: produce a **deployment diagram** (ASCII or mermaid) showing what runs where (caller process ↔ subprocess(es) ↔ vendor cloud ↔ data stores). This goes at the top of Section 0 in the report.

---

### Q1 — Agent Harness (Run Loop) & Message Taxonomy

The core loop *plus* the message/event taxonomy it produces. The loop and its messages are tightly coupled — what the loop yields, when, and in what type *is* the harness's public contract. Runtime concerns (concurrent isolation, scaling) belong in Q2. Sessions & persistence belong in Q3. Network exposure (interrupt, HITL, streaming protocol) belongs in Q6. Built-in tools, MCP, and multi-model routing live in Q11–Q13.

#### Run loop

- **1.1 Run loop entrypoint(s)** — signature, inputs, outputs (return type / yielded type). Show the type.
- **1.2 Per-iteration behavior** — what happens in one trip around the loop? (call LLM → parse tool calls → permission gate → dispatch → collect result → next call)
- **1.3 ReAct loop** — does the stack ship a built-in ReAct loop, or do you assemble one yourself?
- **1.4 Tool dispatch + result handling** — how does the harness route LLM-generated tool calls to executors and feed results back?
- **1.5 Explicit turn concept** — what defines a turn boundary? (Single LLM call? Until no more tool calls? Until result message?)
- **1.6 Event emission mechanism (in-process)** — async generator / EventEmitter / callback / typed stream? Show the code path. (Network-side streaming is Q6.4–6.5.)

#### Message & event taxonomy

The reader wants to understand the *layers* of messages and events — what crosses the wire, what crosses internal boundaries, what's surfaced to the UI, what's emitted as a transient event.

- **1.7 Message layers** — how many distinct message vocabularies exist? (e.g. wire / UI / internal LLM message). Diagram the conversions.
- **1.8 Concrete message types** — table of every type with 1-line purpose.
- **1.9 Messages vs. events** — are they the same iterator, or two separate taxonomies?
- **1.10 Event categories** — stream-event, turn-event, message-event, tool-event, session-lifecycle event, hook event, sub-agent event. Which exist, and what defines each category?
- **1.11 Canonical type-definition file(s)** — cite the source of truth.
- **1.12 Live agentic event stream taxonomy** — what concrete event types stream to the consumer? Sample one frame of each major category.

---

### Q2 — Agent Runtime (Multi-session Host)

The runtime is the layer *around* the loop that hosts many concurrent sessions, scales horizontally, and runs background work. Session shape / persistence is Q3.

Answer:

- **2.1 Multi-session host architecture** — does the stack ship a runtime that hosts N concurrent sessions in one process? Or is "runtime" = "you embed the loop in your own server"?
- **2.2 Concurrent session isolation** — many sessions in one process — is state isolated, or can it bleed? Where is isolation enforced?
- **2.3 Horizontal scaling / multi-instance** — stateless workers? Leader election? Shared store? Can N pods serve the same session pool with shared state?
- **2.4 Background / async / scheduled tasks** — cron, webhook triggers, long-running background agents — first-party or BYO?
- **2.5 Worker pool / queue model** — does the runtime expose a queue (e.g. for long-running agent work), or does it assume short-lived HTTP request scope?

---

### Q3 — Sessions & Persistence

Sessions are where the agent's memory of "this conversation" lives. This question is about the *data model* and the *storage* — the shape of a session/chat, what data it contains, and what stores the SDK ships.

Answer:

- **3.1 Session / chat data model** — what fields exist on a session? Show the type / struct / schema definition. Examples to look for: `id`, `messages`, `tools`, `cwd`, `tenant_id`, `user_id`, `created_at`, `updated_at`, `parent_session_id`, `metadata`, `usage`, `model`, `summary`, …
- **3.2 What's stored on a session** — messages? tool-call history? scratchpad files? embedded memory? attachments? Cite the schema.
- **3.3 Granularity** — single conversation per session? thread/branch model? Can a session fork (LangGraph-style)?
- **3.4 Built-in persistence stores** — what does the SDK ship out-of-box? Possibilities: JSONL on local disk (`~/.claude/projects/<cwd>/<sid>.jsonl` style), SQLite, Postgres (which adapter? `bun`, `pgx`, SQLAlchemy?), Redis, S3, Anthropic-hosted, Mastra Cloud, Vercel Blob, vendor cloud, or **none — BYO**.
- **3.5 Persistence timing** — at what exact moment in the loop are messages persisted? Per token? Per assistant message? Per turn end? After every tool result? Sync vs. async (e.g. LangGraph's `durability="sync"` vs `"async"`, Mastra's debounced batch)?
- **3.6 Mid-run checkpointing (durable)** — can a run resume after crash *mid-tool-call*? Where does the checkpoint actually fire in the code path? (LangGraph's `_runner.commit() → put_writes()` per-task is the gold standard.)
- **3.7 Session ID format** — UUID? Tenant-prefixed? Hash-based? Composite (e.g. `project:session:subpath`)?
- **3.8 Pluggable store interface** — can you plug in your own store (custom DB)? Show the interface (`SessionStore`, `BaseCheckpointer`, …).
- **3.9 Schema evolution / migration** — how does the SDK handle schema changes between versions? Migration helpers shipped, or hand-roll?
- **3.10 Export / replay** — can a session be exported (JSON / JSONL) and deterministically replayed for debugging / eval?
- **3.11 Cross-session memory** — different from in-session messages. Brief note + cross-reference to Q15 (Memory & Knowledge).

---

### Q4 — Multi-tenancy & Arbitrary Context ⭐ THE KEY QUESTION

The audience runs a multi-tenant long-running agent piloted by skills. They need to (a) pass `tenantId` / `userId` / `targetingStrategyId` / `locale` etc. into the harness, (b) use that context to **filter** which tools/skills the LLM can see, and (c) **force** specific tool arguments from the harness — *not* trust the LLM to fill them in. The LLM could hallucinate or be prompt-injected into using the wrong tenant id.

Answer:

- **4.1 Full run-loop input struct** — every field beyond `messages`. Show the type.
- **4.2 Context propagation into a tool call** — how does harness-provided context reach `tool.execute(...)`? Show the call path.
- **4.3 Tool call interface** — `execute` / handler signature: arguments, return type, the context object. Show real code.
- **4.4 Forcing tool arguments from the harness** — can you say "for tool `topicSearch`, always pass `tenantId=acme-corp` regardless of what the LLM generates"? Show the mechanism (e.g. `PreToolUse → updatedInput`, `experimental_refineToolInput`, `_inject_tool_args`, typed `spec T`). If the stack lacks this, say so plainly — it's a real gap.
- **4.5 Filtering visible tools** — can the harness change the toolset visible to the LLM at session-start or per-turn based on context? Show the mechanism (`activeTools`, `allowed_tools`, `prepareStep`, …).
- **4.6 Tenant scope on session** — is tenant identity a first-class field on the session, or stuffed in metadata?
- **4.7 Per-tool-call auth propagation** — does the caller's identity reach every tool call automatically (so tools execute under their permissions)?
- **4.8 Resource scoping primitives** — can skills / sub-agents / tools be scoped global/tenant/user at registration time, or only filtered at runtime?
- **4.9 Per-tenant rate limit + budget cap** — token/cost ceilings enforced per tenant. (Most stacks lack this; only flag 🟢 if you find a USD budget cap, not just turn caps.)

⭐ **Required — light usage example** (5–15 lines). Show how to:
1. Pass `tenantId="acme"`, `targetingStrategyId="strat-42"`, `userId="u-123"` into the run-loop call.
2. Make only the tools `topicSearch`, `iabSearch`, `audienceCreate` visible (skip `bashExec`, `webFetch`).
3. Force every `topicSearch` call to receive `tenantId="acme"` server-side, even if the LLM tries to pass a different value.

If any of the three is impossible in this stack, say "Step N: Not provided — BYO" and explain the closest workaround in 1–2 lines.

---

### Q5 — Hook & Middleware Capabilities (Context Engineering)

Hooks/middleware are how engineering teams extend behavior without forking. This section also covers the *context-engineering* concerns that hooks typically enable (compaction, cache breakpoints, tool result clearing).

Answer:

- **5.1 Enumerate every hook / middleware / lifecycle callback** — table form: name → fires when → can do what (read / mutate / block / branch).
- **5.2 Hook concurrency model** — do matchers fire in sequence, in parallel, with a fold?
- **5.3 Specific capability tests** — for each, say yes/no with code:
  - inject system messages at session start (e.g. "current date is 2026-05-16, tenant is acme, locale fr-FR")
  - expand the user input (slash commands, time-stamp, attachments)
  - mutate the messages list before each LLM call (e.g. prompt-cache breakpoints, redaction)
  - mutate / decorate tool input before dispatch (e.g. inject `tenantId` server-side — see Q4.4)
  - mutate / decorate tool result before it returns to the LLM (e.g. redact, summarize, truncate)
  - **emit additional tool calls in response to a tool result** (Claude Agent SDK supports this via `additional_messages` from `PostToolUse` — does this stack?)
- **5.4 Auto-compaction** — built-in summarization/truncation, or BYO? When does it trigger?
- **5.5 Prompt cache optimization** — provider-cache-aware (Anthropic, OpenAI)? Stable-prefix preservation, breakpoint placement, automatic vs. manual?
- **5.6 Tool result clearing / progressive disclosure** — strategies to keep large tool outputs out of the main context (filesystem stash, summary, on-demand re-read).
- **5.7 Architectural diagram** of where hooks fire across the loop (ASCII or mermaid).

⭐ **Required — light usage example** (5–15 lines). Show:
1. A `SessionStart` hook that injects "tenant=acme, locale=fr-FR, today=2026-05-16" as a system message.
2. A `PreToolUse` hook on `topicSearch` that adds a `tenantId` field server-side (the same forced-args pattern from Q4.4).
3. A `PostToolUse` hook that, when `topicSearch` returns more than 50 results, summarizes them in place.

---

### Q6 — Agent API Exposition (HTTP/network surface)

Some stacks ship a server; some are library-only and the host owns the HTTP layer. Be precise. This question covers everything observable from outside the process — including interrupt, HITL approval, and tool-arg streaming, since those are *features of the API surface* even when the underlying mechanism lives in the loop.

Answer:

- **6.1 Does the stack ship an HTTP/network server?** Or library-only?
- **6.2 Streaming transport** — SSE? WebSocket? HTTP long-poll? Proprietary stream format?
- **6.3 Endpoints that start an agent run** — request shape (body, headers, query). Show one.
- **6.4 Live agentic event stream format** — sample frames: start, mid-stream, terminal. Show the wire format.
- **6.5 Auth termination at API boundary** — does the SDK terminate auth (JWT validation, tenant scoping), or leave it to the host?
- **6.6 Resume / replay endpoint** — how does a client reopen a session (user reopens a tab) or replay agent events?
- **6.7 Interrupt / cancel via API** — DELETE? AbortSignal over the same connection? Close-stream-and-call-cancel?
- **6.8 Tool-arg streaming (partial JSON)** — does the API expose tool arguments as they generate (before the LLM finishes the call)? What's the frame shape?
- **6.9 HITL approval workflow** — how does a client send a tool-approval / rejection verdict? Same endpoint? Different one? Payload shape? Is there a pause state observable to the client?
- **6.10 Tool-call state reconstruction** — ⭐ critical. How does the client link `tool_use` and `tool_result` events from the stream? Explicit `tool_call_id`, or implicit/positional? Show the event types and the linkage mechanism.
- **6.11 Health checks / graceful shutdown** — `/healthz`, `/readyz`, `/metrics`, SIGTERM drain?

⭐ **Required — light usage example** (5–15 lines). Show:
1. A `curl` or `httpie` call to start a run with `X-Tenant-Id: acme` header and a user message.
2. 3–5 lines of the SSE stream the client would receive (start frame, one tool-use frame, terminal frame).
3. A `curl` call to cancel the run mid-flight.
4. A `curl` call to send a HITL approval verdict for a paused tool call.

---

### Q7 — Sub-agents

Answer:

- **7.1 Mechanism** — are sub-agents invoked as a *special tool* (agents-as-tools), as a first-class primitive, or both?
- **7.2 Configuration** — markdown file? struct registered at boot? object inlined per call? runtime-generated by the parent LLM?
- **7.3 LLM-generated configs** — can the parent LLM generate a sub-agent config on the fly with custom system prompt / tools, or must configs be statically registered?
- **7.4 Output handling** — how does the parent receive sub-agent output? Single result string? Streaming events? Structured object? Linked back to a parent `tool_use_id`?
- **7.5 Concurrency model** — serial, parallel, fan-out? Where in the code is parallelism actually implemented (the line that does the `Promise.all` / `sync.WaitGroup` / etc.)?
- **7.6 Context isolation** — does the sub-agent see the parent's context or start fresh? Where is this enforced?
- **7.7 Lifecycle events** — does the parent stream get sub-agent lifecycle events (started, progress, completed)?

⭐ **Required — light usage example** (5–15 lines). Show:
1. Defining 3 persona sub-agents (`persona-young-mom`, `persona-tech-bro`, `persona-retiree`), each with its own system prompt and a `topicSearch` tool.
2. The parent agent invoking them in parallel.
3. Where the parent receives each result.

---

### Q8 — Skills

"Skill" specifically means a markdown file (à la Claude Code's `SKILL.md`) describing a workflow, loaded on-demand to extend the agent — not a "capability" in the loose sense. If the stack doesn't have this concept, say so plainly. Resource-Manager concerns (versioning, publishing, governance, loading from external sources) belong in Q9.

Answer:

- **8.1 First-class concept?** Or community/convention pattern? Or absent entirely?
- **8.2 File format** — `SKILL.md` with YAML frontmatter? Show the schema (fields, types, validators).
- **8.3 Loader mechanism** — filesystem scan? Programmatic registration via SDK call? Plugin system?
- **8.4 Invocation** — is invoking a skill a *tool call*, a *system-prompt injection*, or a third mechanism (e.g. lazy fetch via a `skill_read` tool)?
- **8.5 Loading mode** — eager (all skills in system prompt) or lazy (metadata-only in prompt, body fetched on use)?
- **8.6 Runtime scoping (global / tenant / user)** — can the same agent surface a different skill catalog per tenant *at runtime*? Show the filter mechanism. (Registry-side scoping is Q9.5.)
- **8.7 Skill composition** — can a skill reference / include other skills, or call sub-agents, or pull in references/scripts/assets bundled alongside the `SKILL.md`?

⭐ **Required — light usage example** (10–20 lines). Show:
1. Authoring a `SKILL.md` titled "Generate-Audience-From-Brief" with frontmatter.
2. Loading it at runtime (filesystem path, registry id, or programmatic registration call).
3. The agent discovering and invoking it (show whether the LLM sees a tool, a system-prompt fragment, or a special hook).

---

### Q9 — Resource Manager

The Resource Manager is the *platform* layer that manages many skills, sub-agents, prompts, and tools across teams: where they're stored, how they're versioned, who can publish, and what scope they go live in. Skills-as-a-format is Q8; this is "how do we run a multi-tenant skill library".

Answer:

- **9.1 First-class Resource Manager?** Does the stack ship one (registry, source abstraction, publishing workflow), or is it BYO?
- **9.2 Loading sources** — where can resources LOAD FROM? List every supported source with how it's configured:
  - **Local filesystem** (`./skills/`, `~/.claude/skills/`, `.mastra/`)
  - **Git / GitHub repos** (sparse-checkout, `git+https://`, GitHub raw URLs, Git submodules)
  - **OCI / container registries** (skill bundles as OCI artifacts)
  - **Cloud object storage** (S3, GCS, Azure Blob, Cloudflare R2, Vercel Blob)
  - **Postgres / relational DB** (rows-as-resources, `langgraph_store`-style)
  - **Vendor cloud / managed registry** (LangSmith Hub, Mastra Cloud, Anthropic Hub, AMP Agent Repositories)
  - **HTTP fetch** (arbitrary HTTPS URL with caching)
- **9.3 Source composition / priority** — can multiple sources stack (e.g. `local > tenant-bucket > global-registry`)? What wins on conflict?
- **9.4 Versioning model** — semver? content-hash? immutable refs? rollback support?
- **9.5 Scoping at the registry layer** — can a resource be marked "tenant X only" / "user Y only" at *publish time*, not just filtered at *runtime* (Q8.6)?
- **9.6 Publishing workflow** — draft → review → publish → promote? Multi-environment (dev / staging / prod)? Approval gates?
- **9.7 Lifecycle / governance** — lifecycle states (draft, active, deprecated, retired)? RBAC on who can publish/scope/retire?
- **9.8 Programmatic API** — list / search / sync / pin resources from code? Show the API.
- **9.9 Caching & sync model** — does the SDK pull resources on each request, cache locally, watch for changes, sync periodically?

⭐ **Required — light usage example** (8–15 lines). Show:
1. Registering a `git+https://github.com/dailymotion/predict-skills` source AND a `s3://predict-skills/tenants/acme/` source, with the S3 source winning for tenant `acme`.
2. Promoting a skill from draft → active for tenant `acme` only.
3. Listing all active skills visible to a request with `tenantId=acme`.

---

### Q10 — Observability: Usage, Cost, Tracing, Audit

Answer:

- **10.1 Where tokens are surfaced** — on the result object? On every assistant message? Via events? Via a hook?
- **10.2 Per-call / per-turn / per-session / per-tenant rollups** — what aggregation levels does the SDK expose?
- **10.3 USD cost computation** — does the SDK compute cost in dollars, or only tokens?
- **10.4 Per-tenant / per-conversation cost** — first-party rollup, or BYO via metadata-tagged tracing?
- **10.5 LLM / tool tracing** — OTel built-in? First-party tracer? LangSmith / LangFuse / 25+ exporters?
- **10.6 Audit logging (who / when / what)** — distinct from tracing. Tamper-evident? Hook event stream with a BYO sink?
- **10.7 Canonical "where do I read token counts" code path** — file:line, show the type.

⭐ **Required — light usage example** (5–15 lines). Show:
1. Reading `tokens_in` / `tokens_out` / `cost_usd` for one completed run.
2. Hooking to push per-tenant token usage to a metric sink (Datadog, OTel — pseudocode is fine).

---

### Q11 — Built-in Tools & Tool Authoring API

Answer:

- **11.1 Built-in tools shipped in the box** — web search, file ops (read/write/edit), code exec, fetch, glob, grep, bash, monitor? List the catalog with a one-line purpose each.
- **11.2 Built-in tool quality** — are they thin wrappers or do they encode patterns (e.g. Claude Code's `Edit` with anchor matching, `Read` with line numbers, `Monitor` with line-event streaming)?
- **11.3 Tool authoring API** — what does a developer write to add a new tool? Show the smallest possible tool definition (signature, JSON-schema generation, dispatch).
- **11.4 Typed tool I/O** — runtime validation of LLM-generated args (Zod / Pydantic / JSON-schema)? What happens on invalid args?
- **11.5 Streaming tools** — can a tool yield partial results to the model mid-execution (e.g. progress events)?

---

### Q12 — MCP (Model Context Protocol) Support

Answer:

- **12.1 MCP client support** — can the stack consume external MCP servers (Playwright, GitHub, etc.)? First-class or plugin?
- **12.2 MCP server support** — can the stack expose its own tools as an MCP server for other agents/clients to consume?
- **12.3 Transports** — stdio, SSE, HTTP, in-process/SDK transport?
- **12.4 In-process MCP** — can you define a Python/TS function and surface it as a tool via the MCP machinery without spawning a subprocess?
- **12.5 Auth / lifecycle** — how are credentials passed to remote MCP servers? Reconnection, health, version negotiation?

---

### Q13 — Multi-model Routing & Fallback

Answer:

- **13.1 Multi-provider support** — Anthropic, OpenAI, Gemini, Bedrock, Vertex, Azure, LiteLLM / AnyLLM adapters? Native or third-party?
- **13.2 Per-task model selection** — cheap-for-triage / expensive-for-hard-tasks routing — first-party (registry / gateway) or BYO?
- **13.3 Automatic fallback chain** — when a provider has an outage or rate-limits, does the SDK retry on a fallback model? Show the config.
- **13.4 Mid-stream model switching** — can you switch model at a turn boundary, or only at session start?
- **13.5 Sub-agent model overrides** — can a sub-agent run on a different model than the parent (e.g. Sonnet supervisor + Haiku workers)?

---

### Q14 — Chat UI Layer

Most backend-focused SDKs leave this to the host; some (Vercel AI SDK, Mastra, LangGraph) ship first-party frontend primitives.

Answer:

- **14.1 Streaming chat hook** — first-party frontend hook (e.g. React `useChat`) that handles message streaming, history, chat state?
- **14.2 Tool call rendering primitives** — frontend primitives for rendering which tool is running, with what args, returning what result.
- **14.3 Generative UI components** — first-party support for rendering rich UI artifacts the agent generates (forms, cards, charts).
- **14.4 BYO pattern** — if no first-party UI, what's the recommended pattern? (parse the SSE stream into your own React state, etc.)

---

### Q15 — Memory & Knowledge

Answer:

- **15.1 Long-term memory / semantic recall** — persistent memory across sessions (facts about user/tenant the agent recalls on future turns). Typically vector-search-backed.
- **15.2 RAG / knowledge retrieval integration** — first-party retrieval primitives (vector-store integration, chunkers, retrievers, citations)?
- **15.3 Per-tenant memory scoping** — is memory naturally scoped per-tenant or do you need to namespace yourself?

---

### Q16 — Safety, Guardrails & Tool Sandboxing

Answer:

- **16.1 Input/output guardrails** — PII redaction, prompt-injection detection, hallucination detection — first-party or BYO?
- **16.2 Tool sandboxing / permission model** — allow/deny lists, `canUseTool`-style hooks, per-tool ACL.
- **16.3 Sandbox provider integrations** — E2B, Daytona, Modal, code interpreters?
- **16.4 Default-deny vs. default-allow** — what's the default posture?

---

### Q17 — Eval, Testing & CI Gates

Answer:

- **17.1 Golden datasets / regression suites** — pre-built dataset format + harness for regression-testing agent behavior across model/prompt/skill changes.
- **17.2 LLM-as-judge scoring** — first-party support for using an LLM to grade agent outputs against a rubric.
- **17.3 CI eval gates / pre-merge** — pre-merge eval gates so behavior changes don't ship blind.
- **17.4 Trace replay for skill iteration** — local viewer to step through past traces.

---

### Q18 — Local Sandbox & Dev UX

Answer:

- **18.1 Local agent runner** — CLI, playground, TUI, or web dev UI to run agent sessions on your laptop without deploying.
- **18.2 Trace inspection** — local viewer for past traces.
- **18.3 Tenant / org switching** — can the local sandbox switch between tenant contexts to test tenant-scoped behavior?
- **18.4 Hot reload** — change a skill / prompt and see results without restart?

---

