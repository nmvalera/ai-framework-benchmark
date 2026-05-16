# AI Framework Benchmark

Technical benchmark of AI agent frameworks for building a long-lived, long-running agent piloted by skills with multi-tenancy.

The benchmark focuses on the engineering surface needed to run many isolated agent sessions in production: where the loop executes, how session state is persisted, how tenant and user context reaches tools, whether skills and sub-agents are first-class, and what has to be built around the framework.

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
