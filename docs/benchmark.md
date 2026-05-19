# Stack Choice: Where the Agent Loop Lives

> Generated on 2026-05-19 from 19 framework reports under `docs/reports/`. Taxonomy reworked again on this date: Chat UI/HTTP API rows reordered, Multi-Model trimmed (sub-agent override moved to Sub-agents, per-task selection removed), Context Engineering split Tool result clearing from Progressive disclosure, Skills lost Scoping (now in Resource Manager), Tools absorbed Tool sandboxing from Safety & Policy, Multi-tenancy renamed "context" → "tenant identity" and trimmed redundant rows.
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

## Category × Framework heatmap

Legend: 🟥 mean < 2.0 · 🟨 2.0–3.5 · 🟩 ≥ 3.5 · ⬜ not applicable.

| Category | ADK Go | Agno | AutoAgents | Claude Py | Claude TS | CrewAI | Eino | Genkit | LangGraph | LlamaIndex | Mastra | MS AF | OAI Py | OAI TS | Pydantic | Rig | Strands Py | Strands TS | Vercel AI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0. General | 🟨 3.2 | 🟩 3.8 | 🟨 2.0 | 🟩 3.8 | 🟩 4.0 | 🟩 4.5 | 🟩 3.5 | 🟨 3.2 | 🟩 4.8 | 🟩 4.8 | 🟩 3.5 | 🟩 4.0 | 🟩 3.8 | 🟩 3.5 | 🟩 4.5 | 🟨 2.0 | 🟩 3.5 | 🟨 2.8 | 🟩 4.0 |
| 1. Architecture | 🟩 4.1 | 🟩 3.9 | 🟨 3.4 | 🟨 2.0 | 🟨 2.3 | 🟩 4.1 | 🟩 4.1 | 🟩 4.0 | 🟩 3.6 | 🟩 3.6 | 🟩 4.1 | 🟩 4.4 | 🟩 4.1 | 🟩 3.7 | 🟩 4.1 | 🟩 4.0 | 🟩 3.7 | 🟩 3.6 | 🟩 4.1 |
| 2. Chat UI | 🟥 1.7 | 🟨 2.0 | 🟥 0.0 | 🟥 0.3 | 🟥 1.3 | 🟨 2.0 | 🟥 0.0 | 🟥 0.3 | 🟥 1.7 | 🟥 1.3 | 🟩 4.0 | 🟨 3.0 | 🟥 0.0 | 🟨 3.0 | 🟩 3.7 | 🟥 0.0 | 🟥 0.3 | 🟥 0.0 | 🟩 5.0 |
| 3. HTTP API | 🟨 3.3 | 🟩 4.8 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟥 0.8 | 🟥 0.0 | 🟨 3.0 | 🟩 4.8 | 🟥 0.0 | 🟩 4.7 | 🟩 3.7 | 🟥 0.0 | 🟥 0.0 | 🟨 2.7 | 🟥 0.0 | 🟥 0.3 | 🟥 0.3 | 🟨 3.0 |
| 4. Agent Runtime | 🟩 3.5 | 🟩 3.5 | 🟥 0.8 | 🟥 1.8 | 🟨 2.2 | 🟥 1.0 | 🟥 1.5 | 🟨 2.2 | 🟩 4.8 | 🟥 1.5 | 🟩 3.8 | 🟩 4.0 | 🟨 2.2 | 🟥 1.8 | 🟨 2.5 | 🟥 1.2 | 🟨 2.0 | 🟥 1.8 | 🟥 1.8 |
| 5. Sessions & Persistence | 🟨 3.0 | 🟨 2.8 | 🟥 0.7 | 🟩 3.8 | 🟩 3.8 | 🟨 3.3 | 🟥 1.3 | 🟥 1.3 | 🟩 5.0 | 🟨 2.3 | 🟨 3.2 | 🟨 3.3 | 🟩 3.8 | 🟨 2.3 | 🟥 1.2 | 🟥 1.3 | 🟨 2.7 | 🟨 2.3 | 🟥 0.2 |
| 6. Agent Loop | 🟩 4.8 | 🟩 4.8 | 🟩 4.8 | 🟩 4.2 | 🟩 4.4 | 🟩 3.6 | 🟩 4.2 | 🟩 3.8 | 🟩 4.4 | 🟩 4.8 | 🟩 4.8 | 🟩 3.8 | 🟩 5.0 | 🟩 5.0 | 🟩 4.8 | 🟩 3.8 | 🟩 4.8 | 🟩 4.8 | 🟩 4.6 |
| 7. Multi-Model | 🟥 0.5 | 🟩 5.0 | 🟩 4.5 | 🟨 2.0 | 🟨 2.0 | 🟨 3.0 | 🟨 2.5 | 🟩 4.0 | 🟩 4.0 | 🟨 3.0 | 🟩 5.0 | 🟨 2.0 | 🟨 3.0 | 🟨 2.5 | 🟩 5.0 | 🟨 2.5 | 🟨 3.0 | 🟨 2.5 | 🟩 3.5 |
| 9. Context Engineering | 🟨 2.0 | 🟨 3.2 | 🟥 0.8 | 🟩 4.3 | 🟩 4.7 | 🟨 3.0 | 🟩 4.5 | 🟥 1.7 | 🟨 3.0 | 🟨 2.2 | 🟩 4.2 | 🟩 3.8 | 🟨 3.3 | 🟨 2.7 | 🟩 4.2 | 🟥 0.7 | 🟩 4.5 | 🟩 4.8 | 🟨 2.2 |
| 10. Memory & Knowledge | 🟨 2.7 | 🟩 4.0 | 🟨 2.0 | 🟥 1.3 | 🟨 2.3 | 🟩 4.3 | 🟨 2.3 | 🟨 2.3 | 🟩 4.0 | 🟩 3.7 | 🟩 5.0 | 🟨 3.0 | 🟥 1.0 | 🟥 1.3 | 🟥 1.7 | 🟨 2.3 | 🟨 2.0 | 🟥 0.7 | 🟥 0.7 |
| 11. Skills | 🟩 4.8 | 🟩 4.8 | 🟥 0.0 | 🟩 3.8 | 🟩 3.8 | 🟩 3.5 | 🟩 5.0 | 🟩 3.5 | 🟥 0.0 | 🟥 0.0 | 🟩 4.8 | 🟩 4.8 | 🟩 3.8 | 🟩 4.0 | 🟥 1.8 | 🟥 0.0 | 🟩 4.8 | 🟩 4.8 | 🟥 0.0 |
| 12. Sub-agents | 🟩 3.7 | 🟩 4.0 | 🟨 3.1 | 🟩 4.6 | 🟩 4.4 | 🟨 3.0 | 🟩 3.7 | 🟨 3.0 | 🟨 3.3 | 🟩 3.7 | 🟩 4.6 | 🟨 3.1 | 🟩 3.7 | 🟩 3.7 | 🟨 2.9 | 🟨 2.7 | 🟩 4.3 | 🟩 4.1 | 🟨 2.0 |
| 13. Resource Manager | 🟥 1.3 | 🟨 2.3 | 🟥 0.1 | 🟥 0.9 | 🟥 1.3 | 🟥 1.7 | 🟥 1.0 | 🟥 1.0 | 🟥 1.0 | 🟥 0.1 | 🟨 3.1 | 🟥 1.4 | 🟥 0.6 | 🟥 1.1 | 🟥 0.7 | 🟥 0.3 | 🟥 1.0 | 🟥 1.0 | 🟥 0.1 |
| 14. Tools | 🟥 1.8 | 🟩 4.0 | 🟨 2.0 | 🟩 3.5 | 🟩 4.2 | 🟨 3.0 | 🟨 3.2 | 🟨 2.2 | 🟨 2.8 | 🟨 2.5 | 🟩 3.8 | 🟨 3.2 | 🟩 3.8 | 🟨 3.0 | 🟨 3.2 | 🟥 1.0 | 🟩 4.0 | 🟨 3.2 | 🟩 3.5 |
| 15. MCP | 🟨 3.0 | 🟩 4.8 | 🟨 2.0 | 🟩 4.8 | 🟩 4.5 | 🟩 4.2 | 🟩 3.5 | 🟩 4.2 | 🟩 3.8 | 🟩 4.5 | 🟩 4.5 | 🟩 4.2 | 🟩 3.5 | 🟩 3.5 | 🟩 4.5 | 🟨 2.8 | 🟩 3.8 | 🟩 3.8 | 🟩 3.5 |
| 16. Safety & Policy | 🟥 0.0 | 🟩 5.0 | 🟩 5.0 | 🟥 0.0 | 🟥 0.0 | 🟨 3.0 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟥 1.0 | 🟩 5.0 | 🟩 4.0 | 🟩 4.0 | 🟩 4.0 | 🟥 1.0 | 🟥 0.0 | 🟨 3.0 | 🟨 3.0 | 🟥 0.0 |
| 17. Observability | 🟩 4.0 | 🟩 4.0 | 🟨 3.0 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟨 3.0 | 🟨 3.0 | 🟩 3.5 | 🟩 4.0 | 🟩 3.5 | 🟩 3.5 | 🟨 3.0 | 🟩 3.5 | 🟩 3.5 | 🟩 3.5 | 🟩 4.0 | 🟩 3.5 |
| 18. Cost & Usage | 🟥 1.3 | 🟩 4.0 | 🟥 1.0 | 🟩 4.0 | 🟩 4.0 | 🟨 2.0 | 🟥 1.3 | 🟥 1.3 | 🟥 1.3 | 🟥 1.3 | 🟨 2.7 | 🟥 1.7 | 🟨 2.3 | 🟥 1.7 | 🟩 4.0 | 🟥 1.7 | 🟥 1.7 | 🟨 2.0 | 🟨 3.3 |
| 19. Multi-tenancy | 🟨 2.7 | 🟩 3.5 | 🟥 0.5 | 🟨 3.0 | 🟨 3.0 | 🟥 1.2 | 🟨 2.8 | 🟨 3.0 | 🟩 4.0 | 🟨 2.5 | 🟩 4.0 | 🟨 2.7 | 🟩 3.8 | 🟩 3.8 | 🟩 4.2 | 🟥 1.0 | 🟨 2.7 | 🟨 2.8 | 🟩 4.0 |
| 20. Eval / testing | 🟥 0.0 | 🟩 3.7 | 🟥 0.0 | 🟥 0.0 | 🟥 0.0 | 🟨 2.0 | 🟥 0.0 | 🟨 2.7 | 🟥 0.0 | 🟩 3.7 | 🟩 4.3 | 🟨 3.0 | 🟥 0.3 | 🟥 0.3 | 🟩 4.3 | 🟥 1.3 | 🟥 0.0 | 🟥 0.0 | 🟥 0.7 |
| 21. Local sandbox / dev UX | 🟨 2.5 | 🟨 3.2 | 🟥 0.8 | 🟨 3.2 | 🟨 2.5 | 🟨 2.0 | 🟥 1.2 | 🟨 3.2 | 🟩 3.5 | 🟥 0.2 | 🟩 4.8 | 🟩 3.5 | 🟥 1.5 | 🟥 0.8 | 🟨 2.5 | 🟥 0.5 | 🟥 1.2 | 🟥 1.2 | 🟥 0.5 |
| **Overall mean** | **🟨 2.80** | **🟩 3.75** | **🟥 1.61** | **🟨 2.76** | **🟨 2.92** | **🟨 2.75** | **🟨 2.53** | **🟨 2.62** | **🟨 3.20** | **🟨 2.37** | **🟩 4.11** | **🟨 3.35** | **🟨 2.77** | **🟨 2.62** | **🟨 3.14** | **🟥 1.58** | **🟨 2.78** | **🟨 2.65** | **🟨 2.41** |

Regenerate this table with `python3 .agents/skills/create-benchmark/scripts/render_heatmap.py --data-dir docs/data` whenever `scores.csv` changes.

## Frameworks analysed

19 frameworks, analysed at HEAD on `main` on 2026-05-19:

- **Python** — Agno, Claude Agent SDK, CrewAI, LangGraph, LlamaIndex, OpenAI Agents, Pydantic AI, Strands Agents
- **TypeScript** — Claude Agent SDK, Mastra, OpenAI Agents, Strands Agents, Vercel AI SDK
- **Go** — ADK, Eino, Genkit
- **Rust** — AutoAgents, Rig
- **Multi-language** — Microsoft Agent Framework (Python + .NET)

See `data/frameworks.csv` for commit hashes and report paths.

## Executive conclusions

1. **Two architectural shapes still dominate.** Almost every framework runs the agent loop **in-process** in your own server. The two outliers are Claude Agent SDK Python and Claude Agent SDK TypeScript, which subprocess the bundled Claude Code Node binary — meaning the actual loop runs in Node, not in your runtime. Pick this shape consciously: it ships the richest hook surface and first-party USD cost enforcement, but costs you a ~200 MB platform binary and ~1 GB/session RAM ceiling.

2. **Multi-tenancy remains the single biggest separator for our use case.** Pydantic AI, LangGraph, Mastra, OpenAI Agents (Py + JS), and Vercel AI score ≥3.8 on the 6-row Multi-tenancy section after the rework. LangGraph's `InjectedToolArg` (strip-and-replace) and the Claude Agent SDKs' `PreToolUse.updatedInput` are the only true first-class forced-args mechanisms (declarative schema-stripping); Pydantic AI's `before_tool_validate`, Strands' mutable hooks, and Vercel AI's `experimental_refineToolInput` are the strongest middleware-style alternatives.

3. **The Tools section now incorporates sandboxing** (moved from Safety & Policy). Claude Agent SDK TS (4.2) and OpenAI Agents Python (3.8) are the top combined "built-in catalog + sandboxing" stacks; Agno, Mastra, and Strands Python follow at 4.0. Safety & Policy is now a single-row category (Guardrails) — Agno, AutoAgents, and Mastra each score 5 by shipping multiple bundled detectors (PII, injection, moderation).

4. **Multi-Model is now a 2-row check** (Multi-provider support + Multi-model routing / fallback). Three stacks earn a perfect 5.0 — Agno, Mastra, Pydantic AI — by combining broad provider coverage with a first-class fallback primitive (`FallbackConfig`, `models` array, `FallbackModel`). ADK Go (0.5) is the laggard: Gemini-first with no fallback primitive at all.

5. **Skills as a runtime concept are still rare.** AutoAgents, LangGraph, LlamaIndex, Rig, and Vercel AI all score 0 across every Skills row. The strongest first-class implementations are **Eino** (5.0), **Mastra** (4.8), **Agno** (4.8), **Microsoft Agent Framework** (4.8), **ADK Go** (4.8), and **Strands Py/TS** (4.8) — Eino edges ahead with its fork/fork-with-context/inline composition modes.

6. **Resource Manager is the single most underdeveloped capability in the benchmark.** Only **Mastra** breaks 3.0 (3.1 mean) thanks to `VersionedSkillSource` + content-hashed blob refs. Every other framework sits at 0–2.3 — no publish workflow, no draft/active/deprecated lifecycle, no RBAC. Closed-source paid platforms (LangGraph Platform, CrewAI AMP) cover some of this but are scored conservatively against the OSS surface.

7. **Sessions & Persistence still has one clear winner.** **LangGraph** scores 5.0 mean across the entire section thanks to per-task `put_writes` durability (`_runner.py:574-613`) and a first-class fork primitive. The Claude Agent SDKs follow at 3.8 thanks to their reference Postgres/Redis/S3 `SessionStore` adapters and conformance harness. Vercel AI (0.2) is at the bottom — no built-in session store, no pluggable interface, persistence is entirely on the host.

## Top recommended stacks

Aggregate mean across all scored numeric cells (label-only rows `Ecosystem / primary language` and `Stack type` are excluded):

| Rank | Framework | Mean | Strongest sections |
| --- | --- | --- | --- |
| 1 | **Mastra TypeScript** | 4.11 | Multi-Model (5.0), Memory (5.0), Local sandbox (4.8), Skills (4.8), HTTP API (4.7), Sub-agents (4.6) |
| 2 | **Agno Python** | 3.75 | Multi-Model (5.0), Safety & Policy (5.0), HTTP API (4.8), Skills (4.8), MCP (4.8) |
| 3 | **Microsoft Agent Framework** | 3.35 | Skills (4.8), Architecture (4.4), MCP (4.2), Safety (4.0), Runtime (4.0) |
| 4 | **LangGraph Python** | 3.20 | Sessions (5.0), Agent Runtime (4.8), HTTP API (4.8), Multi-Model (4.0), Multi-tenancy (4.0) |
| 5 | **Pydantic AI** | 3.14 | Multi-Model (5.0), Agent Loop (4.8), Eval (4.3), Multi-tenancy (4.2), Context Engineering (4.2) |
| 6 | **Claude Agent SDK TypeScript** | 2.92 | Context Engineering (4.7), MCP (4.5), Sub-agents (4.4), Agent Loop (4.4), Tools (4.2) |

Honourable mentions:

- **ADK Go** (2.80) — only stack with in-process Go loop + bundled REST/SSE/WS/A2A server. Best Skills surface among Go frameworks (4.8).
- **Strands Agents Python** (2.78) — Context Engineering (4.5), Skills (4.8), Agent Loop (4.8), Sub-agents (4.3).
- **OpenAI Agents Python** (2.77) — Safety (4.0), Multi-tenancy (3.8), Sessions (3.8), Tools (3.8).
- **Claude Agent SDK Python** (2.76) — same feature surface as the TS SDK, slightly lower; loop still runs in the bundled Node binary.

## Major disqualifiers and high-risk gaps

- **AutoAgents** (1.61) and **Rig** (1.58) are well-engineered Rust libraries but require substantial BYO: no sessions, no skills, no resource manager, hooks cannot mutate tool args, no per-tenant budget. Suitable only if Rust performance trumps platform features.
- **Vercel AI SDK** (2.41) is library-only with zero session store, zero registry, zero skill loader, and no `PostToolUse` follow-up tool emission. Strong multi-tenancy primitives (`runtimeContext`, `experimental_refineToolInput`, `prepareStep`) and a first-class Chat UI — but everything beyond the loop is BYO.
- **LangGraph OSS** is excellent at the runtime layer but the HTTP / queue / replay layer is `langgraph_api`, a closed-source / paid platform component. Pure OSS deployment means BYO server + auth + queue.
- **CrewAI** (2.75) has no `tenantId`/`userId` on `Crew`/`Agent`/`Task`, executes only the first tool call per turn (both legacy and new executors), and the default `AgentExecutor` is marked experimental as of v1.14.5a6.
- **Claude Agent SDK Python / TypeScript**: filesystem-shaped tenancy (`.claude/` directories under per-tenant `cwd`), no first-class HTTP server, ~1 GB RAM per session, ~20–30 s worst-case cold start (upstream issue #333). Best feature surface in the benchmark — pay the architectural tax knowingly.

## Open questions

None — all 1767 score cells have evidence; no `?` cells remain.

## Notes on methodology

- 19 framework reports were generated (and restructured to the prior taxonomy) by `analyse-ai-framework` sub-agents on 2026-05-19, each citing file:line references in the analysed submodule. The current scoring pass re-uses those reports as-is.
- 21 `score-benchmark-category` workers scored one taxonomy section each, calibrating row-by-row across all 19 frameworks before moving to the next row.
- Canonical CSVs sort by `(section_order, section, row)` from `taxonomy.csv`, then framework order from `frameworks.csv`.
- The Microsoft Agent Framework submodule was checked out with `GIT_LFS_SKIP_SMUDGE=1`; non-source assets are missing but `python/` and `dotnet/` source trees are intact.
