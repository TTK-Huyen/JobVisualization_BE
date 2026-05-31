#!/usr/bin/env python3
"""Analyze missing-field rates for a crawled job batch.

The script accepts either a single JSON file (for example jobs_combined.json)
or a directory containing JSON files. It reports missing counts and missing
rates for schema fields, both overall and grouped by source_name when available.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "input" / "crawl_schema.json"
DEFAULT_INPUT = ROOT / "data"


def load_schema_fields() -> tuple[list[str], list[str]]:
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot read schema file: {SCHEMA_PATH}") from exc

    required = list(schema.get("required") or [])
    optional = list(schema.get("optional") or [])
    return required, optional


def is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def load_json_items(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def iter_input_files(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        yield input_path
        return

    for path in sorted(input_path.rglob("*.json")):
        if path.name in {"selected_keywords.json"}:
            continue
        yield path


def analyze(path: Path) -> dict[str, Any]:
    required_fields, optional_fields = load_schema_fields()
    all_fields = required_fields + optional_fields

    stats = {
        "overall": {
            "total": 0,
            "filled": defaultdict(int),
            "missing": defaultdict(int),
        },
        "by_source": defaultdict(lambda: {
            "total": 0,
            "filled": defaultdict(int),
            "missing": defaultdict(int),
        }),
        "required_fields": required_fields,
        "optional_fields": optional_fields,
        "all_fields": all_fields,
    }

    for file_path in iter_input_files(path):
        try:
            items = load_json_items(file_path)
        except Exception as exc:
            print(f"[WARN] Skip invalid JSON: {file_path} ({exc})")
            continue

        for item in items:
            source = str(item.get("source_name") or "unknown").strip().lower() or "unknown"
            stats["overall"]["total"] += 1
            stats["by_source"][source]["total"] += 1

            for field in all_fields:
                filled = is_filled(item.get(field))
                if filled:
                    stats["overall"]["filled"][field] += 1
                    stats["by_source"][source]["filled"][field] += 1
                else:
                    stats["overall"]["missing"][field] += 1
                    stats["by_source"][source]["missing"][field] += 1

    return stats


def rate(part: int, total: int) -> float:
    return (part / total * 100.0) if total else 0.0


def build_markdown_report(stats: dict[str, Any], input_path: Path) -> str:
    total = stats["overall"]["total"]
    fields = stats["all_fields"]
    required_fields = set(stats["required_fields"])

    lines = []
    lines.append("# Field Missing Rate Report")
    lines.append("")
    lines.append(f"- Input: {input_path}")
    lines.append(f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- Total records: {total}")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append("| Field | Type | Filled | Missing | Missing rate |")
    lines.append("| :--- | :--- | ---: | ---: | ---: |")
    for field in fields:
        filled = stats["overall"]["filled"][field]
        missing = stats["overall"]["missing"][field]
        kind = "required" if field in required_fields else "optional"
        lines.append(
            f"| `{field}` | {kind} | {filled} | {missing} | {rate(missing, total):.1f}% |"
        )

    lines.append("")
    lines.append("## By Source")
    lines.append("")
    for source, source_stats in sorted(stats["by_source"].items()):
        source_total = source_stats["total"]
        lines.append(f"### {source}")
        lines.append("")
        lines.append("| Field | Filled | Missing | Missing rate |")
        lines.append("| :--- | ---: | ---: | ---: |")
        for field in fields:
            filled = source_stats["filled"][field]
            missing = source_stats["missing"][field]
            lines.append(f"| `{field}` | {filled} | {missing} | {rate(missing, source_total):.1f}% |")
        lines.append("")

    return "\n".join(lines)


def write_csv_report(stats: dict[str, Any], output_path: Path) -> None:
    total = stats["overall"]["total"]
    fields = stats["all_fields"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scope", "source", "field", "total_records", "filled", "missing", "missing_rate_pct"])

        for field in fields:
            filled = stats["overall"]["filled"][field]
            missing = stats["overall"]["missing"][field]
            writer.writerow(["overall", "all", field, total, filled, missing, f"{rate(missing, total):.1f}"])

        for source, source_stats in sorted(stats["by_source"].items()):
            source_total = source_stats["total"]
            for field in fields:
                filled = source_stats["filled"][field]
                missing = source_stats["missing"][field]
                writer.writerow(["source", source, field, source_total, filled, missing, f"{rate(missing, source_total):.1f}"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze missing-field rates for a crawled job batch.")
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_INPUT),
        help="Path to jobs_combined.json or a folder containing JSON files.",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        help="Optional output path for a markdown report.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional output path for a CSV report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_path)

    if not input_path.exists():
        print(f"[ERROR] Input path not found: {input_path}")
        return 2

    stats = analyze(input_path)
    report = build_markdown_report(stats, input_path)
    print(report)

    if args.markdown:
        markdown_path = Path(args.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(report, encoding="utf-8")
        print(f"[OK] Markdown report saved to: {markdown_path}")

    if args.csv:
        csv_path = Path(args.csv)
        write_csv_report(stats, csv_path)
        print(f"[OK] CSV report saved to: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())