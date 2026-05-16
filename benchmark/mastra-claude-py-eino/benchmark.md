# Stack Choice: Mastra vs Claude Agent SDK Py vs Eino

> Generated from `reports/mastra.md`, `reports/claude-agent-sdk-python.md`, and `reports/eino.md`. Canonical data lives under `data/`.

**Score legend:** 0 no support · 1 minimal primitive / large host effort · 2 partial primitive / mostly host-built · 3 usable with gaps · 4 strong with minor gaps · 5 first-class

## Executive Conclusions

- **Mastra is the strongest platform fit** for this scoped comparison: best skill/resource story, server/API surface, storage adapters, local UX, and eval support.
- **Claude Agent SDK Py is strongest for Claude-Code-style loop behavior**: hooks, built-in tools, sub-agents, prompt/cache behavior, and cost budget controls are excellent, but the loop runs in an Anthropic CLI subprocess and HTTP/platform layers are BYO.
- **Eino is the strongest Go runtime foundation**: in-process loop, graph runtime, middleware, checkpoint interfaces, and sub-agent orchestration are strong, but API, auth, persistence implementations, eval, UI, and governance layers are mostly host-built.
- **Multi-tenancy differs sharply**: Mastra has typed `requestContext`; Claude can force args through hooks but scopes skills through filesystem staging; Eino requires context/session-value conventions and custom middleware.
- **For a greenfield product platform**, Mastra minimizes surrounding platform work. **For a Go-native embedded runtime**, Eino is attractive if the host platform already exists. **For Claude-Code semantics**, Claude SDK Py is unmatched but provider/CLI lock-in is the trade-off.

## Overall Average Scores

| Framework | Average |
|---|---:|
| Mastra | 4.23 |
| Claude Agent SDK Py | 3.39 |
| Eino | 2.93 |

## Category Averages

| Category | Mastra | Claude Agent SDK Py | Eino |
|---|---:|---:|---:|
| 0. General | 4.33 | 3.67 | 4.0 |
| 1. Architecture | 4.0 | 1.5 | 4.25 |
| 2. Chat UI | 4.33 | 0.0 | 0.0 |
| 3. Agent API | 4.43 | 3.14 | 2.29 |
| 4. Agent Runtime | 4.25 | 2.5 | 2.0 |
| 5. Sessions & Persistence | 3.88 | 4.12 | 2.38 |
| 6. Agent Harness | 4.8 | 4.4 | 4.6 |
| 7. Message & Event Taxonomy | 4.4 | 4.8 | 4.4 |
| 8. Multi-model Routing | 5.0 | 4.0 | 3.33 |
| 9. Context Engineering | 3.0 | 4.8 | 3.4 |
| 10. Memory & Knowledge | 5.0 | 1.33 | 2.33 |
| 11. Skills | 4.83 | 3.33 | 3.83 |
| 12. Sub-agents | 4.33 | 4.67 | 4.17 |
| 13. Resource Manager | 3.83 | 1.0 | 1.67 |
| 14. Tools | 3.8 | 4.2 | 4.4 |
| 15. MCP | 4.75 | 4.75 | 3.5 |
| 16. Safety & Policy | 3.25 | 4.0 | 2.0 |
| 17. Agent Observability | 3.75 | 4.0 | 2.5 |
| 18. Multi-tenancy + per-call auth | 4.25 | 3.62 | 2.25 |
| 19. Eval / testing | 4.67 | 1.67 | 0.0 |
| 20. Local sandbox / dev UX | 4.5 | 3.25 | 2.0 |
| 21. Operations | 5.0 | 0.0 | 0.0 |

## Major Risks

- **Mastra:** broad framework surface and fast-moving alpha packages; USD cost calculation is still host-filled.
- **Claude Agent SDK Py:** Anthropic/Claude Code lock-in, subprocess cold start, no HTTP server, and filesystem-shaped resource scoping.
- **Eino:** low platform maturity around HTTP/auth/tenant/resource/eval layers despite a strong Go runtime.

## Data Files

- `data/taxonomy.csv`
- `data/frameworks.csv`
- `data/scores.csv`
- `data/evidence.csv`
