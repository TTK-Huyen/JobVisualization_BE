#!/usr/bin/env python3
"""
Script to dynamically update jobs with 'unknown' or NULL search_group.
Maps job titles directly to database search groups using SentenceTransformer embeddings.
"""

import sys
import logging
from pathlib import Path
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("update_unknown_jobs")

# Resolve project root dynamically
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None
for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break

if not PROJECT_ROOT:
    PROJECT_ROOT = THIS_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matching_cv.match_cv import get_db_connection
from matching_cv.utils import load_db_env

def main():
    load_db_env()
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. Fetch dynamic groups from job_group_skill_weights
        logger.info("Fetching unique search groups from weights table...")
        cur.execute(
            "SELECT DISTINCT search_group FROM public.job_group_skill_weights WHERE search_group IS NOT NULL AND search_group != 'unknown'"
        )
        db_groups = [r[0] for r in cur.fetchall()]
        if not db_groups:
            logger.error("No valid search groups found in public.job_group_skill_weights. Exiting.")
            return
        
        logger.info("Loaded %d unique search groups from CSDL.", len(db_groups))
        
        # 2. Fetch jobs with missing/unknown search_group
        logger.info("Querying jobs with 'unknown' or missing search_group...")
        cur.execute(
            "SELECT job_id, title FROM public.jobs WHERE search_group = 'unknown' OR search_group IS NULL"
        )
        jobs_to_update = cur.fetchall()
        if not jobs_to_update:
            logger.info("No jobs with 'unknown' or missing search_group found. Nothing to update.")
            return
            
        logger.info("Found %d jobs to update.", len(jobs_to_update))
        
        # 3. Load SentenceTransformer model
        logger.info("Loading SentenceTransformer model 'all-MiniLM-L6-v2'...")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.error("sentence-transformers library is required. Please install it: pip install sentence-transformers")
            return
            
        model = SentenceTransformer("all-MiniLM-L6-v2")
        
        # Compute embeddings for database groups
        logger.info("Computing embeddings for %d search groups...", len(db_groups))
        db_embeddings = model.encode(db_groups, normalize_embeddings=True)
        
        # 4. Map and update jobs
        logger.info("Processing and updating database records...")
        updated_count = 0
        
        # Perform updates in batches for performance
        for idx, (job_id, title) in enumerate(jobs_to_update):
            title_str = str(title).strip() if title else "unknown"
            
            # Compute title embedding
            title_emb = model.encode([title_str], normalize_embeddings=True)[0]
            
            # Cosine similarity matching
            sims = np.dot(db_embeddings, title_emb)
            best_idx = np.argmax(sims)
            matched_group = db_groups[best_idx]
            similarity = sims[best_idx]
            
            # Update job record in database
            cur.execute(
                "UPDATE public.jobs SET search_group = %s WHERE job_id = %s",
                (matched_group, job_id)
            )
            updated_count += 1
            
            if (idx + 1) % 50 == 0 or (idx + 1) == len(jobs_to_update):
                logger.info("Progress: %d/%d records updated.", idx + 1, len(jobs_to_update))
                conn.commit() # Commit periodically
                
        conn.commit()
        logger.info("Successfully updated %d jobs in the database.", updated_count)
        
    except Exception as e:
        conn.rollback()
        logger.error("An error occurred during database update: %s", e)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
