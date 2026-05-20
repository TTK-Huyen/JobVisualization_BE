import csv
from collections import defaultdict

MASTER='Master_IT_Job_Profiles.csv'
out='job_skill_counts.csv'

titles = defaultdict(set)
cat_counts = defaultdict(lambda: defaultdict(int))
all_cats = set()
with open(MASTER, encoding='utf-8', newline='') as f:
    reader = csv.DictReader(f)
    for r in reader:
        title = (r.get('Title') or '').strip()
        skill = (r.get('Skill_Name') or '').strip().lower()
        cat = (r.get('Category') or '').strip().lower()
        titles[title].add(skill)
        cat_counts[title][cat] += 1
        all_cats.add(cat)

# write summary
with open(out, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Title','Unique_Skills','Categories_Counts'])
    for t in sorted(titles.keys()):
        total = len(titles[t])
        cats = cat_counts[t]
        cat_str = ';'.join(f"{k}:{v}" for k,v in cats.items())
        writer.writerow([t, total, cat_str])
    # also write an archived copy
    archive_dir = Path("archive_reports")
    archive_dir.mkdir(exist_ok=True)
    df.to_csv(archive_dir / out, index=False)
    print(f"Also wrote archive_reports/{out}")

print('Wrote', out)
print('Total job titles:', len(titles))
print('Categories observed:', ', '.join(sorted(c for c in all_cats if c)))
