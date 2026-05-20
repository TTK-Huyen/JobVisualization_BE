#!/usr/bin/env python3
"""Print counts of skills and benefits loaded by the normalize_embeddings pipeline module.

Usage:
  python scripts/print_normalizer_counts.py [--db-url POSTGRES_URL] [--skill-table skills] [--benefit-table benefits]

If --db-url is not provided the script will try to load Db/.env (or project .env) and construct the URL from POSTGRES_* or PG_* vars.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import importlib.util
from collections import Counter

try:
    from sqlalchemy import create_engine, text
except Exception:
    create_engine = None
    text = None


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "Db").exists() and (parent / "Db" / ".env").exists():
            return parent
    # fallback: assume repo root is three levels up
    return Path(__file__).resolve().parents[2]


def load_normalize_module(base_dir: Path):
    mod_path = base_dir / "Db" / "pipeline" / "normalize" / "2_1_normalized_data" / "normalize_embeddings.py"
    if not mod_path.exists():
        raise FileNotFoundError(f"normalize_embeddings.py not found at: {mod_path}")
    spec = importlib.util.spec_from_file_location("normalize_embeddings_mod", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_db_url_from_env(base_dir: Path) -> str | None:
    env_file = base_dir / "Db" / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except Exception:
        pass

    host = os.environ.get("POSTGRES_HOST") or os.environ.get("PG_HOST")
    port = os.environ.get("POSTGRES_PORT") or os.environ.get("PG_PORT")
    database = os.environ.get("POSTGRES_DB") or os.environ.get("PG_DB")
    user = os.environ.get("POSTGRES_USER") or os.environ.get("PG_USER")
    password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("PG_PASSWORD")

    if host or port or database or user or password:
        host = host or "localhost"
        port = str(port or "5432")
        database = database or "postgres"
        user = user or "postgres"
        password_part = f":{password}" if password else ""
        return f"postgresql://{user}{password_part}@{host}:{port}/{database}"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", type=str, default=None)
    parser.add_argument("--skill-table", type=str, default="skills")
    parser.add_argument("--benefit-table", type=str, default="benefits")
    args = parser.parse_args()

    base_dir = find_project_root()
    mod = load_normalize_module(base_dir)

    db_url = args.db_url or os.environ.get("DATABASE_URL") or build_db_url_from_env(base_dir)
    if not db_url:
        print("Error: provide --db-url or set DATABASE_URL or POSTGRES_* / PG_* in Db/.env", file=sys.stderr)
        sys.exit(2)

    # Attempt to get detailed counts by type using SQL (preferred)
    type_counts = None
    sample_by_type = {}

    if create_engine is not None:
        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                # try common type column names
                type_cols = ["type", "skill_type", "category", "skill_category"]
                for col in type_cols:
                    try:
                        q = text(f"SELECT COALESCE({col}, '') AS type_name, COUNT(*) AS cnt FROM {args.skill_table} GROUP BY COALESCE({col}, '') ORDER BY cnt DESC")
                        res = conn.execute(q)
                        rows = res.fetchall()
                        if rows:
                            type_counts = {r[0] or "": int(r[1]) for r in rows}
                            # get sample names per type (up to 5)
                            for tname in list(type_counts.keys()):
                                s_q = text(f"SELECT {args.skill_table}.skill_id, {args.skill_table}.skill_name FROM {args.skill_table} WHERE COALESCE({col}, '') = :t LIMIT 5")
                                sres = conn.execute(s_q, {"t": tname})
                                sample_by_type[tname] = [(int(r[0]), str(r[1])) for r in sres.fetchall()]
                            break
                    except Exception:
                        continue
        except Exception:
            type_counts = None

    if type_counts is None:
        # Fallback: load raw list using pipeline helper (may not include types)
        try:
            skills = mod.load_dictionary_from_db(db_url, args.skill_table)
            benefits = mod.load_dictionary_from_db(db_url, args.benefit_table)
            print(f"Total skills loaded: {len(skills)}")
            print(f"Total benefits loaded: {len(benefits)}")
            print("\nSample skills:")
            for sid, name in skills[:20]:
                print(f" - {sid}: {name}")
        except Exception as e:
            print(f"Failed to load dictionaries: {e}")
        sys.exit(0)

    # Print detailed type counts
    total_skills = sum(type_counts.values())
    print(f"Total skills loaded: {total_skills}")
    print(f"Total benefits loaded: {len(mod.load_dictionary_from_db(db_url, args.benefit_table))}")
    print("\nDetailed counts by Type:")
    for tname, cnt in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        label = tname if tname else "(empty)"
        print(f"{label}: {cnt} skill")

    # Print sample per type
    print("\nSample skills by type (up to 5 each):")
    for tname, samples in sample_by_type.items():
        label = tname if tname else "(empty)"
        print(f"\n{label}:")
        for sid, name in samples:
            print(f" - {sid}: {name}")

    # Additionally: breakdown sub_category for specialized_skill
    try:
        sub_cols = ["sub_category", "category", "sub_cat", "subtype"]
        found = False
        with engine.connect() as conn:
            for col in sub_cols:
                try:
                    # match type case-insensitively and allow variants like 'Specialized Skill'
                    q = text(
                        f"SELECT COALESCE({col}, '') AS sub, COUNT(*) AS cnt"
                        f" FROM {args.skill_table} WHERE lower(COALESCE(type, '')) LIKE 'specialized%' GROUP BY COALESCE({col}, '') ORDER BY cnt DESC"
                    )
                    res = conn.execute(q)
                    rows = res.fetchall()
                    if rows:
                        found = True
                        print("\nspecialized_skill breakdown by sub_category:")
                        for r in rows:
                            sub = r[0] or "[unknown]"
                            cnt = int(r[1])
                            print(f"specialized_skill [{sub}]: {cnt} skills")
                        break
                except Exception:
                    # try next column name
                    continue
        if not found:
            print("\nNo sub_category column found for specialized_skill breakdown (tried: {}).".format(
                ", ".join(sub_cols)
            ))
            try:
                # Diagnostic: show sample rows for specialized skills to inspect 'category' values
                with engine.connect() as conn:
                    s_q = text(f"SELECT {args.skill_table}.skill_id, {args.skill_table}.skill_name, COALESCE({args.skill_table}.category, '') as category FROM {args.skill_table} WHERE lower(COALESCE(type, '')) LIKE 'specialized%' LIMIT 20")
                    sres = conn.execute(s_q)
                    rows = sres.fetchall()
                    if rows:
                        print("\nSample specialized_skill rows (showing category values):")
                        for r in rows:
                            print(f" - {int(r[0])}: {r[1]} (category='{r[2]}')")
                    else:
                        print("\nNo specialized_skill rows returned for diagnostic sample query.")
            except Exception:
                pass
    except Exception:
        # non-fatal
        print("\n[WARN] Could not compute specialized_skill sub_category breakdown.")


if __name__ == "__main__":
    main()
