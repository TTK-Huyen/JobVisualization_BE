#!/usr/bin/env python3
"""Run bootstrap crawls in keyword batches and prepare pending-LLM inputs.

Behavior:
- Load all keywords from the shared daily keyword config.
- Crawl them in groups of 4 keywords.
- Pause a fixed amount between groups.
- Print per-keyword job counts after each crawl.
- Write the combined bootstrap output to data/bootstrap/data_mmddyyyy.json.
- Split the final job list into 1000-job batch files for downstream LLM work.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import run_etl_pipeline as pipeline


BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_KEYWORDS_FILE = BASE_DIR / "pipeline" / "crawl" / "1_crawl_data" / "crawl_data" / "keywords_daily.json"
BOOTSTRAP_DIR = BASE_DIR / "data" / "bootstrap"
BOOTSTRAP_BATCH_DIR = BOOTSTRAP_DIR / "batches"
DEFAULT_KEYWORD_BATCH_SIZE = 4
DEFAULT_PAUSE_SECONDS = 300
DEFAULT_JOB_BATCH_SIZE = 1000
DEFAULT_MAX_JOBS = 150
DEFAULT_MAX_PAGES = 8
DEFAULT_SOURCES = "itviec,careerviet,vietnamworks,linkedin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl all bootstrap keywords in small batches and prepare LLM input files.",
    )
    parser.add_argument(
        "--keywords-file",
        type=Path,
        default=DEFAULT_KEYWORDS_FILE,
        help="Path to keywords_daily.json (default: pipeline/crawl/1_crawl_data/crawl_data/keywords_daily.json)",
    )
    parser.add_argument(
        "--keyword-batch-size",
        type=int,
        default=DEFAULT_KEYWORD_BATCH_SIZE,
        help="How many keywords to crawl before pausing (default: 4)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=int,
        default=DEFAULT_PAUSE_SECONDS,
        help="Pause between keyword batches in seconds (default: 300)",
    )
    parser.add_argument(
        "--job-batch-size",
        type=int,
        default=DEFAULT_JOB_BATCH_SIZE,
        help="Split the final bootstrap output into batches of this many jobs (default: 1000)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=os.getenv("PIPELINE_CRAWL_SOURCES", DEFAULT_SOURCES),
        help="Comma-separated source filter (default: all sources)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=DEFAULT_MAX_JOBS,
        help="Bootstrap max jobs per source per keyword (default: 150)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Bootstrap page safety cap per keyword (default: 8)",
    )
    return parser.parse_args()


def load_keywords(keywords_file: Path) -> list[str]:
    if not keywords_file.exists():
        raise FileNotFoundError(f"Keywords file not found: {keywords_file}")

    with open(keywords_file, encoding="utf-8") as f:
        config = json.load(f)

    keywords = pipeline._flatten_keywords_with_groupnames(config)
    if not keywords:
        raise ValueError(f"No keywords found in: {keywords_file}")
    return keywords


def make_crawl_env(keyword: str, sources: str, max_jobs: int, max_pages: int) -> dict:
    keyword_json = json.dumps([keyword], ensure_ascii=False)
    crawl_env = os.environ.copy()
    crawl_env.update(
        {
            "PIPELINE_CRAWL_MODE": "bootstrap",
            "CRAWL_MAX_PAGES": str(max_pages),
            "ITVIEC_MAX_JOBS": str(max_jobs),
            "CAREERVIET_MAX_JOBS": str(max_jobs),
            "VNWORKS_DAILY_MAX_JOBS": str(max_jobs),
            "LINKEDIN_MAX_JOBS": str(max_jobs),
            "LINKEDIN_MAX_JOBS_LIMIT": str(max_jobs),
            "LINKEDIN_DETAIL_SCRAPE": "true",
            "VNWORKS_CRAWL_MODE": "bootstrap",
            "VNWORKS_FORCE_FULL_CRAWL": "1",
            "JOB_DATE_MODE": "off",
            "DAYS_BACK": "",
            "REALTIME_DAYS": "",
            "DAILY_NUM_KEYWORDS": "1",
            "SELECTED_KEYWORDS": keyword,
            "CRAWL_KEYWORDS": keyword,
            "KEYWORDS": keyword,
            "SELECTED_KEYWORDS_JSON": keyword_json,
            "CRAWL_KEYWORDS_JSON": keyword_json,
            "DAILY_KEYWORDS_JSON": keyword_json,
        }
    )
    crawl_env["PIPELINE_CRAWL_SOURCES"] = (sources.strip() or DEFAULT_SOURCES)
    return crawl_env


def read_raw_jobs(raw_output_path: Path) -> list[dict]:
    if not raw_output_path.exists():
        return []
    with open(raw_output_path, encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    return []


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_job_batches(all_jobs: list[dict], batch_dir: Path, batch_size: int, date_token: str) -> list[Path]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_paths: list[Path] = []
    for index in range(0, len(all_jobs), batch_size):
        batch_number = index // batch_size + 1
        batch_path = batch_dir / f"data_{date_token}_batch_{batch_number:03d}.json"
        write_json(batch_path, all_jobs[index : index + batch_size])
        batch_paths.append(batch_path)
    return batch_paths


def main() -> int:
    args = parse_args()
    keywords = load_keywords(args.keywords_file)
    total_keywords = len(keywords)
    today_token = date.today().strftime("%m%d%Y")
    BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_BATCH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loaded {total_keywords} keywords from {args.keywords_file}")
    print(f"Keyword batch size: {args.keyword_batch_size}")
    print(f"Pause between batches: {args.pause_seconds}s")
    print(f"Job batch size: {args.job_batch_size}")
    print(f"Source filter: {args.sources.strip() or DEFAULT_SOURCES}")

    all_jobs: list[dict] = []
    keyword_reports: list[dict] = []

    for batch_start in range(0, total_keywords, args.keyword_batch_size):
        batch_keywords = keywords[batch_start : batch_start + args.keyword_batch_size]
        print()
        print("=" * 100)
        print(
            f"Keyword batch {batch_start // args.keyword_batch_size + 1} / "
            f"{(total_keywords + args.keyword_batch_size - 1) // args.keyword_batch_size}"
        )
        print("=" * 100)

        for keyword in batch_keywords:
            started_at = datetime.now()
            print()
            print(f"[START] {keyword}")

            crawl_env = make_crawl_env(keyword, args.sources, args.max_jobs, args.max_pages)
            crawl_ok, results_tracker, source_status, raw_output_path = pipeline.run_daily_crawl_parallel(
                keyword=keyword,
                location="Vietnam",
                domestic_max_jobs=args.max_jobs,
                linkedin_max_jobs=args.max_jobs,
                crawl_env=crawl_env,
                domestic_max_pages=args.max_pages,
            )

            raw_jobs = read_raw_jobs(Path(raw_output_path))
            all_jobs.extend(raw_jobs)

            finished_at = datetime.now()
            total_jobs = len(raw_jobs)
            print(f"[DONE] {keyword}: {total_jobs} jobs")
            for source_name, count in results_tracker.items():
                print(f"  - {source_name}: {count}")
            if not crawl_ok:
                print(f"  - Warning: no jobs were collected for '{keyword}'")

            keyword_reports.append(
                {
                    "keyword": keyword,
                    "started_at": started_at.isoformat(timespec="seconds"),
                    "finished_at": finished_at.isoformat(timespec="seconds"),
                    "jobs_total": total_jobs,
                    "jobs_by_source": results_tracker,
                    "source_status": source_status,
                    "raw_output_path": str(raw_output_path),
                }
            )

        if batch_start + args.keyword_batch_size < total_keywords:
            print()
            print(f"Pausing for {args.pause_seconds} seconds before next batch...")
            time.sleep(args.pause_seconds)

    combined_output_path = BOOTSTRAP_DIR / f"data_{today_token}.json"
    write_json(combined_output_path, all_jobs)

    batch_paths = write_job_batches(all_jobs, BOOTSTRAP_BATCH_DIR, args.job_batch_size, today_token)

    report_path = BOOTSTRAP_DIR / f"report_{today_token}.json"
    write_json(
        report_path,
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "keywords_file": str(args.keywords_file),
            "keyword_count": total_keywords,
            "keyword_batch_size": args.keyword_batch_size,
            "pause_seconds": args.pause_seconds,
            "job_batch_size": args.job_batch_size,
            "total_jobs": len(all_jobs),
            "combined_output_path": str(combined_output_path),
            "batch_files": [str(path) for path in batch_paths],
            "keywords": keyword_reports,
        },
    )

    print()
    print("=" * 100)
    print("Bootstrap crawl finished")
    print(f"Keywords crawled: {total_keywords}")
    print(f"Total jobs collected: {len(all_jobs)}")
    print(f"Combined output: {combined_output_path}")
    print(f"Report: {report_path}")
    print(f"Batch files: {len(batch_paths)}")
    for path in batch_paths:
        print(f"  - {path}")
    print("=" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())