import json

with open('job_group_skill_weights.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("="*80)
print("VERIFICATION: Fallback Keywords Weights")
print("="*80)

# Show QA and DevOps (fallback keywords)
for group in ['QA', 'DevOps']:
    result = next((r for r in data['job_group_skill_weights'] if r['search_group'] == group), None)
    if result:
        print(f'\n✅ {group}:')
        print(f"   Method: {result['metadata']['calculation_method']}")
        print(f"   Skills count: {len(result['skill_weights'])}")
        weight_sum = sum(s['weight_wi'] for s in result['skill_weights'])
        print(f"   Weight sum: {weight_sum:.6f}")
        print('   Top 3 skills:')
        for skill in result['skill_weights'][:3]:
            print(f"     - {skill['skill_name']}: {skill['weight_wi']:.4f}")

print("\n" + "="*80)
print("VERIFICATION: LLM-weighted Keywords Weights")
print("="*80)

# Show Backend and Frontend (LLM-weighted keywords)
for group in ['Backend', 'Frontend']:
    result = next((r for r in data['job_group_skill_weights'] if r['search_group'] == group), None)
    if result:
        print(f'\n✅ {group}:')
        print(f"   Method: {result['metadata']['calculation_method']}")
        print(f"   Skills count: {len(result['skill_weights'])}")
        weight_sum = sum(s['weight_wi'] for s in result['skill_weights'])
        print(f"   Weight sum: {weight_sum:.6f}")
        print('   Top 3 skills:')
        for skill in result['skill_weights'][:3]:
            print(f"     - {skill['skill_name']}: {skill['weight_wi']:.4f}")

print("\n" + "="*80)
