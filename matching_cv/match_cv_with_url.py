#!/usr/bin/env python3
"""
CV Matching Engine with Job URL crawling, normalization, and database updates.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import subprocess
import importlib.util
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("match_cv_with_url")

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

# Import utilities from matching_cv.match_cv
try:
    from matching_cv.match_cv import (
        get_db_connection,
        extract_student_skills_gemini,
        normalize_student_skills,
        upsert_user_cv,
        save_user_cv_skills,
        fetch_job_group_weights,
        load_skill_embedding_cache,
        get_skill_similarity,
        insert_unmatched_skills
    )
    from matching_cv.utils import extract_cv_text, load_db_env
    load_db_env()
except ImportError as e:
    logger.error("Failed to import dependencies from match_cv: %s", e)
    sys.exit(1)

def json_serializable(obj):
    """JSON serializer for objects not serializable by default json code"""
    import datetime
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def load_scraper_module(folder_name: str, script_name: str):
    """
    Dynamically load a scraper module using spec_from_file_location
    to bypass Python hyphen-in-folder import syntax limits.
    """
    crawl_dir = PROJECT_ROOT / "Db" / "pipeline" / "crawl" / "1_crawl_data" / "crawl_data" / folder_name / "scripts"
    script_path = crawl_dir / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Scraper script not found: {script_path}")
    
    # Also add parent folders so schema and utilities import correctly
    parent_crawl_dir = crawl_dir.parent.parent
    if str(parent_crawl_dir) not in sys.path:
        sys.path.insert(0, str(parent_crawl_dir))
    if str(crawl_dir) not in sys.path:
        sys.path.insert(0, str(crawl_dir))
        
    spec = importlib.util.spec_from_file_location(f"dynamic_{folder_name.replace('-', '_')}", str(script_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _validate_raw_job(raw_dict: Dict[str, Any], url: str) -> None:
    """Raise early if the scraped job has no usable content."""
    title = raw_dict.get("title") or ""
    desc = raw_dict.get("description_html") or ""
    req = raw_dict.get("requirements_text") or ""
    if not desc.strip() and not req.strip():
        raise RuntimeError(
            f"Scraped job at {url} has no content (description_html and requirements_text are empty). "
            f"title='{title}'. The URL may be dead, blocked (403), or behind a login wall."
        )

def crawl_job_url(url: str) -> Dict[str, Any]:
    """
    Scrape job detail from the given URL using the appropriate scraper module.
    """
    logger.info("Scraping job details from URL: %s", url)
    url_lower = url.lower()
    
    if "itviec.com" in url_lower:
        module = load_scraper_module("crawl-itviec-jobs", "scrape_itviec.py")
        raw_job = module.scrape_job_detail(url)
        if raw_job:
            raw_dict = raw_job.to_dict()
            # Selenium fallback: if cloudscraper was blocked (empty content), try Selenium
            if not (raw_dict.get("description_html") or "").strip():
                logger.warning("itviec cloudscraper returned empty content (likely 403). Trying Selenium fallback...")
                try:
                    linkedin_module = load_scraper_module("crawl-linkedin-jobs", "scrape_linkedin.py")
                    driver = linkedin_module.build_driver()
                    try:
                        from bs4 import BeautifulSoup
                        clean_url = url.split("?")[0]
                        driver.get(clean_url)
                        import time as _time
                        _time.sleep(4)
                        soup = BeautifulSoup(driver.page_source, "html.parser")
                        # Re-parse with the same itviec parser logic
                        raw_job2 = module.scrape_job_detail.__wrapped__(url) if hasattr(module.scrape_job_detail, '__wrapped__') else None
                        # Simpler: extract description_html directly from Selenium page source
                        job_content = soup.select_one("section.job-content, section[data-jobs--jd-scroll-target='jobContent']")
                        if job_content:
                            raw_dict["description_html"] = str(job_content)
                            # Try to get title from Selenium page
                            title_elem = soup.select_one("div.job-header-info h1, h1.job-title")
                            if title_elem:
                                raw_dict["title"] = title_elem.get_text(strip=True)
                            logger.info("Selenium fallback: got description_html (%d chars)", len(raw_dict["description_html"]))
                    finally:
                        driver.quit()
                except Exception as se:
                    logger.warning("Selenium fallback for itviec also failed: %s", se)
            _validate_raw_job(raw_dict, url)
            return raw_dict
            
    elif "careerviet.vn" in url_lower or "careerbuilder.vn" in url_lower:
        import requests
        module = load_scraper_module("crawl-careerviet-jobs", "scrape_careerviet.py")
        session = requests.Session()
        # Set standard headers for session if needed
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        raw_dict = module.scrape_job_detail(session, url)
        if raw_dict:
            job_dict = {
                "title": raw_dict.get("detail_title"),
                "job_url": url,
                "company": raw_dict.get("company_name_from_job"),
                "company_url": raw_dict.get("company_url_from_job")
            }
            company_dict = {}
            raw_job = module.convert_to_raw_job_data(job_dict, raw_dict, company_dict)
            if raw_job:
                result = raw_job.to_dict()
                _validate_raw_job(result, url)
                return result
            
    elif "vietnamworks.com" in url_lower:
        import requests
        module = load_scraper_module("crawl-vietnamwork-jobs", "scrape_vietnamwork.py")
        session = module.build_session()
        detail_dict = module.scrape_job_detail_raw(session, url)
        job_dict = {"job_url": url, "title": None, "company": None}
        raw_job = module.convert_to_raw_job_data(job_dict, detail_dict)
        if raw_job:
            result = raw_job.to_dict()
            _validate_raw_job(result, url)
            return result
            
    elif "linkedin.com" in url_lower:
        module = load_scraper_module("crawl-linkedin-jobs", "scrape_linkedin.py")
        driver = module.build_driver()
        try:
            job_detail = module.extract_job_detail_from_url(url, driver)
            raw_job = module.convert_to_raw_job_data(job_detail)
            if raw_job:
                result = raw_job.to_dict()
                _validate_raw_job(result, url)
                return result
        finally:
            driver.quit()
    else:
        raise ValueError(f"Unsupported job URL domain: {url}")
        
    raise RuntimeError(f"Scraper returned empty/invalid result for {url}")

def find_best_search_group(job_title: str, db_groups: List[str]) -> str:
    """
    Match job_title against the 132 keywords using SentenceTransformer,
    then map the best matching keyword to one of the 36 database search groups.
    """
    logger.info("Matching job title '%s' with keywords...", job_title)
    
    # 1. Load keywords from keywords_daily.json
    keywords_path = PROJECT_ROOT / "Db" / "input" / "keywords_daily.json"
    if not keywords_path.exists():
        keywords_path = PROJECT_ROOT / "input" / "keywords_daily.json"
        
    with open(keywords_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    # Flatten keywords
    keywords = []
    for tier_key in ('tier_1', 'tier_2', 'tier_3'):
        tier_keywords = config.get(tier_key, [])
        if isinstance(tier_keywords, list):
            keywords.extend(tier_keywords)

    groups = config.get('groups', {})
    if isinstance(groups, dict):
        for group_cfg in groups.values():
            if not isinstance(group_cfg, dict):
                continue
            roles = group_cfg.get('roles', [])
            if isinstance(roles, list):
                keywords.extend(roles)
            clusters = group_cfg.get('clusters', {})
            if isinstance(clusters, dict):
                for cluster_roles in clusters.values():
                    if isinstance(cluster_roles, list):
                        keywords.extend(cluster_roles)

    # Deduplicate while keeping order
    seen = set()
    result_keywords = []
    for item in keywords:
        kw = str(item).strip()
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            result_keywords.append(kw)
            
    # Prepend group names prettified
    groups = config.get('groups', {})
    group_keywords = []
    if isinstance(groups, dict):
        for g in groups.keys():
            pretty = str(g).replace('_', ' ').strip().title()
            if pretty and pretty.lower() not in seen:
                seen.add(pretty.lower())
                group_keywords.append(pretty)
                
    all_132_keywords = group_keywords + result_keywords
    
    # 2. Use sentence-transformers to encode and calculate similarities
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError("sentence-transformers is required for vector embedding search_group matching.")
        
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    # Compute embeddings
    # Guard: ensure job_title is a plain string (LLM output may wrap values in dicts)
    if isinstance(job_title, dict):
        job_title = job_title.get("value") or job_title.get("name") or ""
    job_title_str = str(job_title).strip() if job_title else "unknown"
    kw_embeddings = model.encode(all_132_keywords, normalize_embeddings=True)
    title_emb = model.encode([job_title_str], normalize_embeddings=True)[0]
    
    # Cosine similarity (dot product of normalized vectors)
    sims = np.dot(kw_embeddings, title_emb)
    best_kw_idx = np.argmax(sims)
    best_keyword = all_132_keywords[best_kw_idx]
    logger.info("-> Best matching role keyword: '%s' (similarity: %.4f)", best_keyword, sims[best_kw_idx])
    
    # 3. Map best keyword to the 36 database search groups
    db_embeddings = model.encode(db_groups, normalize_embeddings=True)
    kw_emb = kw_embeddings[best_kw_idx]
    db_sims = np.dot(db_embeddings, kw_emb)
    best_db_idx = np.argmax(db_sims)
    best_db_group = db_groups[best_db_idx]
    logger.info("-> Mapped to DB search group: '%s' (similarity: %.4f)", best_db_group, db_sims[best_db_idx])
    
    return best_db_group

def save_cv_job_match_existing_job(
    conn,
    cv_id: int,
    job_id: int,
    search_group: str,
    match_percent: float,
    matched_skills: List[Dict[str, Any]],
    partially_matched_skills: List[Dict[str, Any]],
    missing_skills: List[Dict[str, Any]],
) -> None:
    """
    Save match results of CV with a specific job URL into cv_job_matches table.
    """
    cur = conn.cursor()
    try:
        radar_data = {
            "matched_skills": matched_skills,
            "partially_matched_skills": partially_matched_skills,
        }
        gap_report = {
            "missing_skills": missing_skills,
            "partially_matched_skills": partially_matched_skills,
        }
        cur.execute(
            "SELECT match_id FROM public.cv_job_matches WHERE cv_id = %s AND job_id = %s AND match_type = 'url_job'",
            (cv_id, job_id)
        )
        row = cur.fetchone()
        if row:
            match_id = row[0]
            logger.info("Updating existing cv_job_match (match_id: %d) for job_id: %d...", match_id, job_id)
            cur.execute(
                """
                UPDATE public.cv_job_matches
                SET match_score = %s, radar_data = %s, gap_report = %s, updated_at = CURRENT_TIMESTAMP
                WHERE match_id = %s
                """,
                (match_percent, json.dumps(radar_data), json.dumps(gap_report), match_id)
            )
        else:
            logger.info("Inserting new cv_job_match for cv_id: %d and job_id: %d...", cv_id, job_id)
            cur.execute(
                """
                INSERT INTO public.cv_job_matches (cv_id, match_type, search_group, job_id, match_score, radar_data, gap_report, model_version)
                VALUES (%s, 'url_job', %s, %s, %s, %s, %s, 'gemini-2.5-flash')
                """,
                (cv_id, search_group, job_id, match_percent, json.dumps(radar_data), json.dumps(gap_report))
            )
        conn.commit()
        logger.info("Saved cv_job_match successfully.")
    except Exception as e:
        conn.rollback()
        logger.error("Failed to save CV job match: %s", e)
    finally:
        cur.close()

def main():
    parser = argparse.ArgumentParser(description="Match CV skills with crawled JD URL requirements.")
    parser.add_argument("--cv", required=True, help="Path to student CV file (PDF/PNG/JPG/JPEG)")
    parser.add_argument("--url", required=True, help="Job posting URL to crawl and match against")
    parser.add_argument("--source-id", type=int, default=0, help="Source/Student ID associated with this CV")
    parser.add_argument("--threshold-possessed", type=float, default=0.75, help="Similarity threshold for possessed skills")
    parser.add_argument("--threshold-partial", type=float, default=0.3, help="Similarity threshold for partial match skills")
    parser.add_argument("--confidence-threshold", type=float, default=0.85, help="LLM skill extraction confidence threshold")
    
    args = parser.parse_args()
    
    if not get_db_connection:
        logger.error("Database connection setup is missing.")
        sys.exit(1)
        
    conn = get_db_connection()
    try:
        # ==========================================
        # STEP 1: Extract and Save Student CV
        # ==========================================
        logger.info("--- STEP 1: EXTRACT STUDENT CV ---")
        logger.info("Extracting text from CV: %s", args.cv)
        cv_text = extract_cv_text(args.cv)
        if not cv_text.strip():
            logger.error("No text could be extracted from CV.")
            sys.exit(1)
            
        logger.info("Extracting skills using Gemini...")
        raw_student_skills = extract_student_skills_gemini(cv_text, confidence_threshold=args.confidence_threshold)
        logger.info("Extracted %d skills from CV using Gemini.", len(raw_student_skills))
        
        logger.info("Normalizing CV skills...")
        normalized_student_skills_raw = normalize_student_skills(raw_student_skills)
        
        student_skills = []
        for item in normalized_student_skills_raw:
            sid = item.get("skill_id")
            if sid is not None and sid != -1:
                student_skills.append({
                    "original_skill": item.get("original"),
                    "skill_id": int(sid),
                    "skill_name": item.get("mapped_name"),
                    "similarity_score": float(item.get("confidence", 0.0))
                })
                
        logger.info("Successfully normalized and mapped %d student skills.", len(student_skills))
        
        # Save CV to database
        file_name = Path(args.cv).name
        cv_id = upsert_user_cv(conn, args.source_id, file_name, args.cv, cv_text)
        if cv_id is not None:
            save_user_cv_skills(conn, cv_id, student_skills)
            
        # Log unmatched CV skills
        unmatched_skills = [
            item for item in normalized_student_skills_raw
            if item.get("skill_id") is None or item.get("skill_id") == -1
        ]
        if unmatched_skills and cv_id is not None:
            logger.info("Logging %d unmatched CV skills to database (source_id: %d, source_type: cv)...", len(unmatched_skills), cv_id)
            insert_unmatched_skills(conn, cv_id, "cv", unmatched_skills)

        # ==========================================
        # STEP 2: Crawl Job JD from URL
        # ==========================================
        logger.info("\n--- STEP 2: CRAWL JOB JD FROM URL ---")
        raw_job = crawl_job_url(args.url)
        logger.info("Crawled job title: '%s' from %s", raw_job.get("title"), raw_job.get("source_name"))
        
        # Clean existing temp files in .tmp directory to avoid idempotency/deduplication skips
        tmp_dir = PROJECT_ROOT / ".tmp"
        tmp_dir.mkdir(exist_ok=True)
        for filename in ["raw_job_temp.json", "pending_llm_temp.json", "extracted_temp.json", "normalized_temp.json", "fallback_temp.json"]:
            file_path = tmp_dir / filename
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.warning("Could not delete old temp file %s: %s", filename, e)
        
        raw_temp = tmp_dir / "raw_job_temp.json"
        with open(raw_temp, "w", encoding="utf-8") as f:
            json.dump([raw_job], f, ensure_ascii=False, indent=2, default=json_serializable)
            
        # ==========================================
        # STEP 3: Clean, Extract, Normalize Job via Subprocesses
        # ==========================================
        logger.info("\n--- STEP 3: PROCESS AND NORMALIZE JOB JD ---")
        python_exe = sys.executable
        
        pending_temp = tmp_dir / "pending_llm_temp.json"
        clean_script = PROJECT_ROOT / "Db" / "pipeline" / "clean" / "2_clean_data" / "clean_process.py"
        logger.info("Running clean_process.py...")
        subprocess.run([
            python_exe, str(clean_script), str(raw_temp), "--step", "1", "--output", str(pending_temp)
        ], check=True)
        
        extracted_temp = tmp_dir / "extracted_temp.json"
        fallback_temp = tmp_dir / "fallback_temp.json"
        extract_script = PROJECT_ROOT / "Db" / "pipeline" / "extract" / "process_pending_llm.py"
        logger.info("Running process_pending_llm.py...")
        # Set PYTHONPATH so Db package imports work correctly
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(PROJECT_ROOT), str(PROJECT_ROOT.parent)]) + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
        subprocess.run([
            python_exe, str(extract_script), "--input-path", str(pending_temp), "--output-path", str(extracted_temp), "--fallback-path", str(fallback_temp)
        ], env=env, check=True)
        
        normalized_temp = tmp_dir / "normalized_temp.json"
        normalize_script = PROJECT_ROOT / "Db" / "pipeline" / "normalize" / "2_1_normalized_data" / "normalize_embeddings.py"
        logger.info("Running normalize_embeddings.py...")
        subprocess.run([
            python_exe, str(normalize_script), "--input", str(extracted_temp), "--output", str(normalized_temp)
        ], check=True)
        
        # ==========================================
        # STEP 4: Match Job Title to search_group via vector embedding
        # ==========================================
        logger.info("\n--- STEP 4: MAP JOB TITLE TO SEARCH GROUP ---")
        with open(normalized_temp, "r", encoding="utf-8") as f:
            normalized_jobs = json.load(f)
        if not normalized_jobs:
            raise RuntimeError("Normalization step returned empty output")
        job_rec = normalized_jobs[0]
        job_title = job_rec.get("title") or raw_job.get("title")
        # The LLM pipeline stores some fields as {"value": "...", "confidence": N} dicts.
        # Unwrap to a plain string before passing to sentence-transformers.
        if isinstance(job_title, dict):
            job_title = job_title.get("value") or job_title.get("name") or ""
        job_title = str(job_title).strip() if job_title else ""
        
        # Get unique search groups from database
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT search_group FROM public.job_group_skill_weights")
        db_groups = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        
        # Find best matching search_group
        matched_search_group = find_best_search_group(job_title, db_groups)
        
        # Inject matched search group into normalized job record so import.py handles it
        if "job" not in job_rec:
            job_rec["job"] = {}
        job_rec["job"]["search_group"] = matched_search_group
        job_rec["search_group"] = matched_search_group
        
        # Rewrite normalized job record
        with open(normalized_temp, "w", encoding="utf-8") as f:
            json.dump([job_rec], f, ensure_ascii=False, indent=2, default=json_serializable)
            
        # ==========================================
        # STEP 5: Import Job into DB
        # ==========================================
        logger.info("\n--- STEP 5: IMPORT JOB TO DATABASE ---")
        import_script = PROJECT_ROOT / "Db" / "pipeline" / "import" / "3_import" / "import.py"
        subprocess.run([
            python_exe, str(import_script), "--input", str(normalized_temp)
        ], check=True)
        
        # Query generated/updated job_id from DB
        cur = conn.cursor()
        cur.execute("SELECT job_id FROM public.jobs WHERE job_posting_url = %s", (args.url,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Failed to find imported job in database for URL: {args.url}")
        job_id = row[0]
        logger.info("Imported/Updated job successfully. Job ID: %d", job_id)
        cur.close()

        # ==========================================
        # STEP 6: Match CV Skills with Job Skills (weights from search_group)
        # ==========================================
        logger.info("\n--- STEP 6: MATCH CV SKILLS WITH JD SKILLS ---")
        
        # 1. Fetch weights from search group
        logger.info("Fetching skill weights for search group '%s'...", matched_search_group)
        group_weights = fetch_job_group_weights(conn, matched_search_group)
        weight_map = {w["skill_id"]: w["weight"] for w in group_weights}
        
        # 2. Extract job skills
        job_skills = []
        for s in job_rec.get("normalized_skills", []):
            sid = s.get("skill_id")
            sname = s.get("mapped_name")
            if sid is not None:
                # Look up weight in search group, default to low weight (0.1) if not core
                weight = weight_map.get(sid, 0.1)
                job_skills.append({
                    "skill_id": int(sid),
                    "skill_name": sname,
                    "weight": weight
                })
                
        if not job_skills:
            logger.warning("No normalized skills found for this job description. Using search group default skills.")
            job_skills = group_weights
            
        logger.info("Target job skills: %d", len(job_skills))
        
        # 3. Match calculation
        skill_emb, skill_id_to_idx, _ = load_skill_embedding_cache()
        matched_skills = []
        partially_matched_skills = []
        missing_skills = []
        
        total_weight = sum(item["weight"] for item in job_skills)
        weighted_sim_sum = 0.0
        
        for target in job_skills:
            target_sid = target["skill_id"]
            target_name = target["skill_name"]
            weight = target["weight"]

            max_sim = 0.0
            best_match_name = None
            best_match_sid = None

            for student in student_skills:
                sim = get_skill_similarity(target_sid, student["skill_id"], skill_emb, skill_id_to_idx)
                if sim > max_sim:
                    max_sim = sim
                    best_match_name = student["skill_name"]
                    best_match_sid = student["skill_id"]

            contribution = weight * max_sim
            gap = weight * (1.0 - max_sim)
            weighted_sim_sum += contribution

            skill_detail = {
                "skill_id": target_sid,
                "skill_name": target_name,
                "weight": round(weight, 6),
                "similarity": round(max_sim, 4),
            }

            if max_sim >= args.threshold_possessed:
                skill_detail["contribution"] = round(contribution, 6)
                if best_match_name and best_match_sid != target_sid:
                    skill_detail["matched_via"] = best_match_name
                matched_skills.append(skill_detail)
            elif max_sim >= args.threshold_partial:
                skill_detail["contribution"] = round(contribution, 6)
                skill_detail["gap"] = round(gap, 6)
                if best_match_name and best_match_sid != target_sid:
                    skill_detail["matched_via"] = best_match_name
                partially_matched_skills.append(skill_detail)
            else:
                skill_detail["gap"] = round(gap, 6)
                missing_skills.append(skill_detail)

        match_score = (weighted_sim_sum / total_weight) if total_weight > 0 else 0.0
        match_percent = round(match_score * 100.0, 2)
        
        # Save to cv_job_matches table
        if cv_id is not None:
            save_cv_job_match_existing_job(
                conn,
                cv_id,
                job_id,
                matched_search_group,
                match_percent,
                matched_skills,
                partially_matched_skills,
                missing_skills
            )
            
        output_data = {
            "cv_id": cv_id,
            "job_id": job_id,
            "job_title": job_title,
            "search_group": matched_search_group,
            "match_score": round(match_score, 6),
            "match_percent": match_percent,
            "student_skills": student_skills,
            "matched_skills": matched_skills,
            "partially_matched_skills": partially_matched_skills,
            "missing_skills": missing_skills,
        }
        
        # Print output JSON to stdout
        print("\n=== MATCHING RESULT ===")
        print(json.dumps(output_data, ensure_ascii=False, indent=2, default=json_serializable))
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()
