---
name: analyse-ai-framework
description: In-depth benchmark analysis of an AI agent SDK/framework — deployment & architecture, message taxonomy, harness loop, runtime, sessions & persistence, multi-tenancy, hooks, API surface, sub-agents, skills, resource manager, observability, built-in tools, MCP, multi-model routing, plus secondary capabilities (UI, memory, guardrails, eval, dev UX). Produces a structured reference markdown report with file:line code excerpts and light usage examples. Use when comparing AI agent stacks (Mastra, LangGraph, Claude Agent SDK, Vercel AI SDK, ADK, OpenAI Agents, CrewAI, Eino, Genkit, etc.) for an architectural decision. Triggers on "benchmark this stack", "analyse this SDK in depth", "compare agent frameworks".
---

# Analyse an AI agent stack — benchmark methodology

You're producing a deep technical analysis of one AI agent SDK / framework. The audience is engineers picking a stack for a production, multi-tenant, long-running agent piloted by skills. Your report will sit alongside sibling reports on other stacks and **consistency of vocabulary, ordering, and depth across reports matters as much as raw depth**.

## Inputs the caller provides

- `STACK_NAME` — human-readable (e.g. `Mastra TS`, `Claude Agent SDK Py`)
- `REPO_URL` — Git URL to add as a submodule under `frameworks/`, OR `LOCAL` if you should analyse a repo already on disk
- `FRAMEWORK_PATH` — where the framework lives, normally `frameworks/<framework-slug>/`
- `LOCAL_PATHS` (only for `LOCAL`) — the dirs/files to focus on
- `OUTPUT_PATH` — where the analysis lives (e.g. `reports/mastra.md`)

## Step 1 — Add/update the framework submodule (or locate)

External repos:
```bash
mkdir -p frameworks
git submodule add <REPO_URL> <FRAMEWORK_PATH>   # first time only
git submodule update --init --depth=1 <FRAMEWORK_PATH>
cd <FRAMEWORK_PATH> && git rev-parse HEAD      # capture the commit you analysed — report it!
cd <FRAMEWORK_PATH> && git branch --show-current
```

Use one Git submodule per framework so the benchmark repository records exactly which upstream repo and commit each report analysed. A shallow submodule checkout is fine — you are reading, not contributing. If the submodule already exists, run `git submodule update --init --depth=1 <FRAMEWORK_PATH>` and optionally `cd <FRAMEWORK_PATH> && git fetch --depth=1 origin <branch-or-tag>` before analysing a newer commit.

For `LOCAL`, just `cd` to the listed paths and record `git rev-parse HEAD` + branch.

## Step 2 — Map the online documentation, repos, and release history (10–15 min, before answering anything)

Before drilling into the question bank, map the existing report if one exists, the public docs, the source repository layout, and the release history.

Existing report state:
- If `OUTPUT_PATH` already exists, read it first.
- **Default mode when a report already exists: restructure, do NOT re-research.** Treat the existing report as the primary source of truth for facts about the stack. Your first job is to reconcile its shape with the current `references/questions.md`, not to re-derive findings from the framework source.
- Diff the existing report's headings and sub-bullets against the current `references/questions.md`. If sections have been added, removed, renamed, renumbered, split, or merged — or if sub-bullets have shifted — restructure the report so it matches the new version exactly (heading text, ordering, sub-bullet numbering, ⭐ markers). This is reformatting, not forgetting: move existing content to its new location, merge or split paragraphs to fit the new sub-bullets, and only drop content that is genuinely outside the new scope.
- If existing content does not map cleanly to any current sub-bullet, prefer to re-home it under the closest match rather than discard it. Do not perform a hard remapping (rewriting every line from scratch) unless there is a clear reason — e.g. the section was fundamentally redefined, the existing content is wrong, or it contradicts the current framework commit.
- **Only fall back to exploring the stack when, after restructuring, a sub-bullet has no answer in the existing report and that answer is genuinely missing — not just relocated.** Limit fresh research to those specific gaps; do not re-derive sub-bullets that already have a usable answer.
- Note which sections, after restructuring, are still complete, stale, thin, contradictory, or missing citations. Update stale claims against the current framework commit, docs, changelog, and GitHub Releases only where the existing claim is wrong or out of date — not as a routine pass.
- Preserve useful existing findings, examples, and file references when they are still accurate. Do not delete working content just because you are restructuring; carry it forward unless it is wrong or outside the benchmark scope.

Online documentation:
- Project status: whether the framework is open-source, license, owning organization, maintainers, commercial backing, and support model.
- Project maturity: initial public release date or oldest meaningful commit/tag, current major version, stable/beta/experimental status, and framework age.
- Adoption/community signals: GitHub stars, forks, watchers, contributor count, issue/PR activity, recent commits, release cadence, and whether maintainers actively respond. Record the date you captured these numbers.
- Ecosystem/package signals: package names, primary languages, package registry links, package download signal if easy to verify, and official examples/templates.
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

Read and follow `references/questions.md` in this skill directory. **That file is the single source of truth for the section list, the question order, the sub-bullet numbering, and the ⭐ Required markers.** Do not re-enumerate sections here; do not paraphrase the question text. Keep the generated report's `## N. Section Title` headings character-identical to the `### Qn — Section Title` headings in `references/questions.md` (drop the `Q` prefix in the report, keep the title).

---

## Step 4 — Write the report

Output to `OUTPUT_PATH` in this structure:

````markdown
# <STACK_NAME> — Benchmark Analysis

> **Repo**: <REPO_URL>
> **Commit analysed**: <git rev-parse HEAD>
> **Branch**: <git branch --show-current>
> **Framework path**: <FRAMEWORK_PATH>
> **Analysed on**: <YYYY-MM-DD>

## TL;DR

8–12 bullets covering the most decision-relevant facts:
- ⭐ **What is this stack architecturally?** (e.g. "thin Python wrapper around a Node CLI binary", "Go-native graph runtime", "Next.js-first frontend SDK with a backend Agent class")
- **Ecosystem** — Python / TypeScript / Go / Rust (state it explicitly; one of those four)
- Open-source/license/support profile (who maintains it, license, commercial or community support)
- Maturity/adoption snapshot (age, current stability status, GitHub stars/forks, release cadence)
- Where the agent loop *actually* executes
- Strongest architectural choice for our use case (multi-tenant long-running agent piloted by skills)
- Weakest / biggest gap
- Most surprising finding (good or bad)
- One-line verdict for each of: sessions/persistence, skills, resource manager, sub-agents, multi-tenancy, hooks, API, observability
- Production-readiness verdict for multi-tenant server-side deployment

## <one ## section per question in references/questions.md, in numerical order>

For each question in `references/questions.md`:
- Use `## N. <Section Title>` (e.g. `## 0. General`) matching the question's heading.
- Answer every sub-bullet (`N.1`, `N.2`, …) defined for that question, in the order they appear there.
- If a sub-bullet has an ⭐ marker in `references/questions.md`, include the corresponding artifact (URL list, diagram, light usage example, etc.) in the same position.
- For features the stack does not provide, write `Not provided — BYO`. Do not invent workarounds.

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
- ⭐ Every **light usage example** marked `⭐ Required — light usage example` in `references/questions.md` is mandatory. They're the single most useful part of the report for engineers who want to evaluate "could I actually build my use case on this?".

## Return to caller

After writing the report, return a short text summary (under 300 words) covering:
- Commit hash + branch you analysed
- The 2–3 most decision-relevant findings (architectural shape, biggest gap, biggest surprise)
- Any blocker / gap that disqualifies the stack for the use case (or "no blocker found")
