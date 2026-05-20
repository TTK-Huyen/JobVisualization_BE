#!/usr/bin/env python3
"""
Analyze clean folders in crawl directories:
1. If only pending_llm.json exists -> add to needs_extracted list
2. If both pending_llm.json and extracted.json exist:
   - Compare job_url counts
   - If same count -> no action needed
   - If different count -> add to needs_extracted list
"""

import json
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path("Db/data")

def get_job_urls(file_path):
    """Extract job_url values from a JSON file."""
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

def analyze_clean_folders():
    """Analyze all clean folders in crawl directories."""
    needs_extracted = []
    no_action_needed = []
    only_pending = []
    neither_exists = []
    
    crawl_folders = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith('crawl_')])
    
    print(f"Scanning {len(crawl_folders)} crawl folders...\n")
    
    for crawl_folder in crawl_folders:
        clean_dir = crawl_folder / "clean"
        
        if not clean_dir.exists():
            continue
        
        pending_file = clean_dir / "pending_llm.json"
        extracted_file = clean_dir / "extracted.json"
        
        # Case 1: Only pending_llm exists
        if pending_file.exists() and not extracted_file.exists():
            needs_extracted.append(str(crawl_folder))
            only_pending.append(crawl_folder.name)
            continue
        
        # Case 2: Neither exists
        if not pending_file.exists() and not extracted_file.exists():
            neither_exists.append(crawl_folder.name)
            continue
        
        # Case 3: Both exist
        if pending_file.exists() and extracted_file.exists():
            pending_urls = get_job_urls(pending_file)
            extracted_urls = get_job_urls(extracted_file)
            
            pending_count = len(pending_urls)
            extracted_count = len(extracted_urls)
            
            if pending_count == extracted_count:
                # Same count - no action needed
                no_action_needed.append({
                    'folder': crawl_folder.name,
                    'pending_count': pending_count,
                    'extracted_count': extracted_count
                })
            else:
                # Different count - needs extracted
                needs_extracted.append(str(crawl_folder))
                print(f"  {crawl_folder.name}: pending={pending_count}, extracted={extracted_count} [DIFF]")
    
    return {
        'needs_extracted': needs_extracted,
        'no_action_needed': no_action_needed,
        'only_pending': only_pending,
        'neither_exists': neither_exists
    }

def main():
    results = analyze_clean_folders()
    
    print("\n" + "="*80)
    print("ANALYSIS RESULTS")
    print("="*80)
    
    needs_extracted = results['needs_extracted']
    no_action_needed = results['no_action_needed']
    only_pending = results['only_pending']
    neither_exists = results['neither_exists']
    
    print(f"\n📊 SUMMARY:")
    print(f"  - Only pending_llm (needs extracted): {len(only_pending)}")
    print(f"  - Both exist, SAME job_url count (no action): {len(no_action_needed)}")
    print(f"  - Both exist, DIFF job_url count (needs extracted): {len(needs_extracted) - len(only_pending)}")
    print(f"  - Neither exists: {len(neither_exists)}")
    print(f"  - TOTAL needs extracted: {len(needs_extracted)}")
    
    # Output lists
    print(f"\n{'='*80}")
    print(f"📋 FOLDERS NEEDING EXTRACTED STEP ({len(needs_extracted)}):")
    print(f"{'='*80}")
    for path in needs_extracted:
        print(path)
    
    # Save to file
    output_file = Path("extract_needed_folders.txt")
    with open(output_file, 'w', encoding='utf-8') as f:
        for path in needs_extracted:
            f.write(path + '\n')
    
    print(f"\n✅ Saved to: {output_file}")
    
    # Save summary
    summary_file = Path("clean_folders_analysis.json")
    summary = {
        'total_analyzed': len(only_pending) + len(no_action_needed) + len(neither_exists) + (len(needs_extracted) - len(only_pending)),
        'only_pending_count': len(only_pending),
        'both_same_count': len(no_action_needed),
        'both_diff_count': len(needs_extracted) - len(only_pending),
        'neither_exists_count': len(neither_exists),
        'total_needs_extracted': len(needs_extracted),
        'folders_needing_extracted': needs_extracted,
        'folders_no_action': [item['folder'] for item in no_action_needed]
    }
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Saved summary to: {summary_file}")
    
    print(f"\n{'='*80}")
    print(f"📝 NO ACTION NEEDED ({len(no_action_needed)}):")
    print(f"{'='*80}")
    for item in no_action_needed[:20]:  # Show first 20
        print(f"  {item['folder']}: pending={item['pending_count']}, extracted={item['extracted_count']}")
    if len(no_action_needed) > 20:
        print(f"  ... and {len(no_action_needed) - 20} more")
    
    if neither_exists:
        print(f"\n{'='*80}")
        print(f"⚠️  NEITHER FILES EXIST ({len(neither_exists)}):")
        print(f"{'='*80}")
        for folder in neither_exists[:20]:
            print(f"  {folder}")
        if len(neither_exists) > 20:
            print(f"  ... and {len(neither_exists) - 20} more")

if __name__ == '__main__':
    main()
