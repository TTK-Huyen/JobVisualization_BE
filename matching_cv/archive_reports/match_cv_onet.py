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
from matching_cv.matching_engine import ai_weight_skills

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
                continue

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
