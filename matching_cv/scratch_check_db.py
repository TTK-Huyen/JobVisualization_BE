import sys
import os
from pathlib import Path

# Add parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matching_cv.match_cv import get_db_connection
from matching_cv.utils import load_db_env

load_db_env()
conn = get_db_connection()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM public.jobs")
count = cur.fetchone()[0]
print("Total jobs in DB:", count)

cur.execute("SELECT job_id, title, job_posting_url, scraped_at FROM public.jobs ORDER BY scraped_at DESC LIMIT 5")
rows = cur.fetchall()
print("Latest 5 jobs in DB:", rows)
conn.close()
