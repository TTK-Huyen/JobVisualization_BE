#!/usr/bin/env python3
"""Normalize extracted skills and benefits using SentenceTransformer embeddings against Lightcast taxonomy.

Saves:
- Db/data/crawl_20260429_171900/clean/normalized.json
- Db/data/crawl_20260429_171900/fallback/normalize_fallback.json
- cache/lightcast_embeddings_minilm.pkl
- cache/skills_embedding.pkl (legacy/backward compatibility)
- cache/benefits_embedding.pkl

Requirements: sentence-transformers, numpy, sqlalchemy, tqdm (optional)
Model: all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
import json as _json
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import csv
import re
import hashlib
import pickle
import time
import math

try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    raise RuntimeError("Please install sentence-transformers: pip install sentence-transformers") from e

import numpy as np
from sqlalchemy import create_engine, text
from tqdm import tqdm

# Ensure project root is on sys.path so imports work
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None

for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break

if PROJECT_ROOT and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Soft dependencies/imports for safety
try:
    from Db.llm.debug_llm_adapter import call_llm
except ImportError:
    call_llm = None
try:
    from Db.llm import llm_config
except ImportError:
    llm_config = None
try:
    from Db.input import config_api
except ImportError:
    config_api = None


CORE_ALIASES = {
    "sql": "SQL (Programming Language)",
    "python": "Python (Programming Language)",
    "java": "Java (Programming Language)",
    "scrum": "Scrum (Software Development)"
}


def is_independent_word(query: str, candidate: str) -> bool:
    """Check if query stands as an independent word in candidate."""
    pattern = rf"\b{re.escape(query)}\b"
    return bool(re.search(pattern, candidate, re.IGNORECASE))


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".env").exists() or (parent / "run_etl_pipeline.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]


BASE_DIR = find_project_root()

# Load environment configuration
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / "Db" / ".env")
except Exception:
    pass


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
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return []
    try:
        return json.loads(content)
    except Exception:
        out = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
        return out


def load_dictionary_from_db(db_url: str, table: str) -> List[Tuple[int, str]]:
    if not db_url:
        return []
    # Strip query arguments like ?schema=public if present to satisfy psycopg2 DSN
    if '?' in db_url:
        db_url = db_url.split('?')[0]
        
    engine = create_engine(db_url)
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
            continue
    return []


def compute_embeddings(model: SentenceTransformer, texts: List[str], batch_size: int = 64) -> np.ndarray:
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=float)
    emb = model.encode(texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    return np.asarray(emb, dtype=float)


def normalize_skill_key(text: str) -> str:
    """Legacy skill normalization key used for index lookups in backward compatibility."""
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_skill_name(text: str) -> str:
    """Clean skill names for exact matching based on the notebook's cleaning logic."""
    if not text:
        return ""
    text = str(text).strip()
    text = re.sub(r"\s*\(.*\)", "", text)
    text = text.lower()
    text = text.replace("backend", "back end")
    text = text.replace("frontend", "front end")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_prompt_template(filename: str) -> str:
    return ""


def llm_rerank_job_skills(job_title: str, skill_items: List[Dict[str, Any]], delay_seconds: int = 0, max_retries: int = 0) -> None:
    """Legacy LLM reranker, disabled for production pipeline efficiency."""
    return None


def find_best_evidence(raw_skill: str, requirements_text: str) -> str | None:
    if not raw_skill or not requirements_text:
        return None

    text_val = str(requirements_text)
    skill = str(raw_skill).strip()
    if not skill:
        return None

    parts = re.split(r"[\n\r]+|•|;|\.|\u2022", text_val)
    pattern = re.compile(rf"(?<![\w+#.-]){re.escape(skill)}(?![\w+#.-])", re.IGNORECASE)
    
    for part in parts:
        sentence = re.sub(r"\s+", " ", part).strip()
        if not sentence:
            continue
        if pattern.search(sentence):
            return sentence[:300]

    skill_lower = skill.lower()
    for part in parts:
        sentence = re.sub(r"\s+", " ", part).strip()
        if not sentence:
            continue
        if skill_lower in sentence.lower():
            return sentence[:300]

    return None


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
    top_k: int = 5,
    disable_llm_rerank: bool = False,
    llm_delay: int = 15,
    llm_max_retries: int = 2,
    llm_batch_size: int = 10,
    keyword_index: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Normalize job skills using string cleaning + exact matching, and semantic matching with all-MiniLM-L6-v2.

    Applies deterministic Scenario B matching criteria (Tier 1 >= 0.75 accepted, else rejected).
    """
    normalized_skills = []
    normalized_benefits = []
    skill_id_by_name = {name: sid for sid, name in skill_map}

    # Prepare job metadata
    job_title = job.get("title") or job.get("job", {}).get("title") or job.get("raw", {}).get("job_title") or job.get("search_keyword") or ""
    if isinstance(job_title, dict):
        jt = job_title.get("value") or job_title.get("title") or job_title.get("text")
        job_title = str(jt) if jt is not None else str(job_title)
    job_title = (str(job_title) or "").strip()
    job_id = job.get("id") or job.get("job", {}).get("id") or job.get("job_id") or job.get("raw", {}).get("id") or hashlib.sha256(json.dumps(job, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]

    def _extract_raw_skill(item: Any) -> tuple[str, str]:
        raw = None
        evidence = None
        if isinstance(item, dict):
            for k in ("skill_name", "skill_name_eng", "name", "skill", "original", "raw"):
                if k in item and item.get(k) is not None:
                    raw = item.get(k)
                    break
            if isinstance(raw, dict):
                for nk in ("name", "skill_name", "value", "text"):
                    if nk in raw and raw.get(nk) is not None:
                        raw = raw.get(nk)
                        break
            evidence = item.get("evidence_text") or item.get("evidence") or item.get("context")
        else:
            raw = item
        raw = "" if raw is None else str(raw).strip()
        evidence = "" if evidence is None else str(evidence).strip()
        return raw, evidence

    # Gather extracted skills
    skills_in = job.get("extracted_skills") or []
    skill_entries = []
    requirements_text = (
        job.get("raw", {}).get("requirements_text")
        or job.get("requirements_text")
        or job.get("job", {}).get("skills_desc", {}).get("value")
        or ""
    )

    for s in skills_in:
        raw_skill, evidence_text = _extract_raw_skill(s)
        if not evidence_text:
            evidence_text = find_best_evidence(raw_skill, requirements_text) or ""
        if raw_skill:
            skill_entries.append({"raw": raw_skill, "evidence": evidence_text})

    # Deduplicate queries to normalize once per unique skill
    uniq_skill_q = []
    seen = set()
    for e in skill_entries:
        q = e.get("raw") or ""
        if q and q not in seen:
            seen.add(q)
            uniq_skill_q.append(q)

    # Deduplicate benefits
    benefits_in = job.get("benefits") or []
    uniq_benefit_q = []
    seen_b = set()
    for b in benefits_in:
        if isinstance(b, dict):
            bstr = b.get("value") or b.get("name") or b.get("benefit_name") or ""
        else:
            bstr = str(b)
        bstr = (bstr or "").strip()
        if bstr and bstr not in seen_b:
            seen_b.add(bstr)
            uniq_benefit_q.append(bstr)

    # Setup audit trace file
    trace_path = BASE_DIR / "data" / "normalization_trace.csv"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_header = ["job_id", "original_skill", "job_title", "evidence_text", "stage_reached", "final_method", "final_score", "mapped_name", "status"]
    if not trace_path.exists():
        try:
            with trace_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(trace_header)
        except Exception:
            pass

    # Build Exact-Match cleaned mapping table
    exact_match_lookup = {}
    for original_name in skill_names:
        cleaned = clean_skill_name(original_name)
        if cleaned and cleaned not in exact_match_lookup:
            exact_match_lookup[cleaned] = original_name

    # Phase 1 & 2 Normalization Loop
    if uniq_skill_q:
        q_emb = compute_embeddings(model, uniq_skill_q)
        sims = np.dot(q_emb, skill_emb.T) if skill_emb.shape[0] > 0 else np.zeros((q_emb.shape[0], 0))

        for i, q in enumerate(uniq_skill_q):
            evidence = next((entry.get("evidence") for entry in skill_entries if entry.get("raw") == q), "")
            stage = "start"
            final_method = "Unmatched"
            final_score = 0.0
            mapped_name = None
            mapped_id = None
            status = "unmatched"

            q_clean = clean_skill_name(q)

            # Phase 1: Cleaned Exact Matching
            if q_clean in exact_match_lookup:
                matched_name = exact_match_lookup[q_clean]
                mapped_id = skill_id_by_name.get(matched_name)
                if mapped_id is not None:
                    stage = "exact_match"
                    final_method = "Exact Match"
                    final_score = 1.0
                    status = "auto_accepted"

                    normalized_skills.append({
                        "original": q,
                        "mapped_name": matched_name,
                        "skill_id": mapped_id,
                        "confidence": 1.0,
                        "status": status,
                        "method": final_method,
                        "evidence": evidence,
                        "candidates": [],
                    })
                    try:
                        with trace_path.open("a", encoding="utf-8", newline="") as fh:
                            writer = csv.writer(fh)
                            writer.writerow([job_id, q, job_title, evidence, stage, final_method, 1.0, matched_name, status])
                    except Exception:
                        pass
                    continue

            # Phase 2: Semantic Embedding Match (Tier 1 vs Unmatched)
            if sims.shape[1] > 0:
                top_idx = int(np.argmax(sims[i]))
                top_score = float(sims[i, top_idx])
                candidate_name = skill_names[top_idx]
            else:
                top_score = 0.0
                candidate_name = None

            stage = "bi_encoder"
            if top_score >= 0.75:
                # Tier 1 auto-accepted
                matched_name = candidate_name
                mapped_id = skill_id_by_name.get(matched_name)
                if mapped_id is not None:
                    final_method = "Tier 1"
                    final_score = top_score
                    status = "auto_accepted"

                    normalized_skills.append({
                        "original": q,
                        "mapped_name": matched_name,
                        "skill_id": mapped_id,
                        "confidence": round(final_score, 4),
                        "status": status,
                        "method": final_method,
                        "evidence": evidence,
                        "candidates": [],
                    })
                    try:
                        with trace_path.open("a", encoding="utf-8", newline="") as fh:
                            writer = csv.writer(fh)
                            writer.writerow([job_id, q, job_title, evidence, stage, final_method, round(final_score, 4), matched_name, status])
                    except Exception:
                        pass
                    continue

            # Unmatched / Rejected (Tier 2 & 3)
            final_method = "Unmatched"
            final_score = top_score
            status = "unmatched"

            normalized_skills.append({
                "original": q,
                "mapped_name": None,
                "skill_id": None,
                "confidence": round(final_score, 4),
                "status": status,
                "method": final_method,
                "evidence": evidence,
                "candidates": [],
            })
            try:
                with trace_path.open("a", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow([job_id, q, job_title, evidence, stage, final_method, round(final_score, 4), "", status])
            except Exception:
                pass

    # Map benefits using legacy bi-encoder similarity logic
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
                    "confidence": round(best_sim, 4),
                })

    # Return record containing both mapped list and benefits
    out = dict(job)
    out["normalized_skills"] = normalized_skills
    out["normalized_benefits"] = normalized_benefits
    return out


def remove_unmapped_items(record: Dict[str, Any]) -> Dict[str, Any]:
    """Remove normalized skills/benefits that were not mapped to database identifiers."""
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
    parser = argparse.ArgumentParser(description="Normalize skills and benefits using sentence embeddings.")
    parser.add_argument("--input", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "clean" / "extracted.json")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "clean" / "normalized.json")
    parser.add_argument("--fallback", type=Path, default=BASE_DIR / "data" / "crawl_20260429_171900" / "fallback" / "normalize_fallback.json")
    parser.add_argument("--db-url", type=str, default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--skill-table", type=str, default="skills")
    parser.add_argument("--benefit-table", type=str, default="benefits")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--disable-llm-rerank", action="store_true", default=False)
    parser.add_argument("--llm-rerank-delay", type=int, default=15)
    parser.add_argument("--llm-rerank-max-retries", type=int, default=2)
    parser.add_argument("--llm-batch-size", type=int, default=10)

    args = parser.parse_args()

    # Load DB connection credentials from .env files if db_url is not set
    if not args.db_url:
        env_file = BASE_DIR / "Db" / ".env"
        if not env_file.exists():
            env_file = BASE_DIR / ".env"
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except Exception:
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
        print("Error: provide --db-url or set DATABASE_URL environment variable or set POSTGRES_* in .env", file=sys.stderr)
        return 2

    print(f"Loading input from: {args.input}")
    jobs = load_extracted(args.input)
    print(f"Total jobs loaded: {len(jobs)}")

    print("Connecting to DB and loading dictionaries...")
    skills = load_dictionary_from_db(args.db_url, args.skill_table)
    benefits = load_dictionary_from_db(args.db_url, args.benefit_table)
    db_skills_by_name = {row[1]: row[0] for row in skills}

    print(f"Total skills/keywords loaded from DB: {len(skills)}")
    print(f"Total benefits loaded from DB: {len(benefits)}")

    # Locate local Lightcast CSV
    script_dir = Path(__file__).resolve().parent
    possible_paths = [
        script_dir / "Lightcast" / "lightcast.csv",
        script_dir / "lightcast" / "lightcast.csv",
        Path("Lightcast/lightcast.csv"),
        Path("lightcast/lightcast.csv"),
        Path("./Lightcast/lightcast.csv"),
        Path("./lightcast/lightcast.csv"),
    ]
    lightcast_csv = None
    for p in possible_paths:
        if p.exists():
            lightcast_csv = p.resolve()
            break

    if not lightcast_csv:
        print("Error: Lightcast taxonomy CSV not found locally.", file=sys.stderr)
        return 3

    # Load and filter Lightcast CSV
    print(f"Loading and filtering local Lightcast CSV from: {lightcast_csv}")
    lightcast_skills = []
    allowed_types = {'Hard Skill', 'Specialized Skill', 'Common skill', 'Common Skill'}
    
    with open(lightcast_csv, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 5:
                continue
            name = row[1].strip()
            skill_type = row[4].strip()
            if skill_type in allowed_types and name:
                lightcast_skills.append(name)

    # Deduplicate while preserving order
    seen = set()
    lightcast_skills_dedup = []
    for s in lightcast_skills:
        if s not in seen:
            seen.add(s)
            lightcast_skills_dedup.append(s)
    lightcast_skills = lightcast_skills_dedup
    print(f"Total allowed skills loaded from Lightcast CSV: {len(lightcast_skills)}")

    # Map allowed Lightcast skills to database IDs
    lightcast_skill_map = []
    for name in lightcast_skills:
        sid = db_skills_by_name.get(name)
        if sid is not None:
            lightcast_skill_map.append((sid, name))
        else:
            lightcast_skill_map.append((-1, name))

    print(f"Model: {args.model_name}")
    model = SentenceTransformer(args.model_name)

    # Configure Pickle cache paths
    cache_dir = script_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lightcast_cache_file = cache_dir / "lightcast_embeddings_minilm.pkl"
    legacy_skills_cache_file = cache_dir / "skills_embedding.pkl"
    benefits_cache_file = cache_dir / "benefits_embedding.pkl"
    metadata_file = cache_dir / "metadata.json"

    def _hash_list(obj: List[Any]) -> str:
        return hashlib.sha256(_json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    lightcast_hash = _hash_list(lightcast_skills)
    benefits_hash = _hash_list(benefits)

    metadata = None
    if metadata_file.exists():
        try:
            with metadata_file.open("r", encoding="utf-8") as fh:
                metadata = _json.load(fh)
        except Exception:
            metadata = None

    need_recompute_lightcast = True
    lightcast_emb = None

    if metadata and metadata.get("model") == args.model_name:
        if metadata.get("lightcast_hash") == lightcast_hash and lightcast_cache_file.exists():
            try:
                with lightcast_cache_file.open("rb") as fh:
                    lc_cache = pickle.load(fh)
                lightcast_emb = lc_cache.get("emb")
                if lightcast_emb is not None:
                    lightcast_emb = np.asarray(lightcast_emb, dtype=float)
                    need_recompute_lightcast = False
                    print("Loaded Lightcast embedding vectors from cache")
            except Exception:
                need_recompute_lightcast = True

    if need_recompute_lightcast:
        print(f"Computing embeddings for {len(lightcast_skills)} Lightcast skills...")
        lightcast_emb = compute_embeddings(model, lightcast_skills)
        try:
            with lightcast_cache_file.open("wb") as fh:
                pickle.dump({"emb": lightcast_emb, "skills": lightcast_skills}, fh, protocol=4)
            print("Saved Lightcast vectors to cache")
        except Exception as e:
            print(f"Warning: Failed to write Lightcast cache: {e}")

    # Synchronize legacy skills cache file for CV matching backward compatibility
    if need_recompute_lightcast or not legacy_skills_cache_file.exists():
        try:
            with legacy_skills_cache_file.open("wb") as fh:
                pickle.dump({"emb": lightcast_emb, "map": lightcast_skill_map}, fh, protocol=4)
            print("Synchronized legacy skills_embedding.pkl cache file")
        except Exception as e:
            print(f"Warning: Failed to write legacy skills cache: {e}")

    # Load or compute benefits cache
    need_recompute_benefits = True
    benefit_emb = None

    if metadata and metadata.get("model") == args.model_name:
        if metadata.get("benefits_hash") == benefits_hash and benefits_cache_file.exists():
            try:
                with benefits_cache_file.open("rb") as fh:
                    be_cache = pickle.load(fh)
                benefit_emb = be_cache.get("emb")
                if benefit_emb is not None:
                    benefit_emb = np.asarray(benefit_emb, dtype=float)
                    need_recompute_benefits = False
                    print("Loaded benefits vectors from cache")
            except Exception:
                need_recompute_benefits = True

    if need_recompute_benefits:
        print(f"Computing DB benefits embeddings for {len(benefits)} benefits...")
        benefit_names = [b[1] for b in benefits]
        benefit_emb = compute_embeddings(model, benefit_names)
        try:
            with benefits_cache_file.open("wb") as fh:
                pickle.dump({"emb": benefit_emb, "map": benefits}, fh, protocol=4)
            print("Saved benefits vectors to cache")
        except Exception as e:
            print(f"Warning: Failed to write benefits cache: {e}")

    # Update metadata.json file
    try:
        meta = {
            "model": args.model_name,
            "lightcast_hash": lightcast_hash,
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
    totals_methods: Dict[str, int] = {}

    for job in tqdm(jobs, desc="Normalizing jobs", unit="job"):
        totals["jobs"] += 1
        try:
            rec = normalize_job(
                job,
                skill_names=lightcast_skills,
                skill_emb=lightcast_emb,
                skill_map=lightcast_skill_map,
                benefit_names=[b[1] for b in benefits],
                benefit_emb=benefit_emb,
                benefit_map=benefits,
                model=model,
                threshold=args.threshold,
                top_k=args.top_k,
                disable_llm_rerank=args.disable_llm_rerank,
                llm_delay=args.llm_rerank_delay,
                llm_max_retries=args.llm_rerank_max_retries,
                llm_batch_size=args.llm_batch_size,
                keyword_index=None,
            )
            rec["normalized_skills_debug"] = list(rec.get("normalized_skills", []))
            rec = remove_unmapped_items(rec)

            ss_debug = rec.get("normalized_skills_debug", [])
            for s in ss_debug:
                method = s.get("method") or "unknown"
                totals_methods[method] = totals_methods.get(method, 0) + 1
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

    atomic_write(args.output, normalized_out)
    print(f"Wrote normalized output to: {args.output}")
    if fallback_out:
        atomic_write(args.fallback, fallback_out)
        print(f"Wrote fallback records to: {args.fallback}")

    print("")
    print(f"Total jobs processed: {totals['jobs']}")
    print(f"Total skills mapped: {totals['skills_mapped']}")
    print(f"Total skills unmatched: {totals['skills_unmatched']}")
    print(f"Total benefits mapped: {totals['benefits_mapped']}")
    print(f"Total benefits unmatched: {totals['benefits_unmatched']}")
    print("")
    print("Method counts:")
    for method, cnt in sorted(totals_methods.items(), key=lambda x: -x[1]):
        print(f"  {method}: {cnt}")

    if normalized_out:
        sample = normalized_out[0]
        print("\nSample normalized (first job):")
        try:
            print(json.dumps({
                "normalized_skills": sample.get("normalized_skills"),
                "normalized_benefits": sample.get("normalized_benefits"),
            }, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:
            print(json.dumps({
                "normalized_skills": sample.get("normalized_skills"),
                "normalized_benefits": sample.get("normalized_benefits"),
            }, ensure_ascii=True, indent=2))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
