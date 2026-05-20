import os
import csv
import sys

ROOT = os.path.dirname(__file__)
TECH_XLSX = os.path.join(ROOT, 'ONET_DB', 'Technology Skills.xlsx')
IT_CODES_CSV = os.path.join(ROOT, 'ONET_DB', 'Computer_and_Mathematical.csv')
FINAL_SKILLS_CSV = os.path.join(ROOT, 'Final_IT_Skills_Weights.csv')
OUTPUT_CSV = os.path.join(ROOT, 'Master_IT_Job_Profiles.csv')


def ensure_pandas():
    try:
        import pandas as pd
        return pd
    except Exception:
        print('pandas or openpyxl not installed. Please run: pip install pandas openpyxl')
        sys.exit(2)


def load_it_codes(path):
    codes = set()
    with open(path, encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            code = row[0].strip()
            if code.lower().startswith('code'):
                continue
            codes.add(code)
    return codes


def process_technology():
    pd = ensure_pandas()
    it_codes = load_it_codes(IT_CODES_CSV)

    # Read Excel
    df = pd.read_excel(TECH_XLSX, engine='openpyxl')

    # Expected columns: Example (skill name), Commodity Title (category), O*NET-SOC Code, Hot Technology, In Demand
    # Normalize column names
    cols = {c.strip(): c for c in df.columns}
    def col(name):
        return cols.get(name, name)

    # Filter rows with SOC codes in IT list
    df['O*NET-SOC Code'] = df.get(col('O*NET-SOC Code'))
    df = df[df['O*NET-SOC Code'].isin(it_codes)]

    # Build technology records
    tech_records = []
    for _, r in df.iterrows():
        skill = str(r.get(col('Example'), '')).strip()
        if skill == '' or skill.lower() == 'nan':
            continue
        category = str(r.get(col('Commodity Title'), '')).strip()
        hot = str(r.get(col('Hot Technology'), '')).strip().upper() if col('Hot Technology') in cols else ''
        ind = str(r.get(col('In Demand'), '')).strip().upper() if col('In Demand') in cols else ''
        weight = 0.95 if (hot == 'Y' or ind == 'Y') else 0.80
        tech_records.append({
            'O*NET-SOC Code': r['O*NET-SOC Code'],
            'Title': str(r.get(col('Title'), '')).strip() or '',
            'Skill_Name': skill,
            'Category': category,
            'Weight': round(float(weight), 2)
        })

    # Load final skills (conceptual skills)
    concept = []
    with open(FINAL_SKILLS_CSV, encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            concept.append({
                'O*NET-SOC Code': r['O*NET-SOC Code'],
                'Title': r['Title'],
                'Skill_Name': r['Element Name'],
                'Category': 'conceptual',
                'Weight': float(r['Normalized_Weight'])
            })

    # Merge: normalize skill names to lowercase and strip; technology records override on conflict
    merged = {}
    # Add concept skills first
    for rec in concept:
        key = (rec['Title'], rec['Skill_Name'].strip().lower())
        merged[key] = rec

    # Add/override with tech skills
    for rec in tech_records:
        title = rec['Title']
        if title == '' and rec['O*NET-SOC Code']:
            # try to map title from concept by SOC code
            # find any concept with same SOC code
            title = next((c['Title'] for c in concept if c['O*NET-SOC Code'] == rec['O*NET-SOC Code']), '')
        key = (title, rec['Skill_Name'].strip().lower())
        # prefer technology record
        merged[key] = {
            'O*NET-SOC Code': rec['O*NET-SOC Code'],
            'Title': title,
            'Skill_Name': rec['Skill_Name'].strip().lower(),
            'Category': rec['Category'],
            'Weight': rec['Weight']
        }

    # Flatten to list and write Master CSV
    out_rows = []
    for (title, skill), rec in merged.items():
        out_rows.append({
            'Title': title,
            'Skill_Name': skill,
            'Category': rec['Category'],
            'Weight': f"{rec['Weight']:.3f}",
            'O*NET-SOC Code': rec.get('O*NET-SOC Code', '')
        })

    fieldnames = ['O*NET-SOC Code', 'Title', 'Skill_Name', 'Category', 'Weight']
    with open(OUTPUT_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in out_rows:
            writer.writerow({k: r.get(k, '') for k in fieldnames})

    # Reporting for Software Developers
    sd_skills = [r for r in out_rows if r['Title'] == 'Software Developers']
    hot_techs = [r for r in sd_skills if float(r['Weight']) == 0.95]
    # Top 10 hot technologies (by weight then name)
    hot_top10 = hot_techs[:10]

    print(f"Master file written: {OUTPUT_CSV}")
    print(f"Total merged skill rows: {len(out_rows)}")
    print("Top Hot Technologies for Software Developers (Weight=0.95):")
    for r in hot_top10:
        print(f" - {r['Skill_Name']} ({r['Category']}) -> {r['Weight']}")
    print(f"Total skills for Software Developers after merge: {len(sd_skills)}")

    return out_rows


if __name__ == '__main__':
    process_technology()
