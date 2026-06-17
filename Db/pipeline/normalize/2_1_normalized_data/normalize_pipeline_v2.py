#!/usr/bin/env python3
"""Normalize extracted skills and benefits using SentenceTransformer embeddings against Lightcast taxonomy.

Upgraded to Normalize Pipeline v2:
- Integrates 4-stage Hybrid Matching (Curated Aliases, Advanced Exact Match, FAISS Hybrid Search with Context & Type Resolution, Dynamic Thresholds, and Taxonomy Boosting).
- Retains 100% backward compatibility for function signatures, inputs, and outputs.
- Thread-safe lazy initialization for FAISS indices.
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
import threading

# Configure stdout and stderr to use UTF-8, avoiding UnicodeEncodeError on Windows console
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    raise RuntimeError("Please install sentence-transformers: pip install sentence-transformers") from e

import numpy as np
import faiss
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


# ==========================================
# CURATED ALIASES DICTIONARY - METHOD 6 OPTIMIZED
# ==========================================
CURATED_ALIASES_EXTENDED = {
    # Original 33 aliases
    'FastAPI': 'FastAPI',
    'RESTful APIs': 'RESTful API',
    'Prompt Engineering': 'Prompt Engineering',
    'System design': 'Systems Design',
    'OOP': 'Object-Oriented Programming (OOP)',
    'Indexing': 'Database Indexes',
    'JavaScript': 'JavaScript (Programming Language)',
    'TypeScript': 'TypeScript',
    'Python 3': 'Python (Programming Language)',
    'Python3': 'Python (Programming Language)',
    'Py': 'Python (Programming Language)',
    'C#': 'C# (Programming Language)',
    'C Sharp': 'C# (Programming Language)',
    'C++': 'C++ (Programming Language)',
    'CPP': 'C++ (Programming Language)',
    'VB.NET': 'Visual Basic .NET (Programming Language)',
    'MySQL DB': 'MySQL',
    'Postgres': 'PostgreSQL',
    'Postgre SQL': 'PostgreSQL',
    'Mongo': 'MongoDB',
    'Redis Cache': 'Redis',
    'Elasticsearch Engine': 'Elasticsearch',
    'AWS': 'Amazon Web Services',
    'Azure': 'Microsoft Azure',
    'GCP': 'Google Cloud Platform (GCP)',
    'Cloud Services': 'Cloud Computing',
    'REST': 'RESTful API',
    'GraphQL API': 'GraphQL',
    'SOAP': 'Simple Object Access Protocol (SOAP)',
    'Web Services': 'Web Services',
    'Spring': 'Spring Boot',
    'Express.js': 'Express.js (Javascript Library)',
    'Express': 'Express.js (Javascript Library)',
    
    # Extended 16 aliases for problematic terms
    'Oracle Database': 'Oracle Databases',
    'Oracle DB': 'Oracle Databases',
    'Cloud Computing': 'Cloud Infrastructure',
    'Cloud Services': 'Cloud Infrastructure',
    'Source Code': 'Version Control',
    'SCM': 'Version Control',
    'Web Server': 'Web Services',
    'Memory Management': 'Memory Management',
    'Memory Layout': 'Memory Management',
    
    # Acronym & Domain Guardrail Mappings (No certifications)
    'WAF': 'Firewall',
    'MS Team': 'Virtual Teams',
    'MS Teams': 'Virtual Teams',
    'PowerBI': 'Microsoft Power Platform',
    'Power BI': 'Microsoft Power Platform',
    'Snowflake Schema': 'Database Design',
    'Source Code Management': 'Version Control',
    'CI/CD Pipelines': 'CI/CD',
    'Independent Work': 'Independent Thinking',
    'CSS': 'Cascading Style Sheets (CSS)',
    'CSS3': 'Cascading Style Sheets (CSS)',
    'SaaS': 'Software As A Service (SaaS)',
    'SIEM': 'Security Information And Event Management (SIEM)',
    'System Integration': 'Systems Design',
    'System Integration Services': 'Systems Design',
    'Big Data': 'AWS Big Data',
    'System Thinking': 'Systems Design',
}

# ==========================================
# GLOBAL RESOURCES FOR NORMALIZATION
# ==========================================
GLOBAL_BASE_FAISS_INDEX = None
GLOBAL_MAIN_FAISS_INDEX = None
GLOBAL_LIGHTCAST_METADATA = {}  # Store subcategory and type
GLOBAL_EXACT_MATCH_DICT = {}
GLOBAL_TAXONOMY_LOOKUP = {}
GLOBAL_TAXONOMY_ALIASES = {}
GLOBAL_LABELED_SKILL_TYPES = {}

# Thread-safety lock for lazy resource initialization
GLOBAL_INIT_LOCK = threading.Lock()


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


def load_skills_metadata_from_db(db_url: str, table: str) -> List[Tuple[int, str, str, str]]:
    if not db_url:
        return []
    if '?' in db_url:
        db_url = db_url.split('?')[0]
        
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            # Check what columns exist in the table
            q_cols = text(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")
            cols = [r[0] for r in conn.execute(q_cols).fetchall()]
            
            id_col = "skill_id" if "skill_id" in cols else ("id" if "id" in cols else None)
            name_col = "skill_name" if "skill_name" in cols else ("name" if "name" in cols else None)
            cat_col = "category" if "category" in cols else None
            type_col = "type" if "type" in cols else None
            
            if not id_col or not name_col:
                return []
                
            cols_str = f"{id_col} as id, {name_col} as name"
            if cat_col:
                cols_str += f", {cat_col} as category"
            else:
                cols_str += ", NULL as category"
            if type_col:
                cols_str += f", {type_col} as type"
            else:
                cols_str += ", NULL as type"
                
            q = text(f"SELECT {cols_str} FROM {table}")
            res = conn.execute(q)
            rows = res.fetchall()
            out = []
            for row in rows:
                sid = int(row[0])
                name = str(row[1])
                cat = str(row[2]) if row[2] else "General"
                stype = str(row[3]) if row[3] else "Hard Skill"
                out.append((sid, name, cat, stype))
            return out
    except Exception as e:
        print(f"Warning: Failed to load skills with metadata from DB: {e}")
        return []



def compute_embeddings(model: SentenceTransformer, texts: List[str], batch_size: int = 64) -> np.ndarray:
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=float)
    emb = model.encode(texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    return np.asarray(emb, dtype=float)


def clean_skill_universal(raw_skill: str) -> str:
    """Universal cleaning function standardizing abbreviations & framework names."""
    s = str(raw_skill).strip()
    s = re.sub(r'(?i)\b([a-zA-Z0-9]+)js\b', r'\1.js', s)
    s = re.sub(r'(?i)\brestful apis?\b', 'RESTful API', s)
    s = re.sub(r'(?i)\b\.net\b', '.NET Framework', s)
    s = re.sub(r'(?i)\bcss3\b', 'CSS', s)
    s = re.sub(r'(?i)\b(ms\s*sql|sql\s*server)\b', 'Microsoft SQL Servers', s)
    s = re.sub(r'(?i)\bms teams?\b', 'MS Teams', s)
    return s


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


def get_char_ngram_similarity(s1: str, s2: str, n: int = 3) -> float:
    """Jaccard character n-gram similarity to penalize mismatching contexts."""
    s1 = re.sub(r'[^a-z0-9]', '', s1.lower())
    s2 = re.sub(r'[^a-z0-9]', '', s2.lower())
    if not s1 or not s2:
        return 0.0
    if len(s1) < n or len(s2) < n:
        set1 = set(s1)
        set2 = set(s2)
    else:
        set1 = set(s1[i:i+n] for i in range(len(s1)-n+1))
        set2 = set(s2[i:i+n] for i in range(len(s2)-n+1))
        
    union = set1.union(set2)
    if not union:
        return 0.0
    return len(set1.intersection(set2)) / len(union)


def get_suggested_subcategory_v2(raw_skill_str: str, model: SentenceTransformer, skill_names: List[str]) -> str | None:
    """Query Base FAISS index to find standard subcategory for a raw skill."""
    global GLOBAL_BASE_FAISS_INDEX, GLOBAL_LIGHTCAST_METADATA
    if GLOBAL_BASE_FAISS_INDEX is not None:
        try:
            query_vector = model.encode([raw_skill_str], convert_to_numpy=True).astype('float32')
            faiss.normalize_L2(query_vector)
            scores, indices = GLOBAL_BASE_FAISS_INDEX.search(query_vector, 1)
            top_idx = int(indices[0][0])
            if top_idx != -1 and top_idx < len(skill_names):
                name = skill_names[top_idx]
                meta = GLOBAL_LIGHTCAST_METADATA.get(name, {})
                return meta.get("subcategory")
        except Exception:
            pass
    return None


def resolve_skill_type_v2(raw_skill: str, labeled_skill_types: Dict[str, str], model: SentenceTransformer, skill_names: List[str]) -> str:
    """Determine if a skill is common_skill or hard_skill using pre-labeled mapping or FAISS lookup."""
    global GLOBAL_BASE_FAISS_INDEX, GLOBAL_LIGHTCAST_METADATA
    raw_skill_str = str(raw_skill).strip()
    
    # Check pre-labeled
    if raw_skill_str in labeled_skill_types:
        labeled_type = labeled_skill_types[raw_skill_str]
        if 'common' in labeled_type.lower():
            return 'common_skill'
        else:
            return 'hard_skill'
            
    # FAISS-based lookup fallback
    if GLOBAL_BASE_FAISS_INDEX is not None:
        try:
            query_vector = model.encode([raw_skill_str], convert_to_numpy=True).astype('float32')
            faiss.normalize_L2(query_vector)
            scores, indices = GLOBAL_BASE_FAISS_INDEX.search(query_vector, 1)
            top_idx = int(indices[0][0])
            if top_idx != -1 and top_idx < len(skill_names):
                name = skill_names[top_idx]
                meta = GLOBAL_LIGHTCAST_METADATA.get(name, {})
                db_skill_type = meta.get("type", "Hard Skill")
                if db_skill_type.lower() in ('common skill', 'common_skill'):
                    return 'common_skill'
        except Exception:
            pass
            
    return 'hard_skill'


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


def init_global_resources(
    skill_names: List[str],
    skill_emb: np.ndarray,
    skill_map: List[Tuple[int, str]],
    model: SentenceTransformer
) -> None:
    """Initialize FAISS indexes, Exact Match dictionary, and Taxonomy lookup globally once (thread-safe)."""
    global GLOBAL_BASE_FAISS_INDEX, GLOBAL_MAIN_FAISS_INDEX, GLOBAL_LIGHTCAST_METADATA
    global GLOBAL_EXACT_MATCH_DICT, GLOBAL_TAXONOMY_LOOKUP, GLOBAL_TAXONOMY_ALIASES
    
    if GLOBAL_BASE_FAISS_INDEX is not None and GLOBAL_MAIN_FAISS_INDEX is not None:
        return

    with GLOBAL_INIT_LOCK:
        # Double-checked locking
        if GLOBAL_BASE_FAISS_INDEX is not None and GLOBAL_MAIN_FAISS_INDEX is not None:
            return

        script_dir = Path(__file__).resolve().parent
        # 1. Load Lightcast CSV to recover subcategory & type metadata (if not already populated from DB)
        if not GLOBAL_LIGHTCAST_METADATA:
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

            lightcast_metadata = {}
            if lightcast_csv:
                try:
                    with open(lightcast_csv, mode="r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if not row or len(row) < 5:
                                continue
                            name = row[1].strip()
                            subcat = row[2].strip()
                            skill_type = row[4].strip()
                            lightcast_metadata[name] = {
                                "subcategory": subcat,
                                "type": skill_type
                            }
                except Exception as e:
                    print(f"Warning: Failed to load Lightcast CSV metadata: {e}")

            for sid, name in skill_map:
                if name not in lightcast_metadata:
                    lightcast_metadata[name] = {
                        "subcategory": "General",
                        "type": "Hard Skill"
                    }
            GLOBAL_LIGHTCAST_METADATA = lightcast_metadata

        # 2. Build Exact match dictionary
        exact_match_dict = {}
        for name in skill_names:
            orig_name_lower = name.lower()
            exact_match_dict[orig_name_lower] = name
            
            simplified = re.sub(r'\s*\(.*\)', '', name).strip()
            simplified_lower = simplified.lower()
            if simplified_lower not in exact_match_dict:
                exact_match_dict[simplified_lower] = name
        GLOBAL_EXACT_MATCH_DICT = exact_match_dict

        # 3. Base FAISS Index
        if skill_emb.shape[0] > 0:
            v_base = skill_emb.astype('float32')
            v_base_norm = v_base.copy()
            faiss.normalize_L2(v_base_norm)
            
            base_index = faiss.IndexFlatIP(v_base_norm.shape[1])
            base_index.add(v_base_norm)
            GLOBAL_BASE_FAISS_INDEX = base_index

        # 4. Main FAISS Index (Contextual Embeddings)
        cache_dir = script_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        main_cache_file = cache_dir / "lightcast_main_embeddings_v2.pkl"
        metadata_file = cache_dir / "metadata_v2.json"

        main_texts = []
        for name in skill_names:
            meta = GLOBAL_LIGHTCAST_METADATA.get(name, {"subcategory": "General", "type": "Hard Skill"})
            subcat = meta["subcategory"]
            skill_type = meta["type"]
            
            if skill_type.lower() in ('common skill', 'common_skill'):
                main_texts.append(name)
            else:
                main_texts.append(f"{name} | Context: {subcat}")

        def _hash_list(obj: List[Any]) -> str:
            return hashlib.sha256(_json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

        main_texts_hash = _hash_list(main_texts)
        model_name = getattr(model, "model_name_or_path", "all-MiniLM-L6-v2")
        if model_name and "/" in model_name:
            model_name = model_name.split("/")[-1]

        need_recompute_main = True
        main_emb = None

        metadata = None
        if metadata_file.exists():
            try:
                with metadata_file.open("r", encoding="utf-8") as fh:
                    metadata = json.load(fh)
            except Exception:
                metadata = None

        if metadata and metadata.get("model") == model_name:
            if metadata.get("main_texts_hash") == main_texts_hash and main_cache_file.exists():
                try:
                    with main_cache_file.open("rb") as fh:
                        main_cache = pickle.load(fh)
                    main_emb = main_cache.get("emb")
                    if main_emb is not None:
                        main_emb = np.asarray(main_emb, dtype=float)
                        need_recompute_main = False
                except Exception:
                    need_recompute_main = True

        if need_recompute_main:
            print(f"Computing contextual embeddings for {len(main_texts)} Main FAISS items...")
            main_emb = compute_embeddings(model, main_texts)
            try:
                with main_cache_file.open("wb") as fh:
                    pickle.dump({"emb": main_emb, "texts": main_texts}, fh, protocol=4)
                
                meta = {
                    "model": model_name,
                    "main_texts_hash": main_texts_hash,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                with metadata_file.open("w", encoding="utf-8") as fh:
                    json.dump(meta, fh, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Warning: Failed to save Main cache: {e}")

        if main_emb is not None and main_emb.shape[0] > 0:
            v_main = main_emb.astype('float32')
            v_main_norm = v_main.copy()
            faiss.normalize_L2(v_main_norm)
            
            main_index = faiss.IndexFlatIP(v_main_norm.shape[1])
            main_index.add(v_main_norm)
            GLOBAL_MAIN_FAISS_INDEX = main_index

        # 5. Load taxonomy
        taxonomy_path = script_dir / 'taxonomy.json'
        if taxonomy_path.exists():
            try:
                with open(taxonomy_path, 'r', encoding='utf-8') as f:
                    taxonomy = json.load(f)
                for cat in taxonomy.get('categories', {}).values():
                    for subcat in cat.get('subcategories', {}).values():
                        for skill in subcat.get('skills', []):
                            canonical = skill['canonical_name']
                            GLOBAL_TAXONOMY_LOOKUP[canonical.lower()] = canonical
                            for alias in skill.get('aliases', []):
                                GLOBAL_TAXONOMY_ALIASES[alias.lower()] = canonical
            except Exception as e:
                print(f"Warning: Failed to load taxonomy.json: {e}")


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
    mapping_cache: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Normalize job skills using string cleaning + 4-stage hybrid matching, and semantic matching with all-MiniLM-L6-v2."""
    import sentence_transformers
    lib_ver = sentence_transformers.__version__
    model_name = getattr(model, "model_name_or_path", "all-MiniLM-L6-v2") if model is not None else "all-MiniLM-L6-v2"
    if model_name and "/" in model_name:
        model_name = model_name.split("/")[-1]

    # Lazy-initialize global FAISS and metadata resources (thread-safe)
    init_global_resources(skill_names, skill_emb, skill_map, model)

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
    raw_desc = job.get("raw")
    raw_req = raw_desc.get("requirements_text") if isinstance(raw_desc, dict) else None
    job_desc = job.get("job")
    skills_desc = job_desc.get("skills_desc") if isinstance(job_desc, dict) else None
    if isinstance(skills_desc, dict):
        skills_desc = skills_desc.get("value")
    requirements_text = raw_req or job.get("requirements_text") or skills_desc or ""

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

    # Normalization loop
    if uniq_skill_q:
        if mapping_cache is None:
            mapping_cache = {}

        # Separate cache hits and cache misses
        to_process_skills = []
        for q in uniq_skill_q:
            evidence = next((entry.get("evidence") for entry in skill_entries if entry.get("raw") == q), "")
            if q in mapping_cache:
                cached = mapping_cache[q]
                mapped_name = cached.get("mapped_name")
                mapped_id = cached.get("skill_id")
                confidence = cached.get("confidence", 0.0)
                status = cached.get("status", "unmatched")
                method = cached.get("method", "Unmatched")
                reason = cached.get("reason", "embedding")
                
                skill_entry = {
                    "original": q,
                    "mapped_name": mapped_name,
                    "skill_id": mapped_id,
                    "confidence": confidence,
                    "status": status,
                    "method": method,
                    "evidence": evidence,
                    "candidates": [],
                    "reason": reason,
                    "model_name": model_name,
                    "lib_version": lib_ver,
                }
                if status == "unmatched":
                    skill_entry["top_candidate_name"] = cached.get("top_candidate_name")
                    skill_entry["top_candidate_id"] = cached.get("top_candidate_id")
                
                normalized_skills.append(skill_entry)
                
                try:
                    with trace_path.open("a", encoding="utf-8", newline="") as fh:
                        writer = csv.writer(fh)
                        writer.writerow([job_id, q, job_title, evidence, "cache_hit", method, confidence, mapped_name or "", status])
                except Exception:
                    pass
            else:
                to_process_skills.append(q)

        for q in to_process_skills:
            evidence = next((entry.get("evidence") for entry in skill_entries if entry.get("raw") == q), "")
            
            # Stage 0: Universal cleaning
            cleaned_skill = clean_skill_universal(q)
            cleaned_lower = cleaned_skill.lower()

            # --- LAYER 0: Curated Aliases (Deterministic) ---
            if cleaned_skill in CURATED_ALIASES_EXTENDED:
                matched_name = CURATED_ALIASES_EXTENDED[cleaned_skill]
                matched_lower = matched_name.lower()
                if matched_lower in GLOBAL_EXACT_MATCH_DICT:
                    matched_name = GLOBAL_EXACT_MATCH_DICT[matched_lower]
                
                mapped_id = skill_id_by_name.get(matched_name)
                
                normalized_skills.append({
                    "original": q,
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Aliased",
                    "evidence": evidence,
                    "candidates": [],
                    "reason": "exact_match",
                    "model_name": model_name,
                    "lib_version": lib_ver,
                })
                mapping_cache[q] = {
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Aliased",
                    "reason": "exact_match",
                }
                try:
                    with trace_path.open("a", encoding="utf-8", newline="") as fh:
                        writer = csv.writer(fh)
                        writer.writerow([job_id, q, job_title, evidence, "aliased", "Aliased", 1.0, matched_name, "auto_accepted"])
                except Exception:
                    pass
                continue

            # --- LAYER 1: Exact Match ---
            if cleaned_lower in GLOBAL_EXACT_MATCH_DICT:
                matched_name = GLOBAL_EXACT_MATCH_DICT[cleaned_lower]
                mapped_id = skill_id_by_name.get(matched_name)
                
                normalized_skills.append({
                    "original": q,
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Exact Match",
                    "evidence": evidence,
                    "candidates": [],
                    "reason": "exact_match",
                    "model_name": model_name,
                    "lib_version": lib_ver,
                })
                mapping_cache[q] = {
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Exact Match",
                    "reason": "exact_match",
                }
                try:
                    with trace_path.open("a", encoding="utf-8", newline="") as fh:
                        writer = csv.writer(fh)
                        writer.writerow([job_id, q, job_title, evidence, "exact_match", "Exact Match", 1.0, matched_name, "auto_accepted"])
                except Exception:
                    pass
                continue

            raw_simplified = re.sub(r'\s*\(.*\)', '', cleaned_skill).strip().lower()
            if raw_simplified in GLOBAL_EXACT_MATCH_DICT:
                matched_name = GLOBAL_EXACT_MATCH_DICT[raw_simplified]
                mapped_id = skill_id_by_name.get(matched_name)
                
                normalized_skills.append({
                    "original": q,
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Exact Match",
                    "evidence": evidence,
                    "candidates": [],
                    "reason": "exact_match",
                    "model_name": model_name,
                    "lib_version": lib_ver,
                })
                mapping_cache[q] = {
                    "mapped_name": matched_name,
                    "skill_id": mapped_id,
                    "confidence": 1.0,
                    "status": "auto_accepted",
                    "method": "Exact Match",
                    "reason": "exact_match",
                }
                try:
                    with trace_path.open("a", encoding="utf-8", newline="") as fh:
                        writer = csv.writer(fh)
                        writer.writerow([job_id, q, job_title, evidence, "exact_match_simplified", "Exact Match", 1.0, matched_name, "auto_accepted"])
                except Exception:
                    pass
                continue

            # --- LAYER 2: Semantic Match with Hybrid Scoring ---
            # 1. Resolve Skill Type
            skill_class = resolve_skill_type_v2(cleaned_skill, GLOBAL_LABELED_SKILL_TYPES, model, skill_names)
            
            # 2. Build Query
            if skill_class == 'common_skill':
                query = cleaned_skill
            else:
                context_value = None
                if job_title:
                    context_value = job_title
                else:
                    context_value = get_suggested_subcategory_v2(cleaned_skill, model, skill_names)
                    
                if context_value:
                    query = f"{cleaned_skill} | Context: {context_value}"
                else:
                    query = cleaned_skill

            # 3. Query Main FAISS Index (retrieve top 5 candidates)
            best_candidate_idx = -1
            best_candidate_score = -1.0
            
            if GLOBAL_MAIN_FAISS_INDEX is not None:
                query_vector = model.encode([query], convert_to_numpy=True).astype('float32')
                faiss.normalize_L2(query_vector)
                
                scores, indices = GLOBAL_MAIN_FAISS_INDEX.search(query_vector, 5)
                
                # Dynamic Threshold
                word_count = len(cleaned_skill.split())
                char_len = len(cleaned_skill)
                is_acronym = (char_len <= 5 and cleaned_skill.isupper()) or (word_count == 1 and char_len <= 4)
                
                if is_acronym:
                    dynamic_threshold = 0.80
                elif skill_class == 'hard_skill':
                    dynamic_threshold = 0.70 if word_count < 3 else 0.62
                else:
                    dynamic_threshold = 0.60

                for rank in range(5):
                    idx = int(indices[0][rank])
                    if idx == -1 or idx >= len(skill_names):
                        continue
                        
                    dense_score = float(scores[0][rank])
                    candidate_name = skill_names[idx]
                    meta = GLOBAL_LIGHTCAST_METADATA.get(candidate_name, {"type": "Hard Skill"})
                    candidate_type = meta["type"].strip().lower()
                    
                    # Enforce Type Constraint
                    is_type_match = False
                    if skill_class == 'common_skill' and 'common' in candidate_type:
                        is_type_match = True
                    elif skill_class == 'hard_skill' and 'common' not in candidate_type:
                        is_type_match = True
                        
                    type_penalty = 1.0 if is_type_match else 0.85
                    
                    # Sparse character similarity
                    sparse_score = get_char_ngram_similarity(cleaned_skill, candidate_name, n=3)
                    
                    # Combine dense and sparse scores
                    hybrid_score = (0.85 * dense_score + 0.15 * sparse_score) * type_penalty
                    
                    if hybrid_score > best_candidate_score:
                        best_candidate_score = hybrid_score
                        best_candidate_idx = idx

            # --- LAYER 4: Taxonomy Validation & Boost ---
            is_boosted = False
            matched_name = None
            if best_candidate_idx != -1:
                candidate_name = skill_names[best_candidate_idx]
                if cleaned_lower in GLOBAL_TAXONOMY_LOOKUP:
                    canonical = GLOBAL_TAXONOMY_LOOKUP[cleaned_lower]
                    if canonical.lower() == candidate_name.lower():
                        best_candidate_score = 1.0
                        is_boosted = True
                        boost_method = "Taxonomy + Lightcast"
                elif cleaned_lower in GLOBAL_TAXONOMY_ALIASES:
                    canonical = GLOBAL_TAXONOMY_ALIASES[cleaned_lower]
                    if canonical.lower() == candidate_name.lower():
                        best_candidate_score = 1.0
                        is_boosted = True
                        boost_method = "Taxonomy Alias + Lightcast"

            # Determine match status based on threshold / boost
            if best_candidate_idx != -1:
                candidate_name = skill_names[best_candidate_idx]
                mapped_id = skill_id_by_name.get(candidate_name)
                
                if is_boosted or best_candidate_score >= dynamic_threshold:
                    method_str = boost_method if is_boosted else "Semantic (above threshold)"
                    status_str = "auto_accepted"
                    
                    normalized_skills.append({
                        "original": q,
                        "mapped_name": candidate_name,
                        "skill_id": mapped_id,
                        "confidence": round(best_candidate_score, 4),
                        "status": status_str,
                        "method": method_str,
                        "evidence": evidence,
                        "candidates": [],
                        "reason": "taxonomy_validated" if is_boosted else "embedding",
                        "model_name": model_name,
                        "lib_version": lib_ver,
                    })
                    mapping_cache[q] = {
                        "mapped_name": candidate_name,
                        "skill_id": mapped_id,
                        "confidence": round(best_candidate_score, 4),
                        "status": status_str,
                        "method": method_str,
                        "reason": "taxonomy_validated" if is_boosted else "embedding",
                    }
                    try:
                        with trace_path.open("a", encoding="utf-8", newline="") as fh:
                            writer = csv.writer(fh)
                            writer.writerow([job_id, q, job_title, evidence, "semantic", method_str, round(best_candidate_score, 4), candidate_name, status_str])
                    except Exception:
                        pass
                else:
                    # Unmatched
                    normalized_skills.append({
                        "original": q,
                        "mapped_name": None,
                        "skill_id": None,
                        "confidence": round(best_candidate_score, 4),
                        "status": "unmatched",
                        "method": "Unmatched",
                        "evidence": evidence,
                        "candidates": [],
                        "reason": "embedding",
                        "model_name": model_name,
                        "lib_version": lib_ver,
                        "top_candidate_name": candidate_name,
                        "top_candidate_id": mapped_id,
                    })
                    mapping_cache[q] = {
                        "mapped_name": None,
                        "skill_id": None,
                        "confidence": round(best_candidate_score, 4),
                        "status": "unmatched",
                        "method": "Unmatched",
                        "reason": "embedding",
                        "top_candidate_name": candidate_name,
                        "top_candidate_id": mapped_id,
                    }
                    try:
                        with trace_path.open("a", encoding="utf-8", newline="") as fh:
                            writer = csv.writer(fh)
                            writer.writerow([job_id, q, job_title, evidence, "semantic", "Unmatched", round(best_candidate_score, 4), "", "unmatched"])
                    except Exception:
                        pass
            else:
                # Fallback if FAISS indices are empty
                normalized_skills.append({
                    "original": q,
                    "mapped_name": None,
                    "skill_id": None,
                    "confidence": 0.0,
                    "status": "unmatched",
                    "method": "Unmatched",
                    "evidence": evidence,
                    "candidates": [],
                    "reason": "embedding",
                    "model_name": model_name,
                    "lib_version": lib_ver,
                    "top_candidate_name": None,
                    "top_candidate_id": None,
                })
                mapping_cache[q] = {
                    "mapped_name": None,
                    "skill_id": None,
                    "confidence": 0.0,
                    "status": "unmatched",
                    "method": "Unmatched",
                    "reason": "embedding",
                }

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
    """Remove normalized skills/benefits that were not mapped to database identifiers, and store unmatched skills."""
    all_skills = record.get("normalized_skills", [])
    
    record["unmatched_skills"] = [
        item for item in all_skills
        if not (item.get("mapped_name") and item.get("skill_id"))
    ]

    record["normalized_skills"] = [
        item for item in all_skills
        if item.get("mapped_name") and item.get("skill_id")
    ]

    record["normalized_benefits"] = [
        item for item in record.get("normalized_benefits", [])
        if item.get("mapped_name") and item.get("benefit_id")
    ]
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize skills and benefits using sentence embeddings (v2 FAISS Hybrid).")
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

    # Load DB connection credentials
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

    # 1. Load skills with metadata from DB instead of depending on lightcast.csv
    skills_with_meta = load_skills_metadata_from_db(args.db_url, args.skill_table)
    print(f"Total skills with metadata loaded from DB: {len(skills_with_meta)}")
    
    allowed_types = {'Hard Skill', 'Specialized Skill', 'Common skill', 'Common Skill'}
    lightcast_skills = []
    lightcast_metadata = {}
    
    for sid, name, cat, stype in skills_with_meta:
        lightcast_metadata[name] = {
            "subcategory": cat,
            "type": stype
        }
        if stype in allowed_types and name:
            lightcast_skills.append(name)
            
    # Deduplicate while preserving order
    seen = set()
    lightcast_skills_dedup = []
    for s in lightcast_skills:
        if s not in seen:
            seen.add(s)
            lightcast_skills_dedup.append(s)
    lightcast_skills = lightcast_skills_dedup
    print(f"Total allowed skills loaded: {len(lightcast_skills)}")

    # Set the global metadata variable
    global GLOBAL_LIGHTCAST_METADATA
    GLOBAL_LIGHTCAST_METADATA = lightcast_metadata

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

    script_dir = Path(__file__).resolve().parent
    # Configure Pickle cache paths
    cache_dir = script_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lightcast_cache_file = cache_dir / "lightcast_embeddings_minilm.pkl"
    legacy_skills_cache_file = cache_dir / "skills_embedding.pkl"
    benefits_cache_file = cache_dir / "benefits_embedding.pkl"
    metadata_file = cache_dir / "metadata.json"

    # Configure mapping cache path
    skills_cache_path = cache_dir / "mapped_skills_cache.json"
    mapping_cache = {}
    if skills_cache_path.exists():
        try:
            with skills_cache_path.open("r", encoding="utf-8") as fh:
                mapping_cache = json.load(fh)
            print(f"Loaded {len(mapping_cache)} cached skill mappings from {skills_cache_path}")
        except Exception as e:
            print(f"Warning: Failed to load mapped skills cache: {e}")

    # Load pre-labeled skill types if file exists
    global GLOBAL_LABELED_SKILL_TYPES
    labeled_skills_path = script_dir / 'raw_extracted_skills_fixed_type.csv'
    if labeled_skills_path.exists():
        try:
            with open(labeled_skills_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    skill = row.get('Raw Skill', '').strip()
                    skill_type = row.get('Type', '').strip().lower()
                    if skill:
                        GLOBAL_LABELED_SKILL_TYPES[skill] = skill_type
            print(f"Loaded {len(GLOBAL_LABELED_SKILL_TYPES)} pre-labeled skill types from {labeled_skills_path}")
        except Exception as e:
            print(f"Warning: Failed to load pre-labeled types from CSV: {e}")

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

    # Initialize global resources and FAISS indices before loop (thread-safe)
    init_global_resources(lightcast_skills, lightcast_emb, lightcast_skill_map, model)

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

    for job in tqdm(jobs, desc="Normalizing jobs (v2)", unit="job"):
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
                mapping_cache=mapping_cache,
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
            import traceback
            traceback.print_exc()
            fallback_out.append({
                "status": "normalize_fail",
                "error": str(e),
                "job_data": job,
            })

    atomic_write(args.output, normalized_out)
    print(f"Wrote normalized output to: {args.output}")
    try:
        atomic_write(skills_cache_path, mapping_cache)
        print(f"Saved {len(mapping_cache)} mapped skills to cache: {skills_cache_path}")
    except Exception as e:
        print(f"Warning: Failed to write mapped skills cache: {e}")
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
