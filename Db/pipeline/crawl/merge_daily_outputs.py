import os
import json
import csv
import sys
from pathlib import Path
from datetime import datetime

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE = Path(__file__).resolve().parent
# Use RUN_DATE from env (set by pipeline) or fallback to current time
TODAY_WITH_TIME = os.environ.get("RUN_DATE", datetime.now().strftime("%Y%m%d_%H%M%S"))
CRAWL_DIR = BASE.parent / "data" / f"crawl_{TODAY_WITH_TIME}"
RAW_DIR = CRAWL_DIR / "raw"
FALLBACK_DIR = CRAWL_DIR / "fallback"
SCHEMA_FILE = BASE.parent / "crawl_schema.json"
OUTDIR = RAW_DIR  # Output merged file to same location

# If the pipeline layout's data folder doesn't exist, fall back to the repository-level data folder
if not RAW_DIR.exists():
    # repository root is two parents up from this file (pipeline/crawl -> project root)
    repo_data_candidate = BASE.parents[2] / "data" / f"crawl_{TODAY_WITH_TIME}"
    if repo_data_candidate.exists():
        CRAWL_DIR = repo_data_candidate
        RAW_DIR = CRAWL_DIR / "raw"
        FALLBACK_DIR = CRAWL_DIR / "fallback"

# Ensure output directory exists
OUTDIR.mkdir(parents=True, exist_ok=True)
FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

print(f"[MERGE] Reading crawled files from: {RAW_DIR}")
print(f"[MERGE] Output directory: {OUTDIR}")

sys.path.insert(0, str(BASE))
try:
    from central_filters import filter_recent_jobs
except Exception:
    filter_recent_jobs = None

def load_json_file(p):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def load_csv_file(p):
    rows = []
    try:
        with open(p, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception:
        pass
    return rows

def dedup_key(d: dict) -> str:
    url = (d.get('url') or d.get('job_url') or '').strip().lower()
    if url:
        return f"url::{url}"
    title = (d.get('title') or d.get('detail_title') or '').strip().lower()
    comp = (d.get('company') or d.get('company_name_full') or '').strip().lower()
    loc = ''
    if isinstance(d.get('location'), str):
        loc = d['location'].strip().lower()
    elif isinstance(d.get('address_list'), list) and d['address_list']:
        loc = str(d['address_list'][0]).strip().lower()
    return f"sig::{title}|{comp}|{loc}"


def load_schema_fields() -> tuple[list[str], list[str]]:
    try:
        with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except Exception:
        schema = {}

    required = list(schema.get('required') or [])
    optional = list(schema.get('optional') or [])
    return required, optional


def has_description_html(d: dict) -> bool:
    value = d.get('description_html')
    return isinstance(value, str) and bool(value.strip())


def prefer_record(existing: dict, candidate: dict) -> bool:
    existing_has_description = has_description_html(existing)
    candidate_has_description = has_description_html(candidate)
    return candidate_has_description and not existing_has_description


REQUIRED_FIELDS, OPTIONAL_FIELDS = load_schema_fields()
ALL_SCHEMA_FIELDS = tuple(REQUIRED_FIELDS + OPTIONAL_FIELDS)


def missing_required_fields(d: dict) -> list[str]:
    """Return list of required schema fields that are missing or empty in dict d."""
    missing = []
    for field_name in REQUIRED_FIELDS:
        value = d.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field_name)
    return missing


def missing_schema_fields(d: dict) -> list[str]:
    """Backward-compatible: return missing required + optional (used only for diagnostics).
    Keep this for logging but the routing decision will use only required fields.
    """
    missing = []
    for field_name in ALL_SCHEMA_FIELDS:
        value = d.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field_name)
    return missing


def main():
    items_by_key = {}

    # Scan tất cả files trong RAW_DIR (không scan subdirectories)
    if not RAW_DIR.exists():
        print(f"[ERROR] Raw directory not found: {RAW_DIR}")
        return
    
    for p in RAW_DIR.iterdir():
        # Skip các folder, chỉ xử lý files trực tiếp trong raw
        if p.is_dir():
            continue
        
        # Skip merged file
        if p.name == 'jobs_combined.json':
            continue
            
        name = p.name.lower()
        if p.suffix.lower() == '.json':
            print(f"[MERGE] Processing: {p.name}")
            data = load_json_file(p)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                key = dedup_key(d)
                existing = items_by_key.get(key)
                if existing is None or prefer_record(existing, d):
                    items_by_key[key] = d

        if p.suffix.lower() == '.csv':
            print(f"[MERGE] Processing: {p.name}")
            data = load_csv_file(p)
            for d in data:
                key = dedup_key(d)
                existing = items_by_key.get(key)
                if existing is None or prefer_record(existing, d):
                    items_by_key[key] = d

    # Load keywords config to translate search_keywords
    keyword_cfg = {}
    keywords_file = BASE.parent / "keywords_daily.json"
    if not keywords_file.exists():
        keywords_file = BASE.parent / "keywords_daily.json"
    if not keywords_file.exists():
        keywords_file = BASE.parents[1] / "input" / "keywords_daily.json"
        
    if keywords_file.exists():
        try:
            with open(keywords_file, encoding="utf-8") as f:
                keyword_cfg = json.load(f)
        except Exception as e:
            print(f"[MERGE][WARN] Failed to read keywords file: {e}")

    # Build translation map from Vietnamese to English
    groups = keyword_cfg.get("groups", {})
    vi_to_en = {}
    if isinstance(groups, dict):
        for group_cfg in groups.values():
            if not isinstance(group_cfg, dict):
                continue
            en_list = group_cfg.get("en", [])
            vi_list = group_cfg.get("vi", [])
            if not isinstance(en_list, list) or not en_list:
                continue
            if isinstance(vi_list, list):
                for i, vi_kw in enumerate(vi_list):
                    vi_kw_clean = str(vi_kw).strip().lower()
                    corresponding_en = en_list[i] if i < len(en_list) else en_list[0]
                    vi_to_en[vi_kw_clean] = str(corresponding_en).strip()

    items = list(items_by_key.values())
    for item in items:
        # Normalize search_keyword to its English counterpart
        kw = item.get("search_keyword")
        if isinstance(kw, str):
            kw_clean = kw.strip().lower()
            if kw_clean in vi_to_en:
                item["search_keyword"] = vi_to_en[kw_clean]
        
        # Enforce no search_group field
        if "search_group" in item:
            del item["search_group"]

    # Decide routing based on *required* fields only
    fallback_items = [d for d in items if missing_required_fields(d)]
    combined_items = [d for d in items if not missing_required_fields(d)]

    job_date_mode = str(os.environ.get("JOB_DATE_MODE", "")).strip().lower()
    if filter_recent_jobs and job_date_mode in {"on", "true", "yes", "1", "realtime"}:
        combined_items = filter_recent_jobs(combined_items)

    # Lưu vào same folder
    out_file = OUTDIR / 'jobs_combined.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(combined_items, f, ensure_ascii=False, indent=2)

    # Annotate fallback items with a clear reason for routing to fallback
    for item in fallback_items:
        # Report only missing required fields as the reason for fallback
        missing_req = missing_required_fields(item)
        reason = {
            "type": "missing_required_fields",
            "missing_fields": missing_req,
            "summary": f"missing required: {', '.join(missing_req)}" if missing_req else "unknown"
        }
        # Do not overwrite if a reason already exists
        if 'fallback_reason' not in item and '_fallback_reason' not in item:
            item['fallback_reason'] = reason

    raw_fallback_file = FALLBACK_DIR / 'raw_fallback.json'
    with open(raw_fallback_file, 'w', encoding='utf-8') as f:
        json.dump(fallback_items, f, ensure_ascii=False, indent=2)

    for item in fallback_items:
        missing_fields = ", ".join(missing_required_fields(item))
        print(
            "[MERGE][WARN] Missing schema fields ("
            f"{missing_fields}): "
            f"{item.get('title') or item.get('detail_title') or '(no title)'} | "
            f"{item.get('job_url') or item.get('url') or '(no url)'}"
        )

    print(f"[MERGE] [OK] Merged {len(combined_items)} items -> {out_file}")
    print(f"[MERGE] [OK] Routed {len(fallback_items)} raw fallback items -> {raw_fallback_file}")

if __name__ == '__main__':
    main()
