import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys
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


def upsert_job(cur, rec: Dict[str, Any], company_id: Optional[int], fingerprint: str, valid_keywords: set, vi_to_en: dict) -> int:
    import logging
    title = unwrap_and_truncate(unwrap_value(rec.get("title")) or unwrap_value(rec.get("job", {}).get("title")), 500)
    skills_desc = unwrap_value(rec.get("job", {}).get("skills_desc")) or unwrap_value(rec.get("skills_desc"))
    description = unwrap_value(rec.get("description")) or unwrap_value(rec.get("raw", {}).get("requirements_text")) or unwrap_value(rec.get("requirements_text"))
    formatted_experience_level = unwrap_and_truncate(
        unwrap_value(rec.get("job", {}).get("formatted_experience_level"))
        or unwrap_value(rec.get("experience_raw"))
        or unwrap_value(rec.get("job", {}).get("experience_level")),
        100
    )
    work_type = unwrap_and_truncate(unwrap_value(rec.get("job", {}).get("work_type")), 100)
    raw_loc = unwrap_value(rec.get("location_raw")) or unwrap_value(rec.get("job", {}).get("location"))
    location = unwrap_and_truncate(normalize_location(raw_loc), 255)
    is_remote = unwrap_value(rec.get("job", {}).get("is_remote"))
    if is_remote is None:
        is_remote = unwrap_value(rec.get("is_remote"))
    listed_time = parse_datetime(rec.get("listed_time")) or parse_datetime(rec.get("job", {}).get("listed_time"))
    expiry_time = parse_datetime(rec.get("expiry_time")) or parse_datetime(rec.get("job", {}).get("expiry_time"))
    job_posting_url = unwrap_value(rec.get("job", {}).get("job_posting_url")) or unwrap_value(rec.get("job_url"))
    scraped_at = parse_datetime(rec.get("scraped_at"))
    applies = parse_number(rec.get("applies"))
    views = parse_number(rec.get("views"))
    job_category = unwrap_and_truncate(unwrap_value(rec.get("job", {}).get("job_category")), 100)

    # CHECK-POINT 1: Extract, normalize, and validate search_group keyword
    raw_search_group = unwrap_value(rec.get("job", {}).get("search_group")) or unwrap_value(rec.get("search_keyword"))
    search_group = None
    if raw_search_group:
        normalized_keyword = str(raw_search_group).lower().strip().replace("_", " ")
        
        # Translate to English if it is a Vietnamese keyword
        if normalized_keyword in vi_to_en:
            normalized_keyword = vi_to_en[normalized_keyword]

        if normalized_keyword in valid_keywords:
            search_group = normalized_keyword
        else:
            # Fallback direct database query to check if it exists dynamically
            cur.execute("SELECT 1 FROM public.search_group_keywords WHERE LOWER(REPLACE(TRIM(keyword), '_', ' ')) = %s LIMIT 1", (normalized_keyword,))
            if cur.fetchone():
                search_group = normalized_keyword
            else:
                logging.warning(
                    f"[CHECK-POINT 1] Crawled keyword validation failed: '{raw_search_group}' "
                    f"(normalized: '{normalized_keyword}') does not exist in public.search_group_keywords. "
                    "Temporarily assigning 'unknown' to prevent crash."
                )
                search_group = "unknown"
    else:
        search_group = "unknown"

    source_name = unwrap_and_truncate(unwrap_value(rec.get("source_name")), 50)
    source_id = unwrap_and_truncate(unwrap_value(rec.get("job_source_id")) or unwrap_value(rec.get("source_id")), 255)

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
    unique_skills = {}
    for it in normalized_skills or []:
        sid = it.get("skill_id")
        if not sid:
            continue
        sid = int(sid)
        reason = it.get("reason")
        model_name = it.get("model_name")
        similarity_score = it.get("confidence")
        lib_version = it.get("lib_version")
        raw_skill_name = it.get("original")
        if raw_skill_name is not None:
            raw_skill_name = str(raw_skill_name)[:255]
        
        try:
            score = float(similarity_score) if similarity_score is not None else 0.0
        except (ValueError, TypeError):
            score = 0.0

        if sid not in unique_skills or score > unique_skills[sid].get('_score', 0.0):
            unique_skills[sid] = {
                'reason': reason,
                'model_name': model_name,
                'similarity_score': similarity_score,
                'lib_version': lib_version,
                'raw_skill_name': raw_skill_name,
                '_score': score
            }
            
    rows = []
    for sid, info in unique_skills.items():
        rows.append((job_id, sid, False, info['reason'], info['model_name'], info['similarity_score'], info['lib_version'], info['raw_skill_name']))
        
    if not rows:
        return
    execute_values(
        cur,
        """
        INSERT INTO job_skills(job_id, skill_id, is_inferred, reason, model_name, similarity_score, lib_version, raw_skill_name)
        VALUES %s
        ON CONFLICT (job_id, skill_id)
        DO UPDATE SET
            reason = EXCLUDED.reason,
            model_name = EXCLUDED.model_name,
            similarity_score = EXCLUDED.similarity_score,
            lib_version = EXCLUDED.lib_version,
            raw_skill_name = EXCLUDED.raw_skill_name
        """,
        rows
    )


def insert_unmatched_skills(cur, source_id: int, source_type: str, unmatched_skills: List[Dict[str, Any]]) -> None:
    unique_unmatched = {}
    for it in unmatched_skills or []:
        raw_name = it.get("original")
        if not raw_name:
            continue
        raw_name = str(raw_name).strip()
        if not raw_name:
            continue
        
        # Limit to 255 chars
        raw_name = raw_name[:255]
        
        similarity_score = it.get("confidence", 0.0)
        if similarity_score is None:
            similarity_score = 0.0
        else:
            try:
                similarity_score = float(similarity_score)
            except (ValueError, TypeError):
                similarity_score = 0.0
                
        top_cand_name = it.get("top_candidate_name")
        top_cand_id = it.get("top_candidate_id")
        if top_cand_id is not None:
            try:
                top_cand_id = int(top_cand_id)
            except (ValueError, TypeError):
                top_cand_id = None

        if raw_name not in unique_unmatched:
            unique_unmatched[raw_name] = {
                'max_score': similarity_score,
                'count': 1,
                'top_cand_name': top_cand_name,
                'top_cand_id': top_cand_id
            }
        else:
            unique_unmatched[raw_name]['count'] += 1
            if similarity_score > unique_unmatched[raw_name]['max_score']:
                unique_unmatched[raw_name]['max_score'] = similarity_score
                unique_unmatched[raw_name]['top_cand_name'] = top_cand_name
                unique_unmatched[raw_name]['top_cand_id'] = top_cand_id
            
    rows = []
    for raw_name, info in unique_unmatched.items():
        rows.append((raw_name, info['count'], info['max_score'], info['top_cand_id'], info['top_cand_name'], 'UN_MATCHED'))
        
    if not rows:
        return
        
    # Step 1: Insert into unmatched_skills dictionary table
    returned = execute_values(
        cur,
        """
        INSERT INTO unmatched_skills(raw_skill_name, occurrence_count, max_similarity_score, top_candidate_skill_id, top_candidate_skill_name, analysis_type)
        VALUES %s
        ON CONFLICT (raw_skill_name)
        DO UPDATE SET
            occurrence_count = unmatched_skills.occurrence_count + EXCLUDED.occurrence_count,
            max_similarity_score = GREATEST(unmatched_skills.max_similarity_score, EXCLUDED.max_similarity_score),
            top_candidate_skill_id = COALESCE(unmatched_skills.top_candidate_skill_id, EXCLUDED.top_candidate_skill_id),
            top_candidate_skill_name = COALESCE(unmatched_skills.top_candidate_skill_name, EXCLUDED.top_candidate_skill_name),
            last_seen = CURRENT_TIMESTAMP
        RETURNING raw_skill_name, unmatched_id
        """,
        rows,
        fetch=True
    )
    
    # Map raw_skill_name to unmatched_id
    name_to_id = {row[0]: row[1] for row in returned}
    
    # Step 2: Insert mappings into unmatched_skill_sources bridge table
    bridge_rows = []
    for raw_name, info in unique_unmatched.items():
        unmatched_id = name_to_id.get(raw_name)
        if unmatched_id is not None:
            bridge_rows.append((source_id, unmatched_id, source_type, info['count'], info['max_score']))
            
    if not bridge_rows:
        return
        
    execute_values(
        cur,
        """
        INSERT INTO unmatched_skill_sources(source_id, unmatched_id, source_type, occurrence_count, max_similarity_score)
        VALUES %s
        ON CONFLICT (source_id, unmatched_id, source_type)
        DO UPDATE SET
            occurrence_count = unmatched_skill_sources.occurrence_count + EXCLUDED.occurrence_count,
            max_similarity_score = GREATEST(unmatched_skill_sources.max_similarity_score, EXCLUDED.max_similarity_score),
            last_seen = CURRENT_TIMESTAMP
        """,
        bridge_rows
    )


def insert_job_benefits(cur, job_id: int, normalized_benefits: List[Dict[str, Any]]) -> None:
    unique_bids = set()
    for it in normalized_benefits or []:
        bid = it.get("benefit_id")
        if not bid:
            continue
        unique_bids.add(int(bid))
        
    rows = [(job_id, bid, False) for bid in unique_bids]
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
    
    # Pre-load valid keywords from search_group_keywords for CHECK-POINT 1 validation
    try:
        cur.execute("SELECT keyword FROM public.search_group_keywords")
        valid_keywords = {str(row[0]).lower().strip().replace("_", " ") for row in cur.fetchall() if row[0]}
    except Exception as e:
        print(f"[WARNING] Could not load valid keywords from public.search_group_keywords: {e}")
        valid_keywords = set()

    # Load vi_to_en mapping from keywords_daily.json
    vi_to_en = {}
    try:
        config_path = BASE_DIR / "input" / "keywords_daily.json"
        if not config_path.exists():
            config_path = BASE_DIR / "keywords_daily.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for group_cfg in cfg.get("groups", {}).values():
                en_list = group_cfg.get("en", [])
                vi_list = group_cfg.get("vi", [])
                for en_kw, vi_kw in zip(en_list, vi_list):
                    en_clean = str(en_kw).lower().strip().replace("_", " ")
                    vi_clean = str(vi_kw).lower().strip().replace("_", " ")
                    if vi_clean and en_clean:
                        vi_to_en[vi_clean] = en_clean
    except Exception as e:
        print(f"[WARNING] Could not load vi_to_en mapping from keywords_daily.json: {e}")

    batch_size = 50
    pending_records_in_transaction = 0

    for rec in records:
        try:
            cur.execute("SAVEPOINT record_savepoint")
            fp = make_fingerprint(rec)

            comp = rec.get('company') or {}
            company_id = upsert_company(cur, comp) if comp else None
            cur.execute("SELECT job_id FROM jobs WHERE fingerprint = %s", (fp,))
            existing_job = cur.fetchone()
            job_id = upsert_job(cur, rec, company_id, fp, valid_keywords, vi_to_en)

            upsert_salary(cur, job_id, rec.get('salary') or {})

            insert_job_skills(cur, job_id, rec.get('normalized_skills') or [])
            insert_job_benefits(cur, job_id, rec.get('normalized_benefits') or [])
            insert_unmatched_skills(cur, job_id, 'job', rec.get('unmatched_skills') or [])

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

            cur.execute("RELEASE SAVEPOINT record_savepoint")
            if existing_job:
                stats["updated"] += 1
            else:
                stats["inserted"] += 1

            pending_records_in_transaction += 1

            # Commit in batches of 50 to optimize database IO
            if pending_records_in_transaction >= batch_size:
                conn.commit()
                pending_records_in_transaction = 0
        except Exception as e:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT record_savepoint")
            except Exception:
                pass
            stats['errors'] += 1
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

    # Commit any remaining pending records at the end of the loop
    if pending_records_in_transaction > 0:
        try:
            conn.commit()
        except Exception as e:
            print(f"[ERROR] Final commit failed: {e}")
            conn.rollback()
            stats['errors'] += pending_records_in_transaction
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
    parser.add_argument("--skip-weight-update", action="store_true", help="Skip updating skill weights after import")
    parser.add_argument("--weight-method", type=str, choices=["tf-idf", "llm"], default="tf-idf", help="Weighting method to update: 'tf-idf' or 'llm'")
    parser.add_argument("--stats-output", type=Path, help="Path to write import stats JSON")
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

    if args.stats_output:
        try:
            args.stats_output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.stats_output, "w", encoding="utf-8") as sf:
                json.dump(stats, sf, ensure_ascii=False, indent=2)
            print(f"[INFO] Stats saved to {args.stats_output}")
        except Exception as e:
            print(f"[WARNING] Could not write stats output: {e}")

    conn.close()

    # Check if database was updated/inserted and if we should update weights
    db_changed = stats.get("inserted", 0) > 0 or stats.get("updated", 0) > 0
    skip_env = os.getenv("SKIP_WEIGHT_UPDATE", "false").lower() in ("true", "1", "yes")

    if db_changed and not args.skip_weight_update and not skip_env:
        method = os.getenv("WEIGHT_METHOD", args.weight_method).lower()
        if method not in ("tf-idf", "llm"):
            method = "tf-idf"

        python_exe = sys.executable or "python"
        script_name = "tf_idf.py" if method == "tf-idf" else "build_skill_weights.py"
        script_path = BASE_DIR / "SkillWeighting" / script_name
        if not script_path.exists():
            script_path = BASE_DIR.parent / "SkillWeighting" / script_name

        if script_path.exists():
            print(f"\n[INFO] Triggering automated skill weighting ({method}) via {script_name}...")
            cmd = [python_exe, str(script_path)]
            try:
                subprocess.run(cmd, check=True)
                print("[INFO] Automated skill weighting completed successfully.")
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] Automated skill weighting failed with exit code {e.returncode}")
            except Exception as e:
                print(f"[ERROR] Failed to run automated skill weighting: {e}")
        else:
            print(f"[ERROR] Skill weighting script not found at: {script_path}")
    else:
        if not db_changed:
            print("\n[INFO] Skipping skill weighting update because no jobs were inserted or updated.")
        else:
            print("\n[INFO] Skill weighting update skipped via command line argument or environment variable.")


if __name__ == "__main__":
    main()
