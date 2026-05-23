import os
import sys
import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_and_seed")

# Resolve project root dynamically
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None
for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break
if not PROJECT_ROOT:
    PROJECT_ROOT = THIS_FILE.parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matching_cv.match_cv import get_db_connection
from matching_cv.utils import load_db_env

def run_migration_and_seed():
    load_db_env()
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. SQL Migrate: Create public.search_group_keywords table and its unique index
        logger.info("Starting SQL Migration: Creating table search_group_keywords...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.search_group_keywords (
                id SERIAL PRIMARY KEY,
                group_key VARCHAR(255) NOT NULL,
                keyword VARCHAR(255) NOT NULL
            );
        """)
        
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_search_group_keywords_keyword 
            ON public.search_group_keywords(keyword);
        """)
        conn.commit()
        logger.info("SQL Migration completed successfully.")
        
        # 2. Seeding Data: Load keywords_daily.json and insert config into DB
        keywords_path = PROJECT_ROOT / "Db" / "input" / "keywords_daily.json"
        if not keywords_path.exists():
            keywords_path = PROJECT_ROOT / "input" / "keywords_daily.json"
            
        logger.info(f"Loading keywords from {keywords_path}...")
        with open(keywords_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        groups = config.get("groups", {})
        seeded_count = 0
        skipped_count = 0
        
        logger.info("Seeding search group keywords into database...")
        for group_key, group_cfg in groups.items():
            roles = group_cfg.get("roles", [])
            for r in roles:
                kw = str(r).lower().strip()
                if not kw:
                    continue
                try:
                    # Use ON CONFLICT DO NOTHING to ensure no duplicates are loaded
                    cur.execute("""
                        INSERT INTO public.search_group_keywords (group_key, keyword)
                        VALUES (%s, %s)
                        ON CONFLICT (keyword) DO NOTHING
                        RETURNING id;
                    """, (group_key, kw))
                    row = cur.fetchone()
                    if row:
                        seeded_count += 1
                    else:
                        skipped_count += 1
                except Exception as ex:
                    logger.error(f"Error seeding keyword '{kw}' under group '{group_key}': {ex}")
                    
        conn.commit()
        logger.info(f"Seeding completed. Seeded: {seeded_count} keywords, Skipped/Existing: {skipped_count} keywords.")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Migration and Seeding failed: {e}")
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_migration_and_seed()
