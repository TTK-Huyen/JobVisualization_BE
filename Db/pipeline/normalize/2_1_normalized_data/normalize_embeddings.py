#!/usr/bin/env python3
"""Normalize extracted skills and benefits using sentence-transformers embeddings.

Reads: Db/data/crawl_20260429_171900/clean/extracted.json (default)
Writes: Db/data/crawl_20260429_171900/clean/normalized.json
Fallback: Db/data/crawl_20260429_171900/fallback/normalize_fallback.json

Requirements: sentence-transformers, numpy, sqlalchemy, tqdm (optional)
Model: all-MiniLM-L6-v2
Similarity threshold: 0.5 (configurable)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    raise RuntimeError("Please install sentence-transformers: pip install sentence-transformers") from e

import numpy as np
from sqlalchemy import create_engine, text
from tqdm import tqdm
import hashlib
import pickle
import json as _json
import time


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".env").exists() or (parent / "run_etl_pipeline.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]

BASE_DIR = find_project_root()


def atomic_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(str(tmp), str(path))
    except Exception:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_extracted(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except Exception:
        # try jsonlines
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
        return out


def load_dictionary_from_db(db_url: str, table: str) -> List[Tuple[int, str]]:
    engine = create_engine(db_url)
    # Try common column name variants used in project schema. Return first successful mapping.
    candidates = [
        ("skill_id", "skill_name"),
        ("id", "name"),
        ("id", "skill_name"),
        ("skill_id", "name"),
        ("benefit_id", "benefit_name"),
        ("id", "benefit_name"),
    ]
    for id_col, name_col in candidates:
        try:
            # open a fresh connection per candidate to avoid transaction aborts
            with engine.connect() as conn:
                q = text(f"SELECT {id_col} as id, {name_col} as name FROM {table}")
                res = conn.execute(q)
                rows = res.fetchall()
                if not rows:
                    continue
                out = []
                for row in rows:
                    out.append((int(row[0]), str(row[1])))
                return out
        except Exception:
            # try next candidate
            continue
    # If nothing matches, return empty list
    return []


def compute_embeddings(model: SentenceTransformer, texts: List[str], batch_size: int = 64):
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=float)
    emb = model.encode(texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    return np.asarray(emb, dtype=float)


def normalize_job(
    job: Dict[str, Any],
    skill_names: List[str],
    skill_emb: np.ndarray,
    skill_map: List[Tuple[int, str]],
    benefit_names: List[str],
    benefit_emb: np.ndarray,
    benefit_map: List[Tuple[int, str]],
    model: SentenceTransformer,
    threshold: float = 0.5,
) -> Tuple[Dict[str, Any], None]:
    """Return (normalized_record, None) or raise Exception on per-job failure."""
    normalized_skills = []
    normalized_benefits = []

    # Skills: expected as list of dicts with 'skill_name'
    skills_in = job.get("extracted_skills") or []
    skill_queries = []
    for s in skills_in:
        if isinstance(s, dict):
            name = s.get("skill_name") or s.get("name") or ""
        else:
            name = str(s)
        name = str(name).strip()
        if name:
            skill_queries.append(name)

    # Benefits: expected as list of strings
    benefits_in = job.get("benefits") or []
    benefit_queries = [str(b).strip() for b in benefits_in if str(b).strip()]

    # Batch encode unique queries for efficiency
    uniq_skill_q = list(dict.fromkeys(skill_queries))
    uniq_benefit_q = list(dict.fromkeys(benefit_queries))

    # Map skill queries
    if uniq_skill_q:
        q_emb = compute_embeddings(model, uniq_skill_q)
        # dot product since embeddings normalized -> cosine similarity
        sims = np.dot(q_emb, skill_emb.T) if skill_emb.shape[0] > 0 else np.zeros((q_emb.shape[0], 0))
        for i, q in enumerate(uniq_skill_q):
            if sims.shape[1] == 0:
                best_sim = 0.0
                best_idx = -1
            else:
                best_idx = int(np.argmax(sims[i]))
                best_sim = float(sims[i, best_idx])
            if best_idx >= 0 and best_sim >= threshold:
                sid, sname = skill_map[best_idx]
                normalized_skills.append({
                    "original": q,
                    "mapped_name": sname,
                    "skill_id": sid,
                    "confidence": round(best_sim, 4),
                })
            else:
                normalized_skills.append({
                    "original": q,
                    "mapped_name": None,
                    "skill_id": None,
                    "confidence": round(best_sim if 'best_sim' in locals() else 0.0, 4),
                })

    # Map benefits
    if uniq_benefit_q:
        b_emb = compute_embeddings(model, uniq_benefit_q)
        bsims = np.dot(b_emb, benefit_emb.T) if benefit_emb.shape[0] > 0 else np.zeros((b_emb.shape[0], 0))
        for i, q in enumerate(uniq_benefit_q):
            if bsims.shape[1] == 0:
                best_sim = 0.0
                best_idx = -1
            else:
                best_idx = int(np.argmax(bsims[i]))
                best_sim = float(bsims[i, best_idx])
            if best_idx >= 0 and best_sim >= threshold:
                bid, bname = benefit_map[best_idx]
                normalized_benefits.append({
                    "original": q,
                    "mapped_name": bname,
                    "benefit_id": bid,
                    "confidence": round(best_sim, 4),
                })
            else:
                normalized_benefits.append({
                    "original": q,
                    "mapped_name": None,
                    "benefit_id": None,
                    "confidence": round(best_sim if 'best_sim' in locals() else 0.0, 4),
                })

    # Keep original job and attach normalized lists
    out = dict(job)
    out["normalized_skills"] = normalized_skills
    out["normalized_benefits"] = normalized_benefits
    return out

def remove_unmapped_items(record: Dict[str, Any]) -> Dict[str, Any]:
    """Remove normalized skills/benefits that were not mapped to DB."""
    record["normalized_skills"] = [
        item for item in record.get("normalized_skills", [])
        if item.get("mapped_name") and item.get("skill_id")
    ]

    record["normalized_benefits"] = [
        item for item in record.get("normalized_benefits", [])
        if item.get("mapped_name") and item.get("benefit_id")
    ]

    return record

def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize skills and benefits using embeddings.")
    parser.add_argument("--input", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "clean" / "extracted.json")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "clean" / "normalized.json")
    parser.add_argument("--fallback", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "fallback" / "normalize_fallback.json")
    parser.add_argument("--db-url", type=str, default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--skill-table", type=str, default="skills")
    parser.add_argument("--benefit-table", type=str, default="benefits")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2")
    args = parser.parse_args()

    if not args.db_url:
        # Try loading .env in repo `BASE_DIR` and build connection from POSTGRES_* vars
        env_file = BASE_DIR / ".env"
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file)
        except Exception:
            # dotenv not available or failed — fall back to environment
            pass

        host = os.environ.get("POSTGRES_HOST") or os.environ.get("PG_HOST")
        port = os.environ.get("POSTGRES_PORT") or os.environ.get("PG_PORT")
        database = os.environ.get("POSTGRES_DB") or os.environ.get("PG_DB")
        user = os.environ.get("POSTGRES_USER") or os.environ.get("PG_USER")
        password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("PG_PASSWORD")

        if host or port or database or user or password:
            host = host or "localhost"
            port = str(port or "5432")
            database = database or "postgres"
            user = user or "postgres"
            password_part = f":{password}" if password else ""
            args.db_url = f"postgresql://{user}{password_part}@{host}:{port}/{database}"
            print("Using DB URL built from .env / environment variables")

    if not args.db_url:
        print(
            "Error: provide --db-url or set DATABASE_URL environment variable or set POSTGRES_* in .env",
            file=sys.stderr,
        )
        return 2

    print(f"Loading input from: {args.input}")
    jobs = load_extracted(args.input)
    print(f"Total jobs loaded: {len(jobs)}")

    print("Connecting to DB and loading dictionaries...")
    skills = load_dictionary_from_db(args.db_url, args.skill_table)
    benefits = load_dictionary_from_db(args.db_url, args.benefit_table)

    skill_map = skills
    benefit_map = benefits

    skill_names = [n for (_, n) in skill_map]
    benefit_names = [n for (_, n) in benefit_map]

    print(f"Model: {args.model_name}")
    model = SentenceTransformer(args.model_name)

    print("Computing DB embeddings (once)...")

    # Cache directory for DB dictionary embeddings
    cache_dir = BASE_DIR / "pipeline" / "normalize" / "2_1_normalized_data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    skills_cache_file = cache_dir / "skills_embedding.pkl"
    benefits_cache_file = cache_dir / "benefits_embedding.pkl"
    metadata_file = cache_dir / "metadata.json"

    def _hash_list(obj: List[Tuple[int, str]]) -> str:
        # deterministic JSON representation for hashing
        return hashlib.sha256(_json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    skills_hash = _hash_list(skill_map)
    benefits_hash = _hash_list(benefit_map)

    metadata = None
    try:
        if metadata_file.exists():
            with metadata_file.open("r", encoding="utf-8") as fh:
                metadata = _json.load(fh)
    except Exception:
        metadata = None

    need_recompute_skills = True
    need_recompute_benefits = True

    # Determine cache validity
    if metadata and metadata.get("model") == args.model_name:
        if metadata.get("skills_hash") == skills_hash and skills_cache_file.exists():
            try:
                with skills_cache_file.open("rb") as fh:
                    sk_cache = pickle.load(fh)
                skill_emb = sk_cache.get("emb")
                # ensure shape for empty
                if skill_emb is None:
                    skill_emb = np.zeros((0, model.get_sentence_embedding_dimension()), dtype=float)
                else:
                    skill_emb = np.asarray(skill_emb, dtype=float)
                need_recompute_skills = False
                print("loaded skills vectors from cache")
            except Exception:
                need_recompute_skills = True

        if metadata.get("benefits_hash") == benefits_hash and benefits_cache_file.exists():
            try:
                with benefits_cache_file.open("rb") as fh:
                    be_cache = pickle.load(fh)
                benefit_emb = be_cache.get("emb")
                if benefit_emb is None:
                    benefit_emb = np.zeros((0, model.get_sentence_embedding_dimension()), dtype=float)
                else:
                    benefit_emb = np.asarray(benefit_emb, dtype=float)
                need_recompute_benefits = False
                print("loaded benefits vectors from cache")
            except Exception:
                need_recompute_benefits = True

    else:
        if metadata:
            print("cache invalidated because DB hash/model changed")

    # Recompute and save if needed
    if need_recompute_skills:
        skill_emb = compute_embeddings(model, skill_names)
        try:
            with skills_cache_file.open("wb") as fh:
                pickle.dump({"emb": skill_emb, "map": skill_map}, fh, protocol=4)
            print("recomputed skills vectors")
        except Exception:
            print("warning: failed to write skills cache")

    if need_recompute_benefits:
        benefit_emb = compute_embeddings(model, benefit_names)
        try:
            with benefits_cache_file.open("wb") as fh:
                pickle.dump({"emb": benefit_emb, "map": benefit_map}, fh, protocol=4)
            print("recomputed benefits vectors")
        except Exception:
            print("warning: failed to write benefits cache")

    # Update metadata
    try:
        meta = {
            "model": args.model_name,
            "skills_hash": skills_hash,
            "benefits_hash": benefits_hash,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with metadata_file.open("w", encoding="utf-8") as fh:
            _json.dump(meta, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

    normalized_out = []
    fallback_out = []

    totals = {
        "jobs": 0,
        "skills_mapped": 0,
        "skills_unmatched": 0,
        "benefits_mapped": 0,
        "benefits_unmatched": 0,
    }

    for job in tqdm(jobs, desc="Normalizing jobs", unit="job"):
        totals["jobs"] += 1
        try:
            rec = normalize_job(
                job,
                skill_names,
                skill_emb,
                skill_map,
                benefit_names,
                benefit_emb,
                benefit_map,
                model,
                threshold=args.threshold,
            )
            rec = remove_unmapped_items(rec)
            # update counts
            ss = rec.get("normalized_skills", [])
            for s in ss:
                if s.get("mapped_name"):
                    totals["skills_mapped"] += 1
                else:
                    totals["skills_unmatched"] += 1
            bb = rec.get("normalized_benefits", [])
            for b in bb:
                if b.get("mapped_name"):
                    totals["benefits_mapped"] += 1
                else:
                    totals["benefits_unmatched"] += 1

            normalized_out.append(rec)
        except Exception as e:
            fallback_out.append({
                "status": "normalize_fail",
                "error": str(e),
                "job_data": job,
            })

    # Save outputs
    atomic_write(args.output, normalized_out)
    print(f"Wrote normalized output to: {args.output}")
    if fallback_out:
        atomic_write(args.fallback, fallback_out)
        print(f"Wrote fallback records to: {args.fallback}")

    # Print summary
    print("")
    print(f"Total jobs processed: {totals['jobs']}")
    print(f"Total skills mapped: {totals['skills_mapped']}")
    print(f"Total skills unmatched: {totals['skills_unmatched']}")
    print(f"Total benefits mapped: {totals['benefits_mapped']}")
    print(f"Total benefits unmatched: {totals['benefits_unmatched']}")

    # Show sample normalized output if available
    if normalized_out:
        sample = normalized_out[0]
        print("\nSample normalized (first job):")
        print(json.dumps({
            "normalized_skills": sample.get("normalized_skills"),
            "normalized_benefits": sample.get("normalized_benefits"),
        }, ensure_ascii=False, indent=2))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
