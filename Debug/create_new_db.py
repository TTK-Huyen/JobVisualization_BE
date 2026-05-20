#!/usr/bin/env python3
"""
Create a new Postgres database from an existing schema and seed data.

Requirements:
- psycopg2-binary
- pandas

Usage examples and env vars are in README_CREATE_NEW_DB.md
"""
import argparse
import os
import sys
import time
import logging
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def parse_args():
    p = argparse.ArgumentParser(description="Create new DB from schema and seed data")
    p.add_argument("--old-db-url", help="Old DB URL, e.g. postgresql://user:pass@host:port/db", required=False)
    p.add_argument("--new-db-url", help="New DB URL, e.g. postgresql://user:pass@host:port/newdb", required=False)
    p.add_argument("--schema", help="Path to schema.sql", required=True)
    p.add_argument("--specialized-csv", help="Path to CSV with specialized skills", required=True)
    p.add_argument("--recreate", action='store_true', help="If set, DROP DATABASE IF EXISTS then CREATE new DB")
    p.add_argument("--copy-tables", help="Comma-separated additional tables to copy from old DB (optional)", default="benefits")
    return p.parse_args()


def get_env_or_arg(arg_value, env_name):
    if arg_value:
        return arg_value
    val = os.getenv(env_name)
    if not val:
        raise SystemExit(f"Missing {env_name} and not provided as arg")
    return val


def connect(dsn):
    logging.info(f"Connecting to {dsn}")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def create_database_if_not_exists(admin_dsn, new_db_name):
    logging.info(f"Ensure database {new_db_name} exists")
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (new_db_name,))
    if cur.fetchone():
        logging.info(f"Database {new_db_name} already exists - will not drop")
    else:
        logging.info(f"Creating database {new_db_name}")
        cur.execute(f"CREATE DATABASE \"{new_db_name}\" WITH ENCODING 'UTF8' TEMPLATE template0")
    cur.close()
    conn.close()


def recreate_database(admin_dsn, new_db_name):
    logging.info(f"Recreating database {new_db_name}")
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    cur = conn.cursor()
    # Terminate other connections to allow DROP
    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (new_db_name,))
    cur.execute(f"DROP DATABASE IF EXISTS \"{new_db_name}\"")
    cur.execute(f"CREATE DATABASE \"{new_db_name}\" WITH ENCODING 'UTF8' TEMPLATE template0")
    cur.close()
    conn.close()


def apply_schema(new_db_dsn, schema_path):
    logging.info(f"Applying schema from {schema_path} to new DB")
    raw = open(schema_path, encoding="utf-8").read().splitlines()

    # Remove psql meta-commands (lines starting with backslash) and COPY data blocks
    cleaned_lines = []
    in_copy = False
    for line in raw:
        if in_copy:
            if line.strip() == '\\.' or line.strip() == '\\.' :
                in_copy = False
            continue
        if line.startswith('\\'):
            continue
        # skip pg_dump comment metadata lines
        if line.strip().startswith('--'):
            continue
        if line.strip().upper().startswith('COPY ') and 'FROM stdin' in line:
            in_copy = True
            continue
        cleaned_lines.append(line)

    cleaned_sql = '\n'.join(cleaned_lines)

    conn = psycopg2.connect(new_db_dsn)
    conn.autocommit = True
    cur = conn.cursor()
    # Execute statements one by one to avoid psycopg2 limitations with multiple commands
    statements = [s.strip() for s in cleaned_sql.split(';') if s.strip()]
    try:
        for stmt in statements:
            try:
                cur.execute(stmt + ';')
            except Exception as e:
                logging.error('Failed executing statement (continuing): %s', e)
                logging.debug('Statement: %s', stmt[:200])
        conn.commit()
    except Exception:
        logging.error("Failed to apply schema")
        raise
    finally:
        cur.close()
        conn.close()


def copy_table_rows(old_conn, new_conn, table, columns=None, where_clause=None, preserve_ids=False):
    cur_old = old_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    sel = "*" if not columns else ",".join(columns)
    q = f"SELECT {sel} FROM {table}"
    if where_clause:
        q += f" WHERE {where_clause}"
    cur_old.execute(q)
    rows = cur_old.fetchall()
    logging.info("Found %d rows in old.%s", len(rows), table)
    if not rows:
        cur_old.close()
        return 0

    # Build insert
    if preserve_ids:
        cols = rows[0].keys()
    else:
        cols = [c for c in rows[0].keys() if c != 'skill_id' and c != 'benefit_id']

    insert_cols = ",".join(cols)
    placeholders = ",".join([f"%({c})s" for c in cols])
    insert_sql = f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    cur_new = new_conn.cursor()
    count = 0
    for r in rows:
        data = {c: r[c] for c in cols}
        try:
            cur_new.execute(insert_sql, data)
            count += cur_new.rowcount
        except Exception as e:
            logging.error("Insert failed for table %s row %s: %s", table, data, e)
    new_conn.commit()
    cur_old.close()
    cur_new.close()
    logging.info("Inserted ~%d rows into new.%s", count, table)
    return count


def bulk_insert_skills_from_old(old_conn, new_conn):
    # copy case-sensitive types: 'Common skill' and 'Certification'
    logging.info("Copying skills type 'Common skill' and 'Certification' from old -> new")
    cur_old = old_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur_old.execute("SELECT skill_name, category, type, created_at FROM skills WHERE type IN ('Common skill','Certification')")
    rows = cur_old.fetchall()
    logging.info("Found %d skills to copy", len(rows))
    if not rows:
        return 0
    cur_new = new_conn.cursor()
    insert_sql = "INSERT INTO skills (skill_name, category, type, created_at) VALUES %s ON CONFLICT DO NOTHING"
    values = [(r['skill_name'], r['category'], r['type'], r['created_at']) for r in rows]
    psycopg2.extras.execute_values(cur_new, insert_sql, values, template=None, page_size=100)
    new_conn.commit()
    cur_old.close()
    cur_new.close()
    logging.info("Inserted %d skills", len(values))
    return len(values)


def import_specialized_csv(new_conn, csv_path):
    logging.info("Import specialized skills from %s", csv_path)
    df = pd.read_csv(csv_path, dtype=str)
    required = ['NAME']
    for col in required:
        if col not in df.columns:
            raise SystemExit(f"CSV missing required column: {col}")

    # Map columns
    name_col = 'NAME'
    cat_col = 'SUBCATEGORY_NAME' if 'SUBCATEGORY_NAME' in df.columns else None
    type_col = 'TYPE' if 'TYPE' in df.columns else None

    cur = new_conn.cursor()
    insert_sql = "INSERT INTO skills (skill_name, category, type) VALUES %s ON CONFLICT DO NOTHING"
    values = []
    for idx, row in df.iterrows():
        name = row.get(name_col)
        if pd.isna(name) or str(name).strip() == '':
            logging.warning("Skipping CSV row %d because NAME is missing", idx)
            continue
        cat = row.get(cat_col) if cat_col else None
        typ = row.get(type_col) if type_col else None
        values.append((name, cat, typ))

    if not values:
        logging.info("No rows to insert from CSV")
        return 0
    psycopg2.extras.execute_values(cur, insert_sql, values, template=None, page_size=100)
    new_conn.commit()
    cur.close()
    logging.info("Inserted %d specialized skills from CSV", len(values))
    return len(values)


def main():
    args = parse_args()
    old_db_url = os.getenv('OLD_DB_URL') or args.old_db_url
    new_db_url = os.getenv('NEW_DB_URL') or args.new_db_url
    schema = args.schema
    csv_path = args.specialized_csv

    if not old_db_url:
        raise SystemExit('OLD_DB_URL must be provided via env or --old-db-url')
    if not new_db_url:
        raise SystemExit('NEW_DB_URL must be provided via env or --new-db-url')

    # Parse new DB name and admin DSN to create DB
    parsed = urlparse(new_db_url)
    new_db_name = parsed.path.lstrip('/')
    if not new_db_name:
        raise SystemExit('New DB URL must include database name')

    # Build admin DSN (connect to postgres default DB on same server)
    admin_dsn = new_db_url.replace('/' + new_db_name, '/postgres')

    # Create DB or recreate if requested
    if args.recreate:
        recreate_database(admin_dsn, new_db_name)
    else:
        create_database_if_not_exists(admin_dsn, new_db_name)

    # Apply schema
    apply_schema(new_db_url, schema)

    # Connect to old and new DBs
    old_conn = connect(old_db_url)
    new_conn = connect(new_db_url)

    # Copy skills types common and certification
    try:
        copied_skills = bulk_insert_skills_from_old(old_conn, new_conn)
    except Exception:
        logging.exception("Failed copying skills from old DB")
        raise

    # Copy benefits (preserve ids)
    try:
        copy_table_rows(old_conn, new_conn, 'benefits', preserve_ids=True)
    except Exception:
        logging.exception("Failed copying benefits")
        raise

    # Import specialized CSV
    try:
        imported = import_specialized_csv(new_conn, csv_path)
    except Exception:
        logging.exception("Failed importing specialized CSV")
        raise

    # Validation: counts
    cur_new = new_conn.cursor()
    cur_new.execute("SELECT count(*) FROM skills")
    total_skills = cur_new.fetchone()[0]
    cur_new.execute("SELECT count(*) FROM benefits")
    total_benefits = cur_new.fetchone()[0]
    logging.info("Validation: skills=%d, benefits=%d", total_skills, total_benefits)

    old_conn.close()
    new_conn.close()

    logging.info("Done. Copied %d skills and imported %d specialized CSV rows", copied_skills, imported)


if __name__ == '__main__':
    main()
