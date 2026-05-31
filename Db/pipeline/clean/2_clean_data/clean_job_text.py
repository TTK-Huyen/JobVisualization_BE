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


HTML_TAG_NAMES = (
    "div|p|span|a|li|ul|ol|h[1-6]|b|i|strong|em|u|br|hr|table|tr|td|th|thead|tbody|"
    "ins|del|code|pre|blockquote|section|article|aside|header|footer|nav|svg|template|"
    "script|style|img|iframe|button|form|input|label|select|option|textarea|hgroup|"
    "figure|figcaption|details|summary|main|body|html|head|meta|link|title|picture|source"
)
HTML_TAG_RE = re.compile(rf'</?(?:{HTML_TAG_NAMES})\b[^>]*>', re.I)


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities."""

    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = HTML_TAG_RE.sub(" \n ", text)
    return text


def _extract_sections_from_html_by_headings(html_text: str, headings: list[str]) -> dict:
    """Extract text segments from raw HTML by locating heading keywords.

    Returns a dict mapping heading -> html segment (still containing tags).
    This is a lightweight extractor (no full HTML parser) designed to work
    for patterns commonly found on CareerViet: headings followed by content
    until the next heading.
    """
    if not html_text:
        return {}

    lower = html_text.lower()
    positions = []
    for h in headings:
        idx = lower.find(h.lower())
        if idx != -1:
            positions.append((idx, h))

    if not positions:
        return {}

    positions.sort()
    segments = {}
    for i, (pos, h) in enumerate(positions):
        start = pos
        end = len(html_text)
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        seg = html_text[start:end]
        segments[h] = seg

    return segments


def _clean_html_segment_to_text(segment: str) -> str:
    """Strip tags from an HTML segment and normalize whitespace."""
    if not segment:
        return ""
    text = html.unescape(segment)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    # Replace tags with newlines for clearer section separation
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = HTML_TAG_RE.sub("\n", text)
    text = _normalize_text(text)
    return text.strip()


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

    s = str(text)
    # First, decode HTML entities so encoded tags like &lt;ins&gt; become real tags
    s = html.unescape(s)

    # Remove HTML comments
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)

    # Remove clearly non-content elements
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<svg[^>]*>.*?</svg>", " ", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<template[^>]*>.*?</template>", " ", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<\?[^>]*\?>", " ", s, flags=re.IGNORECASE)  # Remove XML/PHP declarations
    
    # Remove hidden inputs
    s = re.sub(r"<input\b[^>]*type=[\"']?hidden[\"']?[^>]*>", " ", s, flags=re.IGNORECASE)

    # Remove common attribute patterns so class/style names don't leak into text
    s = re.sub(r"\s(class|style|id|data-[a-zA-Z0-9_-]+)\s*=\s*(\".*?\"|'.*?'|[^\s>]+)", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s[a-zA-Z0-9_-]+=(\".*?\"|'.*?'|[^\s>]+)", " ", s)

    # Explicitly remove small inline tags that sometimes survive (ins, del, span, p, br, u, b, i)
    s = re.sub(r"</?(?:ins|del|u|span|p|br|b|i)\b[^>]*>", " ", s, flags=re.IGNORECASE)

    # Strip any remaining tags using the specific HTML tag regex
    s = HTML_TAG_RE.sub(" ", s)

    # Ensure entities decoded (idempotent)
    s = html.unescape(s)

    # Remove obvious skeleton/loading artifact words
    s = re.sub(r"\b(skeleton|loading|placeholder|spinner|progress)\b", " ", s, flags=re.IGNORECASE)

    # Collapse separators and leftover punctuation
    s = re.sub(r"[_\-\|]{2,}", " ", s)

    # Normalize whitespace and newlines
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"\n[ \t]+\n", "\n\n", s)
    s = re.sub(r" {2,}", " ", s)
    s = s.strip()

    return s


def process_jobs(input_path: str | Path, output_path: str | Path) -> None:
    """Read jobs from JSON, add cleaned_job_text, and write a new JSON file."""

    input_file = Path(input_path)
    output_file = Path(output_path)

    jobs = json.loads(input_file.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise ValueError("Input JSON must be a list of job objects")

    cleaned_jobs: list[dict[str, Any]] = []
    lengths: list[int] = []
    lt_with_angle = 0
    very_short = 0

    for job in jobs:
        if not isinstance(job, dict):
            continue

        cleaned_job = dict(job)
        req = clean_description_html(str(job.get("description_html") or ""))
        cleaned_job["requirements_text"] = req
        cleaned_jobs.append(cleaned_job)

        lengths.append(len(req))
        if "<" in req or ">" in req:
            lt_with_angle += 1
        if len(req) < 100:
            very_short += 1

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(cleaned_jobs, ensure_ascii=False, indent=4), encoding="utf-8")

    # Simple validation stats
    total = len(cleaned_jobs)
    non_empty = sum(1 for l in lengths if l > 0)
    min_len = min(lengths) if lengths else 0
    avg_len = (sum(lengths) / len(lengths)) if lengths else 0
    max_len = max(lengths) if lengths else 0

    print(f"total_jobs: {total}")
    print(f"non_empty_requirements_text: {non_empty}")
    print(f"length_chars: min={min_len} avg={avg_len:.1f} max={max_len}")
    print(f"records_with_angle_chars: {lt_with_angle}")
    print(f"very_short_records(<100 chars): {very_short}")


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