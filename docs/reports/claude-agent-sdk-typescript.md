# Claude Agent SDK TypeScript — Benchmark Analysis

> **Repo**: https://github.com/anthropics/claude-agent-sdk-typescript
> **Commit analysed**: `0e21ebb22c36caca1220c34ae6c9fe8ddad40e47`
> **Branch**: `main`
> **Framework path**: `frameworks/claude-agent-sdk-typescript/`
> **Analysed on**: 2026-10-01

Published SDK studied: `@anthropic-ai/claude-agent-sdk@0.3.286` (npm, bundles Claude Code `2.1.286`). The GitHub repo holds only the changelog, CI workflows and the `examples/session-stores/` adapters; the SDK code is published to npm as a compiled bundle. Citations of the form `sdk.d.ts:N`, `sdk-tools.d.ts:N`, `browser-sdk.d.ts:N`, `bridge.d.ts:N`, `core.d.ts` and `manifest.json` refer to the files inside the 0.3.286 npm tarball. Citations to `CHANGELOG.md` and `examples/` are relative to the submodule root.

## TL;DR

- ⭐ **What this is**: a TypeScript shim (`sdk.mjs` is 1.21 MB minified) that **subprocesses a native Claude Code binary** shipped via per-platform optional npm dependencies (`@anthropic-ai/claude-agent-sdk-{darwin,linux,win32}-{x64,arm64}[-musl]`). Each binary is **225–242 MB** (`manifest.json`). Versions ≤ 0.2.112 spawned `node cli.js`; **0.2.113 switched to native single-file binaries** (CHANGELOG.md:922). Despite the "TypeScript SDK" name, the agent loop runs in the spawned binary, the same architecture as the Python SDK.
- **Ecosystem**: TypeScript (Node ≥ 18, Bun, Deno).
- **Licence and support**: **proprietary, not open source.** `LICENSE.md` reads "© Anthropic PBC. All rights reserved" and points to Anthropic's Commercial Terms; npm `license` is `SEE LICENSE IN README.md`. The previous revision of this report said MIT; that was wrong (the file did not change between commits). Issue #57 ("Opensourcing the SDK code") is still open. Anthropic maintains it; support is GitHub issues + Discord + Anthropic commercial support.
- **Maturity / adoption (2026-10-01)**: repo and npm package both created 2025-09-27; still `0.x` (0.3.286). **1,780 stars, 232 forks, ~13.2 M npm downloads/week**. 119 GitHub releases between 2026-05-20 and 2026-09-30 (about one per working day), each tracking one Claude Code patch version.
- **Where the agent loop runs**: in the spawned Claude Code subprocess, NOT in your Node/Bun/Deno process. The TS code is a transport (`child_process.spawn`), a typed-message parser, a hook-callback router over a JSON control protocol on stdio, and an in-process MCP host. You can swap the executable via `pathToClaudeCodeExecutable` or `spawnClaudeCodeProcess` (custom VM/container spawn).
- **Strongest fit for our case**: hooks are the most complete in the benchmark (**33 events** in `HOOK_EVENTS`, sdk.d.ts:957); tool-arg injection via `PreToolUse.updatedInput` / `canUseTool.updatedInput` is first-class; `maxBudgetUsd` is a USD cap enforced by the CLI (sdk.d.ts:1930); three reference `SessionStore` adapters (S3, Redis, Postgres) ship with a 13-contract conformance suite (`examples/session-stores/`). New since May: `canUseTool` and tool hooks now receive MCP-server **provenance** (`mcpServer: {name, source}`, `source === 'sdk'` for your in-process servers — CHANGELOG.md:111), and `prewarm()` / `SpareProcess.claim()` (alpha, CHANGELOG.md:49) start a process before the tenant's `cwd` is known.
- **Biggest gap for multi-tenant SaaS**: the subprocess model. One session = one ~240 MB binary process (vendor sizing guide: **1 GiB RAM, 5 GiB disk, 1 CPU per agent** as a floor). Open issue #372 reports a 4 vCPU / 8 GB host saturating at 40 concurrent sessions; #391 reports a libc probe that blocks the Node event loop 0.5–5 s per `query()` on Linux; #268 (`listSessions()` spawns a CLI, 900 MB+) and #122 (concurrent SDK MCP timeouts) are still open. No first-party HTTP server; skills still load only from the filesystem (vendor docs: "The SDK doesn't provide a programmatic API for registering them").
- **Most surprising finding (good)**: the vendor now publishes a concrete multi-tenant recipe in the hosting guide (`settingSources: []`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, per-tenant `CLAUDE_CONFIG_DIR`, per-tenant `cwd`, consistent-hash routing on `sessionId`) and four session patterns (ephemeral, long-running, hybrid with `SessionStore`, multi-agent container). Combined with `prewarm()`, `SessionStart` hooks that can `reloadSkills: true`, and `plugins: [{ type: 'local', skipMcpDiscovery }]`, per-tenant skill trees are now practical to materialise at session start.
- **Most surprising finding (bad)**: **0.3.286 changed the default permission mode.** An omitted `permissionMode` is now left to Claude Code, which starts in `auto` (model-classifier approval) on third-party providers or with telemetry off, or picks up a `defaultMode` from loaded settings (CHANGELOG.md:10, sdk.d.ts:1979-1992). A server that relied on the old "prompt through `canUseTool`" default must now pass `permissionMode: 'default'` explicitly. Also undocumented in the changelog: the `./assistant` export (`runAssistantWorker`) was removed in 0.3.181 (npm `exports` of 0.3.179 vs 0.3.181).
- **TS-vs-Py comparison**:
  - TS **wins**: ships Postgres/Redis/S3 reference adapters, a browser client (`/browser`, WebSocket or SSE), a smaller `/core` entry point for bundlers, `prewarm()`/`startup()` pre-warming, and JS-native `AbortController` cancel.
  - Py **wins**: `env` merges with the inherited environment (in TS it replaces it — hosting doc), `ClaudeSDKClient` as a long-lived handle.
  - **Equal**: both spawn the same Claude Code binary over the same JSON control protocol, with the same hook events, the same `~/.claude/projects/<cwd>/<sid>.jsonl` persistence default, the same filesystem-only skill loader, and the same subprocess cost.
- **One-liner verdicts**:
  - Sessions/persistence: JSONL on disk by default; `SessionStore` interface (still `@alpha`) with Postgres/Redis/S3 reference adapters. Resume by `sessionId` UUID; resumed sessions now continue `total_cost_usd` (CHANGELOG.md:91).
  - Skills: filesystem-only (user/project dirs, `additionalDirectories`, or `plugins` paths). `skills: string[] | 'all'` is a context filter, not a sandbox (sdk.d.ts:2255-2273). New: `Query.reloadSkills()` and `SessionStart` `reloadSkills: true`.
  - Resource Manager: not a first-class concept. Programmatic sources are local paths only (`SdkPluginConfig.type: 'local'`, sdk.d.ts:5552). The settings tier (`extraKnownMarketplaces`/`enabledPlugins`, passable inline through `Options.settings`/`managedSettings`) can fetch plugins from GitHub, git, npm, URL or a SHA-256-pinned zip archive, but there is no registry API, scoping or publish workflow.
  - Sub-agents: first-class. `agents: Record<string, AgentDefinition>` (sdk.d.ts:1574) defines them; the CLI's `Agent` tool dispatches them, now **background by default** from the model's side, with nesting capped at depth 1 and 20 concurrent sub-agents by default (CHANGELOG.md:437-438). A `Workflow` tool (`agent()/parallel()/pipeline()` scripts) is new.
  - Multi-tenancy: arg forcing ✅, visible-tool filter ✅, tenant-on-session ❌ (use `SessionKey.projectKey`, per-tenant `cwd`/`CLAUDE_CONFIG_DIR`, closures), per-run USD cap ✅ via `maxBudgetUsd`, no cumulative per-tenant cap.
  - Hooks: 33 events (new: `PreModelSwitch`, `PostModelSwitch`, `DirectoryAdded`, `MessageDisplay`). `PreToolUse.updatedInput` is still the canonical force-args pattern.
  - API: no HTTP server. Library-only; the hosting guide tells you to put auth at a gateway and expose your own HTTP/WebSocket port. A `browser` export is a client for a server you write.
  - Observability: `total_cost_usd` and per-model `modelUsage` (`costUSD`, `costBasis`, `canonicalModel`, `provider`) on every result; OTel export built into the CLI via env vars; trace context forwarded to the subprocess (CHANGELOG.md:928).
- **Production readiness for multi-tenant server-side deployment**: **viable with significant scaffolding** (unchanged). You ship ~240 MB of binary per platform, build your own HTTP server, materialise per-tenant `.claude/` trees or plugin dirs, wire `PreToolUse` for tenant-id injection, plug a `SessionStore`, set `permissionMode` explicitly, and size hosts at about one session per GiB. Easier than writing your own loop, much heavier than a library-shaped framework (LangGraph, Mastra). The ceiling is the same as the Py SDK: you cannot escape the Claude Code subprocess.

---

## 0. General

### 0.1 What is this stack?

A **library**: a TypeScript shim around the Claude Code CLI binary. The package layout (`package.json` of 0.3.286):

```json
"exports": {
  ".":          { "types": "./sdk.d.ts",          "default": "./sdk.mjs" },          // Node/Bun/Deno entry
  "./core":     { "types": "./core.d.ts",         "default": "./core.mjs" },         // smaller entry for bundlers (0.3.282)
  "./extract":  { "types": "./extractFromBunfs.d.ts", "default": "./extractFromBunfs.js" }, // bun --compile helper (0.3.144)
  "./browser":  { "types": "./browser-sdk.d.ts",  "default": "./browser-sdk.js" },   // browser client, WebSocket or SSE
  "./bridge":   { "types": "./bridge.d.ts",       "default": "./bridge.mjs" },       // claude.ai Remote Control bridge (alpha)
  "./sdk-tools": { "types": "./sdk-tools.d.ts" }                                      // built-in tool I/O types
},
"optionalDependencies": {
  "@anthropic-ai/claude-agent-sdk-darwin-arm64": "0.3.286",
  "@anthropic-ai/claude-agent-sdk-darwin-x64":   "0.3.286",
  "@anthropic-ai/claude-agent-sdk-linux-arm64":  "0.3.286",
  "@anthropic-ai/claude-agent-sdk-linux-arm64-musl": "0.3.286",
  "@anthropic-ai/claude-agent-sdk-linux-x64":    "0.3.286",
  "@anthropic-ai/claude-agent-sdk-linux-x64-musl": "0.3.286",
  "@anthropic-ai/claude-agent-sdk-win32-x64":    "0.3.286",
  "@anthropic-ai/claude-agent-sdk-win32-arm64":  "0.3.286"
},
"peerDependencies": { "@anthropic-ai/sdk": ">=0.93.0", "@modelcontextprotocol/sdk": "^1.29.0", "zod": "^4.0.0" }
```

The `./assistant` export (`runAssistantWorker`) that existed at 0.3.143 is gone: it is present in the npm `exports` of 0.3.179 and absent from 0.3.181. The changelog does not mention the removal.

Not a server, not a managed service. You import `query()` into your own process and embed it in your HTTP server. (Anthropic's hosted alternative is Managed Agents, linked from the hosting guide.)

### 0.2 Ecosystem

**TypeScript** (primary). Runtime: Node ≥ 18 (`package.json` `engines.node`), Bun (auto-detected), or Deno (`executable: 'deno'`).

The subprocess binary it spawns is itself a bundled JavaScript application compiled into a single static executable, but as an SDK consumer you only see the TS surface.

### 0.3 Project status & governance

- **Licence**: **proprietary.** `LICENSE.md`: "© Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service." npm `license` field: `SEE LICENSE IN README.md`. The README states that use "is governed by Anthropic's Commercial Terms of Service, including when you use it to power products and services that you make available to your own customers". The GitHub repo is public but contains no SDK source (only `CHANGELOG.md`, `README.md`, CI workflows and `examples/session-stores/`); the code ships as minified bundles on npm. Open issue #57 asks Anthropic to open-source it. (The previous revision of this report said MIT; `LICENSE.md` was not changed between the two commits, so that claim was an error.)
- **Owner / maintainer**: Anthropic PBC, the same team that builds Claude Code.
- **Commercial backing**: official Anthropic product; paid support through Anthropic commercial/enterprise plans. Anthropic also offers a hosted alternative (Managed Agents) for teams that do not want to run the loop.
- **Managed cloud**: optional claude.ai integration through `bridge.mjs` (alpha, "Remote Control"), and the `Agent` tool's `isolation: 'remote'` (sdk-tools.d.ts:799, "availability is gated").
- **Support model**: GitHub issues + Anthropic Discord (Claude Developers). Recent repo activity is mostly automated changelog commits; issue triage is partly automated by a Claude-driven workflow (`.github/workflows/issue-triage.yml`).

### 0.4 Project maturity / age

- **Original release**: the GitHub repo and the npm package were both created on **2025-09-27** (first commit `7675a55`, "first commit"; npm `time.created` 2025-09-27). The SDK is the renamed "Claude Code SDK"; the underlying CLI is older. (The previous revision said "first commits from 2024"; the repo history starts in September 2025.)
- **Current version**: `0.3.286` (npm, published 2026-09-30). Still pre-1.0. `SessionStore`, `prewarm()`/`SpareProcess`, `taskBudget`, `readMcpResource()` and `bridge.mjs` are marked `@alpha` in `sdk.d.ts`; `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET()` signals its own status.
- **Stability signal**: one SDK release per Claude Code patch release (`Updated to parity with Claude Code v2.1.N` in most entries). The hosting doc now states the policy: "The SDK follows semver: take patch releases continuously and review the … changelog before taking a minor." Behavioural changes still land in patch releases (e.g. 0.3.286 permission-mode default, 0.3.217 sub-agent depth cap, 0.3.162 Grep/Glob no longer default tools).
- **Bundled CLI version**: `2.1.286` (`manifest.json`, `claudeCodeVersion` in `package.json`), pinned to the SDK patch number.

### 0.5 Adoption & community signal

Captured on **2026-10-01** via `gh api` and the npm downloads API:

| Signal | Value |
|---|---|
| GitHub stars | 1,780 |
| Forks | 232 |
| Watchers | 16 |
| Contributors (GitHub API) | 7 |
| Issues | 212 open / 198 closed |
| Pull requests (all time) | 39 |
| npm downloads | ~13.2 M in the week 2026-09-23 → 2026-09-29 |
| Releases | 119 GitHub releases between 2026-05-20 and 2026-09-30; latest `v0.3.286` on 2026-09-30 |

- The low star/contributor count versus the very high download count reflects that the repo is a release-notes mirror, not where development happens. The npm number includes transitive installs (the SDK is a dependency of other Anthropic tooling).
- Issues cited in the 2026-05-19 revision: #122, #268, #293, #308, #313, #315, #316, #319 are **still open**; #318 (EPIPE startup race) was closed on 2026-07-16.
- Discord: Claude Developers channel on the Anthropic Discord.

### 0.6 Ecosystem fit

- **Package**: `@anthropic-ai/claude-agent-sdk` on npm (https://www.npmjs.com/package/@anthropic-ai/claude-agent-sdk).
- **Per-platform binaries**: `-darwin-arm64`, `-darwin-x64`, `-linux-arm64`, `-linux-arm64-musl`, `-linux-x64`, `-linux-x64-musl`, `-win32-x64`, `-win32-arm64` (all `0.3.286`).
- **Sibling SDK**: `claude-agent-sdk` (Python) — same architecture, same bundled CLI.
- **Official examples / templates**: in this repo only the three session-store adapters (`examples/session-stores/`). Deployable Dockerfiles / Kubernetes / Modal examples live in `anthropics/claude-cookbooks` (`claude_agent_sdk/hosting`), linked from the hosting doc.
- **Primary use shape**: imported as a **library** into a Node/Bun/Deno server. The bundled binary is also the `claude` CLI. The `/browser` export is a client that talks to a server you build.

### 0.7 Documentation depth & cross-team contributor accessibility

- Official docs: English-only, deep, and noticeably expanded since May: separate pages for hosting, secure deployment, session storage, observability, cost tracking, sub-agents, skills, plugins, troubleshooting.
- API reference (`/agent-sdk/typescript`) mirrors the `sdk.d.ts` docstrings, which are themselves very detailed (9,890 lines).
- Hosting guide now gives sizing numbers, four session patterns, a multi-tenant isolation recipe and a known-limitations table.
- Non-engineer authoring: a Product/Data author can write a `SKILL.md` (markdown + YAML frontmatter) or a markdown sub-agent file. Hooks, tools and SDK options need TypeScript.

### 0.8 Documentation entry points ⭐

- **Official landing page**: https://code.claude.com/docs/en/agent-sdk/overview
- **Quickstart**: https://code.claude.com/docs/en/agent-sdk/quickstart
- **TypeScript SDK reference**: https://code.claude.com/docs/en/agent-sdk/typescript
- **Hosting / deployment**: https://code.claude.com/docs/en/agent-sdk/hosting (plus https://code.claude.com/docs/en/agent-sdk/secure-deployment)
- **Session storage**: https://code.claude.com/docs/en/agent-sdk/session-storage
- **Observability / cost**: https://code.claude.com/docs/en/agent-sdk/observability, https://code.claude.com/docs/en/agent-sdk/cost-tracking
- **Migration from Claude Code SDK → Claude Agent SDK**: https://code.claude.com/docs/en/agent-sdk/migration-guide
- **Examples**: `examples/session-stores/` in the repo; hosting cookbook https://github.com/anthropics/claude-cookbooks/tree/main/claude_agent_sdk/hosting
- **GitHub**: https://github.com/anthropics/claude-agent-sdk-typescript
- **Changelog**: https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md
- **GitHub Releases**: https://github.com/anthropics/claude-agent-sdk-typescript/releases
- **GitHub issues**: https://github.com/anthropics/claude-agent-sdk-typescript/issues
  - **#372** — subprocess-per-session architecture causes CPU/memory exhaustion under concurrency (4C8G host saturates at 40 sessions per the reporter's benchmark)
  - **#391** — libc probe (`process.report.getReport()`) runs on every `query()` and blocks the event loop 0.5–5 s on Linux
  - **#268** — `listSessions()` spawns a full CLI process, 900 MB+ for a metadata query
  - **#122** — SDK MCP servers fail to connect from concurrent `query()` calls (60 s timeout)
  - **#231** — sandbox cannot be locked to the current working directory, blocking secure multi-user use
  - **#141** — cannot define slash commands/skills programmatically in SDK options
  - **#293** — per-subagent breakdown in `modelUsage` for cost attribution
  - **#319** — setting `metadata.user_id` from the Agent SDK
  - **#316** — sub-agents cannot access MCP resources declared in sub-agent definitions
  - **#426** — stream SessionStore transcripts without building a full entry array
  - **#57** — open-sourcing the SDK code
- **Discord**: https://anthropic.com/discord — Claude Developers channel
- **Managed Agents (hosted alternative)**: https://platform.claude.com/docs/en/managed-agents/overview

---

## 1. High Level Architecture

### Deployment diagram ⭐

```mermaid
flowchart TB
  subgraph Your Process (Node/Bun/Deno)
    APP[Your HTTP server<br/>Express / Fastify / Next.js]
    SDK["@anthropic-ai/claude-agent-sdk<br/>(sdk.mjs ~1.2 MB, or /core)"]
    HOOKS[Your hook callbacks<br/>PreToolUse / PostToolUse / SessionStart / …]
    MCP[In-process SDK MCP servers<br/>createSdkMcpServer + tool]
    STORE[Your SessionStore impl<br/>Postgres / Redis / S3]
    POOL[Optional warm pool<br/>startup() / prewarm() spares]
  end
  subgraph Subprocess (one per session)
    CLI["Claude Code native binary<br/>~225–242 MB<br/>@anthropic-ai/claude-agent-sdk-{platform}-{arch}/claude"]
    LOOP[Agent loop:<br/>system prompt build,<br/>tool dispatch, permissions,<br/>compaction, skill discovery,<br/>sub-agent fan-out, workflows]
    CFG[CLAUDE_CONFIG_DIR / ~/.claude/<br/>projects/&lt;cwd&gt;/&lt;sid&gt;.jsonl<br/>skills/, plugins/, agents/]
  end
  ANT[Anthropic API<br/>api.anthropic.com<br/>or Bedrock / Vertex / Foundry / gateway]
  EXT[External MCP servers<br/>stdio / SSE / HTTP]
  CLAUDE_AI[(claude.ai Remote Control bridge<br/>OPTIONAL, alpha)]

  APP --> SDK
  POOL --> CLI
  SDK -- "spawn(native binary)<br/>JSON over stdio:<br/>--input-format stream-json<br/>--output-format stream-json" --> CLI
  CLI --> LOOP
  LOOP --> CFG
  LOOP <-- "control_request:<br/>can_use_tool, hook_callback,<br/>mcp_message" --> SDK
  SDK --> HOOKS
  SDK --> MCP
  SDK --> STORE
  STORE -. "mirror append() ~100 ms batches" .-> CFG
  LOOP <-- "model API" --> ANT
  CLI <-- "stdio / SSE / HTTP" --> EXT
  SDK <-. "attachBridgeSession (alpha)" .-> CLAUDE_AI
```

### 1.1 Where does the agent loop *actually* execute?

**In the spawned Claude Code subprocess, not in your Node process.** The TS `query()` function is a transport + control-protocol shim. The model-call → tool-call → tool-result → next-model-call cycle, system-prompt assembly, permission evaluation (including the `auto` mode classifier), skill discovery, compaction, sub-agent dispatch and the new `Workflow` scripts all execute in the CLI binary. The vendor's hosting guide now says it plainly: "When your code calls `query()`, the SDK spawns a separate `claude` CLI process and talks to it over stdio … One agent session maps to one subprocess."

The minified runtime (as analysed at 0.3.143; the spawn path is unchanged in shape) confirms this:

```js
// sdk.mjs (extracted from the bundle, function names mangled)
spawnLocalProcess($) {
  let { command:Q, args:J, cwd:Y, env:X, signal:W } = $;
  let U = spawn(Q, J, { cwd:Y, stdio:["pipe","pipe", G],
                        signal:W, env:X, windowsHide:true });
  …
}
```

```js
let i = ["--output-format", "stream-json", "--verbose",
         "--input-format",  "stream-json"];
```

The resolution chain for which binary to spawn:

1. `options.pathToClaudeCodeExecutable` if set, OR
2. `require.resolve("@anthropic-ai/claude-agent-sdk-{platform}-{arch}/claude")` with glibc/musl detection on Linux (the detection calls `process.report.getReport()` on every `query()` — issue #391), OR
3. throw *"Native CLI not found … set options.pathToClaudeCodeExecutable."* Since 0.3.178 a spawn failure on an existing binary explains the likely libc mismatch (CHANGELOG.md:635).

For `bun build --compile` consumers, `@anthropic-ai/claude-agent-sdk/extract` copies the embedded binary out of the compiled executable's virtual filesystem (CHANGELOG.md:786).

**You cannot fork the loop without forking Claude Code.** Hooks, `canUseTool`, SDK MCP tools and settings are the only extension points.

### 1.2 Runtime dependencies

- **Node ≥ 18** (`package.json` `engines.node`), or **Bun**, or **Deno**. The spawned CLI needs no separate Node install.
- **One platform binary** (~225–242 MB) pulled as `optionalDependencies`. Mandatory in practice.
- **Anthropic API** (or Bedrock / Vertex / Foundry / `anthropicAws` / `anthropicGoogleCloud` / `mantle` / `gateway` — `AccountInfo.apiProvider`, sdk.d.ts:32) to drive the loop.
- Optionally **`bubblewrap`** on Linux when `sandbox: { enabled: true }` (sdk.d.ts:2192).
- Optionally a **Postgres / Redis / S3** instance if you adopt one of the example session-store adapters.
- Optionally an **OTLP collector** for the CLI's built-in OpenTelemetry export (hosting doc, Observability section).
- Optionally the **claude.ai** Remote Control endpoint (only for `bridge.mjs`).

A deployment that installs both `linux-x64` and `linux-arm64` packages carries ≈ 480 MB of binaries.

### 1.3 Recommended deployment topology

The hosting doc (https://code.claude.com/docs/en/agent-sdk/hosting) now documents **four session patterns**:

| Pattern | Shape | Vendor guidance |
|---|---|---|
| **Ephemeral** | One container per user task, destroyed at the end | One-shot entrypoint, `maxTurns` bound |
| **Long-running** | Persistent containers, often many SDK processes per container | Expose HTTP/WebSocket, map each session to a long-lived `query()`; use `streamInput()` for turns, `startup()` or `prewarm()` to pre-warm; "Size the container so it can hold the maximum number of concurrent sessions in memory" |
| **Hybrid** | Ephemeral containers that hydrate from a `SessionStore` on start | "the store is required for this pattern, not optional" |
| **Multi-agent container** | Several SDK subprocesses collaborating in one container | Separate `cwd` per agent, isolate settings loading |

For horizontal scaling of long-running sessions the doc recommends "a pool of containers behind a load balancer and pin each session to one container using consistent hashing on `sessionId`".

For a multi-tenant server-side deployment the practical topology stays **N session subprocesses per pod**, one per active session, with idle eviction and a shared `SessionStore`. The previous revision pointed to `runAssistantWorker` (`assistant.mjs`) as a blueprint for worker-per-session with idle despawn; that export was removed in 0.3.181, so idle eviction is entirely yours.

There is no first-party queue or distributed scheduler.

### 1.4 Cold-start cost & instance footprint

- **Binary footprint**: 225–242 MB per platform in `node_modules` (`manifest.json`, CLI 2.1.286):

```json
"platforms": {
  "darwin-arm64":     { "binary": "claude",     "size": 225167728 },
  "darwin-x64":       { "binary": "claude",     "size": 233607424 },
  "linux-arm64":      { "binary": "claude",     "size": 241033208 },
  "linux-x64":        { "binary": "claude",     "size": 241667256 },
  "linux-arm64-musl": { "binary": "claude",     "size": 233387840 },
  "linux-x64-musl":   { "binary": "claude",     "size": 235417688 },
  "win32-x64":        { "binary": "claude.exe", … }
}
```

  The binaries grew about 8–9 % since 0.3.143 (207–233 MB).

- **Cold start per subprocess**: no vendor number. Mitigations shipped since May:
  - `startup()` → `WarmQuery` (sdk.d.ts:9480, 9859): pre-warm a process whose options are known.
  - `prewarm()` → `SpareProcess.claim()` (alpha, sdk.d.ts:2823, 9306; CHANGELOG.md:49): start a process **before the session's folder and per-session options are known**, then bind it. This is the right primitive for a multi-tenant pool where the tenant `cwd` arrives with the request.
  - The CLI answers `initialize` before its background start-up work (CHANGELOG.md:61); in-process MCP handshakes run inside the SDK (CHANGELOG.md:60); MCP servers connect in the background by default since 0.3.142, with `CLAUDE_CODE_MCP_STARTUP_WAIT_MS` to bound the first-turn wait (CHANGELOG.md:112).
  - `CLAUDE_CODE_EMIT_STARTUP_TIMING=1` adds a per-phase `startup_timing` breakdown to `system/init` (CHANGELOG.md:113).
- **Per-session RAM baseline**: the hosting doc gives "1 GiB RAM, 5 GiB disk, and 1 CPU per agent" as a starting point and calls it "a floor, not the ceiling"; memory grows with session length. Issue #372 reports a 4 vCPU / 8 GB host at 99 % CPU and P95 latency of 103 s with 40 concurrent sessions. Issue #268 (`listSessions()` → 900 MB+) is still open. **Plan for ≥ 1 GiB per concurrent session.**
- **Host-process overhead**: `sdk.mjs` dropped from 1.47 MB to 0.97 MB in 0.3.281 (CHANGELOG.md:59) but measures 1.21 MB at 0.3.286; `/core` (123 KB + two shared chunks of 461 KB and 165 KB) is the slimmer import. Issue #391: on Linux the libc probe blocks the host event loop on every `query()`.

### 1.5 Vendor lock-in

| Dimension | Lock-in level | Reason |
|---|---|---|
| **LLM provider** | **High** | Anthropic models only. Bedrock, Vertex, Foundry, `anthropicAws`, `anthropicGoogleCloud`, `mantle` and `gateway` are hosting routes for Claude models (sdk.d.ts:32), not other model families. Non-Claude models require a translating gateway; the CLI's pricing, compaction and caching assume Claude. New `Settings.allowedProviders` lets an admin restrict providers (CHANGELOG.md:16). |
| **Hosting** | Low for self-host; High for claude.ai bridge / remote isolation | Self-host with your own API key. `bridge.mjs` and `isolation: 'remote'` tie you to claude.ai. |
| **Eval / observability** | Low | OTel export via standard `OTEL_*` env vars; no first-party eval product. |
| **Skill/sub-agent format** | Medium-High | `SKILL.md` follows the open Agent Skills format, but plugins, `AgentDefinition`, hooks and settings are Claude Code-shaped. |
| **Licence** | High | Proprietary bundle under Anthropic Commercial Terms; no source to fork. |

### 1.6 Framework weight / footprint

- TS shim (0.3.286, bytes): `sdk.mjs` 1,208,357; `core.mjs` 123,029 (+ `core-*.mjs` chunks 460,857 and 165,476); `bridge.mjs` 1,284,170; `browser-sdk.js` 1,401,610; `extractFromBunfs.js` 6,606. Unpacked npm package: 5.38 MB.
- Bundled native CLI: **225–242 MB per platform**.
- Type surface: `sdk.d.ts` **9,890 lines** (was 5,722 at 0.3.143), `sdk-tools.d.ts` 4,172 lines (was 2,848). Most of the growth is settings schema, control-protocol messages and hook payloads.

Neither a thin SDK (the bundled binary makes it the heaviest stack in the benchmark by bytes on disk) nor a heavy framework in the "bundles storage, eval, dev UI" sense.

### 1.7 Release-history signal

The repo carries `CHANGELOG.md` and one GitHub Release per version. Between 0.3.143 (2026-05-19) and 0.3.286 (2026-09-30) the changelog grew by 787 lines. The git history in that range is 128 commits, almost all "chore: Update CHANGELOG.md"; the only non-changelog changes are CI hardening (`.github/egress-firewall.yaml`, `.github/scripts/check_workflow_hardening.py`, `.github/workflows/workflow-hardening.yml`) and a new `CLAUDE.md` describing those protections. Decision-relevant entries:

**Breaking or behaviour-changing**
- **0.3.286** (CHANGELOG.md:10): an omitted `permissionMode` is left to Claude Code — a settings `defaultMode` applies, and on third-party providers or with telemetry off the session starts in `auto`. Pass `permissionMode: 'default'` for manual approvals.
- **0.3.269** (CHANGELOG.md:151): plan mode routes writes through `canUseTool` even with `allowDangerouslySkipPermissions`.
- **0.3.268 / 0.3.233** (CHANGELOG.md:165, 355): task-tracking tools (`TaskCreate/Get/Update/List`, `TodoWrite`) are no longer default tools on newer models; list them in `tools`/`allowedTools`.
- **0.3.217** (CHANGELOG.md:437-438): sub-agents no longer spawn nested sub-agents by default (depth cap 5 → 1); concurrent sub-agents capped at 20.
- **0.3.162** (CHANGELOG.md:710): native builds default to embedded `find`/`grep` in Bash instead of the dedicated `Grep`/`Glob` tools; name them in `tools` to keep them (and to intercept them in hooks).
- **0.3.234** (CHANGELOG.md:346): removed an unused `ExitReason` member (compile-time break only).
- **0.3.181**: `./assistant` export removed (not in changelog; verified from npm `exports`).
- **0.3.149** (CHANGELOG.md:765): `Options.env` documented as replacing, not merging with, `process.env`.

**Production-relevant additions**
- **0.3.282** (CHANGELOG.md:47-49): `/core` entry point; `prewarm()` / `SpareProcess.claim()` (alpha); `strictKnownMarketplaces`/`blockedMarketplaces` honoured in host-supplied `managedSettings`.
- **0.3.274** (CHANGELOG.md:111): MCP-server provenance (`source === 'sdk'`) on `canUseTool` options, tool hook inputs and MCP status rows.
- **0.3.259** (CHANGELOG.md:218): `permissionPrompts: 'none'` for sessions with nobody to answer.
- **0.3.246** (CHANGELOG.md:284-286): `modelUsage[*].costBasis`; `modelPricing` in `managedSettings`; `perTaskStopAffordance`.
- **0.3.223** (CHANGELOG.md:402-405): `resumeDropsTurn`; `system/permission_denied` events in bare headless runs; `usage` (main loop, per turn) vs `modelUsage` (cumulative, all calls, "the field for cost accounting") documented.
- **0.3.219** (CHANGELOG.md:422, 424): interrupt with `cancel_queued`; `DirectoryAdded` hook.
- **0.3.206 / 0.3.204** (CHANGELOG.md:502, 511, 513): `command_lifecycle` frames; new `terminal_reason` values so failed turns no longer look `completed`.
- **0.3.169** (CHANGELOG.md:679): browser SDK gains an SSE transport; 0.3.267 adds resume from a sequence number (CHANGELOG.md:170).
- **0.3.152** (CHANGELOG.md:751-752): `SessionStart` hooks can `reloadSkills: true`; `MessageDisplay` hook.
- **0.3.208** (CHANGELOG.md:487): security fix — a caller abort during a pending hook callback had been treated as hook success, letting `PreToolUse`-gated tools run after the abort.

**Older entries still relevant**: 0.2.113 native binaries + `SessionStore` (CHANGELOG.md:920-924); OTel trace-context forwarding (CHANGELOG.md:928); MCP reconnect after transport abort (CHANGELOG.md:897); 0.3.142 breaking changes — v2 session API removed, background MCP connect, Task tools replace `TodoWrite` (CHANGELOG.md:794-796).

Fast-moving areas: permission modes and the auto classifier, sub-agents/background tasks/workflows, MCP lifecycle, result-message metadata. Stable: `query()` signature, `Options` core fields, `tool()` factory, `SessionStore` shape (unchanged since May, still `@alpha`).

---

## 2. Agent Loop

### 2.1 Run loop entrypoint(s)

One primary entrypoint plus two pre-warm helpers:

```ts
// sdk.d.ts:3244
export declare function query(_params: {
  prompt: string | AsyncIterable<SDKUserMessage>;
  options?: Options;
}): Query;

// sdk.d.ts:9480 — pre-warmed subprocess, options known up front
export declare function startup(_params?: {
  options?: Options;
  initializeTimeoutMs?: number;
}): Promise<WarmQuery>;

// sdk.d.ts:2823 — @alpha, parked spare, session bound later
export declare function prewarm(_params?: {
  options?: Options;
  initializeTimeoutMs?: number;
}): Promise<SpareProcess>;
```

`SpareProcess.claim({ prompt, options: { cwd, model, … } })` (sdk.d.ts:9306) binds the spare to a session and returns a `Query`; `spare.claimed` rejects if the process cannot honour the claim, and you fall back to `query()`.

`Query` (sdk.d.ts:2844) is an `AsyncGenerator<SDKMessage, void>` with control methods: `interrupt()` (returns a typed receipt), `setPermissionMode()`, `setMcpPermissionModeOverride()`, `setModel()`, `setMaxThinkingTokens()`, `applyFlagSettings()`, `updateSettings()`, `initializationResult()`, `reinitialize()`, `supportedCommands()`, `supportedModels()`, `supportedAgents()`, `mcpServerStatus()`, `getContextUsage()`, `usage_EXPERIMENTAL_…()`, `readFile()`, `reloadPlugins()`, `reloadSkills()`, `reloadOutputStyles()`, `accountInfo()`, `rewindFiles()`, `seedReadState()`, `reconnectMcpServer()`, `toggleMcpServer()`, `readMcpResource()`, `setMcpServers()`, `streamInput()`, `stopTask()`, `backgroundTasks()`, `close()` — sdk.d.ts:2858–3241. New since 0.3.143: `readMcpResource`, `reinitialize`, `reloadOutputStyles`, `reloadSkills`, `setMcpPermissionModeOverride`, `updateSettings`, `usage_EXPERIMENTAL_…`.

### 2.2 Per-iteration behavior

One trip around the loop (executed entirely in the subprocess):

1. CLI assembles the system prompt (preset `claude_code` or custom from `Options.systemPrompt`), tool catalog, MCP tool catalog (deferred behind tool search unless `alwaysLoad`), skill listing, memory, dynamic sections (cwd, git status, auto-memory) unless `excludeDynamicSections: true`.
2. CLI fires `SessionStart` (first turn, or on resume/fork/clear/compact) and `UserPromptSubmit` / `UserPromptExpansion` for each user input. `verbatimPrompts: true` (sdk.d.ts:1891) disables `@path` expansion and slash-command dispatch.
3. CLI calls the model API and streams the assistant response. With `includePartialMessages: true` the SDK yields `SDKPartialAssistantMessage` (`type: 'stream_event'`).
4. For each `tool_use` block:
   - `PreToolUse` hook (can `updatedInput`, `permissionDecision`, `additionalContext`).
   - Permission evaluation: rules, permission mode (including the `auto` classifier), then `canUseTool` via `control_request: can_use_tool` if the call still needs a decision. With `permissionPrompts: 'none'` the prompt is auto-denied instead (sdk.d.ts:2018).
   - Dispatch: built-in tool, external MCP, or SDK MCP via `control_request: mcp_message`.
   - `PostToolUse` (or `PostToolUseFailure`) per tool, then `PostToolBatch` once for the batch (sdk.d.ts:2619).
5. Tool results are folded back as a `user` turn with `tool_result` blocks.
6. Loop until the assistant returns no `tool_use`, `maxTurns` / `maxBudgetUsd` is hit, a hook stops it, or it is interrupted. Long or slow tool calls (including MCP calls and sub-agents) can be moved to the background and the turn continues.
7. CLI emits `SDKResultMessage` with `total_cost_usd`, `usage`, `modelUsage`, `permission_denials`, `terminal_reason`, `result_index`, `queued_turn_count`.
8. `Stop` (or `StopFailure`) hook fires; a `Stop` hook can now return `additionalContext` to continue the turn with non-error feedback (CHANGELOG.md:705).

### 2.3 ReAct loop

**Built-in.** The CLI runs a ReAct-style loop. You insert hooks and choose tools; you do not author the loop.

### 2.4 Tool dispatch + result handling

Dispatch path depends on tool source:

- **Built-in CLI tools** (Bash, Read, Edit, Write, WebFetch, WebSearch, Agent, Workflow, Monitor, … — `ToolInputSchemas`, sdk-tools.d.ts:11) execute inside the subprocess.
- **External MCP tools** (`McpStdioServerConfig`, `McpSSEServerConfig`, `McpHttpServerConfig`) are connected by the CLI subprocess.
- **SDK MCP tools** (`createSdkMcpServer`, sdk.d.ts:613) run **in your Node process**. The CLI sends `control_request: mcp_message`; the SDK dispatches to the registered `McpServer` and returns the `CallToolResult` via `control_response`. Since 0.3.281 the in-process handshake runs inside the SDK. Per-server `timeout` (ms) overrides `MCP_TOOL_TIMEOUT` (CHANGELOG.md:274).

  ```ts
  // sdk.d.ts:9667
  export declare function tool<Schema extends AnyZodRawShape>(
    _name: string,
    _description: string,
    _inputSchema: Schema,
    _handler: (args: InferShape<Schema>, extra: unknown) => Promise<CallToolResult>,
    _extras?: { annotations?: ToolAnnotations; searchHint?: string; alwaysLoad?: boolean }
  ): SdkMcpToolDefinition<Schema>;
  ```

Results are folded as `tool_result` blocks on a synthetic `user` turn. Since 0.3.216 user messages also carry a `tool_result_meta` sidecar (`non_execution_kind`, `user_feedback`) so consumers can tell denied / interrupted / cancelled calls apart without parsing text (CHANGELOG.md:444).

### 2.5 Explicit turn concept

A **turn** = one assistant message (with any number of `tool_use` blocks) + the synthetic `user` message carrying the matching `tool_result` blocks. `SDKResultMessage` is emitted **once per request-loop terminator**; `num_turns` counts model round-trips for that request. Newer fields make turn bookkeeping explicit for multi-send sessions: `result_index` (position in delivery order), `queued_turn_count` (more results will follow), `user_message_uuid(s)` on the first reply and on the result linking a turn to the user message(s) it answered, and `command_lifecycle` frames reporting each uuid-stamped message as `queued/started/completed/cancelled/discarded` (CHANGELOG.md:156, 298, 217, 502).

### 2.6 Event emission mechanism (in-process)

Async iteration on `Query` (`extends AsyncGenerator<SDKMessage, void>`). Each yielded value is a member of the `SDKMessage` union (sdk.d.ts:5292).

```ts
const q = query({ prompt: 'Hello', options: { ... } });
for await (const msg of q) {
  switch (msg.type) {
    case 'assistant':    /* model turn */ break;
    case 'user':         /* tool result echo */ break;
    case 'result':       /* end of request loop */ break;
    case 'system':       /* subtype: 'init' | 'status' | 'task_*' | 'background_tasks_changed' | 'informational' | … */ break;
    case 'stream_event': /* partial assistant when includePartialMessages */ break;
    case 'conversation_reset': /* /clear or plan-mode exit */ break;
    // … 39 union members in total
  }
}
```

The Node process consumes the CLI's stdout JSONL stream, peels off control-protocol frames (`control_request`, `control_response`, `control_cancel_request`, `keep_alive`), routes them to internal handlers, and yields the rest as typed `SDKMessage`s.

Network-side streaming is your responsibility — see §8.

---

## 3. Message & Event Taxonomy

### 3.1 Message layers

Three layers:

1. **Wire layer (CLI ↔ SDK)** — line-delimited JSON on the subprocess stdout; `StdoutMessage` (sdk.d.ts:9488) = `SDKMessage` ∪ control requests/responses/cancellations ∪ keep-alives. Control frames never reach the caller.
2. **SDK message layer (TS public)** — the discriminated union `SDKMessage` (sdk.d.ts:5292), returned by `Query` iteration.
3. **Transcript on disk** (`~/.claude/projects/<cwd>/<sid>.jsonl`, or via `SessionStore.append()`) — one opaque `SessionStoreEntry` per line (sdk.d.ts:6575).

There is no separate "UI message" layer; the SDK message layer is what your application iterates and re-streams. Several fields are explicitly "wrapper-level siblings" for UIs and are not replayed to the model (`tool_use_meta`, `user_message_uuid`, `usage_report`).

```
Anthropic Messages API (BetaMessage / MessageParam)
        │ wrapped by CLI
        ▼
StdoutMessage JSONL (wire) ──peel control frames──▶ SDKMessage (TS) ──your code──▶ SSE/WS to UI
        │
        └──▶ JSONL transcript ──(dual write)──▶ SessionStore.append()
```

### 3.2 Concrete message types

`SDKMessage` union members (sdk.d.ts:5292; **39 members**, 30 at 0.3.143):

| Type | Discriminator | Purpose |
|---|---|---|
| `SDKAssistantMessage` | `type: 'assistant'` | A model turn (sdk.d.ts:3609). `message: BetaMessage`, `parent_tool_use_id`, `uuid`, `session_id`, `subagent_type`, `timestamp`, `aborted?: true` when truncated by `interrupt()`, `tool_use_meta` display names, `user_message_uuid`. |
| `SDKUserMessage` | `type: 'user'` | User turn or tool-result echo (sdk.d.ts:6179). `priority: 'now'|'next'|'later'`, `shouldQuery`, `isSynthetic`, `pasted_content`, `tool_use_result`, `tool_result_meta`. |
| `SDKUserMessageReplay` | `type: 'user'` | Replayed user message on resume. |
| `SDKSystemMessage` | `type: 'system', subtype: 'init'` | Handshake (sdk.d.ts:5864): `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands`, `skills`, `plugins` (with manifest `version`), `plugin_errors`, `effort`, `fast_mode_disabled_reason`, `claude_code_version`. |
| `SDKResultMessage` | `type: 'result'` | Terminal per-request message (sdk.d.ts:5689). `success` (sdk.d.ts:5691) or error subtypes `error_during_execution`, `error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries`. Carries cost, usage, `modelUsage`, `terminal_reason`, `api_error_status`, latency fields. |
| `SDKPartialAssistantMessage` | `type: 'stream_event'` | Raw `BetaRawMessageStreamEvent` when `includePartialMessages: true` (sdk.d.ts:5442). |
| `SDKCompactBoundaryMessage` | `system / compact_boundary` | Compaction marker with `pre_tokens`, `post_tokens`, preserved segment. |
| `SDKStatusMessage` | `system / status` | `'compacting' | 'requesting' | null`. |
| `SDKAPIRetryMessage` | `system / api_retry` | API retry notice; `error: 'overloaded'` for 529 since 0.3.150. |
| `SDKControlRequestProgressMessage` | `system / control_request_progress` | **new** — progress of an in-flight control request (started / api_retry). |
| `SDKModelRefusalFallbackMessage` / `…NoFallbackMessage` | `system / model_refusal_fallback` … | **new** — a refusal triggered a model fallback (scope session or local). |
| `SDKLocalCommandOutputMessage` | `system / local_command_output` | Slash-command output. |
| `SDKHookStartedMessage` / `…ProgressMessage` / `…ResponseMessage` | `system / hook_*` | Hook lifecycle when `includeHookEvents: true`. |
| `SDKPluginInstallMessage` | `system / plugin_install` | Headless plugin install progress. |
| `SDKToolProgressMessage` | `type: 'tool_progress'` | Elapsed-time heartbeat tied to `tool_use_id` (sdk.d.ts:6074); now also for `Agent` calls, with `subagent_type` / `subagent_retry`. |
| `SDKAuthStatusMessage` | `type: 'auth_status'` | OAuth progress. |
| `SDKTaskStartedMessage` / `…ProgressMessage` / `…UpdatedMessage` / `SDKTaskNotificationMessage` | `system / task_*` | Sub-agent / background task lifecycle; `task_started` carries `is_backgrounded`, `spawn_depth`; `task_notification` carries `reason`, `resource_links`. |
| `SDKBackgroundTasksChangedMessage` | `system / background_tasks_changed` | **new** — full set of live background tasks on every change (REPLACE semantics). |
| `SDKThinkingTokensMessage` | `system / thinking_tokens` | **new** — estimated thinking-token progress. |
| `SDKSessionStateChangedMessage` | `system / session_state_changed` | `'idle' | 'running' | 'requires_action'` (now also while an MCP elicitation waits). |
| `SDKWorkerShuttingDownMessage` | `system / worker_shutting_down` | **new** — Remote Control worker graceful exit. |
| `SDKCommandsChangedMessage` | `system / commands_changed` | **new** — live slash-command/skill list update. |
| `SDKNotificationMessage` | `system / notification` | Text notification with priority. |
| `SDKInformationalMessage` | `system / informational` | **new** — warnings and notices raised during a turn (previously dropped, CHANGELOG.md:41). |
| `SDKFilesPersistedEvent` | `system / files_persisted` | File checkpoint landed. |
| `SDKToolUseSummaryMessage` | `type: 'tool_use_summary'` | Summary across tool uses. |
| `SDKMemoryRecallMessage` | `system / memory_recall` | Memory files surfaced this turn (sdk.d.ts:5267). |
| `SDKRateLimitEvent` | `type: 'rate_limit_event'` | Rate-limit state; re-emitted during an exceeded window. |
| `SDKElicitationCompleteMessage` | `system / …` | MCP elicitation completed. |
| `SDKPermissionDeniedMessage` | `system / permission_denied` | Auto-deny (classifier / mode / rule / `permissionPrompts: 'none'`) (sdk.d.ts:5476). |
| `SDKPromptSuggestionMessage` | `type: 'prompt_suggestion'` | Predicted next user prompt. |
| `SDKMirrorErrorMessage` | `system / mirror_error` | `SessionStore.append()` failed permanently (sdk.d.ts:5358). |
| `SDKConversationResetMessage` | `type: 'conversation_reset'` | **new** — `/clear`, plan-mode exit with clear, etc.; `trigger`, `new_conversation_id`. |

### 3.3 Messages vs. events

**Same iterator.** Everything flows on the single `AsyncGenerator<SDKMessage>`; there is no separate event emitter. The wire format is a JSONL stream out of a subprocess; everything else is typed accessors over it.

### 3.4 Event categories

| Category | Concrete messages |
|---|---|
| **Stream event** | `SDKPartialAssistantMessage`, `SDKThinkingTokensMessage` |
| **Turn event** | `SDKResultMessage` (one per request terminator), `SDKStatusMessage`, `SDKAPIRetryMessage` |
| **Message event** | `SDKAssistantMessage`, `SDKUserMessage`, `SDKUserMessageReplay` |
| **Tool event** | `tool_use` / `tool_result` blocks, `SDKToolProgressMessage`, `SDKToolUseSummaryMessage` |
| **Session lifecycle** | `SDKSystemMessage(init)`, `SDKSessionStateChangedMessage`, `SDKCompactBoundaryMessage`, `SDKConversationResetMessage`, `SDKAuthStatusMessage`, `SDKWorkerShuttingDownMessage`, `SDKCommandsChangedMessage` |
| **Hook event** | `SDKHookStartedMessage`, `SDKHookProgressMessage`, `SDKHookResponseMessage` (opt-in via `includeHookEvents`) |
| **Sub-agent / background event** | `SDKTaskStartedMessage`, `SDKTaskProgressMessage`, `SDKTaskUpdatedMessage`, `SDKTaskNotificationMessage`, `SDKBackgroundTasksChangedMessage` |
| **Notification** | `SDKNotificationMessage`, `SDKInformationalMessage`, `SDKPromptSuggestionMessage`, `SDKMemoryRecallMessage` |
| **Error / state** | `SDKMirrorErrorMessage`, `SDKPermissionDeniedMessage`, `SDKRateLimitEvent`, `SDKModelRefusalFallbackMessage`, `SDKControlRequestProgressMessage` |

### 3.5 Canonical type-definition file(s)

- **`sdk.d.ts`** (9,890 lines) — the public TS API; `SDKMessage` and every related type.
- **`core.d.ts`** — re-exports the runtime subset for the `/core` entry (`query`, `tool`, `createSdkMcpServer`, session mutations, `resolveSettings`, …) plus `export type * from './sdk.js'`.
- **`sdk-tools.d.ts`** (4,172 lines) — auto-generated from the CLI's tool JSON Schema; every built-in tool input/output shape.
- **`bridge.d.ts`**, **`browser-sdk.d.ts`** — claude.ai bridge and browser client. (`assistant.d.ts` no longer ships.)

### 3.6 Live agentic event stream taxonomy

Sample frames (illustrative; structure from the type definitions):

```jsonl
{"type":"system","subtype":"init","session_id":"abc-...","model":"claude-opus-4-7","tools":["Bash","Read","Edit","Write","WebFetch","WebSearch","Agent","Skill","AskUserQuestion","ExitPlanMode","mcp__predict__topicSearch"],"mcp_servers":[{"name":"predict","status":"connected"}],"skills":["generate-audience-from-brief"],"plugins":[],"permissionMode":"default","apiKeySource":"ANTHROPIC_API_KEY","claude_code_version":"2.1.286","slash_commands":["/compact","/context"],"output_style":"default","uuid":"..."}
{"type":"assistant","session_id":"abc-...","timestamp":"2026-10-01T09:00:01.120Z","user_message_uuid":"u-1","message":{"id":"msg_01...","role":"assistant","model":"claude-opus-4-7","content":[{"type":"text","text":"I'll search topics."},{"type":"tool_use","id":"toolu_01...","name":"mcp__predict__topicSearch","input":{"query":"young moms"}}],"stop_reason":"tool_use","usage":{"input_tokens":1234,"output_tokens":42,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}},"parent_tool_use_id":null,"uuid":"..."}
{"type":"tool_progress","tool_use_id":"toolu_01...","tool_name":"mcp__predict__topicSearch","parent_tool_use_id":null,"elapsed_time_seconds":3.2,"uuid":"...","session_id":"abc-..."}
{"type":"user","session_id":"abc-...","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01...","content":"[{...10 topics...}]"}]},"parent_tool_use_id":null,"uuid":"..."}
{"type":"result","subtype":"success","session_id":"abc-...","duration_ms":4200,"duration_api_ms":3800,"num_turns":2,"result":"Found 10 topics.","stop_reason":"end_turn","total_cost_usd":0.0123,"usage":{"input_tokens":1500,"output_tokens":120,"cache_creation_input_tokens":0,"cache_read_input_tokens":0},"modelUsage":{"claude-opus-4-7":{"inputTokens":1500,"outputTokens":120,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"webSearchRequests":0,"costUSD":0.0123,"contextWindow":200000,"maxOutputTokens":32000,"canonicalModel":"claude-opus-4-7","provider":"firstParty","costBasis":"list"}},"permission_denials":[],"is_error":false,"terminal_reason":"completed","result_index":0,"user_message_uuid":"u-1","uuid":"..."}
```

---

## 4. Agent Runtime (Multi-session Host)

### 4.1 Multi-session host architecture

**Not provided as a turnkey runtime.** `query()` is one session per call; you embed it in your own server. The previous revision named `runAssistantWorker` (`assistant.mjs`) as the closest thing to a runtime; it was removed in 0.3.181. What the SDK does provide for a host now:

- `startup()` / `prewarm()` to keep a pool of warm subprocesses (§1.4).
- `streamInput()` (sdk.d.ts:3212) to push turns into a long-lived session.
- `reinitialize()` (sdk.d.ts:2999) to re-send `initialize` and redeliver pending permission prompts after a transport gap (CHANGELOG.md:560); `initialize` is idempotent (CHANGELOG.md:714).
- Background-task visibility (`background_tasks_changed`, `backgroundTasks()`), so a host can tell when a session is idle but still has work running.

A multi-session host in TS looks like:

```ts
// Your own code — not shipped by the SDK
const sessions = new Map<string, Query>();

app.post('/sessions/:sid/turns', async (req, res) => {
  const sid = req.params.sid;
  let q = sessions.get(sid);
  if (!q) {
    q = query({ prompt: messageStreamFor(sid), options: { resume: sid, sessionStore: pgStore, permissionMode: 'default' } });
    sessions.set(sid, q);
  }
  // ... push the turn into messageStreamFor(sid), stream q to res
});
```

### 4.2 Concurrent session isolation

**One subprocess per session is the only safe model**, and the hosting doc now says so. A CLI subprocess has one cwd, one settings tree, one MCP server set, one transcript target; state bleeds if you reuse one across tenants.

The SDK does not enforce isolation. The vendor's multi-tenant recipe (hosting doc, "Multi-tenant isolation"):

- `settingSources: []` to skip user, project and local settings;
- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in `env` (auto memory loads "regardless of `settingSources`");
- a per-tenant `CLAUDE_CONFIG_DIR` so tenants do not share `~/.claude.json`;
- a per-tenant `cwd` on every `query()`;
- per-tenant egress rules at your proxy.

Because `env` **replaces** the subprocess environment in TS (sdk.d.ts:1643-1658), spread `...process.env` yourself. Two fixes since May matter for isolation: long (>200 char) project paths had resolved to another project's session directory (CHANGELOG.md:398), and `sessionStore` resume had lost user settings (CHANGELOG.md:409). Issue #231 (sandbox cannot be locked to `cwd`) remains open.

Issue **#122** (SDK MCP servers failing to connect from concurrent `query()` calls) is still open; use unique SDK MCP server names per session.

### 4.3 Horizontal scaling / multi-instance

**No leader election, no shared state, no session coordinator.** N pods can serve the same session pool only through an external `SessionStore` (sdk.d.ts:6482). The hosting doc's two answers:

- **Long-running**: pin each session to one container with consistent hashing on `sessionId`.
- **Hybrid**: any container can resume any session from the shared store (`query({ options: { resume, sessionStore } })`). The doc notes that "a run resumed from the store deletes its local copy at the end, so the store holds the only durable copy."

`forkSession` (sdk.d.ts:836) and the other session helpers accept `sessionStore`.

### 4.4 Background / async / scheduled tasks

- **Background sub-agents**: `AgentDefinition.background: true` (sdk.d.ts:79) and `AgentInput.run_in_background` (sdk-tools.d.ts:783). The model-facing description now says "Agents run in the background by default". Completion arrives as `task_notification`; `background_tasks_changed` gives the live set.
- **Background Bash**: `BashInput.run_in_background` (sdk-tools.d.ts:829); `timeout` now bounds background commands (default 30 min, max 2 h — CHANGELOG.md:21). Long MCP calls and agents can be auto-backgrounded.
- **`interrupt()` scope**: with `perTaskStopAffordance` (sdk.d.ts:1805) `interrupt()` aborts only the current turn and leaves background agents/workflows running.
- **In-session scheduling (new tools)**: `CronCreate` / `CronDelete` / `CronList` (sdk-tools.d.ts:2880; 5-field cron, `durable: true` persists to `.claude/scheduled_tasks.json`, recurring jobs auto-expire after 7 days) and `ScheduleWakeup` (60–3600 s self-wake for `/loop`). These are model-invoked and local to the session/process, **not a distributed scheduler**. A host can mark a run as a scheduled fire only in a process started with `CLAUDE_CODE_HOST_SCHEDULED_RUN=1` (CHANGELOG.md:67).
- **Remote triggers**: a `RemoteTrigger` tool (sdk-tools.d.ts:2927, actions include `create_webhook_trigger`, `run`, `list_runs`) manages triggers on Anthropic's side; it is tied to a claude.ai account, not your infrastructure.
- **Webhook intake on your infra**: BYO.

### 4.5 Worker pool / queue model

**Not provided — BYO.** `streamInput()`, `stopTask()`, `interrupt({ cancel_queued })` and `queued_turn_count` / `command_lifecycle` frames give you the primitives to run a long-lived session with queued user sends, but there is no shipped job queue, lease, or `enqueue()` API. For long-running fan-out work use BullMQ / Cloud Tasks / Temporal around `query()`.

---

## 5. Sessions & Persistence

### 5.1 Session / chat data model

Session metadata is `SDKSessionInfo` (sdk.d.ts:5770):

```ts
export declare type SDKSessionInfo = {
  sessionId: string;       // UUID
  summary: string;         // display title (custom > AI > first prompt)
  lastModified: number;    // epoch ms
  fileSize?: number;       // local JSONL only
  customTitle?: string;    // renameSession() / /rename
  firstPrompt?: string;
  gitBranch?: string;
  cwd?: string;
  tag?: string;            // tagSession()
  createdAt?: number;
};
```

`SessionKey` for the store layer (sdk.d.ts:6383):

```ts
export declare type SessionKey = {
  /** Caller-defined scope. Default: sanitized cwd. Multi-tenant deployments
   *  should set this to a tenant ID or project name. Paths longer than 200
   *  characters are truncated and suffixed with a portable djb2 hash … */
  projectKey: string;
  sessionId: string;
  subpath?: string;    // omitted = main transcript; set = sub-agent transcript
};
```

**`projectKey` is still the closest thing to a `tenantId`** on the session model.

Per message: `SDKAssistantMessage` / `SDKUserMessage` carry `session_id`, `uuid`, `parent_tool_use_id`, `subagent_type`, `timestamp`, plus the Anthropic API body. Sub-agent session messages now carry `parent_agent_id` for depth-2+ trees (CHANGELOG.md:523).

### 5.2 What's stored on a session

The JSONL transcript covers user and assistant messages (with `tool_use` / `tool_result`), system events (init, compact boundary, memory recall, task events, files persisted, permission denied, mirror error), title/tag rows, compaction anchors, and sub-agent transcripts under `subpath: 'subagents/agent-<id>'`.

`SessionStoreEntry` is intentionally opaque (sdk.d.ts:6575):

```ts
export declare type SessionStoreEntry = {
  type: string;
  uuid?: string;
  timestamp?: string;
  [k: string]: unknown;
};
```

File checkpoints (`enableFileCheckpointing: true`) are stored separately on disk; `rewindFiles()` restores them and now fails when nothing could be restored (CHANGELOG.md:210). `SessionStore` mirrors transcripts only — not `CLAUDE.md` memory files or working-directory artifacts (hosting doc).

### 5.3 Granularity

- Single conversation per session.
- **Forks** via `forkSession(sessionId, { upToMessageId?, title?, sessionStore? })` (sdk.d.ts:836); several fork-correctness fixes landed since May (CHANGELOG.md:29, 40, 103-104). `SessionStart` hooks report source `"fork"` (CHANGELOG.md:459).
- **Rewind**: a `rewind_conversation` control request rewinds to a previous point with a durable resume anchor (CHANGELOG.md:599); `resumeSessionAt` + `resumeDropsTurn` (sdk.d.ts:2099, 2150) truncate on resume and refuse if more than the declared turn would be dropped.
- No LangGraph-style multi-branch session; a fork is a new `sessionId`.

### 5.4 Built-in persistence stores

| Backend | Status |
|---|---|
| **JSONL on local disk** | Default. `~/.claude/projects/<cwd-sanitized>/<sessionId>.jsonl` (or under `CLAUDE_CONFIG_DIR`). Disabled with `persistSession: false`. `CLAUDE_CODE_PROJECT_DIR_NAME` can name the project directory (TS SDK ≥ 0.3.234, per hosting doc). |
| **`InMemorySessionStore`** | Shipped class (sdk.d.ts:1035). Tests/dev. |
| **Postgres** | Reference adapter `examples/session-stores/postgres/` (unchanged since May). One row per entry, `jsonb`, `BIGSERIAL` ordering. Conformance-tested. |
| **Redis** | Reference adapter `examples/session-stores/redis/`. `RPUSH` + sorted-set index. |
| **S3** | Reference adapter `examples/session-stores/s3/`. Part files `s3://{bucket}/{prefix}{projectKey}/{sessionId}/part-{epochMs}-{rand}.jsonl`. |
| **SQLite, MongoDB, DynamoDB, GCS, R2, …** | Not provided — BYO. The interface is six methods (two required). |
| **Anthropic-hosted** | Only through the claude.ai bridge (alpha) — for Remote Control, not primary server-side persistence. |

### 5.5 Persistence timing

From `SessionStore.append()` (sdk.d.ts:6482-6504):

> *Mirror a batch of transcript entries. Called AFTER the subprocess's local write succeeds — durability is already guaranteed locally. Batches arrive at ~100ms cadence during active turns.*

New in the docstring: adapters "SHOULD treat `uuid` as an idempotency key (upsert / ignore-duplicate)" so retries and `importSessionToStore()` replays do not duplicate rows; within a process persist in call order.

`Options.sessionStoreFlush` (sdk.d.ts:1835; `SessionStoreFlush`, sdk.d.ts:6594): `'batched'` (default) or `'eager'`.

Failure mode: rejection retried (3 attempts) with short backoff; 60 s timeouts are not retried; then the batch is dropped and `SDKMirrorErrorMessage` emitted. The hosting doc: "Alert on these if store durability matters."

**Local-disk write is synchronous to the loop**; the external store is a post-local, batched mirror. `persistSession: false` cannot be combined with `sessionStore` (sdk.d.ts:1815-1827).

### 5.6 Mid-run checkpointing (durable)

**The subprocess's local JSONL write is the durability boundary.** A crash mid-tool-call resumes from the last flushed line; the partial tool call is lost. There is no per-task `commit()` like LangGraph.

Since May the CLI handles interrupted turns more explicitly: an automatic re-run of a turn that a host restart interrupted is marked with `resume_reason` on assistant/stream/result messages (CHANGELOG.md:159), deferred tool calls re-run at the start of a resumed turn (CHANGELOG.md:101), and background agent / MCP task state is restored on SDK resume (CHANGELOG.md:648). This is still **turn-level recovery**, not a durable per-step checkpoint primitive.

For an external store: post-local + batched + eventually consistent (~100 ms window). Recovery: `importSessionToStore()` (sdk.d.ts:998) from the local file.

### 5.7 Session ID format

**UUID v4.** Override with `Options.sessionId` (sdk.d.ts:2091; must be a valid UUID; dash-leading values are now passed in equals form — CHANGELOG.md:467). `forkSession` mints a fresh UUID. `projectKey` is a caller-defined string (default: sanitized cwd; >200 chars truncated + djb2 hash).

### 5.8 Pluggable store interface

`SessionStore` (sdk.d.ts:6482), unchanged in shape since May and still `@alpha`:

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

Conformance suite: `examples/session-stores/shared/conformance.ts` (13 contracts). `load()` returns the whole entry array; issue #426 asks for streaming.

### 5.9 Schema evolution / migration

- `importSessionToStore(sessionId, store, options?)` (sdk.d.ts:998) — migrate a local session into a store.
- `foldSessionSummary(prev, key, entries, options?)` (sdk.d.ts:818) — pure fold that adapters call inside `append()` to maintain the `listSessionSummaries()` sidecar.
- No migration helpers for entry-schema bumps; entries are opaque. The SDK keeps legacy union members in types for backward compatibility (e.g. `ApiKeySource`, sdk.d.ts:131).

### 5.10 Export / replay

- `getSessionMessages(sessionId, options?)` (sdk.d.ts:900) — chronological user/assistant messages. Many correctness fixes since May: messages sent while Claude was working, messages from other agents/channels, rewound branches (CHANGELOG.md:18, 30, 40, 102, 105, 114).
- `getSubagentMessages(sessionId, agentId, options?)` (sdk.d.ts:937) — now also returns messages a sub-agent read while running (CHANGELOG.md:22).
- `getSessionInfo()` (sdk.d.ts:870), `listSessions()` (sdk.d.ts:1095; issue #268 still open), `listSubagents()` (sdk.d.ts:1150), `renameSession()`, `tagSession()`, `deleteSession()`.
- Replay via `query({ options: { resume: sessionId, sessionStore, resumeSessionAt } })`. Not deterministic (the model is re-called).

### 5.11 Cross-session memory

See **§17**. The CLI surfaces memory files (`~/.claude/agent-memory/<agentType>/`, `.claude/agent-memory/…`, `.claude/agent-memory-local/…`, per `AgentDefinition.memory`, sdk.d.ts:87) and auto memory under `~/.claude/projects/<project>/memory/` (hosting doc). Not tenant-scoped by default; the hosting doc tells multi-tenant hosts to disable auto memory.

---

## 6. Multi-tenancy & Tenant Identity ⭐ THE KEY QUESTION

### 6.1 Run-loop tenant identity

`Options` (sdk.d.ts:1519–2443) has ~90 fields. **There is no first-class `tenantId`, `userId` or `metadata` field** (issue #319 asks for `metadata.user_id`). The decision-relevant subset:

```ts
export declare type Options = {
  // === Identity / session ===
  sessionId?: string;          // UUID — caller-chosen, otherwise generated
  resume?: string;
  resumeSessionAt?: string;
  resumeDropsTurn?: string;    // new: refuse a truncating resume that drops more than this turn
  continue?: boolean;
  forkSession?: boolean;
  title?: string;
  cwd?: string;                // per-tenant working dir; default projectKey root
  projectConfigRoot?: string;  // new: load .claude trees / project settings from a trusted checkout instead of cwd

  // === Tenant-shaped carriers (no first-class tenantId) ===
  env?: { [k: string]: string | undefined };  // REPLACES the subprocess env (spread process.env yourself)
  additionalDirectories?: string[];
  settings?: string | Settings;               // inline settings object or path (flag layer)
  managedSettings?: Settings;                 // policy-tier settings from the embedder (restrictive-only)
  settingSources?: SettingSource[];           // [] for tenant isolation (hosting doc)
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
  agent?: string;
  agents?: Record<string, AgentDefinition>;
  skills?: string[] | 'all';
  plugins?: SdkPluginConfig[];                  // 'local' only; skipMcpDiscovery per plugin
  pluginDelivery?: 'argv' | 'initialize';       // new
  systemPrompt?: string | string[] | { type: 'custom'; prompt; snapshot? } | { type: 'preset'; preset: 'claude_code'; append?; excludeDynamicSections?; snapshot? };
  planModeInstructions?: string;
  outputFormat?: OutputFormat;
  verbatimPrompts?: boolean;                    // new

  // === Behavior / permissions ===
  permissionMode?: PermissionMode;              // omitted → CLI default (often 'auto') since 0.3.286
  allowDangerouslySkipPermissions?: boolean;
  permissionPromptToolName?: string;
  permissionPrompts?: 'host' | 'none';          // new
  canUseTool?: CanUseTool;
  hooks?: Partial<Record<HookEvent, HookCallbackMatcher[]>>;
  onElicitation?: OnElicitation;
  onUserDialog?: OnUserDialog;                  // new
  sandbox?: SandboxSettings;
  effort?: EffortLevel;
  thinking?: ThinkingConfig;
  maxTurns?: number;
  maxBudgetUsd?: number;
  taskBudget?: { total: number };
  fallbackModel?: string;
  model?: string;
  betas?: SdkBeta[];
  perTaskStopAffordance?: boolean;              // new

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

Tenants are modelled by combining:

- `cwd` (per-tenant working directory) and, for isolation, a per-tenant `CLAUDE_CONFIG_DIR` in `env`;
- `SessionKey.projectKey` on the store side (sdk.d.ts:6383, "Multi-tenant deployments should set this to a tenant ID");
- `env` values (e.g. `TENANT_ID`) visible to the subprocess and its Bash tool;
- closures inside `canUseTool`, hooks and SDK MCP tool handlers (which run in your process);
- `managedSettings` for per-tenant policy (permissions, `modelPricing`, `strictKnownMarketplaces`, `allowedProviders`).

**Tenant-on-session is still not first-class.** `SDKSessionInfo` has no tenant field; you rely on `projectKey`, a per-tenant store instance, or your own session table.

### 6.2 Tenant identity propagation into tool calls

The SDK does not inject a tenant context into tools. For **SDK MCP tools** the handler is `(args, extra) => Promise<CallToolResult>` where `extra` is the MCP request context, not a harness `RunContext`.

Working propagation patterns:

1. **Closure capture** — define tools per tenant/session:

   ```ts
   function makeTopicSearch(tenantId: string) {
     return tool('topicSearch', 'Search topics for a tenant', { query: z.string() },
       async (args) => topicSearchService(tenantId, args.query));
   }
   ```

2. **`PreToolUse` hook closure** — mutate `tool_input.tenantId` before dispatch (§6.4).
3. **`canUseTool` closure** — return `{ behavior: 'allow', updatedInput: { ...input, tenantId } }`. Since 0.3.274 the callback also receives `mcpServer: { name, source }`, so you can apply the rewrite only when `source === 'sdk'` (your own in-process server) and not to a same-named server from configuration (sdk.d.ts:213-245; CHANGELOG.md:111).
4. **Env vars** — `Options.env = { ...process.env, TENANT_ID: 'acme' }`. Built-in `Bash` sees them; SDK MCP tools run in your Node process and should use their own request context (e.g. `AsyncLocalStorage`) rather than `process.env`.

Call path for an SDK MCP tool: model `tool_use` → CLI `PreToolUse` hook (your callback over stdio) → permission evaluation / `canUseTool` (your callback) → CLI `control_request: mcp_message` → SDK → your `tool()` handler with the possibly rewritten args → `control_response` → `tool_result`.

### 6.3 Tool call interface

```ts
// sdk.d.ts:9667
export declare function tool<Schema extends AnyZodRawShape>(
  _name: string,
  _description: string,
  _inputSchema: Schema,                                  // Zod v3 or v4 raw shape (AnyZodRawShape, sdk.d.ts:126)
  _handler: (args: InferShape<Schema>, extra: unknown) => Promise<CallToolResult>,
  _extras?: { annotations?: ToolAnnotations; searchHint?: string; alwaysLoad?: boolean }
): SdkMcpToolDefinition<Schema>;
```

`CallToolResult` is the MCP standard result (`{ content: [{ type: 'text', text } | { type: 'image', … } | { type: 'resource_link', … }], _meta? }`). `resource_link` blocks are now surfaced to hosts as `tool_use_result.resourceLinks` (CHANGELOG.md:228). `zod ^4` is a peer dependency; v3 shapes are still accepted via `zod/v3`.

### 6.4 Forcing tool arguments from the harness

**Yes — two first-class mechanisms.**

#### Mechanism A: `canUseTool` permission callback

```ts
// sdk.d.ts:213 (abridged)
export declare type CanUseTool = (
  toolName: string,
  input: Record<string, unknown>,
  options: {
    signal: AbortSignal;
    suggestions?: PermissionUpdate[];
    mcpServer?: { name: string; source: string };   // 'sdk' = your in-process server
    toolUseID: string;
    agentID?: string;
    requestId: string;                               // echo for out-of-band responses
    defaultToNo?: boolean; suppressAlwaysAllowRule?: boolean; …
  }
) => Promise<PermissionResult | null>;

// sdk.d.ts:2505
export declare type PermissionResult =
  | { behavior: 'allow'; updatedInput?: Record<string, unknown>; updatedPermissions?: PermissionUpdate[]; … }
  | { behavior: 'deny'; message: string; interrupt?: boolean; … };
```

Return `{ behavior: 'allow', updatedInput: { ...input, tenantId: 'acme' } }` and the CLI dispatches with `updatedInput`. Since 0.3.207 returning `allow` without `updatedInput` runs the original input as documented (it was previously rejected with a raw ZodError — CHANGELOG.md:497). Returning `null` tells the SDK you already answered out of band (e.g. an HTTP POST echoing `requestId`, CHANGELOG.md:538).

**Caveat:** `canUseTool` is only called for calls that still need a decision. A rule in `allowedTools`, `bypassPermissions`, or the `auto` classifier approving the call can shadow it; the SDK now warns when `canUseTool` is combined with `allowedTools` or `bypassPermissions` (CHANGELOG.md:544). With the 0.3.286 default (`auto` mode where available), an omitted `permissionMode` can mean your `canUseTool` arg rewrite never runs. **Use `PreToolUse` for forced args.**

#### Mechanism B: `PreToolUse` hook (recommended)

```ts
// sdk.d.ts:2746
export declare type PreToolUseHookSpecificOutput = {
  hookEventName: 'PreToolUse';
  permissionDecision?: HookPermissionDecision;
  permissionDecisionReason?: string;
  updatedInput?: Record<string, unknown>;       // <-- force args here
  additionalContext?: string;
};
```

Registered under `Options.hooks.PreToolUse`, matched by tool name. It fires before permission evaluation regardless of permission mode. Hook input now includes `mcp_server` provenance (sdk.d.ts:2738-2744) and `prompt_id` for OTel correlation (sdk.d.ts:178). A hook callback that is aborted no longer counts as success (CHANGELOG.md:487), and a managed `disableAllHooks` no longer disables SDK-registered callbacks (CHANGELOG.md:300) — both matter for relying on `PreToolUse` as a security control.

Both callbacks run in your Node process; the CLI only sees the resulting `updatedInput`.

### 6.5 Tenant-aware visible tool selection

Layered mechanisms, set per `query()` (i.e. per tenant session):

1. **`Options.tools`** (sdk.d.ts:1638) — base set of built-in tools: an explicit list, `[]` for none, or the `claude_code` preset. Note that on native builds `Grep`/`Glob` and on newer models the task tools are no longer in the default set (CHANGELOG.md:710, 355).
2. **`Options.allowedTools`** (sdk.d.ts:1582) — auto-approved without prompting.
3. **`Options.disallowedTools`** (sdk.d.ts:1602) — removes tools from context; server-level specs `mcp__server` / `mcp__server__*` now work (CHANGELOG.md:639).
4. **`Options.toolAliases`** (sdk.d.ts:1628) — name redirect.
5. **`AgentDefinition.tools` / `disallowedTools`** (sdk.d.ts:46, 50) — per sub-agent.
6. **`Options.skills`** (sdk.d.ts:2273) — skill listing filter (context filter, not a sandbox).
7. **`Options.mcpServers`** — which MCP servers (and so which tools) exist at all.
8. **Mid-session**: `Query.setMcpServers()` (sdk.d.ts:3205), `toggleMcpServer()` (sdk.d.ts:3163), `applyFlagSettings({ permissions })`, `applyFlagSettings({ agent })` (live agent switch, CHANGELOG.md:715).

Per-turn changes require those control methods; there is no `prepareStep`-style per-call hook that rewrites the tool list.

### 6.6 Per-tool-call auth propagation

**Not provided — BYO.** Caller identity does not flow into tool calls. SDK MCP tools run in your Node process, so read identity from your own request context. Built-in tools (Bash, WebFetch) run as the subprocess's OS user with its environment. The hosting doc's guidance is to keep tool credentials out of the agent environment and inject them at an egress proxy; sandbox settings now include credential masking and injection (`sandbox.credentials` with `mode: "mask"`, `injectHosts`, JWT claim masking, AWS SigV4 re-signing — CHANGELOG.md:397, 540).

### 6.7 Per-tenant rate limit + budget cap

- **`Options.maxBudgetUsd`** (sdk.d.ts:1930): USD ceiling per `query()`, enforced by the CLI; overrun → `subtype: 'error_max_budget_usd'` and `terminal_reason: 'budget_exhausted'`. Still the only first-party USD cap in the benchmark (shared with the Py SDK). Note: resumed/forked sessions now continue `total_cost_usd` from earlier turns, but "`maxBudgetUsd` is unchanged" (CHANGELOG.md:91) — the cap applies to the run, so a cumulative tenant budget is still yours.
- **`Options.maxTurns`** (sdk.d.ts:1925): turn ceiling. The hosting doc lists "No top-level session timeout" as a known limitation and recommends `maxTurns` instead.
- **`Options.taskBudget.total`** (sdk.d.ts:1938, `@alpha`): API-side token budget the model can see.
- **Pricing control**: `managedSettings.modelPricing` (with `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`) lets you price at your negotiated rates; `modelUsage[*].costBasis` says which table was used (CHANGELOG.md:284-285).
- **No per-tenant rate limiter or cumulative cap.** Aggregate `modelUsage[*].costUSD` per tenant and refuse `query()` when over.

### ⭐ Required — light usage example

```ts
import { query, tool, createSdkMcpServer, type PreToolUseHookInput } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

// (1) Tenant identity: closures + per-tenant cwd/config dir + store projectKey.
const tenantId = 'acme', targetingStrategyId = 'strat-42', userId = 'u-123';

const topicSearch    = tool('topicSearch', 'Search Predict topics.', { query: z.string(), tenantId: z.string() },
  async (args) => ({ content: [{ type: 'text', text: await predictApi.search(args.tenantId, args.query, targetingStrategyId) }] }));
const iabSearch      = tool('iabSearch', '…', { query: z.string(), tenantId: z.string() }, /* … */);
const audienceCreate = tool('audienceCreate', '…', { name: z.string(), tenantId: z.string() }, /* … */);
const predictServer  = createSdkMcpServer({ name: 'predict', tools: [topicSearch, iabSearch, audienceCreate] });

const q = query({
  prompt: 'Build an audience for young moms in Brazil',
  options: {
    cwd: `/tenants/${tenantId}`,
    settingSources: [],                                   // no shared user/project settings
    env: { ...process.env, CLAUDE_CONFIG_DIR: `/tenants/${tenantId}/.config`,
           CLAUDE_CODE_DISABLE_AUTO_MEMORY: '1', TENANT_ID: tenantId, USER_ID: userId },
    sessionStore: pgStoreFor(tenantId),                   // store keys by projectKey = tenant
    mcpServers: { predict: predictServer },
    permissionMode: 'default',                            // explicit since 0.3.286

    // (2) Only our three tools are visible; no built-ins.
    tools: [],
    allowedTools: ['mcp__predict__topicSearch', 'mcp__predict__iabSearch', 'mcp__predict__audienceCreate'],

    // (3) Force tenantId on every topicSearch, whatever the model wrote.
    hooks: {
      PreToolUse: [{
        matcher: 'mcp__predict__topicSearch',
        hooks: [async (input) => ({
          continue: true,
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            updatedInput: { ...((input as PreToolUseHookInput).tool_input as object), tenantId },
          },
        })],
      }],
    },
    maxBudgetUsd: 0.50,
  },
});
for await (const msg of q) { /* stream to client */ }
```

All three steps work. `tools: []` removes built-in tools; MCP tools come from `mcpServers` and are pre-approved by `allowedTools`. The `PreToolUse.updatedInput` injection is the same pattern as the Python SDK.

---

## 7. Hook & Middleware Capabilities (Context Engineering)

### 7.1 Enumerate every hook / middleware / lifecycle callback

`HOOK_EVENTS` (sdk.d.ts:957) — **33 events** (29 at 0.3.143; new: `PreModelSwitch`, `PostModelSwitch`, `DirectoryAdded`, `MessageDisplay`):

| Event | Fires when | Can do |
|---|---|---|
| `PreToolUse` | Before each tool dispatch | Allow/deny/ask, `updatedInput`, `additionalContext` |
| `PostToolUse` | After each tool returns | `updatedToolOutput` (all tools) / `updatedMCPToolOutput` (MCP only), `additionalContext`, `classifierContext` (note to the auto-mode classifier, CHANGELOG.md:338) |
| `PostToolUseFailure` | After a tool failure | `additionalContext` |
| `PostToolBatch` | Once per batch after all tools resolve | `additionalContext` |
| `Notification` | Notification queued (now also for pending permission prompts on the SDK path, CHANGELOG.md:354) | Observe / `additionalContext` |
| `UserPromptSubmit` | User prompt submitted | `additionalContext`, `sessionTitle`, `suppressOriginalPrompt`, block |
| `UserPromptExpansion` | Slash command / MCP prompt expanded | `additionalContext`, `suppressOriginalPrompt` (CHANGELOG.md:326) |
| `SessionStart` | New / resume / fork / clear / compact | `additionalContext`, `initialUserMessage`, `sessionTitle`, `watchPaths`, **`reloadSkills`** (CHANGELOG.md:751) |
| `SessionEnd` | Session ends | Observe |
| `Stop` | Loop wants to stop | Block to continue; **`additionalContext`** to continue with feedback (CHANGELOG.md:705) |
| `StopFailure` | Turn ended with an API error | Observe (`error`, `error_details`) |
| `SubagentStart` | Sub-agent started | `additionalContext` |
| `SubagentStop` | Sub-agent ended | Block / `additionalContext` |
| `PreCompact` | Before compaction | Custom instructions |
| `PostCompact` | After compaction | Observe (`compact_summary`) |
| `PreModelSwitch` | **new** — before a model switch | allow / deny / ask; input carries `context_tokens`, `prompt_cache_warm`, `estimated_cache_write_usd` (sdk.d.ts:2691-2736) |
| `PostModelSwitch` | **new** — after a model switch | Observe (sdk.d.ts:2570) |
| `PermissionRequest` | Permission needed | Allow/deny with `updatedInput`/`updatedPermissions` |
| `PermissionDenied` | A call was denied | Observe / `retry` |
| `Setup` | Workspace setup | `additionalContext`, `watchPaths` |
| `TeammateIdle` | Teammate idle | Observe |
| `TaskCreated` / `TaskCompleted` | Task lifecycle | Observe |
| `Elicitation` / `ElicitationResult` | MCP server asks for input | accept/decline/cancel; `{ decision: 'block' }` now declines (CHANGELOG.md:31) |
| `ConfigChange` | Settings file changed | Observe |
| `WorktreeCreate` / `WorktreeRemove` | Sub-agent worktree lifecycle | Set `worktreePath` / observe |
| `InstructionsLoaded` | CLAUDE.md etc. loaded | Observe |
| `CwdChanged` / `FileChanged` | cwd or watched file changed | `watchPaths` |
| `DirectoryAdded` | **new** — working directory registered mid-session (sdk.d.ts:672) | Observe |
| `MessageDisplay` | **new** — assistant text delta displayed (sdk.d.ts:1351) | `displayContent` replaces the displayed text (display only, not model context) |

Plus two non-hook callbacks: `canUseTool` (permission) and `onElicitation` / `onUserDialog`.

Still the most comprehensive hook surface in the benchmark.

### 7.2 Hook concurrency model

Several matchers per event. Hooks that match the same call **run in parallel on the original payload**, and rewrites are **last-write-wins**; the `PostToolUse.classifierContext` docstring is explicit: "hooks run in parallel on the ORIGINAL output, so an identity rewrite competes last-write-wins with sibling rewrites and can clobber a real redaction" (sdk.d.ts:2670-2674). Keep one hook per rewrite concern per tool.

Async hooks: return `{ async: true, asyncTimeout? }` (`AsyncHookJSONOutput`, sdk.d.ts:133). Timeouts are now handled per event: a timed-out `Stop`/`SubagentStop`/`SessionStart` callback counts as "no decision" instead of a failure (CHANGELOG.md:125), and a timed-out `UserPromptSubmit` callback blocks the prompt with a message instead of killing the query (CHANGELOG.md:489). Plugin hook ordering is configurable from managed settings (`prependPlugins`/`appendPlugins`).

### 7.3 Specific capability tests

| Capability | Yes/No | How |
|---|---|---|
| **Inject system messages at session start** | ✅ | `SessionStart` → `additionalContext`. Static: `systemPrompt: { type: 'preset', preset: 'claude_code', append }`. |
| **Expand the user input** | ✅ | `UserPromptSubmit` / `UserPromptExpansion` with `additionalContext` or `suppressOriginalPrompt`. |
| **Mutate the messages list before each LLM call** | ⚠️ Partial | The CLI owns the message list. You add context via `additionalContext`; cache boundaries via `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`; `MessageDisplay` only changes what is displayed. No pre-request message-rewrite hook. |
| **Mutate / decorate tool input before dispatch** | ✅ | `PreToolUse.updatedInput` or `canUseTool.updatedInput`. |
| **Mutate / decorate tool result before it returns to the LLM** | ✅ | `PostToolUse.updatedToolOutput` (sdk.d.ts:2668-2680). |
| **Emit additional tool calls in response to a tool result** | ❌ | No `additional_messages`-style field. Closest: `PostToolUse`/`PostToolBatch` `additionalContext`, or a `Stop` hook returning `additionalContext` so the turn continues (CHANGELOG.md:705); the model still decides whether to call a tool. |

### 7.4 Auto-compaction

**Built-in.** The CLI compacts near the context limit (`PreCompact.trigger: 'auto'`) or on `/compact` (`'manual'`). `PreCompact` can supply custom instructions; `PostCompact` sees the summary; `SDKCompactBoundaryMessage` marks it. A custom `systemPrompt` change mid-session now takes effect at the next compaction because prompt recording defaults on (`snapshot`, CHANGELOG.md:171). No SDK option sets the threshold.

### 7.5 Prompt cache optimization

**First-class and more explicit than in May:**

1. **`systemPrompt: string[]`** with `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` (sdk.d.ts:9590) splits a cacheable static prefix from a dynamic suffix. Fixed to work on Bedrock, Vertex, Foundry and gateway providers (CHANGELOG.md:320).
2. **`excludeDynamicSections: true`** (sdk.d.ts:2409) on the preset prompt strips per-user sections so the preset is byte-identical across users — cross-tenant cache hits.
3. **`reloadPlugins({ holdOnCacheImpact: true })`** holds a reload that would invalidate the cache (CHANGELOG.md:158).
4. **`PreModelSwitch` hook** reports whether the cache is warm and the estimated re-cache cost before a model switch; resume/fork `SessionStart` input reports `prompt_cache_likely_expired` and `estimated_cache_write_usd` (sdk.d.ts:6440-6455).
5. The CLI places cache breakpoints for stable prefixes automatically. MCP tool definitions are deferred behind tool search unless `alwaysLoad`.

Cache stats: `usage.cache_creation_input_tokens` / `cache_read_input_tokens`; per model `cacheReadInputTokens` / `cacheCreationInputTokens` in `modelUsage`.

### 7.6 Tool result clearing

- **`PostToolUse.updatedToolOutput`** replaces the result before the model sees it — truncate, summarise or redact in place (sdk.d.ts:2668-2680).
- **Compaction** summarises old turns, including large tool results.
- **No API to remove a past tool result from history after the model has seen it.** `rewind_conversation` / `resumeSessionAt` truncate the conversation, which is not the same as in-place clearing.

### 7.7 Progressive disclosure

- **Filesystem stash**: built-in `Write`/`Read` encode the "write big output to disk, read on demand" pattern; `Read` supports `offset`/`limit`/`pages`.
- **Deferred MCP tool definitions**: tool schemas stay out of the prompt until tool search loads them (`alwaysLoad` overrides, sdk.d.ts:629-633, 1187).
- **Skills**: listing only in the prompt; body loaded when the `Skill` tool is invoked (§10.5).
- **`resource_link` results**: MCP tools can return files by reference (`tool_use_result.resourceLinks`, CHANGELOG.md:228), and `readMcpResource()` reads `ui://` resources (CHANGELOG.md:70).
- **Context accounting**: `Query.getContextUsage({ detail })` (sdk.d.ts:3034) returns per-category usage with `kind` (used/free/buffer/deferred); `detail: 'summary'` avoids token-count API calls (CHANGELOG.md:160, 237).

### 7.8 Architectural diagram — where hooks fire

```mermaid
flowchart TD
  START([query() called]) --> SS[SessionStart hook<br/>additionalContext / reloadSkills]
  SS --> SU[Setup hook]
  SU --> UPS[UserPromptSubmit hook]
  UPS --> UPE{Slash cmd / MCP prompt?}
  UPE -->|Yes| UPEH[UserPromptExpansion hook]
  UPE -->|No|  API[Anthropic API call]
  UPEH --> API
  API -.text deltas.-> MD[MessageDisplay hook<br/>display only]
  API --> ASSIST{assistant has tool_use?}
  ASSIST -->|No| STOP[Stop hook<br/>block / additionalContext]
  STOP -->|continue| API
  ASSIST -->|Yes| PRE[PreToolUse hook<br/>updatedInput / decision]
  PRE --> PERM[Rules + permission mode / auto classifier<br/>PermissionRequest hook + canUseTool]
  PERM --> DISPATCH[Tool dispatch<br/>built-in / MCP / SDK-MCP / Agent]
  DISPATCH --> POST[PostToolUse / PostToolUseFailure<br/>updatedToolOutput]
  POST --> BATCH{All tools in batch done?}
  BATCH -->|No| DISPATCH
  BATCH -->|Yes| PBATCH[PostToolBatch hook]
  PBATCH --> PCC{Context near limit?}
  PCC -->|Yes| PRECOMPACT[PreCompact] --> POSTCOMPACT[PostCompact] --> API
  PCC -->|No| API
  STOP --> RESULT([SDKResultMessage])
  RESULT --> END([SessionEnd hook])
  SETMODEL([setModel / /model]) --> PMS[PreModelSwitch] --> POMS[PostModelSwitch]
```

Sub-agent hooks (`SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`) fire when the `Agent` tool spawns or finishes a sub-agent; `DirectoryAdded`, `CwdChanged`, `FileChanged`, `ConfigChange`, `InstructionsLoaded` fire on environment changes.

### ⭐ Required — light usage example

```ts
import { query, type SessionStartHookInput, type PreToolUseHookInput, type PostToolUseHookInput } from '@anthropic-ai/claude-agent-sdk';

const tenantId = 'acme', locale = 'fr-FR';

const q = query({
  prompt: 'Find topics for young moms',
  options: {
    hooks: {
      // (1) Inject tenant context on session start.
      SessionStart: [{ hooks: [async (_i) => ({ continue: true, hookSpecificOutput: {
        hookEventName: 'SessionStart',
        additionalContext: `tenant=${tenantId}, locale=${locale}, today=2026-10-01`,
      } })] }],
      // (2) Force tenantId on every topicSearch call.
      PreToolUse: [{ matcher: 'mcp__predict__topicSearch', hooks: [async (i) => ({ continue: true, hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        updatedInput: { ...((i as PreToolUseHookInput).tool_input as object), tenantId },
      } })] }],
      // (3) Shrink big topicSearch results in place.
      PostToolUse: [{ matcher: 'mcp__predict__topicSearch', hooks: [async (i) => {
        const out = (i as PostToolUseHookInput).tool_response as { topics?: unknown[] };
        if (!out?.topics || out.topics.length <= 50) return { continue: true };
        return { continue: true, hookSpecificOutput: {
          hookEventName: 'PostToolUse',
          updatedToolOutput: { topics: out.topics.slice(0, 50), truncated: true, total: out.topics.length },
        } };
      }] }],
    },
  },
});
for await (const msg of q) { /* ... */ }
```

All three are first-class. `SessionStart.additionalContext` is added to the context by the CLI; `PreToolUse.updatedInput` replaces the model's input; `PostToolUse.updatedToolOutput` replaces what the model sees. For a model-written summary instead of truncation, call a cheap model inside the hook — the SDK has no built-in summariser for tool results.

---

## 8. HTTP API

### 8.1 Does the framework ship an HTTP server?

**No.** Library-only. You embed `query()` in your own Express / Fastify / Next.js / Hono / Bun.serve handler. The hosting doc: "expose an HTTP or WebSocket port on the container. Your application handles client requests on that port and calls the SDK internally; the subprocess itself does not listen on the network."

`@anthropic-ai/claude-agent-sdk/browser` exposes `query(options: BrowserQueryOptions)` (browser-sdk.d.ts:126) with either a `websocket` or (since 0.3.169) an `sse` transport — it is a **client** for a server you build that speaks the SDK's message protocol. `bridge.mjs` talks to claude.ai's Remote Control endpoint, not to a server you run.

### 8.2 HTTP streaming protocol (SSE/WS)

In-process: `AsyncGenerator<SDKMessage>`. You choose the wire transport:

- **SSE**: one `SDKMessage` JSON per `data:` frame. The browser client's SSE transport supports resume with `fromSequenceNum`, `getSseLastSequenceNum(query)`, `onCatchUpTruncated` and `onDeliveryUpdate` (CHANGELOG.md:170), so if your server assigns sequence numbers the client can reconnect without gaps.
- **WebSocket**: use the browser client's `websocket` option.
- **CLI ↔ SDK**: line-delimited JSON over stdio.

Not provided — BYO HTTP layer.

### 8.3 HTTP endpoints that start an agent run

Not provided — BYO HTTP layer. Sample:

```ts
import express from 'express';
import { query } from '@anthropic-ai/claude-agent-sdk';

const app = express();
app.use(express.json());

app.post('/v1/sessions/:sid/turns', async (req, res) => {
  const tenantId = req.header('x-tenant-id');            // set by your auth gateway
  if (!tenantId) return res.status(401).end();
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.flushHeaders();

  const q = query({
    prompt: req.body.prompt,
    options: { resume: req.params.sid, cwd: `/tenants/${tenantId}`, sessionStore: pgStore, permissionMode: 'default' },
  });
  registry.set(req.params.sid, q);
  req.on('close', () => q.close());
  let seq = 0;
  for await (const msg of q) res.write(`id: ${seq++}\ndata: ${JSON.stringify(msg)}\n\n`);
  res.end();
});
```

### 8.4 Interrupt / cancel in-flight run

In-process: `Query.interrupt()` (sdk.d.ts:2858) returns a typed receipt with `still_queued` UUIDs (CHANGELOG.md:506); the control request accepts opt-in `cancel_queued` to drop queued messages too (CHANGELOG.md:422). `Query.close()` (sdk.d.ts:3241) terminates the subprocess (stdin EOF, ~2 s grace, then the abort signal). `Options.abortController` works as well. With `perTaskStopAffordance`, `interrupt()` stops only the current turn and keeps background agents running (sdk.d.ts:1805). Open issue #429: `interrupt()` during CLI startup resolves but does not interrupt (0.3.241).

HTTP: BYO, e.g. `DELETE /v1/sessions/:sid/turn` → look up the `Query` handle → `q.interrupt()`.

### 8.5 Resume / replay endpoint

The SDK provides the logic, you provide the endpoint:

```ts
app.post('/v1/sessions/:sid/resume', async (req, res) => {
  const q = query({ prompt: req.body.prompt, options: { resume: req.params.sid, sessionStore: pgStore } });
  // ... stream q
});
```

For a reopened tab: replay history with `getSessionMessages(sid, { sessionStore })` (or your SSE sequence numbers), then attach to the live `Query` if one is running. Resume-from-point: `resumeSessionAt` (sdk.d.ts:2099) with `resumeDropsTurn` as a guard.

### 8.6 HITL approval workflow

The HITL primitive is still `canUseTool`, with better support for out-of-band answers:

1. Model emits `tool_use`; rules / mode don't decide it.
2. CLI sends `control_request: can_use_tool` (with `agent_id` for background agents — CHANGELOG.md:597).
3. Your `canUseTool(toolName, input, { toolUseID, requestId, title, displayName, description, defaultToNo, … })` runs. You can either await your operator UI and return a `PermissionResult`, or return `null` after you have sent the `control_response` out of band echoing `requestId` (CHANGELOG.md:538).
4. CLI dispatches with the verdict.

A **pause state is now observable** on the stream if you opt in: `session_state_changed` reports `requires_action` while a permission prompt or MCP elicitation waits (`CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS=1`, CHANGELOG.md:73), and `initialize` returns `pending_permission_requests` so a reconnecting host can re-render pending approvals (CHANGELOG.md:164); `reinitialize()` redelivers them. For sessions with nobody to answer, `permissionPrompts: 'none'` auto-denies.

HTTP shape: BYO — emit a custom SSE frame when `canUseTool` is pending and resolve it on `POST /approvals`.

### 8.7 Token streaming

With `includePartialMessages: true` the SDK yields `SDKPartialAssistantMessage` (`type: 'stream_event'`, sdk.d.ts:5442) wrapping the raw Anthropic stream event. Wire frames if you forward them as SSE:

```text
# text delta
data: {"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Let me find "}},"parent_tool_use_id":null,"session_id":"2f3c-...","uuid":"..."}

# partial tool arguments (before the model finishes the call)
data: {"type":"stream_event","event":{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"query\": \"young"}},"parent_tool_use_id":null,"session_id":"2f3c-...","uuid":"..."}

# agent activity event
data: {"type":"tool_progress","tool_use_id":"toolu_01XYZ","tool_name":"mcp__predict__topicSearch","parent_tool_use_id":null,"elapsed_time_seconds":1.8,"session_id":"2f3c-...","uuid":"..."}
```

Other activity frames: `system/task_started`, `task_progress`, `task_notification`, `background_tasks_changed`, `thinking_tokens`, `hook_*` (with `includeHookEvents`). Open issue #213 asks for streaming Bash stdout/stderr; today tool output arrives only in the final `tool_result`.

### 8.8 Authentication & Authorisation

**Not provided — BYO.** The SDK does not validate JWTs or extract tenants. The hosting doc: "put authentication at a gateway in front of the agent container. The agent should receive pre-authenticated requests and should not be the component that validates user tokens." Resource-level authorisation (which tenant may resume which `sessionId`) is your session table plus `projectKey` scoping in your store. The bridge path needs an Anthropic OAuth token.

### 8.9 Tool-call state reconstruction

Tool calls are `tool_use` content blocks with an `id` in `SDKAssistantMessage.message.content`; the result is a `tool_result` block with the same `tool_use_id` in the next `SDKUserMessage`:

```jsonc
{ "type": "assistant", "message": { "content": [
  { "type": "tool_use", "id": "toolu_01XYZ", "name": "mcp__predict__topicSearch", "input": { "query": "young moms" } }
] }, "tool_use_meta": { "toolu_01XYZ": { "display_name": "Topic search" } }, "uuid": "asst-1" }
{ "type": "tool_progress", "tool_use_id": "toolu_01XYZ", "elapsed_time_seconds": 1.2 }
{ "type": "user", "message": { "content": [
  { "type": "tool_result", "tool_use_id": "toolu_01XYZ", "content": "[...]" }
] }, "tool_result_meta": { /* non_execution_kind when denied / interrupted */ } }
```

**Linkage is explicit: `tool_use_id`.** `tool_progress`, `task_started`/`task_notification` (now also when the CLI resumes a background sub-agent itself — CHANGELOG.md:150) and `resource_links` on `task_notification` carry it. Sub-agent frames carry `parent_tool_use_id`. `tool_use_meta` (display names, `icon_url`) and `tool_result_meta` (denied/interrupted/cancelled) are UI sidecars added since May (CHANGELOG.md:629, 444).

### 8.10 Health checks / graceful shutdown

**Not provided.** Your server provides `/healthz` etc. SDK pieces: `Query.close()`, `AbortController`, `interrupt()`. Remote Control workers send `worker_shutting_down` on graceful exit (CHANGELOG.md:638). The subprocess exposes no health endpoint.

### ⭐ Required — light usage example

#### 1. Start a run with `X-Tenant-Id` and a user message

```bash
curl -N -X POST https://api.example.com/v1/sessions/2f3c.../turns \
  -H 'Authorization: Bearer eyJ...' -H 'X-Tenant-Id: acme' -H 'Content-Type: application/json' \
  -d '{"prompt": "Build an audience for young moms in Brazil"}'
```

#### 2. Sample SSE the client receives

```
id: 0
data: {"type":"system","subtype":"init","session_id":"2f3c-...","model":"claude-opus-4-7","tools":["mcp__predict__topicSearch","mcp__predict__iabSearch","mcp__predict__audienceCreate"],"permissionMode":"default","mcp_servers":[{"name":"predict","status":"connected"}],"uuid":"..."}

id: 1
data: {"type":"assistant","session_id":"2f3c-...","message":{"id":"msg_01ABC","role":"assistant","content":[{"type":"text","text":"Let me find relevant topics."},{"type":"tool_use","id":"toolu_01XYZ","name":"mcp__predict__topicSearch","input":{"query":"young moms"}}],"stop_reason":"tool_use"},"uuid":"..."}

id: 2
data: {"type":"tool_progress","tool_use_id":"toolu_01XYZ","tool_name":"mcp__predict__topicSearch","parent_tool_use_id":null,"elapsed_time_seconds":1.8,"uuid":"..."}

id: 3
data: {"type":"result","subtype":"success","session_id":"2f3c-...","num_turns":2,"total_cost_usd":0.018,"result":"Found 12 relevant topics…","terminal_reason":"completed","is_error":false,"uuid":"..."}
```

#### 3. Cancel mid-flight

```bash
curl -X DELETE https://api.example.com/v1/sessions/2f3c.../turn -H 'Authorization: Bearer eyJ...' -H 'X-Tenant-Id: acme'
# Server: registry.get(sid).interrupt()  → receipt { still_queued: [...] }
```

#### 4. HITL approval verdict for a paused tool call

```bash
curl -X POST https://api.example.com/v1/sessions/2f3c.../approvals -H 'Authorization: Bearer eyJ...' \
  -d '{"requestId":"req_123","toolUseId":"toolu_01XYZ","decision":"allow","updatedInput":{"query":"young moms","tenantId":"acme"}}'
# Server: resolves the pending canUseTool promise for requestId (or writes the control_response and returns null)
```

The SSE encoding, the cancel route and the HITL route are patterns you build; the SDK ships the primitives.

---

## 9. Sub-agents

### 9.1 Mechanism

Agents-as-tools, first-class in the CLI: the built-in **`Agent`** tool (`AgentInput`, sdk-tools.d.ts:763). When the parent model emits `tool_use` `Agent` with `{ description, prompt, subagent_type, model?, run_in_background?, name?, isolation? }`, the CLI spawns a sub-agent with its own context and returns its result as a `tool_result`.

New since May:

- **`Workflow` tool** (sdk-tools.d.ts:2848): the model (or a predefined workflow in `.claude/workflows/`) runs a self-contained script using `agent()`, `parallel()`, `pipeline()` and `phase()` to orchestrate many sub-agents deterministically. Progress is reported through `workflow_agent` events.
- **Named agents** can be addressed while running (`name`, `SendMessage`).
- **`isolation: 'worktree' | 'remote'`** — `remote` launches the agent in Anthropic's cloud ("availability is gated").

### 9.2 Configuration

1. **Programmatic**: `Options.agents: Record<string, AgentDefinition>` (sdk.d.ts:1574).
2. **Markdown files**: `~/.claude/agents/{name}.md`, `.claude/agents/{name}.md`, `<plugin>/agents/{name}.md` (loaded only if the matching `settingSources` / plugins are enabled).

`AgentDefinition` (sdk.d.ts:38):

```ts
{
  description: string;
  prompt: string;
  tools?: string[];                    // inherits parent tools if omitted
  disallowedTools?: string[];          // mcp__server / mcp__server__* remove a whole server
  model?: string;                      // 'fable' | 'opus' | 'sonnet' | 'haiku' | full id | 'inherit'
  mcpServers?: AgentMcpServerSpec[];
  criticalSystemReminder_EXPERIMENTAL?: string;
  skills?: string[];                   // preloaded skills
  initialPrompt?: string;
  maxTurns?: number;
  background?: boolean;
  omitClaudeMd?: boolean;              // new: run without user/project/local CLAUDE.md
  memory?: 'user' | 'project' | 'local';
  effort?: 'low' | 'medium' | 'high' | 'xhigh' | 'max' | number;
  permissionMode?: PermissionMode;
  observer?: string;                   // new: background observer agent receiving activity digests
  observerMessage?: string;
}
```

### 9.3 LLM-generated configs

**Partly.** The parent cannot define a new sub-agent type (system prompt + tool list) at runtime; `subagent_type` must name a registered agent (open issue #315 covers silent fallback when a plugin agent name doesn't resolve). The parent can, however, choose the per-call `model` (`AgentInput.model`, which "takes precedence over the agent definition's model"), background vs foreground, isolation, and — through the `Workflow` tool — write an orchestration script that composes registered agents with its own per-step prompts.

### 9.4 Output handling

The parent receives a `tool_result` linked by `tool_use_id`. Default stream: sub-agent `tool_use`/`tool_result` only; **`forwardSubagentText: true`** (sdk.d.ts:1867) forwards sub-agent text/thinking as nested `SDKAssistantMessage`s with `parent_tool_use_id`.

The structured result now has a published type, `AgentToolCompletedOutput` (CHANGELOG.md:498); `AgentOutput` (sdk-tools.d.ts:100) carries `agentId`, `agentType`, `content`, `resolvedModel`, `modelsUsed`, `totalToolUseCount`, `totalDurationMs`, `totalTokens`, `usage` (with `output_tokens_details`), `toolStats`, and `status` (`completed` / `async_launched`). Background agents deliver completion via `task_notification`.

### 9.5 Concurrency model

- **Parallel** via several `Agent` `tool_use` blocks in one assistant turn, or via `parallel()` inside a `Workflow` script. `PostToolBatch` fires once after the batch (sdk.d.ts:2619).
- **Background by default** from the model's side ("Agents run in the background by default", `AgentInput.run_in_background`, sdk-tools.d.ts:783), so the parent can keep working and receive `task_notification` later.
- **Caps** (CHANGELOG.md:437-438): nested sub-agents disabled by default (depth 1; `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`), at most 20 concurrently running sub-agents (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). The hosting doc warns that large parallel fan-outs can hit rate limits.
- The parallelism itself is implemented inside the CLI binary; no TS-side `Promise.all` to cite.

### 9.6 Context isolation

**Sub-agents start fresh**: own system prompt, `initialPrompt`, tool set; with `omitClaudeMd: true` they also skip user/project/local `CLAUDE.md`. The parent only receives the result (or forwarded text). Transcripts persist under `<sessionId>/subagents/agent-<id>.jsonl` or `SessionKey.subpath`; sub-agent session messages carry `parent_agent_id` (CHANGELOG.md:523). Background agents now forward permission prompts to `canUseTool` with `agentID` instead of auto-denying (CHANGELOG.md:597).

### 9.7 Lifecycle events

- Hooks: `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`.
- Stream: `task_started` (with `is_backgrounded`, `spawn_depth`, `tool_use_id`), `task_progress` (summaries with `agentProgressSummaries: true`), `task_updated`, `task_notification` (`reason`, `resource_links`), `background_tasks_changed` (full live set), `tool_progress` heartbeats for `Agent` calls with `subagent_retry` while waiting out rate limits (CHANGELOG.md:233, 325, 457, 518).

### 9.8 Sub-agent model override

**Yes.** Three levels:

- `AgentDefinition.model` (sdk.d.ts:58) — alias or full id, `'inherit'` for the parent's model; if omitted, a configured default sub-agent model applies, else the main model.
- `AgentInput.model` per call (sdk-tools.d.ts:779, `"sonnet" | "opus" | "haiku" | "fable"`) — chosen by the parent model, overrides the definition.
- `AgentOutput.resolvedModel` reports the model actually used, including after a mid-turn swap (CHANGELOG.md:468).

Cheap-worker / expensive-supervisor: `AgentDefinition.model: 'haiku'` for workers, `Options.model: 'opus'` for the parent. Issue #293 (per-sub-agent `modelUsage` breakdown) is still open, but `modelUsage` is keyed per model so a different worker model shows up as its own row.

### ⭐ Required — light usage example

```ts
import { query, type AgentDefinition } from '@anthropic-ai/claude-agent-sdk';

const persona = (who: string): AgentDefinition => ({
  description: `Predict targeting persona: ${who}`,
  prompt: `You are ${who}. Evaluate the candidate audience. Return JSON {fit: 0-1, why: string}.`,
  tools: ['mcp__predict__topicSearch'],
  model: 'haiku',
  maxTurns: 6,
  omitClaudeMd: true,
});

const q = query({
  prompt: 'For audience X, run persona-young-mom, persona-tech-bro and persona-retiree in parallel (foreground) and return a verdict matrix.',
  options: {
    model: 'opus',
    agents: {
      'persona-young-mom': persona('a young mom in Brazil, 25-35'),
      'persona-tech-bro':  persona('a tech professional, 28-40'),
      'persona-retiree':   persona('a retiree, 65+'),
    },
    mcpServers: { predict: predictServer },
    forwardSubagentText: true,
    agentProgressSummaries: true,
  },
});

for await (const msg of q) {
  if (msg.type === 'system' && msg.subtype === 'task_started') console.log('started', msg.description);
  if (msg.type === 'system' && msg.subtype === 'task_notification') console.log('done', msg.status, msg.tool_use_id);
  if (msg.type === 'user' && msg.parent_tool_use_id === null) {
    // parent receives each persona's result here as a tool_result block, linked by tool_use_id
  }
}
```

The supervisor emits three `Agent` `tool_use` blocks in one turn; the CLI runs them concurrently. Because the model-facing default is now background execution, ask for foreground runs (or wait for the three `task_notification`s) when the parent needs all results before answering.

---

## 10. Skills

### 10.1 First-class concept?

**Yes.** Skills are a first-class Claude Code feature. They are listed in `SDKSystemMessage.skills` (sdk.d.ts:5896), filtered by `Options.skills`, and invoked through the `Skill` tool. Passing `'Skill'` in `allowedTools` or `AgentDefinition.tools` is deprecated in favour of `skills` (CHANGELOG.md:837; sdk.d.ts:44-46).

### 10.2 File format

Markdown with YAML frontmatter, `SKILL.md` in its own directory. The SDK does not parse the frontmatter itself (the CLI does); fields documented by Claude Code include `name`, `description`, `allowed-tools`, `user-invocable`, and others. Example:

```yaml
---
name: generate-audience-from-brief
description: Convert a campaign brief into a Predict audience (topics + IABs + locale). Use when the user provides a brief and asks to create an audience.
allowed-tools:
  - mcp__predict__topicSearch
  - mcp__predict__iabSearch
  - mcp__predict__audienceCreate
---

# Generate Audience From Brief
1. Extract demographics, interests and brand voice from the brief.
2. Call topicSearch with the interest keywords; call iabSearch with the demographics.
3. Keep top-N topics and top-K IABs; call audienceCreate.
```

Since 0.3.221 the SDK validates names passed in `skills` and rejects malformed or wildcard names (CHANGELOG.md:413). Under a managed `allowManagedPermissionRulesOnly` policy, `allowed-tools` frontmatter from user/project skills is ignored (sdk.d.ts:7213-7215).

### 10.3 Loader mechanism

**Filesystem scan only.** Vendor skills doc: "you create skills as files on disk. The SDK doesn't provide a programmatic API for registering them" (issue #141 open). Discovery roots:

- `~/.claude/skills/*/SKILL.md` (user setting source)
- `<cwd>/.claude/skills/` and `.claude/skills/` in parent dirs up to the repo root (project source); also `<dir>/.claude/skills/` for each `additionalDirectories` entry
- `<plugin>/skills/*/SKILL.md` for `plugins: [{ type: 'local', path }]` — loads regardless of `settingSources`, and `skipMcpDiscovery: true` stops the plugin's `.mcp.json` from being read (CHANGELOG.md:664)
- `projectConfigRoot` (sdk.d.ts:1539) loads `.claude` trees from a trusted checkout instead of `cwd`

New dynamic reload: `Query.reloadSkills()` (sdk.d.ts:3102) and `SessionStart` `reloadSkills: true` (sdk.d.ts:6466) re-scan after a hook has written skills to disk, so they are available in the same session.

### 10.4 Invocation

**A tool call to `Skill`.** The prompt carries the skill listing (name + description); the model calls `Skill` with the skill name; the CLI loads the body into context. A skill can also run as a forked agent; `SkillToolOutput` reports `background: true` when a forked skill was dispatched as a detached background agent (CHANGELOG.md:431). Users can also invoke skills as slash commands; a renamed skill's directory name becomes an alias (CHANGELOG.md:27).

### 10.5 Loading mode

**Lazy**: metadata in the prompt, body on use. `Options.skills` (sdk.d.ts:2273):

- omitted: CLI defaults (skills on — "not skills off");
- `'all'`: every discovered skill;
- `string[]`: only those (names match `name`/directory or `plugin:skill`);
- `[]`: none invocable (skills doc).

"This is a context filter, not a sandbox: unlisted skills are hidden from the model's listing and rejected by the Skill tool, but their files remain on disk and are reachable via Read/Bash."

### 10.6 Skill composition

- Reference other skills by name (plugin-qualified `<plugin>:skill`); the model decides to invoke them.
- Call sub-agents (`Agent`) or a `Workflow` from the skill body; `AgentDefinition.skills` preloads skills into a sub-agent.
- Bundle references, scripts and assets beside `SKILL.md`; the model reads/executes them with `Read`/`Bash` on relative paths.
- A new `ProposeSkills` tool lets the model propose new or improved skills for review (sdk-tools.d.ts:2971); it does not install them.

### ⭐ Required — light usage example

#### 1. Author `SKILL.md`

```bash
mkdir -p /tenants/acme/plugin/skills/generate-audience-from-brief
cat > /tenants/acme/plugin/skills/generate-audience-from-brief/SKILL.md <<'EOF'
---
name: generate-audience-from-brief
description: Turn a campaign brief into a Predict audience. Use when the user gives a brief and asks for an audience.
allowed-tools: [mcp__predict__topicSearch, mcp__predict__iabSearch, mcp__predict__audienceCreate]
---
1. Parse the brief into demographics, interests, brand voice.
2. topicSearch(interests); iabSearch(demographics).
3. Keep top-50 topics + top-20 IABs; audienceCreate({ name, topics, iabs, locale }).
EOF
mkdir -p /tenants/acme/plugin/.claude-plugin && echo '{"name":"acme"}' > /tenants/acme/plugin/.claude-plugin/plugin.json
```

#### 2. Load at runtime (plugin path, no shared settings)

```ts
const q = query({
  prompt: 'Brief: "Reach French young moms, eco diapers, 18-35." Create an audience.',
  options: {
    cwd: '/tenants/acme',
    settingSources: [],                                           // tenant isolation
    plugins: [{ type: 'local', path: '/tenants/acme/plugin', skipMcpDiscovery: true }],
    skills: ['acme:generate-audience-from-brief'],
    mcpServers: { predict: predictServer },
    allowedTools: ['mcp__predict__topicSearch', 'mcp__predict__iabSearch', 'mcp__predict__audienceCreate'],
  },
});
```

#### 3. The agent discovering and invoking it

`system/init` lists `acme:generate-audience-from-brief` in `skills`. The prompt carries its name and description; the model emits `tool_use` `Skill` with that name; the CLI loads the body and the model then calls the `mcp__predict__*` tools. **The LLM sees a tool (`Skill`) plus a listing in the prompt**, not a hook and not the full body up front.

---

## 11. Resource Manager

### 11.1 First-class Resource Manager?

**No.** No registry, no source abstraction with priorities you control, no publish workflow, no per-tenant scoping API. Resources (skills, sub-agents, commands, hooks, MCP servers, plugins, output styles, workflows) are discovered from filesystem paths and from the settings tier. `SdkPluginConfig.type` is still `'local'` only (sdk.d.ts:5552).

### 11.2 Loading sources

| Source | Status | How configured |
|---|---|---|
| **Local filesystem** | ✅ | `~/.claude/{skills,agents,commands,workflows}/`, `.claude/…` under `cwd`/parents/`additionalDirectories`/`projectConfigRoot`, `<plugin>/…` via `plugins: [{ type: 'local', path }]` |
| **Git / GitHub repos** | ⚠️ settings tier | `Settings.extraKnownMarketplaces` with `source: 'github' | 'git'` (with `ref` / `sha`) and `enabledPlugins` (`plugin@marketplace`, version constraints). Passable inline through `Options.settings` or `managedSettings`; headless installation reports progress via `SDKPluginInstallMessage` (`CLAUDE_CODE_SYNC_PLUGIN_INSTALL`, sdk.d.ts:5568). Not a programmatic SDK API. |
| **npm** | ⚠️ settings tier | Marketplace `source: 'npm'` and npm-direct plugins (`package@npm`). |
| **HTTP fetch** | ⚠️ settings tier | Marketplace `source: 'url'`; plugin `source: 'archive'` — zip over HTTPS with optional `sha256` verification (CHANGELOG.md:396). |
| **Custom fetcher (shell command)** | ⚠️ settings tier | Plugin `source: 'command'`: a shell command that leaves a plugin directory and prints its path; re-resolved on install/update and once per session (sdk.d.ts:7501). The closest thing to a pluggable source — e.g. a script that pulls from S3. |
| **OCI / container registries** | ❌ | Not provided — BYO |
| **Cloud object storage (S3 / GCS / R2)** | ❌ for resources; ✅ for **sessions** via `SessionStore` |
| **Postgres / relational DB** | ❌ for resources; ✅ for **sessions** via reference adapter |
| **Vendor cloud / managed registry** | ⚠️ | Anthropic's official marketplace and claude.ai-synced/org-hosted marketplaces exist on the settings tier; no SDK registry API. |
| **MCP servers (HTTP/SSE/stdio)** | ✅ | `Options.mcpServers`, `setMcpServers()` — the dynamic source for *tools*. |

**Net**: programmatic sources are local paths; remote sources exist only through Claude Code's marketplace settings, designed for developer machines and admin policy rather than per-tenant runtime resolution.

### 11.3 Source composition / priority

Settings precedence (`enabledPlugins` docstring, sdk.d.ts:7286-7290): **user < project < local < flag < policy**. `Options.settings` is the flag layer; `Options.managedSettings` is policy-tier and restrictive-only (a managed `strictKnownMarketplaces` applies only where admin policy sets none; `blockedMarketplaces` adds to the admin's — CHANGELOG.md:47). For same-named resources, project definitions win over user ones; plugin skills are namespaced (`plugin:skill`) so they do not collide. Plugin hook order is set by managed `prependPlugins` / `appendPlugins`. There is no documented, caller-controlled merge order like `local > tenant-bucket > global-registry`.

### 11.4 Versioning model

- Plugins: manifest `version` (now reported in `system/init` and `reload_plugins` — CHANGELOG.md:458); marketplace entries can pin git `ref`/`sha`, archives can pin `sha256`, `enabledPlugins` accepts version constraints.
- Skills / sub-agents on disk: no versioning beyond your own VCS.
- CLI: `claude_code_version` `2.1.286`, pinned to the SDK patch.
- No rollback API; to roll back, replace files and `reloadPlugins()` / `reloadSkills()`, or start a new session.

### 11.5 Scoping

**Not supported at the registry layer.** You cannot publish a resource as "tenant X only". Scoping is physical and per session:

- **Filesystem placement** — per-tenant `cwd`, per-tenant plugin directory passed in `plugins`, per-tenant `CLAUDE_CONFIG_DIR`, and `settingSources: []` so shared user/project trees do not leak (hosting doc).
- **Runtime filters** — `Options.skills`, `tools`, `allowedTools`/`disallowedTools`, `agents`, `mcpServers`, per session.
- **Policy** — `managedSettings` (per `query()`) can block marketplaces, restrict permission rules to managed ones, and lock customisation surfaces to plugins only (`strictPluginOnlyCustomization`, sdk.d.ts:7231).

There is no `tenantId → skills` mapping API; you build that table and translate it into the options above.

### 11.6 Deployment workflow

**Not provided — BYO.** No draft → review → publish → promote, no environments, no approval gates. A practical pattern: skills in a Git repo, CI packages per-tenant plugin directories (or zips with `sha256`) into object storage, the pod syncs the tenant plugin at session start (or in a `SessionStart` hook followed by `reloadSkills: true`).

### 11.7 Lifecycle / governance

**Not provided — BYO** for lifecycle states and publisher RBAC. The settings tier offers admin-side governance for marketplaces (allow/block lists, host patterns, managed-only permission rules), which is organisation policy, not a per-resource lifecycle.

### 11.8 Programmatic API

Dynamic operations on a live session:

- MCP: `setMcpServers()` (sdk.d.ts:3205), `toggleMcpServer()`, `reconnectMcpServer()`, `mcpServerStatus()`, `setMcpPermissionModeOverride()` (sdk.d.ts:2882).
- Plugins / skills / styles: `reloadPlugins({ holdOnCacheImpact })` (sdk.d.ts:3094), `reloadSkills()` (sdk.d.ts:3102), `reloadOutputStyles()` (sdk.d.ts:3112).
- Settings: `applyFlagSettings()`, `updateSettings('localSettings' | 'userSettings', …)` (sdk.d.ts:2964), `resolveSettings()` (sdk.d.ts:3311, with per-key provenance).
- Listing: `supportedCommands()` (skills appear here), `supportedAgents()`, `supportedModels()`, `getContextUsage()`; live updates via `system/commands_changed`.

No `addSkill()`, `addAgent()` or registry search.

### 11.9 Caching & sync model

- Skills / plugins / agents: read at session start; re-scan with `reloadSkills()` / `reloadPlugins()` or `SessionStart` `reloadSkills: true`. No background sync or file watching of skill dirs (you can wire `FileChanged`/`watchPaths`).
- Marketplace plugins: installed into the config dir; `autoUpdate` behaviour is a Claude Code setting.
- MCP tool lists: cached after connect; refreshed on reconnect / `setMcpServers()` / server `tools/list_changed` (`sdk_mcp_tools_list_changed` capability, CHANGELOG.md:5).
- Sessions: JSONL per entry, `SessionStore` mirror in ~100 ms batches.

### ⭐ Required — light usage example

The SDK has no multi-source Resource Manager, so this is the scaffolding you would own:

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';
import { execSync } from 'node:child_process';

const tenantId = 'acme';
const pluginDir = `/var/tenants/${tenantId}/plugin`;

// (1) Two sources, S3 wins for this tenant: sync shared skills first, then overlay the tenant bucket.
execSync(`git -C /var/cache/predict-skills pull || git clone --depth=1 https://github.com/dailymotion/predict-skills /var/cache/predict-skills`);
execSync(`rsync -a --delete /var/cache/predict-skills/skills/ ${pluginDir}/skills/`);
execSync(`aws s3 sync s3://predict-skills/tenants/${tenantId}/ ${pluginDir}/skills/`);   // overwrites same-named skills

// (2) "Promote draft → active for acme only" = copy into the tenant prefix (your own registry decides).
execSync(`aws s3 cp --recursive s3://predict-skills/draft/audience-gen-v2/ s3://predict-skills/tenants/${tenantId}/audience-gen-v2/`);

// (3) List the skills visible to a request with tenantId=acme.
const q = query({
  prompt: idleInput(),                    // AsyncIterable<SDKUserMessage> that yields nothing until closed
  options: { cwd: `/var/tenants/${tenantId}`, settingSources: [],
             plugins: [{ type: 'local', path: pluginDir }], skills: 'all' },
});
console.log((await q.supportedCommands()).map((c) => c.name));
q.close();
```

Every step is BYO around a filesystem loader. A production Resource Manager would be your own service mapping tenants to skill versions and materialising plugin directories (or `sha256`-pinned archives) before `query()`.

---

## 12. Observability: Usage, Cost, Tracing, Audit

### 12.1 Where tokens are surfaced

- **Per assistant message**: `SDKAssistantMessage.message.usage` (Anthropic `BetaMessage.usage`).
- **Per result**: `SDKResultMessage.usage` (`NonNullableUsage`) — documented since 0.3.223 as **main-loop-only and per turn** (CHANGELOG.md:405). `usage.output_tokens_details.thinking_tokens` now reports real values (CHANGELOG.md:227).
- **Per result, per model**: `SDKResultMessage.modelUsage: Record<string, ModelUsage>` (sdk.d.ts:1430) — **cumulative, covers all query-pipeline calls (sub-agents, side calls), and "the field for cost accounting"** (CHANGELOG.md:405). Fields: `inputTokens`, `outputTokens`, `thinkingTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `webSearchRequests`, `costUSD`, `contextWindow`, `maxOutputTokens`, `canonicalModel`, `provider`, `costBasis`.
- **Per sub-agent**: `AgentOutput.usage` (sdk-tools.d.ts:100). Per-sub-agent rows in `modelUsage` (#293) are still not provided.
- **Live estimates**: `system/thinking_tokens` frames during a turn; `Query.getContextUsage()` snapshot; `/usage` in headless mode attaches an `SDKUsageReport` (session totals + plan rows) to the assistant message (CHANGELOG.md:122); `usage_EXPERIMENTAL_…()` returns session cost, plan rate limits and local usage data (CHANGELOG.md:678).

### 12.2 Per-call / per-turn / per-session / per-tenant rollups

| Granularity | Surfaced where |
|---|---|
| **Per LLM call** | `SDKAssistantMessage.message.usage` |
| **Per turn (main loop)** | `SDKResultMessage.usage` |
| **Per session (cumulative)** | `SDKResultMessage.modelUsage` and `total_cost_usd` are cumulative for the process; since 0.3.277 a resumed or forked session continues from earlier turns instead of starting at zero (CHANGELOG.md:91). Across process restarts without resume: BYO. |
| **Per tenant** | **BYO** — aggregate by your tenant key / `projectKey` |
| **Per sub-agent** | `AgentOutput.usage` |
| **Per model** | `modelUsage[model]` (with `provider`, `canonicalModel`) |

### 12.3 USD cost computation

**Built-in.**

- `SDKResultMessage.total_cost_usd` and `modelUsage[*].costUSD`, priced by the CLI's tables. Since 0.3.239 they include the 1.1× US-only-inference multiplier when `inference_geo: "us"` (CHANGELOG.md:318).
- `costBasis: 'list' | 'managed' | 'unknown'` tells you whether built-in list prices, managed `modelPricing`, or a guess was used (CHANGELOG.md:284). Hosts can set `managedSettings.modelPricing` to their negotiated rates (CHANGELOG.md:285).
- `Options.maxBudgetUsd` (sdk.d.ts:1930) enforces a per-run ceiling.

### 12.4 Per-tenant / per-conversation cost

Per conversation: `total_cost_usd` / `modelUsage` on the latest result of a session (cumulative, including resumes). Per tenant: aggregate yourself keyed by your tenant id; the `SessionStore` is not an aggregation point. `canonicalModel` + `provider` per row let billing pick the right rate table (CHANGELOG.md:433).

### 12.5 LLM / tool tracing

- **Built into the CLI**: the subprocess exports OpenTelemetry traces, metrics and logs when configured via env vars (hosting doc):

  ```bash
  CLAUDE_CODE_ENABLE_TELEMETRY=1
  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1   # traces only
  OTEL_TRACES_EXPORTER=otlp OTEL_METRICS_EXPORTER=otlp OTEL_LOGS_EXPORTER=otlp
  OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.example.com:4318
  ```

  Prompt text and tool inputs are excluded from exports by default (opt-in flags documented on the observability page).
- **Trace-context propagation**: the caller's active OTel context is forwarded to the subprocess so CLI spans parent under your trace (CHANGELOG.md:928).
- **Correlation**: hook inputs carry `prompt_id` matching OTel prompt-level events (sdk.d.ts:178; CHANGELOG.md:555).
- No first-party LangSmith / Langfuse exporter; any OTLP backend works.

### 12.6 Audit logging (who / when / what)

**Not first-class.** The JSONL transcript (local, append-only; mirrored to a `SessionStore` if set) records tool calls, results, permission denials and model responses. `result.permission_denials` now includes path-scoped deny-rule blocks (CHANGELOG.md:148); `system/permission_denied` is emitted even without `canUseTool` (CHANGELOG.md:404) and carries typed reasons (CHANGELOG.md:636). For a real audit log, push `PreToolUse` / `PostToolUse` / `PermissionDenied` / `PermissionRequest` hook events to your own sink. Not tamper-evident.

### 12.7 Canonical "where do I read token counts" code path

```ts
// sdk.d.ts:5691 (abridged)
export declare type SDKResultSuccess = {
  type: 'result';
  subtype: 'success';
  duration_ms: number;
  duration_api_ms: number;
  ttft_ms?: number;
  num_turns: number;
  result: string;
  total_cost_usd: number;                       // cumulative USD
  usage: NonNullableUsage;                      // main loop, this turn
  modelUsage: Record<string, ModelUsage>;       // cumulative, all calls — use for cost (sdk.d.ts:1430)
  permission_denials: SDKPermissionDenial[];
  terminal_reason?: TerminalReason;
  result_index?: number;
  // ... latency and correlation fields
};
```

`NonNullableUsage` derives from `@anthropic-ai/sdk`'s `BetaUsage`; `ModelUsage` is SDK-defined and uses camelCase (`costUSD`, not `cost_usd`).

### ⭐ Required — light usage example

```ts
import { query } from '@anthropic-ai/claude-agent-sdk';
import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('predict-agent');
const tokensIn  = meter.createCounter('llm.tokens.input',  { unit: 'tokens' });
const tokensOut = meter.createCounter('llm.tokens.output', { unit: 'tokens' });
const costUsd   = meter.createCounter('llm.cost.usd',      { unit: 'USD' });
const lastCost  = new Map<string, number>();       // modelUsage is cumulative per session → emit deltas

async function runOneTurn(tenantId: string, sessionId: string, prompt: string) {
  for await (const msg of query({ prompt, options: { resume: sessionId, sessionStore: pgStore } })) {
    if (msg.type !== 'result') continue;
    // (1) Read tokens + cost for this run.
    console.log({ tokens_in: msg.usage.input_tokens, tokens_out: msg.usage.output_tokens, cost_usd: msg.total_cost_usd });
    // (2) Push per-tenant, per-model deltas to OTel (or Datadog via the OTel exporter).
    for (const [model, m] of Object.entries(msg.modelUsage)) {
      const key = `${sessionId}:${model}`;
      const delta = m.costUSD - (lastCost.get(key) ?? 0);
      lastCost.set(key, m.costUSD);
      const attrs = { tenant: tenantId, model, provider: m.provider ?? 'unknown', cost_basis: m.costBasis ?? 'list' };
      costUsd.add(delta, attrs);
    }
    tokensIn.add(msg.usage.input_tokens, { tenant: tenantId });
    tokensOut.add(msg.usage.output_tokens, { tenant: tenantId });
  }
}
```

Because `modelUsage` is cumulative (and now continues across resume), emit deltas rather than raw values when you count per turn.

---

## 13. Built-in Tools & Tool Authoring API

### 13.1 Built-in tools shipped in the box

`ToolInputSchemas` (sdk-tools.d.ts:11) lists the built-in tools. Core catalog:

| Tool | Purpose | Notes |
|---|---|---|
| `Bash` | Shell exec with `timeout`, `description`, `run_in_background` | `timeout` now bounds background commands; `timedOutAfterMs` when auto-backgrounded |
| `Read` (FileRead) | Read with line numbers, `offset`/`limit`, PDF `pages`, images | PDF content now arrives inside `tool_result` (CHANGELOG.md:301) |
| `Write` / `Edit` | Write file; anchor-based `old_string` → `new_string` with uniqueness check | Agent-aware (Edit fails fast on non-unique anchors) |
| `Glob` / `Grep` | Glob; ripgrep wrapper | **No longer default on native builds** — embedded `find`/`grep` in Bash instead; name them in `tools` to keep them (CHANGELOG.md:710) |
| `WebFetch` / `WebSearch` | Fetch URL with prompt; Anthropic-managed search | |
| `Agent` | Spawn a sub-agent (`isolation: 'worktree' | 'remote'`, `run_in_background`, `model`, `name`) | Background by default from the model's side |
| `Workflow` | **new** — run an `agent()/parallel()/pipeline()/phase()` orchestration script or a named workflow from `.claude/workflows/` | |
| `Monitor` | **new** — watch a command's stdout or a WebSocket; each line/frame is an event; 5–30 min deadline | Line-event streaming |
| `TaskCreate` / `TaskGet` / `TaskUpdate` / `TaskList` / `TaskStop`, `TodoWrite` | Task tracking | Not default on newer models (CHANGELOG.md:355, 165); `TaskOutput` removed |
| `CronCreate` / `CronDelete` / `CronList`, `ScheduleWakeup` | **new** — in-session scheduling | Local to the session/process |
| `RemoteTrigger` | **new** — manage Anthropic-hosted triggers/routines | claude.ai account |
| `AskUserQuestion` | HITL multiple-choice with `preview` (markdown or HTML via `toolConfig`) | |
| `ListMcpResources` / `ReadMcpResource` / `ReadMcpResourceDir` / `RefreshMcpTools` / `Mcp` | MCP resource and tool access | `ReadMcpResourceDir` new (CHANGELOG.md:598) |
| `NotebookEdit` | Jupyter cell edit (now returns `old_source`) | |
| `EnterPlanMode` / `ExitPlanMode` | Plan mode | `EnterPlanMode` new |
| `EnterWorktree` / `ExitWorktree` | Git worktree isolation | |
| `Skill` | Load a skill body on demand | |
| `Artifact`, `PushNotification`, `ReadNotifications`, `ProposeSkills`, `ProposeGoal`, `ReportFindings`, `SendFeedback`, `ClaudeDesign`, `Projects`, `ShowOnboardingRolePicker` | **new** — product-facing tools from Claude Code / claude.ai | Mostly irrelevant server-side; restrict with `tools` |

Quality: these are the same tools as Claude Code interactive mode. Agent-aware patterns: `Edit` anchor matching with uniqueness validation, `Read` with line numbers, `Bash` with a mandatory natural-language `description` (useful for audit), `Monitor` line-event streaming, `Skill` lazy loading, `Agent` worktree isolation. Still the strongest built-in catalog in the benchmark; the catalog also grew product tools a server deployment should switch off by passing an explicit `tools` list.

### 13.2 Tool authoring API

```ts
import { tool, createSdkMcpServer } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

const topicSearch = tool(
  'topicSearch',
  'Search the Predict topic catalog.',
  { query: z.string(), limit: z.number().optional() },   // Zod raw shape → JSON Schema + runtime validation
  async (args) => ({ content: [{ type: 'text', text: JSON.stringify(await predictApi.search(args.query, args.limit ?? 10)) }] }),
  { annotations: { readOnlyHint: true }, alwaysLoad: true },
);

const predictServer = createSdkMcpServer({ name: 'predict', tools: [topicSearch], timeout: 30_000 });
query({ prompt: '...', options: { mcpServers: { predict: predictServer } } });
```

- Model-visible name: `mcp__predict__topicSearch`.
- **Typed I/O**: Zod v3 or v4 raw shapes (`AnyZodRawShape`, sdk.d.ts:126); `zod ^4` is now a peer dependency. Invalid args produce an `is_error` result the model can correct. A tool whose schema cannot be converted to JSON Schema is now dropped with a warning instead of emptying the whole server (CHANGELOG.md:7).
- `timeout` per server (CHANGELOG.md:274); `searchHint` / `alwaysLoad` control tool-search deferral.

### 13.3 Streaming tools

**Partial.**

- `SDKToolProgressMessage` heartbeats (`elapsed_time_seconds`) for long calls, including `Agent` calls.
- Long `Bash`, MCP and `Agent` calls can be backgrounded; completion arrives as `task_notification` (with `resource_links` for MCP results).
- `Monitor` turns a process's stdout or a WebSocket into events the model sees as they arrive.
- **Mid-execution partial results from your own tool to the model: not supported.** An SDK MCP tool returns one `CallToolResult`. Issue #213 (stream Bash stdout/stderr to the client) is open.

### 13.4 Tool sandboxing / permission model

The full surface:

- **`PermissionMode`** (sdk.d.ts:2482): `'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'auto'` (+ `'manual'` alias for `'default'`, CHANGELOG.md:532). `'auto'` uses a model classifier and prompts through `canUseTool` when it cannot decide; `PostToolUse.classifierContext` lets the host feed it context. `'bypassPermissions'` needs `allowDangerouslySkipPermissions: true` (sdk.d.ts:2004). Per-MCP-server override: `setMcpPermissionModeOverride(server, 'default' | 'auto' | null)` (sdk.d.ts:2882).
- **`canUseTool`** (sdk.d.ts:213) with MCP provenance; **`PreToolUse`** with `permissionDecision`; **`PermissionRequest`** / **`PermissionDenied`** hooks.
- **`permissionPrompts: 'none'`** (sdk.d.ts:2018): no approval surface; anything that would prompt is denied immediately.
- **Rules**: `PermissionUpdate` (`addRules`, `replaceRules`, `removeRules`, `setMode`, `addDirectories`, `removeDirectories`) with destinations; `allowedTools` / `disallowedTools`; `McpServerToolPolicy` (sdk.d.ts:1288). `managedSettings.allowManagedPermissionRulesOnly` (sdk.d.ts:7215) ignores non-managed allow rules.
- **OS sandbox**: `Options.sandbox` (sdk.d.ts:2192; `SandboxSettings`, sdk.d.ts:3462) — OS-level filesystem and network restriction (`bubblewrap` on Linux; `query()` fails when the sandbox is enabled but unavailable, sdk.d.ts:2160-2192), with `network.strictAllowlist` (CHANGELOG.md:426) and credential masking/injection (`sandbox.credentials`, CHANGELOG.md:397, 540, 593). Issue #231 (cannot lock the sandbox to `cwd` for multi-user use) is open.
- **Sandbox providers**: no E2B / Daytona / Modal integration in the SDK. The hosting doc covers container sandboxing (Docker, gVisor, Firecracker; cookbook examples for Modal and Kubernetes).

**Default posture changed in 0.3.286.** With `permissionMode` omitted, the CLI picks the mode as `claude -p` does: a settings `permissions.defaultMode`, else **`auto`** where auto mode is available (third-party providers or telemetry off), else `default` (sdk.d.ts:1979-1992; CHANGELOG.md:10). Before 0.3.286 the TS SDK defaulted to `default` (ask via `canUseTool`). For server deployments: set `permissionMode` explicitly — `'default'` with `canUseTool`, or `'dontAsk'` / `permissionPrompts: 'none'` for default-deny of anything not pre-approved.

---

## 14. MCP (Model Context Protocol) Support

### 14.1 MCP client support

**First-class.** `Options.mcpServers` (sdk.d.ts:1955):

```ts
// sdk.d.ts:1213
export declare type McpServerConfig =
  | McpStdioServerConfig
  | McpSSEServerConfig
  | McpHttpServerConfig
  | McpSdkServerConfigWithInstance;
```

Also loaded from `.mcp.json` / settings / plugins (unless `strictMcpConfig`, `settingSources: []`, or `skipMcpDiscovery`). Since 0.3.221 servers in `options.mcpServers` are connected before the first turn (CHANGELOG.md:414); servers from settings/plugins connect in the background. MCP Apps: `mcpServerStatus()` tool entries carry `_meta` UI metadata and `readMcpResource()` (alpha) reads `ui://` resources (CHANGELOG.md:69-70).

### 14.2 MCP server support

`createSdkMcpServer` (sdk.d.ts:613) builds an **in-process** server visible only to this SDK's CLI subprocess; other processes cannot connect to it. To expose tools to other agents, write a standalone server with `@modelcontextprotocol/sdk`.

### 14.3 Transports

- **stdio** ✅
- **SSE** ✅
- **Streamable HTTP** ✅
- **In-process SDK** ✅ (`McpSdkServerConfigWithInstance`)
- **claude.ai proxy** — internal (`McpClaudeAIProxyServerConfig`, sdk.d.ts:1283)
- WebSocket — not in the public `McpServerConfig` union.

### 14.4 In-process MCP

**Yes — `createSdkMcpServer` + `tool()`.** No subprocess spawn; calls flow over the existing stdio control channel. Since 0.3.281 the in-process handshake runs inside the SDK, shortening startup (CHANGELOG.md:60). `toggleMcpServer()` now disconnects/re-enables in-process servers correctly (CHANGELOG.md:8). Provenance: these servers report `source: 'sdk'` in `canUseTool`, hook inputs and `mcpServerStatus()` (CHANGELOG.md:111).

### 14.5 Auth / lifecycle

- **stdio**: credentials via `env`. **HTTP/SSE**: `headers` or OAuth (with elicitation through `onElicitation`).
- **Reconnection**: `reconnectMcpServer()` (sdk.d.ts:3155); automatic reconnect after transport aborts; `mcp_status` now reports `pending` while reconnecting (CHANGELOG.md:299).
- **Health**: `mcpServerStatus()` (sdk.d.ts:3023) → `{ status: 'connected' | 'failed' | 'needs-auth' | 'pending' | 'disabled', source, … }`.
- **Startup**: background connect (0.3.142); `alwaysLoad: true` to require a server in turn 1; `CLAUDE_CODE_MCP_STARTUP_WAIT_MS` to bound the first-turn wait (CHANGELOG.md:112, 33).
- **Mid-session**: `setMcpServers()` (with per-server `request_timeout_ms`, CHANGELOG.md:545), `toggleMcpServer()`.
- **Timeouts**: `createSdkMcpServer({ timeout })` or `MCP_TOOL_TIMEOUT`.
- Open: #122 (concurrent SDK MCP connect timeouts), #219 (stdio MCP zombie processes after session end), #316 (sub-agent MCP resources).

---

## 15. Multi-model Routing & Fallback

### 15.1 Multi-provider support

Claude models only, through several hosting providers: `'firstParty' | 'bedrock' | 'vertex' | 'foundry' | 'anthropicAws' | 'anthropicGoogleCloud' | 'mantle' | 'gateway'` (`AccountInfo.apiProvider`, sdk.d.ts:32). Selection is by environment/settings, not an `Options` knob. `modelUsage[*].provider` reports which provider served each model (CHANGELOG.md:433). `Settings.allowedProviders` lets an admin restrict providers; a disallowed one fails startup with `startup_failure_reason: 'provider_not_allowed'` (CHANGELOG.md:16).

**No native OpenAI / Gemini / open-weight support.** Non-Claude models need a translating gateway, and CLI features (pricing, caching, refusal fallback) assume Claude. This remains the largest gap versus ADK / OpenAI Agents / Mastra / Vercel AI / LangGraph.

### 15.2 Automatic fallback chain

**Yes, single-step.** `Options.fallbackModel` (sdk.d.ts:1682). Since 0.3.174 SDK consumers receive `system/model_fallback` for every trigger — `overloaded`, `server_error`, `last_resort`, `model_not_found`, `permission_denied` (CHANGELOG.md:656). A separate **refusal fallback** retries a refused response on another model and reports `system/model_refusal_fallback` with `scope: 'session' | 'local'` (sdk.d.ts:5374). Not an N-model chain; retry policy is still not configurable (#313 open), though `CLAUDE_CODE_RETRY_WATCHDOG` adds unattended retry for usage-limit waits (CHANGELOG.md:72).

### 15.3 Mid-stream model switching

- **Per session**: `Options.model` (sdk.d.ts:1960).
- **Mid-session**: `Query.setModel()` (sdk.d.ts:2894) at a turn boundary; unknown ids are now confirmed with the API rather than refused (CHANGELOG.md:162). `PreModelSwitch` can allow/deny/ask based on the cache-rewarm cost; `PostModelSwitch` observes.
- **Per sub-agent**: see §9.8.
- Not within a single streamed response.

---

## 16. Chat UI Layer

### 16.1 Generative UI components

**Not provided — BYO.** Closest concepts: `AskUserQuestion` previews in HTML (`toolConfig.askUserQuestion.previewFormat: 'html'`, sdk.d.ts:9689) and MCP Apps `ui://` resources that a host can fetch with `readMcpResource()` and render.

### 16.2 Tool call rendering primitives

**Not provided — BYO components**, but the stream now carries UI-oriented sidecars: `tool_use_meta` (display names, `icon_url`), `tool_result_meta` (denied / interrupted / cancelled), `canUseTool` `title` / `displayName` / `description`, `background_tasks_changed` with `ambient` flags, and `resource_links`.

### 16.3 Streaming chat hook

**No React/Vue/Svelte hook.** `@anthropic-ai/claude-agent-sdk/browser` provides `query({ websocket | sse, … })` (browser-sdk.d.ts:126) returning the same `Query` async iterator in the browser, with SSE resume helpers (`getSseLastSequenceNum`, `fromSequenceNum`). Fixed in 0.3.257 for browsers without native `Symbol.dispose` (Safari/iOS, Firefox ESR) (CHANGELOG.md:234). You build the React state on top.

### 16.4 BYO pattern

1. Server: `query()` in an HTTP handler; stream `SDKMessage` JSON over SSE (with sequence ids) or WebSocket.
2. Client: the `/browser` client or your own `EventSource`; reduce frames into state by `type`/`subtype`.
3. Link `tool_use` / `tool_result` by `tool_use_id`; use `tool_use_meta` for labels.
4. Render `tool_progress`, `task_*` and `background_tasks_changed` as activity; `session_state_changed: requires_action` for pending approvals.

---

## 17. Memory & Knowledge

### 17.1 Long-term memory / semantic recall

**First-party, file-based.**

- Agent memory: `~/.claude/agent-memory/<agentType>/`, `.claude/agent-memory/<agentType>/`, `.claude/agent-memory-local/<agentType>/` per `AgentDefinition.memory` (sdk.d.ts:87); surfaced via `SDKMemoryRecallMessage` (sdk.d.ts:5267) with `mode: 'select' | 'synthesize'`.
- Auto memory: `~/.claude/projects/<project>/memory/`, loaded into the system prompt "regardless of `settingSources`" (hosting doc); disable with `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.
- `CLAUDE.md` files (user / project / local tiers), skipped per sub-agent with `omitClaudeMd`.

No vector index. For semantic recall over your data, BYO via an MCP tool. Open issues #99 (session memory for SDK sessions) and #360 (auto-memory writes with a sandbox) show the SDK path is still less complete than the interactive CLI.

### 17.2 RAG / knowledge retrieval integration

**Not provided — BYO** via MCP (vector store, retriever, citations). Tool results can carry `resource_link` blocks surfaced to hosts.

### 17.3 Per-tenant memory scoping

**Not natural; now documented.** Memory lives under the config dir and the project directory. The hosting doc's recipe — per-tenant `cwd`, per-tenant `CLAUDE_CONFIG_DIR`, `settingSources: []`, auto memory disabled — is what keeps one tenant's memory out of another's session. Per-tenant long-term memory in a database is BYO through an MCP tool.

---

## 18. Safety & Policy

### 18.1 Input/output guardrails

**Not first-party** for PII redaction, prompt-injection detection or hallucination detection. Implement with `UserPromptSubmit` (block/rewrite input), `PreToolUse` (validate args), `PostToolUse.updatedToolOutput` (redact results) and `MessageDisplay` (rewrite displayed text — display only). Related built-ins that are not guardrails in the benchmark sense: the `auto` permission classifier (judges tool calls, not content), refusal handling (`stop_reason: "refusal"` with `stop_details`, CHANGELOG.md:709; refusal fallback), and sandbox credential masking. Tool sandboxing and the default posture are covered in §13.4.

---

## 19. Eval, Testing & CI Gates

### 19.1 Golden datasets / regression suites

**Not provided — BYO.** The only test-shaped artifact in the repo is the `SessionStore` conformance suite (`examples/session-stores/shared/conformance.ts`, 13 contracts) — adapter conformance, not agent regression.

### 19.2 LLM-as-judge scoring

**Not provided — BYO.**

### 19.3 CI eval gates / pre-merge

**Not provided — BYO.** The repo's own CI now runs a workflow-hardening check (`.github/workflows/workflow-hardening.yml`, `.github/scripts/check_workflow_hardening.py`) for jobs that call Claude (egress-firewall runner, allow list, `--permission-mode auto`), which is a reference for running agents in CI safely, not an eval gate.

### 19.4 Trace replay for skill iteration

JSONL transcripts are replayable with `query({ options: { resume, resumeSessionAt } })`; `getSessionMessages()` / `getSubagentMessages()` read them; `forkSession()` branches from a point. Replay re-calls the model, so it is not deterministic. No first-party trace viewer; OTel traces go to whatever backend you export to.

---

## 20. Local Sandbox & Dev UX

### 20.1 Local agent runner

The bundled `claude` binary is the interactive Claude Code CLI — a full local runner for the same skills, agents, hooks (settings-defined) and MCP config. For SDK code: run your script with `bun` or `node --import tsx`; no playground or web dev UI.

### 20.2 Trace inspection

Local JSONL under `~/.claude/projects/<cwd-sanitized>/<sessionId>.jsonl` (`jq`, or `claude --resume` in the CLI). With OTel enabled, any trace UI (Jaeger, Honeycomb, Datadog). `/context` results now carry a structured `context_usage` payload (CHANGELOG.md:360).

### 20.3 Tenant / org switching

Change `cwd`, `CLAUDE_CONFIG_DIR`, `settings`/`managedSettings` and `env` per `query()`. No tenant switcher UI.

### 20.4 Hot reload

- **Skills**: `Query.reloadSkills()` and `SessionStart` `reloadSkills: true` (new) — skills can now change without restarting the session.
- **Plugins**: `reloadPlugins()` (optionally holding a reload that would break the prompt cache).
- **Output styles**: `reloadOutputStyles()`.
- **Settings**: `applyFlagSettings()`, `updateSettings()`; `agent` switches live (CHANGELOG.md:715).
- **MCP servers**: `setMcpServers()`, `toggleMcpServer()`.
- **System prompt**: a custom prompt change applies at the next compaction when recorded (`snapshot`, CHANGELOG.md:171); otherwise restart.
- **Sub-agent definitions** in `Options.agents`: restart the query.

No file watcher on skill directories by default; wire `FileChanged` + `watchPaths` and call `reloadSkills()` yourself.

---

## Architectural diagram

```mermaid
flowchart LR
  subgraph CLIENT[Browser / Mobile Client]
    UI[Your UI<br/>React / Svelte / Native]
    BSDK["@anthropic-ai/claude-agent-sdk/browser<br/>(WebSocket or SSE)"]
    UI --> BSDK
  end

  subgraph GW[Your gateway]
    AUTH[Auth / tenant extraction]
  end

  subgraph SERVER[Your Node/Bun/Deno Server]
    HTTP[Your HTTP / WS route handler]
    SDK["@anthropic-ai/claude-agent-sdk (or /core)<br/>query / startup / prewarm / tool / createSdkMcpServer"]
    HOOKS[Hooks: 33 events<br/>PreToolUse / PostToolUse / SessionStart / …]
    SDKMCP[In-process SDK MCP<br/>tool() handlers run here]
    STORE[(SessionStore<br/>Postgres / Redis / S3 adapter)]
    TENANTFS[Per-tenant dirs<br/>cwd, CLAUDE_CONFIG_DIR, plugin/skills]

    HTTP --> SDK
    SDK -.callback.-> HOOKS
    SDK -.in-process MCP.-> SDKMCP
    SDK -.mirror append.-> STORE
  end

  subgraph SUBPROCESS[Claude Code Subprocess — one per session]
    CLI[Native binary<br/>225–242 MB per platform]
    LOOP[Run loop:<br/>tool dispatch, permissions + auto classifier,<br/>compaction, skills, sub-agents, workflows, cron]
    FS["JSONL transcripts<br/>skills / agents / plugins<br/>agent-memory / auto memory"]
    SUBAGENT[Sub-agents<br/>(Agent tool, depth 1, ≤20 concurrent)]
    SANDBOX[bubblewrap sandbox<br/>(optional)]

    CLI --> LOOP
    LOOP --> FS
    LOOP -.fan-out.-> SUBAGENT
    LOOP -.optional.-> SANDBOX
  end

  subgraph EXT[External Services]
    ANT[Anthropic API<br/>or Bedrock / Vertex / Foundry / gateway]
    MCP[External MCP servers<br/>stdio / SSE / HTTP]
    MKT[Plugin marketplaces<br/>GitHub / git / npm / URL / zip<br/>(settings tier)]
    OTEL[OTLP collector]
    CCR[claude.ai Remote Control<br/>(optional, alpha)]
  end

  BSDK --> AUTH --> HTTP
  SDK -- "spawn native binary<br/>stdio stream-json<br/>control: can_use_tool / hook_callback / mcp_message" --> CLI
  TENANTFS --- FS
  CLI -- HTTPS --> ANT
  CLI -- "stdio / SSE / HTTP" --> MCP
  CLI -. install .-> MKT
  CLI -. OTLP .-> OTEL
  SDK <-. "attachBridgeSession (alpha)" .-> CCR
```

---

## Appendix — Files worth reading first

- **`frameworks/claude-agent-sdk-typescript/CHANGELOG.md`** — the only product history in the repo. Lines 1–800 cover 0.3.143 → 0.3.286 (permission default change at line 10, `prewarm` at 49, MCP provenance at 111, `usage` vs `modelUsage` at 405, sub-agent caps at 437-438); line 922 is the 0.2.113 switch to native binaries.
- **`frameworks/claude-agent-sdk-typescript/examples/session-stores/postgres/src/PostgresSessionStore.ts`** — production-shaped `SessionStore` adapter.
- **`frameworks/claude-agent-sdk-typescript/examples/session-stores/shared/conformance.ts`** — the 13 contracts a `SessionStore` must satisfy.
- **`frameworks/claude-agent-sdk-typescript/examples/session-stores/redis/src/RedisSessionStore.ts`** and **`.../s3/src/S3SessionStore.ts`** — Redis and append-only S3 variants.
- **`frameworks/claude-agent-sdk-typescript/examples/session-stores/README.md`** — per-backend production checklist.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/sdk.d.ts`** (0.3.286, 9,890 lines) — start at `Options` (line 1519), `Query` (2844), `prewarm`/`SpareProcess` (2823, 9306), `SDKMessage` (5292), `SDKResultSuccess` (5691), `ModelUsage` (1430), `SessionStore` (6482), `HOOK_EVENTS` (957), `CanUseTool` (213).
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/sdk-tools.d.ts`** — built-in tool I/O shapes; `ToolInputSchemas` (line 11), `AgentInput` (763), `WorkflowInput` (2848), `CronCreateInput` (2880), `MonitorInput` (2950).
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/browser-sdk.d.ts`** — browser client with WebSocket/SSE transports and SSE resume helpers.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/core.d.ts`** — the slimmer entry point's export list.
- **`<node_modules>/@anthropic-ai/claude-agent-sdk/manifest.json`** — per-platform binary sizes (225–242 MB), the key sizing fact.
- **https://code.claude.com/docs/en/agent-sdk/hosting** — vendor sizing, session patterns and the multi-tenant isolation recipe.
