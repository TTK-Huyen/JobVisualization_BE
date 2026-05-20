import json
p='final_insight_report_jobs.json'
with open(p, encoding='utf-8') as f:
    j=json.load(f)
for t,info in j['results'].items():
    print(t)
    print(' similarity %:', info['similarity_percent'])
    rpt=info.get('report',{})
    print(' strong_skills:', [s['skill'] for s in rpt.get('strong_skills',[])])
    print(' breakthrough:', [s['skill'] for s in rpt.get('breakthrough_skills',[])])
    print(' priority top3:', [p['skill'] for p in rpt.get('priority_goals',[])[:3]])
    print()
