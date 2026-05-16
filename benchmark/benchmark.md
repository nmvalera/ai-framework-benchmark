# Stack Choice: Where the Agent Loop Lives

> Generated on 2026-05-16 from 19 framework reports under `reports/`.
> Canonical data lives in [`data/`](data/) (`taxonomy.csv`, `frameworks.csv`, `scores.csv`, `evidence.csv`). Per-category worker outputs live in [`work/`](work/).

The benchmark targets **a long-running, multi-tenant agent piloted by skills**. Calibration favors first-party support over BYO glue.

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

## Frameworks studied

19 frameworks, all studied at HEAD on `main` on 2026-05-16:

- **Python** — Agno, Claude Agent SDK, CrewAI, LangGraph, LlamaIndex, OpenAI Agents, Pydantic AI, Strands Agents
- **TypeScript** — Claude Agent SDK, Mastra, OpenAI Agents, Strands Agents, Vercel AI SDK
- **Go** — ADK, Eino, Genkit
- **Rust** — AutoAgents, Rig
- **Multi-language** — Microsoft Agent Framework (Python + .NET)

See `data/frameworks.csv` for commit hashes and report paths.

## Executive conclusions

1. **Two architectural shapes dominate.** Almost every framework runs the agent loop **in-process** in your own server. The two outliers are Claude Agent SDK Python and Claude Agent SDK TypeScript, which subprocess the bundled Claude Code Node binary — meaning the actual loop runs in Node, not in your runtime. Pick this shape consciously: it ships the richest hook surface and first-party `total_cost_usd` enforcement, but costs you a ~200 MB platform binary and ~1 GB/session RAM ceiling.

2. **Multi-tenancy is the single biggest separator for our use case.** Three frameworks score ≥3.8 on the eight-row Multi-tenancy section: **Mastra**, **Pydantic AI**, and **LangGraph**. They are the only stacks that combine typed run-loop context, server-controlled tenant fields, per-turn visible-tool filtering, and a first-class "force tool args server-side" hook in one place. LangGraph's `InjectedToolArg` (strip-and-replace), Pydantic AI's `before_tool_validate`, and the Claude Agent SDKs' `PreToolUse.updatedInput` / `can_use_tool` are the strongest forced-args mechanisms; every other stack requires reading tenant from context inside the tool body and excluding tenant from the LLM-visible schema.

3. **Per-tenant USD budget caps are nearly universally absent.** Only the two Claude Agent SDKs (`max_budget_usd`) and Pydantic AI (`UsageLimits` + Gateway tiers) ship enforced USD ceilings. Everyone else exposes tokens but leaves cost rollup, namespacing, and enforcement to the host. Treat this as a known multi-tenant glue cost.

4. **Skills as a runtime concept are still rare.** Six frameworks score 0 across the entire Skills section (AutoAgents, LangGraph, LlamaIndex, Rig, Vercel AI). The strongest first-class implementations are **Mastra** (5.00 mean — only stack with `SkillsResolver(ctx)` runtime scoping and a built-in `skill_search`), **Eino** (4.60 — fork / fork-with-context / inline modes), **Microsoft Agent Framework** (4.40 — clean `SkillsSource` / `AggregatingSkillsSource` / `FilteringSkillsSource` chain), and **ADK Go** (4.20). Claude Agent SDK Py/TS score 3.8 — the canonical SKILL.md surface lives in the CLI, not the SDK source.

5. **Resource Manager is the most underdeveloped capability in the benchmark.** Only **Mastra** breaks 3.0 (3.33 mean) thanks to `VersionedSkillSource` + `CompositeVersionedSkillSource` + content-hashed blob refs. Everyone else is 0–2 — no publish workflow, no draft/active/deprecated lifecycle, no RBAC. Closed-source paid platforms (LangGraph Platform, CrewAI AMP) cover some of this but are scored conservatively against the OSS surface.

6. **Durable mid-run checkpointing has one clear winner.** **LangGraph** scores 5/5 on durable mid-run checkpointing (per-task `put_writes` in `_runner.py:574-613`) and 4.83 mean across the entire Sessions & Persistence section. The Claude Agent SDKs follow at 4.00 thanks to their reference Postgres/Redis/S3 `SessionStore` adapters and conformance harness. Most other stacks restrict durability to HITL pauses or leave persistence BYO.

## Top recommended stacks

Aggregate mean across all 97 scored rows:

| Rank | Framework | Mean | Strongest for the use case |
| --- | --- | --- | --- |
| 1 | **Mastra TypeScript** | 4.15 | Skills (5.00), Resource Manager (3.33), Multi-tenancy (4.00), Sessions (3.50), broad first-class platform |
| 2 | **Agno Python** | 3.66 | First-class AgentOS server, scheduler/background tasks, 130+ built-in tools |
| 3 | **Microsoft Agent Framework** | 3.41 | Durable workflows + Cosmos sessions, IntegrityLabel guardrails, dual Python/.NET |
| 4 | **Pydantic AI** | 3.14 | Typed `deps` + `metadata`, `before_tool_validate` forced args, Gateway USD limits, broad hooks |
| 5 | **LangGraph Python** | 3.08 | Best-in-class Sessions (4.83) + durable mid-run checkpoints + `InjectedToolArg` |

Honourable mentions:

- **Claude Agent SDK TypeScript** (3.05) — best context engineering (5.00), `maxBudgetUsd`, Postgres/Redis/S3 `SessionStore` references; the architectural cost is the bundled binary and the loop running in a subprocess.
- **OpenAI Agents Python** (2.87) — 10 first-party session backends + 4 guardrail decorators + 7 sandbox provider integrations.
- **ADK Go** (2.82) — only stack with in-process Go loop + bundled REST/SSE/WS/A2A server (sub-second cold start, simplest deployment shape).

## Major disqualifiers and high-risk gaps

- **AutoAgents** (1.51) and **Rig** (1.47) are well-engineered Rust libraries but require substantial BYO: no sessions, no skills, no resource manager, hooks cannot mutate tool args, no per-tenant budget. Suitable only if Rust performance trumps platform features.
- **Vercel AI SDK** is library-only with zero session store, zero registry, zero skill loader, and no `PostToolUse` follow-up tool emission. Strong multi-tenancy primitives (`runtimeContext`, `experimental_refineToolInput`, `prepareStep`) — but everything beyond the loop is BYO.
- **LangGraph OSS** is excellent at the runtime layer but the HTTP / queue / replay layer is `langgraph_api`, a closed-source / paid platform component. Pure OSS deployment means BYO server + auth + queue.
- **CrewAI** has no `tenantId`/`userId` on `Crew`/`Agent`/`Task`, executes only the first tool call per turn (both legacy and new executors), and the default `AgentExecutor` is marked experimental as of v1.14.5a5.
- **Claude Agent SDK Python / TypeScript**: filesystem-shaped tenancy (`.claude/` directories under per-tenant `cwd`), no first-class HTTP server, ~1 GB RAM per session, ~20–30 s worst-case cold start (upstream issue #333). Best feature surface in the benchmark — pay the architectural tax knowingly.

## Open questions

None — all 1862 score cells have evidence; no `?` cells remain.

## Notes on methodology

- 19 framework reports were generated in parallel by `study-ai-framework` sub-agents, each citing file:line references in the studied submodule.
- 21 `score-benchmark-category` workers scored one taxonomy section each, calibrating row-by-row across all 19 frameworks before moving to the next row.
- Canonical CSVs sort by `(section_order, section, row)` from `taxonomy.csv`, then framework order from `frameworks.csv`.
- The Microsoft Agent Framework submodule was checked out with `GIT_LFS_SKIP_SMUDGE=1`; non-source assets are missing but `python/` and `dotnet/` source trees are intact.
