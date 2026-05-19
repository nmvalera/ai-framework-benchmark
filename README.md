# AI Framework Benchmark

Technical benchmark of AI agent frameworks for building a long-lived, skills-piloted agent exposed to external clients, with per-tenant tool and skill scoping enforced by the runtime rather than the LLM.

> **Scope disclaimer.** This benchmark is calibrated for **long-lived production agents exposed to external clients and piloted by skills**. In this context, *multi-tenancy* means the runtime — not the LLM — picks the tool set available to each tenant, scopes the skill library to that tenant, and injects tenant identity into tool calls server-side rather than trusting LLM-provided arguments. Benchmark rewards first-party support over BYO glue. A low score here is not a verdict on general framework quality — it means the framework leaves more development work for *this specific* use case. If you are building a single-tenant chatbot demo or a short-lived assistant, the rankings will not predict your experience.

## Results

- benchmark summary [page](https://nmvalera.github.io/ai-framework-benchmark/)
- full results [`docs/benchmark.md`](docs/benchmark.md)
- extended framework analysis [reports](docs/reports/)

## Methodology

The benchmark runs in two phases. Phase 1 produces one in-depth analysis per framework. Phase 2 turns those analyses into a single comparable scoring matrix. The two phases parallelize on different axes — Phase 1 fans out by framework, Phase 2 fans out by scoring category — which is what keeps each framework analysed in isolation while still calibrating scores across the whole set.

### Phase 1 — Framework analysis

Each framework is analysed by a dedicated, independent sub-agent running the [`analyse-ai-framework`](.agents/skills/analyse-ai-framework/) skill against the same shared [question bank](.agents/skills/analyse-ai-framework/references/questions.md). For every framework the sub-agent works from:

- the actual source code, pinned as a Git submodule under [`frameworks/`](frameworks/) at a recorded commit and branch;
- the in-repo changelog and GitHub Releases for recent architectural changes;
- the official documentation, used for clarification only — never as the primary source.

The sub-agent maps the repository, answers every question with concrete file:line references, includes light usage examples for the core use case, and marks missing features as `Not provided — BYO` instead of inventing workarounds. The output is one long-form markdown report per framework under [`docs/reports/`](docs/reports/).

Phase 1 sub-agents do not see each other's reports. Every framework is analysed in isolation against the same methodology, so the resulting reports are comparable without any cross-agent coordination.

### Phase 2 — Benchmark creation

Phase 2 fans out by **scoring category** instead of by framework. Each section of [`docs/data/taxonomy.csv`](docs/data/taxonomy.csv) is handed to a dedicated sub-agent running the [`score-benchmark-category`](.agents/skills/score-benchmark-category/) skill, which reads the Phase 1 analyses and produces score cells for its category. A top-level [`create-benchmark`](.agents/skills/create-benchmark/) skill orchestrates the workers and merges per-category CSVs into the canonical [`docs/data/scores.csv`](docs/data/scores.csv).

Within a category, the sub-agent scores **one row at a time across all frameworks** before moving on. This horizontal sweep is what calibrates the rubric: a 3 in framework A means the same level of support as a 3 in framework B for the same row.

Where Phase 1 reads vertically (one framework, all questions), Phase 2 reads horizontally (one question, all frameworks).

The analysed framework set is tracked in [`framework-index.json`](framework-index.json).

## What is benchmarked

Each framework is scored across the following capability areas.

0. **General** — How serious, well-funded, and well-documented the project is.
1. **Architecture** — Where the AI actually runs and what the dependencies are.
2. **Chat UI** — Whether the framework ships ready-to-use chat interface components out of the box or you have to build one yourself.
3. **HTTP API** — Whether the framework ships ready-to-use web API components to interface with the agent, or you have to wrap one yourself.
4. **Agent Runtime** — Whether the framework can handle many users running agents at the same time without breaking down.
5. **Sessions & Persistence** — Whether the framework ships a session store to persist conversation messages and state.
6. **Agent Loop** — How the framework manages the agent loop, dispatches tools, and exposes messages and events.
7. **Multi-Model** — Whether the framework can switch between multiple model providers, route per task, fall back on failure, and override the model for sub-agents.
9. **Context Engineering** — How much control the framework gives over what the AI sees each turn, which drives both answer quality and cost.
10. **Memory & Knowledge** — Whether the AI can remember things about each user across conversations and tap into your company's knowledge base.
11. **Skills** — Whether you can extend the agent with packaged capabilities (e.g. "expense reports", "support tickets") without rebuilding the agent each time.
12. **Sub-agents** — Whether the agent can delegate sub-tasks to specialist child agents.
13. **Resource Manager** — Whether prompts, skills, and tools can be versioned and rolled out to the agent like product features.
14. **Tools** — How rich the catalog of built-in AI tools is (search, send email, edit files…) and how easy it is to add your own.
15. **MCP** — Whether the framework supports MCP.
16. **Safety & Policy** — Whether the framework provides guardrails to keep the AI from saying or doing things you do not want.
17. **Observability** — Whether you can see what the AI is actually doing in production, debug it, and prove it behaved correctly.
18. **Cost & Usage** — Whether token usage and dollar cost can be tracked and rolled up per turn, session, conversation, or tenant.
19. **Multi-tenancy** — Whether the runtime can pick the tool set per tenant, scope the skill library to a tenant, and inject tenant identity into tool calls server-side rather than via LLM-provided arguments.
20. **Eval / testing** — Whether the framework provides AI agent evaluation and testing capabilities to measure performance and behavior.
21. **Local sandbox / dev UX** — Whether the framework provides a local sandbox and development environment to build and iterate on the agent day-to-day.

## Frameworks

Current selected framework set:

| Framework | Ecosystem | One-line description |
| --- | --- | --- |
| [ADK Go](https://github.com/google/adk-go) | Go | Google's official Go-native agent SDK with a built-in HTTP/WebSocket/A2A server, Vertex AI integration, and embedded Web UI, all in one binary. |
| [Agno Python](https://github.com/agno-agi/agno) | Python | Opinionated, batteries-included Python framework whose built-in FastAPI server ("AgentOS") covers scheduler, RBAC, traces, evals, knowledge, and 130+ tools out of the box. |
| [AutoAgents Rust](https://github.com/liquidos-ai/AutoAgents) | Rust | Rust-native library with a typed agent executor and an optional actor runtime for multi-agent coordination. |
| [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python) | Python | Anthropic's Python wrapper around the Claude Code CLI; the agent loop runs in a bundled Node.js binary that your process subprocesses. |
| [Claude Agent SDK TypeScript](https://github.com/anthropics/claude-agent-sdk-typescript) | TypeScript | Anthropic's TypeScript wrapper around the same Claude Code binary as the Python SDK, with a ~200 MB native binary spawned per session. |
| [CrewAI Python](https://github.com/crewAIInc/crewAI) | Python | Multi-agent-first Python framework built around "Crews" (sequential or hierarchical task teams) and event-driven "Flows". |
| [Eino Go](https://github.com/cloudwego/eino) | Go | Go-native library combining a graph orchestration engine with a higher-level agent toolkit shipping prebuilt ReAct, workflow, and supervisor patterns. |
| [Genkit Go](https://github.com/firebase/genkit) | Go | Firebase's flow-centric, in-process Go library with a dev-only reflection server consumed by the JS-based Genkit CLI. |
| [LangGraph Python](https://github.com/langchain-ai/langgraph) | Python | Python graph-based agent runtime with first-class Postgres/SQLite checkpointers; the production HTTP server is a separate closed-source paid component. |
| [LlamaIndex Python](https://github.com/run-llama/llama_index) | Python | Large Python ecosystem (~300 packages) whose agent layer sits on top of an event-driven workflow engine; historically focused on RAG and ingestion. |
| [Mastra TypeScript](https://github.com/mastra-ai/mastra) | TypeScript | Full-stack TypeScript framework where the agent loop is itself a workflow, with first-class skills, resource manager, and broad platform tooling. |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | Python + .NET | Microsoft's dual-language library that converges Semantic Kernel and AutoGen, with a graph-based workflow runtime and optional hosted Azure runtimes. |
| [OpenAI Agents Python](https://github.com/openai/openai-agents-python) | Python | Lightweight in-process Python library built directly on top of the official OpenAI SDK, with no subprocess or vendor runtime. |
| [OpenAI Agents TypeScript](https://github.com/openai/openai-agents-js) | TypeScript | Thin in-process TypeScript SDK exposing `Agent` / `Runner` classes; no bundled server, no subprocess, no hosted runtime. |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | Python | Provider-agnostic, library-first Python agent built as a typed Pydantic-graph state machine that runs in your process. |
| [Rig Rust](https://github.com/0xPlaygrounds/rig) | Rust | Rust library where the agent loop runs as plain async functions in your Tokio runtime; no bundled server or sidecar. |
| [Strands Agents Python](https://github.com/strands-agents/sdk-python) | Python | Model-driven, in-process Python SDK whose agent loop is a pure async generator; the host owns the entire runtime. |
| [Strands Agents TypeScript](https://github.com/strands-agents/sdk-typescript) | TypeScript | Library-only, in-process TypeScript SDK with an optional Express adapter that exposes agents over the A2A protocol. |
| [Vercel AI SDK TypeScript](https://github.com/vercel/ai) | TypeScript | TypeScript library providing the agent-loop primitives to mount on your own HTTP handler, plus first-party React/Vue/Svelte/Angular hooks. |

## Skills

### `benchmark-ai-frameworks`

Use this skill to orchestrate the full flow: read `framework-index.json`, run one `analyse-ai-framework` job per framework in dedicated parallel sub-agents, then run `create-benchmark`.

### `analyse-ai-framework`

Use this skill to produce a deep technical analysis of one framework. It reads the shared question bank and writes a long-form markdown report under `docs/reports/`.

### `create-benchmark`

Use this skill to read the generated reports and produce a comparison markdown table. It is intended for synthesis after individual reports have already been generated.

## Suggested Workflow

1. Update `framework-index.json` with the frameworks to analyse.
2. Run `benchmark-ai-frameworks` to launch one dedicated analysis sub-agent per framework.
3. Review the generated reports for factual errors and missing citations.
4. Use the generated matrix to identify promising stacks and drill back into the detailed reports for evidence.

## Repository Layout

```text
frameworks/
  <framework>/        # Git submodule per analysed framework
framework-index.json
.agents/
  skills/
    benchmark-ai-frameworks/
      SKILL.md
    analyse-ai-framework/
      SKILL.md
      references/
        questions.md
    create-benchmark/
      SKILL.md
docs/
  index.html
  benchmark.md
  data/
    *.csv
  reports/
    *.md
```
