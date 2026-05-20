from __future__ import annotations

import os
import pickle
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import importlib.util

import sys
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
except Exception:
    SentenceTransformer = None
    np = None

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None

for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break

if PROJECT_ROOT and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def load_job_normalizer_module():
    repo_root = Path(__file__).resolve().parents[1]
    normalizer_path = (
        repo_root
        / "Db"
        / "pipeline"
        / "normalize"
        / "2_1_normalized_data"
        / "normalize_embeddings.py"
    )

    if not normalizer_path.exists():
        raise RuntimeError(f"normalize_embeddings.py not found: {normalizer_path}")

    spec = importlib.util.spec_from_file_location(
        "normalize_embeddings_shared",
        normalizer_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _find_skills_cache() -> Optional[Path]:
    # Common cache locations used by Db pipeline
    repo_root = Path(__file__).resolve().parents[1]

    candidates = [
        repo_root / "Db" / "pipeline" / "normalize" / "2_1_normalized_data" / "cache" / "skills_embedding.pkl",
        repo_root / "Db" / "2_1_normalized_data" / "cache" / "skills_embedding.pkl",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def load_skill_embedding_cache():
    cache = _find_skills_cache()
    if not cache:
        raise RuntimeError("Skills embeddings cache not found.")

    with cache.open("rb") as fh:
        data = pickle.load(fh)

    skill_emb = data.get("emb")
    skill_map = data.get("map")

    if skill_emb is None or skill_map is None:
        raise RuntimeError("Invalid skills embedding cache format")

    skill_emb = np.asarray(skill_emb, dtype=float)

    skill_id_to_idx = {
        int(t[0]): idx
        for idx, t in enumerate(skill_map)
    }

    skill_id_to_name = {
        int(t[0]): str(t[1])
        for t in skill_map
    }

    return skill_emb, skill_id_to_idx, skill_id_to_name

def normalize_student_skills(
    raw_skills: List[str],
    model_name: str = "all-MiniLM-L6-v2",
    top_k: int = 10,
    disable_llm_rerank: bool = False,
    llm_batch_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Normalize student CV skills by reusing the same normalize_job()
    logic from job normalization pipeline.
    """

    if SentenceTransformer is None or np is None:
        raise RuntimeError(
            "sentence-transformers and numpy are required. Install: pip install sentence-transformers numpy"
        )

    cache = _find_skills_cache()
    if not cache:
        raise RuntimeError(
            "Skills embeddings cache not found. Run normalization pipeline to produce skills_embedding.pkl"
        )

    with cache.open("rb") as fh:
        data = pickle.load(fh)

    skill_emb = data.get("emb")
    skill_map = data.get("map")

    if skill_emb is None or skill_map is None:
        raise RuntimeError("Invalid skills embedding cache format (expected 'emb' and 'map')")

    skill_emb = np.asarray(skill_emb, dtype=float)
    skill_map = [(int(sid), str(name)) for sid, name in skill_map]
    skill_names = [name for _, name in skill_map]

    model = SentenceTransformer(model_name)

    shared = load_job_normalizer_module()

    keyword_index = {
        shared.normalize_skill_key(name): name
        for _, name in skill_map
        if shared.normalize_skill_key(name)
    }

    skill_items = []

    for s in raw_skills:
        if isinstance(s, dict):
            skill = s.get("skill") or s.get("skill_name") or s.get("name")
            evidence = s.get("evidence") or s.get("evidence_text") or ""
            confidence = s.get("confidence", 100)
        else:
            skill = str(s)
            evidence = ""
            confidence = 100

        skill = str(skill).strip() if skill else ""
        evidence = str(evidence).strip() if evidence else ""

        if skill:
            skill_items.append({
                "skill_name": skill,
                "confidence": confidence,
                "is_direct_skill": True,
                "evidence_text": evidence or skill,
            })

    queries = [x["skill_name"] for x in skill_items]
    if not queries:
        return []

    evidence_context = "\n".join(
        x.get("evidence_text") or x["skill_name"]
        for x in skill_items
    )

    fake_job = {
        "title": "Student CV",
        "extracted_skills": skill_items,
        "benefits": [],
        "requirements_text": evidence_context,
        "raw": {
            "requirements_text": evidence_context
        },
        "job": {
            "skills_desc": {
                "value": evidence_context
            }
        }
    }

    normalized_record = shared.normalize_job(
        fake_job,
        skill_names=skill_names,
        skill_emb=skill_emb,
        skill_map=skill_map,
        benefit_names=[],
        benefit_emb=np.zeros((0, skill_emb.shape[1]), dtype=float),
        benefit_map=[],
        model=model,
        threshold=float(os.getenv("NORMALIZE_SIM_THRESHOLD", "0.5")),
        top_k=top_k,
        disable_llm_rerank=disable_llm_rerank,
        llm_delay=int(os.getenv("NORMALIZE_LLM_RETRY_DELAY", "15")),
        llm_max_retries=int(os.getenv("NORMALIZE_LLM_MAX_RETRIES", "1")),
        llm_batch_size=llm_batch_size,
        keyword_index=keyword_index,
    )

    return normalized_record.get("normalized_skills", [])