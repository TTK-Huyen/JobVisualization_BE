"""
Xử lý output_2_sections.json: tạo skills_list sạch cho STEP 3
"""

import json
from pathlib import Path

def prepare_step3_input(input_file="output/output_2_sections.json", output_file="output/output_2_with_skills_list.json"):
    """
    Đọc output_2, extract skill_name từ nested structure, tạo skills_list sạch
    """
    print(f"[*] Reading: {input_file}")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    if not isinstance(jobs, list):
        jobs = [jobs]
    
    print(f"[*] Processing {len(jobs)} jobs...")
    
    for idx, job in enumerate(jobs, 1):
        # Get extracted_skills (nested structure: list with dict containing 'is_it_job' and 'extracted_skills')
        extracted_skills = job.get('extracted_skills', [])
        
        skills_list = []
        
        # Case 1: extracted_skills is a list where first item is dict with nested 'extracted_skills'
        if isinstance(extracted_skills, list) and len(extracted_skills) > 0:
            first_item = extracted_skills[0]
            if isinstance(first_item, dict) and 'extracted_skills' in first_item:
                # Nested structure: list[0]['extracted_skills'][x]['skill_name_eng' or 'skill_name']
                nested_skills = first_item.get('extracted_skills', [])
                for skill_item in nested_skills:
                    if isinstance(skill_item, dict):
                        # Prefer English translation (skill_name_eng) for better embedding matching
                        skill_name = skill_item.get('skill_name_eng') or skill_item.get('skill_name', '')
                        if skill_name:
                            skills_list.append(skill_name)
                    elif isinstance(skill_item, str):
                        skills_list.append(skill_item)
            else:
                # Direct list of skill dicts
                for skill_item in extracted_skills:
                    if isinstance(skill_item, dict):
                        # Prefer English translation
                        skill_name = skill_item.get('skill_name_eng') or skill_item.get('skill_name', '')
                        if skill_name:
                            skills_list.append(skill_name)
                    elif isinstance(skill_item, str):
                        skills_list.append(skill_item)
        
        # Add skills_list to job
        job['skills_list'] = skills_list
        
        if idx % 10 == 0 or idx == 1:
            print(f"  Job {idx}: {len(skills_list)} skills → {skills_list[:3]}...")
    
    # Save output
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    
    print(f"\n[+] Output saved: {output_file}")
    print(f"   Total: {len(jobs)} jobs with skills_list")

if __name__ == "__main__":
    prepare_step3_input()
