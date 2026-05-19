# Stack Choice: Where the Agent Loop Lives

> Generated on 2026-05-19 from 19 framework reports under `docs/reports/`. The taxonomy was refactored: section 6 "Agent Harness" → "Agent Loop" with its multi-model rows pulled out into a new section 7 "Multi-Model"; section 17 "Agent Observability" → "Observability" with token/cost rows pulled out into a new section 18 "Cost & Usage". Multi-tenancy renumbered 18 → 19; Eval / testing 19 → 20; Local sandbox 20 → 21.
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

## Frameworks analysed

19 frameworks, analysed at HEAD on `main` (analysed date 2026-05-19):

- **Python** — Agno, Claude Agent SDK, CrewAI, LangGraph, LlamaIndex, OpenAI Agents, Pydantic AI, Strands Agents
- **TypeScript** — Claude Agent SDK, Mastra, OpenAI Agents, Strands Agents, Vercel AI SDK
- **Go** — ADK, Eino, Genkit
- **Rust** — AutoAgents, Rig
- **Multi-language** — Microsoft Agent Framework (Python + .NET)

See `data/frameworks.csv` for commit hashes and report paths.

## Executive conclusions

1. **Two architectural shapes dominate.** Almost every framework runs the agent loop **in-process** in your own server. The two outliers are Claude Agent SDK Python and Claude Agent SDK TypeScript, which subprocess the bundled Claude Code Node binary — meaning the actual loop runs in Node, not in your runtime. Pick this shape consciously: it ships the richest hook surface and first-party USD cost enforcement, but costs you a ~200 MB platform binary and ~1 GB/session RAM ceiling.

2. **Multi-tenancy is the single biggest separator for our use case.** Mastra, Pydantic AI, and LangGraph remain the top three on the 8-row Multi-tenancy section. They are the only stacks that combine typed run-loop context, server-controlled tenant fields, per-turn visible-tool filtering, and a first-class "force tool args server-side" hook in one place. LangGraph's `InjectedToolArg` (strip-and-replace), Pydantic AI's `before_tool_validate`, and the Claude Agent SDKs' `PreToolUse.updatedInput` / `can_use_tool` are the strongest forced-args mechanisms; every other stack requires reading tenant from context inside the tool body and excluding tenant from the LLM-visible schema.

3. **The new "Multi-Model" section is the most uniformly strong category.** With model routing/fallback split out from Agent Loop, the gap between leaders and laggards narrows: Pydantic AI scores 5.00 (FallbackModel + callable model_settings + per-sub-agent override), with Mastra, Agno, LangGraph, and Vercel AI all at 4.75. Only the Claude Agent SDKs (Anthropic-only) and a handful of single-provider Rust libraries score below 4. Multi-provider support is essentially table stakes.

4. **The new "Cost & Usage" section is the most uniformly weak category.** With token/cost rows split off from Observability, the gap surfaces clearly: only Pydantic AI, Agno, and Claude Agent SDK TS reach 4.00; everyone else sits at 1–3. No framework rolls up cost per tenant or conversation natively (best is 3 — Pydantic AI Gateway + Vercel AI Gateway). USD computation is shipped by exactly four frameworks (Agno, Claude Py/TS, Pydantic AI). Treat per-tenant cost rollup as known glue work.

5. **Skills as a runtime concept are still rare.** Several frameworks score 0 across the entire Skills section (AutoAgents, LangGraph, LlamaIndex, Rig). The strongest first-class implementations are **Mastra** (5.00 — only stack with `SkillsResolver(ctx)` runtime scoping and a built-in `skill_search`), **Microsoft Agent Framework** (4.60 — `SkillsSource` / `AggregatingSkillsSource` / `FilteringSkillsSource` chain), and **Agno** (4.20). The Claude Agent SDKs score 3.4–3.6 — the canonical SKILL.md surface lives in the CLI, not in the SDK source.

6. **Resource Manager is the most underdeveloped capability in the benchmark.** Only **Mastra** breaks 3.0 (3.50 mean) thanks to `VersionedSkillSource` + `CompositeVersionedSkillSource` + content-hashed blob refs. Everyone else is 0–2.5 — no publish workflow, no draft/active/deprecated lifecycle, no RBAC. Closed-source paid platforms (LangGraph Platform, CrewAI AMP) cover some of this but are scored conservatively against the OSS surface.

7. **Durable mid-run checkpointing has one clear winner.** **LangGraph** scores 4.83 mean across the entire Sessions & Persistence section (per-task `put_writes` in `_runner.py:574-613`). The Claude Agent SDKs follow at 3.67 thanks to their reference Postgres/Redis/S3 `SessionStore` adapters and conformance harness. Most other stacks restrict durability to HITL pauses or leave persistence BYO.

## Top recommended stacks

Aggregate mean across all 98 scored rows (each framework has 98 numeric cells; the 2 label-only rows — `Ecosystem / primary language` and `Stack type` — are excluded from the mean):

| Rank | Framework | Mean | Strongest for the use case |
| --- | --- | --- | --- |
| 1 | **Mastra TypeScript** | 4.12 | Skills (5.00), Agent Loop (5.00), Memory (5.00), HTTP API (4.86), Multi-Model (4.75) |
| 2 | **Agno Python** | 3.71 | First-class AgentOS server, Multi-Model (4.75), MCP (4.75), Cost & Usage (4.00), 130+ built-in tools |
| 3 | **Microsoft Agent Framework** | 3.33 | Skills (4.60), Architecture (4.57), Durable workflows, dual Python/.NET |
| 4 | **Pydantic AI** | 3.17 | Multi-Model (5.00), Agent Loop (4.80), Eval (4.67), General (4.50), Cost & Usage (4.00) |
| 5 | **LangGraph Python** | 3.10 | Sessions (4.83), HTTP API (4.86), Multi-Model (4.75), Agent Loop (4.20) |
| 6 | **Claude Agent SDK TypeScript** | 2.98 | Context Engineering (5.00), MCP (4.50), Sub-agents (4.33), Cost & Usage (4.00) |

Honourable mentions:

- **Claude Agent SDK Python** (2.87) — Context Engineering (4.80), MCP (4.75), Sub-agents (4.67); the loop still runs in the bundled Node binary.
- **OpenAI Agents Python** (2.87) — 10 first-party session backends + 4 guardrail decorators + 7 sandbox provider integrations.
- **ADK Go** (2.83) — only stack with in-process Go loop + bundled REST/SSE/WS/A2A server (sub-second cold start, simplest deployment shape).

## Major disqualifiers and high-risk gaps

- **AutoAgents** (1.47) and **Rig** (1.52) are well-engineered Rust libraries but require substantial BYO: no sessions, no skills, no resource manager, hooks cannot mutate tool args, no per-tenant budget. Suitable only if Rust performance trumps platform features.
- **Vercel AI SDK** (2.49) is library-only with zero session store, zero registry, zero skill loader, and no `PostToolUse` follow-up tool emission. Strong multi-tenancy primitives (`runtimeContext`, `experimental_refineToolInput`, `prepareStep`) and strong Multi-Model — but everything beyond the loop is BYO.
- **LangGraph OSS** is excellent at the runtime layer but the HTTP / queue / replay layer is `langgraph_api`, a closed-source / paid platform component. Pure OSS deployment means BYO server + auth + queue.
- **CrewAI** (2.78) has no `tenantId`/`userId` on `Crew`/`Agent`/`Task`, executes only the first tool call per turn (both legacy and new executors), and the default `AgentExecutor` is marked experimental as of v1.14.5a6.
- **Claude Agent SDK Python / TypeScript**: filesystem-shaped tenancy (`.claude/` directories under per-tenant `cwd`), no first-class HTTP server, ~1 GB RAM per session, ~20–30 s worst-case cold start (upstream issue #333). Best feature surface in the benchmark — pay the architectural tax knowingly.

## Open questions

None — all 1900 score cells have evidence; no `?` cells remain.

## Notes on methodology

- 19 framework reports were generated (and restructured) by `analyse-ai-framework` sub-agents on 2026-05-19, each citing file:line references in the analysed submodule.
- 21 `score-benchmark-category` workers scored one taxonomy section each, calibrating row-by-row across all 19 frameworks before moving to the next row. Section structure was refactored on 2026-05-19: Agent Loop, Multi-Model, Observability, and Cost & Usage replaced the previous Agent Harness and Agent Observability sections.
- Canonical CSVs sort by `(section_order, section, row)` from `taxonomy.csv`, then framework order from `frameworks.csv`.
- The Microsoft Agent Framework submodule was checked out with `GIT_LFS_SKIP_SMUDGE=1`; non-source assets are missing but `python/` and `dotnet/` source trees are intact.
