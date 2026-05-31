import os
import sys
import re
import json
import time
import csv

# Configure stdout and stderr to use UTF-8, avoiding UnicodeEncodeError on Windows console
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
import faiss
from dotenv import load_dotenv

# ==========================================
# CURATED ALIASES DICTIONARY - METHOD 6 OPTIMIZED
# ==========================================
# Layer 0: Curated aliases for known syntax variations & patterns
from Debug.alias_dictionaries import CURATED_ALIASES

CURATED_ALIASES_EXTENDED = {
    # Original 33 aliases
    'FastAPI': 'FastAPI',
    'RESTful APIs': 'RESTful API',
    'Prompt Engineering': 'Prompt Engineering',
    'System design': 'Systems Design',
    'OOP': 'Object-Oriented Programming (OOP)',
    'Indexing': 'Database Indexes',
    'JavaScript': 'JavaScript',
    'TypeScript': 'TypeScript',
    'Python 3': 'Python (Programming Language)',
    'Python3': 'Python (Programming Language)',
    'Py': 'Python (Programming Language)',
    'C#': 'C# (C Sharp)',
    'C Sharp': 'C# (C Sharp)',
    'C++': 'C++',
    'CPP': 'C++',
    'VB.NET': 'Visual Basic (VB .NET)',
    'MySQL DB': 'MySQL',
    'Postgres': 'PostgreSQL',
    'Postgre SQL': 'PostgreSQL',
    'Mongo': 'MongoDB',
    'Redis Cache': 'Redis',
    'Elasticsearch Engine': 'Elasticsearch',
    'AWS': 'Amazon Web Services (AWS)',
    'Azure': 'Microsoft Azure',
    'GCP': 'Google Cloud Platform',
    'Cloud Services': 'Cloud Computing',
    'REST': 'RESTful API',
    'GraphQL API': 'GraphQL',
    'SOAP': 'SOAP (Web Service)',
    'Web Services': 'Web Services',
    'Spring': 'Spring Boot',
    'Express.js': 'Express (Web Framework)',
    'Express': 'Express (Web Framework)',
    
    # Extended 16 aliases for problematic terms
    'Oracle Database': 'Oracle (Database)',
    'Oracle DB': 'Oracle (Database)',
    'Cloud Computing': 'Cloud Infrastructure',
    'Cloud Services': 'Cloud Infrastructure',
    'Banking Systems': 'Financial Services',
    'Financial Systems': 'Financial Services',
    'Source Code': 'Version Control System',
    'SCM': 'Version Control System',
    'Web Server': 'Web Services',
    'Web Services': 'Web Services',
    'Memory Management': 'Memory Management',
    'Memory Layout': 'Memory Management',
    'Data Warehouse': 'Data Warehousing',
    'Data Analytics': 'Data Analysis',
    'Analytics Platform': 'Data Analysis',
    'Business Analysis': 'Business Analyst',
    
    # Acronym & Domain Guardrail Mappings (No certifications)
    'WAF': 'Firewall',
    'MS Team': 'Virtual Teams',
    'MS Teams': 'Virtual Teams',
    'PowerBI': 'Microsoft Power Platform',
    'Power BI': 'Microsoft Power Platform',
    'Computer Vision': 'Computer Vision',
    'Snowflake Schema': 'Database Design',
    'Source Code Management': 'Version Control System',
    'CI/CD Pipelines': 'CI/CD',
    'Independent Work': 'Independent Thinking',
    'CSS': 'Cascading Style Sheets (CSS)',
    'CSS3': 'Cascading Style Sheets (CSS)',
    'SaaS': 'Software As A Service (SaaS)',
    'SIEM': 'Security Information And Event Management (SIEM)',
    'System Integration': 'Systems Design',
    'System Integration Services': 'Systems Design',
    'Stakeholder Management': 'Project Management',
    'Banking': 'Financial Services',
    'Banking Industry Knowledge': 'Financial Services',
    'Banking Operations': 'Financial Services Operations',
    'Big Data': 'AWS Big Data',
    'System Thinking': 'Systems Design',
    'Project Management Tools': 'Project Management',
}

# ==========================================
# 1. SETUP PATHS & CONFIGURATION
# ==========================================
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
LIGHTCAST_CSV_PATH = os.path.join(BASE_PATH, 'lib', 'Lightcast', 'lightcast.csv')
LABELED_SKILLS_PATH = os.path.join(BASE_PATH, 'raw_extracted_skills_fixed_type.csv')
TAXONOMY_PATH = os.path.join(BASE_PATH, 'taxonomy.json')
OUTPUT_PATH = os.path.join(BASE_PATH, 'matched_skills_with_taxonomy_extended.csv')

# Global variables
BI_MODEL = None
BASE_FAISS_INDEX = None
MAIN_FAISS_INDEX = None
LIGHTCAST_DF = None
EXACT_MATCH_DICT = None
LABELED_SKILL_TYPES = {}  # Store pre-labeled skill types
TAXONOMY_LOOKUP = {}  # Taxonomy canonical names
TAXONOMY_ALIASES = {}  # Taxonomy alias mappings

def load_labeled_skill_types(csv_path):
    """Load pre-labeled skill types from CSV"""
    labeled_types = {}
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            for _, row in df.iterrows():
                skill = str(row['Raw Skill']).strip()
                skill_type = str(row['Type']).strip().lower()
                labeled_types[skill] = skill_type
            print(f"✅ Loaded {len(labeled_types)} pre-labeled skill types from {csv_path}")
        except Exception as e:
            print(f"⚠️ Error loading labeled types: {e}")
    return labeled_types

# ==========================================
# 2. LOAD DATA & EXACT DICT BUILDERS
# ==========================================
def load_lightcast_data(csv_path):
    """Load Lightcast database and filter allowed skill types (Certifications Excluded)"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Lightcast CSV not found at: {csv_path}")
        
    print("⏳ Loading Lightcast CSV...")
    lightcast_df = pd.read_csv(csv_path, header=None)
    
    SKILL_COL_NAME = 1
    TYPE_COL = 4
    
    # Filter for relevant skill types (NO Certification)
    allowed_types = ['Hard Skill', 'Specialized Skill', 'Common skill', 'Common Skill']
    lightcast_df = lightcast_df[lightcast_df[TYPE_COL].isin(allowed_types)].reset_index(drop=True)
    print(f"✅ Loaded {len(lightcast_df)} skills from Lightcast CSV (Certifications Excluded)")
    return lightcast_df

def build_exact_match_dictionary(lightcast_df):
    """Build exact match dictionary mapping lowercase names to official Lightcast names"""
    SKILL_COL_NAME = 1
    exact_match_dict = {}
    for _, row in lightcast_df.iterrows():
        orig_name = str(row[SKILL_COL_NAME]).strip()
        orig_name_lower = orig_name.lower()
        exact_match_dict[orig_name_lower] = orig_name
        
        simplified = re.sub(r'\s*\(.*\)', '', orig_name).strip()
        simplified_lower = simplified.lower()
        if simplified_lower not in exact_match_dict:
            exact_match_dict[simplified_lower] = orig_name
    return exact_match_dict

# ==========================================
# 3. DYNAMIC RETRIEVAL & INDEXING MODULES
# ==========================================
def resolve_skill_type(raw_skill):
    """
    Use pre-labeled skill type from CSV if available,
    otherwise fall back to Base FAISS Index resolution
    """
    global LABELED_SKILL_TYPES, BI_MODEL, BASE_FAISS_INDEX, LIGHTCAST_DF
    
    raw_skill_str = str(raw_skill).strip()
    
    # First, check if skill has pre-labeled type
    if raw_skill_str in LABELED_SKILL_TYPES:
        labeled_type = LABELED_SKILL_TYPES[raw_skill_str]
        if 'common' in labeled_type.lower():
            return 'common_skill'
        else:
            return 'hard_skill'
    
    # Fallback: use FAISS-based resolution
    if BI_MODEL is None or BASE_FAISS_INDEX is None or LIGHTCAST_DF is None:
        raise ValueError("FAISS index and embedding model must be initialized before resolving skill types.")
        
    query_vector = BI_MODEL.encode([raw_skill_str], convert_to_numpy=True).astype('float32')
    faiss.normalize_L2(query_vector)
    
    scores, indices = BASE_FAISS_INDEX.search(query_vector, 1)
    top_idx = int(indices[0][0])
    
    if top_idx != -1:
        db_skill_type = str(LIGHTCAST_DF.iloc[top_idx][4]).strip()
        if db_skill_type.lower() == 'common skill':
            return 'common_skill'
            
    return 'hard_skill'

def build_faiss_indices(lightcast_df, bi_model):
    """
    Build Base and Main Indices.
    """
    print("\n📊 Initializing FAISS indices...")
    start_time = time.time()
    
    # 1. Base FAISS Index construction
    list_skills = lightcast_df[1].astype(str).tolist()
    print("⏳ Encoding base index (raw names)...")
    v_base = bi_model.encode(list_skills, convert_to_numpy=True, show_progress_bar=True).astype('float32')
    faiss.normalize_L2(v_base)
    
    base_index = faiss.IndexFlatIP(v_base.shape[1])
    base_index.add(v_base)
    print("✅ Base FAISS index populated")
    
    # 2. Main FAISS Index construction
    main_texts = []
    for _, row in lightcast_df.iterrows():
        skill_name = str(row[1]).strip()
        subcat = str(row[2]).strip()
        skill_type = str(row[4]).strip()
        
        if skill_type.lower() == 'common skill':
            main_texts.append(skill_name)
        else:
            main_texts.append(f"{skill_name} | Context: {subcat}")
            
    print(f"⏳ Encoding main index ({len(main_texts)} aligned entries)...")
    v_main = bi_model.encode(main_texts, convert_to_numpy=True, show_progress_bar=True).astype('float32')
    faiss.normalize_L2(v_main)
    
    main_index = faiss.IndexFlatIP(v_main.shape[1])
    main_index.add(v_main)
    print("✅ Main FAISS index populated")
    
    print(f"✅ FAISS indexing completed in {time.time() - start_time:.2f} seconds")
    return base_index, main_index

# ==========================================
# 4. SUPPORT FUNCTIONS FOR HYBRID SEARCH & CLEANING
# ==========================================
def clean_skill_universal(raw_skill):
    """Universal cleaning function standardizing abbreviations & framework names."""
    s = str(raw_skill).strip()
    s = re.sub(r'(?i)\b([a-zA-Z0-9]+)js\b', r'\1.js', s)
    s = re.sub(r'(?i)\brestful apis?\b', 'RESTful API', s)
    s = re.sub(r'(?i)\b\.net\b', '.NET Framework', s)
    s = re.sub(r'(?i)\bcss3\b', 'CSS', s)
    s = re.sub(r'(?i)\b(ms\s*sql|sql\s*server)\b', 'Microsoft SQL Servers', s)
    s = re.sub(r'(?i)\bms teams?\b', 'MS Teams', s)
    return s

def get_suggested_subcategory(raw_skill_str):
    """Context Alignment Protocol (CAP): Query Base FAISS to find standard subcategory."""
    global BI_MODEL, BASE_FAISS_INDEX, LIGHTCAST_DF
    if BI_MODEL is None or BASE_FAISS_INDEX is None or LIGHTCAST_DF is None:
        return None
    try:
        query_vector = BI_MODEL.encode([raw_skill_str], convert_to_numpy=True).astype('float32')
        faiss.normalize_L2(query_vector)
        scores, indices = BASE_FAISS_INDEX.search(query_vector, 1)
        top_idx = int(indices[0][0])
        if top_idx != -1:
            return str(LIGHTCAST_DF.iloc[top_idx][2]).strip()
    except Exception as e:
        pass
    return None

def get_char_ngram_similarity(s1, s2, n=3):
    """Jaccard character n-gram similarity to penalize mismatching contexts."""
    s1 = re.sub(r'[^a-z0-9]', '', s1.lower())
    s2 = re.sub(r'[^a-z0-9]', '', s2.lower())
    if not s1 or not s2:
        return 0.0
    if len(s1) < n or len(s2) < n:
        set1 = set(s1)
        set2 = set(s2)
    else:
        set1 = set(s1[i:i+n] for i in range(len(s1)-n+1))
        set2 = set(s2[i:i+n] for i in range(len(s2)-n+1))
        
    union = set1.union(set2)
    if not union:
        return 0.0
    return len(set1.intersection(set2)) / len(union)

# ==========================================
# 5. MATCH SKILL FUNCTION
# ==========================================
def match_skill(raw_skill, job_title=None, extracted_subcategory=None):
    """
    Matching pipeline with 4-stage Hybrid Matching:
    - Layer 0: Curated aliases
    - Layer 1: Exact matching
    - Layer 2: Hybrid Search with dynamic/manual type resolution & sparse Jaccard penalty
    - Layer 3: Dynamic Threshold filtering
    """
    global EXACT_MATCH_DICT, LIGHTCAST_DF, BI_MODEL, MAIN_FAISS_INDEX
    
    raw_skill_str = str(raw_skill).strip()
    cleaned_skill = clean_skill_universal(raw_skill_str)
    cleaned_lower = cleaned_skill.lower()
    
    # --- LAYER 0: Curated Aliases (Deterministic) ---
    if cleaned_skill in CURATED_ALIASES_EXTENDED:
        matched = CURATED_ALIASES_EXTENDED[cleaned_skill]
        matched_lower = matched.lower()
        if matched_lower in EXACT_MATCH_DICT:
            matched = EXACT_MATCH_DICT[matched_lower]
        return {
            'Raw Skill': raw_skill_str,
            'Matched Skill': matched,
            'Score': 1.0,
            'Match Type': 'Aliased',
            'Query Used': cleaned_skill,
            'Resolved Type': 'aliased'
        }
    
    # --- LAYER 1: Exact Match ---
    if cleaned_lower in EXACT_MATCH_DICT:
        return {
            'Raw Skill': raw_skill_str,
            'Matched Skill': EXACT_MATCH_DICT[cleaned_lower],
            'Score': 1.0,
            'Match Type': 'Exact',
            'Query Used': cleaned_skill,
            'Resolved Type': 'exact_match'
        }
        
    raw_simplified = re.sub(r'\s*\(.*\)', '', cleaned_skill).strip().lower()
    if raw_simplified in EXACT_MATCH_DICT:
        return {
            'Raw Skill': raw_skill_str,
            'Matched Skill': EXACT_MATCH_DICT[raw_simplified],
            'Score': 1.0,
            'Match Type': 'Exact',
            'Query Used': raw_simplified,
            'Resolved Type': 'exact_match'
        }
        
    # --- LAYER 2: Semantic Match with Hybrid Scoring ---
    # 1. Resolve Skill Type
    skill_class = resolve_skill_type(cleaned_skill)
    
    # 2. Build Query
    if skill_class == 'common_skill':
        query = cleaned_skill
    else:
        context_value = None
        if extracted_subcategory and str(extracted_subcategory).strip():
            context_value = str(extracted_subcategory).strip()
        elif job_title and str(job_title).strip():
            context_value = str(job_title).strip()
            
        if not context_value:
            context_value = get_suggested_subcategory(cleaned_skill)
            
        if context_value:
            query = f"{cleaned_skill} | Context: {context_value}"
        else:
            query = cleaned_skill
            
    # 3. Query Main FAISS Index (retrieve top 5 candidates)
    query_vector = BI_MODEL.encode([query], convert_to_numpy=True).astype('float32')
    faiss.normalize_L2(query_vector)
    
    scores, indices = MAIN_FAISS_INDEX.search(query_vector, 5)
    
    best_candidate_idx = -1
    best_candidate_score = -1.0
    
    # Dynamic Threshold
    word_count = len(cleaned_skill.split())
    char_len = len(cleaned_skill)
    is_acronym = (char_len <= 5 and cleaned_skill.isupper()) or (word_count == 1 and char_len <= 4)
    
    if is_acronym:
        dynamic_threshold = 0.80
    elif skill_class == 'hard_skill':
        dynamic_threshold = 0.70 if word_count < 3 else 0.62
    else:
        dynamic_threshold = 0.60
        
    for rank in range(5):
        idx = int(indices[0][rank])
        if idx == -1:
            continue
            
        dense_score = float(scores[0][rank])
        candidate_name = LIGHTCAST_DF.iloc[idx][1]
        candidate_type = str(LIGHTCAST_DF.iloc[idx][4]).strip().lower()
        
        # Enforce Type Constraint
        is_type_match = False
        if skill_class == 'common_skill' and 'common' in candidate_type:
            is_type_match = True
        elif skill_class == 'hard_skill' and 'common' not in candidate_type:
            is_type_match = True
            
        type_penalty = 1.0 if is_type_match else 0.85
        
        # Sparse character similarity
        sparse_score = get_char_ngram_similarity(cleaned_skill, candidate_name, n=3)
        
        # Combine dense and sparse scores
        hybrid_score = (0.85 * dense_score + 0.15 * sparse_score) * type_penalty
        
        if hybrid_score > best_candidate_score:
            best_candidate_score = hybrid_score
            best_candidate_idx = idx
            
    matched_skill = 'Unmatched'
    final_score = 0.0
    if best_candidate_idx != -1:
        matched_skill = LIGHTCAST_DF.iloc[best_candidate_idx][1]
        final_score = best_candidate_score
        
    match_type = 'Semantic (above threshold)' if final_score >= dynamic_threshold else 'Semantic (below threshold)'
    
    return {
        'Raw Skill': raw_skill_str,
        'Matched Skill': matched_skill,
        'Score': final_score,
        'Match Type': match_type,
        'Query Used': query,
        'Resolved Type': skill_class
    }

# ==========================================
# 6. TAXONOMY VALIDATION
# ==========================================
def load_taxonomy():
    """Load taxonomy.json and build lookup tables"""
    global TAXONOMY_LOOKUP, TAXONOMY_ALIASES
    
    if not os.path.exists(TAXONOMY_PATH):
        print(f"⚠️  Warning: taxonomy.json not found at {TAXONOMY_PATH}")
        return False
    
    try:
        with open(TAXONOMY_PATH, 'r', encoding='utf-8') as f:
            taxonomy = json.load(f)
        
        for cat in taxonomy.get('categories', {}).values():
            for subcat in cat.get('subcategories', {}).values():
                for skill in subcat.get('skills', []):
                    canonical = skill['canonical_name']
                    TAXONOMY_LOOKUP[canonical.lower()] = canonical
                    for alias in skill.get('aliases', []):
                        TAXONOMY_ALIASES[alias.lower()] = canonical
        print(f"✅ Taxonomy loaded: {len(TAXONOMY_LOOKUP)} canonical + {len(TAXONOMY_ALIASES)} aliases")
        return True
    except Exception as e:
        print(f"❌ Error loading taxonomy: {e}")
        return False

def apply_taxonomy_boosts(results_df):
    """Apply taxonomy validation to boost matching confidence"""
    if not TAXONOMY_LOOKUP and not TAXONOMY_ALIASES:
        return results_df
    
    df = results_df.copy()
    boosts = 0
    
    for idx, row in df.iterrows():
        raw_skill_lower = row['Raw Skill'].lower()
        if raw_skill_lower in TAXONOMY_LOOKUP:
            canonical = TAXONOMY_LOOKUP[raw_skill_lower]
            if canonical.lower() == row['Matched Skill'].lower():
                df.at[idx, 'Score'] = 1.0
                df.at[idx, 'Match Type'] = 'Taxonomy + Lightcast'
                df.at[idx, 'reason'] = 'taxonomy_validated'
                boosts += 1
        elif raw_skill_lower in TAXONOMY_ALIASES:
            canonical = TAXONOMY_ALIASES[raw_skill_lower]
            if canonical.lower() == row['Matched Skill'].lower():
                df.at[idx, 'Score'] = 1.0
                df.at[idx, 'Match Type'] = 'Taxonomy Alias + Lightcast'
                df.at[idx, 'reason'] = 'taxonomy_alias_validated'
                boosts += 1
    
    if boosts > 0:
        print(f"✅ Taxonomy validation: {boosts} matches boosted to 100% confidence")
    
    return df

# ==========================================
# 7. MAIN PIPELINE EXECUTION
# ==========================================
def main():
    global BI_MODEL, BASE_FAISS_INDEX, MAIN_FAISS_INDEX, LIGHTCAST_DF, EXACT_MATCH_DICT, LABELED_SKILL_TYPES, TAXONOMY_LOOKUP, TAXONOMY_ALIASES
    
    print("=== SKILL NORMALIZATION PIPELINE WITH HYBRID MATCHING ARCHITECTURE ===\n")
    
    # 1. Load pre-labeled skill types
    LABELED_SKILL_TYPES = load_labeled_skill_types(LABELED_SKILLS_PATH)
    
    # 2. Load Lightcast CSV
    LIGHTCAST_DF = load_lightcast_data(LIGHTCAST_CSV_PATH)
    
    # 3. Build Exact match lookup dictionary
    EXACT_MATCH_DICT = build_exact_match_dictionary(LIGHTCAST_DF)
    
    # 4. Initialize Bi-Encoder model
    print("🚀 Loading all-MiniLM-L6-v2 model...")
    BI_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    print(f"✅ Model loaded on device: {BI_MODEL.device}")
    
    # 5. Build FAISS Indices
    BASE_FAISS_INDEX, MAIN_FAISS_INDEX = build_faiss_indices(LIGHTCAST_DF, BI_MODEL)
    
    # 6. Load Taxonomy
    print("\n📚 Loading taxonomy.json for validation...")
    load_taxonomy()
    
    # 7. Load labeled skills directly from CSV
    print(f"\n📂 Loading skills from: {LABELED_SKILLS_PATH}")
    skills_df = pd.read_csv(LABELED_SKILLS_PATH)
    skills_list = skills_df['Raw Skill'].tolist()
    print(f"💼 Loaded {len(skills_list)} skills for matching")
    
    # 8. Perform matching
    results = []
    for idx, skill in enumerate(skills_list, 1):
        if idx % 200 == 0:
            print(f"  Processing: {idx}/{len(skills_list)}...")
        
        try:
            res = match_skill(
                raw_skill=skill,
                job_title=None,
                extracted_subcategory=None
            )
            results.append(res)
        except Exception as e:
            print(f"⚠️ Error matching skill '{skill}': {e}")
                
    # Convert results to DataFrame
    results_df = pd.DataFrame(results)
    
    # Apply Taxonomy Boosts
    print("\n🔍 Applying taxonomy validation...")
    results_df = apply_taxonomy_boosts(results_df)
    
    # Filter matches
    final_matches = results_df[~results_df['Match Type'].str.contains('below threshold')].copy()
    
    # Add reason column for compatibility
    final_matches['reason'] = final_matches['Match Type'].apply(
        lambda x: 'exact_match' if x in ['Exact', 'Aliased', 'Taxonomy + Lightcast', 'Taxonomy Alias + Lightcast'] else 'embedding_match'
    )
    
    print("\n📊 MATCHING STATISTICS (CERTIFICATIONS EXCLUDED):")
    print(f"Total skills tested: {len(results_df)}")
    print(f"Successfully matched: {len(final_matches)} ({len(final_matches)/len(results_df)*100:.1f}%)")
    
    # Print match types breakdown
    print("\n📋 Breakdown by Match Type:")
    match_counts = final_matches['Match Type'].value_counts()
    for match_type, count in match_counts.items():
        print(f"  - {match_type}: {count}")
    
    # Print skill type resolution breakdown
    print("\n🏷️ Breakdown by Resolved Type:")
    type_counts = final_matches['Resolved Type'].value_counts()
    for skill_type, count in type_counts.items():
        print(f"  - {skill_type}: {count}")
    
    # Show some examples of unmatched skills
    unmatched = results_df[results_df['Match Type'].str.contains('below threshold')]
    if len(unmatched) > 0:
        print(f"\n❌ Unmatched skills ({len(unmatched)} total):")
        sample_unmatched = unmatched.head(15)
        for _, row in sample_unmatched.iterrows():
            print(f"  - {row['Raw Skill']}: {row['Matched Skill']} (Score: {row['Score']:.4f})")
            
    # Save the unmatched skills log
    unmatched_path = os.path.join(BASE_PATH, 'unmatched_skills_log.csv')
    unmatched[['Raw Skill', 'Matched Skill', 'Score', 'Query Used', 'Resolved Type']].to_csv(unmatched_path, index=False, encoding='utf-8')
    print(f"\n💾 Saved unmatched log to: {unmatched_path}")
    
    # 9. Save output
    final_cols = ['Raw Skill', 'Matched Skill', 'Score', 'Match Type', 'Resolved Type', 'Query Used', 'reason']
    final_output_df = final_matches[final_cols]
    final_output_df.to_csv(OUTPUT_PATH, index=False, encoding='utf-8')
    print(f"💾 Exported results to: {OUTPUT_PATH}")
    print("=== PIPELINE EXECUTION COMPLETED ===")

if __name__ == '__main__':
    main()
