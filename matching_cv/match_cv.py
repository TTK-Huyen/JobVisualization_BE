#!/usr/bin/env python3
"""
CV Matching Engine using Gemini, Lightcast Normalizer, and PostgreSQL TF-IDF Weights.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("match_cv")

# Resolve project root dynamically
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None
for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break

if not PROJECT_ROOT:
    # Fallback to parent folder structure
    PROJECT_ROOT = THIS_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load DB environment
from matching_cv.utils import extract_cv_text, load_db_env
load_db_env()

# Load DB connection dynamically
import importlib.util
def load_db_connection_func():
    module_dir = PROJECT_ROOT / "Db" / "pipeline" / "import" / "3_import"
    module_path = module_dir / "import.py"
    if not module_path.exists():
        raise FileNotFoundError(f"Database import module not found at: {module_path}")
    
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
        
    spec = importlib.util.spec_from_file_location("db_import_module", str(module_path))
    db_import = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_import)
    return db_import.get_db_connection

try:
    get_db_connection = load_db_connection_func()
except Exception as e:
    logger.error("Failed to load database connection utility: %s", e)
    get_db_connection = None

from matching_cv.normalizer import normalize_student_skills, load_skill_embedding_cache
from Db.llm.debug_llm_adapter import call_llm as db_call_llm
from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
from Db.input.config_api import get_api_key_info, on_api_quota_error


def load_cv_skill_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "extract_cv_skills.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def clean_text_normalization(text: str) -> str:
    return " ".join(
        str(text)
        .lower()
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
        .replace("...", " ")
        .split()
    )


def extract_student_skills_gemini(cv_text: str, confidence_threshold: float = 0.85, max_attempts: int = 5) -> List[Dict[str, Any]]:
    """
    Extract skills from CV text using Gemini.
    Applies anti-hallucination validation (checking exact presence in CV text).
    """
    if not db_call_llm:
        raise RuntimeError("LLM adapter is not available.")

    prompt_template = load_cv_skill_prompt()
    prompt = prompt_template.replace("{{cv_text}}", cv_text[:8000])

    cv_norm = clean_text_normalization(cv_text)
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        key, key_label = get_api_key_info("gemini")
        if not key:
            raise RuntimeError("No active Gemini API keys available. All keys may be in cooldown.")

        try:
            logger.info("Calling Gemini (attempt %d/%d) using key %s", attempt, max_attempts, key_label)
            raw = db_call_llm(
                prompt=prompt,
                api_key=key,
                timeout_seconds=int(os.getenv("MATCH_CV_LLM_TIMEOUT_SECONDS", str(LLM_CALL_TIMEOUT_SECONDS))),
            )
            raw = raw.strip()

            # Find JSON array using regex
            m = re.search(r"\[.*\]", raw, re.S)
            if m:
                raw = m.group(0)

            data = json.loads(raw)
            extracted_skills = []

            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue

                    skill = item.get("skill") or item.get("name")
                    evidence = item.get("evidence") or item.get("sample") or ""
                    try:
                        confidence = float(item.get("confidence") or 0.0)
                    except Exception:
                        confidence = 0.0

                    if not skill or confidence < confidence_threshold:
                        continue

                    skill_norm = clean_text_normalization(skill)
                    evidence_norm = clean_text_normalization(evidence)

                    # Anti-hallucination check: ensure evidence or skill is in the original text
                    if not evidence_norm or (evidence_norm not in cv_norm and skill_norm not in cv_norm):
                        logger.info("Dropping skill without verifiable evidence in CV: %s (evidence: %s)", skill, evidence)
                        continue

                    extracted_skills.append({
                        "skill": skill,
                        "evidence": evidence,
                        "confidence": confidence
                    })

            if extracted_skills:
                return extracted_skills
            else:
                logger.warning("Gemini returned empty skill list. Retrying...")

        except Exception as e:
            last_exc = e
            logger.warning("Attempt %d/%d failed: %s", attempt, max_attempts, e)
            msg = str(e).lower()
            if any(term in msg for term in ("quota", "429", "rate", "resource_exhausted")):
                on_api_quota_error("gemini")
                continue
            
            if attempt < max_attempts:
                import time
                time.sleep(2)

    raise RuntimeError(f"Failed to extract skills via Gemini: {last_exc}")


def extract_student_skills_keyword_fallback(cv_text: str, conn) -> List[Dict[str, Any]]:
    """
    Extract skills using rule-based exact keyword matching from PostgreSQL skills database.
    Used as fallback when Gemini API hits quota limit or throws error.
    """
    logger.warning("Gemini API quota exhausted or error occurred. Switching to database-driven keyword matching fallback...")
    cur = conn.cursor()
    try:
        # Load all skills from the system taxonomy
        cur.execute("SELECT skill_name FROM public.skills")
        rows = cur.fetchall()
        db_skills = [str(row[0]) for row in rows if row[0]]
    except Exception as e:
        logger.error("Failed to load skills taxonomy for fallback matching: %s", e)
        return []
    finally:
        cur.close()

    cv_text_lower = f" {cv_text.lower()} "
    extracted_set = set()
    extracted_skills = []

    for skill_name in db_skills:
        # Remove parenthesized parts, e.g. "Docker (Software)" -> "Docker"
        cleaned_name = re.sub(r"\([^)]*\)", "", skill_name)
        cleaned_name = re.sub(r"\s+", " ", cleaned_name).strip()
        if not cleaned_name:
            continue
            
        cleaned_lower = cleaned_name.lower()
        if cleaned_lower in extracted_set:
            continue

        matched = False
        # Word boundary matching for short skill keywords (e.g. C, R, Git, Go)
        if len(cleaned_lower) <= 3:
            pattern = rf"\b{re.escape(cleaned_lower)}\b"
            if re.search(pattern, cv_text_lower):
                matched = True
        else:
            if cleaned_lower in cv_text_lower:
                matched = True

        if matched:
            extracted_set.add(cleaned_lower)
            extracted_skills.append({
                "skill": cleaned_name,
                "evidence": f"Found mention of '{cleaned_name}' in CV text (Keyword Fallback)",
                "confidence": 0.85
            })

    logger.info("Fallback keyword extraction completed. Found %d skills.", len(extracted_skills))
    return extracted_skills


def fetch_job_group_weights(conn, search_group: str) -> List[Dict[str, Any]]:
    """
    Fetch the list of standard skills and their weights for a given search group.
    """
    cur = conn.cursor()
    try:
        sql = """
            SELECT w.skill_id, s.skill_name, w.weight_wi
            FROM public.job_group_skill_weights w
            INNER JOIN public.skills s ON w.skill_id = s.skill_id
            WHERE LOWER(w.search_group) = LOWER(%s)
            ORDER BY w.weight_wi DESC
        """
        cur.execute(sql, (search_group,))
        rows = cur.fetchall()
        return [
            {"skill_id": int(row[0]), "skill_name": row[1], "weight": float(row[2])}
            for row in rows
        ]
    finally:
        cur.close()


def get_skill_similarity(sid_a: int, sid_b: int, skill_emb: np.ndarray, skill_id_to_idx: Dict[int, int]) -> float:
    """
    Retrieve cosine similarity between two skill IDs from the precomputed embeddings cache.
    Since embeddings are normalized, similarity is the dot product.
    """
    if sid_a == sid_b:
        return 1.0
    if sid_a not in skill_id_to_idx or sid_b not in skill_id_to_idx:
        return 0.0
    idx_a = skill_id_to_idx[sid_a]
    idx_b = skill_id_to_idx[sid_b]
    vec_a = skill_emb[idx_a]
    vec_b = skill_emb[idx_b]
    return max(0.0, float(np.dot(vec_a, vec_b)))

def insert_unmatched_skills(conn, source_id: int, source_type: str, unmatched_skills: List[Dict[str, Any]]) -> None:
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    try:
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
            
            # Max similarity score
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
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Failed to insert unmatched CV skills: %s", e)
    finally:
        cur.close()


def upsert_user_cv(conn, user_id: str, file_name: str, file_url: str, extracted_text: str, cv_id: str) -> Optional[str]:
    """
    Upsert user CV details into the user_cvs table.
    """
    cur = conn.cursor()
    try:
        # Avoid foreign key violation: check if user_id exists in users table
        cur.execute("SELECT 1 FROM public.users WHERE user_id = %s", (user_id,))
        if not cur.fetchone():
            logger.warning("User ID %s does not exist in public.users table. Skipping user_cvs database update.", user_id)
            return None
        
        # Check if CV already exists with this cv_id
        cur.execute(
            "SELECT cv_id FROM public.user_cvs WHERE cv_id = %s",
            (cv_id,)
        )
        row = cur.fetchone()
        if row:
            logger.info("Found existing CV (cv_id: %s) for user_id: %s, updating...", cv_id, user_id)
            # KHÔNG cập nhật file_url ở đây: bản ghi CV do backend (NestJS) tạo
            # khi upload, file_url là URL Cloudinary thật. Service thuật toán chỉ
            # nhận đường dẫn file tạm (.tmp_cv_uploads/...), nếu ghi đè sẽ làm
            # hỏng URL khiến nút "Xem CV" 404. Chỉ cập nhật các trường phân tích.
            cur.execute(
                """
                UPDATE public.user_cvs
                SET user_id = %s, file_name = %s, extracted_text = %s, updated_at = CURRENT_TIMESTAMP
                WHERE cv_id = %s
                """,
                (user_id, file_name, extracted_text, cv_id)
            )
        else:
            logger.info("Inserting new CV into public.user_cvs with cv_id: %s...", cv_id)
            cur.execute(
                """
                INSERT INTO public.user_cvs (cv_id, user_id, file_name, file_url, extracted_text)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING cv_id
                """,
                (cv_id, user_id, file_name, file_url, extracted_text)
            )
            cv_id = cur.fetchone()[0]
        conn.commit()
        return cv_id
    except Exception as e:
        conn.rollback()
        logger.error("Failed to upsert user CV: %s", e)
        return None
    finally:
        cur.close()


def save_user_cv_skills(conn, cv_id: int, student_skills: List[Dict[str, Any]]) -> None:
    """
    Save mapped CV skills to user_cv_skills table.
    """
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM public.user_cv_skills WHERE cv_id = %s", (cv_id,))
        
        # Deduplicate rows by skill_id to prevent unique constraint violation
        unique_skill_ids = set()
        rows = []
        for s in student_skills:
            sid = s.get("skill_id")
            raw_skill = s.get("original_skill") or ""
            if sid is not None and sid not in unique_skill_ids:
                unique_skill_ids.add(sid)
                rows.append((cv_id, sid, str(raw_skill)[:255]))
                
        if rows:
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                "INSERT INTO public.user_cv_skills (cv_id, skill_id, raw_skill) VALUES %s ON CONFLICT DO NOTHING",
                rows
            )
        conn.commit()
        logger.info("Saved %d skills to user_cv_skills for cv_id: %s.", len(rows), cv_id)
    except Exception as e:
        conn.rollback()
        logger.error("Failed to save user CV skills: %s", e)
    finally:
        cur.close()


def save_cv_job_match(
    conn,
    cv_id: str,
    search_group: str,
    match_percent: float,
    matched_skills: List[Dict[str, Any]],
    partially_matched_skills: List[Dict[str, Any]],
    missing_skills: List[Dict[str, Any]],
    student_skills: List[Dict[str, Any]] = None,
) -> None:
    """
    Save CV job match results to cv_job_matches table.
    """
    cur = conn.cursor()
    try:
        radar_data = {
            "matched_skills": matched_skills,
            "partially_matched_skills": partially_matched_skills,
        }
        if student_skills is not None:
            radar_data["student_skills"] = student_skills
        gap_report = {
            "missing_skills": missing_skills,
            "partially_matched_skills": partially_matched_skills,
        }
        cur.execute(
            "SELECT match_id FROM public.cv_job_matches WHERE cv_id = %s AND LOWER(search_group) = LOWER(%s) AND match_type = 'search_group'",
            (cv_id, search_group)
        )
        row = cur.fetchone()
        if row:
            match_id = row[0]
            logger.info("Updating existing cv_job_match (match_id: %s) for cv_id: %s...", match_id, cv_id)
            cur.execute(
                """
                UPDATE public.cv_job_matches
                SET match_score = %s, radar_data = %s, gap_report = %s, updated_at = CURRENT_TIMESTAMP
                WHERE match_id = %s
                """,
                (match_percent, json.dumps(radar_data), json.dumps(gap_report), match_id)
            )
        else:
            logger.info("Inserting new cv_job_match for cv_id: %s...", cv_id)
            cur.execute(
                """
                INSERT INTO public.cv_job_matches (cv_id, match_type, search_group, match_score, radar_data, gap_report, model_version)
                VALUES (%s, 'search_group', %s, %s, %s, %s, 'gemini-2.5-flash')
                """,
                (cv_id, search_group, match_percent, json.dumps(radar_data), json.dumps(gap_report))
            )
        conn.commit()
        logger.info("Saved cv_job_match successfully.")
    except Exception as e:
        conn.rollback()
        logger.error("Failed to save CV job match: %s", e)
    finally:
        cur.close()


def compute_skill_match(
    target_skills: List[Dict[str, Any]],
    student_skills: List[Dict[str, Any]],
    skill_emb: np.ndarray,
    skill_id_to_idx: Dict[int, int],
    threshold_possessed: float,
    threshold_partial: float,
) -> Dict[str, Any]:
    """
    Tính điểm khớp có trọng số giữa một tập kỹ năng MỤC TIÊU (của nhóm hoặc của
    1 job) với kỹ năng trong CV. Dùng chung cho cả match theo nhóm lẫn chấm từng
    job (cùng công thức cosine có trọng số) để kết quả nhất quán.
    """
    matched_skills: List[Dict[str, Any]] = []
    partially_matched_skills: List[Dict[str, Any]] = []
    missing_skills: List[Dict[str, Any]] = []

    # Load skill type/category metadata for semantic filtering
    skill_metadata = {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT skill_id, category, type, is_software, is_language, category_name FROM public.skills")
        for row in cur.fetchall():
            skill_metadata[int(row[0])] = {
                "category": row[1] or "",
                "type": row[2] or "",
                "is_software": bool(row[3]),
                "is_language": bool(row[4]),
                "category_name": row[5] or ""
            }
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Could not load skill metadata for semantic filtering: %s", e)

    total_weight = sum(item["weight"] for item in target_skills)
    weighted_sim_sum = 0.0

    for target in target_skills:
        target_sid = target["skill_id"]
        target_name = target["skill_name"]
        weight = target["weight"]

        max_sim = 0.0
        best_match_name = None
        best_match_sid = None
        for student in student_skills:
            sim = get_skill_similarity(
                target_sid, student["skill_id"], skill_emb, skill_id_to_idx
            )

            # Apply semantic filtering rules
            t_meta = skill_metadata.get(target_sid)
            s_meta = skill_metadata.get(student["skill_id"])
            if t_meta and s_meta:
                t_type = t_meta.get("type", "")
                s_type = s_meta.get("type", "")
                t_is_sw = t_meta.get("is_software", False)
                s_is_sw = s_meta.get("is_software", False)
                t_is_lang = t_meta.get("is_language", False)
                s_is_lang = s_meta.get("is_language", False)

                # Rule 3: Symmetric Type Grouping (Specialized vs Specialized, Common vs Common)
                # - Certifications are temporarily ignored (forced to 0.0)
                if t_type == "Certification" or s_type == "Certification":
                    sim = 0.0
                elif t_type != s_type:
                    sim = 0.0

                # Rule 2: Software/Tool Exclusivity
                # - Software/Tool cannot match Common skill (soft skills / process)
                if t_is_sw and s_type == "Common skill":
                    sim = 0.0
                elif t_type == "Common skill" and s_is_sw:
                    sim = 0.0

                # Rule 1: Language Filtering
                # - If either is a language skill, they must both be language skills of the same language root
                if t_is_lang or s_is_lang:
                    if not (t_is_lang and s_is_lang):
                        sim = 0.0
                    else:
                        # Extract language root names (e.g. english, german)
                        def get_language_root(name: str) -> str:
                            name_lower = name.lower()
                            for lang in ["english", "vietnamese", "german", "japanese", "french", "chinese", "korean", "spanish", "russian", "italian"]:
                                if lang in name_lower:
                                    return lang
                            return ""
                        
                        t_lang = get_language_root(target_name)
                        s_lang = get_language_root(student["skill_name"])
                        if t_lang and s_lang and t_lang != s_lang:
                            sim = 0.0

                # Rule 5: Subcategory Exclusivity
                # - If both have non-empty subcategory names (category field) and they are different, force similarity to 0.0
                t_subcat = t_meta.get("category", "")
                s_subcat = s_meta.get("category", "")
                if t_subcat and s_subcat and t_subcat != s_subcat:
                    sim = 0.0

                # Rule 6: Subcategory Boost
                # - If both have non-empty subcategory names and they are in the exact same subcategory, apply a boost of 1.2 (up to 1.0)
                if t_subcat and s_subcat and t_subcat == s_subcat:
                    sim = min(1.0, sim * 1.2)

                # Rule 8: Soft Skills Direct Match
                # - If both are Common skills (soft skills) and they have a base similarity > 0.35, they are treated as a full match (1.0)
                if t_type == "Common skill" and s_type == "Common skill" and sim > 0.35:
                    sim = 1.0

            if sim > max_sim:
                max_sim = sim
                best_match_name = student["skill_name"]
                best_match_sid = student["skill_id"]

        contribution = weight * max_sim
        gap = weight * (1.0 - max_sim)
        weighted_sim_sum += contribution

        # Đóng góp tuyệt đối của kỹ năng yêu cầu này vào tổng điểm chung (%)
        abs_contrib_pct = (contribution / total_weight * 100.0) if total_weight > 0 else 0.0
        max_contrib_pct = (weight / total_weight * 100.0) if total_weight > 0 else 0.0

        skill_detail = {
            "skill_id": target_sid,
            "skill_name": target_name,
            "weight": round(weight, 6),
            "similarity": round(max_sim, 4),
            "absolute_contribution_percent": round(abs_contrib_pct, 2),
            "max_contribution_percent": round(max_contrib_pct, 2)
        }
        if max_sim >= threshold_possessed:
            skill_detail["contribution"] = round(contribution, 6)
            if best_match_name and best_match_sid != target_sid:
                skill_detail["matched_via"] = best_match_name
            matched_skills.append(skill_detail)
        elif max_sim >= threshold_partial:
            skill_detail["contribution"] = round(contribution, 6)
            skill_detail["gap"] = round(gap, 6)
            if best_match_name and best_match_sid != target_sid:
                skill_detail["matched_via"] = best_match_name
            partially_matched_skills.append(skill_detail)
        else:
            skill_detail["gap"] = round(gap, 6)
            skill_detail["absolute_contribution_percent"] = 0.0
            missing_skills.append(skill_detail)

    match_score = (weighted_sim_sum / total_weight) if total_weight > 0 else 0.0
    match_percent = round(match_score * 100.0, 2)

    # Sắp xếp các danh sách kỹ năng kết quả theo trọng số (weight) giảm dần
    matched_skills.sort(key=lambda x: x["weight"], reverse=True)
    partially_matched_skills.sort(key=lambda x: x["weight"], reverse=True)
    missing_skills.sort(key=lambda x: x["weight"], reverse=True)

    return {
        "match_score": match_score,
        "match_percent": match_percent,
        "matched_skills": matched_skills,
        "partially_matched_skills": partially_matched_skills,
        "missing_skills": missing_skills,
        "student_skills": student_skills,
    }


def score_jobs_in_group(
    conn,
    cv_id: str,
    search_group: str,
    student_skills: List[Dict[str, Any]],
    group_weights: List[Dict[str, Any]],
    skill_emb: np.ndarray,
    skill_id_to_idx: Dict[int, int],
    threshold_possessed: float,
    threshold_partial: float,
    days: int = 7,
) -> int:
    """
    Chấm CV với TỪNG job đang mở trong `search_group` (listed_time trong `days`
    ngày), mỗi job lưu 1 record cv_job_matches (match_type='existing_job', có
    job_id). Tái dùng trọng số nhóm cho kỹ năng trùng (giống match theo URL).
    Trả về số job đã chấm. Lỗi không làm hỏng luồng match nhóm chính.
    """
    if not student_skills:
        logger.info("No student skills available -> skip per-job scoring.")
        return 0

    weight_map = {w["skill_id"]: w["weight"] for w in group_weights}

    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT j.job_id, js.skill_id, s.skill_name
            FROM public.jobs j
            JOIN public.job_skills js ON js.job_id = j.job_id
            JOIN public.skills s ON s.skill_id = js.skill_id
            WHERE (LOWER(j.search_group) = LOWER(%s) OR LOWER(j.job_category) = LOWER(%s))
              AND (j.expiry_time IS NULL OR j.expiry_time > now())
              AND j.listed_time >= (now() - make_interval(days => %s))
            """,
            (search_group, search_group, days),
        )
        rows = cur.fetchall()
    finally:
        cur.close()

    if not rows:
        logger.info(
            "No open jobs (within %d days) with skills in group '%s' -> nothing to score.",
            days, search_group,
        )
        return 0

    # Gom kỹ năng theo từng job
    job_skill_map: Dict[int, List[Dict[str, Any]]] = {}
    for job_id, skill_id, skill_name in rows:
        job_skill_map.setdefault(int(job_id), []).append(
            {"skill_id": int(skill_id), "skill_name": skill_name}
        )

    records = []
    for job_id, jskills in job_skill_map.items():
        # Trọng số per-job = mượn trọng số nhóm cho kỹ năng trùng; nếu job không
        # có kỹ năng nào nằm trong danh sách trọng số nhóm -> fallback cả nhóm.
        target_skills = [
            {
                "skill_id": s["skill_id"],
                "skill_name": s["skill_name"],
                "weight": weight_map[s["skill_id"]],
            }
            for s in jskills
            if s["skill_id"] in weight_map
        ]
        if not target_skills:
            target_skills = group_weights

        result = compute_skill_match(
            target_skills, student_skills, skill_emb, skill_id_to_idx,
            threshold_possessed, threshold_partial,
        )
        radar_data = {
            "matched_skills": result["matched_skills"],
            "partially_matched_skills": result["partially_matched_skills"],
            "student_skills": result.get("student_skills"),
        }
        gap_report = {
            "missing_skills": result["missing_skills"],
            "partially_matched_skills": result["partially_matched_skills"],
        }
        records.append((
            cv_id, "existing_job", search_group, job_id,
            result["match_percent"],
            json.dumps(radar_data), json.dumps(gap_report),
            "gemini-2.5-flash",
        ))

    cur = conn.cursor()
    try:
        from psycopg2.extras import execute_values
        # Xoá per-job cũ của (cv, nhóm) rồi chèn lại. Cách này KHÔNG cần unique
        # index (cv_id, job_id) -> không phải migrate DB (DB hiện không quản lý
        # bằng Prisma migrate). Cả 2 lệnh nằm trong 1 transaction (commit cuối).
        cur.execute(
            """
            DELETE FROM public.cv_job_matches
            WHERE cv_id = %s
              AND match_type = 'existing_job'
              AND LOWER(search_group) = LOWER(%s)
            """,
            (cv_id, search_group),
        )
        execute_values(
            cur,
            """
            INSERT INTO public.cv_job_matches
                (cv_id, match_type, search_group, job_id, match_score,
                 radar_data, gap_report, model_version)
            VALUES %s
            """,
            records,
        )
        conn.commit()
        logger.info(
            "Per-job scoring: upserted %d job matches for cv_id %s in group '%s'.",
            len(records), cv_id, search_group,
        )
        return len(records)
    except Exception as e:
        conn.rollback()
        logger.error("Failed to bulk upsert per-job matches: %s", e)
        return 0
    finally:
        cur.close()


def main():
    parser = argparse.ArgumentParser(description="Match CV skills with Job Title requirements.")
    parser.add_argument("--cv", required=True, help="Path to student CV file (PDF/PNG/JPG/JPEG)")
    parser.add_argument("--search-group", required=True, help="Search group/job title to match against")
    parser.add_argument("--model-name", default="all-MiniLM-L6-v2", help="SentenceTransformer model name to use")
    parser.add_argument("--threshold-possessed", type=float, default=0.75, help="Similarity threshold for possessed skills")
    parser.add_argument("--threshold-partial", type=float, default=0.45, help="Similarity threshold for partial match skills")
    parser.add_argument("--confidence-threshold", type=float, default=0.85, help="LLM skill extraction confidence threshold")
    parser.add_argument("--source-id", type=str, required=True, help="Source/Student UUID associated with this CV")
    parser.add_argument("--cv-id", type=str, required=True, help="UUID for the CV from the web application")
    parser.add_argument("--output", help="Path to save matching result JSON. Default: next to CV file with suffix '_matching_result.json'")
    parser.add_argument("--score-jobs", action="store_true", help="Also score the CV against each open job in the group (per-job matches)")
    parser.add_argument("--score-days", type=int, default=7, help="When --score-jobs: only score jobs listed within the last N days")

    args = parser.parse_args()

    if not get_db_connection:
        logger.error("Database connection setup is missing.")
        sys.exit(1)

    # Establish database connection
    conn = get_db_connection()
    try:
        # Load job group weights
        logger.info("Fetching weights from database for search group: %s", args.search_group)
        job_skills = fetch_job_group_weights(conn, args.search_group)
        if not job_skills:
            logger.error("No skills found for search group '%s' in the database.", args.search_group)
            sys.exit(1)
        logger.info("Loaded %d target skills for '%s' from DB.", len(job_skills), args.search_group)

        # Extract CV text
        logger.info("Extracting text from CV: %s", args.cv)
        cv_text = extract_cv_text(args.cv)
        if not cv_text.strip():
            logger.error("No text could be extracted from CV.")
            sys.exit(1)

        # Check if CV already exists in database with identical text content
        file_name = Path(args.cv).name
        cur = conn.cursor()
        cur.execute(
            """
            SELECT cv_id, extracted_text 
            FROM public.user_cvs 
            WHERE cv_id = %s
            LIMIT 1
            """,
            (args.cv_id,)
        )
        existing_cv = cur.fetchone()
        
        cv_id = None
        student_skills = []
        cv_cache_hit = False

        if existing_cv:
            db_cv_id, db_extracted_text = existing_cv
            
            # Normalize whitespace for comparison
            clean_local_text = " ".join((cv_text or "").split())
            clean_db_text = " ".join((db_extracted_text or "").split())
            
            if clean_local_text == clean_db_text:
                logger.info("Found existing CV in database (cv_id: %s) with matching content. Fetching skills from database...", db_cv_id)
                cur.execute(
                    """
                    SELECT ucs.skill_id, s.skill_name, ucs.raw_skill
                    FROM public.user_cv_skills ucs
                    INNER JOIN public.skills s ON ucs.skill_id = s.skill_id
                    WHERE ucs.cv_id = %s
                    """,
                    (db_cv_id,)
                )
                skills_rows = cur.fetchall()
                if skills_rows:
                    cv_id = db_cv_id
                    for r in skills_rows:
                        student_skills.append({
                            "original_skill": r[2],
                            "skill_id": int(r[0]),
                            "skill_name": r[1],
                            "similarity_score": 1.0
                        })
                    logger.info("Loaded %d skills from database cache. Bypassing Gemini skill extraction and normalization.", len(student_skills))
                    cv_cache_hit = True
                else:
                    logger.info("Existing CV in database has no skills recorded. Proceeding with extraction.")
            else:
                logger.info("Existing CV found in database but content has changed. Proceeding with re-extraction.")
        cur.close()

        if not cv_cache_hit:
            # Extract skills using Gemini
            logger.info("Extracting skills using Gemini...")
            try:
                raw_skills = extract_student_skills_gemini(cv_text, confidence_threshold=args.confidence_threshold)
                logger.info("Extracted %d skills from CV using Gemini.", len(raw_skills))
                logger.info("RAW EXTRACTED SKILLS: %s", [s.get("skill") for s in raw_skills])
            except RuntimeError as e:
                logger.warning("Gemini extraction failed: %s. Initiating keyword matching fallback...", e)
                raw_skills = extract_student_skills_keyword_fallback(cv_text, conn)

            # Normalize skills using Lightcast
            logger.info("Normalizing CV skills with Lightcast and mini-v6 embeddings...")
            normalized_student_skills_raw = normalize_student_skills(raw_skills)
            
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

            logger.info("Successfully normalized and mapped %d skills to DB skill IDs.", len(student_skills))

            # --- DB UPDATE FOR USER CV ---
            # Insert or update user CV information
            cv_id = upsert_user_cv(conn, args.source_id, file_name, args.cv, cv_text, args.cv_id)
            if cv_id is not None:
                # Save the mapped CV skills
                save_user_cv_skills(conn, cv_id, student_skills)

        # Log unmatched CV skills (Disabled per user decision: do not store unmatched CV skills in database)
        # unmatched_skills = [
        #     item for item in normalized_student_skills_raw
        #     if item.get("skill_id") is None or item.get("skill_id") == -1
        # ]
        # if unmatched_skills:
        #     log_source_id = cv_id if (cv_id is not None) else args.source_id
        #     logger.info("Logging %d unmatched CV skills to database (source_id: %s, source_type: cv)...", len(unmatched_skills), log_source_id)
        #     insert_unmatched_skills(conn, log_source_id, "cv", unmatched_skills)

        # Load skills embeddings cache
        if args.model_name == "all-MiniLM-L6-v2":
            logger.info("Loading default skill embeddings cache...")
            skill_emb, skill_id_to_idx, _ = load_skill_embedding_cache()
        else:
            logger.info("Generating dynamic embeddings using model: %s", args.model_name)
            # Collect unique skill IDs and names
            unique_skills = {}
            for s in student_skills:
                if s["skill_id"] not in unique_skills:
                    unique_skills[s["skill_id"]] = s["skill_name"]
            for s in job_skills:
                if s["skill_id"] not in unique_skills:
                    unique_skills[s["skill_id"]] = s["skill_name"]
                    
            if args.score_jobs:
                logger.info("Fetching additional open job skill names for dynamic encoding...")
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        SELECT DISTINCT js.skill_id, s.skill_name
                        FROM public.jobs j
                        JOIN public.job_skills js ON js.job_id = j.job_id
                        JOIN public.skills s ON s.skill_id = js.skill_id
                        WHERE (LOWER(j.search_group) = LOWER(%s) OR LOWER(j.job_category) = LOWER(%s))
                          AND (j.expiry_time IS NULL OR j.expiry_time > now())
                          AND j.listed_time >= (now() - make_interval(days => %s))
                        """,
                        (args.search_group, args.search_group, args.score_days)
                    )
                    for row in cur.fetchall():
                        sid = int(row[0])
                        if sid not in unique_skills:
                            unique_skills[sid] = row[1]
                finally:
                    cur.close()
            
            # Load the model dynamically
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(args.model_name)
            skill_ids = list(unique_skills.keys())
            skill_names = [unique_skills[sid] for sid in skill_ids]
            
            # Encode
            logger.info("Encoding %d unique skills with %s...", len(skill_names), args.model_name)
            embs = model.encode(skill_names, normalize_embeddings=True)
            
            skill_emb = np.asarray(embs, dtype=float)
            skill_id_to_idx = {sid: idx for idx, sid in enumerate(skill_ids)}

        # Matching calculation (theo NHÓM): dùng chung compute_skill_match
        group_result = compute_skill_match(
            job_skills, student_skills, skill_emb, skill_id_to_idx,
            args.threshold_possessed, args.threshold_partial,
        )
        matched_skills = group_result["matched_skills"]
        partially_matched_skills = group_result["partially_matched_skills"]
        missing_skills = group_result["missing_skills"]
        match_score = group_result["match_score"]
        match_percent = group_result["match_percent"]

        # --- DB UPDATE FOR JOB MATCH RESULT ---
        if cv_id is not None:
            save_cv_job_match(
                conn,
                cv_id,
                args.search_group,
                match_percent,
                matched_skills,
                partially_matched_skills,
                missing_skills,
                group_result["student_skills"],
            )

            # Chấm TỪNG job trong nhóm (chỉ khi được yêu cầu — luồng CV/nhóm
            # mặc định). Lỗi ở đây không làm hỏng kết quả match nhóm ở trên.
            if args.score_jobs:
                try:
                    score_jobs_in_group(
                        conn, cv_id, args.search_group, group_result["student_skills"],
                        job_skills, skill_emb, skill_id_to_idx,
                        args.threshold_possessed, args.threshold_partial,
                        days=args.score_days,
                    )
                except Exception as e:
                    logger.error("Per-job scoring step failed (non-fatal): %s", e)

        output_data = {
            "job_title": args.search_group,
            "match_score": round(match_score, 6),
            "match_percent": match_percent,
            "student_skills": group_result["student_skills"],
            "matched_skills": matched_skills,
            "partially_matched_skills": partially_matched_skills,
            "missing_skills": missing_skills,
        }

        # Print output to stdout
        print("\n=== MATCHING RESULT ===")
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
        
        # Save output JSON to file
        output_file_path = args.output
        if not output_file_path:
            cv_path = Path(args.cv)
            output_file_path = cv_path.parent / f"{cv_path.stem}_matching_result.json"
            
        try:
            with open(output_file_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info("Saved matching result JSON to %s", output_file_path)
        except Exception as e:
            logger.error("Failed to save matching result JSON to file: %s", e)
            
    finally:
        conn.close()


if __name__ == "__main__":
    main()
