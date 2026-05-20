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
import csv
import re

import math
try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    raise RuntimeError("Please install sentence-transformers: pip install sentence-transformers") from e
try:
    from sentence_transformers import CrossEncoder
except Exception:
    CrossEncoder = None

import numpy as np
from sqlalchemy import create_engine, text
from tqdm import tqdm
import hashlib
import pickle
import json as _json
import time

# Ensure project root is on sys.path so `from Db...` imports work
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = None

for parent in THIS_FILE.parents:
    if (parent / "Db").exists():
        PROJECT_ROOT = parent
        break

if PROJECT_ROOT and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from Db.llm.debug_llm_adapter import call_llm
from Db.llm import llm_config
from Db.input import config_api

# Bảng ánh xạ cứng để bảo vệ các kỹ năng quan trọng
CORE_ALIASES = {
    "sql": "SQL (Programming Language)",
    "python": "Python (Programming Language)",
    "java": "Java (Programming Language)",
    "scrum": "Scrum (Software Development)"
}


    
def is_independent_word(query, candidate):
    """Kiểm tra query có đứng độc lập trong candidate không (tránh SQL trong U-SQL)"""
    import re
    pattern = rf"\b{re.escape(query)}\b"
    return bool(re.search(pattern, candidate, re.IGNORECASE))
def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".env").exists() or (parent / "run_etl_pipeline.py").exists():
            return parent
    return Path(__file__).resolve().parents[3]

BASE_DIR = find_project_root()

# Load environment configuration (optional .env in project root)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    # dotenv not installed or file missing; fall back to os.environ
    pass

# Normalization thresholds from environment with defaults
KW_EXACT_CONFIDENCE = float(os.getenv("KW_EXACT_CONFIDENCE", "1.0"))
# More conservative / safer defaults for matching
# Accept strong bi-encoder matches (>= 0.75) immediately to avoid
# relying on cross-encoder raw logits which can be negative.
BI_AUTO_ACCEPT_THRESHOLD = float(os.getenv("BI_AUTO_ACCEPT_THRESHOLD", "0.75"))
# Lower minimum similarity to consider candidates
BI_MIN_SIMILARITY = float(os.getenv("BI_MIN_SIMILARITY", "0.45"))
# Cross-encoder raw logits (ms-marco) are unbounded; use 0.0 as accept threshold
# and apply sigmoid to convert raw logits -> probability in (0,1) before decisions.
CE_AUTO_ACCEPT_THRESHOLD = float(os.getenv("CE_AUTO_ACCEPT_THRESHOLD", "0.10"))
CE_NEED_REVIEW_THRESHOLD = float(os.getenv("CE_NEED_REVIEW_THRESHOLD", "0.55"))
# Domain boost applied after CE score is calculated (added to raw logit before sigmoid)
DOMAIN_BOOST_SCORE = float(os.getenv("DOMAIN_BOOST_SCORE", "0.10"))

# Initialize CrossEncoder globally for cross-encoder stage (best-effort)
cross_encoder = None
if CrossEncoder is not None:
    try:
        cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        print("Loaded CrossEncoder: cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception as e:
        print(f"[WARN] failed to load CrossEncoder: {e}")
        cross_encoder = None


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

def normalize_skill_key(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"\([^)]*\)", "", text)  # Docker (Software) -> Docker
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_prompt_template(filename: str) -> str:
    prompt_path = BASE_DIR / "pipeline" / "normalize" / "2_1_normalized_data" / filename
    return prompt_path.read_text(encoding="utf-8")



def llm_rerank_job_skills(job_title: str, skill_items: List[Dict[str, Any]], delay_seconds: int = 0, max_retries: int = 0):
    """Batch LLM rerank for all skills in a job. Returns mappings list or None on failure.

    Uses existing call_llm and config_api.get_api_key/on_api_quota_error.
    Does not implement SDK retry loop; single call only (per requirements).
    """
    try:
        # Try to get API key; if none, optionally wait once (delay_seconds) then retry once
        api_key = config_api.get_api_key("gemini")
        if not api_key:
            print("[LLM_KEY] no key available")
            if delay_seconds and delay_seconds > 0:
                time.sleep(delay_seconds)
                api_key = config_api.get_api_key("gemini")
            if not api_key:
                return None

        # Build prompt
        skills_json = json.dumps(skill_items, ensure_ascii=False, indent=2)
        prompt = (
            "You are a skill normalization verifier.\n\n"
            "Job title:\n" f"{job_title}\n\n"

            "For each skill, choose the candidate that has EXACT SAME meaning.\n\n"

            "Rules:\n"
            "- You MUST return mapping for EVERY skill.\n"
            "- Always include raw_skill in output.\n"
            "- If a correct candidate exists, DO NOT return NO_MATCH.\n"
            "- Prefer general/base technology over specific tools.\n"

            "Examples:\n"
            "- Docker → Docker (Software)\n"
            "- Python → Python (Programming Language)\n"
            "- Node.js → Node.js (JavaScript Runtime)\n"
            "- React → React (JavaScript Library)\n\n"

            "Input:\n"
            f"{skills_json}\n\n"

            "Return JSON only:\n"
            "{\n"
            "  \"mappings\": [\n"
            "    {\n"
            "      \"raw_skill\": \"Docker\",\n"
            "      \"selected_candidate\": \"Docker (Software)\",\n"
            "      \"confidence\": 0.95,\n"
            "      \"match_type\": \"EXACT\",\n"
            "      \"reason\": \"Docker general technology\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        text = None
        attempts = max(1, int(max_retries or 0) + 1)

        for attempt in range(attempts):
            api_key = config_api.get_api_key("gemini")

            if not api_key:
                print("[LLM_KEY] no key available")
                if attempt < attempts - 1 and delay_seconds > 0:
                    print(f"[LLM_RETRY] no key, wait={delay_seconds}s")
                    time.sleep(delay_seconds)
                    continue
                return None

            try:
                text = call_llm(
                    prompt,
                    api_key,
                    timeout_seconds=llm_config.LLM_CALL_TIMEOUT_SECONDS
                )

                if text:
                    break

            except Exception as e:
                msg = str(e).lower()

                if "quota" in msg or "rate" in msg or "429" in msg or "limit" in msg:
                    try:
                        config_api.on_api_quota_error("gemini")
                    except Exception:
                        pass

                if attempt < attempts - 1 and delay_seconds > 0:
                    print(f"[LLM_RETRY] attempt={attempt+1}/{attempts}, wait={delay_seconds}s")
                    time.sleep(delay_seconds)
                    continue

                return None

        if not text:
            return None

        try:
            j = json.loads(text)
        except Exception:
            # try extract JSON
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    j = json.loads(text[start:end+1])
                except Exception:
                    return None
            else:
                return None

        mappings = j.get("mappings")
        if not isinstance(mappings, list):
            return None
        return mappings
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "rate" in msg or "429" in msg or "limit" in msg:
            try:
                config_api.on_api_quota_error("gemini")
            except Exception:
                pass
        return None

def find_best_evidence(raw_skill: str, requirements_text: str) -> str | None:
    """Find a short evidence sentence/line containing raw_skill.
    Never return the full requirements_text.
    """
    import re

    if not raw_skill or not requirements_text:
        return None

    text = str(requirements_text)
    skill = str(raw_skill).strip()
    if not skill:
        return None

    # Split by common JD separators
    parts = re.split(r"[\n\r]+|•|;|\.|\u2022", text)

    # 1) Exact phrase match
    pattern = re.compile(rf"(?<![\w+#.-]){re.escape(skill)}(?![\w+#.-])", re.IGNORECASE)
    for part in parts:
        sentence = re.sub(r"\s+", " ", part).strip()
        if not sentence:
            continue
        if pattern.search(sentence):
            return sentence[:300]

    # 2) Fallback contains match for special names like Node.js, CI/CD
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
    """Normalize skills for a job using a 3-stage pipeline (keyword, bi-encoder, cross-encoder).

    Produces a list `normalized_skills` matching existing output schema and appends
    an entry for each skill to `normalization_trace.csv` for auditing.
    """
    normalized_skills = []
    normalized_benefits = []
    keyword_index = keyword_index or {}
    skill_id_by_name = {name: sid for sid, name in skill_map}

    # Prepare job fields
    job_title = job.get("title") or job.get("job", {}).get("title") or job.get("raw", {}).get("job_title") or job.get("search_keyword") or ""
    # Normalize job_title to plain string if upstream stores dicts like {"value":..}
    if isinstance(job_title, dict):
        jt = job_title.get("value") or job_title.get("title") or job_title.get("text")
        job_title = str(jt) if jt is not None else str(job_title)
    job_title = (str(job_title) or "").strip()
    job_id = job.get("id") or job.get("job", {}).get("id") or job.get("job_id") or job.get("raw", {}).get("id") or hashlib.sha256(json.dumps(job, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]

    # Helper to safely extract raw skill text from various extracted formats
    def _extract_raw_skill(item: Any) -> tuple[str, str]:
        """Return (raw_skill_str, evidence_text_or_empty).
        Handles nested dicts and multiple key variants.
        """
        raw = None
        evidence = None
        if isinstance(item, dict):
            # Common keys used by upstream extractors
            for k in ("skill_name", "skill_name_eng", "name", "skill", "original", "raw"):
                if k in item and item.get(k) is not None:
                    raw = item.get(k)
                    break
            # If raw is nested dict, try nested name/value
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

    # Gather input skills
    skills_in = job.get("extracted_skills") or []
    skill_entries: List[Dict[str, Any]] = []
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

    # Unique queries to compute embeddings once (preserve order)
    uniq_skill_q = []
    seen = set()
    for e in skill_entries:
        q = e.get("raw") or ""
        if q and q not in seen:
            seen.add(q)
            uniq_skill_q.append(q)

    # Gather benefits (dedupe, preserve order)
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

    # Prepare trace CSV
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

    # Helper: simple domain-match heuristic
    def domain_match(candidate: str, title: str, evidence: str) -> bool:
        c = candidate.lower()
        t = (title or "").lower()
        e = (evidence or "").lower()
        # token-based heuristic: if main candidate token appears in title or evidence
        tokens = re.split(r"\W+", c)
        tokens = [tk for tk in tokens if tk]
        for tk in tokens:
            if tk and (tk in t or tk in e):
                return True
        return False

    if uniq_skill_q:
        q_emb = compute_embeddings(model, uniq_skill_q)
        sims = np.dot(q_emb, skill_emb.T) if skill_emb.shape[0] > 0 else np.zeros((q_emb.shape[0], 0))

        for i, q in enumerate(uniq_skill_q):
            evidence = next((entry.get("evidence") for entry in skill_entries if entry.get("raw") == q), "")
            stage = "start"
            final_method = None
            final_score = 0.0
            mapped_name = None
            mapped_id = None
            status = "unmatched"

            # Stage 1: Keyword exact
            keyword_key = normalize_skill_key(q)
            if keyword_key in keyword_index and is_independent_word(q, keyword_index[keyword_key]):
                canonical = keyword_index[keyword_key]
                sid = skill_id_by_name.get(canonical)
                if sid:
                    stage = "keyword_exact"
                    final_method = "keyword_exact"
                    final_score = KW_EXACT_CONFIDENCE
                    mapped_name = canonical
                    mapped_id = sid
                    status = "auto_accepted"
                    # write normalized and trace
                    normalized_skills.append({
                        "original": q,
                        "mapped_name": mapped_name,
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
                            writer.writerow([job_id, q, job_title, evidence, stage, final_method, round(final_score, 4), mapped_name or "", status])
                    except Exception:
                        pass
                    continue

            # Stage 2: Bi-encoder similarity
            if sims.shape[1] == 0:
                top_score = 0.0
                top_idx = -1
            else:
                top_idx = int(np.argmax(sims[i]))
                top_score = float(sims[i, top_idx])

            if top_score >= BI_AUTO_ACCEPT_THRESHOLD:
                mapped_name = skill_map[top_idx][1]
                mapped_id = skill_map[top_idx][0]
                final_method = "bi_encoder_auto"
                final_score = top_score
                status = "auto_accepted"
                stage = "bi_encoder"
                normalized_skills.append({
                    "original": q,
                    "mapped_name": mapped_name,
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
                        writer.writerow([job_id, q, job_title, evidence, stage, final_method, round(final_score, 4), mapped_name or "", status])
                except Exception:
                    pass
                continue

            # If top score below minimum similarity -> unmatched
            if top_score < BI_MIN_SIMILARITY:
                stage = "bi_encoder"
                final_method = "no_candidate"
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
                continue

            # Stage 2 continued: keep top-K candidates for CE
            # get top_k indices sorted desc
            if sims.shape[1] == 0:
                top_indices = []
            else:
                top_indices = [int(x) for x in np.argsort(sims[i])[-top_k:][::-1]]
            candidates = []
            for rank, idx in enumerate(top_indices, start=1):
                c_sim = float(sims[i, idx])
                sid, sname = skill_map[idx]
                candidates.append({"skill_id": sid, "name": sname, "embedding_score": round(c_sim, 6), "rank": rank})

            # Stage 3: Cross-encoder ranking among candidates
            stage = "cross_encoder"
            if cross_encoder is None:
                # fallback: pick top embedding candidate as need_review
                best = candidates[0] if candidates else None
                if best:
                    mapped_name = best.get("name")
                    mapped_id = best.get("skill_id")
                    final_score = float(best.get("embedding_score") or 0.0)
                    final_method = "ce_fallback_top_embedding"
                    status = "need_review"
                else:
                    final_method = "no_candidate"
                    final_score = 0.0
                    status = "unmatched"
            else:
                # Build input pairs for cross-encoder
                inputA = f"Job Title: {job_title}. Context: {evidence}"
                pairs = [(inputA, c["name"]) for c in candidates]
                try:
                    ce_scores = cross_encoder.predict(pairs)
                except Exception:
                    ce_scores = [0.0] * len(candidates)
                # CE scoring: support sigmoid normalization while preserving
                # the option to compare raw logits when CE_AUTO_ACCEPT_THRESHOLD <= 0.0
                def _sigmoid(x: float) -> float:
                    try:
                        return 1.0 / (1.0 + math.exp(-float(x)))
                    except Exception:
                        return 0.0

                # detect if job title looks like an engineering role for traffic disambiguation
                title_is_it = bool(re.search(r"\b(engineer|backend|developer)\b", job_title or "", re.IGNORECASE))

                raw_scores = []
                probs = []
                for idx_c, c in enumerate(candidates):
                    base = float(ce_scores[idx_c]) if idx_c < len(ce_scores) else 0.0
                    # domain boost applies after CE raw score calculation
                    boost = DOMAIN_BOOST_SCORE if domain_match(c.get("name"), job_title, evidence) else 0.0
                    # disambiguation: penalize candidates that mention traffic/transport for IT roles
                    cname = (c.get("name") or "").lower()
                    if title_is_it and ("traffic" in cname or "transport" in cname or "traffic operations" in cname):
                        boost -= DOMAIN_BOOST_SCORE * 1.5

                    raw = base + boost
                    prob = _sigmoid(raw)
                    raw_scores.append(raw)
                    probs.append(prob)

                # Choose best candidate by probability
                if probs:
                    best_i = int(np.argmax(probs))
                    best_raw = float(raw_scores[best_i])
                    best_prob = float(probs[best_i])
                    best_c = candidates[best_i]
                    mapped_name = best_c.get("name")
                    mapped_id = best_c.get("skill_id")

                    # Decision logic: if CE_AUTO_ACCEPT_THRESHOLD <= 0, interpret as raw-logit threshold
                    if CE_AUTO_ACCEPT_THRESHOLD <= 0.0:
                        # use raw logits for accept/need_review decisions
                        if best_raw >= CE_AUTO_ACCEPT_THRESHOLD:
                            status = "auto_accepted"
                            final_method = "ce_auto"
                        elif best_raw >= CE_NEED_REVIEW_THRESHOLD:
                            status = "need_review"
                            final_method = "ce_need_review"
                        else:
                            status = "unmatched"
                            final_method = "ce_unmatched"
                    else:
                        # use sigmoid probability for decision
                        if best_prob >= CE_AUTO_ACCEPT_THRESHOLD:
                            status = "auto_accepted"
                            final_method = "ce_auto"
                        elif best_prob >= CE_NEED_REVIEW_THRESHOLD:
                            status = "need_review"
                            final_method = "ce_need_review"
                        else:
                            status = "unmatched"
                            final_method = "ce_unmatched"

                    # Store confidence as sigmoid probability for easier interpretation
                    final_score = best_prob
                else:
                    final_method = "ce_no_candidates"
                    final_score = 0.0
                    status = "unmatched"

            normalized_skills.append({
                "original": q,
                "mapped_name": mapped_name,
                "skill_id": mapped_id,
                "confidence": round(final_score, 4),
                "status": status,
                "method": final_method,
                "evidence": evidence,
                "candidates": candidates,
            })

            # Append trace row
            try:
                with trace_path.open("a", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow([job_id, q, job_title, evidence, stage, final_method, round(final_score, 4), mapped_name or "", status])
            except Exception:
                pass

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
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--disable-llm-rerank", action="store_true", default=False)
    parser.add_argument("--llm-rerank-delay", type=int, default=15)
    parser.add_argument("--llm-rerank-max-retries", type=int, default=2)
    parser.add_argument("--llm-batch-size", type=int, default=10)
       
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
    # Log total counts for comparison with previous normalizer library
    try:
        print(f"Total skills/keywords loaded from DB: {len(skill_map)}")
        print(f"Total benefits loaded from DB: {len(benefit_map)}")
    except Exception:
        # defensive: do not fail startup for logging issues
        print("Total skills/benefits: (count unavailable)")
    # Lightweight specialized_skill breakdown using `category` as sub-category
    try:
        engine = create_engine(args.db_url)
        with engine.connect() as conn:
            # match type case-insensitively and allow variants like 'Specialized Skill'
            q = text(
                f"SELECT COALESCE(category, '') AS category, COUNT(*) AS cnt"
                f" FROM {args.skill_table} WHERE lower(COALESCE(type, '')) LIKE 'specialized%' GROUP BY COALESCE(category, '') ORDER BY cnt DESC"
            )
            res = conn.execute(q)
            rows = res.fetchall()
            if rows:
                print("specialized_skill breakdown by category:")
                for r in rows:
                    sub = r[0] or "[unknown]"
                    cnt = int(r[1])
                    print(f"specialized_skill [{sub}]: {cnt} skills")
            else:
                print("specialized_skill breakdown: no rows found")
    except Exception as e:
        # Do not fail startup for stats; log and continue
        print(f"[STATS_WARN] failed to compute specialized_skill breakdown: {e}")
    keyword_index = {
        normalize_skill_key(name): name
        for _, name in skill_map
        if normalize_skill_key(name)
    }
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
    # method-level counters for final summary
    totals_methods: Dict[str, int] = {}

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
                top_k=args.top_k,
                disable_llm_rerank=args.disable_llm_rerank,
                llm_delay=args.llm_rerank_delay,
                llm_max_retries=args.llm_rerank_max_retries,
                llm_batch_size=args.llm_batch_size,
                keyword_index=keyword_index,
            )
            # preserve full normalized skills for debugging/review before trimming
            rec["normalized_skills_debug"] = list(rec.get("normalized_skills", []))
            rec = remove_unmapped_items(rec)
            # update counts from debug view (before trimming)
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
    print("")
    print("Method counts:")
    for method, cnt in sorted(totals_methods.items(), key=lambda x: -x[1]):
        print(f"  {method}: {cnt}")

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
