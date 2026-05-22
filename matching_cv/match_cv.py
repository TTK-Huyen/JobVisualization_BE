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


def main():
    parser = argparse.ArgumentParser(description="Match CV skills with Job Title requirements.")
    parser.add_argument("--cv", required=True, help="Path to student CV file (PDF/PNG/JPG/JPEG)")
    parser.add_argument("--search-group", required=True, help="Search group/job title to match against")
    parser.add_argument("--threshold-possessed", type=float, default=0.75, help="Similarity threshold for possessed skills")
    parser.add_argument("--threshold-partial", type=float, default=0.3, help="Similarity threshold for partial match skills")
    parser.add_argument("--confidence-threshold", type=float, default=0.85, help="LLM skill extraction confidence threshold")
    
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

        # Extract skills using Gemini
        logger.info("Extracting skills using Gemini...")
        raw_skills = extract_student_skills_gemini(cv_text, confidence_threshold=args.confidence_threshold)
        logger.info("Extracted %d skills from CV using Gemini.", len(raw_skills))

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

        # Load skills embeddings cache
        logger.info("Loading skill embeddings cache...")
        skill_emb, skill_id_to_idx, _ = load_skill_embedding_cache()

        # Matching calculation
        # Calculate similarity between target job skills and student skills
        matched_skills = []
        partially_matched_skills = []
        missing_skills = []

        total_weight = sum(item["weight"] for item in job_skills)
        weighted_sim_sum = 0.0

        for target in job_skills:
            target_sid = target["skill_id"]
            target_name = target["skill_name"]
            weight = target["weight"]

            # Compute maximum similarity with any student skill
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

        output_data = {
            "job_title": args.search_group,
            "match_score": round(match_score, 6),
            "match_percent": match_percent,
            "student_skills": student_skills,
            "matched_skills": matched_skills,
            "partially_matched_skills": partially_matched_skills,
            "missing_skills": missing_skills,
        }

        # Print output to stdout
        print(json.dumps(output_data, ensure_ascii=False, indent=2))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
