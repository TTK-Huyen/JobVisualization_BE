import math
from typing import List, Dict, Any

def normalize_skill_text(skill: str) -> str:
    return skill.strip().lower()

def cosine_binary(a: List[int], b: List[int]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def skill_similarity(cv_skills: List[str], target_skill: str) -> float:
    cv_set = {normalize_skill_text(s) for s in cv_skills}
    target = normalize_skill_text(target_skill)

    if target in cv_set:
        return 1.0

    synonyms = {
        "it support": ["technical support", "helpdesk"],
        "technical support": ["it support", "helpdesk"],
        "javascript": ["js"],
        "html": ["html5"],
        "css": ["css3"],
        "qa": ["tester", "qa tester"],
        "api testing": ["postman"],
        "networking": ["lan", "wan"],
    }

    related = synonyms.get(target, [])
    for s in related:
        if s in cv_set:
            return 0.75

    return 0.0

def build_job_weights(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    weighted_skills = []

    for skill in job.get("required_skills", []):
        weighted_skills.append({
            "skill": skill,
            "weight": 0.12
        })

    for skill in job.get("preferred_skills", []):
        weighted_skills.append({
            "skill": skill,
            "weight": 0.06
        })

    total = sum(x["weight"] for x in weighted_skills)
    if total > 0:
        for x in weighted_skills:
            x["weight"] = x["weight"] / total

    return weighted_skills

def compute_match_score(cv_profile: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    cv_skills = cv_profile.get("skills_extracted", []) + cv_profile.get("inferred_skills", [])
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
        elif sim_i < 0.3:
            status = "missing"
        else:
            status = "improvement"

        details.append({
            "skill": skill,
            "weight": round(weight, 4),
            "sim_i": round(sim_i, 4),
            "gap_i": round(gap_i, 4),
            "status": status
        })

    details.sort(key=lambda x: x["gap_i"], reverse=True)

    return {
        "cv_id": cv_profile.get("cv_id"),
        "job_id": job.get("job_id"),
        "job_title": job.get("job_title"),
        "match_score": round(total_score, 4),
        "match_percent": round(total_score * 100, 2),
        "top_gaps": details[:5],
        "all_skill_analysis": details
    }