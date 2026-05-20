from __future__ import annotations

import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("matching_cv.matching_engine")


def _build_prompt(job_title: str, skills: List[str]) -> str:
    skills_text = "\n".join(f"- {s}" for s in skills)
    prompt = (
        "Bạn là chuyên gia phân tích nghề nghiệp dựa trên khung tiêu chuẩn O*NET.\n"
        "Nhiệm vụ của bạn là đánh giá mức độ quan trọng (weight) của danh sách kỹ năng sau đây đối với vị trí "
        + job_title
        + ".\n"
        "Danh sách kỹ năng:\n"
        + skills_text
        + "\n\n"
        "Yêu cầu:\n"
        "Trả về trọng số từ 0.0 đến 1.0.\n"
        "Kỹ năng cốt lõi (Core/Hard Skills) theo O*NET cho vị trí này phải có trọng số > 0.8.\n"
        "Kỹ năng bổ trợ hoặc quá phổ thông (Soft skills/Office) có trọng số từ 0.2 - 0.5.\n"
        "Kỹ năng không liên quan có trọng số < 0.2.\n\n"
        "Định dạng trả về: JSON {\"skill_weights\": [{\"skill\": \"name\", \"weight\": value, \"reason\": \"...\"}]}\n"
        "Trả về duy nhất một JSON hợp lệ (không kèm văn bản mô tả khác)."
    )
    return prompt


def ai_weight_skills(
    job_title: str,
    normalized_skills: List[Dict[str, Any]],
    llm_adapter=None,
    provider_label: str = "gemini",
    max_attempts: int = 4,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Ask an LLM to assign weights to `normalized_skills` given `job_title`.

    normalized_skills: list of dicts where each dict contains at least a skill name
    llm_adapter: callable(prompt, api_key=..., timeout_seconds=...) used to call the LLM (optional)

    Returns a dict with keys:
      - skill_weights: list of {skill, weight, reason}
      - total_weight: sum of weights
      - core_count: number of skills with weight > 0.7
      - match_score: total_weight / max(1, core_count)
      - match_percent: match_score * 100
    """

    # Extract plain skill names
    skills = []
    for s in normalized_skills:
        if isinstance(s, dict):
            name = s.get("skill_name") or s.get("skill") or s.get("name")
        else:
            name = str(s)
        if name:
            skills.append(str(name))

    if not skills:
        return {
            "skill_weights": [],
            "total_weight": 0.0,
            "core_count": 0,
            "match_score": 0.0,
            "match_percent": 0.0,
        }

    prompt = _build_prompt(job_title, skills)

    last_exc = None

    # Try to call provided adapter similar to other modules in the repo
    for attempt in range(1, max_attempts + 1):
        try:
            if llm_adapter is None:
                raise RuntimeError("No llm_adapter provided to ai_weight_skills")

            resp = llm_adapter(prompt=prompt, api_key=None, timeout_seconds=timeout_seconds)

            if not isinstance(resp, str):
                resp = str(resp)

            # extract the first JSON object/array
            s = resp.strip()
            # Try direct load
            try:
                data = json.loads(s)
            except Exception:
                # attempt to find JSON substring
                import re

                m = re.search(r"\{\s*\"skill_weights\".*\}\s*$", s, re.S)
                if m:
                    data = json.loads(m.group(0))
                else:
                    m2 = re.search(r"\{.*\}\s*", s, re.S)
                    if m2:
                        data = json.loads(m2.group(0))
                    else:
                        raise

            skill_weights = []
            raw = data.get("skill_weights") if isinstance(data, dict) else None
            if raw is None and isinstance(data, list):
                raw = data

            if raw is None:
                raise RuntimeError("LLM response does not contain 'skill_weights'")

            # normalize each item
            for item in raw:
                try:
                    skill = item.get("skill") or item.get("name")
                    weight = float(item.get("weight") or 0.0)
                    reason = item.get("reason") or item.get("rationale") or ""
                except Exception:
                    continue
                skill_weights.append({"skill": skill, "weight": round(float(weight), 6), "reason": reason})

            # For any skill not returned, add with weight 0.0
            returned = {s["skill"] for s in skill_weights if s.get("skill")}
            for s in skills:
                if s not in returned:
                    skill_weights.append({"skill": s, "weight": 0.0, "reason": "not returned by LLM"})

            total_weight = sum([w["weight"] for w in skill_weights])
            core_count = sum(1 for w in skill_weights if w["weight"] > 0.7)
            denom = core_count if core_count > 0 else max(1, len(skill_weights))
            match_score = total_weight / float(denom)
            match_percent = round(match_score * 100.0, 2)

            return {
                "skill_weights": skill_weights,
                "total_weight": round(total_weight, 6),
                "core_count": int(core_count),
                "match_score": round(match_score, 6),
                "match_percent": match_percent,
            }

        except Exception as e:
            last_exc = e
            logger.warning("[AI WEIGHT] Attempt %d/%d failed: %s", attempt, max_attempts, e)
            time.sleep(2)

    raise RuntimeError(f"AI weighting failed after {max_attempts} attempts: {last_exc}")


def calculate_match_score(cv_skills, job_title: str, master_csv: str = 'Master_IT_Job_Profiles.csv', core_threshold: float = 0.5, filter_it_categories: bool = True, top_k: int = 50, rescale: float = 1.5):
    """Calculate weighted cosine similarity between a CV skill list and a job profile.

    - cv_skills: list of skill strings from CV (e.g. ['python','sql'])
    - job_title: exact Title field from Master file (e.g. 'Software Developers')
    - master_csv: path to Master_IT_Job_Profiles.csv
    - core_threshold: weight threshold to consider a missing skill "important"

    Returns dict: {'match_percent': float, 'missing_skills': [(skill, weight), ...], 'matched_skills': [(skill, weight), ...]}
    Also prints the percent and missing skills.
    """
    import csv
    from math import sqrt

    # normalize CV skills
    cv_set = {s.strip().lower() for s in cv_skills if s and str(s).strip()}

    # load job skills from master csv
    job_skills = {}
    job_categories = {}
    try:
        with open(master_csv, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                title = (r.get('Title') or '').strip()
                if title != job_title:
                    continue
                skill = (r.get('Skill_Name') or '').strip().lower()
                try:
                    weight = float(r.get('Weight') or 0.0)
                except Exception:
                    weight = 0.0
                category = (r.get('Category') or '').strip().lower()
                if skill:
                    job_skills[skill] = weight
                    job_categories[skill] = category
    except FileNotFoundError:
        raise FileNotFoundError(f"Master CSV not found: {master_csv}")

    if not job_skills:
        raise ValueError(f"No skills found for job title '{job_title}' in {master_csv}")

    # Apply Top-K filter (for display only)
    sorted_skills = sorted(job_skills.items(), key=lambda x: x[1], reverse=True)
    top_skills = [s for s, w in sorted_skills[:top_k]]

    # Optionally filter out non-IT categories (office, document management, graphics) for display
    if filter_it_categories:
        # Exclude broad non-engineering categories and common creative/office/tooling terms
        exclude_terms_categories = (
            'office',
            'document',
            'graphics',
            'photo',
            'desktop publishing',
            'video',
            'creative',
            'design',
            'publishing',
        )
        exclude_terms_skills = (
            'adobe',
            'photoshop',
            'illustrator',
            'indesign',
            'acrobat',
            'figma',
            'powerpoint',
            'word',
            'excel',
            'outlook',
        )

        def is_excluded(skill):
            cat = job_categories.get(skill, '') or ''
            if any(t in cat for t in exclude_terms_categories):
                return True
            if any(t in skill for t in exclude_terms_skills):
                return True
            return False

        filtered = [s for s in top_skills if not is_excluded(s)]
        skills = filtered
    else:
        skills = top_skills
    # --- Global scoring: compute match over ALL job skills (not only Top-K) ---
    all_skills = [s for s, w in sorted(job_skills.items(), key=lambda x: x[0])]
    # Reduce influence of conceptual/soft skills in global scoring so technical skills matter more
    def category_multiplier(skill_name: str) -> float:
        cat = job_categories.get(skill_name, '') or ''
        name = skill_name.lower()
        # Heavily downweight common office/soft skills
        if any(x in name for x in ('excel', 'powerpoint', 'word', 'outlook')):
            return 0.1
        if 'conceptual' in cat or 'soft' in cat or 'communication' in cat:
            return 0.2
        return 1.0

    J_all = [job_skills[s] * category_multiplier(s) for s in all_skills]
    C_presence_all = [1.0 if s in cv_set else 0.0 for s in all_skills]

    WCV_all = [cp * w for cp, w in zip(C_presence_all, J_all)]
    dot = sum(a * b for a, b in zip(WCV_all, J_all))
    norm_wcv = sqrt(sum(a * a for a in WCV_all))
    norm_j = sqrt(sum(b * b for b in J_all))

    if norm_wcv == 0 or norm_j == 0:
        match_score = 0.0
    else:
        match_score = dot / (norm_wcv * norm_j)

    match_percent = round(match_score * 100.0, 2)

    # Rescale for user-friendly score
    RESCALE = rescale
    match_percent_rescaled = min(round(match_percent * RESCALE, 2), 100.0)

    # Optional IT-specific category filter: remove office/graphics/document categories from missing/matching if requested by caller
    # (we expose parameter below in wrapper)

    # Missing skills: those not in CV and with weight >= core_threshold, sorted by weight desc
    missing = [(s, job_skills[s]) for s in skills if s not in cv_set and job_skills[s] >= core_threshold]
    missing_sorted = sorted(missing, key=lambda x: x[1], reverse=True)

    matched = [(s, job_skills[s]) for s in skills if s in cv_set]
    matched_sorted = sorted(matched, key=lambda x: x[1], reverse=True)

    # Print results
    print(f"Match percent for '{job_title}': {match_percent}% (raw), {match_percent_rescaled}% (rescaled)")
    if missing_sorted:
        print("Missing important skills (skill: weight):")
        for s, w in missing_sorted:
            print(f" - {s}: {w:.3f}")
    else:
        print("No important missing skills (threshold={:.2f}).".format(core_threshold))

    return {
        'match_percent_raw': match_percent,
        'match_percent_rescaled': match_percent_rescaled,
        'match_score': match_score,
        'missing_skills': missing_sorted,
        'matched_skills': matched_sorted,
        'total_job_skills': len(skills),
        'cv_skill_count': len(cv_set),
    }


def generate_match_report(cv_skills, job_title: str, master_csv: str = 'Master_IT_Job_Profiles.csv', top_k: int = 50, filter_it_categories: bool = True) -> Dict[str, List[Tuple[str, float]]]:
    """Generate three lists:

    - strong_skills: skills present in CV that are within Top-K job skills (with weights)
    - missing_skills: Top 10 highest-weight job skills that are missing from CV (skill, weight)
    - potential_skills: skills (from Top-K) with weight between 0.4 and 0.6 (inclusive)

    Returns dict with keys 'strong_skills', 'missing_skills', 'potential_skills'.
    """
    import csv

    cv_set = {s.strip().lower() for s in cv_skills if s and str(s).strip()}

    # load job skills
    job_skills = {}
    job_categories = {}
    try:
        with open(master_csv, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                title = (r.get('Title') or '').strip()
                if title != job_title:
                    continue
                skill = (r.get('Skill_Name') or '').strip().lower()
                try:
                    weight = float(r.get('Weight') or 0.0)
                except Exception:
                    weight = 0.0
                category = (r.get('Category') or '').strip().lower()
                if skill:
                    job_skills[skill] = weight
                    job_categories[skill] = category
    except FileNotFoundError:
        raise FileNotFoundError(f"Master CSV not found: {master_csv}")

    if not job_skills:
        raise ValueError(f"No skills found for job title '{job_title}' in {master_csv}")

    # Top-K selection
    sorted_skills = sorted(job_skills.items(), key=lambda x: x[1], reverse=True)
    top_skills = [s for s, w in sorted_skills[:top_k]]

    # apply category/skill exclusions if requested (reuse same rules as calculate_match_score)
    if filter_it_categories:
        exclude_terms_categories = (
            'office', 'document', 'graphics', 'photo', 'desktop publishing', 'video', 'creative', 'design', 'publishing'
        )
        exclude_terms_skills = (
            'adobe', 'photoshop', 'illustrator', 'indesign', 'acrobat', 'figma', 'powerpoint', 'word', 'excel', 'outlook'
        )

        def is_excluded(skill):
            cat = job_categories.get(skill, '') or ''
            if any(t in cat for t in exclude_terms_categories):
                return True
            if any(t in skill for t in exclude_terms_skills):
                return True
            return False

        filtered = [s for s in top_skills if not is_excluded(s)]
        skills = filtered
    else:
        skills = top_skills

    # Try to load technology flags (Hot Technology / In Demand) from Technology Skills.xlsx
    tech_flags = {}
    try:
        import pandas as pd
        import os as _os
        tech_xlsx = _os.path.join(_os.path.dirname(__file__), 'ONET_DB', 'Technology Skills.xlsx')
        if _os.path.exists(tech_xlsx):
            df = pd.read_excel(tech_xlsx, engine='openpyxl')
            cols = {c.strip(): c for c in df.columns}
            def col(name):
                return cols.get(name, name)

            for _, r in df.iterrows():
                skill_name = str(r.get(col('Example'), '')).strip()
                if not skill_name or skill_name.lower() == 'nan':
                    continue
                hot = str(r.get(col('Hot Technology'), '')).strip().upper() if col('Hot Technology') in cols else ''
                ind = str(r.get(col('In Demand'), '')).strip().upper() if col('In Demand') in cols else ''
                tech_flags[skill_name.strip().lower()] = {'hot': hot, 'in_demand': ind}
    except Exception:
        tech_flags = {}

    # Strong skills: in CV and in Top-K (with weight)
    strong = [(s, job_skills[s]) for s in skills if s in cv_set]
    strong_sorted = sorted(strong, key=lambda x: x[1], reverse=True)

    # Breakthrough skills: in CV and flagged Hot Technology == 'Y'
    breakthrough = [(s, w) for s, w in strong_sorted if tech_flags.get(s, {}).get('hot', '') == 'Y']

    # Missing: top 10 highest-weight skills in Top-K that are not in CV
    missing = [(s, job_skills[s]) for s in skills if s not in cv_set]
    missing_sorted = sorted(missing, key=lambda x: x[1], reverse=True)[:10]

    # Priority goals: missing skills that have Hot=='Y' or In Demand=='Y'
    priority_candidates = [(s, job_skills[s]) for s, w in missing if tech_flags.get(s, {}).get('hot', '') == 'Y' or tech_flags.get(s, {}).get('in_demand', '') == 'Y']
    priority_sorted_full = sorted(priority_candidates, key=lambda x: x[1], reverse=True)

    # Smart Priority: promote skills whose category matches any category of the candidate's strong_skills
    strong_skill_names = [s for s, w in strong_sorted]
    strong_categories = set(job_categories.get(s, '') for s in strong_skill_names)

    def priority_key(item):
        s, w = item
        cat = job_categories.get(s, '')
        cat_match = 0 if (cat in strong_categories and cat != '') else 1
        return (cat_match, -w)

    priority_sorted_smart = sorted(priority_sorted_full, key=priority_key)

    # Build priority list with explicit reason and cap to top 10
    priority_with_reason = []
    for s, w in priority_sorted_smart[:10]:
        flags = tech_flags.get(s, {})
        if flags.get('hot', '') == 'Y':
            reason = 'Xu hướng công nghệ mới (Hot Technology)'
        elif flags.get('in_demand', '') == 'Y':
            reason = 'Thị trường đang cần (In Demand)'
        else:
            reason = ''
        priority_with_reason.append({'skill': s, 'weight': w, 'reason': reason})

    market_messages = {
        'strong_skills': 'Vũ khí sẵn có: nhấn mạnh những kỹ năng này trên CV và trong phỏng vấn vì chúng thuộc Top-K.',
        'breakthrough_skills': 'Điểm tựa bứt phá: bạn có Hot Technologies — đây là lợi thế cạnh tranh, hãy làm nổi bật chúng.',
        'priority_goals': 'Mục tiêu ưu tiên: học các kỹ năng Hot hoặc In Demand mà bạn chưa có để tăng employability.',
    }

    action_plan = 'Ưu tiên làm nổi bật các "breakthrough_skills" bạn đã có; sau đó học các "priority_goals" (tối đa 10) để mở rộng năng lực.'

    return {
        'strong_skills': [{'skill': s, 'weight': w} for s, w in strong_sorted],
        'breakthrough_skills': [{'skill': s, 'weight': w} for s, w in breakthrough],
        'priority_goals': priority_with_reason,
        'market_message': market_messages,
        'action_plan': action_plan,
    }


if __name__ == '__main__':
    # quick demo
    demo_cv = ['python', 'sql', 'critical thinking', 'git']
    try:
        res = calculate_match_score(demo_cv, 'Software Developers', master_csv='Master_IT_Job_Profiles.csv')
    except Exception as e:
        print('Demo failed:', e)
