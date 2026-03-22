import json
import re
from pathlib import Path

from constants import SKILL_KEYWORDS, SKILL_KEYWORDS_EXTENDED, SKILL_KEYWORDS_EXTENDED_V2

PROJECT_DIR = Path(__file__).resolve().parent
BASE_DIR = PROJECT_DIR / "Dataset"
INPUT_PATH = BASE_DIR / "processed_jobs" / "jobs_ready.json"
OUTPUT_PATH = BASE_DIR / "processed_jobs" / "jobs_structured.json"

CANONICAL_SKILL_MAP = {
    "python": "Python",
    "django": "Django",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "rest api": "REST API",
    "aws": "AWS",
    "ci/cd": "CI/CD",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "mongodb": "MongoDB",
    "react": "React",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "sql": "SQL",
    "java": "Java",
    "c#": "C#",
    "selenium": "Selenium",
    "pytest": "Pytest",
    "splunk": "Splunk",
    "playwright": "Playwright",
    "cypress": "Cypress",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "jenkins": "Jenkins",
    "agile": "Agile",
    "scrum": "Scrum"
}

def flatten_skill_groups(*skill_dicts):
    skills = []
    for skill_dict in skill_dicts:
        for group in skill_dict.values():
            skills.extend(group)
    return sorted(set(skills))

ALL_CANONICAL_SKILLS = flatten_skill_groups(
    SKILL_KEYWORDS,
    SKILL_KEYWORDS_EXTENDED,
    SKILL_KEYWORDS_EXTENDED_V2
)

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def skill_found(text: str, skill: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)"
    return re.search(pattern, text) is not None

def extract_skills(requirement_text: str):
    text = normalize_text(requirement_text)
    found = []

    for skill in ALL_CANONICAL_SKILLS:
        if skill_found(text, skill):
            found.append(skill)

    return canonicalize_skills(found)

def canonicalize_skills(skills):
    cleaned = []
    seen = set()

    for skill in skills:
        normalized = skill.strip().lower()
        canonical = CANONICAL_SKILL_MAP.get(normalized, skill.strip())

        if canonical.lower() not in seen:
            cleaned.append(canonical)
            seen.add(canonical.lower())

    return sorted(cleaned, key=str.lower)

def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    results = []
    for job in jobs:
        req = job.get("requirements_text") or ""
        results.append({
            "title": job.get("title", ""),
            "company_name": job.get("company_name", ""),
            "job_url": job.get("job_url", ""),
            "skills_extracted": extract_skills(req),
            "requirement_text_raw": req
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Done: {len(results)} jobs")

if __name__ == "__main__":
    main()