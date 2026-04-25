import json
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "123456"
}

QUERY = """
SELECT
    j.job_id,
    j.title,
    c.name AS company_name,
    j.description,
    j.skills_desc,
    j.formatted_experience_level,
    j.work_type,
    j.location,
    j.job_posting_url,
    COALESCE(
        ARRAY_AGG(DISTINCT s.skill_name) FILTER (WHERE s.skill_name IS NOT NULL),
        ARRAY[]::text[]
    ) AS skills_extracted
FROM jobs j
LEFT JOIN companies c ON c.company_id = j.company_id
LEFT JOIN job_skills js ON js.job_id = j.job_id
LEFT JOIN skills s ON s.skill_id = js.skill_id
GROUP BY
    j.job_id, j.title, c.name, j.description, j.skills_desc,
    j.formatted_experience_level, j.work_type, j.location, j.job_posting_url;
"""

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(QUERY)
            rows = cur.fetchall()

        jobs = []
        for row in rows:
            jobs.append({
                "job_id": row["job_id"],
                "title": row["title"] or "",
                "company_name": row["company_name"] or "",
                "description": row["description"] or "",
                "skills_desc": row["skills_desc"] or "",
                "formatted_experience_level": row["formatted_experience_level"] or "",
                "work_type": row["work_type"] or "",
                "location": row["location"] or "",
                "job_url": row["job_posting_url"] or "",
                "skills_extracted": row["skills_extracted"] or []
            })

        with open("jobs_from_db.json", "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)

        print(f"Exported {len(jobs)} jobs to jobs_from_db.json")

    finally:
        conn.close()

if __name__ == "__main__":
    main()