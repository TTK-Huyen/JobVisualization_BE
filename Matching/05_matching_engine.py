import json
from pathlib import Path
from typing import List, Dict, Any


PROJECT_DIR = Path(__file__).resolve().parent
CV_INPUT_PATH = PROJECT_DIR / "cv_profiles_baseline.json"
JOB_INPUT_PATH = PROJECT_DIR / "jobs_from_db.json"
OUTPUT_PATH = PROJECT_DIR / "matching_results.json"
from constants import ALL_SKILLS, HELPDESK_SKILLS, JOB_CATEGORIES

def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def normalize_skill_text(text: str) -> str:
    return text.strip().lower().replace("-", " ").replace("_", " ")

CANONICAL_SKILL_MAP = {
    "js": "javascript",
    "html5": "html",
    "css3": "css",
    "qa tester": "qa engineer",
    "tester": "software tester",
    "helpdesk": "it support",
    "technical support": "it support",
    "postman": "api testing",
    "lan": "networking",
    "wan": "networking",
}

ALL_SKILLS_NORMALIZED = {
    normalize_skill_text(skill): skill
    for skill in ALL_SKILLS
}

def canonicalize_skill(skill: str) -> str:
    key = normalize_skill_text(skill)
    if key in CANONICAL_SKILL_MAP:
        key = CANONICAL_SKILL_MAP[key]

    if key in ALL_SKILLS_NORMALIZED:
        return ALL_SKILLS_NORMALIZED[key]

    return skill.strip()


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []

    for item in items:
        cleaned = (item or "").strip()
        key = normalize_skill_text(cleaned)

        if key and key not in seen:
            seen.add(key)
            result.append(cleaned)

    return result


def is_same_job_family(cv_title: str, job_title: str) -> bool:
    cv_title_norm = normalize_text(cv_title)
    job_title_norm = normalize_text(job_title)

    if not cv_title_norm:
        return True

    tester_keywords = [
        "tester", "qa", "quality assurance", "quality control",
        "qc", "test engineer", "software test"
    ]

    frontend_keywords = [
        "front-end", "frontend", "front end", "web developer",
        "ui developer", "react", "vue", "javascript"
    ]

    helpdesk_keywords = [
        "helpdesk", "it support", "technical support", "desktop support",
        "system support", "service desk", "support engineer"
    ]

    if any(k in cv_title_norm for k in ["tester", "qa", "quality assurance"]):
        return any(k in job_title_norm for k in tester_keywords)

    if any(k in cv_title_norm for k in ["front-end", "frontend", "front end"]):
        return any(k in job_title_norm for k in frontend_keywords)

    if any(k in cv_title_norm for k in ["helpdesk", "support"]):
        return any(k in job_title_norm for k in helpdesk_keywords)

    return True


def skill_similarity(cv_skills: List[str], target_skill: str) -> float:
    cv_set = {normalize_skill_text(canonicalize_skill(skill)) for skill in cv_skills}
    target = normalize_skill_text(canonicalize_skill(target_skill))

    if not target:
        return 0.0

    if target in cv_set:
        return 1.0

    related_groups = [
        {"it support", "technical support", "helpdesk", "troubleshooting"},
        {"javascript", "js"},
        {"html", "html5"},
        {"css", "css3"},
        {"qa", "qa engineer", "software tester", "tester", "qa tester"},
        {"api testing", "postman"},
        {"networking", "lan", "wan"},
    ]

    for group in related_groups:
        if target in group and cv_set.intersection(group):
            return 0.75

    return 0.0


def build_job_weights(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_skills = job.get("skills_extracted", [])
    job_skills = unique_keep_order([canonicalize_skill(skill) for skill in raw_skills])

    if not job_skills:
        return []

    equal_weight = 1.0 / len(job_skills)

    weighted_skills = []
    for skill in job_skills:
        weighted_skills.append({
            "skill": skill,
            "weight": equal_weight
        })

    return weighted_skills


def compute_match_score(cv_profile: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    cv_skills = unique_keep_order([
        canonicalize_skill(skill)
        for skill in (
            cv_profile.get("skills_extracted", []) +
            cv_profile.get("inferred_skills", [])
        )
    ])

    weighted_skills = build_job_weights(job)

    details = []
    total_score = 0.0

    for item in weighted_skills:
        skill = item["skill"]
        weight = item["weight"]
        sim_i = skill_similarity(cv_skills, skill)
        gap_i = weight * (1 - sim_i)

        total_score += weight * sim_i

        if sim_i >= 0.75:
            status = "matched"
        elif sim_i > 0.0:
            status = "improvement"
        else:
            status = "missing"

        details.append({
            "skill": skill,
            "weight": round(weight, 4),
            "sim_i": round(sim_i, 4),
            "gap_i": round(gap_i, 4),
            "status": status
        })

    details.sort(key=lambda item: item["gap_i"], reverse=True)

    return {
        "cv_id": cv_profile.get("cv_id"),
        "file_name": cv_profile.get("file_name"),
        "candidate_name": cv_profile.get("name"),
        "candidate_title": cv_profile.get("title"),
        "job_title": job.get("title", ""),
        "company_name": job.get("company_name", ""),
        "job_url": job.get("job_url", ""),
        "match_score": round(total_score, 4),
        "match_percent": round(total_score * 100, 2),
        "top_gaps": details[:5],
        "all_skill_analysis": details
    }

def match_one_cv_with_all_jobs(
    cv_profile: Dict[str, Any],
    jobs: List[Dict[str, Any]],
    top_k: int = 5
) -> List[Dict[str, Any]]:
    results = []
    cv_title = cv_profile.get("title", "")

    for job in jobs:
        job_title = job.get("title", "")

        if not is_same_job_family(cv_title, job_title):
            continue

        result = compute_match_score(cv_profile, job)

        
        results.append(result)

    results.sort(key=lambda item: item["match_score"], reverse=True)
    return results[:top_k]


def load_json(file_path: Path):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def main():
    if not CV_INPUT_PATH.exists():
        print(f"CV input file not found: {CV_INPUT_PATH}")
        return

    if not JOB_INPUT_PATH.exists():
        print(f"Job input file not found: {JOB_INPUT_PATH}")
        return

    cv_profiles = load_json(CV_INPUT_PATH)
    jobs = load_json(JOB_INPUT_PATH)

    if not isinstance(cv_profiles, list):
        print("Invalid CV input format: expected a list")
        return

    if not isinstance(jobs, list):
        print("Invalid job input format: expected a list")
        return

    final_results = []

    for cv in cv_profiles:
        top_matches = match_one_cv_with_all_jobs(cv, jobs, top_k=5)

        final_results.append({
            "cv_id": cv.get("cv_id"),
            "file_name": cv.get("file_name"),
            "name": cv.get("name"),
            "title": cv.get("title"),
            "skills_extracted": cv.get("skills_extracted", []),
            "inferred_skills": cv.get("inferred_skills", []),
            "top_matches": top_matches
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(final_results, file, ensure_ascii=False, indent=2)

    print(f"Saved matching results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()