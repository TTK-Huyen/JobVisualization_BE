from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

BASE_DIR = Path(__file__).resolve().parent


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("normalize_with_embeddings")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(h)
    return logger


def load_extracted(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # try line-delimited JSON
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
        return items
    if isinstance(payload, list):
        return payload
    return [payload]


def load_skill_library(sqlite_path: Optional[Path]) -> List[Tuple[int, str]]:
    if not sqlite_path:
        raise RuntimeError("No sqlite path provided for skill library")
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Skill DB not found: {sqlite_path}")
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.execute("SELECT id, name FROM skills")
        return [(int(row[0]), str(row[1])) for row in cur.fetchall()]
    finally:
        conn.close()


def load_benefit_library(sqlite_path: Optional[Path]) -> List[Tuple[int, str]]:
    if not sqlite_path:
        raise RuntimeError("No sqlite path provided for benefit library")
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Benefit DB not found: {sqlite_path}")
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.execute("SELECT id, name FROM benefits")
        return [(int(row[0]), str(row[1])) for row in cur.fetchall()]
    finally:
        conn.close()


def build_cache(items: List[Tuple[int, str]], embed_fn, cache_path: Path) -> Tuple[List[int], np.ndarray, List[str]]:
    ids = [i for i, _ in items]
    texts = [t for _, t in items]
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            vecs = [np.array(v, dtype=float) for v in data.get("vectors", [])]
            if len(vecs) == len(texts):
                return ids, np.vstack(vecs), texts
        except Exception:
            pass

    # compute embeddings and save
    vectors = embed_fn(texts)
    arr = np.vstack(vectors)
    try:
        payload = {"ids": ids, "vectors": arr.tolist(), "texts": texts}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return ids, arr, texts


def _try_load_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")

        def embed_fn(texts: List[str]) -> List[List[float]]:
            return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

        return embed_fn
    except Exception:
        return None


def _tfidf_embed_factory():
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=4096)

        def fit_and_embed(corpus: List[str]) -> Tuple:
            mat = vectorizer.fit_transform(corpus)
            return mat

        return vectorizer
    except Exception:
        return None


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # a: (n_features,) or (1,n), b: (m,n)
    if a.ndim == 1:
        a = a.reshape(1, -1)
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-12)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-12)
    return (a_norm @ b_norm.T).ravel()


def match_best(raw: str, embed_fn, lib_ids: List[int], lib_vecs: np.ndarray, lib_texts: List[str], threshold: float = 0.6) -> Tuple[Optional[int], Optional[str], float]:
    if not raw or not raw.strip():
        return None, None, 0.0
    q_vecs = embed_fn([raw])
    if isinstance(q_vecs, np.ndarray):
        qv = q_vecs[0]
    else:
        qv = np.array(q_vecs[0], dtype=float)
    sims = cosine_sim(qv, lib_vecs)
    best_idx = int(np.argmax(sims))
    best_score = float(sims[best_idx])
    if best_score >= threshold:
        return lib_ids[best_idx], lib_texts[best_idx], best_score
    return None, None, best_score


def light_normalize(job: Dict[str, Any]) -> Dict[str, Any]:
    # minimal format-only normalization
    from Db.2_1_normalized_data.light_normalizer import light_normalize_for_import

    return light_normalize_for_import(job)


def normalize_job(job: Dict[str, Any], embed_fn, skill_lib, skill_vecs, skill_texts, skill_ids, benefit_lib, benefit_vecs, benefit_texts, benefit_ids) -> Dict[str, Any]:
    normalized = light_normalize(job)

    # prepare outputs
    out = dict(normalized)
    out["normalized_skills"] = []
    out["normalized_benefits"] = []
    out["unmatched_skills"] = []
    out["unmatched_benefits"] = []

    # extracted_skills may be list of dicts or strings
    skills = job.get("extracted_skills") or []
    for s in skills:
        raw = s.get("skill_name") if isinstance(s, dict) else str(s)
        mid, mname, score = match_best(raw, embed_fn, skill_ids, skill_vecs, skill_texts)
        if mid is not None:
            out["normalized_skills"].append({"raw": raw, "matched_id": mid, "matched_name": mname, "score": score})
        else:
            out["unmatched_skills"].append({"raw": raw, "best_match": mname, "best_score": score})

    benefits = job.get("extracted_benefits") or job.get("benefits") or []
    for b in benefits:
        raw = b if isinstance(b, str) else (b.get("benefit") if isinstance(b, dict) else str(b))
        mid, mname, score = match_best(raw, embed_fn, benefit_ids, benefit_vecs, benefit_texts)
        if mid is not None:
            out["normalized_benefits"].append({"raw": raw, "matched_id": mid, "matched_name": mname, "score": score})
        else:
            out["unmatched_benefits"].append({"raw": raw, "best_match": mname, "best_score": score})

    return out


def save_output(path: Path, data: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    logger = setup_logger()
    parser = argparse.ArgumentParser(description="Normalize extracted jobs and match skills/benefits by embedding")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True)
    parser.add_argument("--sqlite-db", type=Path, required=False, help="Path to sqlite DB containing skills and benefits tables")
    parser.add_argument("--skill-cache", type=Path, default=BASE_DIR / "cache" / "skill_embedding_cache.json")
    parser.add_argument("--benefit-cache", type=Path, default=BASE_DIR / "cache" / "benefit_embedding_cache.json")
    args = parser.parse_args()

    try:
        jobs = load_extracted(args.input)
    except Exception as exc:
        logger.error("Failed to load extracted file: %s", exc)
        return 2

    logger.info("Loaded %s extracted jobs", len(jobs))

    # build embedding function
    embed_fn = _try_load_sentence_transformer()
    use_tfidf = False
    vectorizer = None
    if embed_fn is None:
        vectorizer = _tfidf_embed_factory()
        if vectorizer is None:
            logger.error("No embedding backend available. Install sentence-transformers or scikit-learn.")
            return 3
        use_tfidf = True

    # load libraries
    try:
        skill_items = load_skill_library(args.sqlite_db) if args.sqlite_db else []
        benefit_items = load_benefit_library(args.sqlite_db) if args.sqlite_db else []
    except Exception as exc:
        logger.exception("Failed to load libraries: %s", exc)
        return 4

    if not skill_items:
        logger.error("No skill items loaded; aborting")
        return 5

    # create embed functions and caches
    if use_tfidf:
        # fit vectorizer on library + job queries on the fly per-match
        corp = [t for _, t in skill_items]
        skill_mat = vectorizer.fit_transform(corp).toarray()
        benefit_mat = None
        if benefit_items:
            benefit_mat = vectorizer.transform([t for _, t in benefit_items]).toarray()

        def embed_texts(texts: List[str]):
            return np.array(vectorizer.transform(texts).toarray())

        skill_ids = [i for i, _ in skill_items]
        skill_vecs = skill_mat
        skill_texts = [t for _, t in skill_items]
        benefit_ids = [i for i, _ in benefit_items] if benefit_items else []
        benefit_vecs = benefit_mat if benefit_mat is not None else np.empty((0, skill_vecs.shape[1]))
        benefit_texts = [t for _, t in benefit_items] if benefit_items else []
        embed_function = embed_texts
    else:
        embed_function = embed_fn
        skill_ids, skill_vecs, skill_texts = build_cache(skill_items, embed_fn, args.skill_cache)
        if benefit_items:
            benefit_ids, benefit_vecs, benefit_texts = build_cache(benefit_items, embed_fn, args.benefit_cache)
        else:
            benefit_ids, benefit_vecs, benefit_texts = [], np.empty((0, skill_vecs.shape[1])), []

    normalized: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []

    total = 0
    matched_skills = 0
    unmatched_skills = 0
    matched_benefits = 0
    unmatched_benefits = 0

    for job in jobs:
        total += 1
        try:
            out = normalize_job(job, embed_function, skill_items, skill_vecs, skill_texts, skill_ids, benefit_items, benefit_vecs, benefit_texts, benefit_ids)
            normalized.append(out)
            matched_skills += len(out.get("normalized_skills", []))
            unmatched_skills += len(out.get("unmatched_skills", []))
            matched_benefits += len(out.get("normalized_benefits", []))
            unmatched_benefits += len(out.get("unmatched_benefits", []))
        except Exception as exc:
            job_copy = dict(job)
            job_copy["failure_reason"] = "normalize_error"
            job_copy["error"] = str(exc)
            fallback.append(job_copy)

    save_output(args.output, normalized)
    if fallback:
        save_output(args.fallback, fallback)

    logger.info("Normalization finished: total=%s matched_skills=%s unmatched_skills=%s matched_benefits=%s unmatched_benefits=%s fallback=%s",
                total, matched_skills, unmatched_skills, matched_benefits, unmatched_benefits, len(fallback))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
