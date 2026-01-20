import os
import json
import csv
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "output"
OUTDIR.mkdir(exist_ok=True)

# Tạo folder theo ngày (crawl_14_01_26)
TODAY = datetime.now().strftime("%d_%m_%y")
CRAWL_DIR = OUTDIR / f"crawl_{TODAY}"
CRAWL_DIR.mkdir(exist_ok=True)

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

    # Scan tất cả files trong OUTDIR (không scan subdirectories)
    for p in OUTDIR.iterdir():
        # Skip các folder, chỉ xử lý files trực tiếp trong output
        if p.is_dir():
            continue
            
        name = p.name.lower()
        if p.suffix.lower() == '.json':
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
            data = load_csv_file(p)
            for d in data:
                key = dedup_key(d)
                if key in seen:
                    continue
                seen.add(key)
                items.append(d)

    # Lưu vào folder theo ngày, chỉ 1 file JSON
    out_file = CRAWL_DIR / 'jobs_combined.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"Merged {len(items)} items -> {out_file}")

if __name__ == '__main__':
    main()
