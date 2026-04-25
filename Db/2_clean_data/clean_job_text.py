#!/usr/bin/env python3
"""Clean raw job HTML into a simpler text field for downstream LLM extraction.

This script is intentionally practical:
- it does not try to split requirements / benefits / company info into separate fields
- it only removes obvious UI/web noise and HTML artifacts
- it keeps the job content readable for a later LLM step

Example:
    Before:
        Apply now - Top 3 reasons to join us - Job description - Build and ship...

    After:
        Job description - Build and ship...
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


# Easy-to-edit noise phrases and line patterns.
NOISE_PATTERNS = [
    r"^sign in to view salary$",
    r"^apply now$",
    r"^posted(?:\s*[:\-–—].*)?$",
    r"^company type$",
    r"^company industry$",
    r"^company size$",
    r"^country$",
    r"^working days$",
    r"^overtime policy$",
    r"^top 3 reasons to join us$",
    r"^employees$",
    r"^save this job$",
    r"^job expertise$",
    r"^job domain$",
    r"^skills:?$",
    r"^at office$",
    r"^hybrid$",
    r"^remote$",
    r"^full[- ]time$",
    r"^search$",
    r"^share$",
    r"^follow$",
    r"^company info$",
    r"^about the company$",
    r"^overview$",
]

# Prefixes that can appear before a useful section heading.
SECTION_PREFIX_PATTERNS = [
    r"top 3 reasons",
    r"company type",
    r"company industry",
    r"company size",
    r"working days",
    r"overtime policy",
]

# Lines that strongly suggest the start of useful JD content.
CONTENT_HINTS = [
    r"job description",
    r"responsibilities",
    r"requirements?",
    r"your skills and experience",
    r"why you'll love working here",
    r"must have",
    r"what you bring",
    r"what you must bring",
    r"job requirements",
    r"job purpose",
    r"mô tả công việc",
    r"yêu cầu công việc",
    r"yêu cầu ứng viên",
    r"bắt buộc",
    r"ưu tiên",
]


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities."""

    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " \n ", text)
    return text


def _normalize_text(text: str) -> str:
    """Normalize whitespace and separator noise."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _looks_like_noise(line: str) -> bool:
    """Return True for obvious UI/web noise lines."""

    normalized = re.sub(r"\s+", " ", line).strip().lower()
    if not normalized:
        return True

    for pattern in NOISE_PATTERNS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return True

    # Short metadata lines are usually not helpful for LLM extraction.
    if normalized in {"sign in", "apply", "job", "jobs"}:
        return True

    return False


def _remove_section_noise_prefix(line: str) -> str:
    """Remove simple section labels that are known to be noise.

    The goal is to keep the actual JD content, not to split it into fields.
    """

    cleaned = line.strip()
    for pattern in SECTION_PREFIX_PATTERNS:
        cleaned = re.sub(rf"^(?:{pattern})\s*[:\-–—]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _remove_exact_noise_phrases(text: str) -> str:
    """Remove obvious UI phrases anywhere they appear in the text."""

    replacements = [
        "Sign in to view salary",
        "Apply now",
        "Top 3 reasons to join us",
        "Company type",
        "Company industry",
        "Company size",
        "Country",
        "Working days",
        "Overtime policy",
        "Posted",
    ]

    cleaned = text
    for phrase in replacements:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def clean_description_html(text: str) -> str:
    """Convert raw job HTML into a cleaner plain-text block."""

    if not text:
        return ""

    text = _strip_html(text)
    text = _normalize_text(text)

    # Remove the most obvious UI/web phrases without trying to parse the JD.
    text = _remove_exact_noise_phrases(text)

    # Turn line-based content into a readable block and remove obvious noise.
    lines = []
    for raw_line in text.splitlines():
        line = _remove_section_noise_prefix(raw_line)
        line = re.sub(r"\s+", " ", html.unescape(line)).strip()
        if line and not _looks_like_noise(line):
            lines.append(line)

    cleaned_lines: list[str] = []
    previous = ""
    for line in lines:
        if line == previous:
            continue
        cleaned_lines.append(line)
        previous = line

    cleaned_text = " - ".join(cleaned_lines)
    cleaned_text = re.sub(r"(?:\s*-\s*){2,}", " - ", cleaned_text)
    cleaned_text = re.sub(r"\s{2,}", " ", cleaned_text)
    cleaned_text = re.sub(r"\s+-\s+", " - ", cleaned_text)
    return cleaned_text.strip(" -")


def process_jobs(input_path: str | Path, output_path: str | Path) -> None:
    """Read jobs from JSON, add cleaned_job_text, and write a new JSON file."""

    input_file = Path(input_path)
    output_file = Path(output_path)

    jobs = json.loads(input_file.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise ValueError("Input JSON must be a list of job objects")

    cleaned_jobs: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue

        cleaned_job = dict(job)
        cleaned_job["cleaned_job_text"] = clean_description_html(str(job.get("description_html") or ""))
        cleaned_jobs.append(cleaned_job)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(cleaned_jobs, ensure_ascii=False, indent=4), encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean raw job HTML into cleaned_job_text")
    parser.add_argument("input_path", help="Path to the input JSON file")
    parser.add_argument("output_path", help="Path to the output JSON file")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    process_jobs(args.input_path, args.output_path)


if __name__ == "__main__":
    main()