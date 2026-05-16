### Q0 — General

**Why this is first**: a quick project profile so the reader knows who owns the stack, how mature it is, and which ecosystem they're committing to before drilling into architecture.

Answer:

- **0.1 What is this stack?** One-sentence label: library, framework, server, vendor-managed service, hybrid.
- **0.2 Ecosystem** — primary implementation language. **Must be one of: Python, TypeScript, Go, Rust.** If the project is multi-language (e.g. Python + .NET), name the primary one and call out the other(s) on a second line. This is a hard constraint — a stack that is *not* in one of these four ecosystems should not be in the benchmark.
- **0.3 Project status & governance** — open-source under what license? Who owns/maintains it (company, foundation, individual maintainers, research group)? Is there commercial backing, paid support, managed cloud, enterprise support, or only community support?
- **0.4 Project maturity / age** — initial public release date or first meaningful commit, current major version, stability signals, and whether APIs are marked experimental/beta/stable. If exact age is hard to determine, cite the oldest release/tag or earliest repo commit found.
- **0.5 Adoption & community signal** — GitHub stars, forks, watchers, contributor count, recent commit activity, release cadence, issue/PR volume, and whether maintainers actively answer issues. Include the date these GitHub numbers were captured.
- **0.6 Ecosystem fit** — package name(s), registry links (npm, PyPI, Go module, crates.io), package download signal if easy to verify, official examples/templates, and whether the framework is used mostly as a library, hosted platform, CLI, or app framework.
- **0.7 Documentation depth & cross-team contributor accessibility** — official docs language(s)? Pages thin or deep? Can a non-engineer (Product/Data) author content without engineering hand-holding?
- **0.8 Documentation entry points** ⭐ — list **real URLs** the reader can click. Required:
  - Official docs landing page
  - Quickstart / getting-started
  - API reference
  - Hosting / deployment / production guide (if separate)
  - Examples / demos repo
  - Changelog / release notes
  - GitHub Releases
  - GitHub issues tracker (and any open issue relevant to the benchmark)
  - Discord / community forum (if active)

---

### Q1 — High Level Architecture

The technical architecture layer: where the loop runs, what the host needs, what the recommended deployment looks like, what cold-start costs you pay, and how locked in you are. Downstream questions depend on this — a library that runs in your process is fundamentally different from a wrapper that subprocesses a vendor binary, which is fundamentally different from a hosted REST service.

⭐ **Required**: produce a **deployment diagram** (ASCII or mermaid) showing what runs where (caller process ↔ subprocess(es) ↔ vendor cloud ↔ data stores). This goes at the top of Section 1 in the report.

Answer:

- **1.1 Where does the agent loop *actually* execute?** In your process, in a bundled subprocess, in a sister-repo server, in a vendor cloud? *This is the single most important architectural fact about the stack.* Be explicit. (Example: "The Python SDK is a ~10 kLOC wrapper around the Claude Code Node.js binary, which it subprocesses over stdio JSON-RPC; the actual loop runs in Node, not Python.")
- **1.2 Runtime dependencies** — at a **high level**, what external runtimes, binaries, services, or infrastructure does a host need to run one instance? Think language runtime version (Python 3.X, Node 18+, Go 1.X), bundled external binaries or CLIs the stack subprocesses (e.g. Claude Code CLI, `ffmpeg`), required infrastructure services (Postgres, Redis, a specific cloud server, a vector DB), and required vendor services (LangSmith, Anthropic API, OpenAI API). **Do NOT list package/library dependencies** (npm/PyPI/Go modules) — those are not the point of this question. Focus on what makes the deployment story heavier or lighter.
- **1.3 Recommended deployment topology** — does the vendor recommend container-per-tenant, one-process-many-tenants, or worker-pool? Quote any vendor hosting doc.
- **1.4 Cold-start cost & instance footprint** — startup latency, RAM baseline, disk baseline. (E.g. Claude Agent SDK's open issue #333: 20–30 s startup per instance.)
- **1.5 Vendor lock-in** — LLM-provider lock-in, hosting-platform lock-in, eval-platform lock-in. Score each independently.
- **1.6 Framework weight / footprint** — thin SDK (a few hundred LOC of glue) vs. heavy framework (bundles storage, eval, dev UI, plugin system).
- **1.7 Release-history signal** — what do the in-repo changelog and GitHub Releases show about recent breaking changes, fast-moving areas, deprecations, or production-relevant additions? Cite changelog files with line numbers when available and link release pages.

---

### Q2 — Agent Harness (Run Loop)

The core loop. Runtime concerns (concurrent isolation, scaling) belong in Q4. Sessions & persistence belong in Q5. Network exposure (interrupt, HITL, streaming protocol) belongs in Q8. Built-in tools, MCP, and multi-model routing live in Q13–Q15. Message and event taxonomy lives in Q3.

Answer:

- **2.1 Run loop entrypoint(s)** — signature, inputs, outputs (return type / yielded type). Show the type.
- **2.2 Per-iteration behavior** — what happens in one trip around the loop? (call LLM → parse tool calls → permission gate → dispatch → collect result → next call)
- **2.3 ReAct loop** — does the stack ship a built-in ReAct loop, or do you assemble one yourself?
- **2.4 Tool dispatch + result handling** — how does the harness route LLM-generated tool calls to executors and feed results back?
- **2.5 Explicit turn concept** — what defines a turn boundary? (Single LLM call? Until no more tool calls? Until result message?)
- **2.6 Event emission mechanism (in-process)** — async generator / EventEmitter / callback / typed stream? Show the code path. (Network-side streaming is Q8.4–8.5.)

---

### Q3 — Message & Event Taxonomy

What the loop yields, when, and in what type *is* the harness's public contract. The reader wants to understand the *layers* of messages and events — what crosses the wire, what crosses internal boundaries, what's surfaced to the UI, what's emitted as a transient event.

Answer:

- **3.1 Message layers** — how many distinct message vocabularies exist? (e.g. wire / UI / internal LLM message). Diagram the conversions.
- **3.2 Concrete message types** — table of every type with 1-line purpose.
- **3.3 Messages vs. events** — are they the same iterator, or two separate taxonomies?
- **3.4 Event categories** — stream-event, turn-event, message-event, tool-event, session-lifecycle event, hook event, sub-agent event. Which exist, and what defines each category?
- **3.5 Canonical type-definition file(s)** — cite the source of truth.
- **3.6 Live agentic event stream taxonomy** — what concrete event types stream to the consumer? Sample one frame of each major category.

---

### Q4 — Agent Runtime (Multi-session Host)

The runtime is the layer *around* the loop that hosts many concurrent sessions, scales horizontally, and runs background work. Session shape / persistence is Q5.

Answer:

- **4.1 Multi-session host architecture** — does the stack ship a runtime that hosts N concurrent sessions in one process? Or is "runtime" = "you embed the loop in your own server"?
- **4.2 Concurrent session isolation** — many sessions in one process — is state isolated, or can it bleed? Where is isolation enforced?
- **4.3 Horizontal scaling / multi-instance** — stateless workers? Leader election? Shared store? Can N pods serve the same session pool with shared state?
- **4.4 Background / async / scheduled tasks** — cron, webhook triggers, long-running background agents — first-party or BYO?
- **4.5 Worker pool / queue model** — does the runtime expose a queue (e.g. for long-running agent work), or does it assume short-lived HTTP request scope?

---

### Q5 — Sessions & Persistence

Sessions are where the agent's memory of "this conversation" lives. This question is about the *data model* and the *storage* — the shape of a session/chat, what data it contains, and what stores the SDK ships.

Answer:

- **5.1 Session / chat data model** — what fields exist on a session? Show the type / struct / schema definition. Examples to look for: `id`, `messages`, `tools`, `cwd`, `tenant_id`, `user_id`, `created_at`, `updated_at`, `parent_session_id`, `metadata`, `usage`, `model`, `summary`, …
- **5.2 What's stored on a session** — messages? tool-call history? scratchpad files? embedded memory? attachments? Cite the schema.
- **5.3 Granularity** — single conversation per session? thread/branch model? Can a session fork (LangGraph-style)?
- **5.4 Built-in persistence stores** — what does the SDK ship out-of-box? Possibilities: JSONL on local disk (`~/.claude/projects/<cwd>/<sid>.jsonl` style), SQLite, Postgres (which adapter? `bun`, `pgx`, SQLAlchemy?), Redis, S3, Anthropic-hosted, Mastra Cloud, Vercel Blob, vendor cloud, or **none — BYO**.
- **5.5 Persistence timing** — at what exact moment in the loop are messages persisted? Per token? Per assistant message? Per turn end? After every tool result? Sync vs. async (e.g. LangGraph's `durability="sync"` vs `"async"`, Mastra's debounced batch)?
- **5.6 Mid-run checkpointing (durable)** — can a run resume after crash *mid-tool-call*? Where does the checkpoint actually fire in the code path? (LangGraph's `_runner.commit() → put_writes()` per-task is the gold standard.)
- **5.7 Session ID format** — UUID? Tenant-prefixed? Hash-based? Composite (e.g. `project:session:subpath`)?
- **5.8 Pluggable store interface** — can you plug in your own store (custom DB)? Show the interface (`SessionStore`, `BaseCheckpointer`, …).
- **5.9 Schema evolution / migration** — how does the SDK handle schema changes between versions? Migration helpers shipped, or hand-roll?
- **5.10 Export / replay** — can a session be exported (JSON / JSONL) and deterministically replayed for debugging / eval?
- **5.11 Cross-session memory** — different from in-session messages. Brief note + cross-reference to Q17 (Memory & Knowledge).

---

### Q6 — Multi-tenancy & Arbitrary Context ⭐ THE KEY QUESTION

The audience runs a multi-tenant long-running agent piloted by skills. They need to (a) pass `tenantId` / `userId` / `targetingStrategyId` / `locale` etc. into the harness, (b) use that context to **filter** which tools/skills the LLM can see, and (c) **force** specific tool arguments from the harness — *not* trust the LLM to fill them in. The LLM could hallucinate or be prompt-injected into using the wrong tenant id.

Answer:

- **6.1 Full run-loop input struct** — every field beyond `messages`. Show the type.
- **6.2 Context propagation into a tool call** — how does harness-provided context reach `tool.execute(...)`? Show the call path.
- **6.3 Tool call interface** — `execute` / handler signature: arguments, return type, the context object. Show real code.
- **6.4 Forcing tool arguments from the harness** — can you say "for tool `topicSearch`, always pass `tenantId=acme-corp` regardless of what the LLM generates"? Show the mechanism (e.g. `PreToolUse → updatedInput`, `experimental_refineToolInput`, `_inject_tool_args`, typed `spec T`). If the stack lacks this, say so plainly — it's a real gap.
- **6.5 Filtering visible tools** — can the harness change the toolset visible to the LLM at session-start or per-turn based on context? Show the mechanism (`activeTools`, `allowed_tools`, `prepareStep`, …).
- **6.6 Tenant scope on session** — is tenant identity a first-class field on the session, or stuffed in metadata?
- **6.7 Per-tool-call auth propagation** — does the caller's identity reach every tool call automatically (so tools execute under their permissions)?
- **6.8 Resource scoping primitives** — can skills / sub-agents / tools be scoped global/tenant/user at registration time, or only filtered at runtime?
- **6.9 Per-tenant rate limit + budget cap** — token/cost ceilings enforced per tenant. (Most stacks lack this; only flag 🟢 if you find a USD budget cap, not just turn caps.)

⭐ **Required — light usage example** (5–15 lines). Show how to:
1. Pass `tenantId="acme"`, `targetingStrategyId="strat-42"`, `userId="u-123"` into the run-loop call.
2. Make only the tools `topicSearch`, `iabSearch`, `audienceCreate` visible (skip `bashExec`, `webFetch`).
3. Force every `topicSearch` call to receive `tenantId="acme"` server-side, even if the LLM tries to pass a different value.

If any of the three is impossible in this stack, say "Step N: Not provided — BYO" and explain the closest workaround in 1–2 lines.

---

### Q7 — Hook & Middleware Capabilities (Context Engineering)

Hooks/middleware are how engineering teams extend behavior without forking. This section also covers the *context-engineering* concerns that hooks typically enable (compaction, cache breakpoints, tool result clearing).

Answer:

- **7.1 Enumerate every hook / middleware / lifecycle callback** — table form: name → fires when → can do what (read / mutate / block / branch).
- **7.2 Hook concurrency model** — do matchers fire in sequence, in parallel, with a fold?
- **7.3 Specific capability tests** — for each, say yes/no with code:
  - inject system messages at session start (e.g. "current date is 2026-05-16, tenant is acme, locale fr-FR")
  - expand the user input (slash commands, time-stamp, attachments)
  - mutate the messages list before each LLM call (e.g. prompt-cache breakpoints, redaction)
  - mutate / decorate tool input before dispatch (e.g. inject `tenantId` server-side — see Q6.4)
  - mutate / decorate tool result before it returns to the LLM (e.g. redact, summarize, truncate)
  - **emit additional tool calls in response to a tool result** (Claude Agent SDK supports this via `additional_messages` from `PostToolUse` — does this stack?)
- **7.4 Auto-compaction** — built-in summarization/truncation, or BYO? When does it trigger?
- **7.5 Prompt cache optimization** — provider-cache-aware (Anthropic, OpenAI)? Stable-prefix preservation, breakpoint placement, automatic vs. manual?
- **7.6 Tool result clearing / progressive disclosure** — strategies to keep large tool outputs out of the main context (filesystem stash, summary, on-demand re-read).
- **7.7 Architectural diagram** of where hooks fire across the loop (ASCII or mermaid).

⭐ **Required — light usage example** (5–15 lines). Show:
1. A `SessionStart` hook that injects "tenant=acme, locale=fr-FR, today=2026-05-16" as a system message.
2. A `PreToolUse` hook on `topicSearch` that adds a `tenantId` field server-side (the same forced-args pattern from Q6.4).
3. A `PostToolUse` hook that, when `topicSearch` returns more than 50 results, summarizes them in place.

---

### Q8 — HTTP API

**What this question is about**: whether the framework ships **HTTP API features** to expose the agent and its capabilities to remote clients. Some stacks ship a server (routes, handlers, streaming protocol, auth, cancel, HITL); some are library-only and the host owns every byte of the HTTP layer. Be precise about what the framework gives you out-of-the-box vs. what you wire up yourself.

This question covers everything observable from outside the process **over HTTP** — including interrupt, HITL approval, and tool-arg streaming, since those are *features of the HTTP surface* even when the underlying mechanism lives in the loop. Network-agnostic concerns (in-process event emission, internal turn boundaries) belong in Q2/Q3.

Answer:

- **8.1 Does the framework ship an HTTP server?** First-party server, library-only, or both? Name the exact package or sub-module that exposes the agent.
- **8.2 HTTP streaming transport** — SSE? WebSocket? HTTP long-poll? Proprietary stream format? Multiple, configurable?
- **8.3 HTTP endpoints that start an agent run** — request shape (body, headers, query). Show one real endpoint with method + path.
- **8.4 Live agentic event stream format** — sample frames the HTTP client receives: start, mid-stream, terminal. Show the wire format.
- **8.5 Auth termination at the HTTP boundary** — does the framework terminate auth (JWT validation, tenant scoping) at the route handler, or leave it entirely to the host?
- **8.6 Resume / replay endpoint** — how does an HTTP client reopen a session (user reopens a tab) or replay agent events?
- **8.7 Interrupt / cancel via HTTP** — DELETE? AbortSignal over the same connection? Close-stream-and-call-cancel? Show the request shape.
- **8.8 Tool-arg streaming (partial JSON)** — does the HTTP stream expose tool arguments as they generate (before the LLM finishes the call)? What's the frame shape?
- **8.9 HITL approval workflow over HTTP** — how does an HTTP client send a tool-approval / rejection verdict? Same endpoint? Different one? Payload shape? Is there a pause state observable to the client?
- **8.10 Tool-call state reconstruction** — ⭐ critical. How does the HTTP client link `tool_use` and `tool_result` events from the stream? Explicit `tool_call_id`, or implicit/positional? Show the event types and the linkage mechanism.
- **8.11 Health checks / graceful shutdown** — `/healthz`, `/readyz`, `/metrics`, SIGTERM drain?

⭐ **Required — light usage example** (5–15 lines). Show:
1. A `curl` or `httpie` call to start a run with `X-Tenant-Id: acme` header and a user message.
2. 3–5 lines of the SSE stream the client would receive (start frame, one tool-use frame, terminal frame).
3. A `curl` call to cancel the run mid-flight.
4. A `curl` call to send a HITL approval verdict for a paused tool call.

If the framework ships no HTTP API at all, write **"Not provided — BYO HTTP layer"** for every sub-bullet that requires the server and describe the recommended host-side pattern in 1–2 lines.

---

### Q9 — Sub-agents

Answer:

- **9.1 Mechanism** — are sub-agents invoked as a *special tool* (agents-as-tools), as a first-class primitive, or both?
- **9.2 Configuration** — markdown file? struct registered at boot? object inlined per call? runtime-generated by the parent LLM?
- **9.3 LLM-generated configs** — can the parent LLM generate a sub-agent config on the fly with custom system prompt / tools, or must configs be statically registered?
- **9.4 Output handling** — how does the parent receive sub-agent output? Single result string? Streaming events? Structured object? Linked back to a parent `tool_use_id`?
- **9.5 Concurrency model** — serial, parallel, fan-out? Where in the code is parallelism actually implemented (the line that does the `Promise.all` / `sync.WaitGroup` / etc.)?
- **9.6 Context isolation** — does the sub-agent see the parent's context or start fresh? Where is this enforced?
- **9.7 Lifecycle events** — does the parent stream get sub-agent lifecycle events (started, progress, completed)?

⭐ **Required — light usage example** (5–15 lines). Show:
1. Defining 3 persona sub-agents (`persona-young-mom`, `persona-tech-bro`, `persona-retiree`), each with its own system prompt and a `topicSearch` tool.
2. The parent agent invoking them in parallel.
3. Where the parent receives each result.

---

### Q10 — Skills

"Skill" specifically means a markdown file (à la Claude Code's `SKILL.md`) describing a workflow, loaded on-demand to extend the agent — not a "capability" in the loose sense. If the stack doesn't have this concept, say so plainly. Resource-Manager concerns (versioning, publishing, governance, loading from external sources) belong in Q11.

Answer:

- **10.1 First-class concept?** Or community/convention pattern? Or absent entirely?
- **10.2 File format** — `SKILL.md` with YAML frontmatter? Show the schema (fields, types, validators).
- **10.3 Loader mechanism** — filesystem scan? Programmatic registration via SDK call? Plugin system?
- **10.4 Invocation** — is invoking a skill a *tool call*, a *system-prompt injection*, or a third mechanism (e.g. lazy fetch via a `skill_read` tool)?
- **10.5 Loading mode** — eager (all skills in system prompt) or lazy (metadata-only in prompt, body fetched on use)?
- **10.6 Runtime scoping (global / tenant / user)** — can the same agent surface a different skill catalog per tenant *at runtime*? Show the filter mechanism. (Registry-side scoping is Q11.5.)
- **10.7 Skill composition** — can a skill reference / include other skills, or call sub-agents, or pull in references/scripts/assets bundled alongside the `SKILL.md`?

⭐ **Required — light usage example** (10–20 lines). Show:
1. Authoring a `SKILL.md` titled "Generate-Audience-From-Brief" with frontmatter.
2. Loading it at runtime (filesystem path, registry id, or programmatic registration call).
3. The agent discovering and invoking it (show whether the LLM sees a tool, a system-prompt fragment, or a special hook).

---

### Q11 — Resource Manager

The Resource Manager is the *platform* layer that manages many skills, sub-agents, prompts, and tools across teams: where they're stored, how they're versioned, who can publish, and what scope they go live in. Skills-as-a-format is Q10; this is "how do we run a multi-tenant skill library".

Answer:

- **11.1 First-class Resource Manager?** Does the stack ship one (registry, source abstraction, publishing workflow), or is it BYO?
- **11.2 Loading sources** — where can resources LOAD FROM? List every supported source with how it's configured:
  - **Local filesystem** (`./skills/`, `~/.claude/skills/`, `.mastra/`)
  - **Git / GitHub repos** (sparse-checkout, `git+https://`, GitHub raw URLs, Git submodules)
  - **OCI / container registries** (skill bundles as OCI artifacts)
  - **Cloud object storage** (S3, GCS, Azure Blob, Cloudflare R2, Vercel Blob)
  - **Postgres / relational DB** (rows-as-resources, `langgraph_store`-style)
  - **Vendor cloud / managed registry** (LangSmith Hub, Mastra Cloud, Anthropic Hub, AMP Agent Repositories)
  - **HTTP fetch** (arbitrary HTTPS URL with caching)
- **11.3 Source composition / priority** — can multiple sources stack (e.g. `local > tenant-bucket > global-registry`)? What wins on conflict?
- **11.4 Versioning model** — semver? content-hash? immutable refs? rollback support?
- **11.5 Scoping at the registry layer** — can a resource be marked "tenant X only" / "user Y only" at *publish time*, not just filtered at *runtime* (Q10.6)?
- **11.6 Publishing workflow** — draft → review → publish → promote? Multi-environment (dev / staging / prod)? Approval gates?
- **11.7 Lifecycle / governance** — lifecycle states (draft, active, deprecated, retired)? RBAC on who can publish/scope/retire?
- **11.8 Programmatic API** — list / search / sync / pin resources from code? Show the API.
- **11.9 Caching & sync model** — does the SDK pull resources on each request, cache locally, watch for changes, sync periodically?

⭐ **Required — light usage example** (8–15 lines). Show:
1. Registering a `git+https://github.com/dailymotion/predict-skills` source AND a `s3://predict-skills/tenants/acme/` source, with the S3 source winning for tenant `acme`.
2. Promoting a skill from draft → active for tenant `acme` only.
3. Listing all active skills visible to a request with `tenantId=acme`.

---

### Q12 — Observability: Usage, Cost, Tracing, Audit

Answer:

- **12.1 Where tokens are surfaced** — on the result object? On every assistant message? Via events? Via a hook?
- **12.2 Per-call / per-turn / per-session / per-tenant rollups** — what aggregation levels does the SDK expose?
- **12.3 USD cost computation** — does the SDK compute cost in dollars, or only tokens?
- **12.4 Per-tenant / per-conversation cost** — first-party rollup, or BYO via metadata-tagged tracing?
- **12.5 LLM / tool tracing** — OTel built-in? First-party tracer? LangSmith / LangFuse / 25+ exporters?
- **12.6 Audit logging (who / when / what)** — distinct from tracing. Tamper-evident? Hook event stream with a BYO sink?
- **12.7 Canonical "where do I read token counts" code path** — file:line, show the type.

⭐ **Required — light usage example** (5–15 lines). Show:
1. Reading `tokens_in` / `tokens_out` / `cost_usd` for one completed run.
2. Hooking to push per-tenant token usage to a metric sink (Datadog, OTel — pseudocode is fine).

---

### Q13 — Built-in Tools & Tool Authoring API

Answer:

- **13.1 Built-in tools shipped in the box** — web search, file ops (read/write/edit), code exec, fetch, glob, grep, bash, monitor? List the catalog with a one-line purpose each.
- **13.2 Built-in tool quality** — are they thin wrappers or do they encode patterns (e.g. Claude Code's `Edit` with anchor matching, `Read` with line numbers, `Monitor` with line-event streaming)?
- **13.3 Tool authoring API** — what does a developer write to add a new tool? Show the smallest possible tool definition (signature, JSON-schema generation, dispatch).
- **13.4 Typed tool I/O** — runtime validation of LLM-generated args (Zod / Pydantic / JSON-schema)? What happens on invalid args?
- **13.5 Streaming tools** — can a tool yield partial results to the model mid-execution (e.g. progress events)?

---

### Q14 — MCP (Model Context Protocol) Support

Answer:

- **14.1 MCP client support** — can the stack consume external MCP servers (Playwright, GitHub, etc.)? First-class or plugin?
- **14.2 MCP server support** — can the stack expose its own tools as an MCP server for other agents/clients to consume?
- **14.3 Transports** — stdio, SSE, HTTP, in-process/SDK transport?
- **14.4 In-process MCP** — can you define a Python/TS function and surface it as a tool via the MCP machinery without spawning a subprocess?
- **14.5 Auth / lifecycle** — how are credentials passed to remote MCP servers? Reconnection, health, version negotiation?

---

### Q15 — Multi-model Routing & Fallback

Answer:

- **15.1 Multi-provider support** — Anthropic, OpenAI, Gemini, Bedrock, Vertex, Azure, LiteLLM / AnyLLM adapters? Native or third-party?
- **15.2 Per-task model selection** — cheap-for-triage / expensive-for-hard-tasks routing — first-party (registry / gateway) or BYO?
- **15.3 Automatic fallback chain** — when a provider has an outage or rate-limits, does the SDK retry on a fallback model? Show the config.
- **15.4 Mid-stream model switching** — can you switch model at a turn boundary, or only at session start?
- **15.5 Sub-agent model overrides** — can a sub-agent run on a different model than the parent (e.g. Sonnet supervisor + Haiku workers)?

---

### Q16 — Chat UI Layer

Most backend-focused SDKs leave this to the host; some (Vercel AI SDK, Mastra, LangGraph) ship first-party frontend primitives.

Answer:

- **16.1 Streaming chat hook** — first-party frontend hook (e.g. React `useChat`) that handles message streaming, history, chat state?
- **16.2 Tool call rendering primitives** — frontend primitives for rendering which tool is running, with what args, returning what result.
- **16.3 Generative UI components** — first-party support for rendering rich UI artifacts the agent generates (forms, cards, charts).
- **16.4 BYO pattern** — if no first-party UI, what's the recommended pattern? (parse the SSE stream into your own React state, etc.)

---

### Q17 — Memory & Knowledge

Answer:

- **17.1 Long-term memory / semantic recall** — persistent memory across sessions (facts about user/tenant the agent recalls on future turns). Typically vector-search-backed.
- **17.2 RAG / knowledge retrieval integration** — first-party retrieval primitives (vector-store integration, chunkers, retrievers, citations)?
- **17.3 Per-tenant memory scoping** — is memory naturally scoped per-tenant or do you need to namespace yourself?

---

### Q18 — Safety, Guardrails & Tool Sandboxing

Answer:

- **18.1 Input/output guardrails** — PII redaction, prompt-injection detection, hallucination detection — first-party or BYO?
- **18.2 Tool sandboxing / permission model** — allow/deny lists, `canUseTool`-style hooks, per-tool ACL.
- **18.3 Sandbox provider integrations** — E2B, Daytona, Modal, code interpreters?
- **18.4 Default-deny vs. default-allow** — what's the default posture?

---

### Q19 — Eval, Testing & CI Gates

Answer:

- **19.1 Golden datasets / regression suites** — pre-built dataset format + harness for regression-testing agent behavior across model/prompt/skill changes.
- **19.2 LLM-as-judge scoring** — first-party support for using an LLM to grade agent outputs against a rubric.
- **19.3 CI eval gates / pre-merge** — pre-merge eval gates so behavior changes don't ship blind.
- **19.4 Trace replay for skill iteration** — local viewer to step through past traces.

---

### Q20 — Local Sandbox & Dev UX

Answer:

- **20.1 Local agent runner** — CLI, playground, TUI, or web dev UI to run agent sessions on your laptop without deploying.
- **20.2 Trace inspection** — local viewer for past traces.
- **20.3 Tenant / org switching** — can the local sandbox switch between tenant contexts to test tenant-scoped behavior?
- **20.4 Hot reload** — change a skill / prompt and see results without restart?

---
