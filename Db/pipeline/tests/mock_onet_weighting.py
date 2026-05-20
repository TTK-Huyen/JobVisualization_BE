#!/usr/bin/env python3
"""
Mock O*NET-weighting test for multiple job titles.

Generates 4 test cases (skill lists), assigns O*NET-like weights (simulated),
prints a Skill | Weight | Reason table, totals scores and verifies ranking
for each requested job title (default: AI, Software Eng, Cloud Eng, IT PM).
"""
from typing import List, Tuple


CASES = {
    "Case 1 - AI Specialist": [
        "Machine Learning",
        "Deep Learning",
        "PyTorch",
        "TensorFlow",
        "Computer Vision",
        "Natural Language Processing",
        "Reinforcement Learning",
        "Python",
        "Linear Algebra",
    ],
    "Case 2 - Data Engineer": [
        "SQL",
        "Apache Spark",
        "Hadoop",
        "Data Pipeline",
        "ETL",
        "Python",
        "Java",
        "Docker",
        "Cloud Computing (AWS)",
    ],
    "Case 3 - Software Developer": [
        "Java Spring Boot",
        "ReactJS",
        "HTML/CSS",
        "MySQL",
        "RESTful API",
        "Unit Testing",
        "Git",
        "JavaScript",
    ],
    "Case 4 - Noise/General": [
        "Microsoft Excel",
        "Adobe Photoshop",
        "Digital Marketing",
        "Sales",
        "Teamwork",
        "English Communication",
        "Video Editing",
    ],
}


# Simulated O*NET relevance mapping for AI job title.
# Values 0..1 where higher means more relevant to a job title.
ONET_SIM = {
    # AI-specific
    "machine learning": (1.00, "Core AI capability: ML algorithms and modeling"),
    "deep learning": (1.00, "Core deep learning models used in AI systems"),
    "pytorch": (0.95, "Popular DL framework used in AI research/production"),
    "tensorflow": (0.95, "Popular DL framework used in AI research/production"),
    "computer vision": (0.90, "High relevance for CV tasks in AI"),
    "natural language processing": (0.95, "Core AI subfield for language tasks"),
    "reinforcement learning": (0.90, "Relevant research/advanced AI technique"),
    "python": (0.85, "Primary implementation language for AI/ML"),
    "linear algebra": (0.80, "Foundational math for ML models"),

    # Data engineering / infra (medium relevance)
    "sql": (0.50, "Data retrieval is useful but not AI-specific"),
    "apache spark": (0.60, "Distributed data processing used before modeling"),
    "hadoop": (0.45, "Older big-data tech; medium relevance"),
    "data pipeline": (0.60, "Pipelines feed training data to models"),
    "etl": (0.55, "Data cleaning/ETL helps model training"),
    "java": (0.40, "Used in infra but less common in ML research"),
    "docker": (0.50, "Useful for deployment of AI models"),
    "cloud computing (aws)": (0.60, "Cloud infra is supportive for AI workloads"),

    # Software developer (low-to-medium)
    "java spring boot": (0.30, "Application development, not AI-specific"),
    "reactjs": (0.20, "Frontend framework; low relevance to AI model weights"),
    "html/css": (0.05, "Not relevant for AI model skills"),
    "mysql": (0.30, "DB knowledge helps but not core to AI"),
    "restful api": (0.20, "Deployment/serving concern; limited AI signal"),
    "unit testing": (0.10, "General software practice, little AI signal"),
    "git": (0.05, "Tooling only"),
    "javascript": (0.20, "General programming skill, low AI relevance"),

    # Noise / general
    "microsoft excel": (0.01, "Office skill — irrelevant for AI weighting"),
    "adobe photoshop": (0.01, "Creative tool — irrelevant for AI weighting"),
    "digital marketing": (0.01, "Domain skill — irrelevant for AI weighting"),
    "sales": (0.01, "Domain skill — irrelevant for AI weighting"),
    "teamwork": (0.02, "Soft skill — low signal for many technical roles"),
    "english communication": (0.02, "Soft skill — low signal for many technical roles"),
    "video editing": (0.01, "Creative tool — irrelevant for AI weighting"),
}


def adjust_weight_for_job(base: float, skill_key: str, job_title: str) -> float:
    jt = job_title.strip().lower()
    # Boosts for software engineer
    if "software engineer" in jt or jt.startswith("software"):
        if any(tok in skill_key for tok in ("java", "react", "spring", "javascript", "html", "css", "restful", "git", "unit testing", "mysql")):
            return min(1.0, base * 1.25)

    # Boosts for cloud systems engineer
    if "cloud" in jt or "systems engineer" in jt:
        if any(tok in skill_key for tok in ("cloud", "aws", "gcp", "azure", "docker", "kubernetes", "container")):
            return min(1.0, base * 1.30)
        if any(tok in skill_key for tok in ("data pipeline", "etl", "spark", "hadoop")):
            return min(1.0, base * 1.15)

    # Adjustments for IT project manager
    if "project manager" in jt or "project" in jt or "manager" in jt:
        if any(tok in skill_key for tok in ("project", "management", "teamwork", "communication", "manager", "lead")):
            return min(1.0, base * 1.4)
        if any(tok in skill_key for tok in ("machine", "deep", "pytorch", "tensorflow", "nlp", "computer vision", "reinforcement", "linear algebra")):
            return base * 0.6

    return base


def score_skill(skill: str, job_title: str) -> Tuple[float, str]:
    """Return (weight, reason) for a single skill using ONET_SIM heuristics,
    then adjust based on `job_title` signals."""
    key = skill.strip().lower()
    if key in ONET_SIM:
        w, r = ONET_SIM[key]
        w = float(w)
        w = adjust_weight_for_job(w, key, job_title)
        return w, r

    # fallback heuristics: substring matches for common tokens
    if "ml" in key or "machine" in key:
        base = 0.85
        return adjust_weight_for_job(base, key, job_title), "Contains 'machine'/ML token — high relevance heuristic"
    if "deep" in key:
        base = 0.90
        return adjust_weight_for_job(base, key, job_title), "Contains 'deep' — deep-learning relevance heuristic"
    if "python" in key:
        base = 0.80
        return adjust_weight_for_job(base, key, job_title), "Python detected — common AI language"
    if "data" in key or "pipeline" in key or "etl" in key:
        base = 0.55
        return adjust_weight_for_job(base, key, job_title), "Data engineering token — medium relevance"
    if "cloud" in key or "aws" in key or "gcp" in key or "azure" in key:
        base = 0.55
        return adjust_weight_for_job(base, key, job_title), "Cloud infra token — medium relevance"

    # default tiny weight for unknown/noise skills
    base = 0.02
    return adjust_weight_for_job(base, key, job_title), "Unknown/low relevance — default low signal"


def evaluate_case(name: str, skills: List[str], job_title: str) -> Tuple[float, List[Tuple[str, float, str]]]:
    rows = []
    total = 0.0
    for s in skills:
        w, reason = score_skill(s, job_title)
        rows.append((s, w, reason))
        total += w
    return total, rows


def print_table(name: str, rows: List[Tuple[str, float, str]], total: float) -> None:
    print("\n" + "=" * 60)
    print(f"{name}")
    print("=" * 60)
    print(f"{'Skill':40} | {'Weight':8} | Reason")
    print("-" * 60)
    for skill, w, reason in rows:
        print(f"{skill:40} | {w:8.2f} | {reason}")
    print("-" * 60)
    print(f"Total match score: {total:.2f}\n")


def main(job_titles: List[str] = None):
    # Default job titles to evaluate
    if job_titles is None:
        job_titles = [
            "Artificial Intelligence Engineer",
            "Software Engineer",
            "Cloud Systems Engineer",
            "IT Project Manager",
        ]

    for jt in job_titles:
        print("\n" + "#" * 80)
        print(f"Evaluating for job title: {jt}")
        print("#" * 80)
        totals = []
        for name, skills in CASES.items():
            total, rows = evaluate_case(name, skills, jt)
            print_table(name, rows, total)
            totals.append((name, total))

        ordered = sorted(totals, key=lambda x: x[1], reverse=True)
        print("Ranking by total match score:")
        for idx, (name, total) in enumerate(ordered, start=1):
            print(f"  {idx}. {name}: {total:.2f}")

        print("\nExpected preferred ordering (example): Case1 > Case2 > Case3 > Case4")


if __name__ == '__main__':
    import sys

    # allow passing job titles on the command line
    if len(sys.argv) > 1:
        main(sys.argv[1:])
    else:
        main()
