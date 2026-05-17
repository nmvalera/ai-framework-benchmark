# AI Framework Benchmark

Technical benchmark of AI agent frameworks for building a long-lived, long-running agent piloted by skills with multi-tenancy.

> **Scope disclaimer.** This benchmark is calibrated for **long-lived, multi-tenant production agents piloted by skills**. Benchmark rewards first-party support over BYO glue. A low score here is not a verdict on general framework quality, it means the framework leaves more host work for *this specific* use case. If you are building a single-tenant chatbot demo or a short-lived assistant, the rankings will not predict your experience.

The benchmark focuses on the engineering surface needed to run many isolated agent sessions in production: where the loop executes, how session state is persisted, how tenant and user context reaches tools, whether skills and sub-agents are first-class, and what has to be built around the framework.

Full results: [`docs/benchmark.md`](docs/benchmark.md). Interactive viewer (once GitHub Pages is enabled): https://nmvalera.github.io/ai-framework-benchmark/.

## TL;DR

**Top 5** (aggregate mean across 98 scored rows; full ranking and per-section scores in [`docs/benchmark.md`](docs/benchmark.md)):

| # | Framework | Mean | Why it ranks |
| - | --- | --- | --- |
| 1 | **Mastra** (TS) | 4.15 | Only first-class skills + resource manager; strong multi-tenancy; broad platform |
| 2 | **Agno** (Python) | 3.65 | Bundled AgentOS server, scheduler/background tasks, 130+ built-in tools |
| 3 | **Microsoft Agent Framework** (Py + .NET) | 3.44 | Durable workflows + Cosmos sessions, IntegrityLabel guardrails |
| 4 | **Pydantic AI** (Python) | 3.18 | Typed `deps`/`metadata`, `before_tool_validate` forced args, Gateway USD limits |
| 5 | **Claude Agent SDK** (TS) | 3.11 | Context engineering (5/5), `maxBudgetUsd`, reference Postgres/Redis/S3 `SessionStore` |

**Best for…**

- **Multi-tenancy from day one** → Mastra, Pydantic AI, LangGraph (only stacks combining typed run-loop context, server-controlled tenant fields, per-turn tool filtering, and a forced-args hook)
- **Skills as a runtime concept** → Mastra (5.00), Eino (4.60), Microsoft Agent Framework (4.40), ADK Go (4.20)
- **Durable mid-run checkpointing** → LangGraph (5/5 — per-task `put_writes`)
- **Per-tenant USD budget caps** → Claude Agent SDKs (`max_budget_usd`), Pydantic AI (`UsageLimits` + Gateway)
- **Bundled HTTP server, simplest deploy shape** → Agno (AgentOS), ADK Go (REST/SSE/WS/A2A in-binary), Microsoft Agent Framework

**Avoid if…**

- You want **pure-OSS** multi-tenant runtime end-to-end → LangGraph's HTTP/queue/replay layer (`langgraph_api`) and CrewAI AMP are paid platform components
- You **can't afford a ~200 MB binary or ~1 GB/session RAM** → Claude Agent SDK Py/TS subprocess the bundled Node binary; ~20–30 s worst-case cold start
- You need **tenant identifiers on the runtime** → CrewAI has no `tenantId`/`userId` on `Crew`/`Agent`/`Task`
- You want **everything first-party** beyond the loop → Vercel AI SDK, AutoAgents, Rig are library-only (zero session store, zero registry, zero skill loader)

## Approach

Each framework is studied with the same question bank so the reports can be compared consistently. The methodology favors source-code inspection over documentation summaries:

- add or update the framework source under `frameworks/` as a Git submodule;
- record the exact commit and branch studied;
- map the repository before answering detailed questions;
- inspect the in-repo changelog and GitHub Releases for recent architectural changes;
- answer every question with concrete file and line references;
- include light usage examples for the core use case;
- mark missing features as `Not provided — BYO` instead of inventing workarounds.

The per-framework reports live in [`reports/`](reports/). The study workflow is packaged as a project-scoped Codex skill in [`.agents/skills/study-ai-framework/`](.agents/skills/study-ai-framework/). The question bank is separated into [`.agents/skills/study-ai-framework/questions.md`](.agents/skills/study-ai-framework/questions.md) so readers can inspect the benchmark rubric directly.

The studied framework set is tracked in [`framework-index.json`](framework-index.json).

## Frameworks

Current selected framework set:

Python:

- Agno Python
- Claude Agent SDK Python
- CrewAI Python
- LangGraph Python
- LlamaIndex Python
- OpenAI Agents Python
- Pydantic AI
- Strands Agents Python

TypeScript:

- Claude Agent SDK TypeScript
- Mastra TypeScript
- OpenAI Agents TypeScript
- Strands Agents TypeScript
- Vercel AI SDK TypeScript

Go:

- ADK Go
- Eino Go
- Genkit Go

Rust:

- AutoAgents Rust
- Rig Rust

Multi-language:

- Microsoft Agent Framework

## Skills

### `benchmark-ai-frameworks`

Use this skill to orchestrate the full flow: read `framework-index.json`, run one `study-ai-framework` job per framework in dedicated parallel sub-agents, then run `create-benchmark`.

### `study-ai-framework`

Use this skill to produce a deep technical study for one framework. It reads the shared question bank and writes a long-form markdown report under `reports/`.

### `create-benchmark`

Use this skill to read the generated reports and produce a comparison markdown table. It is intended for synthesis after individual reports have already been generated.

## Suggested Workflow

1. Update `framework-index.json` with the frameworks to study.
2. Run `benchmark-ai-frameworks` to launch one dedicated study sub-agent per framework.
3. Review the generated reports for factual errors and missing citations.
4. Use the generated matrix to identify promising stacks and drill back into the detailed reports for evidence.

## Repository Layout

```text
frameworks/
  <framework>/        # Git submodule per studied framework
framework-index.json
.agents/
  skills/
    benchmark-ai-frameworks/
      SKILL.md
    study-ai-framework/
      SKILL.md
      questions.md
    create-benchmark/
      SKILL.md
reports/
  *.md
```
