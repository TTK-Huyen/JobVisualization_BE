"""
Mock test script for verifying TF-IDF calculations on boundary Job Titles.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from SkillWeighting.tf_idf import calculate_tf_idf


def run_mock_test():
    # 1. Define the mock dataset dictionary as requested
    mock_dataset = {
        'Data Scientist': ['python', 'sql', 'teamwork'],
        'Data Analyst': ['power_bi', 'sql', 'teamwork'],
        'Data Engineer': ['spark', 'python', 'sql']
    }

    # 2. Convert dictionary to the corpus format: List[Tuple[search_group, skill_name, job_count]]
    # Here we assume a job_count of 1 for each skill within the respective title.
    corpus = []
    for job_title, skills in mock_dataset.items():
        for skill in skills:
            corpus.append((job_title, skill, 1))

    # 3. Calculate TF-IDF
    scores = calculate_tf_idf(corpus)

    # 4. Extract verification details
    total_groups = len(mock_dataset)
    print(f"Total Job Titles (|T|): {total_groups}")
    print("-" * 50)

    # Count appearances in groups (m)
    appearances = {}
    for group, skills in mock_dataset.items():
        for skill in skills:
            appearances[skill] = appearances.get(skill, 0) + 1

    # Print frequency assertions
    print("[Verification of Appearances (m/|T|)]:")
    for skill, m in sorted(appearances.items(), key=lambda x: x[1], reverse=True):
        print(f" - Skill '{skill}' appears in {m}/{total_groups} job titles.")

    # Let's verify specific assertions required by the user
    assert appearances['sql'] == 3, f"Expected 'sql' to appear in 3 titles, but got {appearances['sql']}"
    assert appearances['python'] == 2, f"Expected 'python' to appear in 2 titles, but got {appearances['python']}"
    assert appearances['spark'] == 1, f"Expected 'spark' to appear in 1 title, but got {appearances['spark']}"
    print("\n[Assert Check]: Frequencies match expectations (sql=3/3, python=2/3, spark=1/3)!")

    # 5. Print out computed TF-IDF scores
    print("\n[Computed TF-IDF Scores]:")
    for group, skill_scores in scores.items():
        print(f"\nJob Title: {group}")
        for skill, score in sorted(skill_scores.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {skill}: TF-IDF = {score:.4f}")


if __name__ == "__main__":
    run_mock_test()
