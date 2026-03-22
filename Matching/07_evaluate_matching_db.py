import json
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List

PROJECT_DIR = Path(__file__).resolve().parent
JOBS_PATH = PROJECT_DIR / "jobs_from_db.json"
RESULTS_PATH = PROJECT_DIR / "matching_results.json"
REPORT_JSON_PATH = PROJECT_DIR / "matching_db_evaluation_report.json"
REPORT_MD_PATH = PROJECT_DIR / "matching_db_evaluation_report.md"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def detect_family(title: str) -> str:
    text = normalize_text(title)

    tester_keywords = [
        "tester", "qa", "quality assurance", "quality control", "qc", "test engineer"
    ]
    frontend_keywords = [
        "front-end", "frontend", "front end", "ui", "web", "react", "vue", "angular", "javascript"
    ]
    helpdesk_keywords = [
        "helpdesk", "it support", "technical support", "service desk", "support engineer"
    ]

    if any(keyword in text for keyword in tester_keywords):
        return "tester"

    if any(keyword in text for keyword in frontend_keywords):
        return "frontend"

    if any(keyword in text for keyword in helpdesk_keywords):
        return "helpdesk"

    return "other"


def summarize_job_data_quality(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_jobs = len(jobs)
    skill_counts = [len((job or {}).get("skills_extracted") or []) for job in jobs]

    jobs_without_skills = sum(1 for count in skill_counts if count == 0)
    jobs_sparse_skills = sum(1 for count in skill_counts if count <= 3)
    jobs_single_skill = sum(1 for count in skill_counts if count == 1)

    return {
        "total_jobs": total_jobs,
        "jobs_without_skills": jobs_without_skills,
        "jobs_without_skills_ratio": round(jobs_without_skills / total_jobs if total_jobs else 0.0, 4),
        "jobs_sparse_skills": jobs_sparse_skills,
        "jobs_sparse_skills_ratio": round(jobs_sparse_skills / total_jobs if total_jobs else 0.0, 4),
        "jobs_single_skill": jobs_single_skill,
        "jobs_single_skill_ratio": round(jobs_single_skill / total_jobs if total_jobs else 0.0, 4),
        "skill_count_stats": {
            "min": min(skill_counts) if skill_counts else 0,
            "mean": round(mean(skill_counts), 2) if skill_counts else 0.0,
            "median": round(median(skill_counts), 2) if skill_counts else 0.0,
            "max": max(skill_counts) if skill_counts else 0,
        },
    }


def build_job_skill_lookup(jobs: List[Dict[str, Any]]) -> Dict[str, int]:
    lookup: Dict[str, int] = {}

    for job in jobs:
        title = (job or {}).get("title") or ""
        company_name = (job or {}).get("company_name") or ""
        key = f"{title}||{company_name}"
        lookup[key] = len((job or {}).get("skills_extracted") or [])

    return lookup


def summarize_matching_behavior(
    matching_results: List[Dict[str, Any]],
    job_skill_lookup: Dict[str, int],
) -> Dict[str, Any]:
    all_scores: List[float] = []
    top1_scores: List[float] = []
    cv_count_with_matches = 0
    family_consistent_top1 = 0
    overconfident_top1 = 0
    cv_summaries: List[Dict[str, Any]] = []

    for cv in matching_results:
        cv_title = cv.get("title", "")
        cv_family = detect_family(cv_title)
        top_matches = cv.get("top_matches", []) or []

        if top_matches:
            cv_count_with_matches += 1

        for match in top_matches:
            all_scores.append(float(match.get("match_score", 0.0)))

        top1 = top_matches[0] if top_matches else None
        if top1 is not None:
            top1_score = float(top1.get("match_score", 0.0))
            top1_scores.append(top1_score)

            top1_family = detect_family(top1.get("job_title", ""))
            family_ok = (cv_family == "other") or (cv_family == top1_family)
            if family_ok:
                family_consistent_top1 += 1

            key = f"{top1.get('job_title', '')}||{top1.get('company_name', '')}"
            top1_skill_count = job_skill_lookup.get(key, 0)
            is_overconfident = top1_score >= 0.95 and top1_skill_count <= 1
            if is_overconfident:
                overconfident_top1 += 1

            cv_summaries.append({
                "cv_id": cv.get("cv_id"),
                "cv_title": cv_title,
                "cv_family": cv_family,
                "top1_job_title": top1.get("job_title", ""),
                "top1_company_name": top1.get("company_name", ""),
                "top1_score": round(top1_score, 4),
                "top1_skill_count": top1_skill_count,
                "family_consistent": family_ok,
                "overconfident_single_skill": is_overconfident,
            })

    low_confidence_ratio = (
        sum(1 for score in top1_scores if score < 0.3) / len(top1_scores)
        if top1_scores else 1.0
    )

    return {
        "total_cvs": len(matching_results),
        "cvs_with_matches": cv_count_with_matches,
        "total_scored_matches": len(all_scores),
        "score_stats": {
            "min": round(min(all_scores), 4) if all_scores else 0.0,
            "mean": round(mean(all_scores), 4) if all_scores else 0.0,
            "median": round(median(all_scores), 4) if all_scores else 0.0,
            "max": round(max(all_scores), 4) if all_scores else 0.0,
        },
        "top1_stats": {
            "count": len(top1_scores),
            "mean": round(mean(top1_scores), 4) if top1_scores else 0.0,
            "low_confidence_ratio": round(low_confidence_ratio, 4),
            "family_consistency_ratio": round(
                family_consistent_top1 / len(top1_scores) if top1_scores else 0.0,
                4,
            ),
            "overconfident_single_skill_count": overconfident_top1,
        },
        "per_cv_summary": cv_summaries,
    }


def evaluate_fit(
    data_quality: Dict[str, Any],
    behavior: Dict[str, Any],
) -> Dict[str, Any]:
    reasons: List[str] = []
    recommendations: List[str] = []

    no_skill_ratio = data_quality["jobs_without_skills_ratio"]
    sparse_ratio = data_quality["jobs_sparse_skills_ratio"]
    low_conf_ratio = behavior["top1_stats"]["low_confidence_ratio"]
    overconf_count = behavior["top1_stats"]["overconfident_single_skill_count"]

    if no_skill_ratio > 0.30:
        reasons.append(
            f"Ty le job khong co skills_extracted qua cao: {no_skill_ratio:.2%} (>30%)."
        )

    if sparse_ratio > 0.50:
        reasons.append(
            f"Ty le job co <=3 skills qua cao: {sparse_ratio:.2%} (>50%)."
        )

    if low_conf_ratio > 0.50:
        reasons.append(
            f"Hon 50% top-1 co diem <0.3 ({low_conf_ratio:.2%}), matching chua du tin cay."
        )

    if overconf_count > 0:
        reasons.append(
            "Co truong hop diem top-1 >=0.95 voi job chi co 1 skill, gay ao tuong phu hop."
        )

    recommendations.append(
        "Bo qua job co skills_extracted rong truoc khi ranking (hoac gan confidence=0)."
    )
    recommendations.append(
        "Dat nguong toi thieu so luong skill cho job (de xuat >=4) de duoc dua vao matching."
    )
    recommendations.append(
        "Them thanh phan diem theo title similarity va seniority thay vi chi dua vao overlap skill."
    )
    recommendations.append(
        "Ap dung do tin cay (confidence score) de canh bao ket qua diem cao nhung du lieu mong."
    )

    is_fit = len(reasons) == 0

    return {
        "fit_for_database_now": is_fit,
        "overall_decision": "PHU_HOP" if is_fit else "CHUA_PHU_HOP",
        "reasons": reasons,
        "recommendations": recommendations,
    }


def render_markdown_report(
    data_quality: Dict[str, Any],
    behavior: Dict[str, Any],
    verdict: Dict[str, Any],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: List[str] = []
    lines.append("# Matching Evaluation Report (Database)")
    lines.append("")
    lines.append(f"- Generated at: {now}")
    lines.append(f"- Overall decision: **{verdict['overall_decision']}**")
    lines.append(f"- Fit for DB now: **{verdict['fit_for_database_now']}**")
    lines.append("")

    lines.append("## 1) Data Quality (jobs_from_db.json)")
    lines.append(f"- Total jobs: {data_quality['total_jobs']}")
    lines.append(
        f"- Jobs without skills_extracted: {data_quality['jobs_without_skills']} ({data_quality['jobs_without_skills_ratio']:.2%})"
    )
    lines.append(
        f"- Jobs with <=3 skills: {data_quality['jobs_sparse_skills']} ({data_quality['jobs_sparse_skills_ratio']:.2%})"
    )
    lines.append(
        f"- Jobs with exactly 1 skill: {data_quality['jobs_single_skill']} ({data_quality['jobs_single_skill_ratio']:.2%})"
    )
    lines.append(
        "- Skill count stats: "
        f"min={data_quality['skill_count_stats']['min']}, "
        f"mean={data_quality['skill_count_stats']['mean']}, "
        f"median={data_quality['skill_count_stats']['median']}, "
        f"max={data_quality['skill_count_stats']['max']}"
    )
    lines.append("")

    lines.append("## 2) Matching Behavior (matching_results.json)")
    lines.append(f"- Total CVs: {behavior['total_cvs']}")
    lines.append(f"- CVs with at least 1 match: {behavior['cvs_with_matches']}")
    lines.append(f"- Total scored matches (top-k aggregate): {behavior['total_scored_matches']}")
    lines.append(
        "- Score stats: "
        f"min={behavior['score_stats']['min']}, "
        f"mean={behavior['score_stats']['mean']}, "
        f"median={behavior['score_stats']['median']}, "
        f"max={behavior['score_stats']['max']}"
    )
    lines.append(
        "- Top-1 stats: "
        f"count={behavior['top1_stats']['count']}, "
        f"mean={behavior['top1_stats']['mean']}, "
        f"low_confidence_ratio(<0.3)={behavior['top1_stats']['low_confidence_ratio']:.2%}, "
        f"family_consistency_ratio={behavior['top1_stats']['family_consistency_ratio']:.2%}, "
        f"overconfident_single_skill_count={behavior['top1_stats']['overconfident_single_skill_count']}"
    )
    lines.append("")

    lines.append("## 3) Verdict")
    if verdict["reasons"]:
        for reason in verdict["reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- Khong phat hien rui ro lon o bo du lieu hien tai.")
    lines.append("")

    lines.append("## 4) Recommendations")
    for rec in verdict["recommendations"]:
        lines.append(f"- {rec}")
    lines.append("")

    lines.append("## 5) Per-CV Top-1 Snapshot")
    for item in behavior["per_cv_summary"]:
        lines.append(
            "- "
            f"{item['cv_id']} | cv={item['cv_title']} | top1={item['top1_job_title']} | "
            f"score={item['top1_score']} | top1_skill_count={item['top1_skill_count']} | "
            f"family_consistent={item['family_consistent']} | "
            f"overconfident_single_skill={item['overconfident_single_skill']}"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    if not JOBS_PATH.exists():
        raise FileNotFoundError(f"Missing file: {JOBS_PATH}")
    if not RESULTS_PATH.exists():
        raise FileNotFoundError(f"Missing file: {RESULTS_PATH}")

    jobs = load_json(JOBS_PATH)
    matching_results = load_json(RESULTS_PATH)

    if not isinstance(jobs, list):
        raise ValueError("jobs_from_db.json must be a JSON array")
    if not isinstance(matching_results, list):
        raise ValueError("matching_results.json must be a JSON array")

    jobs = [job for job in jobs if isinstance(job, dict)]
    matching_results = [item for item in matching_results if isinstance(item, dict)]

    data_quality = summarize_job_data_quality(jobs)
    job_skill_lookup = build_job_skill_lookup(jobs)
    behavior = summarize_matching_behavior(matching_results, job_skill_lookup)
    verdict = evaluate_fit(data_quality, behavior)

    report_obj = {
        "data_quality": data_quality,
        "matching_behavior": behavior,
        "verdict": verdict,
    }

    REPORT_JSON_PATH.write_text(
        json.dumps(report_obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    REPORT_MD_PATH.write_text(
        render_markdown_report(data_quality, behavior, verdict),
        encoding="utf-8",
    )

    print(f"Saved JSON report to: {REPORT_JSON_PATH}")
    print(f"Saved Markdown report to: {REPORT_MD_PATH}")
    print(f"Decision: {verdict['overall_decision']}")


if __name__ == "__main__":
    main()
