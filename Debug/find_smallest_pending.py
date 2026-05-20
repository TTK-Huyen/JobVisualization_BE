#!/usr/bin/env python3
"""
Find the folder with the smallest pending_llm.json file size
"""

import json
from pathlib import Path

BASE_DIR = Path("Db/data")
EXTRACT_LIST_FILE = Path("extract_needed_folders.txt")

# Load extract_needed_folders.txt
with open(EXTRACT_LIST_FILE, 'r') as f:
    crawl_paths = [line.strip().replace('\\', '/') for line in f if line.strip()]

print(f"Checking {len(crawl_paths)} folders...\n")

smallest = None
smallest_size = float('inf')

for crawl_path in crawl_paths:
    crawl_folder = BASE_DIR / crawl_path.replace('Db/data/', '')
    
    if not crawl_folder.exists():
        continue
    
    clean_dir = crawl_folder / "clean"
    pending_file = clean_dir / "pending_llm.json"
    
    if not pending_file.exists():
        continue
    
    try:
        size = pending_file.stat().st_size
        
        # Try to read and get job count
        with open(pending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        job_count = len(data) if isinstance(data, list) else 0
        
        if size < smallest_size and job_count > 0:
            smallest_size = size
            smallest = {
                'path': crawl_folder,
                'name': crawl_folder.name,
                'size': size,
                'job_count': job_count
            }
        
        if size < 10000:  # Show files smaller than 10KB
            print(f"  {crawl_folder.name}: {size} bytes ({job_count} jobs)")
    
    except Exception as e:
        pass

print(f"\n{'='*80}")
print(f"SMALLEST FILE:")
print(f"{'='*80}")
if smallest:
    print(f"Folder: {smallest['name']}")
    print(f"Path: {smallest['path']}")
    print(f"File size: {smallest['size']} bytes")
    print(f"Job count: {smallest['job_count']}")
    print(f"\nCommand to test:")
    print(f"python run_extract_single.py \"{smallest['path']}\"")
else:
    print("No suitable folder found")
