#!/usr/bin/env python3
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
from matching_cv.normalizer import normalize_student_skills, load_skill_embedding_cache
import time
from matching_cv.utils import extract_cv_text, load_db_env
from Db.llm.llm_config import (
                    LLM_CALL_TIMEOUT_SECONDS,
                    LLM_RETRY_DELAY_2,
                    LLM_DISABLE_KEY_MINUTES,
                )
from Db.input.config_api import get_api_key_info, on_api_quota_error

try:
    import psycopg2
except Exception:
    psycopg2 = None

try:
    from Db.llm.debug_llm_adapter import call_llm as db_call_llm
    from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
except Exception:
    db_call_llm = None
    LLM_CALL_TIMEOUT_SECONDS = 30


logger = logging.getLogger("matching_cv")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def fetch_all_skills(conn):
    cur = conn.cursor()

    sql = """
        SELECT skill_id, skill_name
        FROM public.skills
        ORDER BY skill_name
    """

    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()

    return [
        {
            "skill_id": int(row[0]),
            "skill_name": row[1],
        }
        for row in rows
    ]
    
def load_gemini_keys() -> List[str]:
    keys = []
    for name, value in os.environ.items():
        m = re.fullmatch(r"GEMINI_API_KEY_(\d+)", name)
        if m and value:
            keys.append((int(m.group(1)), value))
    keys.sort()
    return [v for _, v in keys]

def load_cv_skill_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "extract_cv_skills.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")

def extract_student_skills(cv_text: str) -> List[Dict[str, Any]]:
    if not db_call_llm:
        raise RuntimeError("LLM adapter not available (Db.llm.debug_llm_adapter).")

    prompt_template = load_cv_skill_prompt()
    prompt = prompt_template.replace("{{cv_text}}", cv_text[:8000])

    def norm(text: str) -> str:
        return " ".join(
            str(text)
            .lower()
            .replace("￾", " ")
            .replace("...", " ")
            .split()
        )

    cv_norm = norm(cv_text)
    threshold = float(os.getenv("CV_SKILL_CONFIDENCE_THRESHOLD", "0.85"))
    max_attempts = int(os.getenv("MATCH_CV_LLM_MAX_ATTEMPTS", "5"))

    last_exc = None

    for attempt in range(1, max_attempts + 1):
        key, key_label = get_api_key_info("gemini")

        logger.info("[LLM] Using API key: %s", key_label)

        if not key:
            raise RuntimeError("No active Gemini API keys available. All keys may be in cooldown.")

        try:
            logger.info("[LLM] Attempt %d/%d", attempt, max_attempts)

            raw = db_call_llm(
                prompt=prompt,
                api_key=key,
                timeout_seconds=int(os.getenv(
                    "MATCH_CV_LLM_TIMEOUT_SECONDS",
                    str(LLM_CALL_TIMEOUT_SECONDS)
                )),
            )

            raw = raw.strip()

            m = re.search(r"\[.*\]", raw, re.S)
            if m:
                raw = m.group(0)

            data = json.loads(raw)

            out = []

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

                    if not skill or confidence < threshold:
                        continue

                    skill_norm = norm(skill)
                    ev_norm = norm(evidence)

                    # Accept nếu evidence xuất hiện trong CV
                    # hoặc skill name xuất hiện trực tiếp trong CV
                    if not ev_norm or (ev_norm not in cv_norm and skill_norm not in cv_norm):
                        logger.info(
                            "Drop skill without evidence: %s | evidence=%s",
                            skill,
                            evidence
                        )
                        continue

                    out.append({
                        "skill": skill,
                        "evidence": evidence,
                        "confidence": confidence,
                    })

            if len(out) > 0:
                return out
            else:
                logger.warning("Empty skill result, retrying...")

        except Exception as e:
            last_exc = e
            logger.warning("[LLM] Attempt %d/%d failed: %s", attempt, max_attempts, e)

            msg = str(e).lower()
            if "quota" in msg or "429" in msg or "rate" in msg:
                on_api_quota_error("gemini")

            if attempt < max_attempts:
                sleep_seconds = int(os.getenv(
                    "MATCH_CV_LLM_RETRY_SLEEP_SECONDS",
                    str(LLM_RETRY_DELAY_2)
                ))
                logger.info("Waiting %ds before retry...", sleep_seconds)
                time.sleep(sleep_seconds)

    raise RuntimeError(f"LLM extraction failed: {last_exc}")

def get_db_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required. Install psycopg2-binary.")
    host = os.getenv("PG_HOST")
    port = os.getenv("PG_PORT")
    db = os.getenv("PG_DB")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    if not all([host, port, db, user, password]):
        raise RuntimeError("PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD must be set in Db/.env")
    return psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)


def fetch_job_skill_weights(conn, search_group: str) -> Dict[int, float]:
    cur = conn.cursor()
    sql = (
        "SELECT w.skill_id, w.weight_wi, s.skill_name "
        "FROM public.job_group_skill_weights w "
        "LEFT JOIN public.skills s ON w.skill_id = s.skill_id "
        "WHERE w.search_group = %s"
    )
    cur.execute(sql, (search_group,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return {}
    out = {int(r[0]): float(r[1]) for r in rows}
    return out


def compute_match(student_norm: List[Dict[str, Any]], job_weights: Dict[int, float]) -> Dict[str, Any]:
    skill_emb, skill_id_to_idx, skill_id_to_name = load_skill_embedding_cache()

    student_skill_ids = [
        int(s["skill_id"])
        for s in student_norm
        if s.get("skill_id") is not None and int(s["skill_id"]) in skill_id_to_idx
    ]

    matched_skills = []
    skill_gaps = []
    match_score = 0.0

    for job_skill_id, weight in job_weights.items():
        job_skill_id = int(job_skill_id)
        job_skill_name = skill_id_to_name.get(job_skill_id)

        if job_skill_id not in skill_id_to_idx:
            sim_i = 0.0
            best_student_skill = None
        elif job_skill_id in student_skill_ids:
            sim_i = 1.0
            best_student_skill = {
                "skill_id": job_skill_id,
                "skill_name": job_skill_name,
                "similarity": 1.0,
            }
        else:
            job_vec = skill_emb[skill_id_to_idx[job_skill_id]]

            best_sim = 0.0
            best_student_skill = None

            for student_skill_id in student_skill_ids:
                student_vec = skill_emb[skill_id_to_idx[student_skill_id]]

                # embeddings đã normalize nên dot product = cosine similarity
                sim = float(np.dot(job_vec, student_vec))

                if sim > best_sim:
                    best_sim = sim
                    best_student_skill = {
                        "skill_id": student_skill_id,
                        "skill_name": skill_id_to_name.get(student_skill_id),
                        "similarity": round(sim, 6),
                    }

            sim_i = best_sim

            # chặn match ảo: nếu similarity thấp thì xem như không match
            threshold = float(os.getenv("MATCH_SIMILARITY_THRESHOLD", "0.55"))
            if sim_i < threshold:
                sim_i = 0.0
                best_student_skill = None

        contribution = weight * sim_i
        gap = weight * (1.0 - sim_i)

        match_score += contribution

        matched_skills.append({
            "skill_id": job_skill_id,
            "skill_name": job_skill_name,
            "weight": weight,
            "similarity": round(sim_i, 6),
            "matched_student_skill": best_student_skill,
            "contribution": round(contribution, 6),
        })

        skill_gaps.append({
            "skill_id": job_skill_id,
            "skill_name": job_skill_name,
            "weight": weight,
            "similarity": round(sim_i, 6),
            "gap": round(gap, 6),
        })

    skill_gaps = sorted(
        [g for g in skill_gaps if g["gap"] > 0],
        key=lambda x: x["gap"],
        reverse=True
    )

    matched_skills = sorted(
        [m for m in matched_skills if m["similarity"] > 0],
        key=lambda x: x["contribution"],
        reverse=True
    )

    return {
        "match_score": round(match_score, 6),
        "match_percent": round(match_score * 100.0, 2),
        "matched_skills": matched_skills,
        "skill_gaps": skill_gaps,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cv", required=True)
    parser.add_argument("--search-group", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not load_db_env():
        logger.warning("could not load Db/.env (looking up parents). Continuing with existing environment variables.")

    try:
        cv_text = extract_cv_text(args.cv)
    except Exception as e:
        logger.error("Error extracting CV text: %s", e)
        sys.exit(2)

    logger.info("CV text length: %d", len(cv_text))

    try:
        student_raw = extract_student_skills(cv_text)
    except Exception as e:
        logger.error("LLM extraction failed: %s", e)
        sys.exit(3)

    logger.info("LLM extracted skills: %d", len(student_raw))

    # raw skill names
    raw_skill_names = [s.get("skill") for s in student_raw if s.get("skill")]

    try:
        student_norm = normalize_student_skills(raw_skill_names)
    except Exception as e:
        logger.error("Normalization failed: %s", e)
        sys.exit(4)

    normalized_success = len([s for s in student_norm if s.get("skill_id")])
    logger.info("Normalized skills count (mapped to DB skill_id): %d", normalized_success)

    try:
        conn = get_db_conn()
    except Exception as e:
        logger.error("DB connection failed: %s", e)
        sys.exit(5)

    try:
        job_weights = fetch_job_skill_weights(conn, args.search_group)
    except Exception as e:
        logger.error("Failed to fetch job weights: %s", e)
        conn.close()
        sys.exit(6)

    if not job_weights:
        logger.error("No weights found for search_group '%s'", args.search_group)
        conn.close()
        sys.exit(7)

    total_w = sum(job_weights.values())
    logger.info("Total weight for job: %.6f", total_w)

    result = compute_match(student_norm, job_weights)

    # Log match percent and top 10 gaps
    logger.info("Match percent: %.2f%%", result.get("match_percent", 0.0))

    top_gaps = result.get("skill_gaps", [])[:10]
    logger.info("Top %d skill gaps:", min(10, len(top_gaps)))
    for i, g in enumerate(top_gaps, start=1):
        logger.info("%d) skill_id=%s weight=%.6f similarity=%.4f gap=%.6f", i, g.get("skill_id"), g.get("weight"), g.get("similarity"), g.get("gap"))

    out = {
        "job_title": args.search_group,
        "match_score": result["match_score"],
        "match_percent": result["match_percent"],
        "student_skills": student_norm,
        "matched_skills": result["matched_skills"],
        "skill_gaps": result["skill_gaps"],
    }

    # print JSON to stdout for downstream consumption
    summary_out = {
        "job_title": args.search_group,
        "match_score": result["match_score"],
        "match_percent": result["match_percent"],
        "student_skill_count": len(student_norm),
        "job_skill_count": len(job_weights),
        "top_matched_skills": result["matched_skills"][:15],
        "top_missing_skills": [
            g for g in result["skill_gaps"]
            if g["gap"] > 0
        ][:15],
    }

    print(json.dumps(summary_out, ensure_ascii=False, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
