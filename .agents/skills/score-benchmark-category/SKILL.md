---
name: score-benchmark-category
description: "Score one benchmark taxonomy category across all AI framework reports. Used by create-benchmark sub-agents: load one taxonomy section, compare all frameworks row-by-row, and write category-local scores.csv and evidence.csv under OUTPUT_DIR/work/."
---

# Score Benchmark Category

You score exactly one taxonomy category for the AI framework benchmark. This skill is designed for sub-agents spawned by `create-benchmark`.

Your job is comparative scoring, not report generation. Work row-by-row across all frameworks so scores are calibrated within the category.

## Inputs

- `REPORTS_DIR` — generated framework reports, usually `reports/`.
- `OUTPUT_DIR` — benchmark bundle directory, usually `benchmark/`.
- `section_order` or `section` — the single taxonomy section you own.
- framework list/order from `create-benchmark`.
- Optional `FOCUS` — row or framework constraints.

The framework list from `create-benchmark` is authoritative. Score only those frameworks, even if additional reports exist in `REPORTS_DIR`.

## Taxonomy

Load only your assigned category from the orchestrator skill:

```bash
python3 .agents/skills/create-benchmark/scripts/load_taxonomy.py --section-order <N> --format markdown
python3 .agents/skills/create-benchmark/scripts/load_taxonomy.py --section "<Name>" --format json
```

Use:

- `row` as the score row label.
- `expected` as your scoring rubric.
- `legend` only as display text for the final benchmark; do not let a vague legend override precise `expected` guidance.
- `details` as the required long-form cell explanation for the viewer when you write scores.

Never edit taxonomy. Taxonomy changes must be made in `create-benchmark/references/taxonomy.csv` before scoring.

## Output Files

Write only category-local files:

```text
<OUTPUT_DIR>/work/<section_order>-<section_slug>/scores.csv
<OUTPUT_DIR>/work/<section_order>-<section_slug>/evidence.csv
```

Do not write final shared files under `<OUTPUT_DIR>/data/`; the caller merges those after all categories finish.

`scores.csv` schema:

```csv
section_order,section,row,framework_id,score,note,details
```

`evidence.csv` schema:

```csv
section_order,section,row,framework_id,report_path,report_section,line_ref,evidence_note
```

Write headers first. Append results incrementally after each taxonomy row is scored so progress is durable if the worker is interrupted.

## Scoring Workflow

For each row in your assigned category:

1. Read the row's `expected` guidance.
2. Locate the relevant evidence in every framework report.
3. Bring evidence for all frameworks into the same working context.
4. Compare the strongest, weakest, and middle cases.
5. Assign each framework cell a score, note, or both.
6. Append that row's cells to `scores.csv`.
7. Append evidence references and caveats to `evidence.csv`.
8. Move to the next row.

Do not score one framework end-to-end before moving to the next. A `3` in one framework must mean the same level of support as a `3` in another framework for the same row.

## Score Meaning

- blank score: not applicable to that stack.
- `?`: applicable, but generated reports lack enough evidence.
- `0`: the framework does not provide the feature at all.
- `1`: a small primitive exists, but large effort around the framework is needed.
- `2`: partial primitive exists, but production use is mostly host-built.
- `3`: usable support exists, with meaningful integration or policy gaps.
- `4`: strong support exists, with minor gaps or non-default setup.
- `5`: first-class capability that directly fits the benchmark use case.

Preferred note format:

- `5 — first-class Postgres checkpointer`
- `2 — interface only, BYO store`
- `0 — no skill concept`

Keep notes short: 2-8 words where possible.

Details format:

- `details` is required for scored cells unless the row is label-only or the evidence is genuinely trivial.
- Write 3 sentences when the row needs context, comparison, or caveats.
- For label-only rows such as `Stack type`, use `note` for the one-word display label and `details` for the explanatory rationale.
- Keep the long note focused on why the score is what it is, not on rehashing the taxonomy legend.

## Evidence Rules

- Prefer report section and line references over long quotes.
- Keep `evidence_note` concise but sufficient to audit the score.
- For `?`, write the missing-evidence reason in `evidence.csv`.
- If evidence conflicts across a report, use `?` or a conservative score and note the conflict.
- Do not make claims unsupported by generated reports.

## Category Completion Response

When finished, return a short summary:

```markdown
## <section_order>. <section>

- Rows scored: N
- Frameworks scored: N
- Scores written: <OUTPUT_DIR>/work/<section_order>-<section_slug>/scores.csv
- Evidence written: <OUTPUT_DIR>/work/<section_order>-<section_slug>/evidence.csv
- Open questions: N
- Integration warnings: ...
```

Do not paste the full CSV in the final response; the caller reads the files.
