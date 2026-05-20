"""
Kiểm tra tất cả crawl folders, nếu raw folder có chứa job JSON files
nhưng không có jobs_combined.json thì bổ sung bằng merge algorithm
"""
import os
import json
import csv
import sys
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict, List, Any

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DATA_DIR = Path(__file__).resolve().parent / "Db" / "data"
SCHEMA_FILE = Path(__file__).resolve().parent / "Db" / "pipeline" / "crawl" / "crawl_schema.json"

def load_json_file(p):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  [WARN] Failed to load {p.name}: {e}")
        return []

def load_csv_file(p):
    rows = []
    try:
        with open(p, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception as e:
        print(f"  [WARN] Failed to load CSV {p.name}: {e}")
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

def load_schema_fields() -> Tuple[List[str], List[str]]:
    try:
        with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except Exception:
        print(f"[WARN] Schema file not found at {SCHEMA_FILE}")
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

def missing_required_fields(d: dict, required_fields: List[str]) -> List[str]:
    """Return list of required schema fields that are missing or empty in dict d."""
    missing = []
    for field_name in required_fields:
        value = d.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field_name)
    return missing

def merge_crawl_folder(crawl_path: Path, required_fields: List[str]) -> Dict[str, Any]:
    """
    Merge JSON/CSV files in crawl folder's raw directory.
    Returns: {"success": bool, "message": str, "stats": {...}}
    """
    raw_dir = crawl_path / "raw"
    fallback_dir = crawl_path / "fallback"
    
    # Check if raw folder exists
    if not raw_dir.exists():
        return {"success": False, "message": "No raw directory", "stats": {}}
    
    # Check if raw folder is empty
    raw_files = list(raw_dir.glob("*.json")) + list(raw_dir.glob("*.csv"))
    raw_files = [f for f in raw_files if f.name != "jobs_combined.json"]
    
    if not raw_files:
        return {"success": False, "message": "Raw folder is empty", "stats": {}}
    
    # Check if jobs_combined.json already exists
    combined_file = raw_dir / "jobs_combined.json"
    if combined_file.exists():
        return {"success": False, "message": "jobs_combined.json already exists", "stats": {}}
    
    # Merge algorithm
    items_by_key = {}
    
    print(f"  [MERGE] Processing {len(raw_files)} raw files...")
    for p in raw_files:
        if p.suffix.lower() == '.json':
            data = load_json_file(p)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                key = dedup_key(d)
                existing = items_by_key.get(key)
                if existing is None or prefer_record(existing, d):
                    items_by_key[key] = d
        
        elif p.suffix.lower() == '.csv':
            data = load_csv_file(p)
            for d in data:
                key = dedup_key(d)
                existing = items_by_key.get(key)
                if existing is None or prefer_record(existing, d):
                    items_by_key[key] = d
    
    items = list(items_by_key.values())
    
    # Split based on required fields
    fallback_items = [d for d in items if missing_required_fields(d, required_fields)]
    combined_items = [d for d in items if not missing_required_fields(d, required_fields)]
    
    # Save combined items
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(combined_items, f, ensure_ascii=False, indent=2)
    
    # Save fallback items
    fallback_dir.mkdir(parents=True, exist_ok=True)
    raw_fallback_file = fallback_dir / "raw_fallback.json"
    
    for item in fallback_items:
        if 'fallback_reason' not in item and '_fallback_reason' not in item:
            missing_req = missing_required_fields(item, required_fields)
            reason = {
                "type": "missing_required_fields",
                "missing_fields": missing_req,
                "summary": f"missing required: {', '.join(missing_req)}" if missing_req else "unknown"
            }
            item['fallback_reason'] = reason
    
    with open(raw_fallback_file, 'w', encoding='utf-8') as f:
        json.dump(fallback_items, f, ensure_ascii=False, indent=2)
    
    return {
        "success": True,
        "message": f"Merged and saved",
        "stats": {
            "total_items": len(items),
            "combined_items": len(combined_items),
            "fallback_items": len(fallback_items),
            "combined_file": str(combined_file),
            "fallback_file": str(raw_fallback_file)
        }
    }

def main():
    if not BASE_DATA_DIR.exists():
        print(f"[ERROR] Data directory not found: {BASE_DATA_DIR}")
        return
    
    required_fields, optional_fields = load_schema_fields()
    print(f"[INFO] Schema: {len(required_fields)} required fields, {len(optional_fields)} optional")
    print(f"[INFO] Checking all crawl folders in: {BASE_DATA_DIR}")
    print()
    
    # Get all crawl folders
    crawl_folders = sorted([d for d in BASE_DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])
    
    processed = 0
    skipped = 0
    merged = 0
    
    for crawl_folder in crawl_folders:
        raw_dir = crawl_folder / "raw"
        combined_file = raw_dir / "jobs_combined.json"
        
        # Quick check: is there a raw folder?
        if not raw_dir.exists():
            skipped += 1
            continue
        
        # Quick check: does jobs_combined.json already exist?
        if combined_file.exists():
            skipped += 1
            continue
        
        # Check if there are any JSON files
        json_files = list(raw_dir.glob("*.json"))
        csv_files = list(raw_dir.glob("*.csv"))
        
        if not json_files and not csv_files:
            skipped += 1
            continue
        
        # Found a candidate for merging
        processed += 1
        print(f"[{processed}] {crawl_folder.name}")
        result = merge_crawl_folder(crawl_folder, required_fields)
        
        if result["success"]:
            merged += 1
            stats = result["stats"]
            print(f"  ✓ SUCCESS: {stats['combined_items']} combined, {stats['fallback_items']} fallback")
        else:
            print(f"  ✗ SKIPPED: {result['message']}")
        print()
    
    print("=" * 70)
    print(f"SUMMARY:")
    print(f"  Total crawl folders: {len(crawl_folders)}")
    print(f"  Candidates checked: {processed}")
    print(f"  Successfully merged: {merged}")
    print(f"  Skipped (no raw or already merged): {skipped}")
    print("=" * 70)

if __name__ == '__main__':
    main()
