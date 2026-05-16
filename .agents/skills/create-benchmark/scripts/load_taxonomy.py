#!/usr/bin/env python3
"""Load benchmark taxonomy sections for create-benchmark sub-agents."""

from __future__ import annotations

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TAXONOMY = SKILL_DIR / "references" / "taxonomy.csv"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"section_order", "section", "row", "legend", "expected"}
    if not rows:
        raise SystemExit(f"No taxonomy rows found in {path}")
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"Missing taxonomy columns in {path}: {', '.join(sorted(missing))}")
    return rows


def group_sections(rows: list[dict[str, str]]) -> OrderedDict[tuple[str, str], list[dict[str, str]]]:
    sections: OrderedDict[tuple[str, str], list[dict[str, str]]] = OrderedDict()
    for row in rows:
        key = (row["section_order"], row["section"])
        sections.setdefault(key, []).append(row)
    return sections


def select_rows(
    rows: list[dict[str, str]],
    section: str | None,
    section_order: str | None,
) -> list[dict[str, str]]:
    if section is None and section_order is None:
        return rows
    selected = []
    for row in rows:
        section_matches = section is None or row["section"].lower() == section.lower()
        order_matches = section_order is None or row["section_order"] == section_order
        if section_matches and order_matches:
            selected.append(row)
    if not selected:
        criteria = []
        if section is not None:
            criteria.append(f"section={section!r}")
        if section_order is not None:
            criteria.append(f"section_order={section_order!r}")
        raise SystemExit(f"No taxonomy rows matched {', '.join(criteria)}")
    return selected


def print_sections(rows: list[dict[str, str]]) -> None:
    for (section_order, section), section_rows in group_sections(rows).items():
        print(f"{section_order}\t{section}\t{len(section_rows)} rows")


def print_markdown(rows: list[dict[str, str]]) -> None:
    for (section_order, section), section_rows in group_sections(rows).items():
        print(f"## {section_order}. {section}")
        print()
        for row in section_rows:
            print(f"- **{row['row']}**")
            print(f"  - Legend: {row['legend']}")
            print(f"  - Scoring: {row['expected']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--section", help="Section name to load, e.g. General")
    parser.add_argument("--section-order", help="Section order to load, e.g. 0")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format for selected rows",
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="Print available sections and row counts",
    )
    args = parser.parse_args()

    rows = load_rows(args.taxonomy)
    if args.list_sections:
        print_sections(rows)
        return

    selected = select_rows(rows, args.section, args.section_order)
    if args.format == "markdown":
        print_markdown(selected)
    else:
        print(json.dumps(selected, indent=2))


if __name__ == "__main__":
    main()
