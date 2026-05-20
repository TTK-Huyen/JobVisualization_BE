"""Create pending_llm.json by regex-cleaning original raw job files.

Usage:
    python scripts/create_pending_llm.py \
        --jobs_raw Db/evaluation_inputs/round_2_five_jobs/jobs_raw.json \
        --out Db/evaluation_inputs/round_2_five_jobs/pending_llm.json

The script uses utilities.clean_text_regex and utilities.extract_job_sections
and does NOT call any LLM.
"""
import argparse
import json
from pathlib import Path

import importlib.util

# Load utilities.py by path because the folder name starts with a digit and
# cannot be imported as a normal package name.
UTILS_PATH = Path(__file__).resolve().parent.parent / 'Db' / 'pipeline' / 'clean' / '2_clean_data' / 'utilities.py'
spec = importlib.util.spec_from_file_location('clean_utils', str(UTILS_PATH))
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)  # type: ignore


def process_raw_file(raw_path: Path, evaluation_entry: dict):
    try:
        with raw_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️  Could not open {raw_path}: {e}")
        return []

    cleaned_jobs = []
    for job in data:
        # Copy job to avoid mutating original
        cj = dict(job)

        # Prefer description_html then raw_html then title
        raw_html = job.get('description_html') or job.get('raw_html') or ''
        cleaned_text = utils.clean_text_regex(raw_html)
        sections = utils.extract_job_sections(cleaned_text)

        # Prefer requirements section; fallback to job_description or full cleaned text
        requirements = sections.get('requirements') or sections.get('job_description') or cleaned_text

        # Ensure requirements_text is populated for downstream LLM input
        cj['requirements_text'] = requirements
        cj['cleaned_text'] = cleaned_text

        # Preserve search keyword from evaluation entry if present
        if evaluation_entry and evaluation_entry.get('search_keyword') and not cj.get('search_keyword'):
            cj['search_keyword'] = evaluation_entry.get('search_keyword')

        cleaned_jobs.append(cj)

    return cleaned_jobs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs_raw', default='Db/evaluation_inputs/round_2_five_jobs/jobs_raw.json')
    parser.add_argument('--out', default='Db/evaluation_inputs/round_2_five_jobs/pending_llm.json')
    args = parser.parse_args()

    jobs_raw_path = Path(args.jobs_raw)
    out_path = Path(args.out)

    if not jobs_raw_path.exists():
        print(f"jobs_raw not found: {jobs_raw_path}")
        return

    with jobs_raw_path.open('r', encoding='utf-8') as f:
        jobs = json.load(f)

    all_cleaned = []
    for entry in jobs:
        original = entry.get('original_file')
        if not original:
            continue

        raw_path = Path(original)
        # If path is relative to repo root, resolve
        if not raw_path.exists():
            raw_path = Path(__file__).resolve().parent.parent.parent / original

        cleaned = process_raw_file(raw_path, entry)
        print(f"Processed {raw_path}: found {len(cleaned)} jobs")
        all_cleaned.extend(cleaned)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(all_cleaned, f, ensure_ascii=False, indent=2)

    print(f"Wrote pending LLM dataset: {out_path} ({len(all_cleaned)} jobs)")


if __name__ == '__main__':
    main()
