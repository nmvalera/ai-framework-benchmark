# AI Framework Benchmark

Technical benchmark of AI agent frameworks for building a long-lived, long-running agent piloted by skills with multi-tenancy.

The benchmark focuses on the engineering surface needed to run many isolated agent sessions in production: where the loop executes, how session state is persisted, how tenant and user context reaches tools, whether skills and sub-agents are first-class, and what has to be built around the framework.

## Approach

Each framework is studied with the same question bank so the reports can be compared consistently. The methodology favors source-code inspection over documentation summaries:

- clone or locate the framework source;
- record the exact commit and branch studied;
- map the repository before answering detailed questions;
- answer every question with concrete file and line references;
- include light usage examples for the core use case;
- mark missing features as `Not provided — BYO` instead of inventing workarounds.

The per-framework reports live in [`studies/`](studies/). The study workflow is packaged as a Codex skill in [`skills/study-ai-stack/`](skills/study-ai-stack/). The question bank is separated into [`skills/study-ai-stack/questions.md`](skills/study-ai-stack/questions.md) so readers can inspect the benchmark rubric directly.

## Frameworks

Current studies:

- ADK Go
- Claude Agent SDK Python
- Claude Agent SDK TypeScript
- CrewAI Python
- Eino Go
- Genkit Go
- Harden POC Go
- LangGraph Python
- Mastra TypeScript
- OpenAI Agents Python
- Vercel AI SDK TypeScript

## Skills

### `study-ai-stack`

Use this skill to produce a deep technical study for one framework. It reads the shared question bank and writes a long-form markdown report under `studies/`.

### `create-benchmark`

Use this skill to read the generated studies and produce a comparison markdown table. It is intended for synthesis after individual reports have already been generated.

## Suggested Workflow

1. Run `study-ai-stack` for each candidate framework.
2. Review the generated report for factual errors and missing citations.
3. Run `create-benchmark` across `studies/` to generate the comparison matrix.
4. Use the matrix to identify promising stacks and drill back into the detailed reports for evidence.

## Repository Layout

```text
skills/
  study-ai-stack/
    SKILL.md
    questions.md
  create-benchmark/
    SKILL.md
studies/
  *.md
```
