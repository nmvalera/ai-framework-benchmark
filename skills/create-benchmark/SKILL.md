---
name: create-benchmark
description: Read generated AI framework study reports and create a concise markdown comparison table for a long-running, skill-piloted, multi-tenant agent benchmark. Use after `study-ai-stack` has produced reports under `studies/`.
---

# Create Benchmark Matrix

You synthesize existing framework studies into a comparison table. Do not restudy the frameworks from scratch unless a report is missing or contradictory. Prefer evidence already present in the generated markdown reports.

## Inputs

- `STUDIES_DIR` — directory containing generated study reports, usually `studies/`.
- `OUTPUT_PATH` — markdown file to write, for example `benchmark.md`.
- Optional `FOCUS` — narrow the matrix to specific capabilities or frameworks.

## Method

1. List all `*.md` reports in `STUDIES_DIR`.
2. For each report, extract:
   - framework name;
   - repo URL, commit, branch, and studied date when available;
   - TL;DR verdict bullets;
   - direct answers for the core matrix rows below;
   - caveats and `Not provided — BYO` gaps.
3. Normalize findings into the rating legend.
4. Write a markdown table first, followed by short notes that cite the source report sections.
5. If a report lacks enough evidence for a cell, use `?` and add a note listing the missing evidence.

## Rating Legend

- `🟢` Built-in or first-party support that directly fits the use case.
- `🟡` Partial support: useful primitives exist, but production use needs host glue or custom policy.
- `🔴` Not provided or effectively BYO.
- `?` Unknown from the generated report.

## Core Matrix Rows

Use these rows by default:

- Documentation depth
- Framework weight / footprint
- Vendor lock-in
- Where the agent loop executes
- Streaming chat / UI primitives
- Agent API / server surface
- Live event stream taxonomy
- Session persistence
- Durable mid-run checkpointing
- Concurrent session isolation
- Horizontal scaling model
- Background / async task runtime
- ReAct loop
- Tool dispatch and result handling
- Arbitrary tenant/user context
- Forced server-side tool arguments
- Tenant-aware visible tool filtering
- Per-tenant budget or rate caps
- Hooks / middleware depth
- Auto-compaction
- Prompt-cache optimization
- Tool result clearing / progressive disclosure
- Markdown skills
- On-demand skill loading
- Skill/tool scoping: global / tenant / user
- Sub-agents and parallel fan-out
- Resource manager / registry
- Resource versioning and publish workflow
- Usage / token / cost observability
- Audit log support
- Built-in tools
- MCP support
- Multi-model routing and fallback
- Memory / RAG primitives
- Guardrails
- Tool sandboxing / permission model
- Eval and CI gates
- Local sandbox / dev UX

## Output Structure

```markdown
# AI Framework Benchmark Matrix

> Generated from reports in `<STUDIES_DIR>`.

## Summary

[3-6 bullets with the strongest cross-framework conclusions.]

## Matrix

| Capability | Framework A | Framework B | ... |
| --- | --- | --- | --- |
| Session persistence | 🟢 Short verdict | 🟡 Short verdict | ... |

## Notes

- `Framework A`: key caveats and source report sections.
- `Framework B`: key caveats and source report sections.

## Open Questions

- Cells marked `?` and the evidence needed to resolve them.
```

## Rules

- Keep each table cell short: rating plus a 2-8 word verdict.
- Do not hide major caveats in the notes if they change the rating.
- Preserve the distinction between first-party support and host-built glue.
- Avoid broad claims that are not backed by a generated report.
- Do not use domain-specific wording beyond the benchmark goal: a long-running agent piloted by skills with multi-tenancy.
