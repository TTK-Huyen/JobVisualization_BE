#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Normalize raw job data from different crawlers to standard RawJobData schema.

Problem Analysis:
- iTViec: Uses standard schema fields (source_name, description_html, requirements_text, etc.)
- CareerViet: Uses different field names (desc_mota, desc_yeucau, desc_quyenloi, company_name_full, detail_salary, etc.)
- Merge process doesn't normalize field names, resulting in missing data

Solution: Create a normalization step before clean_process.py processes the data
"""

import json
from pathlib import Path
import sys

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

from datetime import datetime
import sys

# Fix encoding for Windows console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def normalize_job_data(raw_job):
    """
    Normalize job data from different crawler sources to standard RawJobData schema.
    
    Field Mapping:
    - description_html: from desc_mota, description_html, desc
    - requirements_text: from desc_yeucau, requirements_text, requirements
    - benefits: from desc_quyenloi, benefits, benefit_list
    - salary_raw: from salary_list, detail_salary, salary_raw
    - experience_raw: from exp_list, detail_experience, experience_raw
    - company_name: from company_name_full, company_name, company
    - location_raw: from address_list, detail_location, location_raw
    - source_name: from source_name, or infer from job_url domain
    - employment_type: from working_times (if it contains values)
    """
    
    # Ensure source_name exists
    if not raw_job.get('source_name') or raw_job['source_name'] == 'unknown':
        # Infer from job_url
        job_url = raw_job.get('job_url', '')
        if 'careerviet.vn' in job_url:
            raw_job['source_name'] = 'careerviet'
        elif 'linkedin.com' in job_url:
            raw_job['source_name'] = 'linkedin'
        elif 'itviec.com' in job_url:
            raw_job['source_name'] = 'itviec'
        elif 'vietnamwork' in job_url:
            raw_job['source_name'] = 'vietnamwork'
        else:
            raw_job['source_name'] = 'unknown'
    
    # === Description (Priority: desc_mota, description_html, desc) ===
    if not raw_job.get('description_html') or raw_job['description_html'] == '':
        raw_job['description_html'] = raw_job.get('desc_mota', '') or raw_job.get('desc', '')
    
    # === Requirements (Priority: desc_yeucau, requirements_text, requirements) ===
    if not raw_job.get('requirements_text') or raw_job['requirements_text'] == '':
        raw_job['requirements_text'] = raw_job.get('desc_yeucau', '') or raw_job.get('requirements', '')
    
    # === Benefits (Priority: desc_quyenloi, benefits, benefit_list) ===
    if not raw_job.get('benefits') or raw_job['benefits'] == '[]':
        benefits_val = raw_job.get('desc_quyenloi', '')
        if benefits_val:
            # Split by newline or common delimiters
            raw_job['benefits'] = [b.strip() for b in benefits_val.split('\n') if b.strip()]
        else:
            raw_job['benefits'] = []
    
    # === Salary (Priority: salary_list, detail_salary, salary_raw) ===
    if not raw_job.get('salary_raw') or raw_job['salary_raw'] == '':
        raw_job['salary_raw'] = raw_job.get('salary_list', '') or raw_job.get('detail_salary', '')
    
    # === Experience (Priority: exp_list, detail_experience, experience_raw) ===
    if not raw_job.get('experience_raw') or raw_job['experience_raw'] == '':
        raw_job['experience_raw'] = raw_job.get('exp_list', '') or raw_job.get('detail_experience', '')
    
    # === Company Name (Priority: company_name_full, company_name, company) ===
    if not raw_job.get('company_name'):
        raw_job['company_name'] = raw_job.get('company_name_full', '') or raw_job.get('company', '')
    
    # === Location (Priority: address_list, detail_location, location_raw) ===
    if not raw_job.get('location_raw') or raw_job['location_raw'] == '':
        raw_job['location_raw'] = raw_job.get('address_list', '') or raw_job.get('detail_location', '')
    
    # === Job Source ID ===
    if not raw_job.get('job_source_id'):
        raw_job['job_source_id'] = raw_job.get('job_source_id', '')
    
    # === Posted Date ===
    if not raw_job.get('posted_date'):
        raw_job['posted_date'] = raw_job.get('deadline', '') or ''
    
    # === Scraped Timestamp ===
    if not raw_job.get('scraped_at'):
        raw_job['scraped_at'] = datetime.now().isoformat()
    
    # === Company Website ===
    if not raw_job.get('company_website'):
        raw_job['company_website'] = ''
    
    # === Company Address ===
    if not raw_job.get('company_address'):
        raw_job['company_address'] = ''
    
    # === Company Size ===
    if not raw_job.get('company_size_raw'):
        raw_job['company_size_raw'] = raw_job.get('company_size', '')
    
    # === Company Industry ===
    if not raw_job.get('company_industry'):
        raw_job['company_industry'] = ''
    
    # === Title ===
    if not raw_job.get('title'):
        raw_job['title'] = raw_job.get('detail_title', '') or 'Unknown'
    
    # === Employment Type ===
    if not raw_job.get('employment_type') or raw_job['employment_type'] == '':
        raw_job['employment_type'] = raw_job.get('working_times', '')
    
    # === Tags/Skills ===
    if not raw_job.get('tags'):
        raw_job['tags'] = []
    
    return raw_job

def normalize_file(input_path, output_path):
    """Normalize a raw jobs JSON file"""
    
    print(f"Reading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    print(f"Normalizing {len(jobs)} jobs...")
    normalized_jobs = [normalize_job_data(job) for job in jobs]
    
    print(f"Writing: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(normalized_jobs, f, ensure_ascii=False, indent=2)
    
    # Statistics
    sources = {}
    for job in normalized_jobs:
        source = job.get('source_name', 'unknown')
        sources[source] = sources.get(source, 0) + 1
    
    print(f"\n✅ Normalization Complete!")
    print(f"Sources distribution:")
    for source, count in sorted(sources.items()):
        print(f"   {source}: {count} jobs")

if __name__ == '__main__':
    import sys
    from datetime import datetime
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '_normalized.json')
    else:
        # Default: use new data/raw directory structure
        TODAY = datetime.now().strftime("%Y%m%d")
        BASE = Path(__file__).resolve().parent
        RAW_DIR = BASE.parent / "data" / "raw" / f"crawl_{TODAY}"
        input_file = RAW_DIR / 'jobs_combined.json'
        output_file = RAW_DIR / 'jobs_normalized.json'
    
    if Path(input_file).exists():
        normalize_file(input_file, output_file)
    else:
        print(f"Error: File not found - {input_file}")
        sys.exit(1)
