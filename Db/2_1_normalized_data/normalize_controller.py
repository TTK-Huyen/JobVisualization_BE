from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def setup_logger():
    logger = logging.getLogger("normalize_controller")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(h)
    return logger


def run_normalize(input_file: str, output_file: str, fallback_file: str, sqlite_db: str | None = None) -> List[Dict[str, Any]]:
    """Controller for normalization: loads input, runs embedding match, writes outputs.

    Mirrors previous `step_3_normalize_skills` behavior but located in 2_1_normalized_data.
    """
    logger = setup_logger()
    try:
        # Lazy imports to avoid heavy deps unless called
        from Db.2_clean_data.load_db_skills import load_all_skills, load_all_benefits
        from Db.2_clean_data.embedding_matcher import EmbeddingMatcher
    except Exception as exc:
        logger.exception("Failed to import normalize dependencies: %s", exc)
        raise

    input_path = Path(input_file)
    out_path = Path(output_file)
    fallback_path = Path(fallback_file)

    with input_path.open('r', encoding='utf-8') as f:
        jobs = json.load(f)
    if not isinstance(jobs, list):
        jobs = [jobs]

    logger.info("Loaded %s jobs for normalization", len(jobs))

    # Load canonical skills and benefits from DB
    skills = load_all_skills()
    benefits = load_all_benefits()
    if not skills:
        logger.error("No skills loaded from DB, aborting normalize")
        raise RuntimeError("No skills loaded")

    matcher_skills = EmbeddingMatcher(skills)
    matcher_benefits = EmbeddingMatcher(benefits) if benefits else None

    normalized_jobs = []
    fallback_jobs = []

    stats = {
        'matched_skills': 0,
        'unmatched_skills': 0,
        'matched_benefits': 0,
        'unmatched_benefits': 0,
    }

    for job in jobs:
        try:
            raw_skills = []
            extracted_skills = job.get('extracted_skills', [])
            if isinstance(extracted_skills, list):
                for item in extracted_skills:
                    if isinstance(item, dict):
                        raw = item.get('skill_name_eng') or item.get('skill_name')
                        if raw:
                            raw_skills.append(raw)
                    elif isinstance(item, str):
                        raw_skills.append(item)

            normalized_skills = []
            unmatched_skills = []
            for s in raw_skills:
                try:
                    cands = matcher_skills.find_top_5(s, k=1)
                    if cands and len(cands) > 0:
                        best, dist = cands[0]
                        confidence = 1.0 / (1.0 + dist) if dist is not None else 1.0
                        normalized_skills.append({'raw': s, 'normalized': best, 'confidence': confidence})
                        stats['matched_skills'] += 1
                    else:
                            # include highest-scoring candidate even if below match threshold
                            best_name = None
                            best_conf = 0.0
                            if cands and len(cands) > 0:
                                try:
                                    best_name, dist0 = cands[0]
                                    best_conf = 1.0 / (1.0 + dist0) if dist0 is not None else 0.0
                                except Exception:
                                    best_name = None
                                    best_conf = 0.0
                            unmatched_skills.append({'raw': s, 'best_match': best_name, 'best_score': best_conf})
                        stats['unmatched_skills'] += 1
                except Exception:
                    unmatched_skills.append({'raw': s, 'confidence': 0.0})
                    stats['unmatched_skills'] += 1

            normalized_benefits = []
            unmatched_benefits = []
            raw_benefits = job.get('benefits', []) or []
            if matcher_benefits and isinstance(raw_benefits, list):
                for b in raw_benefits:
                    try:
                        cands = matcher_benefits.find_top_5(b, k=1)
                        if cands and len(cands) > 0:
                            best, dist = cands[0]
                            confidence = 1.0 / (1.0 + dist) if dist is not None else 1.0
                            normalized_benefits.append({'raw': b, 'normalized': best, 'confidence': confidence})
                            stats['matched_benefits'] += 1
                        else:
                            best_name = None
                            best_conf = 0.0
                            if cands and len(cands) > 0:
                                try:
                                    best_name, dist0 = cands[0]
                                    best_conf = 1.0 / (1.0 + dist0) if dist0 is not None else 0.0
                                except Exception:
                                    best_name = None
                                    best_conf = 0.0
                            unmatched_benefits.append({'raw': b, 'best_match': best_name, 'best_score': best_conf})
                            stats['unmatched_benefits'] += 1
                    except Exception:
                        unmatched_benefits.append({'raw': b, 'confidence': 0.0})
                        stats['unmatched_benefits'] += 1

            job['normalized_skills'] = normalized_skills
            job['normalized_benefits'] = normalized_benefits
            job['unmatched_skills'] = unmatched_skills
            job['unmatched_benefits'] = unmatched_benefits

            normalized_jobs.append(job)
        except Exception as exc:
            job_copy = dict(job)
            job_copy['_error'] = str(exc)
            job_copy['failure_reason'] = 'normalize_error'
            fallback_jobs.append(job_copy)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(normalized_jobs, f, ensure_ascii=False, indent=2)

    if fallback_jobs:
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with fallback_path.open('w', encoding='utf-8') as f:
            json.dump(fallback_jobs, f, ensure_ascii=False, indent=2)

    logger.info("Normalize complete: total=%s matched_skills=%s unmatched_skills=%s matched_benefits=%s unmatched_benefits=%s fallback=%s",
                len(jobs), stats['matched_skills'], stats['unmatched_skills'], stats['matched_benefits'], stats['unmatched_benefits'], len(fallback_jobs))

    return normalized_jobs
