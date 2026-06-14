#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv(BASE_DIR / ".env")

from scripts.split_description import extract_clean_job_description  # noqa: E402


DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "description_backfill_preview"
DEFAULT_CUTOFF_DATE = "2026-06-14"
BACKUP_TABLE = "job_description_clean_backups"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview and optionally backfill cleaned jobs.description for old crawls "
            "using the same split_description cleaner used after LLM extract."
        )
    )
    parser.add_argument(
        "--cutoff-date",
        default=DEFAULT_CUTOFF_DATE,
        help="Clean jobs with scraped_at earlier than this date, YYYY-MM-DD. Default: 2026-06-14.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum rows to fetch for this run. Use 0 for no limit. Default: 100.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional case-insensitive source_name filter, e.g. LinkedIn, ITviec, CareerViet, VietnamWorks.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where preview JSON/CSV files are written.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update jobs.description. Without this flag the script only writes preview files.",
    )
    parser.add_argument(
        "--include-unchanged",
        action="store_true",
        help="Include rows whose cleaned description is identical to the original in preview files.",
    )
    return parser.parse_args()


def connect_db():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is not installed in the current environment") from exc

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB") or os.getenv("PG_DB", "postgres"),
        user=os.getenv("POSTGRES_USER") or os.getenv("PG_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD", ""),
    )


def parse_cutoff(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"--cutoff-date must be YYYY-MM-DD, got: {value}") from exc


def compact_text(value: Any, max_chars: int = 700) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def fetch_jobs(conn, cutoff: datetime, limit: int, source: str | None) -> list[dict[str, Any]]:
    where = [
        "scraped_at < %s",
        "description IS NOT NULL",
        "btrim(description) <> ''",
        "source_name IS NOT NULL",
        "btrim(source_name) <> ''",
    ]
    params: list[Any] = [cutoff]

    if source:
        where.append("source_name ILIKE %s")
        params.append(f"%{source}%")

    limit_sql = ""
    if limit and limit > 0:
        limit_sql = " LIMIT %s"
        params.append(limit)

    query = f"""
        SELECT job_id, title, source_name, source_id, job_posting_url, scraped_at, description
        FROM public.jobs
        WHERE {' AND '.join(where)}
        ORDER BY scraped_at ASC, job_id ASC
        {limit_sql}
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_preview(rows: list[dict[str, Any]], include_unchanged: bool) -> list[dict[str, Any]]:
    preview = []
    for row in rows:
        original = row.get("description") or ""
        cleaned = extract_clean_job_description(row.get("source_name") or "", original)
        changed = cleaned != original
        if not changed and not include_unchanged:
            continue

        preview.append(
            {
                "job_id": row.get("job_id"),
                "title": row.get("title"),
                "source_name": row.get("source_name"),
                "source_id": row.get("source_id"),
                "job_posting_url": row.get("job_posting_url"),
                "scraped_at": row.get("scraped_at").isoformat() if row.get("scraped_at") else None,
                "changed": changed,
                "original_length": len(original),
                "cleaned_length": len(cleaned),
                "length_delta": len(cleaned) - len(original),
                "original_preview": compact_text(original),
                "cleaned_preview": compact_text(cleaned),
                "original_description": original,
                "cleaned_description": cleaned,
                "_original": original,
                "_cleaned": cleaned,
            }
        )
    return preview


def write_preview_files(preview: list[dict[str, Any]], output_dir: Path, cutoff_date: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"clean_description_preview_before_{cutoff_date}_{stamp}.json"
    csv_path = output_dir / f"clean_description_preview_before_{cutoff_date}_{stamp}.csv"

    public_preview = []
    for item in preview:
        public_item = dict(item)
        public_item.pop("_original", None)
        public_item.pop("_cleaned", None)
        public_preview.append(public_item)

    json_path.write_text(json.dumps(public_preview, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "job_id",
        "title",
        "source_name",
        "source_id",
        "job_posting_url",
        "scraped_at",
        "changed",
        "original_length",
        "cleaned_length",
        "length_delta",
        "original_preview",
        "cleaned_preview",
        "cleaned_description",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in public_preview:
            writer.writerow({key: item.get(key) for key in fieldnames})

    return json_path, csv_path


def ensure_backup_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS public.{BACKUP_TABLE} (
                backup_id bigserial PRIMARY KEY,
                job_id bigint NOT NULL,
                old_description text NOT NULL,
                new_description text NOT NULL,
                source_name varchar(50),
                scraped_at timestamp without time zone,
                backed_up_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def apply_updates(conn, preview: list[dict[str, Any]]) -> int:
    changed_items = [item for item in preview if item.get("changed")]
    if not changed_items:
        return 0

    ensure_backup_table(conn)
    with conn.cursor() as cur:
        for item in changed_items:
            cur.execute(
                f"""
                INSERT INTO public.{BACKUP_TABLE}
                    (job_id, old_description, new_description, source_name, scraped_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    item["job_id"],
                    item["_original"],
                    item["_cleaned"],
                    item.get("source_name"),
                    item.get("scraped_at"),
                ),
            )
            cur.execute(
                """
                UPDATE public.jobs
                SET description = %s
                WHERE job_id = %s
                """,
                (item["_cleaned"], item["job_id"]),
            )
    conn.commit()
    return len(changed_items)


def main() -> int:
    args = parse_args()
    cutoff = parse_cutoff(args.cutoff_date)

    conn = connect_db()
    try:
        rows = fetch_jobs(conn, cutoff, args.limit, args.source)
        preview = build_preview(rows, args.include_unchanged)
        json_path, csv_path = write_preview_files(preview, args.output_dir, args.cutoff_date)

        changed_count = sum(1 for item in preview if item.get("changed"))
        print(f"Cutoff: scraped_at < {args.cutoff_date}")
        print(f"Fetched rows: {len(rows)}")
        print(f"Preview rows written: {len(preview)}")
        print(f"Changed rows in preview: {changed_count}")
        print(f"Preview JSON: {json_path}")
        print(f"Preview CSV : {csv_path}")

        for item in preview[:5]:
            print("\n" + "-" * 80)
            print(f"job_id={item['job_id']} source={item['source_name']} scraped_at={item['scraped_at']}")
            print(f"title={item.get('title')}")
            print(f"original_length={item['original_length']} cleaned_length={item['cleaned_length']} delta={item['length_delta']}")
            print(f"ORIGINAL: {item['original_preview']}")
            print(f"CLEANED : {item['cleaned_preview']}")

        if not args.apply:
            print("\nDry run only. Review the preview files, then rerun with --apply to update public.jobs.description.")
            return 0

        updated = apply_updates(conn, preview)
        print(f"\nUpdated rows: {updated}")
        print(f"Backup table: public.{BACKUP_TABLE}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
