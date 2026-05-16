---
name: study-ai-framework
description: In-depth benchmark study of an AI agent SDK/framework — deployment & architecture, message taxonomy, harness loop, runtime, sessions & persistence, multi-tenancy, hooks, API surface, sub-agents, skills, resource manager, observability, built-in tools, MCP, multi-model routing, plus secondary capabilities (UI, memory, guardrails, eval, dev UX). Produces a structured reference markdown report with file:line code excerpts and light usage examples. Use when comparing AI agent stacks (Mastra, LangGraph, Claude Agent SDK, Vercel AI SDK, ADK, OpenAI Agents, CrewAI, Eino, Genkit, etc.) for an architectural decision. Triggers on "benchmark this stack", "study this SDK in depth", "compare agent frameworks".
---

# Study an AI agent stack — benchmark methodology

You're producing a deep technical analysis of one AI agent SDK / framework. The audience is engineers picking a stack for a production, multi-tenant, long-running agent piloted by skills. Your report will sit alongside sibling reports on other stacks and **consistency of vocabulary, ordering, and depth across reports matters as much as raw depth**.

## Inputs the caller provides

- `STACK_NAME` — human-readable (e.g. `Mastra TS`, `Claude Agent SDK Py`)
- `REPO_URL` — Git URL to add as a submodule under `frameworks/`, OR `LOCAL` if you should study a repo already on disk
- `FRAMEWORK_PATH` — where the framework lives, normally `frameworks/<framework-slug>/`
- `LOCAL_PATHS` (only for `LOCAL`) — the dirs/files to focus on
- `OUTPUT_PATH` — where the analysis lives (e.g. `reports/mastra.md`)

## Step 1 — Add/update the framework submodule (or locate)

External repos:
```bash
mkdir -p frameworks
git submodule add <REPO_URL> <FRAMEWORK_PATH>   # first time only
git submodule update --init --depth=1 <FRAMEWORK_PATH>
cd <FRAMEWORK_PATH> && git rev-parse HEAD      # capture the commit you studied — report it!
cd <FRAMEWORK_PATH> && git branch --show-current
```

Use one Git submodule per framework so the benchmark repository records exactly which upstream repo and commit each report studied. A shallow submodule checkout is fine — you are reading, not contributing. If the submodule already exists, run `git submodule update --init --depth=1 <FRAMEWORK_PATH>` and optionally `cd <FRAMEWORK_PATH> && git fetch --depth=1 origin <branch-or-tag>` before studying a newer commit.

For `LOCAL`, just `cd` to the listed paths and record `git rev-parse HEAD` + branch.

## Step 2 — Map the online documentation, repos, and release history (10–15 min, before answering anything)

Before drilling into the question bank, map the existing report if one exists, the public docs, the source repository layout, and the release history.

Existing report state:
- If `OUTPUT_PATH` already exists, read it first.
- Note which sections are already complete, stale, thin, contradictory, or missing citations.
- Preserve useful existing findings, examples, and file references when they are still accurate.
- Update stale claims against the current framework commit, docs, changelog, and GitHub Releases.
- Do not delete working report content just because you are restructuring; carry it forward unless it is wrong or outside the benchmark scope.

Online documentation:
- Official docs landing page.
- Quickstart / getting-started guide.
- API reference.
- Hosting / deployment / production guide.
- Examples / demos repo.
- Changelog / release notes.
- GitHub Releases.
- GitHub issues tracker and any open issues that matter for this benchmark.
- Discord / community forum if active.

Repository layout:
- The agent run loop entrypoint (`run`, `stream`, `generate`, `Run`, `Step`, `loop`, `query`).
- Message types (search `Message`, `MessageType`, `Event`, `Part`, `Chunk`).
- Tool abstraction (`Tool`, `tool(`, `defineTool`, `createTool`, `@tool`).
- Session / state objects (`Session`, `Thread`, `Context`, `RunState`, `Conversation`, `Checkpointer`).
- Hooks / middleware / callbacks (`Hook`, `Middleware`, `Callback`, `Interceptor`, `Plugin`, `prepareStep`).
- HTTP/API server if any (`server`, `route`, `app.get`, `useChat`, `stream`, `langgraph_api`).
- Sub-agent / multi-agent primitive (`SubAgent`, `handoff`, `delegate`, `spawnAgent`, `Crew`, `Swarm`, `Task` tool).
- Skill loader (`SKILL.md`, `loadSkills`, `Skill`, `WorkspaceSkills`, `setting_sources`).
- Resource manager / registry (`Registry`, `SkillSource`, `VersionedSkillSource`, `plugin`, `marketplace`).
- Observability hooks (`usage`, `tokens`, `cost`, `telemetry`, `tracer`, `otel`, `LangSmith`).
- **Critically**: does the loop actually run *here*, or is this a wrapper around something else (CLI subprocess, vendor REST API, separate runtime in a sister repo)?

Release history:
- In-repo release notes (`CHANGELOG.md`, `RELEASES.md`, `HISTORY.md`, docs release notes) and GitHub Releases. Note recent changes that affect architecture, session persistence, hooks, skills, sub-agents, MCP, model routing, or deployment. If the repo has no changelog or releases, say so.

Note paths as you go — you'll cite them.

## Step 3 — Answer the question areas

Read and follow `questions.md` in this skill directory. Keep the generated report structure and numbering aligned with that file.

---

## Step 4 — Write the report

Output to `OUTPUT_PATH` in this structure:

````markdown
# <STACK_NAME> — Benchmark Study

> **Repo**: <REPO_URL>
> **Commit studied**: <git rev-parse HEAD>
> **Branch**: <git branch --show-current>
> **Framework path**: <FRAMEWORK_PATH>
> **Studied on**: <YYYY-MM-DD>

## TL;DR

8–12 bullets covering the most decision-relevant facts:
- ⭐ **What is this stack architecturally?** (e.g. "thin Python wrapper around a Node CLI binary", "Go-native graph runtime", "Next.js-first frontend SDK with a backend Agent class")
- Where the agent loop *actually* executes
- Strongest architectural choice for our use case (multi-tenant long-running agent piloted by skills)
- Weakest / biggest gap
- Most surprising finding (good or bad)
- One-line verdict for each of: sessions/persistence, skills, resource manager, sub-agents, multi-tenancy, hooks, API, observability
- Production-readiness verdict for multi-tenant server-side deployment

## 0. Architectural Overview & Deployment Model

[Deployment diagram (mermaid or ASCII) showing process boundaries]
[0.1–0.10 architecture, deployment, release-history & documentation links]

## 1. Agent Harness (Run Loop) & Message Taxonomy

[1.1–1.6 run loop]
[1.7–1.12 message & event taxonomy]
## 2. Agent Runtime (Multi-session Host)
## 3. Sessions & Persistence
## 4. Multi-tenancy & Arbitrary Context
[include the ⭐ light usage example]
## 5. Hook & Middleware Capabilities (Context Engineering)
[include the ⭐ light usage example + hook fire-points diagram]
## 6. Agent API Exposition
[include the ⭐ light usage example]
## 7. Sub-agents
[include the ⭐ light usage example]
## 8. Skills
[include the ⭐ light usage example]
## 9. Resource Manager
[include the ⭐ light usage example]
## 10. Observability: Usage, Cost, Tracing, Audit
[include the ⭐ light usage example]
## 11. Built-in Tools & Tool Authoring API
## 12. MCP (Model Context Protocol) Support
## 13. Multi-model Routing & Fallback
## 14. Chat UI Layer
## 15. Memory & Knowledge
## 16. Safety, Guardrails & Tool Sandboxing
## 17. Eval, Testing & CI Gates
## 18. Local Sandbox & Dev UX

## Architectural diagram

```mermaid
[Full architecture: API ↔ run loop ↔ session/state ↔ tool dispatch ↔ hooks ↔ providers]
```

## Appendix — Files worth reading first

8–12 bullet list of `path/to/file.ts` with one-line "this is where X lives" so a future engineer can deep-dive themselves.
````

## Style rules

- Cite **real file paths and line numbers** the reader can click. Format: `pkg/foo/bar.ts:42` (relative to the framework submodule root, not absolute).
- Prefer **direct code excerpts** (5–30 lines) over paraphrase.
- When a feature does NOT exist, write **"Not provided — BYO"**. Don't invent workarounds.
- Avoid promotional language. Engineers are picking a stack — they want facts and gaps.
- Length: ~2500–5000 lines is normal for the expanded structure. Long is fine; this is a reference document.
- If you spot something genuinely surprising (good or bad), flag it in the TL;DR — that's the most valuable signal across reports.
- ⭐ The **light usage examples** in Q4, Q5, Q6, Q7, Q8, Q9, Q10 are NOT optional. They're the single most useful part of the report for engineers who want to evaluate "could I actually build my use case on this?".

## Return to caller

After writing the report, return a short text summary (under 300 words) covering:
- Commit hash + branch you studied
- The 2–3 most decision-relevant findings (architectural shape, biggest gap, biggest surprise)
- Any blocker / gap that disqualifies the stack for the use case (or "no blocker found")
