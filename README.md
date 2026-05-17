# AI Framework Benchmark

Technical benchmark of AI agent frameworks for building a long-lived, long-running agent piloted by skills with multi-tenancy.

> **Scope disclaimer.** This benchmark is calibrated for **long-lived, multi-tenant production agents piloted by skills**. Benchmark rewards first-party support over BYO glue. A low score here is not a verdict on general framework quality, it means the framework leaves more host work for *this specific* use case. If you are building a single-tenant chatbot demo or a short-lived assistant, the rankings will not predict your experience.

The benchmark focuses on the engineering surface needed to run 
- many isolated agent sessions in production
- persisting state
- multi-tenancy: where the loop executes, how session state is persisted, how tenant and user context reaches tools, whether skills and sub-agents are first-class, and what has to be built around the framework.

Full results: [`docs/benchmark.md`](docs/benchmark.md). Interactive viewer (once GitHub Pages is enabled): https://nmvalera.github.io/ai-framework-benchmark/.

## Methodology

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

## What is benchmarked

Each framework is scored across the following capability areas. Definitions below are written for product readers; the per-row scoring rubric sits in [`docs/data/taxonomy.csv`](docs/data/taxonomy.csv).

0. **General** — How serious, well-funded, and well-documented the project is.
1. **Architecture** — Where the AI actually runs and what the dependencies are.
2. **Chat UI** — Whether the framework ships ready-to-use chat interface components out of the box or you have to build one yourself.
3. **HTTP API** — Whether the framework ships ready-to-use web API components to interface with the agent, or you have to wrap one yourself.
4. **Agent Runtime** — Whether the framework can handle many users running agents at the same time without breaking down.
5. **Sessions & Persistence** — Whether the framework ships a session store to persist conversation messages and state.
6. **Agent Harness** — How the framework manages the agent loop, interacts with models and tools, and exposes messages and events.
9. **Context Engineering** — How much control the framework gives over what the AI sees each turn, which drives both answer quality and cost.
10. **Memory & Knowledge** — Whether the AI can remember things about each user across conversations and tap into your company's knowledge base.
11. **Skills** — Whether you can extend the agent with packaged capabilities (e.g. "expense reports", "support tickets") without rebuilding the agent each time.
12. **Sub-agents** — Whether the agent can delegate sub-tasks to specialist child agents.
13. **Resource Manager** — Whether prompts, skills, and tools can be versioned and rolled out to the agent like product features.
14. **Tools** — How rich the catalog of built-in AI tools is (search, send email, edit files…) and how easy it is to add your own.
15. **MCP** — Whether the framework supports MCP.
16. **Safety & Policy** — Whether the framework provides guardrails to keep the AI from saying or doing things you do not want.
17. **Agent Observability** — Whether you can see what the AI is actually doing in production, debug it, and prove it behaved correctly.
18. **Multi-tenancy** — Whether the framework enables safely isolating each client's data, tools, and skills across agent sessions.
19. **Eval / testing** — Whether the framework provides AI agent evaluation and testing capabilities to measure performance and behavior.
20. **Local sandbox / dev UX** — Whether the framework provides a local sandbox and development environment to build and iterate on the agent day-to-day.

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
