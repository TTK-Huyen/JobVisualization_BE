#!/usr/bin/env python3
"""One-off script to copy benefits table from old DB to new DB using explicit columns."""
import os
import logging
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

OLD = os.getenv('OLD_DB_URL', 'postgresql://postgres:123456@localhost:5432/job_vis')
NEW = os.getenv('NEW_DB_URL', 'postgresql://postgres:123456@localhost:5432/job_vis_clone')

def main():
    old = psycopg2.connect(OLD)
    new = psycopg2.connect(NEW)
    old.autocommit = True
    new.autocommit = True
    cur_old = old.cursor()
    cur_old.execute("SELECT benefit_id, benefit_name, category, created_at FROM public.benefits")
    rows = cur_old.fetchall()
    logging.info("Found %d benefits in old DB", len(rows))
    if not rows:
        return
    cur_new = new.cursor()
    insert_sql = "INSERT INTO benefits (benefit_id, benefit_name, category, created_at) VALUES %s ON CONFLICT DO NOTHING"
    psycopg2.extras.execute_values(cur_new, insert_sql, rows, template=None, page_size=100)
    new.commit()
    logging.info("Inserted %d benefits into new DB", len(rows))
    cur_old.close()
    cur_new.close()
    old.close()
    new.close()

if __name__ == '__main__':
    main()
