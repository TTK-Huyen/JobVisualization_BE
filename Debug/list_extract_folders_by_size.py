#!/usr/bin/env python3
"""
List folders from extract_needed_folders.txt with pending_llm.json file sizes
Sort by size to find smallest test cases
"""

import json
from pathlib import Path

BASE_DIR = Path("Db/data")
EXTRACT_LIST_FILE = Path("extract_needed_folders.txt")

# Load extract_needed_folders.txt
with open(EXTRACT_LIST_FILE, 'r') as f:
    crawl_paths = [line.strip().replace('\\', '/') for line in f if line.strip()]

print(f"Analyzing {len(crawl_paths)} folders from extract_needed_folders.txt...\n")

folders_info = []

for crawl_path in crawl_paths:
    # Remove 'Db/data/' prefix if present
    folder_name = crawl_path.replace('Db/data/', '')
    crawl_folder = BASE_DIR / folder_name
    
    if not crawl_folder.exists():
        continue
    
    clean_dir = crawl_folder / "clean"
    pending_file = clean_dir / "pending_llm.json"
    
    if not pending_file.exists():
        continue
    
    try:
        size = pending_file.stat().st_size
        
        # Get job count
        with open(pending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        job_count = len(data) if isinstance(data, list) else 0
        
        if job_count > 0:
            folders_info.append({
                'name': folder_name,
                'path': crawl_folder,
                'size': size,
                'job_count': job_count
            })
    
    except Exception as e:
        pass

# Sort by size
folders_info.sort(key=lambda x: x['size'])

print(f"{'Folder Name':<30} {'Size (KB)':<12} {'Jobs':<6}")
print(f"{'-'*30} {'-'*12} {'-'*6}")

for info in folders_info[:20]:  # Show top 20 smallest
    size_kb = info['size'] / 1024
    print(f"{info['name']:<30} {size_kb:>10.1f}  {info['job_count']:>5}")

if len(folders_info) > 20:
    print(f"... and {len(folders_info) - 20} more")

print(f"\n{'='*80}")
print(f"Recommended test folder: {folders_info[0]['name']}")
print(f"Size: {folders_info[0]['size']} bytes ({folders_info[0]['size']/1024:.1f} KB)")
print(f"Jobs: {folders_info[0]['job_count']}")
print(f"\nTest command:")
print(f"python Db\\pipeline\\extract\\process_pending_llm.py --input-path \"{folders_info[0]['path']}/clean/pending_llm.json\" --output-path \"{folders_info[0]['path']}/clean/extracted.json\" --fallback-path \"{folders_info[0]['path']}/clean/extract_fallback.json\"")
