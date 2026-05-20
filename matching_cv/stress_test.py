from matching_engine import generate_match_report, calculate_match_score
import json

JOB_TITLE = 'Software Developers'
CVS = {
    'CV1_Specialist': ['python', 'sql', 'django', 'docker', 'postgresql', 'git', 'critical thinking'],
    'CV2_CrossSkilled': ['javascript', 'react', 'html', 'css', 'typescript', 'git', 'communication'],
    'CV3_Beginner': ['microsoft excel', 'powerpoint', 'writing', 'speaking', 'teamwork'],
    'CV4_Generalist': ['python', 'html', 'java', 'sql', 'problem solving'],
}

results = {}
summary = []

for name, cv in CVS.items():
    # run calculate_match_score to get overall percent (rescaled)
    try:
        cs = calculate_match_score(cv, JOB_TITLE, master_csv='Master_IT_Job_Profiles.csv')
        overall_percent = cs.get('match_percent_rescaled', cs.get('match_percent_raw', 0.0))
    except Exception as e:
        overall_percent = 0.0

    # run generate_match_report for insights
    try:
        rep = generate_match_report(cv, JOB_TITLE, master_csv='Master_IT_Job_Profiles.csv')
    except Exception as e:
        rep = {'strong_skills': [], 'breakthrough_skills': [], 'priority_goals': [], 'market_message': {}, 'action_plan': ''}

    breakthrough_count = len(rep.get('breakthrough_skills', []))
    top3_priority = rep.get('priority_goals', [])[:3]

    results[name] = {
        'cv': cv,
        'overall_percent': overall_percent,
        'breakthrough_count': breakthrough_count,
        'top3_priority': top3_priority,
        'report': rep,
        'calculate_match_score': cs if 'cs' in locals() else {},
    }

    summary.append((name, overall_percent, breakthrough_count, [p if isinstance(p, dict) else {'skill': p[0], 'weight': p[1]} for p in top3_priority]))

# Sort summary by overall_percent desc
summary_sorted = sorted(summary, key=lambda x: x[1], reverse=True)

# Print comparison table
print("Summary comparison (Name | Overall% | Breakthrough count | Top3 priority skills):")
for row in summary_sorted:
    name, pct, bcount, top3 = row
    top3_names = [t['skill'] if isinstance(t, dict) else str(t) for t in top3]
    print(f"- {name}: {pct}% | breakthrough={bcount} | top3_priority={top3_names}")

# Save detailed report for CV1
cv1_report = results.get('CV1_Specialist')
with open('stress_test_report.json', 'w', encoding='utf-8') as f:
    json.dump({'job_title': JOB_TITLE, 'cv_name': 'CV1_Specialist', 'cv': cv1_report['cv'], 'overall_percent': cv1_report['overall_percent'], 'report': cv1_report['report'], 'calculate_match_score': cv1_report['calculate_match_score']}, f, ensure_ascii=False, indent=2)

print('\nWrote stress_test_report.json for CV1_Specialist')

# Quick logic check: CV1 should be highest, CV3 lowest
order = [name for name, _, _, _ in summary_sorted]
if order[0] == 'CV1_Specialist' and order[-1] == 'CV3_Beginner':
    print('\nLogic check PASSED: CV1 highest, CV3 lowest')
else:
    print('\nLogic check FAILED: ordering is', order)

# Short analysis: does algorithm prioritize Hot Tech? We'll check average weight of breakthrough vs others
analysis = {}
for name, data in results.items():
    rep = data['report']
    priority = rep.get('priority_goals', [])
    if priority:
        avg_priority_weight = sum([p['weight'] for p in priority]) / len(priority)
    else:
        avg_priority_weight = 0.0
    analysis[name] = {'priority_count': len(priority), 'avg_priority_weight': avg_priority_weight}

print('\nQuick analysis: priority groups summary:')
for name, a in analysis.items():
    print(f"- {name}: priority_count={a['priority_count']} avg_weight={a['avg_priority_weight']:.3f}")

# Save full results
with open('stress_test_all_results.json', 'w', encoding='utf-8') as f:
    json.dump({'summary_sorted': summary_sorted, 'results': results, 'analysis': analysis}, f, ensure_ascii=False, indent=2)

print('\nWrote stress_test_all_results.json')
