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
# New structure: read from data/crawl_YYYYMMDD/raw/, write merged to data/crawl_YYYYMMDD/raw/
TODAY = datetime.now().strftime("%Y%m%d")
CRAWL_DIR = BASE.parent / "data" / f"crawl_{TODAY}"
RAW_DIR = CRAWL_DIR / "raw"
OUTDIR = RAW_DIR  # Output merged file to same location

# Ensure output directory exists
OUTDIR.mkdir(parents=True, exist_ok=True)

print(f"[MERGE] Reading crawled files from: {RAW_DIR}")
print(f"[MERGE] Output directory: {OUTDIR}")

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


def main():
    items = []
    seen = set()

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
                if key in seen:
                    continue
                seen.add(key)
                items.append(d)

        if p.suffix.lower() == '.csv':
            print(f"[MERGE] Processing: {p.name}")
            data = load_csv_file(p)
            for d in data:
                key = dedup_key(d)
                if key in seen:
                    continue
                seen.add(key)
                items.append(d)

    # Lưu vào same folder
    out_file = OUTDIR / 'jobs_combined.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"[MERGE] [OK] Merged {len(items)} items -> {out_file}")

if __name__ == '__main__':
    main()
