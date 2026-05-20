#!/usr/bin/env python3
"""
Recruitment Pipeline Data Reconciliation Script
------------------------------------------------
This script reconciles job data across 80K crawls based on a cutoff date of 2026-05-10.
It performs the following:
1. Scan crawl directories in Db/data/.
2. Classify crawls into:
   - Prep-cutoff: Date < 2026-05-10. Re-extract all raw jobs from jobs_combined.json.
   - Post-cutoff: Date >= 2026-05-10. Read extracted.json to identify completed jobs,
     and extract any raw jobs that are missing in extracted.json.
3. De-duplicate raw jobs using URL hashing.
4. Output backlog in batches of 2,000 to Db/data/queue/batch_*.json.
"""

import os
import re
import json
import logging
import datetime
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple

# Configuration Constants
CUTOFF_DATE_STR = "20260510"
BATCH_SIZE = 1000

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("reconcile")

# Resolve Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE_ROOT / "Db" / "data"
QUEUE_DIR = DATA_DIR / "queue"

def parse_cutoff_date(date_str: str) -> datetime.date:
    return datetime.date(
        int(date_str[:4]),
        int(date_str[4:6]),
        int(date_str[6:])
    )

def parse_folder_date(folder_name: str) -> datetime.date | None:
    # 1. Format: crawl_YYYYMMDD_HHMMSS
    m1 = re.match(r"^crawl_(\d{4})(\d{2})(\d{2})_\d{6}$", folder_name)
    if m1:
        return datetime.date(int(m1.group(1)), int(m1.group(2)), int(m1.group(3)))

    # 2. Format: crawl_YYYYMMDD
    m2 = re.match(r"^crawl_(\d{4})(\d{2})(\d{2})$", folder_name)
    if m2:
        return datetime.date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))

    # 3. Format: crawlMMDDYYYY
    m3 = re.match(r"^crawl(\d{2})(\d{2})(\d{4})$", folder_name)
    if m3:
        return datetime.date(int(m3.group(3)), int(m3.group(1)), int(m3.group(2)))

    # 4. Format: crawl_MMDDYYYY
    m4 = re.match(r"^crawl_(\d{2})(\d{2})(\d{4})$", folder_name)
    if m4:
        return datetime.date(int(m4.group(3)), int(m4.group(1)), int(m4.group(2)))

    # 5. Fallback regex to find any 8 consecutive digits in a folder starting with "crawl"
    m5 = re.search(r"crawl.*?(\d{8})", folder_name)
    if m5:
        digits = m5.group(1)
        # Try YYYYMMDD first
        try:
            year = int(digits[:4])
            month = int(digits[4:6])
            day = int(digits[6:])
            if 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime.date(year, month, day)
        except ValueError:
            pass
        # Try MMDDYYYY
        try:
            month = int(digits[:2])
            day = int(digits[2:4])
            year = int(digits[4:])
            if 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime.date(year, month, day)
        except ValueError:
            pass

    return None

def get_job_url(job: Dict[str, Any]) -> str | None:
    for key in ['job_url', 'url', 'job_url_raw', 'job_source_id']:
        val = job.get(key)
        if val and isinstance(val, str):
            val_strip = val.strip()
            if val_strip:
                return val_strip
    return None

def load_json_file(file_path: Path) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
    except Exception as e:
        logger.warning(f"Error reading JSON from {file_path}: {e}")
    return []

def scan_and_reconcile() -> List[Dict[str, Any]]:
    cutoff_date = parse_cutoff_date(CUTOFF_DATE_STR)
    logger.info(f"Using cutoff date: {cutoff_date}")
    
    new_run_backlog: List[Dict[str, Any]] = []
    
    if not DATA_DIR.exists():
        logger.error(f"Data directory does not exist: {DATA_DIR}")
        return []

    crawl_dirs = [d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl")]
    logger.info(f"Found {len(crawl_dirs)} crawl directories in {DATA_DIR}")
    
    for cdir in sorted(crawl_dirs):
        folder_date = parse_folder_date(cdir.name)
        if not folder_date:
            logger.warning(f"Skipping folder {cdir.name} (unable to parse date)")
            continue
        
        # Resolve raw combined file path
        raw_paths = [
            cdir / "raw" / "jobs_combined.json",
            cdir / "jobs_combined.json"
        ]
        raw_file = None
        for p in raw_paths:
            if p.exists():
                raw_file = p
                break
                
        if not raw_file:
            logger.warning(f"No jobs_combined.json found in {cdir.name}, skipping.")
            continue
            
        if folder_date >= cutoff_date:
            # Case 1: Post-cutoff (Clean/Standard structure)
            completed_urls: Set[str] = set()
            
            # Read extracted.json if it exists
            extracted_paths = [
                cdir / "clean" / "extracted.json",
                cdir / "extracted.json"
            ]
            extracted_file = None
            for p in extracted_paths:
                if p.exists():
                    extracted_file = p
                    break
            
            if extracted_file:
                extracted_jobs = load_json_file(extracted_file)
                for job in extracted_jobs:
                    url = get_job_url(job)
                    if url:
                        completed_urls.add(url)
                logger.info(f"[{cdir.name}] Post-cutoff. Found {len(completed_urls)} extracted URLs in {extracted_file.name}")
            else:
                # SAFE FALLBACK: If extracted.json is missing, treat completed_urls as empty
                logger.info(f"[{cdir.name}] Post-cutoff. No extracted.json found. All jobs will be treated as pending.")
                
            raw_jobs = load_json_file(raw_file)
            pending_count = 0
            for job in raw_jobs:
                url = get_job_url(job)
                if not url or url not in completed_urls:
                    new_run_backlog.append(job)
                    pending_count += 1
            logger.info(f"[{cdir.name}] Post-cutoff. Appended {pending_count}/{len(raw_jobs)} pending jobs to backlog.")
            
        else:
            # Case 2: Pre-cutoff (Old structure, discard past extractions, re-extract everything)
            raw_jobs = load_json_file(raw_file)
            new_run_backlog.extend(raw_jobs)
            logger.info(f"[{cdir.name}] Pre-cutoff. Appended all {len(raw_jobs)} jobs to backlog.")
            
    return new_run_backlog

def write_batches(jobs: List[Dict[str, Any]]) -> List[Path]:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clear existing batch files to avoid stale data
    for old_file in QUEUE_DIR.glob("batch_*.json"):
        try:
            old_file.unlink()
            logger.info(f"Deleted stale batch file: {old_file.name}")
        except Exception as e:
            logger.warning(f"Failed to delete stale batch file {old_file.name}: {e}")
            
    # Deduplicate based on job_url
    seen_urls: Set[str] = set()
    unique_jobs: List[Dict[str, Any]] = []
    
    for job in jobs:
        url = get_job_url(job)
        if not url:
            title = job.get('title') or job.get('job_title') or ''
            desc = job.get('description') or job.get('description_html') or ''
            fallback_str = f"{title}_{desc}"
            url = hashlib.sha256(fallback_str.encode('utf-8')).hexdigest()
            
        if url not in seen_urls:
            seen_urls.add(url)
            unique_jobs.append(job)
            
    total_unique = len(unique_jobs)
    logger.info(f"Total jobs collected: {len(jobs)}")
    logger.info(f"Total unique jobs after deduplication: {total_unique}")
    
    num_batches = (total_unique + BATCH_SIZE - 1) // BATCH_SIZE
    written_files: List[Path] = []
    
    for i in range(num_batches):
        batch_jobs = unique_jobs[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        batch_filename = f"batch_{i + 1}.json"
        batch_filepath = QUEUE_DIR / batch_filename
        
        # Write batch atomically
        temp_filepath = QUEUE_DIR / f"{batch_filename}.tmp"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as f:
                json.dump(batch_jobs, f, ensure_ascii=False, indent=2)
            os.replace(str(temp_filepath), str(batch_filepath))
            written_files.append(batch_filepath)
            logger.info(f"Successfully wrote {len(batch_jobs)} jobs to {batch_filepath.name}")
        except Exception as e:
            logger.error(f"Failed to write batch {batch_filename}: {e}")
            if temp_filepath.exists():
                temp_filepath.unlink()
                
    return written_files

def main():
    logger.info("Starting pipeline data reconciliation...")
    backlog = scan_and_reconcile()
    if not backlog:
        logger.info("No jobs to reconcile.")
        return
        
    written = write_batches(backlog)
    logger.info(f"Reconciliation completed successfully. Wrote {len(written)} batch files under {QUEUE_DIR}")

if __name__ == "__main__":
    main()
