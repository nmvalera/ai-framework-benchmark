---
name: benchmark-ai-frameworks
description: >-
  Orchestrate the full AI framework benchmark flow from framework-index.json:
  prepare framework submodules, run one analyse-ai-framework report per framework
  in dedicated parallel sub-agents, then synthesize reports with create-benchmark.
  Use when refreshing all framework reports, adding a new framework to the
  benchmark, or generating the overall comparison matrix.
---

# Benchmark AI Frameworks

This skill coordinates the full benchmark workflow. It does not replace `analyse-ai-framework` or `create-benchmark`; it sequences them across the framework set.

## Inputs

- `FRAMEWORK_INDEX` — usually `framework-index.json`.
- `FRAMEWORKS_DIR` — usually `frameworks/`.
- `REPORTS_DIR` — usually `reports/`.
- `MATRIX_OUTPUT_PATH` — usually `docs/benchmark.md`.
- Optional `FOCUS` — a subset of framework ids or benchmark capabilities.

## Workflow

1. Read `FRAMEWORK_INDEX` and validate that every selected framework has:
   - `id`
   - `name`
   - `ecosystem`
   - either `repo_url` + `framework_path`, `repos[]`, or `repo_url: "LOCAL"` + `local_path`
   - `report_path`
2. Add or update the listed framework repositories under `FRAMEWORKS_DIR`.
   - Use Git submodules for external repos.
   - For multi-repo frameworks, initialize each `repos[]` entry.
   - For `LOCAL`, verify the local path exists and record its current commit/branch.
3. Run each framework analysis with `analyse-ai-framework`.
   - Each analysis must run in a dedicated sub-agent with its own context.
   - Launch independent framework analyses in parallel whenever possible.
   - Give each sub-agent exactly one framework entry, its framework path(s), and its report path.
   - Tell sub-agents to preserve and update an existing report if `report_path` already exists.
   - Sub-agents must not edit reports owned by other framework analyses.
4. Wait for all selected framework analysis sub-agents to complete.
5. Check coverage:
   - every selected framework has a report at `report_path`;
   - every selected report records repo URL, commit, branch when available, framework path, and analysed date;
   - every selected report follows the section list and numbering defined by the `analyse-ai-framework` skill. This skill does not duplicate that list; the canonical source lives in the `analyse-ai-framework` skill's `references/` directory.
6. Run `create-benchmark` with `REPORTS_DIR`, `MATRIX_OUTPUT_PATH`, and optional `FOCUS`.
7. Return a short summary:
   - frameworks analysed or refreshed;
   - reports changed;
   - benchmark matrix path;
   - blockers, missing evidence, or failed sub-agent runs.

## Sub-Agent Contract

Use one worker sub-agent per framework. A worker owns only:

- its external framework checkout path(s) under `frameworks/`;
- its one report file under `reports/`;
- no other reports, skills, or benchmark matrix files.

Sub-agent prompt shape:

```text
Use the analyse-ai-framework skill for exactly this framework.

Framework entry:
<single JSON object from framework-index.json>

Inputs:
- STACK_NAME: <name>
- REPO_URL / LOCAL_PATHS: <from framework entry>
- FRAMEWORK_PATH: <framework_path or repos[].framework_path>
- OUTPUT_PATH: <report_path>

Preserve useful existing report content if OUTPUT_PATH exists. Update it against the current repo, online docs, changelog, and GitHub Releases. Do not edit other framework reports.
```

## Rules

- Treat `framework-index.json` as the source of truth for the public/currently selected benchmark set. Local or private reports may exist outside the index and should be ignored unless the user explicitly selects them.
- Keep framework ids stable; changing an id changes report ownership and matrix columns.
- Do not synthesize the matrix until all selected analyses have completed or failed clearly.
- Do not fill matrix cells from memory when the corresponding report lacks evidence; use `?` and list missing evidence.
