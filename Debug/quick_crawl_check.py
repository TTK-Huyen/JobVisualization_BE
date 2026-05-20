#!/usr/bin/env python3
"""Quick crawl directory analyzer"""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path("Db/data")

# Get list of crawl dirs
crawl_dirs = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])
print(f"Found {len(crawl_dirs)} crawl directories\n")

# Analyze each directory
for crawl_dir in crawl_dirs:
    name = crawl_dir.name
    try:
        date_str = name.split("_")[1]
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        
        # Check for extracted.json
        extracted = crawl_dir / "clean" / "extracted.json"
        if extracted.exists():
            size_mb = extracted.stat().st_size / (1024*1024)
            # Rough estimate: ~7.3 MB per ~1000 jobs
            jobs_est = int((size_mb / 7.3) * 1000)
            print(f"{date_obj.strftime('%Y-%m-%d')}: extracted.json ({size_mb:.1f} MB, ~{jobs_est} jobs)")
        
        # Check for crawl/jobs_combined.json
        combined = crawl_dir / "crawl" / "jobs_combined.json"
        if combined.exists():
            size_mb = combined.stat().st_size / (1024*1024)
            jobs_est = int((size_mb / 7.3) * 1000)
            print(f"{date_obj.strftime('%Y-%m-%d')}: crawl/jobs_combined.json ({size_mb:.1f} MB, ~{jobs_est} jobs)")
        
        # Check raw files
        raw_dir = crawl_dir / "raw"
        if raw_dir.exists():
            raw_files = list(raw_dir.glob("*.json"))
            if raw_files:
                total_size = sum(f.stat().st_size for f in raw_files) / (1024*1024)
                jobs_est = int((total_size / 7.3) * 1000)
                print(f"{date_obj.strftime('%Y-%m-%d')}: {len(raw_files)} raw files ({total_size:.1f} MB, ~{jobs_est} jobs)")
        
        print()
    except Exception as e:
        print(f"{name}: Error - {e}\n")
