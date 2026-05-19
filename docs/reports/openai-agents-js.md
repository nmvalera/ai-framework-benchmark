# OpenAI Agents TypeScript — Benchmark Study

> **Repo**: https://github.com/openai/openai-agents-js
> **Commit studied**: 629d35af99e1ba80fc968b0d062c070caed0683d
> **Branch**: main
> **Framework path**: frameworks/openai-agents-js
> **Studied on**: 2026-05-16

## TL;DR

- **Architecturally** a thin TypeScript SDK / library: the agent loop runs **in your Node.js / Deno / Bun process**. There is **no first-party server, no hosted runtime, no CLI binary, no subprocess**. Everything is a class you instantiate (`Agent`, `Runner`) inside your own host (`packages/agents-core/src/run.ts:387`).
- **Ecosystem**: TypeScript (Node 22+, Deno, Bun; experimental Cloudflare Workers).
- **Open-source MIT**, owned by OpenAI (`LICENSE`, `packages/agents-core/package.json:38`); maintained by `@openai/agents` core team; OpenAI provides commercial backing through the Traces dashboard and Conversations API but no managed agent runtime.
- **Maturity / version**: pre-1.0, version `0.11.4` across all packages (`packages/agents-core/package.json:5`). CHANGELOG history shows frequent minor/patch releases; sandbox-agent runtime added in `0.9.0` (May 2026 area). APIs still evolve.
- **Where the loop runs**: in-process. `Runner.run()` is a synchronous TypeScript `while(true)` loop that calls a `Model` instance over HTTP/SSE/WebSocket directly from your process (`packages/agents-core/src/run.ts:844-1078`).
- **Strongest fit for our use case**: typed `tool({ execute, needsApproval, isEnabled })` API gives clean per-tool runtime filtering by `RunContext.context`, full HITL approvals via `RunState` serialization, and explicit `callModelInputFilter` / `agent_*` lifecycle hooks. Multi-tenancy is achievable via the typed `RunContext<TContext>` payload.
- **Weakest gap**: **no first-party HTTP server, no SSE/WebSocket route, no `/healthz`, no auth termination, no resource manager.** You hand-roll the network surface (see `examples/nextjs/src/app/api/basic/route.ts`). No registry, no versioning, no skill marketplace beyond the in-sandbox-only `skills()` capability.
- **Surprising finding (good)**: Skills are a first-class concept but **only inside Sandbox Agents** — `SKILL.md` frontmatter loaders, lazy loading via a `load_skill` tool, and progressive-disclosure prompts are all built in (`packages/agents-core/src/sandbox/capabilities/skills.ts`). Non-sandbox agents have no skill loader.
- **Surprising finding (bad)**: tracing defaults to **exporting to the OpenAI platform** on every run (`packages/agents/src/index.ts:8` calls `setDefaultOpenAITracingExporter()`); for multi-tenant deployments you must explicitly disable via `OPENAI_AGENTS_DISABLE_TRACING=1` or replace processors.
- **Verdicts**:
  - sessions/persistence: 🟡 in-memory `MemorySession` + `OpenAIConversationsSession`; BYO for Postgres/Redis (pluggable `Session` interface).
  - skills: 🟡 only inside Sandbox Agents.
  - resource manager: 🔴 Not provided — BYO.
  - sub-agents: 🟢 two mechanisms (`handoffs` + `Agent.asTool()`), structured input, parallel ok.
  - multi-tenancy: 🟡 typed `RunContext<TContext>` + `isEnabled` filtering; no first-class tenantId on sessions; no per-tenant budget caps.
  - hooks: 🟡 `EventEmitter` lifecycle events + `callModelInputFilter` + per-tool guardrails; no `PreToolUse` mutation hook like Claude Agent SDK.
  - API: 🔴 library-only; BYO HTTP/SSE.
  - observability: 🟢 OpenAI Traces + pluggable `TracingProcessor` + Usage rollups; 🔴 no USD cost.
- **Production-readiness verdict**: viable for **request-scoped** server-side multi-tenant deployments where you own the HTTP layer, plug a custom `Session` store, and disable default OpenAI tracing. **Not** viable as a drop-in for long-running stateful agents — there is no built-in runtime, durability, or worker pool.

## 0. General

### 0.1 What is this stack?

A library / SDK. `@openai/agents` is a TypeScript package you import and call `run(agent, input)` on; the entire loop runs in the caller's Node/Deno/Bun process. There is no companion server binary, no managed cloud runtime, no CLI.

### 0.2 Ecosystem

**TypeScript** (Node 22+, Deno, Bun; experimental Cloudflare Workers with `nodejs_compat`). Single-language project — no other implementation language is mixed in. The Python sibling repo (`openai-agents-python`) is a parallel implementation, not a dependency.

### 0.3 Project status & governance

- **Open-source**, MIT license (`LICENSE`, `packages/agents-core/package.json:38`).
- **Owner**: OpenAI (`AUTHOR: OpenAI <support@openai.com>` in `packages/agents-core/package.json:8`).
- **Commercial backing**: hosted complementary services (OpenAI Traces dashboard, Conversations API, hosted MCP, hosted built-in tools, hosted sandbox tools) all sit behind the OpenAI platform paywall. There is **no managed agent runtime**; the SDK is community-supported via GitHub issues plus OpenAI Help Center for API issues.
- **Support model**: community / GitHub issues.

### 0.4 Project maturity / age

- Current version: **0.11.4** (all five packages, `packages/agents-core/package.json:5`, `packages/agents/package.json:5`).
- Status: **pre-1.0** — APIs still marked stable for individual constructs (`Agent`, `tool`, `run`) but **Sandbox Agents** are explicitly labeled "beta" in `README.md:38`.
- Release cadence: `packages/agents-core/CHANGELOG.md` shows ~3 minor versions in the last 6 months (0.9.0 → 0.11.x), heavy patch traffic. Sandbox agents core runtime introduced in 0.9.0.

### 0.5 Adoption & community signal

(Captured 2026-05-16, primary signal: npm package metadata visible in submodule; GitHub stars not captured live in this study)

- The TypeScript SDK is the official complement to the Python SDK (`README.md:14`).
- Active development: 100+ commits in the last 0.11.x patch range; clear use of changesets (`.changeset/` directory, `packages/*/CHANGELOG.md`).
- Many examples (`examples/` has 22 sub-folders: `agent-patterns`, `sandbox`, `realtime-twilio`, `nextjs`, `mcp`, `memory`, `ai-sdk`, …).

### 0.6 Ecosystem fit

- Packages: `@openai/agents` (umbrella), `@openai/agents-core` (loop + types), `@openai/agents-openai` (OpenAI provider + tracing exporter), `@openai/agents-realtime` (voice), `@openai/agents-extensions` (AI SDK / Cloudflare / Twilio adapters).
- Registry: npm — https://www.npmjs.com/package/@openai/agents
- Primarily used as a **library** — embed in Next.js routes, Express, Cloudflare Workers, etc.
- Official examples/templates: `examples/` directory in the monorepo (22 sub-folders).

### 0.7 Documentation depth & cross-team contributor accessibility

- Astro/Starlight site under `docs/`, multi-language (English + ja/zh/ko translations).
- Guides cover Agents, Running Agents, Sessions, Streaming, Tools, MCP, Handoffs, Human-in-the-loop, Guardrails, Tracing, Sandbox Agents, Voice Agents, Models, Context, Troubleshooting (`docs/src/content/docs/guides/`).
- Examples directory is large and runnable (22 sub-folders).
- A non-engineer would need TypeScript and CLI familiarity; no no-code surface.

### 0.8 Documentation entry points ⭐

- Official docs landing: https://openai.github.io/openai-agents-js
- Quickstart: https://openai.github.io/openai-agents-js/guides/quickstart
- API reference: https://openai.github.io/openai-agents-js/openai/agents-core/ (auto-generated)
- Hosting / deployment: https://openai.github.io/openai-agents-js/guides/troubleshooting/ and https://openai.github.io/openai-agents-js/extensions/cloudflare/
- Examples / demos: https://github.com/openai/openai-agents-js/tree/main/examples
- Changelog: per-package, e.g. https://github.com/openai/openai-agents-js/blob/main/packages/agents-core/CHANGELOG.md
- GitHub Releases: https://github.com/openai/openai-agents-js/releases
- GitHub issues: https://github.com/openai/openai-agents-js/issues
- Community: no official Discord; OpenAI community forum at https://community.openai.com/

---

## 1. High Level Architecture

⭐ **Deployment diagram**

```
┌──────────────────────────────────────────────────────────────────────┐
│  Your Node.js / Deno / Bun host process                              │
│                                                                       │
│   HTTP server (Next.js, Express, Hono, etc. — YOU bring this)        │
│        │                                                              │
│        ▼                                                              │
│   run(agent, input, options)  ← Runner / runner.run()                │
│        │                                                              │
│        ▼                                                              │
│   while (true) {                                                      │
│     prepareTurn → prepareModelCall → Model.getResponse()              │
│       │                                  │                            │
│       │                                  ▼                            │
│       │             HTTP/SSE/WebSocket ──────→  OpenAI Responses API  │
│       │                                  ▲                            │
│       │                                  │  (or Anthropic / Bedrock / │
│       │                                  │   AI-SDK adapter)          │
│       ▼                                                              │
│     processModelResponse → toolExecution → resolveTurn                │
│        │            │                                                 │
│        │            ▼                                                 │
│        │      MCP servers (stdio/SSE/Streamable HTTP)                 │
│        │      User tool callbacks (run in this process)               │
│        ▼                                                              │
│     Session.addItems()  ──── MemorySession                            │
│                          ──── OpenAIConversationsSession ─→ OpenAI    │
│                          ──── YOUR custom Session (Postgres, Redis…)  │
│                                                                       │
│     BatchTraceProcessor ─── OpenAITracingExporter ─→ platform.openai  │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.1 Where does the agent loop *actually* execute?

In your Node.js / Deno / Bun process. `Runner.run()` is a TypeScript class with a single `while (true)` loop:

```ts
// packages/agents-core/src/run.ts:844
while (true) {
  state._currentStep = state._currentStep ?? { type: 'next_step_run_again' };

  if (state._currentStep.type === 'next_step_interruption') { … }

  if (state._currentStep.type === 'next_step_run_again') {
    const { turnInput, parallelGuardrailPromise } = await prepareTurn({ … });
    const preparedCall = await this.#prepareModelCall(state, …);
    state._lastTurnResponse = await getResponseWithRetry(preparedCall.model, { … });
    const processedResponse = await processModelResponseAsync(…);
    const turnResult = await resolveTurnAfterModelResponse(…);
    applyTurnResult({ state, turnResult, … });
  }

  switch (currentStep.type) {
    case 'next_step_final_output':  return new RunResult(state);
    case 'next_step_handoff':       state.setCurrentAgent(currentStep.newAgent); break;
    case 'next_step_interruption':  return new RunResult(state);
    case 'next_step_run_again':     break;
  }
}
```

No subprocess. No vendor binary. The "OpenAI" in the name is provider-agnostic loop + first-party OpenAI provider; other providers plug in via `Model` / `ModelProvider` (`packages/agents-extensions/src/ai-sdk/index.ts` wraps the Vercel AI SDK).

### 1.2 Runtime dependencies

- **Language runtime**: Node.js 22+, Deno, or Bun (`README.md:31`). Cloudflare Workers experimental with `nodejs_compat` (`README.md:36`).
- **Bundled binaries / subprocesses**: none. The SDK does not subprocess any vendor binary.
- **Required infrastructure services**: none for the loop itself. Sessions live in-memory by default (`MemorySession`); persistence is BYO.
- **Required vendor services**: OpenAI API (for default `Model`) — outbound HTTPS to `api.openai.com`. Default tracing also calls out to `platform.openai.com` unless disabled.
- **Optional**: MCP server subprocesses (stdio); Anthropic/Gemini/Bedrock via the AI-SDK extension.

### 1.3 Recommended deployment topology

The docs do **not** prescribe a topology. The `examples/nextjs/` reference shows one-process-many-requests embedded in a Next.js Route Handler. Each `run()` call is request-scoped: prepare input → run loop → return result. Many concurrent runs share one Node process but each run owns its own `RunState`. There is no built-in worker pool, queue, or cluster mode.

Quoting `docs/src/content/docs/guides/troubleshooting.mdx` and `docs/src/content/docs/extensions/cloudflare.mdx`: deploy as a normal Node.js HTTP service; Cloudflare Workers documented as experimental.

### 1.4 Cold-start cost & instance footprint

- No bundled binary. The SDK is pure JS / TS — startup is whatever your Node process takes (~200-400 ms typical).
- RAM baseline: minimal beyond Node baseline; sessions live in memory by default (`MemorySession`).
- No equivalent of Claude Agent SDK issue #333 (slow bootstrap). Loop starts on `run()` invocation in milliseconds.

### 1.5 Vendor lock-in

- **LLM provider**: medium. Default is OpenAI Responses API (`packages/agents-openai/src/openaiResponsesModel.ts`). Pluggable via custom `ModelProvider`. Anthropic / Gemini / Bedrock / Vertex possible via the `@openai/agents-extensions/ai-sdk` bridge (uses Vercel AI SDK as provider abstraction) or hand-rolled `Model` impl. Hosted tools (`webSearchTool`, `fileSearchTool`, `codeInterpreterTool`, `imageGenerationTool`, `toolSearchTool`) are **OpenAI Responses API only** (`packages/agents-openai/src/tools.ts`).
- **Hosting**: low. Library-only.
- **Eval / observability**: tracing defaults to OpenAI Traces dashboard (`packages/agents/src/index.ts:8` calls `setDefaultOpenAITracingExporter()`); to escape you call `setTraceProcessors([…])` or set `OPENAI_AGENTS_DISABLE_TRACING=1`.

### 1.6 Framework weight / footprint

Lean. The umbrella `@openai/agents` package re-exports from `agents-core`, `agents-openai`, `agents-realtime`. No bundled storage, eval, dev UI, or plugin system. Source roots:

- `packages/agents-core/src/` ≈ 60 top-level TS files
- `packages/agents-openai/src/` ≈ 15 files (provider, tracing exporter, conversations session, transports)
- `packages/agents-realtime/src/` (voice-only)
- `packages/agents-extensions/src/` (AI-SDK + Cloudflare + Twilio adapters)

### 1.7 Release-history signal

`packages/agents-core/CHANGELOG.md` recent highlights:

- `0.11.4`: tracing shutdown fixes (`f36e7b2`, line 9).
- `0.11.0`: extra path grants required for local sandbox sources outside base directory (`eb81397`, line 44).
- `0.10.0`: switched default model to `gpt-5.4-mini` (`2e7e48a`, line 57); `maxTurns: null` to disable turn limits (`3546add`, line 61); function tool execution concurrency (`0e7cbf0`, line 62).
- `0.9.0`: **Sandbox Agents core runtime** introduced (`2e1d626`, line 79) — this is the big architectural shift around skills + filesystem workspace.

High patch traffic on sandbox sessions / GitRepo path safety implies sandbox features are still hardening. GitHub Releases: https://github.com/openai/openai-agents-js/releases.

---

## 2. Agent Loop

### 2.1 Run loop entrypoint(s)

```ts
// packages/agents-core/src/run.ts:387
export async function run<TAgent extends Agent<any, any>, TContext = undefined>(
  agent: TAgent,
  input: string | AgentInputItem[] | RunState<TContext, TAgent>,
  options?: NonStreamRunOptions<TContext, TAgent>,
): Promise<RunResult<TContext, TAgent>>;

export async function run<TAgent, TContext>(
  agent: TAgent,
  input: string | AgentInputItem[] | RunState<TContext, TAgent>,
  options?: StreamRunOptions<TContext, TAgent>,
): Promise<StreamedRunResult<TContext, TAgent>>;
```

Two return types based on `options.stream`. Streaming yields `RunStreamEvent` instances; non-streaming returns the final `RunResult`. `Runner` class (`packages/agents-core/src/run.ts:416`) exposes `run()` directly so you can reuse configuration across invocations.

### 2.2 Per-iteration behavior

In `run.ts:844-1078`:

1. `prepareTurn` — assemble `turnInput` from session history + new input + generated items; run input guardrails in parallel (`packages/agents-core/src/runner/turnPreparation.ts`).
2. `prepareAgentArtifacts` + `#prepareModelCall` — resolve effective `Agent`, system instructions, enabled tools, handoffs, `modelSettings`, and apply `callModelInputFilter` if set (`run.ts:927-939`).
3. `getResponseWithRetry` — call the `Model` (HTTP / SSE / WebSocket).
4. `processModelResponseAsync` — split model output into `messages`, `toolCalls`, `handoffs`, `interruptions` (`packages/agents-core/src/runner/modelOutputs.ts`).
5. `resolveTurnAfterModelResponse` — execute function tools (with per-tool guardrails, approvals), produce a `TurnResult` whose `nextStep` is `final_output | handoff | interruption | run_again` (`packages/agents-core/src/runner/turnResolution.ts`).
6. Loop back, or terminate.

### 2.3 ReAct loop

Yes — the canonical ReAct loop is built in. See the docstring at `run.ts:476-495`:

> 1. The agent is invoked with the given input.
> 2. If there is a final output (i.e. the agent produces something of type `agent.outputType`), the loop terminates.
> 3. If there's a handoff, we run the loop again, with the new agent.
> 4. Else, we run tool calls (if any), and re-run the loop.

`maxTurns` defaults to `DEFAULT_MAX_TURNS = 10` (`packages/agents-core/src/runner/constants.ts`), settable to `null` to disable since 0.10.0 (CHANGELOG line 61).

### 2.4 Tool dispatch + result handling

`packages/agents-core/src/runner/toolExecution.ts` dispatches function tool calls produced by the LLM, running them concurrently up to `toolExecution.maxFunctionToolConcurrency` (`run.ts:180-202`). Per-tool input/output guardrails run around `tool.invoke()` (`packages/agents-core/src/tool.ts:1876-1933`). Tool results become `RunToolCallOutputItem` and get fed back to the model on the next turn.

Tool execution path: model → `FunctionCallItem` → `FunctionTool.invoke(runContext, input, details)` → `parser(input)` → `options.execute(parsed, runContext, details)` → `RunToolCallOutputItem` (`tool.ts:1806-1845`).

### 2.5 Explicit turn concept

A turn is bounded by `prepareTurn → model call → resolveTurnAfterModelResponse → applyTurnResult`. `state._currentTurn` (`packages/agents-core/src/runState.ts`) increments at the start of each turn. The loop terminates only on `next_step_final_output` or `next_step_interruption`.

### 2.6 Event emission mechanism (in-process)

Two mechanisms:

1. **Runner / Agent lifecycle EventEmitter** (`packages/agents-core/src/lifecycle.ts:101-181`) — events: `agent_start`, `agent_end`, `agent_handoff`, `agent_tool_start`, `agent_tool_end`.
2. **Streamed run events** — `StreamedRunResult` exposes an async iterable of `RunStreamEvent` (`packages/agents-core/src/events.ts:1-83`).

```ts
// packages/agents-core/src/lifecycle.ts:101-108
export class AgentHooks<TContext, TOutput> extends EventEmitterDelegate<AgentHookEvents<TContext, TOutput>> {
  protected eventEmitter = new RuntimeEventEmitter<AgentHookEvents<TContext, TOutput>>();
}
```

---

## 3. Message & Event Taxonomy

### 3.1 Message layers

Three distinct vocabularies:

1. **Protocol items** (`packages/agents-core/src/types/protocol.ts`) — the wire-format Zod-validated types that go to/from the model. Discriminated union of `UserMessageItem`, `AssistantMessageItem`, `SystemMessageItem`, `FunctionCallItem`, `FunctionCallResultItem`, `HostedToolCallItem`, `ToolSearchCallItem`, `ToolSearchOutputItem`, `ComputerUseCallItem`, `ShellCallItem`, `ApplyPatchCallItem`, `ReasoningItem`, `CompactionItem`, `UnknownItem`.
2. **RunItem classes** (`packages/agents-core/src/items.ts`) — internal SDK items wrapping protocol items with helpers (`RunMessageOutputItem`, `RunToolCallItem`, `RunToolCallOutputItem`, `RunHandoffCallItem`, `RunHandoffOutputItem`, `RunReasoningItem`, `RunToolApprovalItem`, `RunToolSearchCallItem`, `RunToolSearchOutputItem`).
3. **Stream events** (`packages/agents-core/src/events.ts`) — `RunRawModelStreamEvent` (raw provider chunks), `RunItemStreamEvent` (named events wrapping a `RunItem`), `RunAgentUpdatedStreamEvent` (active agent changed).

Conversion: protocol items ↔ RunItem wrappers happen in `items.ts`; stream events wrap RunItem instances and are yielded by `StreamedRunResult`.

### 3.2 Concrete message types

| Type | Purpose |
| --- | --- |
| `UserMessageItem` | User input message |
| `AssistantMessageItem` | Model textual output |
| `SystemMessageItem` | Static system instructions |
| `FunctionCallItem` | LLM-emitted function tool call |
| `FunctionCallResultItem` | Local tool execution result |
| `HostedToolCallItem` | OpenAI-hosted tool invocation (web/file/code/image) |
| `ToolSearchCallItem` | Deferred tool-loading call |
| `ToolSearchOutputItem` | Tool-search result |
| `ComputerUseCallItem` | Computer-use action |
| `ComputerCallResultItem` | Computer-use result |
| `ShellCallItem` / `ShellCallResultItem` | Hosted shell action / result |
| `ApplyPatchCallItem` / `ApplyPatchCallResultItem` | Hosted apply-patch operation |
| `ReasoningItem` | Reasoning trace (GPT-5.x) |
| `CompactionItem` | Compaction marker |
| `UnknownItem` | Forward-compat fallback for new provider types |

(`packages/agents-core/src/types/protocol.ts:340-835`)

### 3.3 Messages vs. events

Two **separate** taxonomies. Persisted history uses **protocol items** (`AgentInputItem`). The streaming surface uses **events** that wrap items: `RunItemStreamEvent` has `name: RunItemStreamEventName` and `item: RunItem` (`events.ts:51-62`).

### 3.4 Event categories

- **Stream event** — `RunRawModelStreamEvent` (raw chunks from the model; e.g., `output_text_delta`).
- **Turn event** — internal step transitions surface via `next_step_*`; not a public type.
- **Message event** — `RunItemStreamEvent` with `name: 'message_output_created'`.
- **Tool event** — `RunItemStreamEvent` with `name: 'tool_called' | 'tool_output' | 'tool_approval_requested' | 'tool_search_called' | 'tool_search_output_created'`.
- **Session lifecycle** — not in the stream; persistence is fire-and-forget via the `Session` interface.
- **Hook event** — `AgentHookEvents` / `RunHookEvents` on `EventEmitter`s, separate from the stream.
- **Sub-agent event** — `RunAgentUpdatedStreamEvent` when handoff switches the active agent; `Agent.asTool({ onStream })` lets nested runs forward sub-agent stream events to a parent callback (`packages/agents-core/src/agent.ts:165`).

### 3.5 Canonical type-definition file(s)

- `packages/agents-core/src/types/protocol.ts` — protocol message + stream-event Zod schemas (single source of truth).
- `packages/agents-core/src/events.ts` — run-loop event classes.
- `packages/agents-core/src/items.ts` — `RunItem` class hierarchy.

### 3.6 Live agentic event stream taxonomy

Sample frames (TypeScript classes; the SDK does not serialize them — that's your job at the network boundary):

```ts
// Raw model delta
new RunRawModelStreamEvent({
  type: 'output_text_delta',
  delta: 'Hello',
});

// Tool was called
new RunItemStreamEvent('tool_called', new RunToolCallItem(
  { type: 'function_call', name: 'topicSearch', callId: 'call_…', arguments: '{"q":"sports"}' },
  agent,
));

// Active agent changed (handoff)
new RunAgentUpdatedStreamEvent(billingAgent);

// Terminal (synthetic — completion is observed by iterator end)
{ type: 'response_done', response: { id, usage, output } }
```

---

## 4. Agent Runtime (Multi-session Host)

### 4.1 Multi-session host architecture

**Not provided — BYO.** There is no first-party multi-session runtime. The `Runner` class is per-run config + an event emitter; **you** spin up the host process and embed it in your own server. The `examples/nextjs/src/app/api/basic/route.ts` example illustrates the recommended pattern: one `Runner` per request, no shared loop state across requests.

### 4.2 Concurrent session isolation

State isolation is **per-`RunState`**: each `run()` invocation constructs a fresh `RunState` (`run.ts:769-780`). `RunContext<TContext>` carries your app context (`runContext.context`) and is mutable; **you** decide what to put there per call. Because there is no shared runtime, isolation is trivially correct as long as you don't share mutable objects across runs.

Approvals and usage are shared between a parent `RunContext` and forked nested contexts (`packages/agents-core/src/runContext.ts:140-152`), but the `context` (app data) is shared by reference.

### 4.3 Horizontal scaling / multi-instance

Stateless: as long as session state lives in an external store (your custom `Session` impl backed by Postgres/Redis), any number of pods can serve the same session pool. No leader election, no shared in-process state. `RunState.toString()` / `RunState.fromString()` (`packages/agents-core/src/runState.ts`) lets you serialize a paused run to any KV store; `examples/nextjs/src/app/api/basic/route.ts:83` writes it to a generic `db().set(conversationId, ...)`.

### 4.4 Background / async / scheduled tasks

**Not provided — BYO.** No cron, no webhook trigger primitives, no queues. Run a worker process (BullMQ, AWS SQS, etc.) and call `run()` from inside it.

### 4.5 Worker pool / queue model

Not provided. The SDK assumes short-lived HTTP request scope by default. Long-running agents need a serialized `RunState` checkpoint pattern (HITL example at `examples/agent-patterns/human-in-the-loop.ts:81-106`).

---

## 5. Sessions & Persistence

### 5.1 Session / chat data model

`Session` is a minimal interface:

```ts
// packages/agents-core/src/memory/session.ts:27-74
export interface Session {
  getSessionId(): Promise<string>;
  getItems(limit?: number): Promise<AgentInputItem[]>;
  prepareHistoryItemForModelInput?(item: AgentInputItem): AgentInputItem;
  preserveReasoningItemIdsForPersistence?(): boolean;
  addItems(items: AgentInputItem[]): Promise<void>;
  popItem(): Promise<AgentInputItem | undefined>;
  clearSession(): Promise<void>;
}
```

A session is just `{ sessionId: string, items: AgentInputItem[] }`. No first-class `tenant_id`, `user_id`, `cwd`, `model`, `metadata`, `usage`, or `summary` fields — those live in your context or in metadata you bolt onto the session yourself.

### 5.2 What's stored on a session

`AgentInputItem[]` — the full message history including user inputs, assistant outputs, function-call items, tool-call results, hosted-tool calls, reasoning items, etc. No scratchpad files, no embedded memory, no attachments. Reasoning-item IDs are persistable via an opt-in (`preserveReasoningItemIdsForPersistence`).

### 5.3 Granularity

Single linear conversation per session. **No fork / branch model.** No parent_session_id. If you need branching you implement a graph layer on top.

### 5.4 Built-in persistence stores

- `MemorySession` — in-process arrays (`packages/agents-core/src/memory/memorySession.ts:20-92`). For demos/tests.
- `OpenAIConversationsSession` — calls OpenAI's Conversations API. Conversation history lives in OpenAI's backend (`packages/agents-openai/src/memory/openaiConversationsSession.ts`).
- `OpenAIResponsesCompactionSession` — wraps another `Session` and calls OpenAI `responses.compact` to shrink history (`packages/agents-openai/src/memory/openaiResponsesCompactionSession.ts`).
- **No SQLite / no Postgres / no Redis / no S3 / no JSONL on disk built-in.**
- Example custom adapters (BYO): `examples/memory/sessions/file.ts` (filesystem JSON), `examples/memory/prisma.ts` (Prisma adapter).

### 5.5 Persistence timing

- Non-streaming: a single `session.addItems()` call after `runResult` resolves, persisting both the original user input and the model outputs (`packages/agents-core/src/runner/sessionPersistence.ts`, `docs/src/content/docs/guides/sessions.mdx:86`).
- Streaming: user input is written first (after guardrails complete), then streamed outputs are appended when the turn completes (docs line 87).
- Sync only — no `durability='sync'|'async'` switch. Persistence happens via the `Session` impl which can be sync or async at its own discretion.

### 5.6 Mid-run checkpointing (durable)

**No automatic mid-tool-call durability.** If your process crashes during a `tool.execute` it cannot resume.

The closest equivalent is **HITL state serialization**: when a tool needs approval (`needsApproval: true`), the run halts and returns a `RunResult.state` you can serialize via `state.toString()` / `RunState.fromString(agent, str)` and re-run with `run(agent, state)`. See `examples/agent-patterns/human-in-the-loop.ts:81-106` and `examples/nextjs/src/app/api/basic/route.ts:83`. Not a substitute for LangGraph-style per-tool checkpoints.

### 5.7 Session ID format

`MemorySession` generates `randomUUID()` (`memorySession.ts:27`). `OpenAIConversationsSession` generates `conv_<random>` IDs server-side. The format is implementation-defined; the interface only requires a `string`.

### 5.8 Pluggable store interface

Yes. Implement the `Session` interface and pass via `options.session`. The interface is short (7 methods) and `examples/memory/sessions/file.ts` is a complete 119-line reference implementation. Optional extension interfaces:

- `SessionHistoryRewriteAwareSession` (`session.ts:76-78`) — supports `applyHistoryMutations({ mutations: SessionHistoryMutation[] })` (e.g., `replace_function_call`).
- `OpenAIResponsesCompactionAwareSession` (`session.ts:112-128`) — supports `runCompaction()`.

### 5.9 Schema evolution / migration

`AgentInputItem` is a Zod-validated discriminated union (`protocol.ModelItem` at `protocol.ts:815-833`) with an `UnknownItem` fallback for forward compatibility (`protocol.ts:786-790`). Schema mismatches throw at parse time when reading from your store. No migration helpers shipped; you author your own.

### 5.10 Export / replay

Yes:

- `RunResult.history` and `RunResult.state` are serializable via JSON (`state.toJSON()` is implemented across `runState.ts`).
- `RunState.fromString(agent, json)` rebuilds a state for replay (`packages/agents-core/src/runState.ts`).
- The Traces dashboard at `platform.openai.com/traces` provides a hosted replay viewer (`docs/src/content/docs/guides/tracing.mdx:12`).

### 5.11 Cross-session memory

Not first-class. Cross-reference Q17. The `Session` interface is per-conversation; for cross-session semantic memory the docs and SDK don't ship anything (no embeddings, no vector store integration).

---

## 6. Multi-tenancy & Arbitrary Context ⭐ THE KEY QUESTION

### 6.1 Full run-loop input struct

```ts
// packages/agents-core/src/run.ts:318-339
type SharedRunOptions<TContext, TAgent> = {
  context?: TContext | RunContext<TContext>;
  maxTurns?: number | null;
  signal?: AbortSignal;
  previousResponseId?: string;
  conversationId?: string;
  session?: Session;
  sessionInputCallback?: SessionInputCallback;
  callModelInputFilter?: CallModelInputFilter;
  toolErrorFormatter?: ToolErrorFormatter;
  reasoningItemIdPolicy?: ReasoningItemIdPolicy;
  tracing?: TracingConfig;
  sandbox?: SandboxRunConfig;
  toolExecution?: ToolExecutionConfig;
  errorHandlers?: RunErrorHandlers<TContext, TAgent>;
};
```

Plus `stream?: boolean` on the streaming variant. Your arbitrary tenant context goes in `context` (typed `TContext`).

### 6.2 Context propagation into a tool call

`Runner.run()` constructs a `RunContext<TContext>` wrapping `options.context` (`run.ts:771-774`). On every tool invoke, that same `RunContext` is passed as the second argument:

```ts
// packages/agents-core/src/tool.ts:1806-1845
async function _invoke(runContext: RunContext<Context>, input: string, details?: ToolCallDetails) {
  const [error, parsed] = await safeExecute(() => parser(input));
  if (error !== null) throw new InvalidToolInputError(…);
  const result = await options.execute(parsed, runContext, details);
  …
}
```

So `tool({ execute: async (args, runContext) => …runContext.context.tenantId… })` is the standard pattern.

### 6.3 Tool call interface

```ts
// packages/agents-core/src/tool.ts:1397
execute: ToolExecuteFunction<TParameters, Context>;
// signature: (parsedInput, runContext, details) => Promise<Result>
```

Plus `needsApproval?: boolean | ToolApprovalFunction<TParameters>`, `isEnabled?: boolean | ((args: { runContext, agent }) => boolean | Promise<boolean>)`, `errorFunction?: ToolErrorFunction | null`, per-tool guardrails. Real code:

```ts
// examples/docs/context/localContext.ts:9-19
const fetchUserAge = tool({
  name: 'fetch_user_age',
  description: 'Return the age of the current user',
  parameters: z.object({}),
  execute: async (_args, runContext?: RunContext<UserInfo>): Promise<string> => {
    return `User ${runContext?.context.name} is 47 years old`;
  },
});
```

### 6.4 Forcing tool arguments from the harness

**Two ways, both have limits.**

1. **Server-side forcing inside `execute`**: ignore the LLM's arg and substitute from context. Simple and bulletproof:
   ```ts
   const topicSearch = tool({
     name: 'topicSearch',
     parameters: z.object({ q: z.string(), tenantId: z.string().optional() }),
     execute: async ({ q }, ctx: RunContext<{ tenantId: string }>) => {
       // Ignore any tenantId the LLM passed; use the trusted ctx one.
       return await searchTopics({ q, tenantId: ctx.context.tenantId });
     },
   });
   ```
2. **`callModelInputFilter`** (`packages/agents-core/src/runner/conversation.ts:31-33`) — runs before every model call and lets you mutate the input items + system instructions, but **operates on messages, not pending tool args**. So it cannot intercept LLM-generated tool arguments after the model emits them.

There is **no `PreToolUse` hook** (à la Claude Agent SDK's `updatedInput`) that mutates the LLM-emitted JSON args mid-loop. The standard pattern is approach (1) — ignore-and-override inside `execute`, often paired with `isEnabled` to make the tool invisible when the trusted context is missing.

### 6.5 Filtering visible tools

Yes — first-class. Per-tool `isEnabled`:

```ts
// packages/agents-core/src/tool.ts:1411-1414
isEnabled?:
  | boolean
  | ((args: { runContext, agent }) => boolean | Promise<boolean>);
```

Evaluated at turn-prep time in `Agent.getAllTools(runContext)`:

```ts
// packages/agents-core/src/agent.ts:1038-1064
async getAllTools(runContext: RunContext<TContext>): Promise<Tool<TContext>[]> {
  const mcpTools = await this.getMcpTools(runContext);
  const enabledTools: Tool<TContext>[] = [];
  for (const candidate of this.tools) {
    if (candidate.type === 'function') {
      const enabled = typeof candidate.isEnabled === 'function'
        ? await candidate.isEnabled(runContext, this)
        : candidate.isEnabled ?? true;
      if (!enabled) continue;
    }
    enabledTools.push(candidate);
  }
  return [...mcpTools, ...enabledTools];
}
```

Handoffs support an `isEnabled` predicate too (`agent.ts:1075-1086`). Note: hosted/MCP tools are not filtered by `isEnabled` directly — MCP tool filters come from `MCPServer.toolFilter` (`packages/agents-core/src/mcp.ts:64`).

### 6.6 Tenant scope on session

Not first-class. The `Session` interface has only `sessionId: string`. Encode tenant info either in the `sessionId` (e.g., `acme:user-123:thread-…`) or via your custom `Session` impl that scopes reads by tenant out-of-band.

### 6.7 Per-tool-call auth propagation

Whatever you put in `runContext.context` is automatically reachable from every tool, lifecycle hook, guardrail, and handoff (`docs/src/content/docs/guides/context.mdx:24`: "Every agent, tool and hook participating in a single run must use the same type of context."). The SDK does not perform an HTTP-auth-like check at the tool boundary; you do it inside `execute`.

### 6.8 Resource scoping primitives

Not provided — there's no registration-time scope (no "this tool belongs to tenant X"). Filtering is runtime-only via `isEnabled` / handoff `isEnabled` / `callModelInputFilter`.

### 6.9 Per-tenant rate limit + budget cap

**Not provided — BYO.** The SDK surfaces token usage (`RunContext.usage`, `RunResult.state._context.usage`) but doesn't enforce caps. You enforce ceilings either in an `agent_tool_start` listener that throws, or in a custom `Model` wrapper that pre-checks usage. There is no USD budget cap — only token counters.

### ⭐ Required light usage example

```ts
import { Agent, run, tool, RunContext } from '@openai/agents';
import { z } from 'zod';

type TenantCtx = { tenantId: string; targetingStrategyId: string; userId: string };

const topicSearch = tool({
  name: 'topicSearch',
  description: 'Search topics for the current tenant',
  parameters: z.object({ q: z.string() }),
  execute: async ({ q }, ctx: RunContext<TenantCtx>) =>
    await searchTopics({ q, tenantId: ctx.context.tenantId }), // forced server-side
});

const iabSearch = tool({
  name: 'iabSearch',
  description: 'Search IAB taxonomy',
  parameters: z.object({ q: z.string() }),
  execute: async ({ q }, ctx: RunContext<TenantCtx>) => searchIab({ q, tenantId: ctx.context.tenantId }),
});

const audienceCreate = tool({
  name: 'audienceCreate',
  description: 'Create an audience',
  parameters: z.object({ name: z.string(), segments: z.array(z.string()) }),
  execute: async ({ name, segments }, ctx: RunContext<TenantCtx>) =>
    createAudience({ name, segments, tenantId: ctx.context.tenantId }),
});

const bashExec = tool({
  name: 'bashExec',
  description: 'Run a shell command',
  parameters: z.object({ cmd: z.string() }),
  isEnabled: ({ runContext }: { runContext: RunContext<TenantCtx> }) =>
    runContext.context.tenantId === 'internal-ops', // hidden for most tenants
  execute: async ({ cmd }) => execBash(cmd),
});

const agent = new Agent<TenantCtx>({
  name: 'predict-agent',
  instructions: 'You help marketers build predictive audiences.',
  tools: [topicSearch, iabSearch, audienceCreate, bashExec],
});

// 1. + 2. Pass tenantId etc.; 3. Force tenantId server-side; bashExec is hidden via isEnabled.
const result = await run(agent, 'Build a sports audience for our acme tenant.', {
  context: { tenantId: 'acme', targetingStrategyId: 'strat-42', userId: 'u-123' },
});
```

Notes:

- Step 3 (forcing `tenantId`) is implemented by **ignoring the LLM's args** and pulling from `ctx.context`. There is no `PreToolUse` hook that rewrites JSON args before dispatch. If you need to additionally hide `tenantId` from the LLM-visible parameter schema, just omit it from `parameters` and read it from the context.

---

## 7. Hook & Middleware Capabilities (Context Engineering)

### 7.1 Enumerate every hook / middleware / lifecycle callback

| Hook / Mechanism | Fires when | Capability |
| --- | --- | --- |
| `RunHooks.on('agent_start', …)` | Before each turn starts | read only (`lifecycle.ts:118`) |
| `RunHooks.on('agent_end', …)` | After final output | read |
| `RunHooks.on('agent_handoff', …)` | At handoff | read |
| `RunHooks.on('agent_tool_start', …)` | Before tool invoke | read; can throw to abort |
| `RunHooks.on('agent_tool_end', …)` | After tool invoke | read |
| `AgentHooks.on(…)` | Per-agent equivalents | read |
| `InputGuardrail.execute` | Input guardrail | read; can trigger tripwire to halt run (`guardrail.ts`) |
| `OutputGuardrail.execute` | Final-output guardrail | read; can trigger tripwire |
| `ToolInputGuardrail.execute` | Before per-tool invoke | read **+ mutate input or block** (`packages/agents-core/src/toolGuardrail.ts`) |
| `ToolOutputGuardrail.execute` | After per-tool invoke | read **+ mutate output or block** |
| `RunConfig.callModelInputFilter` | Before each model call | mutate `{ input, instructions }` (`runner/conversation.ts:31-33`) |
| `RunConfig.sessionInputCallback` | When merging session history with new input | replace combined input |
| `RunConfig.toolErrorFormatter` | When tool throws / approval-rejected | rewrite the model-visible error message (`run.ts:173-175`) |
| `RunConfig.errorHandlers` | On run errors | branch / recover (`runner/errorHandlers.ts`) |
| `tool({ needsApproval })` | Per-tool approval | halt run with `interruption`; resume via `state.approve / state.reject` |
| `Agent.asTool({ onStream })` | Streamed events from a nested agent-as-tool run | observer |
| `HandoffInputFilter` | When handing off to another agent | edit input history for next agent (`handoff.ts:44`) |
| `ToolApprovalFunction` | Conditional approval | predicate |

### 7.2 Hook concurrency model

- `RunHooks` / `AgentHooks` are EventEmitters → listeners fire synchronously in registration order; awaits aren't awaited by the loop.
- `inputGuardrails` run **in parallel** with the agent by default (`InputGuardrail.runInParallel = true`, `guardrail.ts:72-77`), tripwire stops the run.
- `callModelInputFilter` runs serially once per model call, awaited.

### 7.3 Specific capability tests

| Capability | Status | Code |
| --- | --- | --- |
| Inject system messages at session start | ✅ via `agent.instructions` (string or `(ctx, agent) => string`) (`agent.ts:285-290`); alternatively via `callModelInputFilter` mutating `instructions` |
| Expand user input (slash commands, time-stamp) | ✅ via `sessionInputCallback` or `callModelInputFilter` |
| Mutate messages list before each LLM call | ✅ `callModelInputFilter` (`conversation.ts:31-33`): returns `{ input, instructions }` |
| Mutate / decorate tool input before dispatch | 🟡 partial. `ToolInputGuardrail` can throw to block, but mutating the LLM-emitted JSON args is not directly supported via a hook; do it inside `execute`. |
| Mutate / decorate tool result before it returns to the LLM | ✅ `ToolOutputGuardrail` can replace the result |
| Emit additional tool calls in response to a tool result | ❌ no equivalent to Claude Agent SDK's `additional_messages`. You'd need to chain via handoff or wrap in `Agent.asTool`. |

### 7.4 Auto-compaction

Yes via `OpenAIResponsesCompactionSession` wrapper (`packages/agents-openai/src/memory/openaiResponsesCompactionSession.ts`). Calls `responses.compact` on the OpenAI side. Triggered after each completed turn with configurable thresholds (`OpenAIResponsesCompactionArgs.force`, `compactionMode`, `responseId`). Not built into `MemorySession` or generic stores.

### 7.5 Prompt cache optimization

Not first-class. The SDK passes `previousResponseId` to OpenAI's Responses API (server-side caching benefit), but doesn't manage Anthropic-style `cache_control` breakpoints. The `ai-sdk` extension's caching is whatever the underlying Vercel AI SDK provider supports.

### 7.6 Tool result clearing / progressive disclosure

Not first-class outside of Sandbox Agents. Sandbox Agents have a filesystem workspace where tools can write large outputs to disk and reference them by path. Non-sandbox tools just return their result string to the LLM.

### 7.7 Architectural diagram of where hooks fire

```
run(agent, input, options)
   │
   │  ── input guardrails (parallel) ──── tripwire? halt ──►
   ▼
prepareTurn → sessionInputCallback → buildTurnInput
   │
   │  ── emit 'agent_start' ──►
   ▼
prepareAgentArtifacts: Agent.getAllTools() applies isEnabled filters
   │
   ▼
prepareModelCall: applyCallModelInputFilter({ modelData, agent, context })
   │
   ▼
Model.getResponse  ◄── retry / fallback in modelRetry
   │
   ▼
processModelResponse → split into messages, tool calls, handoffs
   │
   ▼
for each tool call:
   ├── ToolInputGuardrail.execute  (mutate / block)
   ├── needsApproval? → halt with interruption
   ├── tool.execute(args, runContext, details)
   │      └─ emit 'agent_tool_start' / 'agent_tool_end'
   └── ToolOutputGuardrail.execute  (mutate / block)
   │
   ▼
resolveTurn → next step
   ├── final_output → output guardrails → emit 'agent_end'
   ├── handoff → HandoffInputFilter → switch agent → emit 'agent_handoff'
   ├── interruption → return RunResult (resume later)
   └── run_again → back to prepareTurn
```

### ⭐ Required light usage example

```ts
import { Agent, run, tool, Runner } from '@openai/agents';
import { z } from 'zod';

// (1) "SessionStart"-style system context: agent.instructions function runs each turn.
const agent = new Agent({
  name: 'predict-agent',
  instructions: (ctx /* RunContext */) =>
    `Tenant=${ctx.context.tenantId}, locale=${ctx.context.locale}, today=2026-05-16`,
  tools: [/* topicSearch, etc. */],
});

// (2) "PreToolUse"-style forced args: server-side override inside execute.
const topicSearch = tool({
  name: 'topicSearch',
  parameters: z.object({ q: z.string() }),
  execute: async ({ q }, ctx) => searchTopics({ q, tenantId: ctx.context.tenantId }),
});

// (3) PostToolUse-style summarisation via a ToolOutputGuardrail
import { defineToolOutputGuardrail } from '@openai/agents';
const summarizeIfLarge = defineToolOutputGuardrail({
  name: 'summarize-large-topicSearch',
  async execute({ result, toolName }) {
    if (toolName === 'topicSearch' && Array.isArray(result) && result.length > 50) {
      return { result: result.slice(0, 5).concat([`…and ${result.length - 5} more`]) };
    }
    return { result };
  },
});

const topicSearchWithGuard = tool({ ...topicSearch, outputGuardrails: [summarizeIfLarge] });

const runner = new Runner({});
await run(agent, 'List sports topics.', {
  context: { tenantId: 'acme', locale: 'fr-FR' },
});
```

---

## 8. HTTP API

### 8.1 Does the framework ship an HTTP server?

**No.** Library-only. You bring Next.js, Express, Hono, Fastify, Cloudflare Workers, etc. The reference is `examples/nextjs/src/app/api/basic/route.ts`. No `@openai/agents-server` package exists.

### 8.2 HTTP streaming transport

Not provided — BYO HTTP layer. The SDK streams **inside your process** via async iteration over `RunStreamEvent`. There is no built-in SSE / WebSocket / HTTP framing — you serialize events to whatever wire format you choose.

The companion `@openai/agents-extensions/ai-sdk-ui` package provides UI message stream helpers (`packages/agents-extensions/src/ai-sdk-ui/uiMessageStream.ts`, `textStream.ts`) that adapt a `StreamedRunResult` to Vercel AI SDK's `useChat` SSE format.

### 8.3 HTTP endpoints that start an agent run

Not provided — BYO. Closest example:

```ts
// examples/nextjs/src/app/api/basic/route.ts:13-31
export async function POST(req: NextRequest) {
  const { messages, conversationId, decisions } = await req.json();
  …
  const runner = new Runner({ groupId: conversationId });
  const result = await runner.run(agent, messages);
  return NextResponse.json({ response: result.finalOutput, history: result.history, conversationId });
}
```

### 8.4 Live agentic event stream format

Not provided — you choose. With the `ai-sdk-ui` extension you get Vercel's SSE wire format. Otherwise, common pattern: iterate `streamedRunResult` and pipe `event.type === 'raw_model_stream_event'` deltas to SSE `data:` frames.

### 8.5 Auth termination at the HTTP boundary

Not provided. You handle JWT / API key validation in your host's middleware before calling `run()`.

### 8.6 Resume / replay endpoint

Not provided as an endpoint, but the data-plane primitive exists: `RunState.toString()` → store keyed by `conversationId`/`sessionId` → `RunState.fromString(agent, str)` → `run(agent, state)`. See `examples/nextjs/src/app/api/basic/route.ts:36-77` for the recipe.

### 8.7 Interrupt / cancel via HTTP

Not provided — BYO HTTP layer. The data-plane primitive: `options.signal: AbortSignal` (`run.ts:324`) propagates abort into the model call (`run.ts:966`) and to tool executions through `details.signal`. Pattern: have your route attach `request.signal` to `options.signal`. No DELETE / cancel endpoint, no first-party `/cancel/<runId>`.

### 8.8 Tool-arg streaming (partial JSON)

Provider-dependent. Raw model events surface as `RunRawModelStreamEvent` with the underlying provider event under `event.data.event`, so if the provider streams partial tool args you'll see them. The SDK itself does not normalize this into a typed "tool-call-delta" event.

### 8.9 HITL approval workflow over HTTP

Not provided as a server endpoint. The data-plane mechanism: when a tool with `needsApproval: true` is called, the run returns with `result.interruptions: RunToolApprovalItem[]`. You serialize `result.state`, present approvals to the user, then on the next request call `state.approve(interruption)` / `state.reject(interruption)` and re-run with `run(agent, state)`. Full example at `examples/agent-patterns/human-in-the-loop.ts`. The HTTP shape is whatever you design (the Next.js example uses a `decisions: { callId: 'approved'|'rejected' }` payload on the same POST).

### 8.10 Tool-call state reconstruction ⭐

`RunToolCallItem` carries `rawItem: protocol.ToolCallItem` with `.callId` (or `.id` fallback). Matching tool-call ↔ tool-result is by **explicit `callId`** (`items.ts:66-75`). On the wire, the corresponding `FunctionCallResultItem` carries the same `callId` field (`protocol.ts`, see `FunctionCallResultItem`). So a client renders a tool by joining `tool_called` event with its later `tool_output` event on `callId`.

### 8.11 Health checks / graceful shutdown

Not provided. You add `/healthz` to your HTTP framework. The SDK exposes `getGlobalTraceProvider().forceFlush()` for trace flush on shutdown (recommended for Cloudflare Workers; `docs/src/content/docs/guides/tracing.mdx:30-43`).

### ⭐ Required light usage example

```bash
# (1) Start a run — call your own Next.js route
curl -X POST https://your-app/api/basic \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: acme' \
  -d '{"messages":[{"role":"user","content":[{"type":"input_text","text":"Build me an audience"}]}]}'

# (2) SSE frames (with ai-sdk-ui extension):
data: {"type":"text-delta","textDelta":"Hello"}
data: {"type":"tool-call","toolCallId":"call_abc","toolName":"topicSearch","args":{"q":"sports"}}
data: {"type":"finish","finishReason":"stop"}

# (3) Cancel: your route must hold the AbortController and respond to client disconnect.
# Pattern: pass req.signal into options.signal. No built-in endpoint.

# (4) HITL approval — your route again. The SDK has no endpoint shape.
curl -X POST https://your-app/api/basic \
  -H 'Content-Type: application/json' \
  -d '{"conversationId":"conv_xyz","decisions":{"call_abc":"approved"}}'
```

Step 3 and 4 are not first-party endpoints. They're DIY routes following the reference at `examples/nextjs/src/app/api/basic/route.ts`. **Not provided — BYO HTTP layer** for the framework-shipped sub-bullets above; the example shows the recommended host-side pattern.

---

## 9. Sub-agents

### 9.1 Mechanism

**Both** mechanisms exist:

1. **Handoffs** (first-class transfer) — `Agent.handoffs: (Agent | Handoff)[]`. The LLM picks one via a synthesized `transfer_to_<agent>` tool; the loop switches `state._currentAgent` (`run.ts:1055-1067`) and continues with the new agent's instructions and tools.
2. **Agents as tools** (`Agent.asTool({ … })`) — wraps an agent as a `FunctionTool` named e.g. `translate_to_spanish`. The parent calls it like any other tool; the agent runs nested via `Runner.run` and returns its final output as the tool result (`packages/agents-core/src/agent.ts:103-166`).

### 9.2 Configuration

- Statically registered TypeScript objects at module load. No markdown-file sub-agent format.
- `Agent.create({ name, handoffs: […] })` or `Agent.asTool({ toolName, toolDescription, parameters, … })`.

### 9.3 LLM-generated configs

**Not provided.** Sub-agents are statically declared TypeScript. You cannot have the parent LLM generate a fresh `system prompt + tools` and spawn a child at runtime. Closest: parameterize via `Agent.asTool({ parameters, inputBuilder })` so the parent passes structured input that influences sub-agent behavior, but the sub-agent code itself is fixed.

### 9.4 Output handling

- Handoff: the new agent takes over; output is the new agent's final output, linked back via `RunAgentUpdatedStreamEvent`.
- `asTool`: the nested agent's final output becomes the function tool result (string by default, customizable via `customOutputExtractor`). Linked back to the parent via the `tool_use_id` of the wrapping `FunctionCallItem`. The full nested `RunResult` is exposed on `FunctionToolResult.agentRunResult` (`tool.ts:1178-1187`).

### 9.5 Concurrency model

Concurrent — `Agent.asTool` invocations issued in a single turn dispatch in parallel up to `toolExecution.maxFunctionToolConcurrency` (`run.ts:180-202`). The actual parallelism is in `runner/toolExecution.ts` (Promise.all across the tool-call array). Handoffs are sequential by definition (only one current agent).

### 9.6 Context isolation

Nested `Agent.asTool` runs **share** the parent's `RunContext.context`, approvals, and usage (`runContext.ts:140-152` `_cloneSharedState`). The `toolInput` on the fork is the structured input that triggered the nested run. So no isolation by default — useful if children should write back to a shared todo list, dangerous if you want strict separation.

### 9.7 Lifecycle events

Yes. `Agent.asTool({ onStream })` receives every `RunStreamEvent` from the nested run, plus a reference to the `toolCall` that triggered it (`agent.ts:89-100`).

### ⭐ Required light usage example

```ts
import { Agent, run, tool } from '@openai/agents';
import { z } from 'zod';

const topicSearch = tool({
  name: 'topicSearch',
  parameters: z.object({ q: z.string() }),
  execute: async ({ q }) => searchTopics(q),
});

const personaYoungMom = new Agent({
  name: 'persona-young-mom',
  instructions: 'You are a 32-year-old mom. Discover topics that match your interests.',
  tools: [topicSearch],
});
const personaTechBro = new Agent({
  name: 'persona-tech-bro',
  instructions: 'You are a 27-year-old SF engineer. Discover topics that match your interests.',
  tools: [topicSearch],
});
const personaRetiree = new Agent({
  name: 'persona-retiree',
  instructions: 'You are a 67-year-old retiree. Discover topics that match your interests.',
  tools: [topicSearch],
});

const orchestrator = new Agent({
  name: 'orchestrator',
  instructions: 'Run all three personas in parallel and merge their topic lists.',
  tools: [
    personaYoungMom.asTool({ toolName: 'persona_young_mom', toolDescription: 'Topics for a young mom' }),
    personaTechBro.asTool({ toolName: 'persona_tech_bro', toolDescription: 'Topics for a tech bro' }),
    personaRetiree.asTool({ toolName: 'persona_retiree', toolDescription: 'Topics for a retiree' }),
  ],
});

// Parent receives each result inside result.newItems (RunToolCallOutputItem entries),
// or via streamed events when run with { stream: true }.
const result = await run(orchestrator, 'Build a cross-generational audience.');
```

---

## 10. Skills

### 10.1 First-class concept?

**Yes — but only inside Sandbox Agents.** Outside the `SandboxAgent` flavor, "skills" are not a thing in this SDK. Skills are exposed as a **capability** on a `SandboxAgent`'s manifest (`packages/agents-core/src/sandbox/capabilities/skills.ts:50`).

### 10.2 File format

`SKILL.md` with YAML frontmatter, à la Claude Code. Parsed by `parseSkillFrontmatter(markdown)` (`packages/agents-core/src/sandbox/capabilities/skills.ts:69`). Schema:

```ts
// derived from packages/agents-core/src/sandbox/capabilities/skills.ts:21-41
type SkillIndexEntry = {
  name: string;          // skill name
  description: string;   // one-liner shown to the model
  path?: string;         // directory under .agents/
};

type SkillDescriptor = {
  name: string;
  description: string;
  content: string | Uint8Array | File | LocalFile;
  scripts?: Record<string, Entry>;
  references?: Record<string, Entry>;
  assets?: Record<string, Entry>;
  compatibility?: string[];
  deferred?: boolean;
};
```

### 10.3 Loader mechanism

Three sources:

1. **Inline** — `skills([{ name, description, content, … }])` registered programmatically.
2. **Filesystem** — `localDirLazySkillSource({ src: './skills' })` (`packages/agents-core/src/sandbox/localSkills.ts:25-36`). Walks a directory, reads each subfolder's `SKILL.md`, builds an index.
3. **GitRepo** — `gitRepo({ repo, ref })` source attached to a manifest entry (`README.md:46` shows this in the quickstart).

### 10.4 Invocation

**System-prompt injection** for the skill index + **tool invocation** for lazy materialization. The skills capability injects an "available skills" section into the agent's instructions via `Capability.instructions(manifest)` (`skills.ts:194-211`). When loaded lazily, the agent also gets a `load_skill` tool to materialize the skill files on demand (`skills.ts:72-145`).

### 10.5 Loading mode

Both supported:

- **Eager** — `skills({ skills: [...] })` or `skills({ from: dir(…) })` materializes everything into `.agents/<skill>/` and shows full metadata to the model.
- **Lazy** — `skills({ lazyFrom: localDirLazySkillSource({…}) })` shows only the index in the system prompt; the model calls `load_skill({ skill_name })` when it decides to use one.

### 10.6 Runtime scoping (global / tenant / user)

You can attach a different `defaultManifest` per-`SandboxAgent`, or override at run-time via `options.sandbox.manifestPatch`. There is no built-in tenant-aware skill catalog. You'd compose a manifest yourself based on `runContext.context.tenantId` before passing it.

### 10.7 Skill composition

Skills can bundle `scripts/`, `references/`, `assets/` (see `SkillDescriptor` above). The injected instructions explicitly tell the model: "If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed", "If `scripts/` exist, prefer running or patching them", "If `assets/` or templates exist, reuse them" (`skills.ts:269-291`). Skills can therefore reference scripts and assets they ship with. Skills cannot directly "call" other skills, but the lazy loader lets them request loading another skill at runtime.

### ⭐ Required light usage example

```
# 1. ./skills/Generate-Audience-From-Brief/SKILL.md
---
name: Generate-Audience-From-Brief
description: Turn a marketer brief into a structured audience definition with segment IDs.
---

When the user describes an audience in prose, decompose it into:
1. Demographics (age, gender, geo)
2. Interests (call topicSearch for each)
3. Behavioral signals (call iabSearch)
Then emit a JSON object { name, segments[] } and stop.
```

```ts
// 2. Load it at runtime via SandboxAgent + lazyFrom
import { run } from '@openai/agents';
import { SandboxAgent } from '@openai/agents/sandbox';
import { UnixLocalSandboxClient } from '@openai/agents/sandbox/local';
import { skills, localDirLazySkillSource } from '@openai/agents-core/sandbox';

const agent = new SandboxAgent({
  name: 'predict-agent',
  instructions: 'You build predictive audiences for marketers.',
  capabilities: [
    skills({
      lazyFrom: localDirLazySkillSource({ src: './skills' }),
    }),
  ],
});

// 3. Agent discovers skills via the injected system prompt index, then materializes
//    the chosen skill via the load_skill tool, then reads SKILL.md from the workspace.
const result = await run(
  agent,
  'Build me a young-mom audience around back-to-school products.',
  { sandbox: { client: new UnixLocalSandboxClient() } },
);
```

The LLM sees the skill list in the system prompt and calls the `load_skill` tool to fetch the body. From the model's perspective, the skill is a **system-prompt fragment with a fetch tool**, not a single tool invocation.

---

## 11. Resource Manager

### 11.1 First-class Resource Manager?

**No — BYO.** There is no registry, no versioning, no publishing workflow, no marketplace, no source abstraction outside of the per-`SandboxAgent` `manifest.entries` (which is a local concept tied to one agent's filesystem).

### 11.2 Loading sources

Per `manifest.entries` (`packages/agents-core/src/sandbox/entries`):

- **Local filesystem** — `localDir({ src })` / `localFile({ src })`, scoped by `extraPathGrants` for paths outside the project base directory (changelog 0.11.0).
- **Inline** — `dir(…)` / `file(…)` with literal content.
- **Git / GitHub repos** — `gitRepo({ repo: 'openai/openai-agents-js', ref: 'main', subpath? })`. Cloned into the sandbox session.
- **OCI / container registries**: ❌ not provided.
- **Cloud object storage (S3 / GCS / Azure / R2 / Vercel Blob)**: ❌ not provided.
- **Postgres / relational DB**: ❌ not provided.
- **Vendor cloud / managed registry**: ❌ not provided. OpenAI does not ship a "skills hub".
- **HTTP fetch**: ❌ not first-class. You'd write to disk before referencing.

### 11.3 Source composition / priority

Per-manifest only. A `SandboxAgent` has one `defaultManifest`; merging is `cloneManifest` + capability `processManifest` (`packages/agents-core/src/sandbox/capabilities/skills.ts:147-192`). No `local > tenant > global` cascading.

### 11.4 Versioning model

`gitRepo({ ref })` lets you pin a git ref (branch / tag / SHA). No semver registry, no content-hash addressing beyond what git provides. No rollback primitive shipped.

### 11.5 Scoping at the registry layer

Not provided — there's no registry. Scoping is done implicitly by choosing which manifest to pass for which agent / tenant in your application code.

### 11.6 Publishing workflow

Not provided. No draft / review / publish / promote stages, no multi-environment story.

### 11.7 Lifecycle / governance

Not provided. No draft / active / deprecated / retired states; no RBAC.

### 11.8 Programmatic API

`Manifest` class is the closest thing (`packages/agents-core/src/sandbox/manifest.ts`). You can build / clone / patch manifests in code, but there is no `registry.list()`, no `registry.search()`, no `registry.publish()`.

### 11.9 Caching & sync model

Caching is whatever your filesystem / git client does. The sandbox session materializes manifest entries on first access. No watcher / hot-reload primitive.

### ⭐ Required light usage example

**Not provided — BYO.** Closest illustration:

```ts
// Not a registry — just composing two manifests by hand.
import { gitRepo, localDir } from '@openai/agents-core/sandbox';
import { skills } from '@openai/agents-core/sandbox';

function tenantManifest(tenantId: string) {
  const globalSkills = skills({ lazyFrom: { source: gitRepo({ repo: 'dailymotion/predict-skills', ref: 'main' }) } });
  const tenantSkills = tenantId === 'acme'
    ? skills({ from: localDir({ src: `./s3-mirror/tenants/${tenantId}` }) }) // pre-synced from S3 to local
    : null;
  return { entries: {}, capabilities: [globalSkills, tenantSkills].filter(Boolean) };
}

// Step 1: composing tenant + global sources — you write this yourself.
// Step 2: "Promoting draft → active for tenant acme only" — no concept in the SDK.
//          You'd encode this as a folder convention in your S3 mirror.
// Step 3: "Listing all active skills visible to tenantId=acme" — call manifest.
//          For lazy sources, call lazyFrom.getIndex(manifest) and merge.
```

There is no engineered story here. If you need a multi-tenant skill library you ship the registry layer yourself.

---

## 12. Observability: Usage, Cost, Tracing, Audit

### 12.1 Where tokens are surfaced

On `RunContext.usage` (the `Usage` class) and accumulated across the run (`runContext.ts:113`, `run.ts:979` `state._context.usage.add(state._lastTurnResponse.usage)`). Also on `ModelResponse.usage` per call.

```ts
// packages/agents-core/src/usage.ts:91-110
export class Usage {
  public requests: number;
  public inputTokens: number;
  public outputTokens: number;
  public totalTokens: number;
  public inputTokensDetails: Array<Record<string, number>> = [];
  public outputTokensDetails: Array<Record<string, number>> = [];
  public requestUsageEntries: RequestUsage[] | undefined;
}
```

### 12.2 Per-call / per-turn / per-session / per-tenant rollups

- **Per-call**: `RequestUsage` entries (`Usage.requestUsageEntries`, `usage.ts:125`).
- **Per-turn / per-run**: aggregated `Usage` on `RunContext.usage`, available on `RunResult.state._context.usage`.
- **Per-session / per-tenant**: not provided by the SDK; you aggregate yourself in a custom `Session` impl or by reading `result.state._context.usage` after each run and tagging with your tenantId.

### 12.3 USD cost computation

**Not provided.** The SDK only reports tokens. You compute cost from your own pricing table.

### 12.4 Per-tenant / per-conversation cost

BYO via `groupId` (`RunConfig.groupId`) attached to traces so you can aggregate downstream. Inside the loop, attach the `tenantId` to `runContext.context` and aggregate per `groupId`.

### 12.5 LLM / tool tracing

- **First-party tracer** with batch processor and OpenAI exporter (`packages/agents-core/src/tracing/`).
- Spans: `AgentSpan`, `GenerationSpan`, `FunctionSpan`, `HandoffSpan`, `GuardrailSpan`, `MCPListToolsSpan`, `TranscriptionSpan`, `SpeechSpan` (`packages/agents-core/src/tracing/index.ts:22-37`).
- Default exporter → OpenAI Traces dashboard. Replace with `setTraceProcessors([new BatchTraceProcessor(yourExporter)])`.
- External integrations documented: AgentOps, Respan, PromptLayer (`docs/src/content/docs/guides/tracing.mdx:139-141`). No first-party LangSmith / Langfuse / OTel adapter shipped — those community integrations adapt to the SDK's `TracingProcessor` interface.
- **No OTel exporter built-in.**

### 12.6 Audit logging (who / when / what)

Tracing spans (with `traceIncludeSensitiveData: true`) capture LLM inputs/outputs and tool inputs/outputs (`docs/src/content/docs/guides/tracing.mdx:100-107`). For tamper-evident logging you build your own append-only sink and call `addTraceProcessor` to mirror.

### 12.7 Canonical "where do I read token counts" code path

```ts
// packages/agents-core/src/run.ts:979
state._context.usage.add(state._lastTurnResponse.usage);
// Then on the result:
const result = await run(agent, 'hello', { context });
console.log(result.state._context.usage.totalTokens, result.state._context.usage.requests);
```

### ⭐ Required light usage example

```ts
import { Agent, run, addTraceProcessor, BatchTraceProcessor } from '@openai/agents';

const agent = new Agent({ name: 'demo', instructions: 'Hi.' });

// (1) Read tokens for one completed run
const result = await run(agent, 'Hello!');
const u = result.state._context.usage;
console.log({
  tokens_in: u.inputTokens,
  tokens_out: u.outputTokens,
  total: u.totalTokens,
  // cost_usd: BYO from a pricing table since the SDK doesn't compute it
});

// (2) Push per-tenant token usage to a metric sink via a custom TracingProcessor
addTraceProcessor(new BatchTraceProcessor({
  async export(items) {
    for (const span of items) {
      if (span.spanData.type === 'generation' && span.spanData.usage) {
        datadog.metric('llm.tokens.total', span.spanData.usage.totalTokens, {
          tags: [`tenant:${span.metadata?.tenantId}`, `model:${span.spanData.model}`],
        });
      }
    }
  },
  async shutdown() {},
  async forceFlush() {},
}));
```

---

## 13. Built-in Tools & Tool Authoring API

### 13.1 Built-in tools shipped in the box

| Tool | Source | Purpose |
| --- | --- | --- |
| `webSearchTool` | `packages/agents-openai/src/tools.ts:71` | OpenAI hosted web search |
| `fileSearchTool` | `tools.ts:127` | OpenAI hosted vector store search |
| `codeInterpreterTool` | `tools.ts:176` | OpenAI hosted code interpreter |
| `imageGenerationTool` | `tools.ts:262` | OpenAI hosted image generation |
| `toolSearchTool` | `tools.ts:204` | Deferred tool loading (Responses API) |
| `hostedMcpTool` | `packages/agents-core/src/tool.ts:918` | Hosted MCP server (Responses API) |
| `computerTool` | core | Computer-use action wrapping (`shell.ts`, `editor.ts`) |
| Hosted **shell** capabilities | `tool.ts:92-165` | Local/container shell with skill bundles |
| Hosted **apply_patch** | core | Hosted patch operations |
| Sandbox `load_skill` (auto) | `sandbox/capabilities/skills.ts:81` | Lazy skill materialization |

There is **no built-in `Read`, `Edit`, `Write`, `Grep`, `Glob`, `Monitor`** like Claude Code. File operations only happen inside a `SandboxAgent`'s workspace via the sandbox shell capabilities (`packages/agents-core/src/sandbox/capabilities/filesystem.ts`).

### 13.2 Built-in tool quality

- Hosted tools are **thin wrappers** that build `providerData` and emit a `HostedTool` descriptor; actual execution happens server-side at OpenAI (`packages/agents-openai/src/tools.ts:71-91`).
- Sandbox shell capability is more substantive: it manages local/container shells, skill bundles, network policies (`tool.ts:117-165`).
- No Claude-Code-style anchor-matching `Edit` or Monitor-with-line-events.

### 13.3 Tool authoring API

```ts
import { tool } from '@openai/agents';
import { z } from 'zod';

const getWeatherTool = tool({
  name: 'get_weather',
  description: 'Get the weather for a given city',
  parameters: z.object({ city: z.string() }),
  async execute({ city }) {
    return `The weather in ${city} is sunny.`;
  },
});
```

Implementation: `tool()` (`packages/agents-core/src/tool.ts:1768-1934`) parses your Zod/JSON schema, wires JSON parse/validate of LLM args, wraps timeouts and error handling, and produces a `FunctionTool<Context, TParameters, Result>` (`tool.ts:223-289`).

### 13.4 Typed tool I/O

Zod or JSON schema (`tool.ts:1230-1233`). Zod-typed parameters with `strict: true` (default) trigger runtime validation; the LLM's args are `JSON.parse`'d and validated. Invalid args throw `InvalidToolInputError` (`tool.ts:1821-1826`) which is caught and routed through `errorFunction` (default returns a model-visible "Invalid tool input" message; the run continues so the LLM can retry).

### 13.5 Streaming tools

**Not first-class.** The `execute` function returns a `Promise<Result>`. There is no `yield`-based incremental output to the model. You'd have to buffer and return a final string. For long-running tools, use HITL approval pause as a poor substitute.

---

## 14. MCP (Model Context Protocol) Support

### 14.1 MCP client support

Yes, first-class. `agent.mcpServers: MCPServer[]` plus three built-in server types (`packages/agents-core/src/mcp.ts:63-82`):

- `MCPServerStdio`
- `MCPServerStreamableHttp`
- `MCPServerSSE` (legacy)

Tools from MCP servers are auto-merged into the agent's tools each run via `Agent.getMcpTools(runContext)` and `getAllMcpTools()` (`mcp.ts`).

### 14.2 MCP server support

The SDK **does not expose its own agent as an MCP server.** You can expose your tools as MCP via the upstream `@modelcontextprotocol/sdk` package directly, but this SDK provides no wrapper.

### 14.3 Transports

- **stdio** — `MCPServerStdio` spawns a child process.
- **Streamable HTTP** — `MCPServerStreamableHttp` (recommended).
- **SSE** — `MCPServerSSE` (legacy).
- **Hosted (OpenAI Responses API)** — `hostedMcpTool({ serverLabel, serverUrl, connectorId, allowedTools, requireApproval })` (`tool.ts:918`).

### 14.4 In-process MCP

Not first-class. You'd subclass `MCPServer` to surface in-process tools without subprocess, but no helper is provided.

### 14.5 Auth / lifecycle

- Stdio servers receive env vars from the parent process.
- Streamable HTTP / SSE servers accept `headers` (including auth tokens) per server.
- Hosted MCP accepts `authorization` and `headers` (`docs/src/content/docs/guides/mcp.mdx:80-90`).
- Lifecycle: `MCPServers` helper / `connectMcpServers` opens connections in parallel and closes them at shutdown (`packages/agents-core/src/mcpServers.ts:35-105`).
- Reconnection / version negotiation — basic, handled by `@modelcontextprotocol/sdk`.

---

## 15. Multi-model Routing & Fallback

### 15.1 Multi-provider support

- **OpenAI** (Responses API + Chat Completions) — first-party (`packages/agents-openai/src/openaiResponsesModel.ts`, `openaiChatCompletionsModel.ts`).
- **Anthropic, Gemini, Bedrock, Vertex, Mistral, LiteLLM-compatible**: via the `@openai/agents-extensions/ai-sdk` adapter that wraps a Vercel AI SDK `LanguageModelV2` instance as a `Model` (`packages/agents-extensions/src/ai-sdk/index.ts:35-65`).
- Custom providers: implement `Model` + `ModelProvider` (`packages/agents-core/src/model.ts`) — `setDefaultModelProvider(provider)` (`packages/agents-core/src/providers.ts:10`).

### 15.2 Per-task model selection

Per-agent: `new Agent({ model: 'gpt-5.4' | gpt5Model })`. Per-run override: `new Runner({ model: '…' })` or `RunConfig.model`. Per-`asTool` override: `runConfig.model` on `Agent.asTool({ runConfig: { model: '…' } })` (see `examples/agent-patterns/agents-as-tools.ts:33-39`).

No first-party registry / gateway that auto-routes by task class. You wire selection in code or via a custom `ModelProvider`.

### 15.3 Automatic fallback chain

The SDK retries within a single provider via `getResponseWithRetry` / `getStreamedResponseWithRetry` (`packages/agents-core/src/runner/modelRetry.ts`). There is **no automatic provider-fallback chain** ("try OpenAI; on 429 fall back to Anthropic"). You'd implement fallback in a custom `ModelProvider` that wraps multiple `Model` instances.

### 15.4 Mid-stream model switching

Switch is at **agent boundary** (handoff to an agent with a different `model`) or **turn boundary** (a custom `Model` impl could switch internally). No per-token model switching.

### 15.5 Sub-agent model overrides

Yes — `Agent.asTool({ runConfig: { model: 'gpt-5.4-mini' } })` (see `examples/agent-patterns/agents-as-tools.ts:33-39`). Handoff-target agents can each pin their own `model`.

---

## 16. Chat UI Layer

### 16.1 Streaming chat hook

Not provided in `@openai/agents` itself, but the **`@openai/agents-extensions/ai-sdk-ui`** subpackage adapts a `StreamedRunResult` to Vercel AI SDK's `useChat` / `useAssistant` SSE wire format (`packages/agents-extensions/src/ai-sdk-ui/uiMessageStream.ts`, `textStream.ts`). So the recommended UI integration is **Vercel AI SDK on the client + this extension on the server**.

### 16.2 Tool call rendering primitives

Inherits from Vercel AI SDK once you use the `ai-sdk-ui` adapter — `useChat` exposes `tool-call` and `tool-result` parts. Not first-party here.

### 16.3 Generative UI components

Not provided in this SDK. Use Vercel AI SDK + RSC for generative UI.

### 16.4 BYO pattern

For non–Vercel-AI-SDK frontends: iterate the `StreamedRunResult`, serialize `RunRawModelStreamEvent` / `RunItemStreamEvent` / `RunAgentUpdatedStreamEvent` into your own SSE / WebSocket frames, parse on the client into React state. `examples/realtime-next/` shows a Next.js Realtime voice-agent UI.

---

## 17. Memory & Knowledge

### 17.1 Long-term memory / semantic recall

Not provided as a built-in. Cross-session semantic memory is BYO. The only "memory" surface is `Session` (in-conversation history).

For Sandbox Agents there's a **`memory()` capability** (`packages/agents-core/src/sandbox/capabilities/memory.ts`) that materializes a filesystem-backed scratchpad inside the workspace — useful for cross-turn notes inside one sandbox run, but not semantic recall across sessions.

### 17.2 RAG / knowledge retrieval integration

`fileSearchTool` (OpenAI hosted file search over vector stores, `packages/agents-openai/src/tools.ts:127`) is the closest built-in. Otherwise BYO retriever as a function tool.

### 17.3 Per-tenant memory scoping

Not provided. You namespace yourself by setting per-tenant vector store IDs in `fileSearchTool(vectorStoreIds)`, or by partitioning your custom `Session` impl.

---

## 18. Safety, Guardrails & Tool Sandboxing

### 18.1 Input/output guardrails

First-class. Five distinct guardrail surfaces (`packages/agents-core/src/guardrail.ts`, `packages/agents-core/src/toolGuardrail.ts`):

- `InputGuardrail` — runs on initial input (parallel default).
- `OutputGuardrail` — runs on final output (`agent.outputGuardrails`).
- `ToolInputGuardrail` — per-tool, can block / mutate.
- `ToolOutputGuardrail` — per-tool, can block / mutate.
- `HandoffEnabledPredicate` — gates handoffs (`handoff.ts:94-98`).

All produce `tripwireTriggered: boolean` outcomes that halt the run with `GuardrailTripwireTriggered` errors.

No first-party PII / prompt-injection detection; you BYO with `LlmGuard`, `Lakera`, etc., wrapped as a guardrail.

### 18.2 Tool sandboxing / permission model

- `tool({ needsApproval: true | predicate })` — runtime approval gate (`tool.ts:1408`).
- `tool({ isEnabled })` — visibility filter (`tool.ts:1411`).
- `tool({ inputGuardrails, outputGuardrails })` — per-tool block/mutate.
- `agent.toolUseBehavior` — limits tool loops (`agent.ts:254-263`).

### 18.3 Sandbox provider integrations

Built-in: `UnixLocalSandboxClient` (`@openai/agents/sandbox/local`) and OpenAI-hosted shell with container_auto. Third-party Docker / Blaxel / E2B-like providers are referenced in CHANGELOG (`0.11.1: align Blaxel sandbox errors`). Sandbox is real and growing.

### 18.4 Default-deny vs. default-allow

Tools default to `isEnabled: true`, `needsApproval: false`. The default is **allow**.

---

## 19. Eval, Testing & CI Gates

### 19.1 Golden datasets / regression suites

Not provided as a first-class harness. The repo's own tests use vitest (`vitest.config.ts`), but no agent-eval primitive ships.

### 19.2 LLM-as-judge scoring

Not provided in the SDK. `examples/agent-patterns/llm-as-a-judge.ts` shows the pattern — implemented by users from primitives (one agent grades another).

### 19.3 CI eval gates / pre-merge

Not provided.

### 19.4 Trace replay for skill iteration

The OpenAI Traces dashboard at `platform.openai.com/traces` provides hosted trace viewing/replay. No local viewer ships in the SDK.

---

## 20. Local Sandbox & Dev UX

### 20.1 Local agent runner

A CLI playground is **not** shipped. You run your agent code with `tsx`, `node`, `deno run`, `bun run`. `examples/sandbox/basic.ts` is the closest "playground": a TypeScript file you `tsx examples/sandbox/basic.ts`.

### 20.2 Trace inspection

Default exporter → platform.openai.com/traces (hosted only). For local inspection use `ConsoleSpanExporter` (`packages/agents-core/src/tracing/processor.ts:70`).

### 20.3 Tenant / org switching

Not provided as a built-in. You toggle via your own env vars / context.

### 20.4 Hot reload

Not provided. Use `tsx watch` or `nodemon` yourself.

---

## Architectural diagram

```mermaid
flowchart TD
  Client[Browser / curl / Slack bot]
  HTTP[Your HTTP server<br/>Next.js / Express / Hono / CF Workers]
  Runner[Runner.run / run]
  Loop[while(true) loop<br/>packages/agents-core/src/run.ts:844]
  Prep[prepareTurn + applyCallModelInputFilter]
  Model[Model.getResponse<br/>HTTP / SSE / WebSocket]
  OpenAI[OpenAI Responses API]
  AISDK[AI-SDK adapter<br/>Anthropic / Gemini / Bedrock / …]
  ProcResp[processModelResponseAsync]
  ToolExec[toolExecution<br/>parallel Promise.all]
  UserTools[Your tool.execute<br/>runs in this process]
  MCP[MCP servers<br/>stdio / Streamable HTTP / SSE]
  Hosted[Hosted tools<br/>web_search / file_search / code_interpreter]
  Resolve[resolveTurnAfterModelResponse]
  ApplyTurn[applyTurnResult]
  Session[Session.addItems<br/>MemorySession / OpenAIConversationsSession / BYO Postgres]
  Trace[BatchTraceProcessor → OpenAITracingExporter]
  Dash[platform.openai.com/traces]

  Client --> HTTP --> Runner --> Loop
  Loop --> Prep --> Model
  Model -->|HTTP/SSE/WS| OpenAI
  Model -->|via adapter| AISDK
  OpenAI --> ProcResp
  AISDK --> ProcResp
  ProcResp --> ToolExec
  ToolExec --> UserTools
  ToolExec --> MCP
  ProcResp -->|hosted calls round-trip via OpenAI| Hosted
  ToolExec --> Resolve --> ApplyTurn --> Loop
  ApplyTurn --> Session
  Loop --> Trace --> Dash
```

## Appendix — Files worth reading first

- `packages/agents-core/src/run.ts:387-1117` — top-level `run()` + `Runner.run()` + the canonical `while(true)` loop.
- `packages/agents-core/src/agent.ts:483-1122` — `Agent` class, `getAllTools`, `asTool`, handoffs.
- `packages/agents-core/src/tool.ts:1768-1934` — `tool()` factory: parsing, validation, timeouts, approvals, guardrails.
- `packages/agents-core/src/lifecycle.ts:43-181` — `AgentHookEvents` / `RunHookEvents` (lifecycle event taxonomy).
- `packages/agents-core/src/runner/conversation.ts:25-178` — `callModelInputFilter` (the canonical "mutate messages before send" hook).
- `packages/agents-core/src/runContext.ts:104-421` — `RunContext<TContext>` with `context`, `usage`, approvals; this is where multi-tenant data flows.
- `packages/agents-core/src/memory/session.ts:27-148` — `Session` interface + `OpenAIResponsesCompactionAwareSession`.
- `packages/agents-core/src/memory/memorySession.ts:20-92` — reference in-memory `Session`.
- `packages/agents-core/src/types/protocol.ts:340-958` — message + stream-event Zod schemas.
- `packages/agents-core/src/sandbox/capabilities/skills.ts:50-310` — `SkillsCapability` (only first-class skill loader; sandbox-only).
- `packages/agents-openai/src/memory/openaiConversationsSession.ts` — OpenAI-managed conversation session.
- `examples/nextjs/src/app/api/basic/route.ts` — reference HITL-aware POST endpoint pattern.
- `examples/agent-patterns/human-in-the-loop.ts:81-106` — `RunState` serialization + resume idiom.
