"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║         SCRIPT 13: COMBINE LLM RANKINGS + FREQUENCY → FINAL WEIGHTS           ║
║         AHP calculation for each search_keyword group                         ║
╚═══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│ 🎯 MỤC TIÊU (OBJECTIVE)                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Từ LLM rankings cho mỗi search_keyword, tính final skill weights.          │
│                                                                              │
│  Quy trình:                                                                  │
│  1. Đọc category_rankings_by_keyword.json (từ Script 12)                   │
│  2. Đọc jobs_from_db.json để count skill frequency                         │
│  3. Foreach search_keyword:                                                 │
│     a. Get LLM category rankings (1-13)                                    │
│     b. Convert rankings to AHP scores                                       │
│     c. Count skill frequency per category                                  │
│     d. Final skill weight = category_importance × skill_frequency          │
│  4. Lưu results: final_skill_weights_with_llm.json                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📥 INPUT (2 files)                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. category_rankings_by_keyword.json (từ Script 12):                      │
│     {                                                                        │
│       "Backend": {                                                           │
│         "total_jobs": 120,                                                   │
│         "rankings": {                                                        │
│           "Languages": 1,                                                    │
│           "Backend_Frameworks": 2,                                           │
│           ...                                                                │
│         }                                                                     │
│       }                                                                       │
│     }                                                                         │
│                                                                              │
│  2. jobs_from_db.json (all 452 jobs):                                       │
│     [{job_id, title, search_keyword, skills_with_category, ...}, ...]     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📤 OUTPUT (final_skill_weights_with_llm.json)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    "Backend": {                                                             │
│      "total_jobs": 120,                                                      │
│      "llm_rankings": {                                                       │
│        "Languages": 1,                                                       │
│        "Backend_Frameworks": 2,                                             │
│        ...                                                                   │
│      },                                                                       │
│      "skill_weights": {                                                      │
│        "java": 0.15,      ← weight for java skill                           │
│        "spring": 0.12,                                                       │
│        "postgresql": 0.08,                                                   │
│        ...                                                                   │
│      }                                                                        │
│    },                                                                         │
│    "Frontend": {...},                                                        │
│    ...                                                                        │
│  }                                                                            │
│                                                                              │
│  File size: ~100-150 KB                                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 SAMPLE (Backend group calculation)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT from Script 12:                                                       │
│  {                                                                           │
│    "Backend": {                                                             │
│      "total_jobs": 120,                                                      │
│      "rankings": {                                                           │
│        "Languages": 1,                                                       │
│        "Backend_Frameworks": 2,                                             │
│        "SQL_Databases": 3,                                                  │
│        "DevOps_Tools": 4,                                                   │
│        "Cloud_Platforms": 5,                                                │
│        ...                                                                   │
│      }                                                                        │
│    }                                                                         │
│  }                                                                            │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  STEP 1: Convert rankings to importance scores                              │
│                                                                              │
│  For each category:                                                          │
│    score = (14 - rank) / 13  ← normalize to 0-1 range                       │
│                                                                              │
│  Languages:            (14 - 1) / 13 = 1.00                                 │
│  Backend_Frameworks:   (14 - 2) / 13 = 0.92                                 │
│  SQL_Databases:        (14 - 3) / 13 = 0.85                                 │
│  DevOps_Tools:         (14 - 4) / 13 = 0.77                                 │
│  Cloud_Platforms:      (14 - 5) / 13 = 0.69                                 │
│  ...                                                                          │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  STEP 2: Count skill frequency in Backend jobs                              │
│                                                                              │
│  Languages skills (found in 120 Backend jobs):                              │
│    - java: 100 jobs (100/120 = 83.3%)                                       │
│    - python: 45 jobs (45/120 = 37.5%)                                       │
│    - c#: 20 jobs (20/120 = 16.7%)                                           │
│                                                                              │
│  Backend_Frameworks skills:                                                 │
│    - spring: 85 jobs (85/120 = 70.8%)                                       │
│    - nodejs: 35 jobs (35/120 = 29.2%)                                       │
│    - dotnetcore: 15 jobs (15/120 = 12.5%)                                   │
│                                                                              │
│  SQL_Databases skills:                                                       │
│    - postgresql: 80 jobs (80/120 = 66.7%)                                   │
│    - mysql: 40 jobs (40/120 = 33.3%)                                        │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  STEP 3: Calculate final skill weights                                       │
│                                                                              │
│  For each skill:                                                             │
│    weight = category_score × skill_frequency                                │
│                                                                              │
│  java:         1.00 × 0.833 = 0.833                                         │
│  python:       1.00 × 0.375 = 0.375                                         │
│  c#:           1.00 × 0.167 = 0.167                                         │
│  spring:       0.92 × 0.708 = 0.651                                         │
│  nodejs:       0.92 × 0.292 = 0.268                                         │
│  dotnetcore:   0.92 × 0.125 = 0.115                                         │
│  postgresql:   0.85 × 0.667 = 0.567                                         │
│  mysql:        0.85 × 0.333 = 0.283                                         │
│  ...                                                                          │
│                                                                              │
│  Then normalize all skill weights to sum to 1.0                             │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  FINAL OUTPUT for Backend:                                                  │
│                                                                              │
│  {                                                                           │
│    "Backend": {                                                             │
│      "total_jobs": 120,                                                      │
│      "llm_rankings": {                                                       │
│        "Languages": 1,                                                       │
│        "Backend_Frameworks": 2,                                             │
│        "SQL_Databases": 3,                                                  │
│        "DevOps_Tools": 4,                                                   │
│        "Cloud_Platforms": 5,                                                │
│        ...                                                                   │
│      },                                                                       │
│      "category_scores": {                                                    │
│        "Languages": 1.00,                                                    │
│        "Backend_Frameworks": 0.92,                                           │
│        "SQL_Databases": 0.85,                                               │
│        "DevOps_Tools": 0.77,                                                 │
│        ...                                                                   │
│      },                                                                       │
│      "skill_weights": {                                                      │
│        "java": 0.15,       ← After normalization                            │
│        "spring": 0.12,                                                       │
│        "postgresql": 0.10,                                                   │
│        "python": 0.07,                                                       │
│        "nodejs": 0.06,                                                       │
│        "mysql": 0.05,                                                        │
│        ...                                                                   │
│      }                                                                        │
│    }                                                                          │
│  }                                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import json
import os
from pathlib import Path
from collections import defaultdict, Counter

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

# Skill weight for common skills (fixed)
COMMON_SKILL_WEIGHT = 0.02




def create_skill_id_mapping(all_jobs):
    """Create mapping of skill_name to skill_id (hash-based)."""
    
    skill_id_map = {}
    next_id = 1
    
    # Collect all unique skills
    for job in all_jobs:
        skills = job.get('skills_with_category', [])
        for skill in skills:
            if skill is None:
                continue
            skill_name = skill.get('name')
            if skill_name and skill_name.lower() not in skill_id_map:
                skill_id_map[skill_name.lower()] = next_id
                next_id += 1
    
    return skill_id_map


def load_skill_types():
    """
    Load skill types from cache (Specialized Skill vs Common skill).
    
    Returns:
        {skill_name_lower: {'id': int, 'name': str, 'type': str}}
        
    If cache doesn't exist, returns empty dict (will default to checking skills list).
    """
    cache_file = OUTPUT_DIR / "skill_types_cache.json"
    
    if not cache_file.exists():
        print("[!] Warning: skill_types_cache.json not found")
        print("    Please run: python prefetch_skill_types.py")
        print("    Proceeding without skill type classification...")
        return {}
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            skill_types = data.get('skill_types', {})
            print(f"✓ Loaded {len(skill_types)} skills from cache")
            
            # Count by type
            specialized = sum(1 for v in skill_types.values() if 'Specialized' in v.get('type', ''))
            common = sum(1 for v in skill_types.values() if 'Common' in v.get('type', ''))
            print(f"  • Specialized: {specialized}, Common: {common}")
            
            return skill_types
    except Exception as e:
        print(f"[!] Error loading skill cache: {e}")
        return {}


def calculate_final_weights():
    """Calculate final skill weights from LLM rankings and skill frequency."""
    
    # 1️⃣ Load input files
    print("📥 Loading input files...")
    
    rankings_file = OUTPUT_DIR / "category_rankings_by_keyword.json"
    
    # Get input directory for test_sample_jobs.json
    input_dir = os.getenv('PIPELINE_INPUT_DIR')
    if input_dir:
        input_dir = Path(input_dir)
    else:
        input_dir = Path(__file__).parent
    
    jobs_file = input_dir / "test_sample_jobs.json"
    
    if not rankings_file.exists():
        print(f"❌ Error: {rankings_file} not found!")
        print("   Please run Script 12 first: python 12_apply_llm_rankings.py")
        return
    
    if not jobs_file.exists():
        print(f"❌ Error: {jobs_file} not found!")
        return
    
    with open(rankings_file, 'r', encoding='utf-8') as f:
        category_rankings = json.load(f)
    
    with open(jobs_file, 'r', encoding='utf-8') as f:
        all_jobs = json.load(f)
    
    print(f"✓ Loaded {len(category_rankings)} keyword groups")
    print(f"✓ Loaded {len(all_jobs)} total jobs")
    
    # Load skill types (Specialized vs Common)
    print("\n📊 Loading skill classifications...")
    skill_types = load_skill_types()
    
    # Create skill_id mapping
    print("📊 Creating skill_id mapping...")
    skill_id_map = create_skill_id_mapping(all_jobs)
    print(f"✓ Mapped {len(skill_id_map)} unique skills")
    
    # 2️⃣ Calculate weights for each keyword group
    print("\n🔄 Calculating weights for each keyword...\n")
    
    results = []  # Changed from dict to list for database-friendly format
    
    for keyword, ranking_data in category_rankings.items():
        print(f"  Processing: {keyword}...", end='', flush=True)
        
        total_jobs_in_keyword = ranking_data.get('total_jobs', 0)
        llm_rankings = ranking_data.get('rankings', {})
        
        # Step 1: Convert rankings to importance scores (0-1 normalized)
        category_scores = {}
        for category, rank in llm_rankings.items():
            score = (14 - rank) / 13.0
            category_scores[category] = score
        
        # Step 2: Count skill frequencies for jobs with this keyword
        skill_frequencies = Counter()
        jobs_in_keyword = [j for j in all_jobs if j.get('search_keyword') == keyword]
        
        for job in jobs_in_keyword:
            skills = job.get('skills_with_category', [])
            if not skills:
                continue
            for skill in skills:
                if skill is None:
                    continue
                skill_name = skill.get('name')
                category = skill.get('category')
                if skill_name and category:
                    skill_frequencies[skill_name.lower()] += 1
        
        # Step 3: Calculate skill weights = category_score × skill_frequency
        # UPDATED: Differentiate between Specialized and Common skills
        skill_weights_list = []
        total_jobs = len(jobs_in_keyword) if jobs_in_keyword else 1
        skill_weights_raw = {}
        
        # First pass: calculate raw weights based on skill type
        for job in jobs_in_keyword:
            skills = job.get('skills_with_category', [])
            if not skills:
                continue
            for skill in skills:
                if skill is None:
                    continue
                skill_name = skill.get('name')
                category = skill.get('category')
                if not skill_name or not category:
                    continue
                
                skill_abr = skill.get('skill_abr') or skill_name.lower().replace(' ', '_')
                skill_name_lower = skill_name.lower()
                freq_ratio = skill_frequencies[skill_name_lower] / total_jobs
                
                # Determine skill type (Specialized or Common)
                skill_meta = skill_types.get(skill_name_lower, {})
                skill_type = skill_meta.get('type', 'Specialized Skill')
                
                # Calculate raw weight based on skill type
                if 'Common' in skill_type:
                    # Common skill: weight = 0.02 × frequency
                    raw_weight = COMMON_SKILL_WEIGHT * freq_ratio
                else:
                    # Specialized skill: weight = category_score × frequency
                    category_score = category_scores.get(category, 0)
                    raw_weight = category_score * freq_ratio
                
                if skill_name_lower not in skill_weights_raw:
                    skill_weights_raw[skill_name_lower] = {
                        'skill_name': skill_name_lower,
                        'skill_abr': skill_abr,
                        'category': category,
                        'skill_type': skill_type,
                        'weight': 0
                    }
                skill_weights_raw[skill_name_lower]['weight'] = max(
                    skill_weights_raw[skill_name_lower]['weight'], 
                    raw_weight
                )
        
        # Second pass: normalize to sum to 1 (all skills together)
        total_weight = sum(item['weight'] for item in skill_weights_raw.values())
        if total_weight > 0:
            for skill_name_lower, item in skill_weights_raw.items():
                normalized_weight = item['weight'] / total_weight
                skill_id = skill_id_map.get(skill_name_lower, 0)
                
                skill_weights_list.append({
                    "skill_id": skill_id,
                    "skill_name": item['skill_name'],
                    "skill_abr": item['skill_abr'],
                    "category": item['category'],
                    "skill_type": item['skill_type'],
                    "weight_wi": round(normalized_weight, 4)
                })
        
        # Sort by weight_wi descending
        skill_weights_list.sort(key=lambda x: x['weight_wi'], reverse=True)
        
        # Count skills by type
        specialized_count = sum(1 for s in skill_weights_list if 'Specialized' in s['skill_type'])
        common_count = sum(1 for s in skill_weights_list if 'Common' in s['skill_type'])
        
        print(f" ✓ ({len(skill_weights_list)} skills: {specialized_count} specialized, {common_count} common)")
        
        # Store result with database-friendly structure
        results.append({
            "search_group": keyword,
            "total_jobs_analyzed": total_jobs_in_keyword,
            "specialized_skills_count": specialized_count,
            "common_skills_count": common_count,
            "skill_weights": skill_weights_list,
            "metadata": {
                "llm_rankings": llm_rankings,
                "weight_group": {c: round((14-r)/13, 4) for c, r in llm_rankings.items()}
            }
        })
    
    # 3️⃣ Save results
    output_file = OUTPUT_DIR / "job_group_skill_weights.json"
    
    output_data = {
        "job_group_skill_weights": results
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ SUCCESS: Calculated weights for {len(results)} keyword groups")
    print(f"📄 Output file: {output_file}")
    print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
    
    # Also save old format for backward compatibility
    output_file_legacy = OUTPUT_DIR / "final_skill_weights_with_llm.json"
    legacy_data = {item['search_group']: {
        'total_jobs': item['total_jobs_analyzed'],
        'llm_rankings': item['metadata']['llm_rankings'],
        'weight_group': item['metadata']['weight_group'],
        'skill_weights': {skill['skill_name']: skill['weight_wi'] for skill in item['skill_weights']}
    } for item in results}
    
    with open(output_file_legacy, 'w', encoding='utf-8') as f:
        json.dump(legacy_data, f, indent=2, ensure_ascii=False)
    
    print(f"📄 Legacy format: {output_file_legacy}")
    
    # 4️⃣ Show sample results
    print("\n" + "="*80)
    print("📋 SAMPLE RESULTS (First 3 keywords)")
    print("="*80)
    
    for idx, item in enumerate(results[:3]):
        print(f"\n🔹 Search Group: {item['search_group']}")
        print(f"   Total jobs: {item['total_jobs_analyzed']}")
        print(f"   Specialized: {item['specialized_skills_count']}, Common: {item['common_skills_count']}")
        print(f"   Top 10 skills by weight_wi:")
        for skill in item['skill_weights'][:10]:
            skill_type_badge = "📘 SP" if 'Specialized' in skill['skill_type'] else "📗 CM"
            print(f"     • {skill_type_badge} {skill['skill_name']:20s} (ID: {skill['skill_id']:3d}, " +
                  f"Category: {skill['category']:20s}, Weight: {skill['weight_wi']:.4f})")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    calculate_final_weights()
