from __future__ import annotations

import os
import pickle
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
except Exception:
    SentenceTransformer = None
    np = None


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
    top_k: int = 1
) -> List[Dict[str, Any]]:
    """Map raw student skills to DB canonical skills using embedding similarity."""

    cache = _find_skills_cache()
    if not cache:
        raise RuntimeError(
            "Skills embeddings cache not found. Run normalization pipeline to produce skills_embedding.pkl"
        )

    try:
        with cache.open("rb") as fh:
            data = pickle.load(fh)
    except Exception as e:
        raise RuntimeError(f"Failed to load skills embedding cache: {e}")

    skill_emb = data.get("emb")
    skill_map = data.get("map")

    if skill_emb is None or skill_map is None:
        raise RuntimeError("Invalid skills embedding cache format (expected 'emb' and 'map')")

    skill_ids = [int(t[0]) for t in skill_map]
    skill_names = [str(t[1]) for t in skill_map]

    if SentenceTransformer is None or np is None:
        raise RuntimeError(
            "sentence-transformers and numpy are required. Install: pip install sentence-transformers numpy"
        )

    queries = [str(s).strip() for s in raw_skills if str(s).strip()]
    if not queries:
        return []

    model = SentenceTransformer(model_name)

    q_emb = model.encode(queries, normalize_embeddings=True)
    skill_emb = np.asarray(skill_emb, dtype=float)

    sims = (
        np.dot(q_emb, skill_emb.T)
        if skill_emb.shape[0] > 0
        else np.zeros((q_emb.shape[0], 0))
    )

    normalize_sim_threshold = float(os.getenv("NORMALIZE_SIM_THRESHOLD", "0.65"))

    out: List[Dict[str, Any]] = []

    for i, q in enumerate(queries):
        if sims.shape[1] == 0:
            best_idx = -1
            best_sim = 0.0
            sid = None
            sname = None
        else:
            best_idx = int(np.argmax(sims[i]))
            best_sim = float(sims[i, best_idx])

            if best_sim >= normalize_sim_threshold:
                sid = int(skill_ids[best_idx])
                sname = skill_names[best_idx]
            else:
                sid = None
                sname = None
        print(f"[Normalize] {q} → {sname} | sim={best_sim:.3f}")
        out.append({
            "original_skill": q,
            "skill_id": sid,
            "skill_name": sname,
            "similarity_score": round(best_sim, 6),
        })

    return out
