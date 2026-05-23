import os
import sys
import logging
from pathlib import Path

# Configure stdout encoding to prevent Windows charmap exceptions
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_historical_jobs")

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

def run_historical_migration():
    load_db_env()
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. Load keywords from database sorted by length descending (to avoid sub-string matching errors)
        logger.info("Loading keywords from public.search_group_keywords...")
        cur.execute("SELECT keyword FROM public.search_group_keywords")
        keywords = [row[0] for row in cur.fetchall() if row[0]]
        
        # Sort by length descending to match longer keywords first (e.g. 'senior systems analyst' before 'systems analyst')
        sorted_keywords = sorted(keywords, key=len, reverse=True)
        logger.info(f"Loaded {len(sorted_keywords)} keywords for substring matching.")
        
        # 2. Fetch all legacy jobs
        logger.info("Fetching jobs from database...")
        cur.execute("SELECT job_id, title, search_group FROM public.jobs")
        jobs = cur.fetchall()
        logger.info(f"Retrieved {len(jobs)} jobs in total.")
        
        # 3. CHECK-POINT 2: Historical Data Substring Matching
        logger.info("Performing Substring Matching on job titles...")
        updated_count = 0
        skipped_count = 0
        unmatched_count = 0
        
        for job_id, title, current_search_group in jobs:
            if not title:
                continue
                
            title_lower = title.lower()
            matched_keyword = None
            
            # Find the longest matching keyword inside the job title
            for kw in sorted_keywords:
                if kw in title_lower:
                    matched_keyword = kw
                    break  # Found the longest match due to descending length sorting
            
            if matched_keyword:
                # Update if the search group is currently different or NULL
                if current_search_group != matched_keyword:
                    cur.execute("""
                        UPDATE public.jobs
                        SET search_group = %s
                        WHERE job_id = %s
                    """, (matched_keyword, job_id))
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                unmatched_count += 1
                # If it doesn't match any keyword, keep or set to NULL/unknown as needed.
                # Here we do not force overwrite if it already has a value, but we count it as unmatched.
                if current_search_group is None:
                    # Let's optionally set it to unknown/NULL if it's currently NULL and wasn't matched
                    pass

        conn.commit()
        logger.info("Historical data migration commits succeeded.")
        
        # 4. CHECK-POINT 3: Post-Migration Statistics Verification
        # Let's count totals directly from the database for accurate stats
        cur.execute("SELECT COUNT(*) FROM public.jobs")
        total_jobs = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM public.jobs WHERE search_group IS NOT NULL AND search_group != 'unknown'")
        normalized_jobs = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM public.jobs WHERE search_group IS NULL OR search_group = 'unknown'")
        unlabeled_jobs = cur.fetchone()[0]
        
        success_percentage = (normalized_jobs / total_jobs * 100.0) if total_jobs > 0 else 0.0
        
        print("\n" + "="*50)
        print("    CHECK-POINT 3: HẬU KIỂM TRA MIGRATION DỮ LIỆU CŨ")
        print("="*50)
        print(f"Tổng số jobs trong hệ thống:              {total_jobs}")
        print(f"Số job đã được chuẩn hóa thành công (khớp): {normalized_jobs}")
        print(f"Số job không khớp với từ khóa nào (unknown): {unlabeled_jobs}")
        print(f"Tỷ lệ gán nhãn thành công:                 {success_percentage:.2f}%")
        print(f"Số bản ghi vừa được cập nhật trong đợt này:  {updated_count}")
        print(f"Số bản ghi khớp nhưng đã giữ nguyên cấu hình: {skipped_count}")
        print("="*50 + "\n")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Historical job migration failed: {e}")
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_historical_migration()
