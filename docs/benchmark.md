# Stack Choice: Where the Agent Loop Lives

> Generated on 2026-10-01 from 19 framework reports under `docs/reports/`. This is a refresh of the 2026-05-19 benchmark: every framework submodule was moved to its upstream `main` HEAD as of 2026-10-01, each report was updated against that delta, and scores were re-calibrated against the previous matrix (305 of 1767 cells changed). The taxonomy is unchanged.
> Canonical data lives in [`data/`](data/) (`taxonomy.csv`, `sections.csv`, `frameworks.csv`, `scores.csv`).

The benchmark targets **a long-running, skills-piloted agent exposed to external clients**, where the runtime — not the LLM — picks the tool set available to each tenant, scopes the skill library to that tenant, and injects tenant identity into tool calls server-side. Calibration favors first-party support over BYO glue.

## Score legend

| Score | Meaning |
| ----- | ------- |
| `0` | No support. |
| `1` | Minimal primitive, large host effort. |
| `2` | Partial primitive, mostly host-built. |
| `3` | Usable support with meaningful gaps. |
| `4` | Strong support with minor gaps. |
| `5` | First-class fit for the benchmark. |
| `?` | Applicable, but generated report lacks evidence. |
| blank | Not applicable to that stack. |

A first-party capability that is explicitly labelled experimental, alpha, beta, canary or provisional — or that ships in a 0.x satellite package next to a stable core, or exists only in unreleased commits — is scored on capability and capped at `4`. A framework's overall 0.x version number does not trigger the cap; it is reflected in the General section only.

## Category × Framework heatmap

Legend: 🟥 mean < 2.0 · 🟨 2.0–3.5 · 🟩 ≥ 3.5 · ⬜ not applicable.

| Category | ADK Go | Agno | AutoAgents | Claude Py | Claude TS | CrewAI | Eino | Genkit | LangGraph | LlamaIndex | Mastra | MS AF | OAI Py | OAI TS | Pydantic | Rig | Strands Py | Strands TS | Vercel AI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0. General | 🟩 3.8 | 🟩 4.2 | 🟨 2.0 | 🟩 3.8 | 🟩 3.5 | 🟩 4.5 | 🟩 3.5 | 🟩 3.8 | 🟩 4.5 | 🟩 4.5 | 🟩 4.0 | 🟩 4.5 | 🟩 4.0 | 🟩 3.8 | 🟩 5.0 | 🟨 2.2 | 🟩 4.0 | 🟩 3.5 | 🟩 4.5 |
| 1. Architecture | 🟩 4.3 | 🟩 4.0 | 🟨 3.4 | 🟨 2.1 | 🟨 2.3 | 🟩 4.1 | 🟩 4.1 | 🟩 4.0 | 🟩 3.6 | 🟩 3.6 | 🟩 4.1 | 🟩 4.4 | 🟩 4.1 | 🟩 3.9 | 🟩 4.3 | 🟩 4.0 | 🟩 3.7 | 🟩 3.7 | 🟩 4.0 |
| 2. Chat UI | 🟥 1.3 | 🟨 2.0 | 🟥 0.0 | 🟥 0.3 | 🟥 1.7 | 🟨 2.3 | 🟥 0.3 | 🟥 1.3 | 🟥 1.7 | 🟥 1.7 | 🟩 4.0 | 🟨 3.3 | 🟥 0.0 | 🟨 3.0 | 🟩 3.7 | 🟥 0.0 | 🟥 0.3 | 🟥 0.0 | 🟩 5.0 |
| 3. HTTP API | 🟩 3.7 | 🟩 4.8 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟥 0.8 | 🟥 0.0 | 🟩 3.7 | 🟩 5.0 | 🟥 1.2 | 🟩 4.8 | 🟩 3.7 | 🟥 0.0 | 🟥 0.0 | 🟨 2.7 | 🟥 0.0 | 🟥 0.8 | 🟥 0.3 | 🟨 3.0 |
| 4. Agent Runtime | 🟩 3.5 | 🟩 5.0 | 🟥 0.8 | 🟨 2.5 | 🟨 2.2 | 🟥 1.5 | 🟨 2.0 | 🟨 2.8 | 🟩 4.8 | 🟥 1.5 | 🟩 4.8 | 🟩 4.0 | 🟨 2.2 | 🟥 1.8 | 🟨 2.5 | 🟥 1.5 | 🟨 2.2 | 🟨 2.2 | 🟨 2.0 |
| 5. Sessions & Persistence | 🟨 3.0 | 🟩 3.7 | 🟥 0.7 | 🟩 3.8 | 🟩 3.7 | 🟩 3.5 | 🟥 1.5 | 🟨 2.8 | 🟩 5.0 | 🟨 2.3 | 🟩 3.5 | 🟨 3.3 | 🟩 4.2 | 🟨 2.5 | 🟨 2.8 | 🟨 2.3 | 🟨 2.8 | 🟨 2.8 | 🟥 0.8 |
| 6. Agent Loop | 🟩 4.8 | 🟩 4.8 | 🟩 4.8 | 🟩 4.2 | 🟩 4.4 | 🟩 4.0 | 🟩 4.4 | 🟩 4.0 | 🟩 4.4 | 🟩 4.8 | 🟩 4.8 | 🟩 3.8 | 🟩 5.0 | 🟩 5.0 | 🟩 4.8 | 🟩 4.2 | 🟩 4.8 | 🟩 4.8 | 🟩 4.6 |
| 7. Multi-Model | 🟥 1.0 | 🟩 5.0 | 🟩 4.5 | 🟨 2.0 | 🟨 2.0 | 🟨 3.0 | 🟩 4.0 | 🟩 4.5 | 🟩 4.0 | 🟨 3.0 | 🟩 5.0 | 🟨 2.5 | 🟨 3.0 | 🟨 2.5 | 🟩 5.0 | 🟨 3.0 | 🟩 5.0 | 🟩 4.0 | 🟩 4.0 |
| 9. Context Engineering | 🟨 3.2 | 🟩 3.8 | 🟥 1.0 | 🟩 4.3 | 🟩 4.7 | 🟨 3.3 | 🟩 4.8 | 🟨 2.0 | 🟨 3.0 | 🟨 2.2 | 🟩 4.2 | 🟩 4.2 | 🟨 3.3 | 🟨 3.2 | 🟩 4.3 | 🟨 3.2 | 🟩 4.8 | 🟩 4.8 | 🟨 2.8 |
| 10. Memory & Knowledge | 🟨 2.7 | 🟩 4.3 | 🟨 2.0 | 🟨 2.3 | 🟨 2.3 | 🟩 4.3 | 🟨 2.3 | 🟨 2.3 | 🟩 4.0 | 🟩 3.7 | 🟩 5.0 | 🟨 3.3 | 🟨 2.0 | 🟨 2.0 | 🟨 2.7 | 🟨 2.3 | 🟨 2.7 | 🟨 2.7 | 🟥 0.7 |
| 11. Skills | 🟩 4.8 | 🟩 4.8 | 🟥 0.0 | 🟩 3.8 | 🟩 3.8 | 🟩 4.0 | 🟩 5.0 | 🟩 3.5 | 🟥 0.0 | 🟥 0.0 | 🟩 4.8 | 🟩 4.8 | 🟩 3.8 | 🟩 4.0 | 🟩 3.5 | 🟥 0.0 | 🟩 4.8 | 🟩 4.8 | 🟨 3.0 |
| 12. Sub-agents | 🟩 3.7 | 🟩 3.9 | 🟨 3.1 | 🟩 4.6 | 🟩 4.7 | 🟨 3.1 | 🟩 3.7 | 🟨 3.4 | 🟨 3.4 | 🟩 3.7 | 🟩 4.6 | 🟨 3.4 | 🟩 3.9 | 🟩 3.9 | 🟩 4.0 | 🟨 2.7 | 🟩 4.7 | 🟩 4.6 | 🟨 2.3 |
| 13. Resource Manager | 🟥 1.3 | 🟨 2.6 | 🟥 0.1 | 🟥 1.3 | 🟥 1.7 | 🟨 2.6 | 🟥 1.0 | 🟥 1.0 | 🟥 1.0 | 🟥 0.1 | 🟨 3.4 | 🟥 1.6 | 🟥 0.9 | 🟥 1.1 | 🟥 1.6 | 🟥 0.3 | 🟥 1.0 | 🟥 1.0 | 🟥 0.1 |
| 14. Tools | 🟨 2.2 | 🟩 4.0 | 🟨 2.0 | 🟩 3.5 | 🟩 4.2 | 🟨 3.0 | 🟩 3.5 | 🟨 3.2 | 🟨 2.8 | 🟨 2.5 | 🟩 4.5 | 🟨 3.2 | 🟩 3.5 | 🟨 3.2 | 🟩 4.0 | 🟥 1.5 | 🟩 4.5 | 🟩 3.8 | 🟩 4.0 |
| 15. MCP | 🟨 3.2 | 🟩 4.8 | 🟨 3.0 | 🟩 4.5 | 🟩 4.5 | 🟨 3.2 | 🟩 3.5 | 🟩 4.2 | 🟩 3.8 | 🟩 4.5 | 🟩 4.5 | 🟩 4.5 | 🟨 3.2 | 🟩 3.5 | 🟩 3.8 | 🟨 2.8 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 |
| 16. Safety & Policy | 🟥 0.0 | 🟩 5.0 | 🟩 5.0 | 🟥 0.0 | 🟥 0.0 | 🟨 3.0 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟥 1.0 | 🟩 5.0 | 🟩 4.0 | 🟩 4.0 | 🟩 4.0 | 🟩 4.0 | 🟥 0.0 | 🟨 3.0 | 🟨 3.0 | 🟥 0.0 |
| 17. Observability | 🟩 4.5 | 🟩 4.5 | 🟨 3.0 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟨 3.0 | 🟨 3.0 | 🟩 3.5 | 🟩 4.0 | 🟩 3.5 | 🟩 3.5 | 🟨 3.0 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 |
| 18. Cost & Usage | 🟥 1.7 | 🟨 3.0 | 🟥 1.0 | 🟩 4.0 | 🟩 4.3 | 🟨 2.0 | 🟥 1.3 | 🟥 1.7 | 🟥 1.3 | 🟥 1.3 | 🟩 4.3 | 🟥 1.7 | 🟨 2.3 | 🟥 1.7 | 🟩 4.7 | 🟨 2.0 | 🟨 2.0 | 🟨 2.0 | 🟨 3.3 |
| 19. Multi-tenancy | 🟨 3.2 | 🟩 3.5 | 🟥 1.0 | 🟨 3.0 | 🟨 3.0 | 🟥 1.5 | 🟨 3.0 | 🟨 3.0 | 🟩 4.2 | 🟨 2.5 | 🟩 4.3 | 🟨 3.0 | 🟩 3.8 | 🟩 3.8 | 🟩 4.5 | 🟩 3.8 | 🟨 3.0 | 🟩 3.5 | 🟩 4.0 |
| 20. Eval / testing | 🟥 0.0 | 🟩 4.7 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟨 2.0 | 🟥 0.0 | 🟨 2.7 | 🟥 0.0 | 🟩 3.7 | 🟩 4.7 | 🟨 3.0 | 🟥 0.7 | 🟥 0.7 | 🟩 4.3 | 🟥 1.3 | 🟩 4.0 | 🟥 0.3 | 🟥 1.3 |
| 21. Local sandbox / dev UX | 🟨 2.5 | 🟩 3.5 | 🟥 0.8 | 🟨 3.2 | 🟨 3.0 | 🟨 2.0 | 🟥 1.2 | 🟨 3.2 | 🟩 3.5 | 🟥 0.5 | 🟩 4.8 | 🟩 3.5 | 🟥 1.8 | 🟥 0.8 | 🟨 2.8 | 🟥 0.8 | 🟥 1.8 | 🟥 1.8 | 🟨 2.0 |
| **Overall mean** | **🟨 3.02** | **🟩 3.99** | **🟥 1.70** | **🟨 2.86** | **🟨 2.99** | **🟨 2.91** | **🟨 2.66** | **🟨 2.97** | **🟨 3.22** | **🟨 2.46** | **🟩 4.35** | **🟨 3.49** | **🟨 2.87** | **🟨 2.74** | **🟩 3.65** | **🟨 2.10** | **🟨 3.18** | **🟨 2.96** | **🟨 2.79** |

Regenerate this table with `python3 .agents/skills/create-benchmark/scripts/render_heatmap.py --data-dir docs/data` whenever `scores.csv` changes.

## Frameworks analysed

19 frameworks, analysed at HEAD on `main` on 2026-10-01:

- **Python** — Agno, Claude Agent SDK, CrewAI, LangGraph, LlamaIndex, OpenAI Agents, Pydantic AI, Strands Agents
- **TypeScript** — Claude Agent SDK, Mastra, OpenAI Agents, Strands Agents, Vercel AI SDK
- **Go** — ADK, Eino, Genkit
- **Rust** — AutoAgents, Rig
- **Multi-language** — Microsoft Agent Framework (Python + .NET)

See `data/frameworks.csv` for commit hashes, versions and report paths.

## What changed since 2026-05-19

- **Repository moves.** Strands Agents TypeScript moved from the archived `strands-agents/sdk-typescript` into the `strands-agents/harness-sdk` monorepo (renamed from `sdk-python`), so both Strands SDKs are now analysed from one submodule. Genkit moved from `firebase/genkit` to `genkit-ai/genkit`.
- **Major versions.** ADK Go v1 → v2.5, Agno v2 → v3, Pydantic AI v1 → v2.52, Vercel AI SDK v7 went stable, Microsoft Agent Framework Python 1.4 → 1.19 / .NET 1.23, Rig 0.37 → 0.43.
- **Corrections.** Several May claims were wrong at the May commits and are fixed in both reports and scores, notably: CrewAI did execute parallel tool calls; the LangGraph server (`langgraph-api`) is source-available under ELv2, not closed-source; Claude Agent SDK TypeScript is proprietary, not MIT; Agno never computed USD cost itself; OpenAI Agents JS tool guardrails cannot rewrite tool arguments; the May ADK Go tenant example stored tenant id in shared `app:` state.
- **Biggest movers.** Rig (+0.52), Pydantic AI (+0.51), Strands Python (+0.40), Vercel AI (+0.38), Genkit Go (+0.35). No framework's overall mean went down.

## Executive conclusions

1. **The two architectural shapes are unchanged.** Every framework still runs the agent loop in your process except Claude Agent SDK Python and TypeScript, which drive the bundled Claude Code binary. That shape still carries the richest hook surface and first-party USD cost tracking, at the cost of a ~1 GiB-per-session sizing floor and filesystem-shaped tenancy. Since 0.3.286 the TypeScript SDK may start sessions in `auto` permission mode when `permissionMode` is omitted, so servers must set it explicitly.

2. **"Harness" layers are the trend of this period.** Pydantic AI (`pydantic-ai-harness`, 0.x), Strands (`create_harness()`, beta), Vercel AI (`HarnessAgent`, experimental) and Microsoft Agent Framework (now stable) all ship a first-party layer bundling skills, sub-agents, sandboxes, persistence and budgets on top of the core loop. Most of these are pre-stable, which the maturity cap keeps at `4`; expect scores to rise further as they stabilise.

3. **Multi-tenancy remains the biggest separator, and the field is narrowing.** Pydantic AI (4.5), Mastra (4.3), LangGraph (4.2) and Vercel AI (4.0) lead; OpenAI Agents Python/TS and Rig follow at 3.8. Rig is the largest mover (1.0 → 3.8) thanks to its new `AgentHook` (tool-argument rewrite) and typed per-run `ToolContext`. Per-tenant USD budget caps are now first-party in Mastra (`TokenCostControl`) and Pydantic AI (harness `SpendLimits`). CrewAI (1.5) and AutoAgents (1.0) remain the weakest.

4. **Skills spread further.** Only AutoAgents, LangGraph, LlamaIndex and Rig still score 0 across Skills. Eino (5.0) still leads; ADK Go, Agno, Mastra, Microsoft Agent Framework and both Strands SDKs sit at 4.8. Vercel AI moved 0 → 3.0, but only through the experimental `HarnessAgent`; its core `ToolLoopAgent` still has no skill loader.

5. **Resource Manager is still the least developed capability.** Mastra (3.4) leads, followed by Agno and CrewAI (2.6, CrewAI via its AMP Skills Repository client). Everything else sits at 0.1–1.7: there is still no common publish workflow, lifecycle, or per-tenant RBAC for prompts, skills and tools.

6. **Sessions & Persistence still has one clear winner.** LangGraph scores 5.0; OpenAI Agents Python (4.2), Claude Agent SDK Python (3.8), Agno and Claude Agent SDK TypeScript (3.7) follow. Crash-resumable runs are no longer rare: Agno (`checkpoint="tool-batch"`), Mastra (`DurableAgent.recover()`), Eino (cancel with resumable checkpoint) and Strands (experimental checkpoints) all added them. Vercel AI (0.8) is still at the bottom.

## Top recommended stacks

Aggregate mean across all scored numeric cells (label-only rows `Ecosystem / primary language` and `Stack type` are excluded):

| Rank | Framework | Mean (May) | Strongest sections |
| --- | --- | --- | --- |
| 1 | **Mastra TypeScript** | 4.35 (4.11) | Multi-Model (5.0), Memory (5.0), HTTP API (4.8), Agent Runtime (4.8), Skills (4.8), Local sandbox (4.8) |
| 2 | **Agno Python** | 3.99 (3.75) | Agent Runtime (5.0), Multi-Model (5.0), Safety & Policy (5.0), HTTP API (4.8), MCP (4.8), Skills (4.8) |
| 3 | **Pydantic AI** | 3.65 (3.14) | General (5.0), Multi-Model (5.0), Agent Loop (4.8), Cost & Usage (4.7), Multi-tenancy (4.5) |
| 4 | **Microsoft Agent Framework** | 3.49 (3.35) | Skills (4.8), MCP (4.5), Architecture (4.4), Context Engineering (4.2), Agent Runtime (4.0) |
| 5 | **LangGraph Python** | 3.22 (3.20) | Sessions (5.0), HTTP API (5.0), Agent Runtime (4.8), Multi-tenancy (4.2) |
| 6 | **Strands Agents Python** | 3.18 (2.78) | Multi-Model (5.0), Context Engineering (4.8), Skills (4.8), Sub-agents (4.7), Tools (4.5) |

Honourable mentions:

- **ADK Go** (3.02) — still the only in-process Go loop with a bundled REST/SSE/WS/A2A server, which now has pluggable authentication and a strict user authorizer (v2.4+). Skills 4.8, Observability 4.5.
- **Claude Agent SDK TypeScript** (2.99) — Context Engineering (4.7), Sub-agents (4.7), MCP (4.5), Cost & Usage (4.3).
- **Genkit Go** (2.97) — new experimental Agents API with per-tenant session stores, HTTP routes for abort/resume/approval, and built-in delegation.
- **Strands Agents TypeScript** (2.96) — near feature parity with the Python SDK in the shared monorepo; middleware, model routing, memory manager and Cedar policies landed since May.

## Major disqualifiers and high-risk gaps

- **AutoAgents** (1.70) still requires substantial BYO: no sessions store, no skills, no resource manager, no HTTP API. **Rig** (2.10) improved the most but still has no HTTP API, skills, resource manager, or built-in provider fallback.
- **Vercel AI SDK** (2.79) is still library-first: no session store (0.8) and no memory layer (0.7). Skills and sub-agents exist only through the experimental `HarnessAgent`, which hands the loop to an external runtime in a sandbox.
- **LangGraph OSS** is excellent at the runtime layer, but the HTTP / queue / replay layer is `langgraph-api` (now "LangSmith Deployment"): source-available under ELv2, not in this repo, and licence-key gated in production. Pure OSS deployment means BYO server + auth + queue.
- **CrewAI** (2.91) has no tenant field, no server-side forced tool arguments, no budget cap and no cancel API in OSS (Multi-tenancy 1.5); its HTTP serving is third-party or the paid AMP platform.
- **LlamaIndex** (2.46): the README now says the company's primary focus has shifted to LlamaParse, and commit activity dropped by roughly 70% since Q1. Treat it as maintenance-mode for agent use.
- **Claude Agent SDK Python / TypeScript**: filesystem-shaped tenancy (`.claude/` directories under per-tenant `cwd`), no first-party HTTP server, ~1 GiB RAM per session, and a proprietary bundled CLI. Hook-based tenant enforcement needs Python SDK ≥ 0.2.160 (background sub-agents could bypass `PreToolUse` before 0.2.127).

## Open questions

No `?` cells remain. Known evidence caveats, recorded in the affected cells' `details`:

- Some capabilities exist only in unreleased commits on `main` at analysis time (Agno 3.1 authz/audit, several OpenAI Agents JS changesets, some Strands TS features ahead of npm 1.19.0); they are capped at `4`.
- Microsoft Agent Framework's Durable Task / Azure Functions hosting moved to `microsoft/agent-framework-durable-extension` (preview); it was assessed from its README and releases, not source.
- Claude Agent SDK Python parity with the TypeScript SDK on CLI-side features (memory, scheduled tasks, hosting patterns) relies on the shared bundled CLI and the SDK options that pass settings through.

## Notes on methodology

- 2026-10-01 refresh: one `analyse-ai-framework` sub-agent per framework updated its existing report against the OLD..NEW commit delta (changelogs, GitHub Releases, migration guides), re-verified every citation in changed files, and restructured each report to the current question bank.
- One `score-benchmark-category` sub-agent per taxonomy section then re-scored row by row across all 19 frameworks, starting from the May scores and changing a cell only where the refreshed report gave new evidence or corrected an old claim. A final calibration pass resolved cross-framework inconsistencies the section workers flagged.
- Canonical CSVs sort by `(section_order, section, row)` from `taxonomy.csv`, then framework order from `frameworks.csv`.
- `data/evidence.csv` is a legacy artefact from the first benchmark run. It is not read by the viewer and its line references were not refreshed.
