import json
import os
J='final_insight_report_jobs.json'
if not os.path.exists(J):
    raise FileNotFoundError(J)
with open(J, encoding='utf-8') as f:
    data=json.load(f)
md='huyen_career_path_report.md'
with open(md,'w',encoding='utf-8') as m:
    m.write('# Huyen Career Path Comparison\n\n')
    m.write('Comparison of 3 target job titles based on CV embedding match.\n\n')
    for t,info in data['results'].items():
        m.write('## %s\n\n' % t)
        m.write('- Similarity: %s%%\n' % info.get('similarity_percent',0))
        rpt=info.get('report',{})
        strong=[s['skill'] for s in rpt.get('strong_skills',[])]
        pri=[p['skill'] for p in rpt.get('priority_goals',[])]
        m.write('- Strong skills (sample): %s\n' % (', '.join(strong[:10]) or 'None'))
        m.write('- Priority top3: %s\n' % (', '.join(pri[:3]) or 'None'))
        m.write('\n')
print('Wrote', md)
