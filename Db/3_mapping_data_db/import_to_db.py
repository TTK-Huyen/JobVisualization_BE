import json
import os
import psycopg2
from psycopg2 import extras
from pathlib import Path
import unicodedata
import re
import sys

# Ensure console uses UTF-8 to avoid UnicodeEncodeError on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# [NEW] Import dotenv để đọc file .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("SUCCESS: Loaded environment variables from .env")
except ImportError:
    print("WARNING: python-dotenv not installed. Using system environment variables.")

# [NEW] Import constants để Seed data trực tiếp
try:
    import constants
except ImportError:
    constants = None
    print("WARNING: constants.py not found. Skill mapping may be inaccurate.")

# --- CẤU HÌNH DATABASE (Update theo file .env của bạn) ---
DB_CONFIG = {
    "dbname": os.getenv("PG_DB", "postgre"),      # Sửa khớp với .env của bạn
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", "123456"),
    "host": os.getenv("PG_HOST", "localhost"),    # Lưu ý: Host thường là localhost
    "port": os.getenv("PG_PORT", "5432")
}

JSON_FILE = 'clean/import_ready.json'  # Default
SQL_FILE = 'CreateDB.sql'

# Parse command line arguments
import sys
import argparse

parser = argparse.ArgumentParser(description='Import cleaned job data to PostgreSQL database')
parser.add_argument('--input', type=str, help='Input JSON file path from clean step')
args = parser.parse_args()

if args.input:
    JSON_FILE = args.input

def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}")
        print(f"TIP: Check .env file: {DB_CONFIG}")
        return None

def slugify(text):
    """Hàm tạo slug để đối chiếu dữ liệu"""
    if not text: return ""
    text = text.lower().replace("c++", "cpp").replace("c#", "c-sharp").replace(".net", "dot-net")
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text)
    return re.sub(r'[-\s]+', '-', text).strip('-')

def init_database(conn):
    """Đọc file SQL và tạo bảng"""
    print("1. Initializing database tables...")
    try:
        cur = conn.cursor()
        
        if not Path(SQL_FILE).exists():
            print(f"ERROR: SQL file not found: {SQL_FILE}")
            return False
            
        sql_content = Path(SQL_FILE).read_text(encoding='utf-8')
        cur.execute(sql_content)
        
        # Patch thêm cột nếu thiếu
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='jobs' AND column_name='job_category') THEN 
                    ALTER TABLE jobs ADD COLUMN job_category VARCHAR(100); 
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='jobs' AND column_name='fingerprint') THEN 
                    ALTER TABLE jobs ADD COLUMN fingerprint VARCHAR(32) UNIQUE; 
                END IF;
            END $$;
        """)
        
        # Migrate job_benefits table to new schema with benefit_id
        cur.execute("""
            DO $$ 
            BEGIN 
                -- Check if old schema exists (benefit_name column)
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='job_benefits' AND column_name='benefit_name') THEN
                    -- Drop old table and recreate with new schema
                    DROP TABLE IF EXISTS job_benefits CASCADE;
                    
                    CREATE TABLE IF NOT EXISTS job_benefits (
                        job_id BIGINT REFERENCES jobs(job_id) ON DELETE CASCADE,
                        benefit_id INT REFERENCES benefits(benefit_id) ON DELETE CASCADE,
                        is_inferred BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (job_id, benefit_id)
                    );
                END IF;
            END $$;
        """)

        conn.commit()
        cur.close()
        print("SUCCESS: Database tables created!")
        return True
    except Exception as e:
        conn.rollback()
        print(f"ERROR: Failed to create tables: {e}")
        return False

def seed_constants_data(conn):
    """
    Nạp dữ liệu chuẩn (Skills/Industries) từ constants.py vào DB TRƯỚC khi import Job.
    Điều này cực kỳ quan trọng để bảng job_skills tìm thấy ID.
    """
    if not constants: return
    print("2. Seeding standard data (Skills/Industries)...")
    cur = conn.cursor()
    
    # 1. Seed Industries
    if hasattr(constants, 'JOB_CATEGORIES'):
        for industry_name in constants.JOB_CATEGORIES.keys():
            cur.execute("INSERT INTO industries (industry_name) VALUES (%s) ON CONFLICT (industry_name) DO NOTHING", (industry_name,))
            
    # 2. Seed Skills
    if hasattr(constants, 'SKILL_KEYWORDS'):
        for category, skills_list in constants.SKILL_KEYWORDS.items():
            for skill in skills_list:
                # Insert skill with category
                cur.execute("""
                    INSERT INTO skills (skill_name, category) 
                    VALUES (%s, %s) 
                    ON CONFLICT (skill_name) DO UPDATE SET category = EXCLUDED.category
                """, (skill, category))
    
    # 3. Seed Benefits
    if hasattr(constants, 'BENEFITS_KEYWORDS'):
        for category, benefits_list in constants.BENEFITS_KEYWORDS.items():
            for benefit in benefits_list:
                # Insert và update category nếu đã tồn tại
                cur.execute("""
                    INSERT INTO benefits (benefit_name, category) 
                    VALUES (%s, %s) 
                    ON CONFLICT (benefit_name) DO UPDATE SET category = EXCLUDED.category
                """, (benefit, category))
    
    conn.commit()
    cur.close()
    print("SUCCESS: Standard data seeding completed.")

def load_json_data():
    if not Path(JSON_FILE).exists():
        print(f"ERROR: JSON file not found: {JSON_FILE}. Run transform_for_import.py first.")
        return None
    return json.loads(Path(JSON_FILE).read_text(encoding='utf-8'))

def import_data(conn, data):
    print("3. Importing job data from JSON...")
    cur = conn.cursor()
    
    # [NEW] Validate job categories against constants
    valid_categories = set(constants.JOB_CATEGORIES.keys()) if hasattr(constants, 'JOB_CATEGORIES') else set()
    print(f"✓ Valid job categories: {sorted(valid_categories)}")
    
    # Statistics tracking
    stats = {
        'total_jobs_in_file': 0,
        'new_jobs_inserted': 0,
        'duplicate_jobs_skipped': 0,
        'companies_processed': 0,
        'salaries_inserted': 0,
        'benefits_inserted': 0,
        'job_skills_linked': 0,
        'job_industries_linked': 0
    }
    
    # --- LOAD MAP ID TỪ DB (QUAN TRỌNG) ---
    # Sau khi seed, chúng ta lấy ID thực tế từ DB để map vào JSON
    cur.execute("SELECT skill_name, skill_id FROM skills")
    db_skills_map = {row[0].lower(): row[1] for row in cur.fetchall()} 
    
    cur.execute("SELECT industry_name, industry_id FROM industries")
    db_industries_map = {row[0].lower(): row[1] for row in cur.fetchall()}
    
    cur.execute("SELECT benefit_name, benefit_id FROM benefits")
    db_benefits_map = {row[0].lower(): row[1] for row in cur.fetchall()} 

    # Map ID tạm trong JSON -> Skill name
    json_skill_temp_to_name = {s['temp_id']: s['skill_name'] for s in data.get('skills_master', [])}
    json_ind_temp_to_name = {i['temp_id']: i['industry_name'] for i in data.get('industries', [])}

    # --- IMPORT COMPANIES ---
    companies_data = []
    for c in data.get('companies', []):
        companies_data.append((c['temp_id'], c['name'], c.get('size', ''), c.get('address', ''), c.get('website', '')))
    
    if companies_data:
        stats['companies_processed'] = len(companies_data)
        extras.execute_values(cur, """
            INSERT INTO companies (company_id, name, description, address, url) VALUES %s
            ON CONFLICT (company_id) DO UPDATE SET name = EXCLUDED.name;
        """, companies_data)

    # --- IMPORT JOBS ---
    jobs_data = []
    invalid_categories_found = []
    
    for j in data.get('jobs', []):
        # [NEW] Validate job category
        job_category = j.get('job_category', 'Other')
        if job_category not in valid_categories:
            invalid_categories_found.append({
                'job_id': j.get('temp_id'),
                'title': j.get('title', 'N/A'),
                'category': job_category
            })
            continue  # Skip jobs with invalid categories
        
        # Parse posted_date - convert invalid dates to None
        posted_date = j.get('posted_date')
        if posted_date and not posted_date.replace('-', '').replace('/', '').replace(':', '').replace(' ', '').isdigit():
            # If contains non-numeric characters like "1 week ago", set to None
            posted_date = None
        
        jobs_data.append((
            j['company_temp_id'], j['title'], job_category,
            j.get('description', ''), j.get('requirements', ''), j.get('formatted_experience_level'),
            j.get('formatted_work_type'), j.get('remote_allowed', False), j.get('job_url'),
            j.get('fingerprint'), posted_date
        ))

    # [NEW] Report invalid categories if found
    if invalid_categories_found:
        print(f"\n⚠️  VALIDATION WARNING: {len(invalid_categories_found)} jobs skipped due to invalid categories!")
        for item in invalid_categories_found[:5]:
            print(f"  - Job {item['job_id']} ({item['title'][:50]}): category '{item['category']}'")
        if len(invalid_categories_found) > 5:
            print(f"  ... and {len(invalid_categories_found) - 5} more")

    stats['total_jobs_in_file'] = len(jobs_data)
    stats['invalid_categories_skipped'] = len(invalid_categories_found)
    
    if jobs_data:
        # Get existing job IDs and fingerprints BEFORE insertion
        cur.execute("SELECT job_id FROM jobs")
        existing_job_ids_before = {row[0] for row in cur.fetchall()}
        
        # Use UPSERT to handle duplicates by both job_id and fingerprint
        # Since PostgreSQL only allows one ON CONFLICT clause, we prioritize job_id
        # But fingerprint uniqueness will still be enforced, so we handle it with filtering
        try:
            extras.execute_values(cur, """
                INSERT INTO jobs (
                    company_id, title, job_category, description, skills_desc, 
                    formatted_experience_level, work_type, is_remote, job_posting_url, fingerprint, listed_time
                ) VALUES %s ON CONFLICT (fingerprint) DO NOTHING;
            """, jobs_data)
        except (psycopg2.errors.UniqueViolation, psycopg2.errors.ForeignKeyViolation) as e:
            # If fingerprint or foreign key conflict, try inserting only new jobs
            if 'fingerprint' in str(e):
                print("[INFO] Fingerprint duplicate detected; filtering new jobs...")
                # Rollback the failed transaction before continuing
                conn.rollback()
                # Get existing fingerprints and valid company IDs
                cur = conn.cursor()
                cur.execute("SELECT fingerprint FROM jobs WHERE fingerprint IS NOT NULL")
                existing_fingerprints = {row[0] for row in cur.fetchall()}
                cur.execute("SELECT company_id FROM companies")
                valid_company_ids = {row[0] for row in cur.fetchall()}
                
                # Filter out duplicates and jobs with non-existent companies
                filtered_jobs = [j for j in jobs_data if j[10] not in existing_fingerprints and j[1] in valid_company_ids]  # j[10] is fingerprint, j[1] is company_id
                stats['duplicate_jobs_skipped'] = len(jobs_data) - len(filtered_jobs)
                
                if filtered_jobs:
                    extras.execute_values(cur, """
                        INSERT INTO jobs (
                            company_id, title, job_category, description, skills_desc, 
                            formatted_experience_level, work_type, is_remote, job_posting_url, fingerprint, listed_time
                        ) VALUES %s ON CONFLICT (fingerprint) DO NOTHING;
                    """, [
                        (
                            j[0], j[1], j[2], j[3], j[4], j[5], j[6], j[7], j[8], j[9], j[10]
                        ) for j in filtered_jobs
                    ])
            elif 'company_id' in str(e):
                print(f"[WARN] Bỏ qua jobs có company không tồn tại")
                # Rollback the failed transaction before continuing
                conn.rollback()
                cur = conn.cursor()
                # Get valid company IDs
                cur.execute("SELECT company_id FROM companies")
                valid_company_ids = {row[0] for row in cur.fetchall()}
                
                # Filter out jobs with non-existent companies
                filtered_jobs = [j for j in jobs_data if j[1] in valid_company_ids]  # j[1] is company_id
                
                if filtered_jobs:
                    extras.execute_values(cur, """
                        INSERT INTO jobs (
                            company_id, title, job_category, description, skills_desc, 
                            formatted_experience_level, work_type, is_remote, job_posting_url, fingerprint, listed_time
                        ) VALUES %s ON CONFLICT (fingerprint) DO NOTHING;
                    """, [
                        (
                            j[0], j[1], j[2], j[3], j[4], j[5], j[6], j[7], j[8], j[9], j[10]
                        ) for j in filtered_jobs
                    ])
            else:
                raise
        
        # Calculate how many new jobs were actually inserted
        cur.execute("SELECT job_id FROM jobs")
        existing_job_ids_after = {row[0] for row in cur.fetchall()}
        stats['new_jobs_inserted'] = len(existing_job_ids_after - existing_job_ids_before)
        stats['duplicate_jobs_skipped'] = stats['total_jobs_in_file'] - stats['new_jobs_inserted']

    # --- GET VALID JOB IDS FOR DEPENDENT TABLES ---
    cur.execute("SELECT job_id FROM jobs")
    valid_job_ids = {row[0] for row in cur.fetchall()}

    # --- IMPORT SALARIES ---
    salaries_data = [(s['job_temp_id'], s['min_salary'], s['max_salary'], s['med_salary'], s['currency'], s['pay_period']) for s in data.get('salaries', []) if s['job_temp_id'] in valid_job_ids]
    if salaries_data:
        extras.execute_values(cur, "INSERT INTO salaries (job_id, min_salary, max_salary, med_salary, currency, pay_period) VALUES %s ON CONFLICT DO NOTHING", salaries_data)
        stats['salaries_inserted'] = len(salaries_data)

    # --- IMPORT BENEFITS ---
    job_benefits_data = set()
    for jb in data.get('job_benefits', []):
        # Only add benefits for jobs that were successfully inserted
        if jb['job_temp_id'] not in valid_job_ids:
            continue
            
        benefit_name_lower = jb['benefit_name'].lower()
        real_benefit_id = db_benefits_map.get(benefit_name_lower)
        
        # Nếu không tìm thấy trong DB (benefit mới), insert vào DB
        if not real_benefit_id:
            try:
                cur.execute(
                    "INSERT INTO benefits (benefit_name, category) VALUES (%s, 'Uncategorized') RETURNING benefit_id",
                    (jb['benefit_name'],)
                )
                real_benefit_id = cur.fetchone()[0]
                db_benefits_map[benefit_name_lower] = real_benefit_id  # Cập nhật cache
            except:
                conn.rollback()  # Bỏ qua nếu lỗi
                continue
        
        if real_benefit_id:
            job_benefits_data.add((jb['job_temp_id'], real_benefit_id, jb.get('is_inferred', False)))
    
    if job_benefits_data:
        extras.execute_values(
            cur,
            "INSERT INTO job_benefits (job_id, benefit_id, is_inferred) VALUES %s ON CONFLICT DO NOTHING",
            list(job_benefits_data)
        )
        stats['benefits_inserted'] = len(job_benefits_data)

    # --- IMPORT JOB SKILLS (LINKING) ---
    job_skills_data = set()
    for js in data.get('job_skills', []):
        # Only add skills for jobs that were successfully inserted
        if js['job_temp_id'] not in valid_job_ids:
            continue
            
        skill_name = json_skill_temp_to_name.get(js['skill_temp_id'])
        real_skill_id = db_skills_map.get(skill_name.lower() if skill_name else None) # Tìm ID thực trong DB
        
        # Nếu không tìm thấy trong DB → BỎ QUA (không thêm skill mới)
        # Chỉ thêm skills có trong constants.py
        if real_skill_id:
            job_skills_data.add((js['job_temp_id'], real_skill_id, js.get('is_inferred', False)))
            
    if job_skills_data:
        extras.execute_values(cur, "INSERT INTO job_skills (job_id, skill_id, is_inferred) VALUES %s ON CONFLICT DO NOTHING", list(job_skills_data))
        stats['job_skills_linked'] = len(job_skills_data)

    # --- IMPORT JOB INDUSTRIES (LINKING) ---
    job_inds_data = set()
    for ji in data.get('job_industries', []):
        # Only add industries for jobs that were successfully inserted
        if ji['job_temp_id'] not in valid_job_ids:
            continue
            
        ind_name = json_ind_temp_to_name.get(ji['industry_temp_id'], "").lower()
        real_ind_id = db_industries_map.get(ind_name)
        if real_ind_id:
            job_inds_data.add((ji['job_temp_id'], real_ind_id))

    if job_inds_data:
        extras.execute_values(cur, "INSERT INTO job_industries (job_id, industry_id) VALUES %s ON CONFLICT DO NOTHING", list(job_inds_data))
        stats['job_industries_linked'] = len(job_inds_data)

    conn.commit()
    cur.close()
    
    # Print detailed statistics
    print("\n" + "="*70)
    print("IMPORT STATISTICS:")
    print("="*70)
    print(f"Jobs in file       : {stats['total_jobs_in_file']}")
    print(f"New jobs inserted  : {stats['new_jobs_inserted']}")
    print(f"Jobs skipped (dup) : {stats['duplicate_jobs_skipped']}")
    print(f"Companies touched  : {stats['companies_processed']}")
    print(f"Salaries inserted  : {stats['salaries_inserted']}")
    print(f"Benefits inserted  : {stats['benefits_inserted']}")
    print(f"Job-Skills linked  : {stats['job_skills_linked']}")
    print(f"Job-Industries linked: {stats['job_industries_linked']}")
    print("="*70)
    
    if stats['new_jobs_inserted'] == 0:
        print("\nNO NEW JOBS - All jobs already exist in DB.")
    else:
        print(f"\nSUCCESS: Imported {stats['new_jobs_inserted']} new jobs.")
    print()

if __name__ == "__main__":
    conn = get_connection()
    if conn:
        if init_database(conn):      # Bước 1: Tạo bảng
            seed_constants_data(conn) # Bước 2: Nạp dữ liệu chuẩn
            json_data = load_json_data()
            if json_data:
                import_data(conn, json_data) # Bước 3: Nạp dữ liệu job
        conn.close()