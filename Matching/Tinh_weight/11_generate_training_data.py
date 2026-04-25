"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                 SCRIPT 11: GROUP JOBS BY TITLE                                ║
║              Organize 452 Jobs for LLM Group Analysis                         ║
╚═══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│ 🎯 MỤC TIÊU (OBJECTIVE)                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Group 452 jobs theo job title (e.g., "Backend Developer", "QA Engineer"). │
│                                                                              │
│  Quy trình:                                                                  │
│  1. Đọc 452 jobs từ jobs_from_db.json                                      │
│  2. Group theo job title (job['title'])                                     │
│  3. Mỗi group sẽ có ~100 jobs cùng title                                  │
│  4. Lưu vào jobs_grouped_by_title.json                                     │
│                                                                              │
│  Ví dụ grouping:                                                             │
│  • Backend Developer: 100 jobs                                               │
│  • Frontend Developer: 95 jobs                                               │
│  • QA Engineer: 87 jobs                                                      │
│  • ... (tất cả 452 jobs)                                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📥 INPUT (Từ jobs_from_db.json)                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [{                                                                          │
│    "job_id": 1,                                                             │
│    "title": "Backend Developer",                                            │
│    "description": "We need Java Spring Boot expert...",                     │
│    "skills_with_category": [                                               │
│      {"name": "java", "category": "Languages"},                            │
│      {"name": "spring", "category": "Backend_Frameworks"},                 │
│      {...}                                                                   │
│    ]                                                                         │
│  },                                                                          │
│  {                                                                           │
│    "job_id": 2,                                                             │
│    "title": "Frontend Developer",                                           │
│    "description": "Looking for React expert...",                            │
│    "skills_with_category": [...]                                           │
│  },                                                                          │
│  ...]                                                                        │
│                                                                              │
│  Total: 452 jobs với nhiều job titles khác nhau                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📤 OUTPUT (jobs_grouped_by_title.json)                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Keyed by job title, each containing array of jobs:                         │
│                                                                              │
│  {                                                                           │
│    "Backend Developer": [                                                   │
│      {                                                                        │
│        "job_id": 1,                                                          │
│        "title": "Backend Developer",                                         │
│        "description": "...",                                                 │
│        "skills_with_category": [...]                                        │
│      },                                                                       │
│      {                                                                        │
│        "job_id": 5,                                                          │
│        "title": "Backend Developer",                                         │
│        "description": "...",                                                 │
│        "skills_with_category": [...]                                        │
│      },                                                                       │
│      ...                                                                      │
│      (100 Backend Developer jobs total)                                     │
│    ],                                                                         │
│    "Frontend Developer": [95 jobs...],                                       │
│    "QA Engineer": [87 jobs...],                                              │
│    ...                                                                        │
│  }                                                                            │
│                                                                              │
│  File size: ~150-200 MB (all 452 jobs grouped)                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 SAMPLE (Example of one job group)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    "Backend Developer": [  ← Group key (job title)                          │
│      {                                                                        │
│        "job_id": 1,                                                          │
│        "title": "Backend Developer",                                         │
│        "description": "We are looking for experienced Backend Developer...  │
│                       Must know Java, Spring Boot, PostgreSQL, Docker...",  │
│        "skills_with_category": [                                            │
│          {"name": "java", "category": "Languages"},                         │
│          {"name": "spring", "category": "Backend_Frameworks"},              │
│          {"name": "postgresql", "category": "SQL_Databases"},               │
│          {"name": "docker", "category": "DevOps_Tools"},                    │
│          {"name": "aws", "category": "Cloud_Platforms"},                    │
│          {...}                                                               │
│        ]                                                                      │
│      },                                                                       │
│      {                                                                        │
│        "job_id": 2,                                                          │
│        "title": "Backend Developer",  ← Same title                           │
│        "description": "Join our team. Seeking Sr. Backend Engineer...      │
│                       Experience with Node.js, Express, MongoDB.",          │
│        "skills_with_category": [                                            │
│          {"name": "javascript", "category": "Languages"},                   │
│          {"name": "nodejs", "category": "Backend_Frameworks"},              │
│          {"name": "mongodb", "category": "NoSQL_Databases"},                │
│          {...}                                                               │
│        ]                                                                      │
│      },                                                                       │
│      ...                                                                      │
│      (98 more Backend Developer jobs)                                        │
│    ],                                                                         │
│    "Frontend Developer": [95 jobs...],                                       │
│    ...                                                                        │
│  }                                                                            │
│                                                                              │
│  KEY INSIGHT:                                                                 │
│  • 100 Backend Developer jobs in one group                                  │
│  • Each has different descriptions, different skills                        │
│  • BUT same job title → represents role consistency                         │
│  • Now LLM can read all 100 and infer importance patterns                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# Get output directory from environment or use current directory
OUTPUT_DIR = os.getenv('PIPELINE_OUTPUT_DIR')
if OUTPUT_DIR:
    OUTPUT_DIR = Path(OUTPUT_DIR)
else:
    OUTPUT_DIR = Path(__file__).parent

SKILL_CATEGORIES = [
    "Backend_Frameworks",
    "Cloud_DevOps_Tools",
    "Data_AI_Stack",
    "Databases_Storage",
    "Frontend_Frameworks",
    "Languages",
    "Methodologies",
    "Mobile_Frameworks",
    "Security_Tools",
    "Testing_Frameworks",
]

def group_jobs_by_keyword():
    """Group jobs by search_keyword for LLM analysis."""
    
    # 1️⃣ Load input data
    pipeline_mode = os.getenv('PIPELINE_MODE', 'test')
    input_dir = os.getenv('PIPELINE_INPUT_DIR')
    if input_dir:
        input_dir = Path(input_dir)
    else:
        input_dir = Path(__file__).parent
    
    # Determine input filename based on mode
    if pipeline_mode == 'real':
        input_file = input_dir / "jobs_from_database.json"
        print("📥 Loading jobs_from_database.json (REAL mode)...")
    else:
        input_file = input_dir / "test_sample_jobs.json"
        print("📥 Loading test_sample_jobs.json (TEST mode)...")
    
    if not input_file.exists():
        print(f"❌ Error: {input_file} not found!")
        print(f"   Mode: {pipeline_mode}")
        print(f"   Path: {input_dir}")
        return
    
    with open(input_file, 'r', encoding='utf-8') as f:
        all_jobs = json.load(f)
    
    print(f"✓ Loaded {len(all_jobs)} jobs from {input_file.name}")
    
    # 2️⃣ Group by search_keyword (skip null)
    print("\n📊 Grouping jobs by search_keyword...")
    
    groups = defaultdict(list)
    skipped_null = 0
    
    for job in all_jobs:
        keyword = job.get('search_keyword')
        
        if keyword is None or keyword == "":
            skipped_null += 1
            continue
        
        groups[keyword].append(job)
    
    print(f"✓ Found {len(groups)} unique search_keywords")
    print(f"✓ Skipped {skipped_null} jobs with null/empty search_keyword")
    
    # 3️⃣ Sort keywords by number of jobs (descending)
    sorted_keywords = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    print(f"\n📋 Search keywords by frequency:")
    for idx, (keyword, jobs) in enumerate(sorted_keywords):
        print(f"  {idx+1}. {keyword}: {len(jobs)} jobs")
    
    # 4️⃣ Show statistics
    total_jobs_in_groups = sum(len(jobs) for jobs in groups.values())
    avg_jobs_per_keyword = total_jobs_in_groups / len(groups) if groups else 0
    
    print(f"\n📊 Statistics:")
    print(f"   Total search_keywords: {len(groups)}")
    print(f"   Total jobs grouped: {total_jobs_in_groups}")
    print(f"   Jobs skipped (null keyword): {skipped_null}")
    print(f"   Avg jobs per keyword: {avg_jobs_per_keyword:.1f}")
    
    # 5️⃣ Save grouped jobs
    output_file = OUTPUT_DIR / "jobs_grouped_by_keyword.json"
    
    grouped_output = {keyword: jobs for keyword, jobs in sorted_keywords}
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(grouped_output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ SUCCESS: Grouped {len(groups)} search_keywords")
    print(f"📄 Output file: {output_file}")
    print(f"   File size: {output_file.stat().st_size / (1024*1024):.1f} MB")
    
    # 6️⃣ Show sample
    print("\n" + "="*80)
    print("📋 SAMPLE: First search_keyword group")
    print("="*80)
    
    if sorted_keywords:
        first_keyword, first_group = sorted_keywords[0]
        print(f"\nSearch Keyword: {first_keyword}")
        print(f"Total jobs: {len(first_group)}")
        
        print(f"\nFirst 3 jobs in this group:")
        for idx, job in enumerate(first_group[:3]):
            print(f"\n  Job {idx+1}:")
            print(f"    ID: {job.get('job_id')}")
            print(f"    Title: {job.get('title')}")
            print(f"    Keyword: {job.get('search_keyword')}")
            desc = job.get('description', '')
            if desc:
                print(f"    Description (first 100 chars): {desc[:100]}...")
            else:
                print(f"    Description: (empty)")
            
            skills = job.get('skills_with_category', [])
            categories_in_this_job = set(s.get('category') for s in skills)
            print(f"    Categories with skills: {', '.join(sorted(categories_in_this_job))}")
            print(f"    Total skills: {len(skills)}")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    group_jobs_by_keyword()
