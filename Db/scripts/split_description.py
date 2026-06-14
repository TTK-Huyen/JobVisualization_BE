"""Utility to clean and extract job description HTML by source."""
from __future__ import annotations

import re
import html as html_lib
from typing import Optional


def extract_clean_job_description(source_name: str, description_html: str) -> str:
    """Clean raw description_html for a given job source.

    Removes boilerplate markup (scripts, styles, nav, header, footer) and
    normalises whitespace while keeping the core HTML structure intact so
    downstream renderers can still display it.

    Returns the cleaned string, or the original value when nothing useful
    can be extracted.
    """
    if not isinstance(description_html, str) or not description_html.strip():
        return description_html or ""

    txt = description_html

    # Strip noisy structural blocks
    txt = re.sub(r"<script[\s\S]*?</script>", " ", txt, flags=re.I)
    txt = re.sub(r"<style[\s\S]*?</style>", " ", txt, flags=re.I)
    txt = re.sub(r"<header[\s\S]*?</header>", " ", txt, flags=re.I)
    txt = re.sub(r"<nav[\s\S]*?</nav>", " ", txt, flags=re.I)
    txt = re.sub(r"<footer[\s\S]*?</footer>", " ", txt, flags=re.I)

    # Source-specific boilerplate removal
    src = (source_name or "").lower()
    if "careerviet" in src:
        # Remove share/apply button blocks common on CareerViet
        txt = re.sub(r"<div[^>]+class=['\"][^'\"]*(?:share|apply|social)[^'\"]*['\"][\s\S]*?</div>", " ", txt, flags=re.I)
    elif "itviec" in src:
        txt = re.sub(r"<div[^>]+class=['\"][^'\"]*(?:sidebar|widget)[^'\"]*['\"][\s\S]*?</div>", " ", txt, flags=re.I)
    elif "linkedin" in src:
        txt = re.sub(r"<section[^>]+class=['\"][^'\"]*(?:similar-jobs)[^'\"]*['\"][\s\S]*?</section>", " ", txt, flags=re.I)
    elif "vietnamworks" in src:
        txt = re.sub(r"<div[^>]+class=['\"][^'\"]*(?:related|recommend)[^'\"]*['\"][\s\S]*?</div>", " ", txt, flags=re.I)

    # Collapse excessive whitespace inside the remaining markup
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt)

    return txt.strip() or description_html
