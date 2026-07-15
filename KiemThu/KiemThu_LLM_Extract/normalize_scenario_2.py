import json
import os
import sys
import importlib.util
from pathlib import Path
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

# 1. Define paths
workspace_root = Path(r"f:\HCMUS_KH\LuanVan\JobVisualization_BE")
script_dir = workspace_root / "KiemThu" / "KiemThu_LLM_Extract"
normalize_script_path = workspace_root / "Db" / "pipeline" / "normalize" / "2_1_normalized_data" / "normalize_pipeline_v2.py"

# 2. Dynamic import of normalize_pipeline_v2.py
if not normalize_script_path.exists():
    print(f"❌ Error: normalize_pipeline_v2.py not found at {normalize_script_path}")
    sys.exit(1)

spec = importlib.util.spec_from_file_location("normalize_pipeline_v2", str(normalize_script_path))
norm_mod = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(normalize_script_path.parent))
sys.path.insert(0, str(workspace_root))
spec.loader.exec_module(norm_mod)

def main():
    # 3. Load DB credentials
    dotenv_path = workspace_root / "Db" / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
        
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL not set in environment or Db/.env")
        sys.exit(1)
        
    print("🔄 Connecting to DB and loading dictionaries...")
    skills = norm_mod.load_dictionary_from_db(db_url, "skills")
    benefits = norm_mod.load_dictionary_from_db(db_url, "benefits")
    db_skills_by_name = {row[1]: row[0] for row in skills}
    
    skills_with_meta = norm_mod.load_skills_metadata_from_db(db_url, "skills")
    
    allowed_types = {'Hard Skill', 'Specialized Skill', 'Common skill', 'Common Skill'}
    lightcast_skills = []
    lightcast_metadata = {}
    
    for sid, name, cat, stype in skills_with_meta:
        lightcast_metadata[name] = {
            "subcategory": cat,
            "type": stype
        }
        if stype in allowed_types and name:
            lightcast_skills.append(name)
            
    # Deduplicate allowed skills
    seen = set()
    lightcast_skills_dedup = []
    for s in lightcast_skills:
        if s not in seen:
            seen.add(s)
            lightcast_skills_dedup.append(s)
    lightcast_skills = lightcast_skills_dedup
    
    norm_mod.GLOBAL_LIGHTCAST_METADATA = lightcast_metadata
    
    lightcast_skill_map = []
    for name in lightcast_skills:
        sid = db_skills_by_name.get(name)
        if sid is not None:
            lightcast_skill_map.append((sid, name))
        else:
            lightcast_skill_map.append((-1, name))
            
    # 4. Load SentenceTransformer
    print("🔄 Initializing SentenceTransformer (all-MiniLM-L6-v2)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    # 5. Load or compute embeddings
    cache_dir = normalize_script_path.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lightcast_cache_file = cache_dir / "lightcast_embeddings_minilm.pkl"
    benefits_cache_file = cache_dir / "benefits_embedding.pkl"
    
    # Compute skills embeddings
    if lightcast_cache_file.exists():
        import pickle
        print(f"🔄 Loading cached Lightcast embeddings from: {lightcast_cache_file.name}")
        with open(lightcast_cache_file, "rb") as fh:
            lc_cache = pickle.load(fh)
        lightcast_emb = lc_cache.get("emb")
    else:
        print("🔄 Computing Lightcast embeddings...")
        lightcast_emb = norm_mod.compute_embeddings(model, lightcast_skills)
        with open(lightcast_cache_file, "wb") as fh:
            pickle.dump({"emb": lightcast_emb, "skills": lightcast_skills}, fh, protocol=4)
            
    # Compute benefits embeddings
    benefit_names = [b[1] for b in benefits]
    if benefits_cache_file.exists():
        import pickle
        with open(benefits_cache_file, "rb") as fh:
            be_cache = pickle.load(fh)
        benefits_emb = be_cache.get("emb")
    else:
        benefits_emb = norm_mod.compute_embeddings(model, benefit_names)
        with open(benefits_cache_file, "wb") as fh:
            pickle.dump({"emb": benefits_emb, "map": benefits}, fh, protocol=4)
            
    # Load mapped cache
    skills_cache_path = cache_dir / "mapped_skills_cache.json"
    mapping_cache = {}
    if skills_cache_path.exists():
        with skills_cache_path.open("r", encoding="utf-8") as fh:
            mapping_cache = json.load(fh)
            
    # Load pre-labeled types
    labeled_skills_path = normalize_script_path.parent / 'raw_extracted_skills_fixed_type.csv'
    if labeled_skills_path.exists():
        import csv
        with open(labeled_skills_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                skill = row.get('Raw Skill', '').strip()
                skill_type = row.get('Type', '').strip().lower()
                if skill:
                    norm_mod.GLOBAL_LABELED_SKILL_TYPES[skill] = skill_type

    # 6. Load input JDs
    input_file = script_dir / "pipeline_jds_output.json"
    if not input_file.exists():
        print(f"❌ Error: {input_file} not found.")
        sys.exit(1)
        
    with open(input_file, "r", encoding="utf-8") as f:
        jds = json.load(f)
        
    # Re-format each job for the normalizer
    norm_results = []
    print(f"🔄 Normalizing skills for {len(jds)} jobs...")
    
    for item in jds:
        url = item.get("url")
        skills = item.get("skills", [])
        
        # Prepare job dict
        job_dict = {
            "url": url,
            "title": "Software Engineer", # dummy title
            "extracted_skills": [{"skill_name": s} for s in skills]
        }
        
        # Normalize
        normalized_job = norm_mod.normalize_job(
            job=job_dict,
            skill_names=lightcast_skills,
            skill_emb=lightcast_emb,
            skill_map=lightcast_skill_map,
            benefit_names=benefit_names,
            benefit_emb=benefits_emb,
            benefit_map=benefits,
            model=model,
            threshold=0.5,
            top_k=10,
            disable_llm_rerank=True, # Disable LLM to run purely on FAISS/Cosine local algorithms
            mapping_cache=mapping_cache
        )
        
        # Post-process
        normalized_job = norm_mod.remove_unmapped_items(normalized_job)
        
        mapped_skills = normalized_job.get("normalized_skills", [])
        unmapped_skills = normalized_job.get("unmatched_skills", [])
        
        # Build lookup of results
        norm_map = {}
        for s_entry in mapped_skills:
            orig = s_entry["original"]
            mapped = s_entry["mapped_name"]
            norm_map[orig] = mapped
        for s_entry in unmapped_skills:
            orig = s_entry["original"]
            norm_map[orig] = None # meaning not normalized (unmatched)
            
        for s in skills:
            norm_results.append({
                "url": url,
                "skill_extract": s,
                "skill_normalize": norm_map.get(s, None)
            })
            
    # Save the output
    output_file = script_dir / "pipeline_normalization_output.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(norm_results, f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully normalized all skills and saved to: {output_file}")
    
    # Save mapping cache back
    try:
        with skills_cache_path.open("w", encoding="utf-8") as fh:
            json.dump(mapping_cache, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

if __name__ == "__main__":
    main()
