---
name: create-benchmark
description: "Orchestrate benchmark synthesis after `analyse-ai-framework` reports exist: read taxonomy, spawn one score-benchmark-category worker per taxonomy section, merge per-category CSVs into canonical benchmark data, and write a concise markdown summary."
---

# Create Benchmark Bundle

You create the final benchmark bundle from generated framework reports. Do not re-analyse frameworks unless a report is missing or contradictory. Prefer evidence already present in `docs/reports/*.md`.

The canonical output is CSV data plus a short markdown executive summary. Do not generate the HTML/JavaScript viewer here; the viewer is maintained separately and reads the CSV files.

## Inputs

- `REPORTS_DIR` — generated framework reports, usually `docs/reports/`.
- `OUTPUT_DIR` — benchmark bundle directory, default `docs/`.
- Optional `FOCUS` — narrow to specific sections, rows, or frameworks.
- Optional `TITLE` — default `Stack Choice: Where the Agent Loop Lives`.
- Optional `INCLUDE_BASELINE` — include a hand-built baseline column such as `Harden POC (Go)` when evidence exists outside generated reports.
- Optional `OUT_OF_SCOPE` — frameworks considered but intentionally excluded or only mentioned in scope notes.
- Optional `OUTPUT_FORMAT` — `bundle` by default. Use `markdown` only when explicitly requested.

## Bundle Shape

For `OUTPUT_FORMAT=bundle`, the final layout is:

```text
<OUTPUT_DIR>/
  data/
    taxonomy.csv
    sections.csv
    frameworks.csv
    scores.csv
  benchmark.md
```

During the run, category workers also write transient files under `<OUTPUT_DIR>/work/<section_order>-<section_slug>/scores.csv`. This directory is removed at the end of the workflow and is gitignored.

Artifact roles:

- `data/taxonomy.csv` — copy of `references/taxonomy.csv`; section/row order, user-facing legends, and scoring guidance.
- `data/sections.csv` — copy of `references/sections.csv`; one short user-facing definition per taxonomy section, rendered inline next to the section header in the viewer.
- `data/frameworks.csv` — one row per framework in scope.
- `data/scores.csv` — canonical merged score, short cell note, and longer details cells.
- `benchmark.md` — concise executive summary for GitHub and slide preparation, derived from the CSVs.
- `work/` — transient scratch space for per-category worker output; deleted before the workflow returns.

## Taxonomy

`references/taxonomy.csv` is the single source of truth for rows. `references/sections.csv` is the single source of truth for one-line, user-facing definitions of each taxonomy section (used inline by the viewer next to the section header). Do not duplicate either file's content in this skill.

Use `scripts/load_taxonomy.py` to inspect it:

```bash
python3 .agents/skills/create-benchmark/scripts/load_taxonomy.py --list-sections
python3 .agents/skills/create-benchmark/scripts/load_taxonomy.py --section "General" --format markdown
python3 .agents/skills/create-benchmark/scripts/load_taxonomy.py --section-order 0 --format json
```

CSV columns:

- `section_order` — numeric ordering for section groups.
- `section` — group label.
- `row` — matrix row label.
- `legend` — user-facing explanation displayed in the benchmark output.
- `expected` — agent-facing guidance for scoring.

## Workflow

1. Create `<OUTPUT_DIR>/data/` and `<OUTPUT_DIR>/work/`.
2. Copy `references/taxonomy.csv` to `<OUTPUT_DIR>/data/taxonomy.csv` and `references/sections.csv` to `<OUTPUT_DIR>/data/sections.csv`.
3. Resolve frameworks in scope and write `<OUTPUT_DIR>/data/frameworks.csv`.
4. Load taxonomy sections with `scripts/load_taxonomy.py --list-sections`.
5. Spawn one `score-benchmark-category` worker per taxonomy section in scope.
6. Give each worker:
   - `REPORTS_DIR`
   - `OUTPUT_DIR`
   - `section_order` and `section`
   - framework list/order
   - any `FOCUS` constraints
7. Wait for all category workers to finish.
8. Merge category files from `<OUTPUT_DIR>/work/*/` into `<OUTPUT_DIR>/data/scores.csv`.
9. Generate `benchmark.md` from canonical CSV data.
10. Remove `<OUTPUT_DIR>/work/` once the merged `data/` files and `benchmark.md` are written. Only delete after verifying the canonical files exist and are non-empty; if the merge fails, leave `work/` in place for inspection.

If the runtime cannot spawn sub-agents, emulate the same shape locally: process one category at a time and write the same per-category files before merging.

## Frameworks CSV

Write `<OUTPUT_DIR>/data/frameworks.csv` with:

```csv
framework_id,label,language,report_path,repo_url,commit,branch,analysed_date,notes
```

Use stable lowercase `framework_id` values such as `langgraph`, `mastra`, `openai-agents-python`.

If the user names specific frameworks, treat that as a hard framework focus:

- include only those framework reports;
- pass only those frameworks to `score-benchmark-category`;
- do not include other reports in `frameworks.csv`, `scores.csv`, or `benchmark.md`;
- if a requested framework report is missing, stop and report the missing file instead of silently substituting another framework.

## Merge Rules

- Read category files only after the corresponding worker has completed.
- Merge by ascending `section_order`, then row order from `data/taxonomy.csv`, then framework order from `data/frameworks.csv`.
- Reject or fix rows whose `(section_order, section, row)` is absent from taxonomy.
- Preserve blank scores for not-applicable cells.
- Preserve `?` scores; keep missing-evidence explanations inside the `details` column.
- If duplicate cells exist, resolve them by checking the reports; otherwise flag an integration conflict in `benchmark.md`.
- Do not alter worker scores silently when calibrating. If the main agent changes a score, update the canonical score note and `details` to explain why.

## Canonical CSV Schemas

`data/sections.csv`:

```csv
section_order,section,definition
```

- One row per taxonomy section (matches the distinct `(section_order, section)` pairs in `taxonomy.csv`).
- `definition` is one short sentence (≤ ~30 words) shown inline next to the section header in the viewer.

`data/scores.csv`:

```csv
section_order,section,row,framework_id,score,note,details
```

Score rules:

- blank score means not applicable.
- `?` means applicable but evidence is missing.
- `0` to `5` means scored.
- `note` is the short cell label shown next to the score bar: 3-5 words, no leading score prefix (the bar shows the score).
- `details` is the long-form explanation shown on cell hover and in the details pane: up to 5 sentences focused on why the score is what it is.
- Row legends stay in `data/taxonomy.csv`.
- Some rows are label-only. For those, leave `score` blank and use `note` plus `details` instead. `Stack type` is the main example.

## Markdown Summary

`benchmark.md` is not the source of truth. Keep it short:

- title and generation context;
- score legend;
- 3-6 executive conclusions;
- top recommended stacks and why;
- major disqualifiers or high-risk gaps;
- note that canonical data lives under `data/`.

Score legend:

- `0`: no support.
- `1`: minimal primitive, large host effort.
- `2`: partial primitive, mostly host-built.
- `3`: usable support with meaningful gaps.
- `4`: strong support with minor gaps.
- `5`: first-class fit for the benchmark.

Score display:

- Render scores as a 5-segment progress bar in the HTML viewer, not as a plain numeral badge.
- Leave the bar empty when the cell is label-only or not applicable.
- Keep the short note visible in the cell and reserve the longer `details` text for the side panel.

## Rules

- Treat `data/*.csv` as canonical. Derive `benchmark.md` from those files.
- Use `score-benchmark-category` for category scoring; keep row-level scoring details out of this orchestrator.
- Preserve the distinction between first-party support and host-built glue.
- Avoid broad claims that are not backed by generated reports.
- Do not use domain-specific wording beyond the benchmark goal: a long-running, skills-piloted agent exposed to external clients, with per-tenant tool and skill scoping enforced by the runtime rather than the LLM.
