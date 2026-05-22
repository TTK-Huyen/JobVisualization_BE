import os
import json
import re
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("consolidate")

def parse_folder_date(folder_name: str) -> str:
    """Extract YYYYMMDD from folder name starting with crawl_"""
    m = re.match(r"^crawl_(\d{8})_\d{6}$", folder_name)
    if m:
        return m.group(1)
    m2 = re.match(r"^crawl_(\d{8})$", folder_name)
    if m2:
        return m2.group(1)
    return ""

def main():
    base_dir = Path("Db/data")
    if not base_dir.exists():
        logger.error(f"Base directory {base_dir} does not exist.")
        sys.exit(1)

    # 1. Target Directory: Scan for directories matching crawl_202605* >= 20260510
    matching_folders = []
    for entry in base_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("crawl_202605"):
            date_str = parse_folder_date(entry.name)
            if date_str and date_str >= "20260510":
                matching_folders.append(entry)

    # Sort folders chronologically/alphabetically
    matching_folders = sorted(matching_folders, key=lambda x: x.name)

    global_jobs = []
    report_rows = []

    logger.info(f"Scanning target directory. Found {len(matching_folders)} directories to process.")

    # 2. Safe File Reading & 3. Memory Aggregation & 4. Exception Handling
    for folder in matching_folders:
        clean_dir = folder / "clean"
        extracted_file = clean_dir / "extracted.json"
        
        job_count = 0
        if not extracted_file.exists():
            logger.warning(f"[{folder.name}] Missing 'clean\\extracted.json'. Treating count as 0.")
        else:
            try:
                with open(extracted_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                
                if not content:
                    logger.warning(f"[{folder.name}] 'clean\\extracted.json' is empty. Treating count as 0.")
                else:
                    data = json.loads(content)
                    
                    # Safe parsing: support both raw arrays [...] and object-wrapped structures {"jobs": [...]}
                    jobs = []
                    if isinstance(data, list):
                        jobs = data
                    elif isinstance(data, dict):
                        if "jobs" in data and isinstance(data["jobs"], list):
                            jobs = data["jobs"]
                        else:
                            # Fallback: check if there's any other list attribute in the object
                            lists = [v for v in data.values() if isinstance(v, list)]
                            if lists:
                                jobs = lists[0]
                                logger.info(f"[{folder.name}] Found list under custom key. Parsed successfully.")
                            else:
                                raise ValueError("JSON object does not contain a list of jobs.")
                    else:
                        raise ValueError(f"Root JSON element is {type(data).__name__}, expected list or dict.")
                    
                    # Verify each job is an object/dict
                    valid_jobs = []
                    for job in jobs:
                        if isinstance(job, dict):
                            valid_jobs.append(job)
                        else:
                            logger.warning(f"[{folder.name}] Found non-dict job element. Skipping that element.")
                            
                    job_count = len(valid_jobs)
                    global_jobs.extend(valid_jobs)
                    
            except Exception as e:
                logger.warning(f"[{folder.name}] Failed to parse or read 'clean\\extracted.json'. Error: {e}. Treating count as 0.")
                job_count = 0

        report_rows.append((folder.name, job_count))

    # 5. Disk Writing
    output_dir = base_dir / "normalize_workspace"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "full_extracted_since_1005.json"

    logger.info(f"Saving {len(global_jobs)} consolidated jobs to {output_file}...")
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(global_jobs, f, ensure_ascii=False, indent=2)
        write_success = True
    except Exception as e:
        logger.error(f"Failed to write consolidated file: {e}")
        write_success = False

    # PRINT EXPECTED REPORT
    print("\n### EXPECTED OUTPUT REPORT\n")
    print("| Folder Name | Number of Extracted Jobs Found |")
    print("| :--- | :---: |")
    for folder_name, count in report_rows:
        print(f"| {folder_name} | {count} |")
    print(f"\n- **Total combined jobs in the final list**: {len(global_jobs)}")
    
    if write_success and output_file.exists():
        print(f"- **Physical verification**: The file \"full_extracted_since_1005.json\" has been successfully created on the disk at `{output_file}` (File size: {output_file.stat().st_size} bytes).")
    else:
        print("- **Physical verification**: FAILED! The consolidated file could not be written or verified on the disk.")

if __name__ == "__main__":
    main()
