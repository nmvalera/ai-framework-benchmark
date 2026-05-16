# Claude Agent SDK TS — Benchmark Study

> **Repo**: https://github.com/anthropics/claude-agent-sdk-typescript
> **Commit studied**: `fa5d004c65b6a173ee3eba3f67336a1e8039576a`
> **Branch**: `main`
> **Cloned at**: `benchmarked-stacks/claude-agent-sdk-typescript/`
> **Published SDK studied**: `@anthropic-ai/claude-agent-sdk@0.3.143` (npm)
> **Bundled Claude Code version**: `2.1.143`
> **Studied on**: 2026-05-16

## TL;DR

- ⭐ **What this is**: a ~1 MB TypeScript shim (`sdk.mjs` is 862 KB minified) that **subprocesses a native Claude Code binary** shipped via per-platform optional npm dependencies (`@anthropic-ai/claude-agent-sdk-{darwin,linux,win32}-{x64,arm64}`). Each binary is **207–233 MB** of bundled Node + JS code (`manifest.json`). Older versions (≤ 0.2.112) spawned `node cli.js`; **0.2.113 switched to native single-file binaries** (CHANGELOG.md:137). Despite "TypeScript SDK" branding, the agent loop runs in the spawned binary — exactly the same architecture as the Python SDK.
- **Where the agent loop runs**: in the spawned Claude Code subprocess, NOT in your Node/Bun/Deno process. The TS code is a transport (`spawnLocalProcess`, `child_process.spawn`), a typed-message parser, hook callback router over a JSON control protocol on stdio (`--input-format stream-json --output-format stream-json`), and an in-process MCP host. You can swap the executable via `pathToClaudeCodeExecutable` or `spawnClaudeCodeProcess` (custom VM/container spawn).
- **Strongest fit for our case**: hooks are excellent (29 lifecycle events — `HOOK_EVENTS`, sdk.d.ts:738), tool-arg injection via `PreToolUse.updatedInput` and `canUseTool.updatedInput` is first-class, `maxBudgetUsd` cap is enforced server-side (sdk.d.ts:1473), and three reference `SessionStore` adapters (S3, Redis, Postgres) ship in the repo with a 13-contract conformance suite (examples/session-stores/).
- **Biggest gap for multi-tenant SaaS**: the subprocess model means **~200 MB binary baked into your Docker image per platform**, a JSON-RPC handshake on every cold start (issue #318 — startup race, issue #122 — concurrent query MCP timeouts), and **no first-class HTTP server** — you wrap `query()` in your own Express/Fastify route. Skills, sub-agents, slash commands, plugins, and CLAUDE.md all load from filesystem paths under `cwd` + `CLAUDE_CONFIG_DIR`; there is no `registerSkill(tenantID, ...)` programmatic API.
- **Most surprising finding (good)**: the SDK now ships three production-grade `SessionStore` reference adapters (Postgres, Redis, S3) with end-to-end conformance tests and a 13-contract harness (`examples/session-stores/shared/conformance.ts`). The Python SDK only ships `InMemorySessionStore`. This is the single largest differentiation TS-vs-Py.
- **Most surprising finding (bad)**: `listSessions()` spawns a full Claude Code subprocess just to read metadata — open issue #268 reports 900 MB+ memory cost for a metadata query. Operating a multi-tenant session browser at scale on top of this is a non-starter without your own `sessionStore.listSessions()` shortcut.
- **TS-vs-Py honest comparison**:
  - TS **wins**: ships Postgres/Redis/S3 reference adapters (Py only ships in-memory), has a native `browser-sdk` export over WebSocket (Py has nothing), better edge-runtime story (works on Bun/Deno per `getDefaultExecutable`), JS-native `AbortController`-based cancel.
  - Py **wins**: arrived a few releases earlier with `max_budget_usd`, slightly more mature `pre_compact`/`SessionStore` examples in the older docs. Both are now at feature parity on hooks, sub-agents, skills, MCP, multi-model routing, fallbackModel.
  - **Equal**: both spawn the same Claude Code binary the same way, with the same JSON control protocol, the same 29 hook events, the same `~/.claude/projects/<cwd>/<sid>.jsonl` persistence default, the same filesystem-only skill loader, the same subprocess startup cost.
- **One-liner verdicts**:
  - Sessions/persistence: JSONL on disk by default; `SessionStore` interface (alpha) with shipped Postgres/Redis/S3 adapters. Resume by `sessionId` UUID.
  - Skills: filesystem-only, plugin-qualified. The `skills: string[] | 'all'` option (sdk.d.ts:1721) is a *context filter*, not a sandbox — explicitly documented.
  - Resource Manager: not a first-class concept. Sources are filesystem (`~/.claude/skills/`, `.claude/skills/`), plugin dirs (`SdkPluginConfig.type: 'local'` only), and bundled assets. No git/OCI/S3/Postgres registry. BYO if you want multi-source resolution.
  - Sub-agents: first-class. `agents: Record<string, AgentDefinition>` (sdk.d.ts:1203) defines them inline; the CLI's built-in `Agent` tool (formerly `Task`) dispatches them, with `background: true` for fire-and-forget and `parallel` via multiple `tool_use` blocks in one assistant turn.
  - Multi-tenancy: arg forcing ✅, visible-tool filter ✅, tenant-on-session ❌ (you stuff it in `projectKey` on `SessionKey`, or in env vars passed to the subprocess), per-tenant cost cap ✅ via `maxBudgetUsd`.
  - Hooks: 29 events. Best-in-class. `PreToolUse.updatedInput` is the canonical force-args pattern.
  - API: no HTTP server. Library-only — you embed `query()` in your own Express/Fastify/Next.js route. A `browser-sdk` export exists for WebSocket-talking-to-your-server clients.
  - Observability: `total_cost_usd` and `usage` on every `SDKResultMessage`, `modelUsage` per-model breakdown, OTel trace-context auto-forwarded to the subprocess (CHANGELOG.md:143).
- **Production readiness for multi-tenant server-side deployment**: **viable with significant scaffolding**. You ship 200 MB of binary per platform, build your own HTTP server, materialize per-tenant `.claude/` filesystem trees for skills/plugins/sub-agents, wire `PreToolUse` for tenant-id injection, plug a `SessionStore` (Postgres adapter ready), and design around `listSessions()` being slow. Net: easier than rolling your own, much harder than a true library-shaped framework (LangGraph, Mastra). The architectural ceiling is the same as the Py SDK — you cannot escape the Claude Code subprocess.

---

## 0. Architectural Overview & Deployment Model

### Deployment diagram

```mermaid
flowchart TB
  subgraph Your Process (Node/Bun/Deno)
    APP[Your HTTP server<br/>Express / Fastify / Next.js]
    SDK["@anthropic-ai/claude-agent-sdk<br/>(sdk.mjs ~862KB bundled)"]
    HOOKS[Your hook callbacks<br/>PreToolUse / PostToolUse / SessionStart / …]
    MCP[In-process SDK MCP servers<br/>createSdkMcpServer + tool]
    STORE[Your SessionStore impl<br/>Postgres / Redis / S3]
  end
  subgraph Subprocess
    CLI["Claude Code native binary<br/>~207–233 MB<br/>@anthropic-ai/claude-agent-sdk-{platform}-{arch}/claude"]
    LOOP[Agent loop:<br/>system prompt build,<br/>tool dispatch, permissions,<br/>compaction, skill discovery,<br/>sub-agent fan-out]
    CFG[~/.claude/<br/>projects/&lt;cwd&gt;/&lt;sid&gt;.jsonl<br/>skills/, plugins/, agents/]
  end
  ANT[Anthropic API<br/>api.anthropic.com<br/>or Bedrock / Vertex]
  EXT[External MCP servers<br/>stdio / SSE / HTTP / WS]
  CLAUDE_AI[(claude.ai bridge<br/>SSE + CCRClient)<br/>OPTIONAL]

  APP --> SDK
  SDK -- "spawn(node|bun|claude_binary)<br/>JSON over stdio:<br/>--input-format stream-json<br/>--output-format stream-json" --> CLI
  CLI --> LOOP
  LOOP --> CFG
  LOOP <-- "control_request:<br/>can_use_tool, hook_callback,<br/>mcp_message, mcp_call" --> SDK
  SDK --> HOOKS
  SDK --> MCP
  SDK --> STORE
  STORE -. "mirror append() per-turn" .-> CFG
  LOOP <-- "model API" --> ANT
  CLI <-- "stdio / SSE / HTTP" --> EXT
  SDK <-. "attachBridgeSession<br/>(remote workers)" .-> CLAUDE_AI
```

### 0.1 What is this stack?

A **thin TypeScript shim around the Claude Code CLI binary**. The package layout (`package.json`):

```json
"exports": {
  ".":           { "default": "./sdk.mjs" },         // Node/Bun/Deno entry
  "./browser":   { "default": "./browser-sdk.js" },  // browser, talks WebSocket to your server
  "./bridge":    { "default": "./bridge.mjs" },      // claude.ai SSE bridge (alpha)
  "./assistant": { "default": "./assistant.mjs" }    // runAssistantWorker (alpha)
},
"optionalDependencies": {
  "@anthropic-ai/claude-agent-sdk-darwin-arm64": "0.3.143",
  "@anthropic-ai/claude-agent-sdk-darwin-x64":   "0.3.143",
  "@anthropic-ai/claude-agent-sdk-linux-arm64":  "0.3.143",
  "@anthropic-ai/claude-agent-sdk-linux-arm64-musl": "0.3.143",
  "@anthropic-ai/claude-agent-sdk-linux-x64":    "0.3.143",
  "@anthropic-ai/claude-agent-sdk-linux-x64-musl": "0.3.143",
  "@anthropic-ai/claude-agent-sdk-win32-x64":    "0.3.143",
  "@anthropic-ai/claude-agent-sdk-win32-arm64":  "0.3.143"
}
```

`manifest.json` lists the binary sizes:

```json
"platforms": {
  "darwin-arm64": { "binary": "claude", "size": 207605280 },
  "darwin-x64":   { "binary": "claude", "size": 210119440 },
  "linux-arm64":  { "binary": "claude", "size": 232961672 },
  "linux-x64":    { "binary": "claude", "size": 233088720 },
  "linux-arm64-musl": { "binary": "claude", "size": 225816408 },
  "linux-x64-musl":   { "binary": "claude", "size": 227482672 },
  "win32-x64":   { "binary": "claude.exe", "size": 228902560 },
  "win32-arm64": { "binary": "claude.exe", "size": 224866976 }
}
```

So a deployment that supports `linux-x64` + `linux-arm64` ships **≈460 MB** of binaries in `node_modules` even if you never run on the other one (npm grabs all matching `optionalDependencies` it can install; pnpm/bun mostly only pulls the host platform).

### 0.2 Where does the agent loop *actually* execute?

**In the spawned Claude Code subprocess, not in your Node process.** The TS `query()` function is, internally, a transport + control-protocol shim. The actual model-call → tool-call → tool-result → next-model-call cycle, system prompt assembly, permission evaluation, skill discovery, compaction, and sub-agent dispatch all execute in the CLI binary.

The minified runtime confirms this:

```js
// sdk.mjs (extracted from the bundle, function names mangled)
spawnLocalProcess($) {
  let { command:Q, args:J, cwd:Y, env:X, signal:W } = $;
  let U = spawn(Q, J, { cwd:Y, stdio:["pipe","pipe", G],
                        signal:W, env:X, windowsHide:true });
  …
}
getDefaultExecutable() { return process.versions.bun !== undefined ? "bun" : "node"; }
```

And the arg list:

```js
let i = ["--output-format", "stream-json", "--verbose",
         "--input-format",  "stream-json"];
```

The resolution chain for which binary to spawn:

1. `options.pathToClaudeCodeExecutable` if set, OR
2. Try to `require.resolve("@anthropic-ai/claude-agent-sdk-{platform}-{arch}/claude")` (with `linux-musl` detection), OR
3. Fall back to `./cli.js` (not present in v0.3.143; throws). The throw message: *"Native CLI not found … Install @anthropic-ai/claude-agent-sdk without --omit=optional, or set options.pathToClaudeCodeExecutable."*

If the resolved path is a native binary (Fx() filter: not `.js/.mjs/.tsx/.ts/.jsx`), it is spawned **directly**. Otherwise it is invoked as `node|bun <path>`. In v0.3.143 the resolved path is the platform binary, so the subprocess is the native binary itself — **the TS executable is irrelevant to the runtime path**; it is only used for resolving the binary location.

**You cannot fork the loop without forking Claude Code.** Hooks and `canUseTool` are the only extension points the bundled CLI exposes.

### 0.3 Runtime dependencies

- **Node ≥ 18** (`package.json` `engines.node`), or **Bun** (auto-detected via `process.versions.bun`), or **Deno** (you can set `executable: 'deno'`).
- **`@anthropic-ai/sdk` ≥ 0.93.0** as a `peerDependencies` (was `dependencies` ≤ 0.3.142; switched in 0.3.143 per CHANGELOG.md:5 — yarn classic users now must install it explicitly).
- **`@modelcontextprotocol/sdk` ^1.29.0** peer dep.
- **`zod` ^4.0.0** peer dep — required for `tool()` definitions.
- **One platform binary** (~200 MB) pulled as `optionalDependencies`. Mandatory in practice; the SDK throws on missing binary unless `pathToClaudeCodeExecutable` is set.
- Optionally: Postgres / Redis / S3 client packages if you adopt one of the example session-store adapters (`pg`, `ioredis`, `@aws-sdk/client-s3`).
- Optionally: `bubblewrap` on Linux when you turn on `sandbox: { enabled: true }` (sdk.d.ts:1617).

### 0.4 Recommended deployment topology

The vendor's *hosting* doc (`https://code.claude.com/docs/en/agent-sdk/hosting`) recommends **one CLI subprocess per session**, mediated by your HTTP server. The same `attachBridgeSession` and `runAssistantWorker` exports (alpha, in `bridge.mjs` / `assistant.mjs`) document a **worker-per-session** pattern for the claude.ai bridge:

```ts
// assistant.d.ts:55 — AssistantWorkerOptions
{
  bridge: ConnectRemoteControlOptions,  // 1 worker = 1 claude.ai session
  buildQueryOptions: (base) => Options, // called on each query() spawn
  userIdleMs?: number,                  // despawn after this quiet period (default 5 min)
  …
}
```

For a multi-tenant *server-side* deployment (no claude.ai bridge), the practical topology is **N session workers per pod**, each owning one CLI subprocess. The `userIdleMs` despawn pattern from the assistant worker is a useful blueprint even when you're not using the bridge.

There is no first-party queue or scheduler. The `scheduling` field on `AssistantWorkerOptions` polls a local `.claude/scheduled_tasks.json` file — not a distributed cron.

### 0.5 Cold-start cost & instance footprint

- **Binary footprint**: 207–233 MB per platform in `node_modules`. Multi-arch Docker images add up.
- **Cold start per subprocess**: the binary itself is a self-contained Node binary that runs the bundled CLI; my best estimate from CHANGELOG entries and matching Py SDK issue #333 is **5–20 s warm-process resolve + initialize handshake**. The `startup()` / `WarmQuery` API exists explicitly to amortize this (sdk.d.ts:5450) — the subprocess is pre-warmed and the `initialize` handshake done before the first `query()` lands a prompt.
- **Per-session RAM baseline**: the spawned binary loads Node + the bundled CLI + tool registry + memory recall + skill loader + plugin loader. Open issue #268 reports `listSessions()` (which spawns one CLI just for metadata) using **900 MB+ memory**; an active session is similar to slightly higher. **Plan for ~1 GB resident per concurrent session.**
- **TS shim runtime footprint**: small (`sdk.mjs` loaded), but the per-call `tool()` and `createSdkMcpServer()` registrations all live in your Node heap.

### 0.6 Vendor lock-in

| Dimension | Lock-in level | Reason |
|---|---|---|
| **LLM provider** | **High → Medium** | Native first-class is Anthropic. Bedrock, Vertex, Foundry, `anthropicAws`, `mantle`, "gateway" are explicitly enumerated (sdk.d.ts:32 — `AccountInfo.apiProvider`). 3P providers like OpenAI / Gemini require gateway adapters. |
| **Hosting** | Low for self-host, High for claude.ai bridge | You can self-host with your own Anthropic API key. `bridge.mjs` is opt-in alpha for claude.ai-anchored workers. |
| **Eval / observability** | Low | OTel trace context is forwarded to the subprocess (CHANGELOG.md:143). No first-party eval framework. |
| **Skill/sub-agent format** | High | `SKILL.md` and `AgentDefinition` are CC-shaped — porting requires rewriting. |

### 0.7 Framework weight / footprint

- TS shim: **~862 KB** minified `sdk.mjs`, **~1.1 MB** `bridge.mjs`, ~31 KB `assistant.mjs`, ~17 KB `browser-sdk.js`. Total ≤ **2 MB** of pure JS.
- Bundled native CLI: **207–233 MB per platform**.
- Type-only `sdk.d.ts`: **5722 lines** of public type surface. This is *huge* for a "thin SDK" — but most of it is hook payload types, settings schema (auto-generated from a JSONSchema), and control-protocol message types you never construct yourself.

This is neither a thin SDK (the bundled binary makes it the *heaviest* of the 11 stacks studied by bytes-on-disk) nor a heavy framework (the TS surface is small and focused).

### 0.8 Documentation depth & cross-team contributor accessibility

- Official docs: well-written, deep, English-only.
- Quickstart: 5 minutes.
- API reference (`https://code.claude.com/docs/en/agent-sdk/typescript`): autogenerated from the TypeScript types, comprehensive.
- Hosting / production guide: separate page (`/hosting`), short but covers permissions and multi-tenant gotchas.
- Examples: only the 3 session-store adapters in this repo. Anthropic's broader examples (Claude API skill, Claude Code skill) are in sibling repos.
- Non-engineer authoring: a Product manager can author a `SKILL.md` file. They cannot author hooks, sub-agents, or tools without engineering — those are TypeScript code.

### 0.9 Documentation entry points ⭐

- **Official landing page**: https://code.claude.com/docs/en/agent-sdk/overview
- **Quickstart**: https://code.claude.com/docs/en/agent-sdk/typescript (same page acts as quickstart + reference)
- **TypeScript SDK reference**: https://code.claude.com/docs/en/agent-sdk/typescript
- **Hosting / deployment**: https://code.claude.com/docs/en/agent-sdk/hosting
- **Migration from Claude Code SDK → Claude Agent SDK**: https://docs.claude.com/en/docs/claude-code/sdk/migration-guide
- **Examples**: only the three session-store adapters in `examples/session-stores/` of the repo
- **GitHub**: https://github.com/anthropics/claude-agent-sdk-typescript
- **Changelog**: https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md
- **GitHub issues**: https://github.com/anthropics/claude-agent-sdk-typescript/issues
  - **#268** — `listSessions()` spawns full CLI process — 900MB+ memory for metadata query (critical for multi-tenant session browsers)
  - **#122** — SDK MCP servers fail to connect from concurrent `query()` calls — 60s timeout (impacts horizontal scaling)
  - **#293** — Feature request: per-subagent breakdown in `modelUsage` for cost/token attribution (impacts tenant cost accounting)
  - **#319** — Should it be possible to set `metadata.user_id` when using the Agent SDK? (impacts tenant trace correlation)
  - **#316** — Subagents cannot access MCP server resources declared in subagent definitions
  - **#318** — Uncaught EPIPE from subprocess stdin during startup-crash → fresh-retry race
  - **#308** — Silent process exit (code 1) when calling `query()` from SDK v0.2.121
- **Discord**: https://anthropic.com/discord — Claude Developers channel
- **Managed Agents exit ramp** (same doc as Python): https://platform.claude.com/docs/en/managed-agents/overview

---

## 1. Agent Harness (Run Loop) & Message Taxonomy

### Run loop

#### 1.1 Run loop entrypoint(s)

A single primary entrypoint, plus a pre-warm helper:

```ts
// sdk.d.ts:2281
export declare function query(_params: {
  prompt: string | AsyncIterable<SDKUserMessage>;
  options?: Options;
}): Query;

// sdk.d.ts:5450 — pre-warmed subprocess
export declare function startup(_params?: {
  options?: Options;
  initializeTimeoutMs?: number;
}): Promise<WarmQuery>;

// sdk.d.ts:5691
export declare interface WarmQuery extends AsyncDisposable {
  query(prompt: string | AsyncIterable<SDKUserMessage>): Query;
  close(): void;
}
```

`Query` is an `AsyncGenerator<SDKMessage, void>` extended with control methods (`interrupt()`, `setPermissionMode()`, `setModel()`, `applyFlagSettings()`, `stopTask()`, `backgroundTasks()`, `setMcpServers()`, `streamInput()`, `close()`, `mcpServerStatus()`, `accountInfo()`, `supportedModels()`, `supportedAgents()`, `supportedCommands()`, `getContextUsage()`, `rewindFiles()`, `readFile()`, `reloadPlugins()`, `seedReadState()`, `reconnectMcpServer()`, `toggleMcpServer()`, `initializationResult()`, `setMaxThinkingTokens()`) — sdk.d.ts:2052–2278.

#### 1.2 Per-iteration behavior

One trip around the loop (executed entirely in the subprocess):

1. CLI assembles system prompt (preset `claude_code` or custom from `Options.systemPrompt`), tools, MCP tool catalog, skill catalog, memory recall, dynamic sections (cwd, git status, auto-memory) — unless `excludeDynamicSections: true`.
2. CLI fires `SessionStart` hook (first turn) or no hook on subsequent turns.
3. CLI calls Anthropic API with the assembled prompt + messages, streams the assistant response back.
4. SDK emits `SDKPartialAssistantMessage` (`type: 'stream_event'`) per stream event when `includePartialMessages: true`.
5. When an assistant message includes one or more `tool_use` blocks:
   - For *each* tool call, CLI fires `PreToolUse` hook. Hook can `updatedInput`, `permissionDecision: allow|deny|defer`, `additionalContext`.
   - If `canUseTool` callback registered, CLI sends `control_request: can_use_tool` to the SDK over stdio; SDK invokes the callback and replies via `control_response`.
   - CLI dispatches the tool (built-in like `Bash`/`Read`/`WebFetch`, MCP, or SDK MCP via `control_request: mcp_message`).
   - CLI fires `PostToolUse` per tool, then `PostToolBatch` once for the whole batch (sdk.d.ts:1953).
6. Tool results are folded back into the messages list as a `user` turn with `tool_result` blocks.
7. Loop until the assistant returns no `tool_use`, hits `maxTurns`, hits `maxBudgetUsd`, hits hook `decision: block`, or aborts.
8. CLI emits `SDKResultMessage` with `total_cost_usd`, `usage`, `modelUsage`, `permission_denials`, `terminal_reason`, `stop_reason`.
9. CLI fires `Stop` (or `StopFailure` on error) hook.

#### 1.3 ReAct loop

**Built-in** — the CLI runs a ReAct-style loop. You do not author the loop; you only insert hooks and choose tools.

#### 1.4 Tool dispatch + result handling

Dispatch path depends on tool source:

- **Built-in CLI tools** (Bash, Read, Edit, Glob, Grep, WebFetch, WebSearch, TaskCreate, etc. — 25+ enumerated in `sdk-tools.d.ts:11`) execute inside the subprocess. No round-trip to the SDK consumer.
- **MCP-process tools** (`McpStdioServerConfig`, `McpSSEServerConfig`, `McpHttpServerConfig`) are managed by the CLI subprocess directly — the CLI spawns/connects the MCP server.
- **SDK MCP tools** (`McpSdkServerConfig` returned by `createSdkMcpServer`) run **in your Node process**. The CLI sends `control_request: mcp_message` over stdio to the SDK; the SDK dispatches to the registered `McpServer` instance and returns the `CallToolResult` via `control_response`. This is how the `tool()` factory bridges TS code into the loop:

  ```ts
  // sdk.d.ts:5592
  export declare function tool<Schema extends AnyZodRawShape>(
    _name: string,
    _description: string,
    _inputSchema: Schema,
    _handler: (args: InferShape<Schema>, extra: unknown) => Promise<CallToolResult>,
    _extras?: { annotations?: ToolAnnotations; searchHint?: string; alwaysLoad?: boolean }
  ): SdkMcpToolDefinition<Schema>;
  ```

Results are folded as `tool_result` blocks on a synthetic `user` turn that the CLI prepends to the next API call.

#### 1.5 Explicit turn concept

A **turn** = one assistant message (with any number of `tool_use` blocks) + the synthetic `user` message containing the matching `tool_result` blocks. A `SDKResultMessage` is emitted **once per request loop terminator** — when the assistant returns no more `tool_use` blocks, or `maxTurns` / `maxBudgetUsd` / hook-stop terminates. `num_turns` is the count of model API round-trips for this `query()` call.

#### 1.6 Event emission mechanism (in-process)

Async iteration on `Query` (which `extends AsyncGenerator<SDKMessage, void>`). Each yielded value is a discriminated union member of `SDKMessage` (sdk.d.ts:3175).

```ts
const q = query({ prompt: 'Hello', options: { ... } });
for await (const msg of q) {
  switch (msg.type) {
    case 'assistant': /* model turn */ break;
    case 'user':      /* tool result echo */ break;
    case 'result':    /* end of run */ break;
    case 'system':    /* subtype: 'init' | 'status' | 'task_*' | 'memory_recall' | … */ break;
    case 'stream_event': /* partial assistant when includePartialMessages */ break;
    // ... 30+ more
  }
}
```

The Node process consumes the CLI's stdout JSONL stream, parses each frame, peels off control-protocol frames (`control_request`, `control_response`, `control_cancel_request`, `transcript_mirror`, `keep_alive`), routes those to internal handlers, and yields the remaining frames as typed `SDKMessage`s.

---

### Message & event taxonomy

#### 1.7 Message layers

Three layers:

1. **Wire layer (CLI ↔ SDK)** — line-delimited JSON on the CLI subprocess's stdout. Discriminated by `type ∈ {"assistant", "user", "system", "result", "stream_event", "rate_limit_event", "control_request", "control_response", "control_cancel_request", "transcript_mirror", "tool_progress", "tool_use_summary", "prompt_suggestion", "auth_status", "keep_alive"}`. Control / transcript / keep-alive frames are peeled off by the read loop and never surfaced to the caller.
2. **SDK message layer (TS public)** — typed discriminated union `SDKMessage` (sdk.d.ts:3175). Returned by `Query` async iteration.
3. **Transcript on disk** (`~/.claude/projects/<cwd>/<sid>.jsonl` or via `SessionStore.append()`) — one `SessionStoreEntry` per line, an opaque pass-through of the CLI's internal entry format.

There is no separate "UI message" layer — the SDK message layer is what your application iterates and what you re-stream to the browser.

#### 1.8 Concrete message types

`SDKMessage` union members (sdk.d.ts:3175):

| Type | Discriminator | Purpose |
|---|---|---|
| `SDKAssistantMessage` | `type: 'assistant'` | A model turn. Holds `message: BetaMessage` (Anthropic API shape), `parent_tool_use_id`, `uuid`, `session_id`, `subagent_type`, `task_description`. |
| `SDKUserMessage` | `type: 'user'` | A user turn or tool-result echo. Holds `message: MessageParam`, `parent_tool_use_id`, `priority: 'now'|'next'|'later'`, `shouldQuery`. |
| `SDKUserMessageReplay` | `type: 'user'` | Replayed user message on resume. |
| `SDKSystemMessage` | `type: 'system', subtype: 'init'` | Initial handshake. Has `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands`, `skills`, `plugins`, `claude_code_version`. |
| `SDKResultMessage` | `type: 'result'` | Terminal per-run message. Discriminated subtype: `'success'` (sdk.d.ts:3356), `'error_during_execution'`, `'error_max_turns'`, `'error_max_budget_usd'`, `'error_max_structured_output_retries'`. Carries `total_cost_usd`, `usage`, `modelUsage`, `permission_denials`, `terminal_reason`, `num_turns`, `duration_ms`, `duration_api_ms`, `ttft_ms`. |
| `SDKPartialAssistantMessage` | `type: 'stream_event'` | Per-API-event stream payload when `includePartialMessages: true`. Carries the raw `BetaRawMessageStreamEvent`. |
| `SDKCompactBoundaryMessage` | `type: 'system', subtype: 'compact_boundary'` | Marks a compaction event with `pre_tokens`, `post_tokens`, `preserved_segment`, `preserved_messages`. |
| `SDKStatusMessage` | `type: 'system', subtype: 'status'` | `'compacting' | 'requesting' | null`. |
| `SDKAPIRetryMessage` | `type: 'system', subtype: ...` | API retry notification. |
| `SDKLocalCommandOutputMessage` | `type: 'system', subtype: 'local_command_output'` | Slash-command output (e.g. `/voice`, `/usage`). |
| `SDKHookStartedMessage` | `type: 'system', subtype: 'hook_started'` | Hook lifecycle when `includeHookEvents: true`. |
| `SDKHookProgressMessage` | `type: 'system', subtype: 'hook_progress'` | Async hook progress. |
| `SDKHookResponseMessage` | `type: 'system', subtype: 'hook_response'` | Hook completed. |
| `SDKPluginInstallMessage` | `type: 'system', subtype: 'plugin_install'` | Headless plugin install progress. |
| `SDKToolProgressMessage` | `type: 'tool_progress'` | Tool elapsed-time heartbeat for long-running tool calls. Tied to `tool_use_id`. |
| `SDKAuthStatusMessage` | `type: 'auth_status'` | OAuth-flow progress. |
| `SDKTaskNotificationMessage` | `type: 'system', subtype: 'task_notification'` | Sub-agent/task completed/failed/stopped. |
| `SDKTaskStartedMessage` | `type: 'system', subtype: 'task_started'` | Sub-agent or local workflow started. |
| `SDKTaskUpdatedMessage` | `type: 'system', subtype: 'task_updated'` | Patch of sub-agent state fields. |
| `SDKTaskProgressMessage` | `type: 'system', subtype: 'task_progress'` | Sub-agent in-flight description (when `agentProgressSummaries: true`). |
| `SDKSessionStateChangedMessage` | `type: 'system', subtype: 'session_state_changed'` | `'idle' | 'running' | 'requires_action'`. |
| `SDKNotificationMessage` | `type: 'system', subtype: 'notification'` | Text notification with priority. |
| `SDKFilesPersistedEvent` | `type: 'system', subtype: 'files_persisted'` | File-checkpoint snapshot landed. |
| `SDKToolUseSummaryMessage` | `type: 'tool_use_summary'` | Summary across multiple tool uses. |
| `SDKMemoryRecallMessage` | `type: 'system', subtype: 'memory_recall'` | Memory file paths surfaced this turn. |
| `SDKRateLimitEvent` | `type: 'rate_limit_event'` | Rate-limit state change. |
| `SDKElicitationCompleteMessage` | `type: 'system', subtype: ...` | MCP elicitation completed. |
| `SDKPermissionDeniedMessage` | `type: 'system', subtype: 'permission_denied'` | Auto-deny short-circuit (classifier / mode / rule). |
| `SDKPromptSuggestionMessage` | `type: 'prompt_suggestion'` | Predicted next user prompt. |
| `SDKMirrorErrorMessage` | `type: 'system', subtype: 'mirror_error'` | `SessionStore.append()` failed permanently. |

#### 1.9 Messages vs. events

**Same iterator.** Everything flows on the single `AsyncGenerator<SDKMessage>`. There is no parallel event-emitter, no `on('toolStart')` listener, no separate event bus. This is the same design as the Python SDK and is *deliberately* simpler than Mastra / Vercel AI SDK / LangGraph — the wire format is a JSONL stream out of a subprocess; everything else is just typed accessors over it.

#### 1.10 Event categories

Mapped to the existing message types:

| Category | Concrete messages |
|---|---|
| **Stream event** | `SDKPartialAssistantMessage` (`type: 'stream_event'`) |
| **Turn event** | `SDKResultMessage` (one per query terminator) |
| **Message event** | `SDKAssistantMessage`, `SDKUserMessage`, `SDKUserMessageReplay` |
| **Tool event** | `tool_use` block in `SDKAssistantMessage`, `tool_result` block in `SDKUserMessage`, `SDKToolProgressMessage`, `SDKToolUseSummaryMessage` |
| **Session lifecycle** | `SDKSystemMessage(subtype: 'init')`, `SDKSessionStateChangedMessage`, `SDKCompactBoundaryMessage`, `SDKAuthStatusMessage` |
| **Hook event** | `SDKHookStartedMessage`, `SDKHookProgressMessage`, `SDKHookResponseMessage` (opt-in via `includeHookEvents: true`) |
| **Sub-agent event** | `SDKTaskStartedMessage`, `SDKTaskProgressMessage`, `SDKTaskUpdatedMessage`, `SDKTaskNotificationMessage` |
| **Notification** | `SDKNotificationMessage`, `SDKPromptSuggestionMessage`, `SDKMemoryRecallMessage` |
| **Error / state** | `SDKMirrorErrorMessage`, `SDKPermissionDeniedMessage`, `SDKRateLimitEvent`, `SDKAPIRetryMessage` |

#### 1.11 Canonical type-definition file(s)

- **`sdk.d.ts`** (5722 lines) — the public TS API. The `SDKMessage` union and every related type are declared here.
- **`agentSdkTypes.d.ts`** — single-line file used as the type-rewrite seed for the `bridge`, `browser`, and `assistant` sub-exports (per the build script comments in `bridge.d.ts:5-10`).
- **`sdk-tools.d.ts`** (2848 lines) — auto-generated from the CLI's tool JSON-schema. Lists every built-in tool I/O shape.
- **`assistant.d.ts`**, **`bridge.d.ts`**, **`browser-sdk.d.ts`** — sub-exports for cloud worker / claude.ai bridge / WebSocket browser client respectively.

#### 1.12 Live agentic event stream taxonomy

Sample frames (illustrative — exact bytes vary; structure is from the type defs):

```jsonl
{"type":"system","subtype":"init","session_id":"abc-...","model":"claude-opus-4-7","tools":["Bash","Read","Edit","Glob","Grep","WebFetch","WebSearch","Agent","TaskCreate","TaskGet","TaskUpdate","TaskList","NotebookEdit","Skill","AskUserQuestion","WriteCheckpoint","ExitPlanMode"],"mcp_servers":[],"skills":["pdf"],"plugins":[],"permissionMode":"default","apiKeySource":"oauth","claude_code_version":"2.1.143","slash_commands":["/init","/usage"],"output_style":"default","uuid":"..."}
{"type":"assistant","session_id":"abc-...","message":{"id":"msg_01...","role":"assistant","model":"claude-opus-4-7","content":[{"type":"text","text":"I'll search topics."},{"type":"tool_use","id":"toolu_01...","name":"topicSearch","input":{"query":"young moms"}}],"stop_reason":"tool_use","usage":{"input_tokens":1234,"output_tokens":42,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}},"parent_tool_use_id":null,"uuid":"..."}
{"type":"tool_progress","tool_use_id":"toolu_01...","tool_name":"topicSearch","parent_tool_use_id":null,"elapsed_time_seconds":3.2,"uuid":"...","session_id":"abc-..."}
{"type":"user","session_id":"abc-...","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01...","content":"[{...10 topics...}]"}]},"parent_tool_use_id":null,"uuid":"..."}
{"type":"result","subtype":"success","session_id":"abc-...","duration_ms":4200,"duration_api_ms":3800,"num_turns":2,"result":"Found 10 topics.","stop_reason":"end_turn","total_cost_usd":0.0123,"usage":{"input_tokens":1500,"output_tokens":120,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"server_tool_use":null,"service_tier":"standard","cache_creation":null},"modelUsage":{"claude-opus-4-7":{"input_tokens":1500,"output_tokens":120,"cost_usd":0.0123}},"permission_denials":[],"is_error":false,"uuid":"...","terminal_reason":"completed"}
```

---

## 2. Agent Runtime (Multi-session Host)

### 2.1 Multi-session host architecture

**Not provided as a turnkey runtime.** The SDK gives you `query()` (one session per call); you embed it in your own server. The closest thing to a runtime is `runAssistantWorker` (`assistant.d.ts:135`, alpha) — but that's a single-session worker scoped to the claude.ai bridge use case. There is **no `Server` class** that hosts N sessions per process; you build that yourself.

A multi-session host pattern in TS looks like:

```ts
// Your own code — not shipped by the SDK
const sessions = new Map<string, Query>();

app.post('/sessions/:sid/turns', async (req, res) => {
  const sid = req.params.sid;
  let q = sessions.get(sid);
  if (!q) {
    q = query({ prompt: messageStreamFor(sid), options: { sessionId: sid, sessionStore: pgStore } });
    sessions.set(sid, q);
  }
  // ... stream q.next() to res
});
```

### 2.2 Concurrent session isolation

**One subprocess per session is the only safe model.** A single CLI subprocess has one cwd, one settings tree, one MCP server set. State *bleeds* if you reuse a single subprocess across tenants (the in-memory file-checkpoint, the working-directory permission caches, the session JSONL append target, the active model setting are all process-global).

The SDK does not enforce isolation — it's your responsibility to spawn one process per `(tenant, session)` and tear it down on idle. The `Options` `env`, `cwd`, `sessionId`, `settings`, `managedSettings`, and `mcpServers` are all set per `query()` and become the spawned subprocess's environment.

Open issue **#122** ("SDK MCP servers fail to connect from concurrent query() calls — 60s timeout") is a real concurrency hazard: when multiple `query()` calls in the same Node process share an SDK MCP server name, the SDK's in-process MCP host can race. Workaround: unique SDK MCP server names per session.

### 2.3 Horizontal scaling / multi-instance

**No leader election, no shared state, no session-coordinator.** N pods can serve different sessions; they cannot serve the same session pool with shared state unless they share an external `SessionStore`.

The `SessionStore` interface (sdk.d.ts:3738) plus a Postgres adapter (`examples/session-stores/postgres/`) gets you horizontal scaling — any pod can resume any session ID by reading from the shared store. The local `~/.claude/projects/...` JSONL is the canonical local cache but is no longer authoritative when `sessionStore` is set ("dual write" pattern documented in `Options.sessionStore`, sdk.d.ts:1378).

`forkSession` (sdk.d.ts:622) is also store-aware (`SessionMutationOptions.sessionStore`), so a forked session can be persisted to the same shared store.

### 2.4 Background / async / scheduled tasks

- **Background sub-agents**: `AgentDefinition.background: true` (sdk.d.ts:79) and `AgentInput.run_in_background: true` (sdk-tools.d.ts:301) — the parent's turn completes immediately; the sub-agent runs to completion and emits a `task_notification` event when done.
- **Background Bash commands**: `BashInput.run_in_background: true` (sdk-tools.d.ts:345) — same fire-and-forget semantics. `TaskOutputInput` polls completion.
- **Cron-horizon scheduling**: `AssistantWorkerOptions.scheduling.dir` (assistant.d.ts:72) — the worker polls `<dir>/.claude/scheduled_tasks.json` every 10s and spawns the child ~5s before a fire is due. This is **local-only** and tied to the worker's filesystem — not a distributed cron. BYO for distributed scheduling.
- **Webhook triggers**: BYO. The SDK has no webhook intake.

### 2.5 Worker pool / queue model

**Not provided — BYO.** The `Query` interface includes `streamInput()` and `stopTask()` (sdk.d.ts:2251, 2256) which give you the primitives for a long-running streaming session, but there is no shipped queue, no `enqueue()` API, no leasing semantics. For a long-running agent that fan-outs persona experiments overnight, you'd build that on top with BullMQ / Cloud Tasks / etc.

---

## 3. Sessions & Persistence

### 3.1 Session / chat data model

Session metadata is `SDKSessionInfo` (sdk.d.ts:3383):

```ts
export declare type SDKSessionInfo = {
  sessionId: string;       // UUID
  summary: string;         // display title (custom > AI > first prompt)
  lastModified: number;    // epoch ms
  fileSize?: number;       // for local JSONL only
  customTitle?: string;    // user-set via /rename
  firstPrompt?: string;
  gitBranch?: string;      // git branch at session-end
  cwd?: string;
  tag?: string;            // user-set via tagSession()
  createdAt?: number;      // epoch ms, from first entry timestamp
};
```

`SessionKey` for the store layer (sdk.d.ts:3668) — the actual identifier used by `SessionStore.append/load/delete`:

```ts
export declare type SessionKey = {
  projectKey: string;  // caller-defined scope. Default: sanitized cwd. "Multi-tenant deployments should set this to a tenant ID or project name."
  sessionId: string;
  subpath?: string;    // omitted = main transcript. Set = subagent transcript.
};
```

**This is the closest thing to a `tenantId` field on the session model** — `projectKey` is explicitly meant for multi-tenant scoping per the docstring.

Per-message: `SDKAssistantMessage` and `SDKUserMessage` both carry `session_id`, `uuid`, `parent_tool_use_id`, `subagent_type`, `task_description`, plus the Anthropic API message body (`BetaMessage` / `MessageParam`).

### 3.2 What's stored on a session

The JSONL transcript ("session entries") covers:

- `user` messages (incl. tool_result echoes)
- `assistant` messages (incl. tool_use)
- `system` events: init, status, compact_boundary, memory_recall, task_*, files_persisted, plugin_install, permission_denied, mirror_error
- `summary` rows (from AI-generated titles)
- `custom_title`, `tag` rows
- compaction `preserved_segment` / `preserved_messages` anchors
- subagent transcripts in `subpath: 'subagents/agent-<id>'`

The `SessionStoreEntry` type is intentionally opaque (sdk.d.ts:3830):

```ts
export declare type SessionStoreEntry = {
  type: string;
  uuid?: string;
  timestamp?: string;
  [k: string]: unknown;  // rest is pass-through JSON
};
```

Tool-call history is part of the assistant/user messages (`tool_use` and `tool_result` blocks). File checkpoints (`enableFileCheckpointing: true`) are stored separately as on-disk backups (mentioned in `SDKFilesPersistedEvent`); the `rewindFiles(userMessageId)` Query method restores them — not part of `SessionStore`.

### 3.3 Granularity

- Single conversation per session.
- **Forks supported** via `forkSession(sessionId, { upToMessageId?, title?, sessionStore? })` (sdk.d.ts:622). Branches at a specific message UUID with full UUID remapping and `parentUuid` chain preservation. Forked sessions start without file-checkpoint history.
- No LangGraph-style cyclical graph / multiple parallel branches per session — fork creates a new sessionId.

### 3.4 Built-in persistence stores

| Backend | Status |
|---|---|
| **JSONL on local disk** | Default. `~/.claude/projects/<cwd-sanitized>/<sessionId>.jsonl`. Subagent transcripts in `<sessionId>/subagents/agent-<id>.jsonl`. Disabled with `persistSession: false`. |
| **`InMemorySessionStore`** | Shipped class (sdk.d.ts:825). For tests and dev only. |
| **Postgres** | Reference adapter in `examples/session-stores/postgres/`. Schema: one row per entry, `jsonb` column, `BIGSERIAL` for ordering. Conformance-tested. |
| **Redis** | Reference adapter in `examples/session-stores/redis/`. Uses `RPUSH` + sorted set for session index. Conformance-tested. |
| **S3** | Reference adapter in `examples/session-stores/s3/`. Stores JSONL as part files `s3://{bucket}/{prefix}{projectKey}/{sessionId}/part-{epochMs}-{rand}.jsonl`. Conformance-tested. |
| **SQLite, MongoDB, Cassandra, DynamoDB, Cloudflare R2, Vercel Blob** | Not provided — BYO. The `SessionStore` interface is small (6 methods) so adapters are short (~120 LOC each). |
| **Anthropic-hosted / vendor cloud** | Only via `attachBridgeSession` (alpha, `bridge.d.ts:171`) which writes to claude.ai-side CCR storage. Not the same as a server-side primary persistence — it's for sync to claude.ai for human handoff. |

### 3.5 Persistence timing

Documented in `SessionStore.append()` (sdk.d.ts:3739–3759):

> *Mirror a batch of transcript entries. Called AFTER the subprocess's local write succeeds — durability is already guaranteed locally. Batches arrive at ~100 ms cadence during active turns.*

And in `Options.sessionStoreFlush` (sdk.d.ts:1396 + 3849):

- `'batched'` (default): coalesced at end-of-turn or pending-threshold.
- `'eager'`: every frame flushes via background `append()`. Adapters should be cheap per call.

Failure mode: **3 retries with short backoff**, then drop the batch and emit `SDKMirrorErrorMessage` (sdk.d.ts:3198). Timeouts (60 s) are NOT retried.

**Local-disk write IS synchronous to the loop** (the subprocess writes the JSONL line before continuing). External `sessionStore.append()` is **dual-write, post-local, batched** — so durability is local-first and the external store is an eventual mirror. If you set `persistSession: false`, the mirror cannot fire (the docstring explicitly forbids the combination — sdk.d.ts:1378).

### 3.6 Mid-run checkpointing (durable)

**The subprocess's local JSONL write is the durability boundary.** Each transcript entry is flushed line-by-line. A crash mid-tool-call resumes from the last flushed JSONL line; the partial tool call is lost (no per-task `commit()` like LangGraph). On resume, the CLI re-reads the JSONL, rebuilds the message chain, and continues.

For an external store, durability is **post-local + batched + eventually consistent** — a 100 ms window where a crash drops entries from the external store but they remain in local JSONL. Recovery: re-run `importSessionToStore()` (sdk.d.ts:779) against the local file.

This is **not a true durable checkpoint primitive** in the LangGraph sense. The `_runner.commit() → put_writes()` per-task pattern does not exist.

### 3.7 Session ID format

**UUID v4** (`crypto.randomUUID()` — visible in the bundled mjs). You can override with `Options.sessionId` (must be a valid UUID) — sdk.d.ts:1597. Forking with `forkSession` mints a fresh UUID.

The `projectKey` on `SessionKey` is caller-defined string (default: sanitized cwd). **Multi-tenant deployments should set `projectKey` to a tenant ID or project name** — explicitly recommended in the docstring (sdk.d.ts:3669).

### 3.8 Pluggable store interface

Yes — `SessionStore` (sdk.d.ts:3738) is the interface to implement:

```ts
export declare type SessionStore = {
  append(key: SessionKey, entries: SessionStoreEntry[]): Promise<void>;
  load(key: SessionKey): Promise<SessionStoreEntry[] | null>;
  listSessions?(projectKey: string): Promise<Array<{ sessionId: string; mtime: number }>>;
  listSessionSummaries?(projectKey: string): Promise<SessionSummaryEntry[]>;
  delete?(key: SessionKey): Promise<void>;
  listSubkeys?(key: { projectKey: string; sessionId: string }): Promise<string[]>;
};
```

The first two are required; the rest are optional (`delete` no-ops for WORM stores like S3).

Marked `@alpha`. Conformance suite: `examples/session-stores/shared/conformance.ts` (13 tests across all adapters; vendored so the example dirs are standalone).

### 3.9 Schema evolution / migration

- `importSessionToStore(sessionId, store, options?)` (sdk.d.ts:779) — copy a local JSONL session into a `SessionStore`. Useful for migrating from local-disk to Postgres.
- `foldSessionSummary(prev, key, entries, options?)` (sdk.d.ts:604) — pure function that adapters call inside `append()` to keep a `SessionSummaryEntry` sidecar up-to-date without re-reading the transcript. Set-once fields freeze on first sight; last-wins fields overwrite. This is how the Postgres / Redis / S3 adapters maintain the `listSessionSummaries()` view.
- No automatic migration helpers for schema bumps within the SDK. Bumps to the `SessionStoreEntry` schema are CLI-side and rare; adapters treat entries as opaque pass-through.

### 3.10 Export / replay

- `getSessionMessages(sessionId, options?)` (sdk.d.ts:681) — read user/assistant messages in chronological order from the JSONL. Optional `includeSystemMessages`.
- `getSessionInfo(sessionId, options?)` (sdk.d.ts:651) — single-session metadata.
- `listSessions(options?)` (sdk.d.ts:885) — paginated session listing. Has the `sessionStore` option but per **issue #268** spawns a full subprocess when reading from local disk.
- `listSubagents(sessionId, options?)` (sdk.d.ts:929) — list subagent transcripts under a session.
- Deterministic replay via `query({ options: { resume: sessionId, sessionStore } })` — re-runs the conversation from the stored transcript. Combined with `resumeSessionAt: messageUuid` you can replay up to a specific point.

### 3.11 Cross-session memory

Different from in-session messages — see **§15 (Memory & Knowledge)**. The CLI has a memory recall supervisor that surfaces relevant memories from `~/.claude/agent-memory/<agentType>/` (or `.claude/agent-memory/` per-project / `.claude/agent-memory-local/`) into the turn via `SDKMemoryRecallMessage`. Scoping is by `AgentDefinition.memory: 'user' | 'project' | 'local'` (sdk.d.ts:83). It is *not* tenant-scoped out of the box.

---

## 4. Multi-tenancy & Arbitrary Context ⭐

### 4.1 Full run-loop input struct

`Options` (sdk.d.ts:1158–1836) — ~80 fields. The decision-relevant subset:

```ts
export declare type Options = {
  // === Identity ===
  sessionId?: string;          // UUID — caller-chosen, otherwise auto-generated
  resume?: string;             // resume an existing session
  resumeSessionAt?: string;    // resume up to this message UUID
  continue?: boolean;          // continue last session in cwd
  forkSession?: boolean;
  title?: string;
  cwd?: string;                // process cwd — also the filesystem-projectKey root

  // === Tenant-shaped (no first-class tenantId) ===
  env?: { [k: string]: string | undefined };  // injected into subprocess env
  additionalDirectories?: string[];           // extra dirs the agent can access
  settings?: string | Settings;               // inline settings or path
  managedSettings?: Settings;                 // policy-tier settings from embedder
  settingSources?: SettingSource[];           // 'user' | 'project' | 'local'
  pathToClaudeCodeExecutable?: string;
  spawnClaudeCodeProcess?: (opts: SpawnOptions) => SpawnedProcess;

  // === Toolset ===
  tools?: string[] | { type: 'preset'; preset: 'claude_code' };
  allowedTools?: string[];
  disallowedTools?: string[];
  toolAliases?: Record<string, string>;
  toolConfig?: ToolConfig;
  mcpServers?: Record<string, McpServerConfig>;

  // === Authorship ===
  agent?: string;                                  // main thread agent name
  agents?: Record<string, AgentDefinition>;        // inline sub-agent defs
  skills?: string[] | 'all';                       // skill filter
  plugins?: SdkPluginConfig[];                     // 'local' only as of 0.3.143
  systemPrompt?: string | string[] | { type: 'preset'; preset: 'claude_code'; append?: string; excludeDynamicSections?: boolean };
  planModeInstructions?: string;
  outputFormat?: OutputFormat;

  // === Behavior ===
  permissionMode?: PermissionMode;
  allowDangerouslySkipPermissions?: boolean;
  permissionPromptToolName?: string;
  canUseTool?: CanUseTool;
  hooks?: Partial<Record<HookEvent, HookCallbackMatcher[]>>;
  onElicitation?: OnElicitation;
  sandbox?: SandboxSettings;
  effort?: EffortLevel;
  thinking?: ThinkingConfig;
  maxThinkingTokens?: number;
  maxTurns?: number;
  maxBudgetUsd?: number;
  taskBudget?: { total: number };
  fallbackModel?: string;
  model?: string;
  betas?: SdkBeta[];

  // === Streaming / observability ===
  includeHookEvents?: boolean;
  includePartialMessages?: boolean;
  forwardSubagentText?: boolean;
  agentProgressSummaries?: boolean;
  promptSuggestions?: boolean;
  stderr?: (data: string) => void;
  debug?: boolean;
  debugFile?: string;

  // === Persistence ===
  persistSession?: boolean;
  sessionStore?: SessionStore;
  sessionStoreFlush?: SessionStoreFlush;
  loadTimeoutMs?: number;
  enableFileCheckpointing?: boolean;

  // === Control ===
  abortController?: AbortController;
  strictMcpConfig?: boolean;
  executable?: 'bun' | 'deno' | 'node';
  executableArgs?: string[];
  extraArgs?: Record<string, string | null>;
};
```

**There is no first-class `tenantId` field.** Tenants are modeled by:

- `cwd` (process cwd)
- `SessionKey.projectKey` (recommended by the SDK doc for multi-tenant scoping)
- `env` (anything you want, including `TENANT_ID`)
- `sessionStore` instance (which can be tenant-aware)
- closures inside `canUseTool` / hooks (which capture tenant-shaped state)

### 4.2 Context propagation into a tool call

For **SDK MCP tools** registered with `tool(...)` and surfaced via `createSdkMcpServer(...)`, the handler signature is:

```ts
handler: (args: InferShape<Schema>, extra: unknown) => Promise<CallToolResult>;
```

`extra` is the MCP request context (token, request meta) — *not* a harness-injected `RunContext`. There is no first-class `extra.tenantId` propagated by the SDK.

The actual propagation patterns in production:

1. **Closure capture.** Define the tool inside a per-tenant function that closes over `tenantId`:

   ```ts
   function makeTopicSearch(tenantId: string) {
     return tool(
       'topicSearch',
       'Search topics for a tenant',
       { query: z.string() },
       async (args) => { return topicSearchService(tenantId, args.query); }
     );
   }
   ```

2. **`PreToolUse` hook closure.** The hook callback closes over `tenantId` and mutates `tool_input.tenantId` before dispatch (see §4.4).

3. **`canUseTool` closure.** Same — the callback returns `{ behavior: 'allow', updatedInput: { ...input, tenantId } }`.

4. **Env vars on subprocess.** `Options.env = { TENANT_ID: 'acme', ...process.env }`. The CLI's built-in `Bash` tool sees these env vars; SDK-MCP tools can read `process.env.TENANT_ID` (same Node process).

There is no `ctx.tenantId` injected for you — you wire it.

### 4.3 Tool call interface

For SDK-MCP tools:

```ts
// sdk.d.ts:5592
export declare function tool<Schema extends AnyZodRawShape>(
  _name: string,
  _description: string,
  _inputSchema: Schema,                                  // Zod 3 or Zod 4 shape
  _handler: (args: InferShape<Schema>, extra: unknown) => Promise<CallToolResult>,
  _extras?: {
    annotations?: ToolAnnotations;
    searchHint?: string;
    alwaysLoad?: boolean;
  }
): SdkMcpToolDefinition<Schema>;
```

`CallToolResult` is the MCP standard result type (re-exported from `@modelcontextprotocol/sdk/types.js`). It's a `{ content: Array<{ type: 'text', text: string } | { type: 'image', ... } | ...> }` shape.

### 4.4 Forcing tool arguments from the harness

**Yes — two mechanisms, both first-class.**

#### Mechanism A: `canUseTool` permission callback

```ts
// sdk.d.ts:155
export declare type CanUseTool = (
  toolName: string,
  input: Record<string, unknown>,
  options: { signal: AbortSignal; toolUseID: string; agentID?: string; ... }
) => Promise<PermissionResult>;

// sdk.d.ts:1887
export declare type PermissionResult =
  | { behavior: 'allow';
      updatedInput?: Record<string, unknown>;   // <-- force args here
      updatedPermissions?: PermissionUpdate[];
      toolUseID?: string;
      decisionClassification?: PermissionDecisionClassification; }
  | { behavior: 'deny'; message: string; interrupt?: boolean; ... };
```

Return `{ behavior: 'allow', updatedInput: { ...input, tenantId: 'acme' } }` and the CLI uses your `updatedInput` instead of the LLM's `input`. **The LLM cannot bypass this** because the CLI dispatches the tool with `updatedInput`, not the original.

#### Mechanism B: `PreToolUse` hook

```ts
// sdk.d.ts:2028
export declare type PreToolUseHookSpecificOutput = {
  hookEventName: 'PreToolUse';
  permissionDecision?: HookPermissionDecision;
  permissionDecisionReason?: string;
  updatedInput?: Record<string, unknown>;       // <-- same mechanism
  additionalContext?: string;
};
```

Same effect — registered under `Options.hooks.PreToolUse`, matched by tool name. Several matchers can run in parallel for the same event; merge semantics are documented per hook.

**Both are out-of-band callbacks invoked via the JSON control protocol over stdio.** The TS hook callback runs *in your Node process*; the CLI does not see your tenant-injection logic, only the resulting `updatedInput`.

### 4.5 Filtering visible tools

Three layered mechanisms:

1. **`Options.tools`** (sdk.d.ts:1264) — base whitelist. `['Bash', 'Read', 'Edit']` or `[]` to disable all built-in tools or `{ type: 'preset', preset: 'claude_code' }` for the default Claude Code set.
2. **`Options.allowedTools`** — tools that auto-pass permission without prompting.
3. **`Options.disallowedTools`** — explicit deny; removes from the model's context entirely.
4. **`Options.toolAliases`** — single-hop name redirect (e.g. `{ Bash: 'mcp__workspace__bash' }`).
5. **`AgentDefinition.tools`** / **`AgentDefinition.disallowedTools`** — per-sub-agent scoping.
6. **`Options.skills: string[] | 'all'`** — limits which skills load into the prompt. Explicitly a *context filter*, not a sandbox (sdk.d.ts:1710).
7. **`Query.setMcpServers(servers)`** — mid-session replace MCP servers (sdk.d.ts:2230). Useful for per-turn dynamic toolset changes.

You can change the toolset at session-start (Options); per-turn changes require `setMcpServers` or `applyFlagSettings` (`{ permissions: { ... } }`).

### 4.6 Tenant scope on session

**Not first-class.** No `tenantId` field on `Options` or `SDKSessionInfo`. The recommended workaround is `SessionKey.projectKey` for store-side scoping (explicitly documented for multi-tenant deployments — sdk.d.ts:3669). Spec authors and engineers can stash tenant in `env`, `metadata` (none — there is no metadata field on Options), `cwd` (per-tenant working directory), or `Options.title`.

**This is a real gap for long-running agent-style multi-tenant SaaS.** You will be modeling tenant as filesystem-cwd + sessionStore.projectKey + env var.

### 4.7 Per-tool-call auth propagation

**Not provided — BYO.** The caller's identity does not flow into tool calls automatically. SDK-MCP tools run in your Node process so you can pull identity from your own request context (e.g. via AsyncLocalStorage). The CLI's built-in tools (Bash, WebFetch, etc.) execute under the subprocess's identity (the OS user that spawned the SDK).

For tenant-aware auth, the standard pattern is closure capture (see §4.2) plus `PreToolUse.updatedInput` to inject a per-call signing token.

### 4.8 Resource scoping primitives

Registration-time scoping is **filesystem-based**:

- **Skills**: `~/.claude/skills/{name}/` (user) or `.claude/skills/{name}/` (project) or `<plugin>/skills/{name}/`. To scope to a tenant: materialize a per-tenant `.claude/skills/` tree under the per-tenant cwd.
- **Sub-agents** (markdown): `~/.claude/agents/{name}.md` / `.claude/agents/{name}.md` / `<plugin>/agents/{name}.md`. Same scoping pattern. Programmatic registration via `Options.agents: Record<string, AgentDefinition>` is a second option.
- **Slash commands**, **CLAUDE.md** memory files, **hooks settings**, **MCP server settings**: all filesystem.

You **cannot register a resource as "tenant X only" via an API call**. You can only filter at runtime via the various option filters.

### 4.9 Per-tenant rate limit + budget cap

- **`Options.maxBudgetUsd`** (sdk.d.ts:1473): a USD ceiling enforced server-side. On overrun: `SDKResultMessage(subtype: 'error_max_budget_usd')`. **This is the only first-party cost cap among the 11 stacks studied; same as the Py SDK.**
- **`Options.maxTurns`** (sdk.d.ts:1466): turn ceiling.
- **`Options.taskBudget.total`** (sdk.d.ts:1481, @alpha): API-side task budget in tokens. Sent as `output_config.task_budget` with the `task-budgets-2026-03-13` beta header — makes the model aware of remaining budget so it can pace tool use.
- No per-tenant cumulative cap. If you need monthly tenant ceilings, aggregate `total_cost_usd` from `SDKResultMessage` into your own store and refuse `query()` calls when the tenant is over.

### ⭐ Required — light usage example

```ts
import { query, tool, createSdkMcpServer, type PreToolUseHookInput } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

// (1) Inject tenant context into Options + tools.
const tenantId = 'acme';
const targetingStrategyId = 'strat-42';
const userId = 'u-123';

const topicSearch = tool(
  'topicSearch',
  'Search Predict topics in the catalog.',
  { query: z.string(), tenantId: z.string() },         // tenantId is part of the schema
  async (args) => {
    return { content: [{ type: 'text', text: await predictApi.search(args.tenantId, args.query) }] };
  },
);
const iabSearch     = tool('iabSearch',     '…', { query: z.string(), tenantId: z.string() }, /*…*/);
const audienceCreate = tool('audienceCreate', '…', { name: z.string(), tenantId: z.string() }, /*…*/);

const predictServer = createSdkMcpServer({
  name: 'predict',
  tools: [topicSearch, iabSearch, audienceCreate],
});

const q = query({
  prompt: 'Build an audience for young moms in Brazil',
  options: {
    sessionId: `${tenantId}-${crypto.randomUUID()}`,
    cwd: `/tenants/${tenantId}`,                       // (a) tenant-scoped filesystem
    env: { ...process.env, TENANT_ID: tenantId, USER_ID: userId, STRAT_ID: targetingStrategyId },
    sessionStore: pgStore,                             // SessionKey.projectKey defaults to sanitized cwd → tenant-scoped
    mcpServers: { predict: predictServer },

    // (2) Restrict visible tools to ONLY our three.
    tools: ['mcp__predict__topicSearch', 'mcp__predict__iabSearch', 'mcp__predict__audienceCreate'],
    // (No 'Bash', 'WebFetch', etc. — they are not in the whitelist, so the LLM cannot see them.)

    // (3) Force tenantId=acme on every topicSearch call, regardless of what the LLM puts.
    hooks: {
      PreToolUse: [{
        matcher: 'mcp__predict__topicSearch',
        hooks: [async (input: PreToolUseHookInput) => ({
          continue: true,
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            updatedInput: { ...(input.tool_input as object), tenantId },  // SERVER WINS
          },
        })],
      }],
    },

    maxBudgetUsd: 0.50,                                // per-run USD cap
  },
});
for await (const msg of q) { /* stream to client */ }
```

All three steps work. The `tenantId` injection via `PreToolUse.updatedInput` is the canonical multi-tenant pattern and is identical in the Python SDK.

---

## 5. Hook & Middleware Capabilities (Context Engineering)

### 5.1 Enumerate every hook / middleware / lifecycle callback

`HOOK_EVENTS` (sdk.d.ts:738) — **29 events**:

| Event | Fires when | Can do |
|---|---|---|
| `PreToolUse` | Before each tool dispatch | Allow/deny, mutate `updatedInput`, inject `additionalContext`, set `permissionDecisionReason` |
| `PostToolUse` | After each tool returns | Replace `updatedToolOutput` (all tools) / `updatedMCPToolOutput` (MCP only), inject `additionalContext` |
| `PostToolUseFailure` | After a tool failure | Inject `additionalContext` (recovery suggestion) |
| `PostToolBatch` | Once per turn after all tools resolved | Inject `additionalContext` |
| `Notification` | Loop-side text notification queued | Observe / mutate |
| `UserPromptSubmit` | User typed a prompt | Inject `additionalContext`, set `sessionTitle`, `suppressOriginalPrompt`, block via `decision: 'block'` |
| `UserPromptExpansion` | Slash command or MCP prompt expanded | Inject `additionalContext` |
| `SessionStart` | New / resume / clear / compact | Inject `additionalContext`, set `initialUserMessage`, set `watchPaths` |
| `SessionEnd` | Session ends | Observe |
| `Stop` | Loop wants to stop (`stop_reason: 'end_turn'`) | Force continue via `continue: false`-like reasoning (returns `decision: 'block'` to keep going) |
| `StopFailure` | Loop ended with an error | Observe |
| `SubagentStart` | A sub-agent (Task tool) started | Inject `additionalContext` |
| `SubagentStop` | A sub-agent ended | Observe |
| `PreCompact` | Before auto-compaction | Set custom instructions |
| `PostCompact` | After compaction | Observe (has `compact_summary`) |
| `PermissionRequest` | Permission needed | Allow/deny with `updatedInput`/`updatedPermissions` |
| `PermissionDenied` | A permission decision was deny | Observe / `retry` |
| `Setup` | Workspace setup phase | Inject `additionalContext`, set `watchPaths` |
| `TeammateIdle` | Multi-agent teammate idle | Observe |
| `TaskCreated` | Task created (sub-agent fan-out) | Observe |
| `TaskCompleted` | Task done | Observe |
| `Elicitation` | MCP server requested user input | `accept` / `decline` / `cancel` with `content` |
| `ElicitationResult` | After elicitation response | Observe / override response |
| `ConfigChange` | Settings file changed | Observe |
| `WorktreeCreate` | Sub-agent isolation mode created a worktree | Set `worktreePath` |
| `WorktreeRemove` | Worktree removed | Observe |
| `InstructionsLoaded` | CLAUDE.md or similar loaded | Observe |
| `CwdChanged` | cwd changed mid-session | Set `watchPaths` |
| `FileChanged` | File watched changed | Set `watchPaths` |

This is the **most comprehensive hook surface** in the 11-stack comparison — strictly more than Mastra, LangGraph, Vercel AI, Eino, ADK, OpenAI Agents.

### 5.2 Hook concurrency model

Multiple matchers per hook event can be configured. The matchers fire **per call site** (e.g. one `PreToolUse` matcher per tool name). Within a single event firing, matchers are evaluated and their outputs are merged — typically with **last-wins** semantics on `updatedInput`. Asynchronous hooks are supported via `AsyncHookJSONOutput` (sdk.d.ts:118) which signals `async: true, asyncTimeout?: number` so the CLI doesn't block the dispatch beyond a deadline.

### 5.3 Specific capability tests

| Capability | Yes/No | How |
|---|---|---|
| **Inject system messages at session start** | ✅ | `SessionStart` hook returns `{ additionalContext: 'tenant=acme, locale=fr-FR, today=2026-05-16' }`. Also `Options.systemPrompt: { type: 'preset', preset: 'claude_code', append: '...' }` for static injection. |
| **Expand user input** | ✅ | `UserPromptSubmit` hook with `additionalContext` (added before model) or `UserPromptExpansion` for slash commands. |
| **Mutate the messages list before each LLM call** | ⚠️ Partial — the CLI owns the messages list; you cannot directly mutate it. You inject *context* via `additionalContext` and the CLI prepends it as a synthetic user message. For prompt-cache breakpoint control, use `Options.systemPrompt: [..., SYSTEM_PROMPT_DYNAMIC_BOUNDARY, ...]`. |
| **Mutate / decorate tool input before dispatch** | ✅ | `PreToolUse.updatedInput` or `canUseTool.updatedInput`. |
| **Mutate / decorate tool result before it returns to the LLM** | ✅ | `PostToolUse.updatedToolOutput` (any tool) / `updatedMCPToolOutput` (MCP only, deprecated). |
| **Emit additional tool calls in response to a tool result** | ❌ | The TS SDK's `PostToolUseHookSpecificOutput` (sdk.d.ts:2002) does NOT expose an `additional_messages` field. The Py SDK has the same shape. *Both lack this.* The closest workaround: return `additionalContext` so the model is prompted to call another tool, but you cannot force a tool call. |

### 5.4 Auto-compaction

**Built-in.** The CLI auto-compacts when context approaches the model's window. `PreCompact` and `PostCompact` hooks fire. `PreCompact.custom_instructions` lets you steer the summarization prompt. The `SDKCompactBoundaryMessage` (`type: 'system', subtype: 'compact_boundary'`) marks where compaction happened and lists `preserved_segment` / `preserved_messages` for clean resume.

Trigger: implicit threshold (no SDK option). Custom-trigger via slash command `/compact` from the user side; programmatically you can set `Query.applyFlagSettings({ ... })` to nudge.

### 5.5 Prompt cache optimization

**First-class.** Three mechanisms:

1. **`Options.systemPrompt: string[]`** with the constant `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` (sdk.d.ts:5524) inserted as a standalone element splits the prompt into a static (cacheable across sessions) prefix and dynamic suffix.
2. **`excludeDynamicSections: true`** (sdk.d.ts:1755) on the preset prompt — strips per-user dynamic sections (cwd, auto-memory, git status) so the preset is identical across users; the stripped content is re-injected as the first user message. **Cross-user prompt cache hit** — the killer feature for multi-tenant fleets.
3. The CLI handles cache breakpoint placement automatically for stable-prefix content (system prompt, tool catalog).

Cache hit/miss stats are surfaced on `SDKResultMessage.usage.cache_creation_input_tokens` and `cache_read_input_tokens`.

### 5.6 Tool result clearing / progressive disclosure

- **PostToolUse `updatedToolOutput`**: replace the tool result in-place before it goes to the model. Use this to truncate / summarize / redact. (sdk.d.ts:2008)
- **File scratchpad pattern**: the built-in `Write` / `Edit` / `Read` tools encode the progressive-disclosure pattern naturally — large outputs go to disk, the model receives a path it can `Read` on demand.
- **`getContextUsage()` query method** (sdk.d.ts:2152) returns a per-category breakdown (system prompt / tools / messages / MCP / memory / agents / skills / commands) so you can decide when to compact / clear.
- **MCP tool descriptions deferred** by default (`alwaysLoad: false` is the default) — MCP tool definitions are not included in the prompt until tool-search is invoked, saving tokens.

### 5.7 Architectural diagram — where hooks fire

```mermaid
flowchart TD
  START([query() called]) --> SS[SessionStart hook]
  SS --> SU[Setup hook]
  SU --> UPS[UserPromptSubmit hook]
  UPS --> UPE{Slash cmd / MCP prompt?}
  UPE -->|Yes| UPEH[UserPromptExpansion hook]
  UPE -->|No|  API[Anthropic API call]
  UPEH --> API
  API --> ASSIST{assistant has tool_use?}
  ASSIST -->|No| STOP[Stop hook]
  ASSIST -->|Yes| PRE[PreToolUse hook<br/>updatedInput / decision]
  PRE --> PERM[PermissionRequest hook<br/>+ canUseTool callback]
  PERM --> DISPATCH[Tool dispatch<br/>built-in / MCP / SDK-MCP]
  DISPATCH --> POST[PostToolUse hook<br/>or PostToolUseFailure<br/>updatedToolOutput]
  POST --> BATCH{All tools in batch done?}
  BATCH -->|No| DISPATCH
  BATCH -->|Yes| PBATCH[PostToolBatch hook]
  PBATCH --> PCC{Context near limit?}
  PCC -->|Yes| PRECOMPACT[PreCompact hook]
  PRECOMPACT --> POSTCOMPACT[PostCompact hook]
  POSTCOMPACT --> API
  PCC -->|No| API
  STOP --> RESULT([SDKResultMessage])
  RESULT --> END([SessionEnd hook])
```

Sub-agent hooks (`SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`) fire on the parent's stream when the CLI's `Agent` tool spawns / completes a sub-agent.

### ⭐ Required — light usage example

```ts
import { query, type SessionStartHookInput, type PreToolUseHookInput, type PostToolUseHookInput } from '@anthropic-ai/claude-agent-sdk';

const tenantId = 'acme';
const locale = 'fr-FR';

const q = query({
  prompt: 'Find topics for young moms',
  options: {
    hooks: {
      // (1) Inject tenant context on session start.
      SessionStart: [{
        hooks: [async (_input: SessionStartHookInput) => ({
          continue: true,
          hookSpecificOutput: {
            hookEventName: 'SessionStart',
            additionalContext: `tenant=${tenantId}, locale=${locale}, today=2026-05-16`,
          },
        })],
      }],
      // (2) Force tenantId on every topicSearch call.
      PreToolUse: [{
        matcher: 'mcp__predict__topicSearch',
        hooks: [async (input: PreToolUseHookInput) => ({
          continue: true,
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            updatedInput: { ...(input.tool_input as object), tenantId },
          },
        })],
      }],
      // (3) Summarize big topicSearch results in place.
      PostToolUse: [{
        matcher: 'mcp__predict__topicSearch',
        hooks: [async (input: PostToolUseHookInput) => {
          const out = input.tool_response as { topics?: unknown[] };
          if (out?.topics && out.topics.length > 50) {
            return {
              continue: true,
              hookSpecificOutput: {
                hookEventName: 'PostToolUse',
                updatedToolOutput: {
                  topics: out.topics.slice(0, 50),
                  truncated: true,
                  total: out.topics.length,
                },
              },
            };
          }
          return { continue: true };
        }],
      }],
    },
  },
});
for await (const msg of q) { /* ... */ }
```

All three scenarios are first-class. The `additionalContext` from `SessionStart` is prepended to the system prompt by the CLI; the `updatedInput` from `PreToolUse` replaces the LLM's input; the `updatedToolOutput` from `PostToolUse` replaces what the model sees as the tool result.

---

## 6. Agent API Exposition (HTTP/network surface)

### 6.1 Does the stack ship an HTTP/network server?

**No.** The SDK is library-only. You embed `query()` in your own Express / Fastify / Next.js / Bun.serve / Hono route handler.

There is a *browser-side* SDK (`@anthropic-ai/claude-agent-sdk/browser`) that exposes `query({ websocket: { url, headers, authMessage } })` — but it is the **client** of a WebSocket server *you build*. The bridge / WebSocket *server* is your responsibility.

The `bridge.mjs` and `assistant.mjs` sub-exports talk to **claude.ai's CCR endpoint** for the hosted-on-Anthropic deployment mode — not a server you can run yourself.

### 6.2 Streaming transport

In-process: `AsyncGenerator<SDKMessage>`. You decide the wire transport.

Common patterns:
- **Server → browser**: SSE (consume the SDK iterator, stringify each `SDKMessage` as `data: ...\n\n`).
- **Server → browser** alternate: WebSocket (use the `browser-sdk` import on the client).
- **CLI subprocess ↔ SDK**: line-delimited JSON over stdin/stdout, `--input-format stream-json --output-format stream-json`.

### 6.3 Endpoints that start an agent run

Not provided. Sample BYO pattern:

```ts
import express from 'express';
import { query } from '@anthropic-ai/claude-agent-sdk';

const app = express();
app.use(express.json());

app.post('/v1/sessions/:sid/turns', async (req, res) => {
  const tenantId = req.header('x-tenant-id');
  if (!tenantId) return res.status(401).end();
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.flushHeaders();

  const q = query({
    prompt: req.body.prompt,
    options: {
      sessionId: req.params.sid,
      cwd: `/tenants/${tenantId}`,
      sessionStore: pgStore,
      // hooks / mcpServers / tools per tenant
    },
  });
  req.on('close', () => q.close());
  for await (const msg of q) {
    res.write(`data: ${JSON.stringify(msg)}\n\n`);
  }
  res.end();
});
```

### 6.4 Live agentic event stream format

You define the wire format. The natural SSE encoding is one `SDKMessage` JSON per `data:` frame. See §1.12 for sample frames.

### 6.5 Auth termination at API boundary

**Not provided — BYO.** The SDK does not validate JWTs, OAuth, or anything else. Auth termination happens in your HTTP layer (your `app.post` handler). Once authenticated, you pass tenant context to `query()` via `cwd` / `env` / closure-captured hook callbacks.

For the claude.ai bridge path (`bridge.mjs`), an Anthropic OAuth token is required (`getAccessToken` field on `ConnectRemoteControlOptions`, sdk.d.ts:231).

### 6.6 Resume / replay endpoint

The SDK provides the *logic* (`query({ options: { resume: sessionId } })`); you provide the endpoint.

```ts
app.post('/v1/sessions/:sid/resume', async (req, res) => {
  const q = query({
    prompt: req.body.prompt,
    options: { resume: req.params.sid, sessionStore: pgStore },
  });
  // ... stream q
});
```

For replay-from-point: `resumeSessionAt: messageUuid` (sdk.d.ts:1603).

### 6.7 Interrupt / cancel via API

In-process: `Query.interrupt()` (sdk.d.ts:2062) or `Query.close()` (sdk.d.ts:2278) — the latter forcefully terminates the subprocess. Both work via the JSON control protocol over stdio (`SDKControlInterruptRequest`, sdk.d.ts:2798).

You can also pass `Options.abortController?: AbortController` and call `controller.abort()` from anywhere.

API: BYO. Pattern is `DELETE /v1/sessions/:sid/turn` → call `q.interrupt()` on the right `Query` handle.

### 6.8 Tool-arg streaming (partial JSON)

**Yes — via `includePartialMessages: true`.** This emits `SDKPartialAssistantMessage` (`type: 'stream_event'`) — wrapping the raw `BetaRawMessageStreamEvent` from `@anthropic-ai/sdk` (sdk.d.ts:3226). The wrapped Anthropic stream events include `input_json_delta` events that progressively reveal the tool's JSON input character-by-character as the model generates it. Consumers parse these to render "topicSearch({ query: 'young'..." in real time.

### 6.9 HITL approval workflow

The HITL primitive is `canUseTool`. The full flow:

1. LLM emits `tool_use`.
2. CLI sends `control_request: can_use_tool` over stdio to SDK.
3. SDK's `canUseTool` callback runs (in your Node process). You can:
   - Return `{ behavior: 'allow', updatedInput }` immediately for safe tools.
   - **Await human input**: your callback returns a Promise that resolves only when your operator UI posts a verdict. You correlate via the `toolUseID` argument.
4. SDK replies with `control_response`.
5. CLI dispatches the tool with the verdict.

There is **no separate pause-state observable** to the client — the entire HITL flow is mediated by the SDK consumer (your code). For client-visible pause, you'd emit a custom SSE frame from your HTTP handler when `canUseTool` is awaiting human input, and resolve the inner Promise when the client POSTs an `/approve` or `/deny`.

### 6.10 Tool-call state reconstruction ⭐

`SDKAssistantMessage.message.content` is a `BetaMessage` content array. Tool calls appear as content blocks of `type: 'tool_use'` with an `id` field (Anthropic API standard).

The matching `tool_result` arrives as a `SDKUserMessage.message.content` block of `type: 'tool_result'` with a `tool_use_id` field that exactly equals the `id` of the assistant's tool_use block.

```jsonc
// Assistant turn (one frame)
{ "type": "assistant", "session_id": "...", "message": { "content": [
  { "type": "text", "text": "I'll search." },
  { "type": "tool_use", "id": "toolu_01XYZ", "name": "topicSearch", "input": { "query": "young moms" } }
] }, "uuid": "asst-uuid-1" }

// Tool-progress heartbeats (multiple frames may follow)
{ "type": "tool_progress", "tool_use_id": "toolu_01XYZ", "elapsed_time_seconds": 1.2 }

// Tool result (next user-role frame)
{ "type": "user", "session_id": "...", "message": { "content": [
  { "type": "tool_result", "tool_use_id": "toolu_01XYZ", "content": "[...10 topics...]" }
] } }
```

**Linkage is explicit and stable: `tool_use_id`.** Both `SDKToolProgressMessage` (`tool_use_id` field on the message itself) and the `tool_result` block (`tool_use_id` in the block) carry it. For sub-agent fan-out, `SDKAssistantMessage.parent_tool_use_id` tracks which parent tool call spawned this assistant message.

### 6.11 Health checks / graceful shutdown

**Not provided.** Your HTTP server provides `/healthz`, `/readyz`, `/metrics`. The SDK has:

- `Query.close()` to terminate one subprocess.
- `AbortController` integration for SIGTERM-style drain (on SIGTERM your handler calls `controller.abort()` for each in-flight Query).

The bundled CLI subprocess does not expose an HTTP health endpoint of its own.

### ⭐ Required — light usage example

#### 1. Start a run with `X-Tenant-Id` and a user message

```bash
curl -N -X POST https://api.example.com/v1/sessions/2f3c.../turns \
  -H 'Authorization: Bearer eyJ...' \
  -H 'X-Tenant-Id: acme' \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Build an audience for young moms in Brazil"}'
```

#### 2. Sample SSE the client receives

```
data: {"type":"system","subtype":"init","session_id":"2f3c-...","model":"claude-opus-4-7","tools":["mcp__predict__topicSearch","mcp__predict__iabSearch","mcp__predict__audienceCreate"],"permissionMode":"default","mcp_servers":[{"name":"predict","status":"connected"}],"uuid":"..."}

data: {"type":"assistant","session_id":"2f3c-...","message":{"id":"msg_01ABC","role":"assistant","model":"claude-opus-4-7","content":[{"type":"text","text":"Let me find relevant topics."},{"type":"tool_use","id":"toolu_01XYZ","name":"mcp__predict__topicSearch","input":{"query":"young moms","tenantId":"acme"}}],"stop_reason":"tool_use","usage":{"input_tokens":1500,"output_tokens":42,"cache_creation_input_tokens":0,"cache_read_input_tokens":1200}},"uuid":"..."}

data: {"type":"tool_progress","tool_use_id":"toolu_01XYZ","tool_name":"mcp__predict__topicSearch","parent_tool_use_id":null,"elapsed_time_seconds":1.8,"uuid":"..."}

data: {"type":"user","session_id":"2f3c-...","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01XYZ","content":"[{\"topic\":\"parenting/babies\",\"score\":0.95},...]"}]},"uuid":"..."}

data: {"type":"result","subtype":"success","session_id":"2f3c-...","duration_ms":4200,"num_turns":2,"total_cost_usd":0.018,"result":"Found 12 relevant topics including parenting/babies, household, kids.","usage":{"input_tokens":1800,"output_tokens":140,"cache_creation_input_tokens":0,"cache_read_input_tokens":1200,"server_tool_use":null,"service_tier":"standard","cache_creation":null},"modelUsage":{"claude-opus-4-7":{"input_tokens":1800,"output_tokens":140,"cost_usd":0.018}},"permission_denials":[],"is_error":false,"terminal_reason":"completed","uuid":"..."}
```

#### 3. Cancel mid-flight

```bash
curl -X DELETE https://api.example.com/v1/sessions/2f3c.../turn \
  -H 'Authorization: Bearer eyJ...' \
  -H 'X-Tenant-Id: acme'
# Server-side: handler holds the Query handle in a Map<sessionId, Query>; on DELETE → q.interrupt()
```

#### 4. HITL approval verdict for a paused tool call

```bash
curl -X POST https://api.example.com/v1/sessions/2f3c.../approvals \
  -H 'Authorization: Bearer eyJ...' \
  -d '{"toolUseId": "toolu_01XYZ", "decision": "allow", "updatedInput": {"query":"young moms","tenantId":"acme","limit":10}}'
# Server-side: resolves the Promise inside the canUseTool callback for this toolUseId
```

The SSE encoding, the `interrupt()` mechanism, and the HITL pattern are all **patterns you build**; the SDK ships the primitives.

---

## 7. Sub-agents

### 7.1 Mechanism

Sub-agents are dispatched as a **special tool** — the CLI's built-in `Agent` tool (formerly named `Task`, renamed in 0.3.142 — CHANGELOG.md:11). When the parent LLM emits `tool_use` with `name: 'Agent'` and `input: { subagent_type, prompt, ... }`, the CLI spawns a sub-agent with its own model context, runs it to completion (or in the background), and returns the result as a `tool_result` to the parent.

So: agents-as-tools, but first-class in the CLI (you cannot disable the Agent tool's special semantics).

### 7.2 Configuration

Two ways:

1. **Programmatic, inline**: `Options.agents: Record<string, AgentDefinition>` (sdk.d.ts:1203) — register at session start.
2. **Markdown files**: `~/.claude/agents/{name}.md` (user) / `.claude/agents/{name}.md` (project) / `<plugin>/agents/{name}.md`. Same frontmatter schema as `AgentDefinition`.

`AgentDefinition` (sdk.d.ts:38):

```ts
{
  description: string;                                            // when to use this agent
  prompt: string;                                                 // system prompt
  tools?: string[];                                               // tool whitelist (inherits if omitted)
  disallowedTools?: string[];
  model?: string;                                                 // model alias or full ID, 'inherit' = parent
  mcpServers?: AgentMcpServerSpec[];
  criticalSystemReminder_EXPERIMENTAL?: string;
  skills?: string[];                                              // skills preloaded into context
  initialPrompt?: string;                                         // auto-submitted as first user turn
  maxTurns?: number;
  background?: boolean;                                           // fire-and-forget
  memory?: 'user' | 'project' | 'local';                          // agent-memory scope
  effort?: EffortLevel | number;
  permissionMode?: PermissionMode;
}
```

### 7.3 LLM-generated configs

**No.** Configs must be statically registered at session start (via `Options.agents` or on disk). The parent LLM cannot generate a new sub-agent config on the fly with a custom system prompt — it can only choose `subagent_type` from registered agents. (This is a deliberate Claude Code design — see issue #315 for plugin-loaded agent gotchas.)

### 7.4 Output handling

The parent sees the sub-agent result as a regular `tool_result` block on a `user`-role message, linked by `tool_use_id`. By default only `tool_use` / `tool_result` blocks emit from sub-agents (lightweight). Set **`Options.forwardSubagentText: true`** (sdk.d.ts:1428) to forward sub-agent assistant text and thinking as nested `SDKAssistantMessage`s with `parent_tool_use_id` set — useful for rendering a nested transcript.

The `AgentOutput` shape (sdk-tools.d.ts:61) includes:
```ts
{
  agentId: string;
  agentType?: string;
  content: { type: 'text'; text: string }[];
  totalToolUseCount: number;
  totalDurationMs: number;
  totalTokens: number;
  usage: { ...full Anthropic API usage... };
  toolStats?: { readCount, searchCount, bashCount, editFileCount, linesAdded, linesRemoved, otherToolCount };
  status: 'completed' | 'async_launched';
  prompt: string;
}
```

### 7.5 Concurrency model

**Parallel via multiple `tool_use` blocks in one assistant turn.** The CLI runs them concurrently (the assistant message can include 3 `Agent` `tool_use` blocks; the CLI dispatches all 3 in parallel, fires `PostToolBatch` once after all resolve). Each sub-agent runs to completion in its own subprocess-internal context.

Background sub-agents: `AgentDefinition.background: true` or per-call `AgentInput.run_in_background: true` (sdk-tools.d.ts:301) — parent's turn completes immediately; sub-agent emits a `task_notification` event when done. Polling via `TaskOutputInput.block: true` (sdk-tools.d.ts:351).

The exact parallelism implementation is in the bundled CLI binary (not visible TS-side). The `PostToolBatch` event firing semantics (sdk.d.ts:1953) document the "fires exactly once with the full batch" contract.

### 7.6 Context isolation

**Sub-agent starts fresh.** It does NOT see the parent's context — only its own system prompt, its own `initialPrompt` (if set), and its own tool catalog. The parent only receives the sub-agent's final result (or with `forwardSubagentText: true`, the intermediate text).

Sub-agent transcripts persist separately under `<sessionId>/subagents/agent-<id>.jsonl` on disk, or with `SessionKey.subpath = 'subagents/agent-<id>'` in the store.

### 7.7 Lifecycle events

- `SubagentStart` hook (parent stream observes).
- `SubagentStop` hook.
- `TaskCreated`, `TaskCompleted` hooks.
- `SDKTaskStartedMessage`, `SDKTaskProgressMessage` (with `summary` if `agentProgressSummaries: true`), `SDKTaskUpdatedMessage`, `SDKTaskNotificationMessage` — emitted on the parent's stream so the UI can render sub-agent status.

### ⭐ Required — light usage example

```ts
import { query, type AgentDefinition } from '@anthropic-ai/claude-agent-sdk';

const personaAgents: Record<string, AgentDefinition> = {
  'persona-young-mom': {
    description: 'Predict targeting persona: young mom in Brazil, age 25-35, parenting & household focus',
    prompt: 'You are a young mom in Brazil. Evaluate audiences from this perspective. Return JSON {fit: 0-1, why: string}.',
    tools: ['mcp__predict__topicSearch'],   // sub-agent toolset
    model: 'haiku',                          // cheap worker
    maxTurns: 6,
  },
  'persona-tech-bro': {
    description: 'Predict targeting persona: tech professional, 28-40, gadgets & startups',
    prompt: 'You are a tech professional. Evaluate audiences. Return JSON {fit: 0-1, why: string}.',
    tools: ['mcp__predict__topicSearch'],
    model: 'haiku',
    maxTurns: 6,
  },
  'persona-retiree': {
    description: 'Predict targeting persona: retiree, 65+, health & travel',
    prompt: 'You are a retiree. Evaluate audiences. Return JSON {fit: 0-1, why: string}.',
    tools: ['mcp__predict__topicSearch'],
    model: 'haiku',
    maxTurns: 6,
  },
};

const q = query({
  prompt: 'For the candidate audience X, fan out to all three personas in parallel and return a verdict matrix.',
  options: {
    agents: personaAgents,
    model: 'opus',                           // supervisor on big model
    forwardSubagentText: true,               // render the nested transcript on the UI
    agentProgressSummaries: true,            // get "Persona evaluating X" heartbeats
  },
});

for await (const msg of q) {
  if (msg.type === 'system' && msg.subtype === 'task_started') {
    console.log(`[${msg.subagent_type}] started: ${msg.description}`);
  }
  if (msg.type === 'system' && msg.subtype === 'task_notification' && msg.status === 'completed') {
    console.log(`[${msg.subagent_type}] done in ${msg.usage?.duration_ms}ms`);
  }
  if (msg.type === 'assistant' && msg.parent_tool_use_id) {
    // sub-agent assistant text (because forwardSubagentText: true)
    console.log(`[sub] ${msg.subagent_type}: ${JSON.stringify(msg.message.content)}`);
  }
  if (msg.type === 'user' && msg.message.role === 'user') {
    // parent receives sub-agent result here, with tool_use_id linkage
  }
}
```

The supervisor LLM emits three `Agent` tool_use blocks in one turn (parent prompt nudges this). CLI dispatches them in parallel; each result flows back as a `tool_result` with linkage by `tool_use_id`. Lifecycle events stream throughout.

---

## 8. Skills

### 8.1 First-class concept?

**Yes.** Skills are a first-class feature inherited from Claude Code. They are loaded as part of the session and gated by the `Options.skills` filter or the `Skill` tool (now deprecated in `allowedTools`; use `skills` option instead — CHANGELOG.md:52).

### 8.2 File format

Markdown file with YAML frontmatter, conventionally `SKILL.md`. Standard Claude Code schema (from observation of the loaded skills set; the SDK doesn't re-document the format since it's CLI-side):

```yaml
---
name: generate-audience-from-brief
description: Convert a long-running agent brief into a Predict audience definition with topics + IABs + locale filter.
license: internal
allowed-tools:
  - mcp__predict__topicSearch
  - mcp__predict__iabSearch
  - mcp__predict__audienceCreate
trigger: Use when user provides a long-running agent brief and asks for an audience to be created.
---

# Generate Audience From Brief

## Steps
1. Extract demographics, interests, brand voice from the brief.
2. Call topicSearch with the interest keywords.
3. Call iabSearch with the demographics.
4. Combine: keep top-N topics, top-K IABs.
5. Call audienceCreate with the combined list.
```

The frontmatter fields are CLI-validated (the SDK does not parse them itself — it just reads what the CLI surfaces).

### 8.3 Loader mechanism

**Filesystem scan.** The CLI discovers skills from three roots (matching the broader Claude Code convention):

- `~/.claude/skills/*/SKILL.md` (user-global)
- `.claude/skills/*/SKILL.md` (project, relative to `cwd`)
- `<plugin>/skills/*/SKILL.md` (plugin-bundled, when `Options.plugins: [{ type: 'local', path: '<plugin>' }]`)

Programmatic registration: **none.** You cannot pass a skill body via `Options`. You must materialize the `SKILL.md` to a filesystem path the CLI can read.

This is the same as the Python SDK and matches the doc note: "skills … remain on disk and are reachable via Read/Bash. Do not store secrets in skill files." (sdk.d.ts:1710).

### 8.4 Invocation

**Lazy fetch via a `Skill` tool.** The CLI surfaces the skill list as metadata in the system prompt (name + description); the model invokes a skill by emitting `tool_use` with name `Skill` (or per the deprecated path, by including `'Skill'` in `allowedTools`). The body of the `SKILL.md` is fetched on use, not eagerly loaded into the prompt.

The skill list emitted in `SDKSystemMessage.skills` (sdk.d.ts:3488) is the filtered set per `Options.skills`.

### 8.5 Loading mode

**Lazy by default** (metadata in system prompt; body fetched on use). The `Options.skills: string[] | 'all'` (sdk.d.ts:1721) controls *which* skills are listed in the prompt:

- omitted: CLI defaults apply (NOT skills-off — important nuance).
- `'all'`: every discovered skill is listed.
- `string[]`: only listed skills are listed.

### 8.6 Runtime scoping (global / tenant / user)

At runtime, `Options.skills` filters per call. Tenant scoping is achieved by either:

- Materializing per-tenant `.claude/skills/` trees and pointing `cwd` at the tenant root, OR
- Passing a tenant-specific `Options.skills: ['tenant-acme:audience-gen', ...]` whitelist with all tenant skills in one shared registry.

**There is no `tenantId → skills` mapping API.** Same gap as Py SDK.

### 8.7 Skill composition

- Can reference other skills via plugin-qualified names (`<plugin>:skill-name` per the comment at sdk.d.ts:1708).
- Can call sub-agents (skill body is markdown; the LLM reads it and decides to invoke `Agent` tool).
- Can pull in bundled assets via `Read`/`Bash` on relative paths inside the skill directory.

### ⭐ Required — light usage example

#### 1. Author `SKILL.md`

```bash
mkdir -p .claude/skills/generate-audience-from-brief/
cat > .claude/skills/generate-audience-from-brief/SKILL.md <<'EOF'
---
name: generate-audience-from-brief
description: Convert a long-running agent brief into a Predict audience.
allowed-tools:
  - mcp__predict__topicSearch
  - mcp__predict__iabSearch
  - mcp__predict__audienceCreate
trigger: Use when the user provides a brief and asks to create a Predict audience.
---

# Generate Audience From Brief

## Steps
1. Parse the brief into (demographics, interests, brand_voice).
2. Call `mcp__predict__topicSearch(query=interests)`.
3. Call `mcp__predict__iabSearch(query=demographics)`.
4. Combine top-50 topics + top-20 IABs.
5. Call `mcp__predict__audienceCreate({ name, topics, iabs, locale })`.
6. Return the created audience ID and a one-paragraph summary.
EOF
```

#### 2. Load at runtime (filesystem-discovered)

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';

const q = query({
  prompt: 'Brief: "Reach French young moms with eco-friendly diapers, mass-market tone, 18-35yo." Create an audience.',
  options: {
    cwd: process.cwd(),                        // .claude/skills/ is discovered under cwd
    skills: ['generate-audience-from-brief'],  // only this skill is surfaced
    mcpServers: { predict: predictServer },
    tools: [
      'Skill',
      'mcp__predict__topicSearch',
      'mcp__predict__iabSearch',
      'mcp__predict__audienceCreate',
    ],
  },
});
```

#### 3. The agent discovering and invoking it

The CLI surfaces "generate-audience-from-brief" in the system prompt's skill catalog (name + description). The LLM, given the user brief, emits `tool_use` with `name: 'Skill'` and `input: { skill: 'generate-audience-from-brief' }` (or invokes via the skill's `trigger` text). The CLI fetches the skill body, injects it as additional system context, and the model then proceeds to call the listed `mcp__predict__*` tools. **The skill is invoked as a tool call to `Skill`; not as a hook, not as a static system-prompt fragment** — lazy fetch.

---

## 9. Resource Manager

### 9.1 First-class Resource Manager?

**No first-class Resource Manager.** The SDK does not ship a registry, source abstraction, or publishing workflow. Resources (skills, sub-agents, slash commands, hooks, MCP servers, plugins) are discovered from filesystem paths the CLI knows to scan. There is no `Registry.register(resource, scope)` API.

The `plugins: SdkPluginConfig[]` option (sdk.d.ts:1561) gets *close* — it's a list of paths to install — but the only supported `type` is `'local'`. No Git, no OCI, no S3, no remote registry.

### 9.2 Loading sources

| Source | Status | How configured |
|---|---|---|
| **Local filesystem** | ✅ | `~/.claude/skills/`, `.claude/skills/`, `~/.claude/agents/`, `.claude/agents/`, `.claude/commands/`, `~/.claude/commands/`, `CLAUDE.md`, plus `<plugin>/skills/`, `<plugin>/agents/` |
| **Git / GitHub repos** | ❌ | Not provided — BYO (git-clone into a plugin dir then `plugins: [{ type: 'local', path: ... }]`). The CHANGELOG mentions a `marketplace` setting that can `autoUpdate` (Settings type, sdk.d.ts:4556) but it's a Claude Code CLI feature accessed via settings.json, not a programmatic API for the SDK consumer. |
| **OCI / container registries** | ❌ | Not provided — BYO |
| **Cloud object storage (S3 / GCS / R2)** | ❌ for skills; ✅ for **session persistence** via `SessionStore` (reference S3 adapter) |
| **Postgres / relational DB** | ❌ for skills; ✅ for **session persistence** via reference adapter |
| **Vendor cloud / managed registry** | ❌ | No Hub. The `bridge.mjs` claude.ai integration is for session sync, not resource sync. |
| **HTTP fetch (arbitrary URL)** | ❌ for skills (CLI doesn't `WebFetch` skills). MCP HTTP servers can come from HTTP URLs (sdk.d.ts:951). |
| **MCP HTTP/SSE/WS servers** | ✅ | `Options.mcpServers` accepts `McpHttpServerConfig`, `McpSSEServerConfig`, `McpStdioServerConfig`. This is the only non-filesystem dynamic source for *tools*. |
| **Plugin marketplaces (Settings tier)** | ⚠️ CLI-only | Claude Code Settings has a marketplace concept, but the SDK exposes it only via `Settings.plugins.marketplaces` config (read-only from SDK side; `reloadPlugins()` re-scans). |

**Net**: for skills / sub-agents / slash commands, the SDK is filesystem-only. For tools you can plug HTTP/SSE MCP servers. For sessions you have Postgres/Redis/S3 reference adapters.

### 9.3 Source composition / priority

CLI-side precedence (observable via the Settings cascade):

1. `--settings` CLI arg (`Options.settings` flag layer) — highest user precedence.
2. `.claude/settings.local.json` (project local — uncommitted).
3. `.claude/settings.json` (project — committed).
4. `~/.claude/settings.json` (user-global).
5. Managed settings (`Options.managedSettings`, MDM/plist/registry, `managed-settings.json`) — policy tier, restrictive-only.

For resources themselves (skills/agents/commands), the layering is **plugin-bundled + project + user + managed**, with project winning over user. Conflict resolution: by name; later-loaded wins for same-name. (No documented explicit precedence diagram, but observable from `reloadPlugins()` semantics.)

### 9.4 Versioning model

- **Skills/sub-agents** in plugins: versioned by the plugin's own versioning (whatever Git tag the plugin dir comes from). No semver enforcement by the SDK.
- **CLI itself**: `claude_code_version` is `'2.1.143'` (manifest.json), pinned to the npm package version (matching `claudeCodeVersion` field in package.json).
- No content-hash addressing, no immutable refs, no rollback API. To "roll back" a skill: replace the file on disk and call `Query.reloadPlugins()`.

### 9.5 Scoping at the registry layer

**Not supported.** You cannot mark a skill "tenant X only" at publish time — there is no publish workflow. The only scoping is filesystem placement (per-tenant cwd) and runtime filter (`Options.skills`).

### 9.6 Publishing workflow

**Not provided — BYO.** There is no draft → review → publish → promote pipeline. You'd build:

- A Git repo per tenant for `.claude/` trees.
- CI that publishes to a per-tenant S3 bucket.
- A sync agent on each pod that pulls per-tenant trees on session start.

### 9.7 Lifecycle / governance

**Not provided — BYO.** No lifecycle states, no RBAC on publish/scope/retire. You'd track this in your own DB and enforce via your own UI.

### 9.8 Programmatic API

For the resource types that *are* dynamic:

- **MCP servers**: `Query.setMcpServers(servers)` (sdk.d.ts:2244) — mid-session replace dynamic MCP servers.
- **Plugins**: `Query.reloadPlugins()` (sdk.d.ts:2173) — refresh from disk after the plugin dir changes.
- **Skills**: no `setSkills` API mid-session; you must restart the query.
- **Sub-agents**: `supportedAgents()` lists what's available (sdk.d.ts:2139); no `addAgent()`.

For listing:

- `Query.supportedCommands()` → `SlashCommand[]`
- `Query.supportedAgents()` → `AgentInfo[]`
- `Query.mcpServerStatus()` → `McpServerStatus[]`
- `Query.getContextUsage()` → per-category breakdown (includes `skills.totalSkills`, `skills.includedSkills`, `agents`, `mcpTools`, etc.)

### 9.9 Caching & sync model

- Plugin files: read on session start; refresh with `reloadPlugins()`.
- Settings: cached per-call; can hot-reload with `applyFlagSettings()`.
- MCP server tool lists: cached after first connect; refresh with `reconnectMcpServer()` or `setMcpServers()`.
- Sessions: per-turn append to JSONL (and `SessionStore` if set); read on resume.

No background sync, no auto-pull from remote, no file watching for skill changes during a live session (skill changes require either `reloadPlugins()` or a fresh session). `CwdChanged` and `FileChanged` hooks can be used to wire your own watch.

### ⭐ Required — light usage example

A truthful example for *this stack* — because the SDK does not have a multi-source Resource Manager, the example shows the manual scaffolding you'd own:

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';
import { execSync } from 'child_process';
import { existsSync, mkdirSync } from 'fs';

// (1) "Register" two sources by materializing them under <tenant-cwd>/.claude/skills/
//     The SDK does not provide source registration; we mimic it on the filesystem.
const tenantId = 'acme';
const tenantRoot = `/var/tenants/${tenantId}`;
const skillsDir = `${tenantRoot}/.claude/skills`;

if (!existsSync(skillsDir)) mkdirSync(skillsDir, { recursive: true });

// Source A: shared org skills from Git.
execSync(
  `git clone --depth=1 https://github.com/dailymotion/predict-skills ${skillsDir}/_shared`,
  { stdio: 'inherit' },
);
// Source B: tenant-specific overrides from S3 — wins on conflict via later scan precedence.
execSync(
  `aws s3 sync s3://predict-skills/tenants/${tenantId}/ ${skillsDir}/_tenant`,
  { stdio: 'inherit' },
);

// (2) "Promote draft → active for tenant acme only".
//     There's no publish workflow; you do it by moving a file into the tenant-scoped tree.
execSync(
  `aws s3 cp s3://predict-skills/draft/audience-gen-v2/SKILL.md s3://predict-skills/tenants/${tenantId}/audience-gen-v2/SKILL.md`,
);
execSync(
  `aws s3 sync s3://predict-skills/tenants/${tenantId}/ ${skillsDir}/_tenant`,
);

// (3) List active skills visible to a request for this tenant.
//     `supportedCommands()` returns commands + skills.
const q = query({
  prompt: '/list-skills',
  options: { cwd: tenantRoot, skills: 'all' },
});
const skills = await q.supportedCommands();
console.log(skills.map((s) => s.name));
q.close();
```

**Every step here is BYO scaffolding around a filesystem-only loader.** A real multi-tenant deployment would build a `ResourceManager` service that materializes per-tenant trees on session start and ties skill IDs to a Postgres registry. The SDK gives you no help.

---

## 10. Observability: Usage, Cost, Tracing, Audit

### 10.1 Where tokens are surfaced

- **Per assistant message**: `SDKAssistantMessage.message.usage` (sdk.d.ts:2492 — `BetaMessage.usage` per Anthropic API: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `server_tool_use`, `service_tier`, `cache_creation`).
- **Per result (turn termination)**: `SDKResultMessage.usage` (sdk.d.ts:3368). Same `NonNullableUsage` shape — cumulative for the request loop.
- **Per result, per model**: `SDKResultMessage.modelUsage: Record<string, ModelUsage>` — broken down by model when `fallbackModel` or sub-agents on different models were used.
- **Per sub-agent**: `AgentOutput.usage` (sdk-tools.d.ts:72) — cumulative for the sub-agent's lifetime. Open issue **#293** requests per-sub-agent breakdown in `modelUsage` for cost attribution; not currently provided.
- **Context usage snapshot**: `Query.getContextUsage()` (sdk.d.ts:2152) returns categorized token totals (system prompt, tools, messages, MCP, memory, agents, skills, commands) for the *current state*.

### 10.2 Per-call / per-turn / per-session / per-tenant rollups

| Granularity | Surfaced where |
|---|---|
| **Per LLM call** | `SDKAssistantMessage.message.usage` |
| **Per turn (one result loop)** | `SDKResultMessage` |
| **Per session** | **BYO** — sum `SDKResultMessage` across turns of the same `session_id`. The SDK does not maintain a session-level rollup. |
| **Per tenant** | **BYO** — keyed by `SessionKey.projectKey` you assign |
| **Per sub-agent** | `AgentOutput.usage` |
| **Per model** | `SDKResultMessage.modelUsage[model]` |

### 10.3 USD cost computation

**Yes — built-in.**

- `SDKResultMessage.total_cost_usd` (sdk.d.ts:3367) — per result. Computed by the CLI based on model pricing tables it bundles.
- `Options.maxBudgetUsd` (sdk.d.ts:1473) — server-side enforced ceiling; on overrun `subtype: 'error_max_budget_usd'`.

### 10.4 Per-tenant / per-conversation cost

`total_cost_usd` is per `SDKResultMessage`. For per-tenant / per-conversation: aggregate by `session_id` and your own `tenantId` mapping. The SDK does not roll these up for you. The `SessionStore` is *not* an aggregation point; entries are opaque pass-through.

### 10.5 LLM / tool tracing

- **OTel trace context auto-propagated** to the CLI subprocess (CHANGELOG.md:143: *"Added OpenTelemetry trace context propagation — the caller's active trace context is forwarded to the CLI subprocess so spans parent under your distributed trace"*).
- The CLI binary emits OTel spans for LLM calls and tool calls when configured (via settings — see CHANGELOG references to OTel events).
- No first-party LangSmith / LangFuse exporter. You instrument your own SDK consumer code (around `query()` calls and hook callbacks) using `@opentelemetry/api`.

### 10.6 Audit logging

**Not first-class.** The closest thing is the on-disk JSONL transcript (every action of the loop is in there: tool calls, decisions, permission denials, model responses). It is append-only on local disk; with a `SessionStore` mirror you get a tamper-resistant copy.

For a true audit log, hook `PostToolUse` / `PermissionDenied` / `PermissionRequest` and push events to your own audit sink.

### 10.7 Canonical "where do I read token counts" code path

`SDKResultMessage.usage` (sdk.d.ts:3368) and `SDKResultMessage.total_cost_usd` (sdk.d.ts:3367). The single source of truth per-turn:

```ts
// sdk.d.ts:3356
export declare type SDKResultSuccess = {
  type: 'result';
  subtype: 'success';
  duration_ms: number;
  duration_api_ms: number;
  ttft_ms?: number;
  num_turns: number;
  result: string;
  total_cost_usd: number;
  usage: NonNullableUsage;
  modelUsage: Record<string, ModelUsage>;
  permission_denials: SDKPermissionDenial[];
  // ...
};
```

`NonNullableUsage` and `ModelUsage` are re-exports from `@anthropic-ai/sdk` (so the schema matches Anthropic API exactly).

### ⭐ Required — light usage example

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';
import { metrics } from '@opentelemetry/api';
import StatsD from 'hot-shots';

const dd = new StatsD({ host: 'localhost', port: 8125, prefix: 'predict.' });
const meter = metrics.getMeter('predict-agent');
const tokensIn  = meter.createCounter('llm.tokens.input',  { unit: 'tokens' });
const tokensOut = meter.createCounter('llm.tokens.output', { unit: 'tokens' });
const costUsd   = meter.createCounter('llm.cost.usd',     { unit: 'USD' });

async function runOneTurn(tenantId: string, sessionId: string, prompt: string) {
  const q = query({ prompt, options: { sessionId, sessionStore: pgStore, /* per-tenant cwd, hooks, … */ } });
  for await (const msg of q) {
    if (msg.type === 'result') {
      // (1) Read token + cost off the result.
      console.log({
        tokens_in:  msg.usage.input_tokens,
        tokens_out: msg.usage.output_tokens,
        cache_read: msg.usage.cache_read_input_tokens,
        cost_usd:   msg.total_cost_usd,
        turns:      msg.num_turns,
        duration:   msg.duration_ms,
      });
      // (2) Push per-tenant rollup to Datadog + OTel.
      const tags = [`tenant:${tenantId}`, `session:${sessionId}`];
      dd.gauge('llm.tokens.in',  msg.usage.input_tokens,   tags);
      dd.gauge('llm.tokens.out', msg.usage.output_tokens,  tags);
      dd.gauge('llm.cost.usd',   msg.total_cost_usd,       tags);
      tokensIn.add(msg.usage.input_tokens,    { tenant: tenantId });
      tokensOut.add(msg.usage.output_tokens,  { tenant: tenantId });
      costUsd.add(msg.total_cost_usd,         { tenant: tenantId });
      // (3) Roll-up by model (cheap-supervisor + expensive-worker)
      for (const [model, m] of Object.entries(msg.modelUsage)) {
        dd.gauge('llm.cost.usd.by_model', m.cost_usd, [...tags, `model:${model}`]);
      }
    }
  }
}
```

`total_cost_usd` is the killer metric; the SDK is one of the only stacks that gives you USD directly without you maintaining a pricing table.

---

## 11. Built-in Tools & Tool Authoring API

### 11.1 Built-in tools shipped in the box

From `sdk-tools.d.ts:11` (the `ToolInputSchemas` union) — the CLI ships **25+ built-in tools**:

| Tool | Purpose |
|---|---|
| `Bash` | Shell command exec with `timeout`, `description`, `run_in_background`, `dangerouslyDisableSandbox` |
| `Read` (FileRead) | Read file with `offset`, `limit`, `pages` (PDF), absolute paths |
| `Write` (FileWrite) | Write file with absolute path + content |
| `Edit` (FileEdit) | Anchor-based edit: `old_string` → `new_string` with optional `replace_all` |
| `Glob` | Filesystem glob with `pattern` + optional `path` |
| `Grep` | ripgrep wrapper with `pattern`, `path`, `glob`, output mode `content|files_with_matches|count`, plus rg flags `-A/-B/-C/-i/-n/-o` |
| `WebFetch` | HTTP GET with URL + optional prompt-as-context |
| `WebSearch` | Anthropic-managed web search |
| `Agent` | Spawn a sub-agent (formerly `Task`, renamed 0.3.142) |
| `TaskCreate` | New explicit task (replaces deprecated `TodoWrite`) |
| `TaskGet` / `TaskUpdate` / `TaskList` | Task CRUD |
| `TaskStop` | Stop a running task |
| `TaskOutput` | Poll a background task's output |
| `NotebookEdit` | Jupyter notebook cell edit |
| `Skill` | Invoke a discovered skill (lazy fetch) |
| `AskUserQuestion` | HITL question with options + previewFormat (markdown/html) |
| `ListMcpResources` / `ReadMcpResource` | MCP resource catalog access |
| `Mcp` | Direct MCP tool invoke |
| `EnterWorktree` / `ExitWorktree` | Git worktree management for sub-agent isolation |
| `ExitPlanMode` | Exit plan mode after presenting a plan |

### 11.2 Built-in tool quality

These are **the same battle-tested tools from Claude Code interactive mode** — production-grade.

- `Edit` uses **anchor-string matching with uniqueness validation** (the LLM fails fast if `old_string` is not unique unless `replace_all: true`). This makes the model's edits surprisingly reliable.
- `Read` returns content **with line numbers prefixed** so subsequent `Edit` calls can use precise anchors.
- `Bash` has a **mandatory natural-language description field** (sdk-tools.d.ts:329) the model fills in — useful for audit logs.
- `Grep` is a thin ripgrep wrapper with the full flag set exposed (`-A`, `-B`, `-C`, `-i`, `-n`, etc.) — exactly what an experienced engineer would reach for.
- `WebFetch` and `WebSearch` are Anthropic-managed (no API key needed beyond the Anthropic key).
- `Agent` (sub-agent) supports `isolation: 'worktree'` to run on a temporary git worktree — clean isolation for parallel edit-style agents.
- `Skill` does on-demand body fetch (token-saving lazy load).
- All tools have **JSON-schema input validation** generated from TypeScript types.

This is genuinely the strongest built-in tool catalog among the 11 stacks studied — same level as the Py SDK, far ahead of generic adapters like Vercel AI / Mastra / Eino.

### 11.3 Tool authoring API

The smallest possible custom tool definition:

```ts
import { tool, createSdkMcpServer } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

const myTool = tool(
  'topicSearch',                                    // name
  'Search the Predict topic catalog.',              // description (visible to LLM)
  { query: z.string(), limit: z.number().optional() },  // Zod schema (validated)
  async (args) => {                                 // handler
    const topics = await predictApi.search(args.query, args.limit ?? 10);
    return { content: [{ type: 'text', text: JSON.stringify(topics) }] };
  },
);

const predictServer = createSdkMcpServer({
  name: 'predict',
  tools: [myTool],
});

// Then pass to query():
query({
  prompt: '...',
  options: { mcpServers: { predict: predictServer } },
});
```

The tool name **as visible to the LLM** is `mcp__predict__topicSearch` (MCP namespacing: `mcp__{serverName}__{toolName}`).

### 11.4 Typed tool I/O

**Yes — Zod (v3 or v4) schemas.** The `tool()` factory uses Zod for both schema generation (sent to the LLM) and runtime validation (of the LLM's tool_use input). On invalid args, the SDK MCP layer returns an error result and the loop sees `is_error: true` on the `tool_result`, prompting the model to correct.

### 11.5 Streaming tools

**Partial.**

- The `Bash` tool with `run_in_background: true` (sdk-tools.d.ts:345) returns immediately; output is polled via `TaskOutputInput.block: true` (sdk-tools.d.ts:351).
- `SDKToolProgressMessage` (sdk.d.ts:3586) emits `elapsed_time_seconds` heartbeats during long tool calls so the UI can show progress.
- For **mid-execution partial results** to the model (i.e. the tool yields chunks that the model consumes before the tool completes): **not supported.** The model only sees the final `tool_result` block.

---

## 12. MCP (Model Context Protocol) Support

### 12.1 MCP client support

**First-class.** The CLI consumes external MCP servers natively via `Options.mcpServers` (sdk.d.ts:1498). Supported transports:

```ts
// sdk.d.ts:979
export declare type McpServerConfig =
  | McpStdioServerConfig    // command + args + env
  | McpSSEServerConfig      // SSE URL + headers + OAuth
  | McpHttpServerConfig     // streamable HTTP URL + headers + OAuth
  | McpSdkServerConfigWithInstance;  // in-process SDK server
```

Plus internal CLI-only types (visible in the bundled mjs but not in the public API): `claudeai-proxy` and `ws`/`ws-ide` for IDE integrations.

### 12.2 MCP server support

You can **expose your tools as an SDK MCP server** via `createSdkMcpServer` (sdk.d.ts:428) — but this server is **in-process to your Node process, not externally connectable**. Other agents/clients cannot connect to it from outside your process.

For exposing tools to *other processes* via MCP, you would write a standalone MCP server using `@modelcontextprotocol/sdk` directly and have the consumer connect to it as an external `McpStdioServerConfig`.

### 12.3 Transports

- **stdio** ✅
- **SSE** ✅
- **streamable HTTP** ✅ (alias `'streamable-http'` → `'http'`)
- **WebSocket** ⚠️ (visible in CLI internals but not in public `McpServerConfig` union — for IDE servers like `ws-ide`)
- **In-process SDK** ✅ via `McpSdkServerConfigWithInstance`

### 12.4 In-process MCP

**Yes — `createSdkMcpServer` is exactly this.** You define a TypeScript function with `tool(...)`, wrap it in a `createSdkMcpServer({ name, tools })`, pass it via `mcpServers`, and the CLI invokes it via the JSON control protocol over stdio (no subprocess spawn).

This is how Predict tools should be exposed for production — no separate MCP-server-as-subprocess cost.

### 12.5 Auth / lifecycle

- **stdio servers**: credentials passed as `env`.
- **HTTP/SSE servers**: `headers` object or **OAuth flow** (DE config: `clientId`, `callbackPort`, `authServerMetadataUrl`, `scopes` — visible in the bundled mjs schema).
- **Reconnection**: `Query.reconnectMcpServer(serverName)` (sdk.d.ts:2214); also automatic reconnect after transport stream abort (CHANGELOG.md:112: *"Long-running SDK sessions now reconnect claude.ai-proxied MCP servers after a transport-stream abort"*).
- **Health**: `Query.mcpServerStatus()` returns `{ status: 'connected' | 'failed' | 'needs-auth' | 'pending' | 'disabled', error?, tools?, serverInfo? }` (sdk.d.ts:986).
- **Background connect** (since 0.3.142): MCP servers connect in the background by default; sessions start immediately and slow servers report `status: 'pending'` in `init` until ready. Mark `alwaysLoad: true` to force pre-turn-1 connect (CHANGELOG.md:10).
- **Toggle**: `Query.toggleMcpServer(serverName, enabled)` for runtime enable/disable.
- **Set servers mid-session**: `Query.setMcpServers(servers)` to swap the dynamic-server set (sdk.d.ts:2244).
- **Elicitation**: `Options.onElicitation` callback handles MCP server requests for user input (form fields, URL auth).

---

## 13. Multi-model Routing & Fallback

### 13.1 Multi-provider support

Through Anthropic API providers: `'firstParty' | 'bedrock' | 'vertex' | 'foundry' | 'anthropicAws' | 'mantle' | 'gateway'` (sdk.d.ts:32 — `AccountInfo.apiProvider`).

Selection is by environment / settings tier — not via a config knob on `Options`. To route through Bedrock or Vertex, set the appropriate AWS/GCP env vars in `Options.env`; the CLI auto-detects.

**No native OpenAI / Gemini direct support.** OpenAI/Gemini require a gateway (your code translates / runs a LiteLLM-style gateway). This is one of the largest deltas vs. ADK / OpenAI Agents / Eino / Mastra / Vercel AI / LangGraph (all of which natively speak multiple provider APIs).

### 13.2 Per-task model selection

- **Per session**: `Options.model: string` (sdk.d.ts:1502) — e.g. `'claude-sonnet-4-6'`, `'claude-opus-4-7'`, `'sonnet'`, `'opus'`, `'haiku'` aliases.
- **Per sub-agent**: `AgentDefinition.model` (sdk.d.ts:56) — overrides parent's model.
- **Mid-session**: `Query.setModel(model?)` (sdk.d.ts:2076) — changes the model for subsequent responses.

So: cheap-supervisor + expensive-worker is straightforward, by setting `AgentDefinition.model: 'haiku'` for worker personas and keeping the supervisor on `opus`.

### 13.3 Automatic fallback chain

**Yes — `Options.fallbackModel`** (sdk.d.ts:1301): *"Fallback model to use if the primary model fails or is unavailable."*

This is a single-step fallback (not a chain of N models). Triggered by API errors and rate-limit responses. The result `modelUsage` will reflect which model actually served the turn.

For deeper retry / circuit-breaker logic: open issue **#313** ("Expose retry policy / max retry controls for API retries") — not currently exposed.

### 13.4 Mid-stream model switching

`Query.setModel(model)` is at turn boundary only (sdk.d.ts:2076). You cannot switch mid-stream within a single API response.

### 13.5 Sub-agent model overrides

**Yes — `AgentDefinition.model` (sdk.d.ts:56) is exactly this.** Set it to `'haiku'` for cheap workers, leave the parent on `opus`. Required-but-trivial for tenant cost control.

---

## 14. Chat UI Layer

### 14.1 Streaming chat hook

**Not first-party.** No `useChat` React hook, no Svelte / Vue / Solid bindings.

The `@anthropic-ai/claude-agent-sdk/browser` import provides a `query()` function that takes a WebSocket URL and returns the same `Query` async iterator (browser-sdk.d.ts:53). You build the React state on top.

This is a real gap vs. Vercel AI SDK (which is `useChat`-first) and Mastra (which ships a Playground UI).

### 14.2 Tool call rendering primitives

**Not provided — BYO.** The SDK emits typed messages (`SDKAssistantMessage` with `tool_use` blocks, `SDKToolProgressMessage`, `tool_result` blocks) — you write React components that render them. There's no `<ToolCall>` component.

### 14.3 Generative UI components

**Not provided — BYO.** No first-party support for rich UI artifacts. The `AskUserQuestion` tool with `previewFormat: 'html'` (sdk.d.ts:5614) is the closest concept — the model can emit HTML option previews for a choice prompt; you render them in your UI.

### 14.4 BYO pattern

Standard pattern:

1. Server: `query()` in an HTTP handler, stream `SDKMessage` JSON over SSE.
2. Client: open SSE / WebSocket, parse each frame, dispatch to React state by `msg.type`/`msg.subtype`.
3. Use `tool_use_id` to link `tool_use` and `tool_result` in your component state.
4. Render `tool_progress` heartbeats as "tool running…" indicators.

---

## 15. Memory & Knowledge

### 15.1 Long-term memory / semantic recall

**First-party.** The CLI has a memory recall supervisor that surfaces relevant memory files from disk:

- `~/.claude/agent-memory/<agentType>/` — user-scoped.
- `.claude/agent-memory/<agentType>/` — project-scoped.
- `.claude/agent-memory-local/<agentType>/` — local, uncommitted.

Per `AgentDefinition.memory: 'user' | 'project' | 'local'` (sdk.d.ts:83). Surfaced into the turn via `SDKMemoryRecallMessage` (sdk.d.ts:3153) with `mode: 'select' | 'synthesize'` — selector returns full file bodies; synthesizer returns a Sonnet-authored paragraph distilled from many tiny memories.

There is no vector index of your own data — it scans on-disk files. For true vector-search RAG, **BYO**: define an `mcp__myrag__search` tool that hits Qdrant/Pinecone/etc.

### 15.2 RAG / knowledge retrieval integration

**Not first-party.** No built-in vector store, no chunker, no retriever, no citation primitive. BYO via MCP server.

### 15.3 Per-tenant memory scoping

**Not natural.** Memory dirs are global-per-machine (`~/.claude/agent-memory/`) or project-scoped (under `cwd`). To scope per-tenant: use the per-tenant cwd pattern (`cwd: /tenants/${tenantId}` → memory lives under `.claude/agent-memory/`).

For long-term cross-tenant memory served by a vector DB, BYO an MCP tool.

---

## 16. Safety, Guardrails & Tool Sandboxing

### 16.1 Input/output guardrails

**Not first-party.** No PII redaction, no prompt-injection detection, no hallucination detection out of the box. BYO via `PreToolUse` / `PostToolUse` hooks (e.g. run input through a regex redaction step before tool dispatch).

### 16.2 Tool sandboxing / permission model

**Excellent.** The full surface:

- **`canUseTool` callback** (sdk.d.ts:155) — your TS function decides per-call.
- **`PreToolUse` hook** with `permissionDecision: 'allow' | 'deny' | 'defer'`.
- **`PermissionMode`**: `'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'auto'` (sdk.d.ts:1865). Note `'auto'` uses a model classifier; `'bypassPermissions'` requires `allowDangerouslySkipPermissions: true` (sdk.d.ts:1541) — safety belt.
- **`PermissionRequest` hook** for pre-decision logic.
- **`PermissionUpdate` rules** persisted into settings (`addRules`, `replaceRules`, `removeRules`, `setMode`, `addDirectories`, `removeDirectories`) with destinations `userSettings | projectSettings | localSettings | session | cliArg`.
- **Per-MCP-server tool ACL** via `McpServerToolPolicy`.
- **`Options.disallowedTools`** — hard removal from context.
- **`Options.tools: []`** — disable all built-in tools.

### 16.3 Sandbox provider integrations

**Built-in Linux sandbox via bubblewrap.** `Options.sandbox: SandboxSettings` (sdk.d.ts:1645) configures a bubblewrap-based filesystem / network restriction:

```ts
sandbox: {
  enabled: true,
  autoAllowBashIfSandboxed: true,
  network: { allowLocalBinding: true, allowUnixSockets: ['/var/run/docker.sock'] },
}
```

Linux-only (requires `bubblewrap`). When unavailable, `failIfUnavailable: true` (the default when `enabled: true`) errors at startup rather than silently running unsandboxed.

**No E2B / Daytona / Modal integration** — that's the realm of code-interpreter-style tools, not provided.

### 16.4 Default-deny vs. default-allow

**Default-ask.** `permissionMode: 'default'` prompts for "dangerous" operations (file writes, bash, etc.). The list of what counts as dangerous is CLI-defined and exhaustive. `'dontAsk'` flips to default-deny (only pre-approved tools run).

For server-side / autonomous deployment, you typically set `permissionMode: 'acceptEdits'` or `'bypassPermissions'` (with `allowDangerouslySkipPermissions: true`) and gate via `canUseTool` callback for fine-grained control.

---

## 17. Eval, Testing & CI Gates

### 17.1 Golden datasets / regression suites

**Not provided — BYO.** No golden-dataset format, no regression harness.

The only test-shaped artifact in the repo is the **`SessionStore` conformance suite** (`examples/session-stores/shared/conformance.ts`, 13 cases) — that's an adapter conformance test, not an agent regression test.

### 17.2 LLM-as-judge scoring

**Not provided — BYO.** No first-party LLM-as-judge primitive.

### 17.3 CI eval gates / pre-merge

**Not provided — BYO.** You'd build this with your own eval harness over `query()`.

### 17.4 Trace replay for skill iteration

The local JSONL transcripts (`~/.claude/projects/<cwd>/<sid>.jsonl`) are replayable via `query({ options: { resume: sessionId, resumeSessionAt: messageUuid } })`. Combined with `getSessionMessages()`, you can build a step-through tool. **Not a first-party trace viewer.**

The Claude Code interactive CLI itself has a UI for viewing transcripts; the SDK exposes the same data but no UI.

---

## 18. Local Sandbox & Dev UX

### 18.1 Local agent runner

The **Claude Code interactive CLI** (the same binary the SDK spawns) is itself a local runner — `claude` from the terminal launches an interactive REPL. That's not what the SDK ships as a dev UI; it's the underlying CLI.

For the **SDK consumer**, there is no playground / TUI / web dev UI. You write a script that calls `query()` and run it with `bun run script.ts` or `node --import tsx script.ts`.

### 18.2 Trace inspection

Local JSONL files in `~/.claude/projects/<cwd-sanitized>/<sessionId>.jsonl`. Inspect with `cat`, `jq`, or build your own viewer. The CLI's interactive `/transcript` and `/usage` commands show formatted versions.

### 18.3 Tenant / org switching

Per-tenant testing: change `cwd` and `Options.env`. No first-party tenant switcher UI.

### 18.4 Hot reload

- **Plugins**: `Query.reloadPlugins()` re-scans plugin dirs and refreshes commands/agents/MCP servers.
- **Settings**: `Query.applyFlagSettings({ ... })` merges new settings into the flag layer mid-session.
- **MCP servers**: `Query.setMcpServers(...)` swaps the dynamic set.
- **Skills**: no hot reload mid-session; restart `query()`.
- **Sub-agents**: no hot reload mid-session.
- **System prompt**: not mid-session.
- **Tool list**: only via plugin reload or `setMcpServers`.

The lack of source-watch (for skills / agents / hooks) means dev cycles look like: edit file → restart `query()`.

---

## Architectural diagram

```mermaid
flowchart LR
  subgraph CLIENT[Browser / Mobile Client]
    UI[Your UI<br/>React / Svelte / Native]
    BSDK["@anthropic-ai/claude-agent-sdk/browser<br/>(WebSocket transport)"]
    UI --> BSDK
  end

  subgraph SERVER[Your Node/Bun/Deno Server]
    HTTP[Your HTTP route handler<br/>Express / Fastify / Next.js]
    SDK["@anthropic-ai/claude-agent-sdk<br/>query / tool / createSdkMcpServer"]
    HOOKS[Hooks: 29 events<br/>PreToolUse / PostToolUse / SessionStart / …]
    SDKMCP[In-process SDK MCP<br/>tool() handlers run here]
    STORE[(SessionStore<br/>Postgres / Redis / S3 adapter)]

    HTTP --> SDK
    SDK -.callback.-> HOOKS
    SDK -.in-process MCP.-> SDKMCP
    SDK -.mirror append.-> STORE
  end

  subgraph SUBPROCESS[Claude Code Subprocess]
    CLI[Native binary<br/>207–233 MB<br/>per-platform]
    LOOP[Run loop:<br/>tool dispatch, planner,<br/>permissions, compaction,<br/>skill discovery, sub-agent fan-out]
    FS["~/.claude/projects/<br/>~/.claude/skills/<br/>~/.claude/agents/<br/>~/.claude/agent-memory/<br/>JSONL transcripts"]
    SUBAGENT[Sub-agent worker<br/>(Agent tool)<br/>own context]
    SANDBOX[bubblewrap sandbox<br/>(Linux only)]

    CLI --> LOOP
    LOOP --> FS
    LOOP -.fan-out.-> SUBAGENT
    LOOP -.optional.-> SANDBOX
  end

  subgraph EXT[External Services]
    ANT[Anthropic API<br/>or Bedrock / Vertex /<br/>Foundry / gateway]
    MCP[External MCP servers<br/>stdio / SSE / HTTP / WS]
    GIT[Git / S3 / disk<br/>for skills + plugins]
    CCR[claude.ai bridge<br/>(optional, alpha)]
  end

  BSDK -- "WebSocket<br/>SDKMessage frames" --> HTTP
  SDK -- "spawn(node/bun/binary)<br/>stdio: --input-format stream-json<br/>            --output-format stream-json<br/>JSON-RPC control channel:<br/>can_use_tool / hook_callback / mcp_message" --> CLI
  CLI -- "Anthropic API HTTPS" --> ANT
  CLI -- "stdio / SSE / HTTP / WS" --> MCP
  FS <-- "git clone / s3 sync (BYO)" --> GIT
  SDK <-. "attachBridgeSession<br/>worker-mode (alpha)" .-> CCR
```

---

## Appendix — Files worth reading first

- **`benchmarked-stacks/claude-agent-sdk-typescript/CHANGELOG.md`** — the most informative file in the repo. Documents 0.2.113's switch from bundled JS to native binary (line 137), Postgres/Redis/S3 SessionStore additions, hook-event additions, MCP background-connect breaking change.
- **`benchmarked-stacks/claude-agent-sdk-typescript/examples/session-stores/postgres/src/PostgresSessionStore.ts`** — 122-line production-shape adapter. Read first if you're planning to plug into your own Postgres.
- **`benchmarked-stacks/claude-agent-sdk-typescript/examples/session-stores/shared/conformance.ts`** — 13 conformance tests; the truth about what a `SessionStore` must satisfy.
- **`benchmarked-stacks/claude-agent-sdk-typescript/examples/session-stores/redis/src/RedisSessionStore.ts`** — for the Redis-as-store option; clean reference.
- **`benchmarked-stacks/claude-agent-sdk-typescript/examples/session-stores/s3/src/S3SessionStore.ts`** — for the WORM/append-only S3 option.
- **`benchmarked-stacks/claude-agent-sdk-typescript/examples/session-stores/README.md`** — production checklist per backend (IAM, eviction, pool sizing, jsonb caveats).
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/sdk.d.ts`** — the canonical 5722-line type surface. Start at `Options` (line 1158), `Query` interface (line 2052), `SDKMessage` union (line 3175), `SessionStore` (line 3738), `HOOK_EVENTS` (line 738).
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/sdk-tools.d.ts`** — auto-generated catalog of every built-in tool I/O shape. Start at the `ToolInputSchemas` union (line 11) and skim the per-tool interfaces (lines 281–2244).
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/bridge.d.ts`** — the claude.ai bridge (alpha) shape — for understanding the worker / SSE architecture if you're considering claude.ai-hosted deployment.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/assistant.d.ts`** — `runAssistantWorker` (alpha) — the closest the SDK has to a multi-session runtime, scoped to claude.ai bridge.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/browser-sdk.d.ts`** — 53-line file showing the browser WebSocket-client shape.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/manifest.json`** — confirms the 200 MB native binary per platform (the most important operational fact for sizing your deployment).
