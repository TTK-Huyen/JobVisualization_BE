"""
Kiểm tra các folder crawl, nếu folder nào có:
- pending_llm.json trong clean folder là rỗng (hoặc file rỗng)
- extracted.json chứa data
Thì archive riêng vào một folder
"""
import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DIR = Path(__file__).resolve().parent / "Db"
DATA_DIR = BASE_DIR / "data"
ARCHIVE_DIR = DATA_DIR / "_archived_incomplete_pipeline"

def log(msg):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def is_file_empty_or_no_data(file_path: Path) -> bool:
    """Check if JSON file is empty or contains empty array"""
    if not file_path.exists():
        return True
    
    try:
        size = file_path.stat().st_size
        if size == 0:
            return True
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list) and len(data) == 0:
            return True
        if isinstance(data, dict) and len(data) == 0:
            return True
        
        return False
    except Exception as e:
        log(f"    [WARN] Error reading {file_path.name}: {e}")
        return True

def has_valid_data(file_path: Path) -> bool:
    """Check if JSON file has valid data"""
    if not file_path.exists():
        return False
    
    try:
        size = file_path.stat().st_size
        if size == 0:
            return False
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            return len(data) > 0
        if isinstance(data, dict):
            return len(data) > 0
        
        return True
    except Exception as e:
        log(f"    [WARN] Error reading {file_path.name}: {e}")
        return False

def get_file_size_mb(file_path: Path) -> float:
    """Get file size in MB"""
    if not file_path.exists():
        return 0
    return file_path.stat().st_size / (1024 * 1024)

def main():
    if not DATA_DIR.exists():
        log(f"❌ Data directory not found: {DATA_DIR}")
        return
    
    log(f"Checking crawl folders for incomplete pipeline status...")
    print()
    
    # Get all crawl folders
    crawl_folders = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])
    
    total = len(crawl_folders)
    skipped = 0
    found = 0
    archived = 0
    
    candidates = []
    
    for idx, crawl_folder in enumerate(crawl_folders, start=1):
        clean_dir = crawl_folder / "clean"
        pending_file = clean_dir / "pending_llm.json"
        extracted_file = clean_dir / "extracted.json"
        
        # Check if pending_llm.json is empty or doesn't exist
        pending_empty = is_file_empty_or_no_data(pending_file)
        
        # Check if extracted.json has data
        extracted_has_data = has_valid_data(extracted_file)
        
        # Condition: pending_llm.json is empty AND extracted.json has data
        if pending_empty and extracted_has_data:
            found += 1
            pending_size = get_file_size_mb(pending_file)
            extracted_size = get_file_size_mb(extracted_file)
            
            candidates.append({
                "folder": crawl_folder,
                "name": crawl_folder.name,
                "pending_size": pending_size,
                "extracted_size": extracted_size,
                "pending_empty": pending_empty,
            })
            
            print(f"[{found}] {crawl_folder.name}")
            print(f"    pending_llm.json: {'EMPTY' if pending_empty else f'{pending_size:.2f}MB'}")
            print(f"    extracted.json: {extracted_size:.2f}MB ✓")
            print()
        else:
            skipped += 1
    
    if not candidates:
        log("No incomplete pipeline folders found")
        log(f"Total checked: {total}, All complete or skipped: {skipped}")
        return
    
    # Archive candidates
    log(f"Found {found} incomplete pipeline folders. Archiving...")
    print()
    
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    
    for candidate in candidates:
        crawl_folder = candidate["folder"]
        archive_dest = ARCHIVE_DIR / crawl_folder.name
        
        if archive_dest.exists():
            log(f"  [{candidate['name']}] Already archived, skipping")
            continue
        
        try:
            shutil.copytree(crawl_folder, archive_dest, dirs_exist_ok=True)
            log(f"  ✓ Archived: {crawl_folder.name}")
            archived += 1
        except Exception as e:
            log(f"  ✗ Failed to archive {crawl_folder.name}: {e}")
    
    log("=" * 70)
    log("SUMMARY:")
    log(f"  Total crawl folders: {total}")
    log(f"  Incomplete pipeline (empty pending_llm + valid extracted): {found}")
    log(f"  Successfully archived: {archived}")
    log(f"  Archive location: {ARCHIVE_DIR}")
    log("=" * 70)

if __name__ == '__main__':
    main()
