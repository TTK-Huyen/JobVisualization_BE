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
    # Prefer v2 normalizer, fallback to original
    normalizer_path_v2 = (
        repo_root
        / "Db"
        / "pipeline"
        / "normalize"
        / "normalize_pipeline_v2.py"
    )
    normalizer_path_old = (
        repo_root
        / "Db"
        / "pipeline"
        / "normalize"
        / "normalize_embeddings.py"
    )

    normalizer_path = normalizer_path_v2 if normalizer_path_v2.exists() else normalizer_path_old

    if not normalizer_path.exists():
        raise RuntimeError(f"normalize normalizer not found: {normalizer_path}")

    spec = importlib.util.spec_from_file_location(
        "normalize_embeddings_shared",
        normalizer_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_normalize_skill_key_func(shared_module):
    """Get the appropriate skill normalization function based on module version."""
    # Try v2 first (clean_skill_name), then fallback to v1 (normalize_skill_key)
    if hasattr(shared_module, 'clean_skill_name'):
        return shared_module.clean_skill_name
    elif hasattr(shared_module, 'normalize_skill_key'):
        return shared_module.normalize_skill_key
    else:
        # Fallback: create a simple normalization function
        def simple_normalize(text: str) -> str:
            if not text:
                return ""
            text = str(text).lower()
            text = re.sub(r"\([^)]*\)", "", text)
            text = re.sub(r"\s+", " ", text)
            return text.strip()
        return simple_normalize

def _find_skills_cache() -> Optional[Path]:
    # Common cache locations used by Db pipeline
    repo_root = Path(__file__).resolve().parents[1]

    candidates = [
        repo_root / "Db" / "pipeline" / "normalize" / "cache" / "skills_embedding.pkl",
        repo_root / "Db"  / "cache" / "skills_embedding.pkl",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def _ensure_skills_embedding_cache(model_name: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    default_cache = repo_root / "Db" / "pipeline" / "normalize" / "cache" / "skills_embedding.pkl"

    cache = _find_skills_cache()
    
    # Check if cache is missing or empty
    need_rebuild = False
    if not cache:
        need_rebuild = True
        cache = default_cache
    else:
        try:
            with cache.open("rb") as fh:
                data = pickle.load(fh)
            if not data or not data.get("map"):
                need_rebuild = True
        except Exception:
            need_rebuild = True

    if need_rebuild:
        print(f"[CACHE INFO] Skills embedding cache empty or missing at {cache}. Rebuilding from database...")
        import psycopg2
        import os
        
        try:
            conn = psycopg2.connect(
                host=os.getenv("PG_HOST", "localhost"),
                port=os.getenv("PG_PORT", "5432"),
                database=os.getenv("PG_DB", "job_vis_clone"),
                user=os.getenv("PG_USER", "postgres"),
                password=os.getenv("PG_PASSWORD", "123456")
            )
            cur = conn.cursor()
            cur.execute("SELECT skill_id, skill_name FROM public.skills ORDER BY skill_id;")
            rows = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to database to rebuild skills cache: {e}")

        if not rows:
            raise RuntimeError("Database table 'public.skills' is empty! Cannot rebuild skills embedding cache.")

        print(f"[CACHE INFO] Loaded {len(rows)} skills from database. Computing embeddings using {model_name}...")
        
        skill_map = [(int(row[0]), str(row[1])) for row in rows]
        skill_names = [str(row[1]) for row in rows]
        
        model = SentenceTransformer(model_name)
        skill_emb = model.encode(skill_names, show_progress_bar=True)
        
        cache.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with cache.open("wb") as fh:
                pickle.dump({"emb": skill_emb, "map": skill_map}, fh, protocol=4)
            print(f"[CACHE INFO] Successfully created and saved skills embedding cache to {cache}.")
        except Exception as e:
            raise RuntimeError(f"Failed to write skills embedding cache to disk: {e}")

    return cache

def load_skill_embedding_cache(model_name: str = "all-MiniLM-L6-v2"):
    cache = _ensure_skills_embedding_cache(model_name)

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

    cache = _ensure_skills_embedding_cache(model_name)

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
    normalize_skill_key = get_normalize_skill_key_func(shared)

    keyword_index = {
        normalize_skill_key(name): name
        for _, name in skill_map
        if normalize_skill_key(name)
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