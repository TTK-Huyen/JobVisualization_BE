"""
SCRIPT 10: FETCH JOBS FROM DATABASE
Fetch all jobs from PostgreSQL and export as JSON for training
"""

import json
import os
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import DictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("[!] Warning: psycopg2 not installed.")
    print("    Install with: pip install psycopg2-binary")

# Get output directory
OUTPUT_DIR = os.getenv('PIPELINE_OUTPUT_DIR')
if OUTPUT_DIR:
    OUTPUT_DIR = Path(OUTPUT_DIR)
else:
    OUTPUT_DIR = Path(__file__).parent

# Get database credentials from environment
PG_HOST = os.getenv('PG_HOST', 'localhost')
PG_PORT = int(os.getenv('PG_PORT', '5432'))
PG_DB = os.getenv('PG_DB', 'postgres')
PG_USER = os.getenv('PG_USER', 'postgres')
PG_PASSWORD = os.getenv('PG_PASSWORD', '')

def fetch_jobs_from_db():
    """
    Fetch all jobs from PostgreSQL database.
    Expected table structure:
    - jobs (job_id, title, description, search_keyword, ...)
    - job_skills (job_id, skill_id)
    - skills (skill_id, name, category, ...)
    """
    
    if not PSYCOPG2_AVAILABLE:
        print("[!] psycopg2 not available!")
        return None
    
    try:
        print("📥 Connecting to PostgreSQL...")
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            database=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD
        )
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        print(f"   Connected to {PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB}")
        
        # Query: Get all jobs with their skills
        query = """
        SELECT 
            j.job_id,
            j.title,
            j.description,
            COALESCE(j.search_keyword, 'Unknown') as search_keyword,
            json_agg(
                json_build_object(
                    'name', s.skill_name,
                    'catxegory', COALESCE(s.skill_category, 'Unknown'),
                    'skill_abr', s.skill_name
                )
            ) FILTER (WHERE s.skill_id IS NOT NULL) as skills_with_category
        FROM jobs j
        LEFT JOIN job_skills js ON j.job_id = js.job_id
        LEFT JOIN skills s ON js.skill_id = s.skill_id
        GROUP BY j.job_id, j.title, j.description, j.search_keyword
        ORDER BY j.job_id
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"✓ Fetched {len(rows)} jobs from database")
        
        # Convert to list of dicts
        jobs = []
        for row in rows:
            job = {
                "job_id": row['job_id'],
                "title": row['title'],
                "description": row['description'],
                "search_keyword": row['search_keyword'],
                "skills_with_category": row['skills_with_category'] or []
            }
            jobs.append(job)
        
        cursor.close()
        conn.close()
        
        return jobs
        
    except Exception as e:
        print(f"[!] Database error: {e}")
        return None


def save_jobs_to_json(jobs, filename="jobs_from_database.json"):
    """Save fetched jobs to JSON file."""
    if not jobs:
        print("[!] No jobs to save!")
        return False
    
    output_file = OUTPUT_DIR / filename
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        
        file_size = output_file.stat().st_size / 1024
        print(f"✓ Saved {len(jobs)} jobs to {output_file}")
        print(f"  File size: {file_size:.1f} KB")
        
        return True
        
    except Exception as e:
        print(f"[!] Error saving JSON: {e}")
        return False


def print_summary(jobs):
    """Print summary of fetched jobs."""
    if not jobs:
        return
    
    print("\n" + "="*80)
    print("SUMMARY: Jobs From Database")
    print("="*80)
    
    print(f"\n📊 Total jobs: {len(jobs)}")
    
    # Group by search_keyword
    keywords = {}
    for job in jobs:
        kw = job.get('search_keyword', 'Unknown')
        if kw not in keywords:
            keywords[kw] = 0
        keywords[kw] += 1
    
    print(f"\n📋 Jobs by search_keyword:")
    for kw, count in sorted(keywords.items(), key=lambda x: -x[1]):
        print(f"   • {kw}: {count} jobs")
    
    # Sample job
    if jobs:
        print(f"\n📝 SAMPLE: First Job")
        print("="*80)
        job = jobs[0]
        print(f"   ID: {job['job_id']}")
        print(f"   Title: {job['title']}")
        print(f"   Keyword: {job['search_keyword']}")
        print(f"   Description: {job['description'][:100]}...")
        print(f"   Skills: {len(job['skills_with_category'])} skills")
        if job['skills_with_category']:
            for skill in job['skills_with_category'][:3]:
                print(f"      - {skill['name']} ({skill['category']})")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("[*] SCRIPT 10: FETCH JOBS FROM DATABASE")
    print("="*80 + "\n")
    
    # Fetch jobs from database
    print(f"[>] Database: {PG_HOST}:{PG_PORT}/{PG_DB}")
    print(f"[>] Output: {OUTPUT_DIR}\n")
    
    jobs = fetch_jobs_from_db()
    
    if jobs:
        # Save to JSON
        if save_jobs_to_json(jobs):
            # Print summary
            print_summary(jobs)
            print("\n✅ SUCCESS: Fetched and saved jobs from database")
        else:
            print("\n❌ FAILED: Could not save jobs")
    else:
        print("\n❌ FAILED: Could not fetch jobs from database")
        print("\nHint: Check PostgreSQL connection settings in .env:")
        print(f"   PG_HOST={PG_HOST}")
        print(f"   PG_PORT={PG_PORT}")
        print(f"   PG_DB={PG_DB}")
        print(f"   PG_USER={PG_USER}")
