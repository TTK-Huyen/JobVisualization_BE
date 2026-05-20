#!/usr/bin/env python3
"""
Remove jobs from pending_llm.json that already exist in extracted.json
by comparing job_url field.
"""

import json
from pathlib import Path

BASE_DIR = Path("Db/data")

def get_extracted_urls(file_path):
    """Get all job_url values from extracted.json."""
    if not file_path.exists():
        return set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return set()
    
    urls = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and 'job_url' in item:
                url = item.get('job_url', '').strip()
                if url:
                    urls.add(url)
    return urls

def dedupe_pending_llm(crawl_folder):
    """
    Remove jobs from pending_llm.json that exist in extracted.json.
    Returns (removed_count, remaining_count) or None if error.
    """
    clean_dir = crawl_folder / "clean"
    pending_file = clean_dir / "pending_llm.json"
    extracted_file = clean_dir / "extracted.json"
    
    if not pending_file.exists() or not extracted_file.exists():
        return None
    
    try:
        # Get extracted URLs
        extracted_urls = get_extracted_urls(extracted_file)
        
        # Load pending_llm.json
        with open(pending_file, 'r', encoding='utf-8') as f:
            pending_data = json.load(f)
        
        if not isinstance(pending_data, list):
            return None
        
        # Filter out jobs that are already in extracted
        original_count = len(pending_data)
        filtered_data = [
            job for job in pending_data
            if not (isinstance(job, dict) and 
                    job.get('job_url', '').strip() in extracted_urls)
        ]
        removed_count = original_count - len(filtered_data)
        
        if removed_count > 0:
            # Save deduplicated pending_llm.json
            with open(pending_file, 'w', encoding='utf-8') as f:
                json.dump(filtered_data, f, indent=2, ensure_ascii=False)
        
        return removed_count, len(filtered_data)
    
    except Exception as e:
        print(f"  ❌ Error processing {crawl_folder.name}: {e}")
        return None

def main():
    crawl_folders = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith('crawl_')])
    
    print(f"Processing {len(crawl_folders)} crawl folders...\n")
    
    total_removed = 0
    total_processed = 0
    failed = []
    
    for crawl_folder in crawl_folders:
        clean_dir = crawl_folder / "clean"
        if not clean_dir.exists():
            continue
        
        pending_file = clean_dir / "pending_llm.json"
        extracted_file = clean_dir / "extracted.json"
        
        # Only process folders with both files
        if not (pending_file.exists() and extracted_file.exists()):
            continue
        
        result = dedupe_pending_llm(crawl_folder)
        
        if result is not None:
            removed, remaining = result
            if removed > 0:
                total_processed += 1
                total_removed += removed
                print(f"✅ {crawl_folder.name}: removed {removed}, remaining {remaining}")
    
    print(f"\n{'='*80}")
    print(f"📊 SUMMARY:")
    print(f"  - Folders processed: {total_processed}")
    print(f"  - Total jobs removed: {total_removed}")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
