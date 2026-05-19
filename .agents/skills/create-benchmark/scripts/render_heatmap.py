#!/usr/bin/env python3
"""Render the category × framework heatmap shown at the top of benchmark.md.

Reads canonical data from `<OUTPUT_DIR>/data/`:
- taxonomy.csv (for category order)
- frameworks.csv (for framework order and labels)
- scores.csv (for cell values)

Emits a markdown table with one row per taxonomy section and one column per
framework. Cells show a colored square plus the numeric mean of that section's
numeric scores for that framework:

- 🟥 mean < 2.0
- 🟨 2.0 <= mean < 3.5
- 🟩 mean >= 3.5
- ⬜  no scorable cells in that (section, framework)

A final "Overall mean" row averages every numeric cell per framework.

Label-only rows (Stack type, Ecosystem / primary language) have blank scores
and are skipped from means by design — they live in the cell `note` column.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def short_label(label: str) -> str:
    """Compact a framework label for table headers without losing identity."""
    table = {
        "ADK Go": "ADK Go",
        "Agno Python": "Agno",
        "AutoAgents Rust": "AutoAgents",
        "Claude Agent SDK Python": "Claude Py",
        "Claude Agent SDK TypeScript": "Claude TS",
        "CrewAI Python": "CrewAI",
        "Eino Go": "Eino",
        "Genkit Go": "Genkit",
        "LangGraph Python": "LangGraph",
        "LlamaIndex Python": "LlamaIndex",
        "Mastra TypeScript": "Mastra",
        "Microsoft Agent Framework": "MS AF",
        "OpenAI Agents Python": "OAI Py",
        "OpenAI Agents TypeScript": "OAI TS",
        "Pydantic AI": "Pydantic",
        "Rig Rust": "Rig",
        "Strands Agents Python": "Strands Py",
        "Strands Agents TypeScript": "Strands TS",
        "Vercel AI SDK TypeScript": "Vercel AI",
    }
    return table.get(label, label)


def color_square(mean: float | None) -> str:
    if mean is None:
        return "⬜"
    if mean < 2.0:
        return "🟥"
    if mean < 3.5:
        return "🟨"
    return "🟩"


def load_scores(scores_path: Path) -> list[dict[str, str]]:
    with scores_path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_frameworks(frameworks_path: Path) -> list[dict[str, str]]:
    with frameworks_path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_section_order(taxonomy_path: Path) -> list[tuple[str, str]]:
    """Return ordered (section_order, section) pairs as they appear in the taxonomy."""
    seen = set()
    out: list[tuple[str, str]] = []
    with taxonomy_path.open(newline="") as f:
        for row in csv.DictReader(f):
            key = (row["section_order"], row["section"])
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def render(data_dir: Path) -> str:
    scores = load_scores(data_dir / "scores.csv")
    frameworks = load_frameworks(data_dir / "frameworks.csv")
    sections = load_section_order(data_dir / "taxonomy.csv")

    fw_order = [f["framework_id"] for f in frameworks]
    fw_short = {f["framework_id"]: short_label(f["label"]) for f in frameworks}

    per_section: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    per_framework: dict[str, list[float]] = defaultdict(list)
    for row in scores:
        v = row["score"]
        if v in ("", "?"):
            continue
        try:
            f = float(v)
        except ValueError:
            continue
        key = (row["section_order"], row["section"])
        per_section[key][row["framework_id"]].append(f)
        per_framework[row["framework_id"]].append(f)

    def cell(values: list[float]) -> str:
        if not values:
            return "⬜"
        m = sum(values) / len(values)
        return f"{color_square(m)} {m:.1f}"

    def total_cell(values: list[float]) -> str:
        if not values:
            return "—"
        m = sum(values) / len(values)
        return f"**{color_square(m)} {m:.2f}**"

    lines: list[str] = []
    lines.append("Legend: 🟥 mean < 2.0 · 🟨 2.0–3.5 · 🟩 ≥ 3.5 · ⬜ not applicable.")
    lines.append("")
    header = "| Category | " + " | ".join(fw_short[fw] for fw in fw_order) + " |"
    sep = "| --- |" + "".join([" --- |"] * len(fw_order))
    lines.append(header)
    lines.append(sep)
    for so, sec in sections:
        cells = [cell(per_section[(so, sec)][fw]) for fw in fw_order]
        lines.append(f"| {so}. {sec} | " + " | ".join(cells) + " |")
    overall = [total_cell(per_framework[fw]) for fw in fw_order]
    lines.append("| **Overall mean** | " + " | ".join(overall) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("docs/data"),
        help="Directory containing taxonomy.csv, frameworks.csv, scores.csv.",
    )
    args = parser.parse_args()
    print(render(args.data_dir))


if __name__ == "__main__":
    main()
