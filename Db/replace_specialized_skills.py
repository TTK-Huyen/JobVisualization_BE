#!/usr/bin/env python3
"""
Replace specialized skills in DB and update the Specialize_skill.csv file

Usage:
  python Db/replace_specialized_skills.py --csv new_specialized.csv [--env Db/.env] [--dry-run]

What it does:
  - Connects to Postgres using PG_* env vars (can load a .env file)
  - Finds skills where LOWER(type) LIKE '%special%'
  - For each such skill, finds the subcategory name from the CSV mapping (NAME -> SUBCATEGORY_NAME).
    - If a subcategory skill doesn't exist in `skills`, it will be inserted.
    - Job references in `job_skills` and `job_group_skill_weights` are migrated to the subcategory skill id.
    - The old specialized skill row is deleted.
  - Optionally replaces `Db/Specialize_skill.csv` with the provided CSV (backups previous file).

This script performs safe updates using transactions. Use --dry-run to preview changes.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

try:
    import psycopg2
except Exception:
    psycopg2 = None


def load_csv_mapping(path: Path) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    out = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("NAME") or "").strip()
            sub = (row.get("SUBCATEGORY_NAME") or row.get("SUBCATEGORY") or "").strip()
            cat = (row.get("CATEGORY_NAME") or row.get("CATEGORY") or "").strip()
            if name:
                out[name.lower()] = (sub or None, cat or None)
    return out


def get_db_conn_from_env(env_path: Optional[Path] = None):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required. Install psycopg2-binary.")
    if env_path and env_path.exists():
        load_dotenv(dotenv_path=str(env_path))
    host = os.getenv("PG_HOST")
    port = os.getenv("PG_PORT")
    db = os.getenv("PG_DB")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    if not all([host, port, db, user, password]):
        raise RuntimeError("PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD must be set")
    return psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)


def migrate_specialized_skills(conn, csv_map: Dict[str, Tuple[Optional[str], Optional[str]]], dry_run: bool = False):
    cur = conn.cursor()

    cur.execute("SELECT skill_id, skill_name, category FROM public.skills WHERE LOWER(COALESCE(type, '')) LIKE %s", ("%special%",))
    rows = cur.fetchall()
    if not rows:
        print("No specialized skills found in DB (type LIKE '%special%').")
        cur.close()
        return

    print(f"Found {len(rows)} specialized skills to migrate.")

    for skill_id, skill_name, skill_category in rows:
        name_l = (skill_name or "").strip().lower()
        mapping = csv_map.get(name_l)
        subcategory = None
        category_name = None
        if mapping:
            subcategory, category_name = mapping

        if not subcategory:
            subcategory = skill_category

        if not subcategory:
            print(f"  - Skipping skill id={skill_id} name='{skill_name}' (no subcategory available)")
            continue

        subcategory = subcategory.strip()
        print(f"  - Skill {skill_id} '{skill_name}' -> subcategory '{subcategory}'")

        cur.execute("SELECT skill_id FROM public.skills WHERE LOWER(skill_name) = %s LIMIT 1", (subcategory.lower(),))
        found = cur.fetchone()
        if found:
            target_id = found[0]
            print(f"    → Found existing target skill id={target_id}")
        else:
            if dry_run:
                print("    → Would INSERT new subcategory skill (dry-run)")
                target_id = None
            else:
                cur.execute(
                    "INSERT INTO public.skills (skill_name, category, type) VALUES (%s, %s, %s) RETURNING skill_id",
                    (subcategory, category_name or None, "Subcategory"),
                )
                target_id = cur.fetchone()[0]
                conn.commit()
                print(f"    → INSERTED new subcategory skill id={target_id}")

        if not target_id:
            continue

        print(f"    → Migrating job_skills from {skill_id} to {target_id}")
        if not dry_run:
            cur.execute(
                "INSERT INTO public.job_skills (job_id, skill_id, is_inferred) SELECT job_id, %s, is_inferred FROM public.job_skills WHERE skill_id = %s ON CONFLICT (job_id, skill_id) DO NOTHING",
                (target_id, skill_id),
            )
            cur.execute("DELETE FROM public.job_skills WHERE skill_id = %s", (skill_id,))

            cur.execute(
                "INSERT INTO public.job_group_skill_weights (search_group, skill_id, weight_wi) SELECT search_group, %s, weight_wi FROM public.job_group_skill_weights WHERE skill_id = %s ON CONFLICT (search_group, skill_id) DO NOTHING",
                (target_id, skill_id),
            )
            cur.execute("DELETE FROM public.job_group_skill_weights WHERE skill_id = %s", (skill_id,))

            cur.execute("DELETE FROM public.skills WHERE skill_id = %s", (skill_id,))
            conn.commit()
            print(f"    → Deleted old skill id={skill_id}")
        else:
            print("    → Dry-run: Skipped DB writes")

    cur.close()


def backup_and_replace_csv(target_path: Path, new_csv: Path):
    if not new_csv.exists():
        raise FileNotFoundError(f"New CSV not found: {new_csv}")
    if target_path.exists():
        bak = target_path.with_suffix(target_path.suffix + f".bak.{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(str(target_path), str(bak))
        print(f"Backed up {target_path} -> {bak}")
    shutil.copy2(str(new_csv), str(target_path))
    print(f"Replaced {target_path} with {new_csv}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', help='Path to new specialized skills CSV to write into Db/Specialize_skill.csv')
    parser.add_argument('--env', help='Path to .env file to load (defaults to Db/.env)', default=str(Path(__file__).resolve().parent / '.env'))
    parser.add_argument('--dry-run', action='store_true', help='Do not write changes to DB or CSV')
    args = parser.parse_args()

    env_path = Path(args.env) if args.env else None
    if env_path and env_path.exists():
        load_dotenv(dotenv_path=str(env_path))

    repo_csv = Path(__file__).resolve().parent / 'Specialize_skill.csv'
    csv_to_load = Path(args.csv) if args.csv else repo_csv
    csv_map = load_csv_mapping(csv_to_load)

    conn = get_db_conn_from_env(env_path)
    try:
        migrate_specialized_skills(conn, csv_map, dry_run=args.dry_run)
    finally:
        conn.close()

    if args.csv:
        if args.dry_run:
            print('Dry-run: CSV replace skipped')
        else:
            backup_and_replace_csv(repo_csv, Path(args.csv))


if __name__ == '__main__':
    main()
