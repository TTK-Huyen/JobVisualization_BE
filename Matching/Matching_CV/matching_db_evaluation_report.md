# Matching Evaluation Report (Database)

- Generated at: 2026-03-22 09:44:14
- Overall decision: **CHUA_PHU_HOP**
- Fit for DB now: **False**

## 1) Data Quality (jobs_from_db.json)
- Total jobs: 283
- Jobs without skills_extracted: 183 (64.66%)
- Jobs with <=3 skills: 191 (67.49%)
- Jobs with exactly 1 skill: 4 (1.41%)
- Skill count stats: min=0, mean=12.15, median=0, max=66

## 2) Matching Behavior (matching_results.json)
- Total CVs: 3
- CVs with at least 1 match: 3
- Total scored matches (top-k aggregate): 11
- Score stats: min=0.0, mean=0.1342, median=0.027, max=1.0
- Top-1 stats: count=3, mean=0.4, low_confidence_ratio(<0.3)=66.67%, family_consistency_ratio=100.00%, overconfident_single_skill_count=1

## 3) Verdict
- Ty le job khong co skills_extracted qua cao: 64.66% (>30%).
- Ty le job co <=3 skills qua cao: 67.49% (>50%).
- Hon 50% top-1 co diem <0.3 (66.67%), matching chua du tin cay.
- Co truong hop diem top-1 >=0.95 voi job chi co 1 skill, gay ao tuong phu hop.

## 4) Recommendations
- Bo qua job co skills_extracted rong truoc khi ranking (hoac gan confidence=0).
- Dat nguong toi thieu so luong skill cho job (de xuat >=4) de duoc dua vao matching.
- Them thanh phan diem theo title similarity va seniority thay vi chi dua vao overlap skill.
- Ap dung do tin cay (confidence score) de canh bao ket qua diem cao nhung du lieu mong.

## 5) Per-CV Top-1 Snapshot
- cv_01 | cv=Tester Intern | top1=Full-stack Test Engineer | score=0.2 | top1_skill_count=35 | family_consistent=True | overconfident_single_skill=False
- cv_02 | cv=IT Helpdesk | top1=IT Helpdesk Leader | score=0.0 | top1_skill_count=0 | family_consistent=True | overconfident_single_skill=False
- cv_03 | cv=Front-end Developer | top1=Technical Demo Architect (API, Javascript, JSON, Git) | score=1.0 | top1_skill_count=1 | family_consistent=True | overconfident_single_skill=True
