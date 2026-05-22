import os
import sys
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

# Ensure we can import location_normalization
sys.path.append(str(Path(__file__).resolve().parent))
from location_normalization import normalize_location, normalize_country

def get_db_connection():
    base_dir = Path(__file__).resolve().parents[3]
    load_dotenv(base_dir / ".env")

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)

    host = os.getenv("POSTGRES_HOST") or os.getenv("PG_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PG_PORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("PG_DB") or "postgres"
    user = os.getenv("POSTGRES_USER") or os.getenv("PG_USER") or "postgres"
    pwd = os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD")

    conn_str = f"host={host} port={port} dbname={db} user={user} password={pwd}"
    return psycopg2.connect(conn_str)

def main():
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Starting location normalization migration...")

        # 1. Update jobs table (location)
        cur.execute("SELECT job_id, location FROM jobs;")
        jobs = cur.fetchall()
        jobs_to_update = []
        
        for job_id, loc in jobs:
            norm_loc = normalize_location(loc)
            # Compare. If original was None and normalized is None, skip.
            # Otherwise if they differ, add to update queue.
            if loc != norm_loc:
                jobs_to_update.append((norm_loc, job_id))

        if jobs_to_update:
            print(f"Updating {len(jobs_to_update)} jobs...")
            # We can run execute many or execute_values
            # Using execute_batch or execute_values
            # For simplicity and speed:
            from psycopg2.extras import execute_batch
            execute_batch(cur, "UPDATE jobs SET location = %s WHERE job_id = %s;", jobs_to_update)
        else:
            print("No jobs need location update.")

        # 2. Update companies table (city, country)
        cur.execute("SELECT company_id, city, country FROM companies;")
        companies = cur.fetchall()
        companies_to_update = []

        for company_id, city, country in companies:
            norm_city = normalize_location(city)
            norm_country = normalize_country(country)
            
            if city != norm_city or country != norm_country:
                companies_to_update.append((norm_city, norm_country, company_id))

        if companies_to_update:
            print(f"Updating {len(companies_to_update)} companies...")
            from psycopg2.extras import execute_batch
            execute_batch(cur, "UPDATE companies SET city = %s, country = %s WHERE company_id = %s;", companies_to_update)
        else:
            print("No companies need city/country update.")

        conn.commit()
        print("Migration completed successfully!")
        print(f"Total jobs updated: {len(jobs_to_update)}")
        print(f"Total companies updated: {len(companies_to_update)}")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
