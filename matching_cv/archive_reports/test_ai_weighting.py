#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from matching_cv.matching_engine import ai_weight_skills


def mock_llm_adapter(prompt: str, api_key=None, timeout_seconds: int = 30) -> str:
    """
    Simple deterministic mock that parses the prompt to extract the skill list
    (lines starting with "- ") and returns a JSON payload following the
    specified format. We simulate O*NET-aware weighting for "Artificial Intelligence Engineer".
    """
    lines = [l.strip() for l in prompt.splitlines()]
    skills = [l[2:].strip() for l in lines if l.startswith("- ")]

    core = set(map(str.lower, [
        "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow",
        "Computer Vision", "Natural Language Processing", "Reinforcement Learning",
        "Python", "Linear Algebra"
    ]))

    data_engineer = set(map(str.lower, [
        "SQL", "Apache Spark", "Hadoop", "Data Pipeline", "ETL", "Java", "Docker", "Cloud Computing", "AWS"
    ]))

    software_dev = set(map(str.lower, [
        "Java Spring Boot", "ReactJS", "HTML/CSS", "MySQL", "RESTful API", "Unit Testing", "Git", "JavaScript"
    ]))

    noise = set(map(str.lower, [
        "Microsoft Excel", "Adobe Photoshop", "Digital Marketing", "Sales", "Teamwork", "English Communication", "Video Editing"
    ]))

    out = []
    for s in skills:
        key = s.lower()
        # assign deterministic weights by category
        if key in core:
            weight = 0.92
            reason = "Core O*NET technical skill for AI Engineer"
        elif key in data_engineer:
            weight = 0.45
            reason = "Supporting data-engineering skill relevant to AI workflows"
        elif key in software_dev:
            weight = 0.25
            reason = "General software development skill with limited direct AI relevance"
        elif key in noise:
            weight = 0.05
            reason = "Not relevant to AI Engineer role"
        else:
            # fuzzy check for substrings
            if "python" in key or "machine" in key or "learning" in key or "nlp" in key:
                weight = 0.9
                reason = "Likely core AI skill"
            elif "sql" in key or "spark" in key or "hadoop" in key:
                weight = 0.45
                reason = "Supporting data skill"
            else:
                weight = 0.1
                reason = "Generic or ambiguous skill"

        out.append({"skill": s, "weight": round(float(weight), 6), "reason": reason})

    return json.dumps({"skill_weights": out}, ensure_ascii=False)


def run_tests():
    cases = {
        "Case 1 - AI Specialist": [
            "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow",
            "Computer Vision", "Natural Language Processing", "Reinforcement Learning",
            "Python", "Linear Algebra"
        ],
        "Case 2 - Data Engineer": [
            "SQL", "Apache Spark", "Hadoop", "Data Pipeline", "ETL",
            "Python", "Java", "Docker", "Cloud Computing (AWS)"
        ],
        "Case 3 - Software Developer": [
            "Java Spring Boot", "ReactJS", "HTML/CSS", "MySQL",
            "RESTful API", "Unit Testing", "Git", "JavaScript"
        ],
        "Case 4 - Noise/General": [
            "Microsoft Excel", "Adobe Photoshop", "Digital Marketing", "Sales",
            "Teamwork", "English Communication", "Video Editing"
        ],
    }

    results = []

    for name, skills in cases.items():
        ai_result = ai_weight_skills(
            "Artificial Intelligence Engineer",
            [{"skill_name": s} for s in skills],
            llm_adapter=mock_llm_adapter,
        )

        print("\n" + name)
        print("Skill | AI Weight | Reason")
        print("-----|-----------:|------")
        for item in ai_result["skill_weights"]:
            print(f"{item['skill']} | {item['weight']:.3f} | {item['reason']}")

        total = ai_result.get("total_weight", 0.0)
        score = ai_result.get("match_score", 0.0)
        percent = ai_result.get("match_percent", 0.0)
        # alternative normalized score: average weight per skill (0..1)
        normalized_avg = total / float(len(skills)) if skills else 0.0
        print(f"Total weight={total:.6f}  Match score={score:.6f}  Match%={percent:.2f}  AvgWeight={normalized_avg:.6f}")

        results.append((name, normalized_avg))

    # Rank check
    ranked = sorted(results, key=lambda x: x[1], reverse=True)
    print("\nRanking by match_score:")
    for i, (n, s) in enumerate(ranked, start=1):
        print(f"{i}. {n}: {s:.6f}")

    # Check expected ordering
    order = [r[0] for r in ranked]
    expected = [
        "Case 1 - AI Specialist",
        "Case 2 - Data Engineer",
        "Case 3 - Software Developer",
        "Case 4 - Noise/General",
    ]
    ok = order == expected
    print("\nOrdering matches expected Case1>Case2>Case3>Case4:", ok)


if __name__ == "__main__":
    run_tests()
