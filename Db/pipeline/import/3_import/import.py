import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
import re
import unicodedata
from location_normalization import normalize_location, normalize_country

def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".env").exists() or (parent / "run_etl_pipeline.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]

BASE_DIR = find_project_root()


def load_json(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if isinstance(data, list):
        return data
    # support newline-delimited JSON
    if isinstance(data, dict):
        return [data]
    raise ValueError("Unsupported input JSON format")


def get_db_connection():
    load_dotenv(BASE_DIR / ".env")

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)

    host = os.getenv("POSTGRES_HOST") or os.getenv("PG_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PG_PORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("PG_DB") or "postgres"
    user = os.getenv("POSTGRES_USER") or os.getenv("PG_USER") or "postgres"
    pwd = os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD")

    print(f"[DEBUG] DB connect: user={user}, db={db}, host={host}, port={port}")

    conn_str = f"host={host} port={port} dbname={db} user={user} password={pwd}"
    return psycopg2.connect(conn_str)

def unwrap_value(v: Any) -> Any:
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def unwrap_and_truncate(v: Any, max_len: int) -> Optional[str]:
    val = unwrap_value(v)
    if val is None:
        return None
    return str(val)[:max_len]



def parse_datetime(v: Any) -> Optional[str]:
    v = unwrap_value(v)
    if not v:
        return None
    if isinstance(v, (int, float)):
        return None
    s = str(v).strip()
    if not s:
        return None
    # try ISO
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        return dt.isoformat()
    except Exception:
        pass
    # common date-only formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat()
        except Exception:
            continue
    return None


def parse_number(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    # remove non-numeric except .,-
    s2 = s.replace(',', '')
    try:
        return float(s2)
    except Exception:
        return None


def make_fingerprint(rec: Dict[str, Any]) -> str:
    title = normalize_for_fingerprint(
        rec.get("title") or rec.get("job", {}).get("title") or ""
    )

    company_name = normalize_for_fingerprint(
        rec.get("company_name")
        or rec.get("company", {}).get("name")
        or ""
    )

    skills_desc = normalize_for_fingerprint(
        rec.get("job", {}).get("skills_desc")
        or rec.get("skills_desc")
        or ""
    )

    raw = "|".join([title, company_name, skills_desc])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def upsert_company(cur, comp: Dict[str, Any]) -> Optional[int]:
    name = unwrap_and_truncate(comp.get("name") or comp.get("company_name"), 255)
    if not name:
        return None
    url = unwrap_and_truncate(comp.get("url") or comp.get("company_website"), 500)
    # try find by name and url
    if url:
        cur.execute("SELECT company_id FROM companies WHERE name = %s AND url = %s", (name, url))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("SELECT company_id FROM companies WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    # create new company_id as max+1
    cur.execute("SELECT COALESCE(MAX(company_id), 0) + 1 FROM companies")
    new_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO companies(company_id, name, description, company_size_min, company_size_max, country, city, address, url, industry) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            new_id,
            name,
            unwrap_value(comp.get("description")),
            parse_number(comp.get("company_size_min")),
            parse_number(comp.get("company_size_max")),
            unwrap_and_truncate(normalize_country(comp.get("country")), 100),
            unwrap_and_truncate(normalize_location(comp.get("city")), 100),
            unwrap_value(comp.get("address")),
            url,
            unwrap_and_truncate(comp.get("industry"), 255),
        ),
    )
    return new_id


def upsert_job(cur, rec: Dict[str, Any], company_id: Optional[int], fingerprint: str) -> int:
    title = unwrap_and_truncate(rec.get("title") or rec.get("job", {}).get("title"), 500)
    skills_desc = unwrap_value(rec.get("job", {}).get("skills_desc") or rec.get("skills_desc"))
    description = unwrap_value(rec.get("description") or rec.get("raw", {}).get("requirements_text") or rec.get("requirements_text"))
    formatted_experience_level = unwrap_and_truncate(
        rec.get("job", {}).get("formatted_experience_level")
        or rec.get("experience_raw")
        or rec.get("job", {}).get("experience_level"),
        100
    )
    work_type = unwrap_and_truncate(rec.get("job", {}).get("work_type"), 100)
    raw_loc = rec.get("location_raw") or rec.get("job", {}).get("location")
    location = unwrap_and_truncate(normalize_location(raw_loc), 255)
    is_remote = unwrap_value(rec.get("job", {}).get("is_remote") or rec.get("is_remote"))
    listed_time = parse_datetime(rec.get("listed_time") or rec.get("job", {}).get("listed_time"))
    expiry_time = parse_datetime(rec.get("expiry_time") or rec.get("job", {}).get("expiry_time"))
    job_posting_url = unwrap_value(rec.get("job", {}).get("job_posting_url") or rec.get("job_url") or rec.get("job", {}).get("job_posting_url"))
    scraped_at = parse_datetime(rec.get("scraped_at"))
    applies = parse_number(rec.get("applies"))
    views = parse_number(rec.get("views"))
    job_category = unwrap_and_truncate(rec.get("job", {}).get("job_category"), 100)
    search_group = unwrap_and_truncate(rec.get("job", {}).get("search_group") or rec.get("search_keyword"), 100)
    source_name = unwrap_and_truncate(rec.get("source_name"), 50)
    source_id = unwrap_and_truncate(rec.get("job_source_id") or rec.get("source_id"), 255)

    # Insert or update by fingerprint
    cur.execute(
        "INSERT INTO jobs(company_id, title, skills_desc, description, formatted_experience_level, work_type, location, is_remote, listed_time, expiry_time, job_posting_url, scraped_at, applies, views, fingerprint, job_category, search_group, source_name, source_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fingerprint) DO UPDATE SET company_id = EXCLUDED.company_id, title = EXCLUDED.title, skills_desc = EXCLUDED.skills_desc, description = EXCLUDED.description, formatted_experience_level = EXCLUDED.formatted_experience_level, work_type = EXCLUDED.work_type, location = EXCLUDED.location, is_remote = EXCLUDED.is_remote, listed_time = EXCLUDED.listed_time, expiry_time = EXCLUDED.expiry_time, job_posting_url = EXCLUDED.job_posting_url, scraped_at = EXCLUDED.scraped_at, applies = EXCLUDED.applies, views = EXCLUDED.views, job_category = EXCLUDED.job_category, search_group = EXCLUDED.search_group, source_name = EXCLUDED.source_name, source_id = EXCLUDED.source_id RETURNING job_id",
        (
            company_id,
            title,
            skills_desc,
            description,
            formatted_experience_level,
            work_type,
            location,
            is_remote,
            listed_time,
            expiry_time,
            job_posting_url,
            scraped_at,
            applies,
            views,
            fingerprint,
            job_category,
            search_group,
            source_name,
            source_id,
        ),
    )
    return cur.fetchone()[0]


def upsert_salary(cur, job_id: int, salary: Dict[str, Any]) -> None:
    if not salary:
        return
    min_s = parse_number(salary.get("min_salary"))
    max_s = parse_number(salary.get("max_salary"))
    med_s = parse_number(salary.get("med_salary"))
    currency = unwrap_and_truncate(salary.get("currency"), 10)
    pay_period = unwrap_and_truncate(salary.get("pay_period"), 20)

    # check existing by job_id
    cur.execute("SELECT salary_id FROM salaries WHERE job_id = %s", (job_id,))
    r = cur.fetchone()
    if r:
        cur.execute(
            "UPDATE salaries SET min_salary=%s, max_salary=%s, med_salary=%s, currency=%s, pay_period=%s WHERE job_id=%s",
            (min_s, max_s, med_s, currency, pay_period, job_id),
        )
    else:
        cur.execute(
            "INSERT INTO salaries(job_id, min_salary, max_salary, med_salary, currency, pay_period) VALUES (%s,%s,%s,%s,%s,%s)",
            (job_id, min_s, max_s, med_s, currency, pay_period),
        )


def insert_job_skills(cur, job_id: int, normalized_skills: List[Dict[str, Any]]) -> None:
    rows = []
    for it in normalized_skills or []:
        sid = it.get("skill_id")
        if not sid:
            continue
        rows.append((job_id, int(sid), False))
    if not rows:
        return
    execute_values(cur,
                   "INSERT INTO job_skills(job_id, skill_id, is_inferred) VALUES %s ON CONFLICT (job_id, skill_id) DO NOTHING",
                   rows)


def insert_job_benefits(cur, job_id: int, normalized_benefits: List[Dict[str, Any]]) -> None:
    rows = []
    for it in normalized_benefits or []:
        bid = it.get("benefit_id")
        if not bid:
            continue
        rows.append((job_id, int(bid), False))
    if not rows:
        return
    execute_values(cur,
                   "INSERT INTO job_benefits(job_id, benefit_id, is_inferred) VALUES %s ON CONFLICT (job_id, benefit_id) DO NOTHING",
                   rows)


def insert_company_industries(cur, company_id: int, industry_value: Any) -> None:
    if not industry_value:
        return
    name = unwrap_and_truncate(industry_value, 255)
    if not name:
        return
    # ensure industries row
    cur.execute("SELECT industry_id FROM industries WHERE industry_name = %s", (name,))
    r = cur.fetchone()
    if r:
        iid = r[0]
    else:
        cur.execute("INSERT INTO industries(industry_name) VALUES (%s) RETURNING industry_id", (name,))
        iid = cur.fetchone()[0]
    # link company_industries
    cur.execute("INSERT INTO company_industries(company_id, industry_id) VALUES (%s,%s) ON CONFLICT (company_id, industry_id) DO NOTHING", (company_id, iid))


def import_records(conn, records: List[Dict[str, Any]], fallback_path: Path) -> Dict[str, int]:
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    cur = conn.cursor()
    for rec in records:
        try:
            fp = make_fingerprint(rec)

            comp = rec.get('company') or {}
            company_id = upsert_company(cur, comp) if comp else None
            cur.execute("SELECT job_id FROM jobs WHERE fingerprint = %s", (fp,))
            existing_job = cur.fetchone()
            job_id = upsert_job(cur, rec, company_id, fp)

            upsert_salary(cur, job_id, rec.get('salary') or {})

            insert_job_skills(cur, job_id, rec.get('normalized_skills') or [])
            insert_job_benefits(cur, job_id, rec.get('normalized_benefits') or [])

            # company industries
            try:
                cur.execute("SAVEPOINT sp_industry")
                insert_company_industries(cur, company_id, rec.get('company', {}).get('industry') or rec.get('industry') or rec.get('industries'))
                cur.execute("RELEASE SAVEPOINT sp_industry")
            except Exception:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_industry")
                except Exception:
                    pass

            conn.commit()
            if existing_job:
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
        except Exception as e:
            stats['errors'] += 1
            conn.rollback()
            # append fallback
            entry = {"record": rec, "error": str(e)}
            if fallback_path:
                if fallback_path.exists():
                    try:
                        arr = json.loads(fallback_path.read_text(encoding='utf-8-sig') or '[]')
                    except Exception:
                        arr = []
                else:
                    arr = []
                arr.append(entry)
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_path.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding='utf-8')
            # continue with next record
    cur.close()
    return stats


def normalize_for_fingerprint(text: Any) -> str:
    text = unwrap_value(text)
    if not text:
        return ""

    text = str(text).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # chỉ giữ chữ và số, bỏ ký tự đặc biệt
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, default=BASE_DIR / "3_import" / "import_fallback.json")
    args = parser.parse_args()

    # Clear previous fallback file if it exists
    if args.fallback and args.fallback.exists():
        try:
            args.fallback.unlink()
        except Exception as e:
            print(f"[WARNING] Could not delete old fallback file: {e}")

    records = load_json(args.input)
    conn = get_db_connection()
    conn.autocommit = False

    stats = import_records(conn, records, args.fallback)
    print(json.dumps(stats, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
