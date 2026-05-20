import csv
import os
from collections import defaultdict

ROOT = os.path.dirname(__file__)
SKILLS_CSV = os.path.join(ROOT, "ONET_DB", "Skills.csv")
IT_CODES_CSV = os.path.join(ROOT, "ONET_DB", "Computer_and_Mathematical.csv")
OUTPUT_CSV = os.path.join(ROOT, "Final_IT_Skills_Weights.csv")


def load_it_soc_codes(path):
    codes = set()
    with open(path, encoding="utf-8", newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            code = row[0].strip()
            if code.lower().startswith("code"):
                continue
            if code:
                codes.add(code)
    return codes


def parse_float_decimal_comma(s):
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    # Convert comma decimal to dot decimal
    s = s.replace('"', '').replace("'", "").replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def process_and_export(skills_csv, it_codes_csv, output_csv):
    it_codes = load_it_soc_codes(it_codes_csv)

    rows_out = []

    with open(skills_csv, encoding="utf-8", newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            soc = r.get('O*NET-SOC Code') or r.get('O*NET-SOC Code ')
            scale_id = r.get('Scale ID')
            if soc is None:
                continue
            soc = soc.strip()
            if soc not in it_codes:
                continue
            if scale_id != 'IM':
                continue

            title = r.get('Title', '').strip()
            elem = r.get('Element Name', '').strip()
            raw_val = r.get('Data Value', '').strip()
            val = parse_float_decimal_comma(raw_val)
            if val is None:
                continue
            # Normalize: W = (Value - 1) / 4, round 3 decimals
            w = round((val - 1.0) / 4.0, 3)
            if w < 0:
                w = 0.0
            if w > 1:
                w = 1.0

            rows_out.append({
                'O*NET-SOC Code': soc,
                'Title': title,
                'Element Name': elem,
                'Normalized_Weight': f"{w:.3f}"
            })

    # Write output CSV
    fieldnames = ['O*NET-SOC Code', 'Title', 'Element Name', 'Normalized_Weight']
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)

    return rows_out


def build_index(rows):
    by_title = defaultdict(dict)
    for r in rows:
        by_title[r['Title']][r['Element Name']] = float(r['Normalized_Weight'])
    return by_title


def get_job_skill_vector(job_title, index):
    # Exact match (case-sensitive), then case-insensitive fallback
    if job_title in index:
        return index[job_title]
    # case-insensitive search
    lowered = {k.lower(): k for k in index}
    key = lowered.get(job_title.lower())
    if key:
        return index[key]
    raise ValueError(f"Job title '{job_title}' not found in the IT job subset.")


def top_n_programming(rows, n=10):
    # Find rows where Element Name contains 'Programming' (exact) and sort by weight
    prog_rows = [r for r in rows if r['Element Name'].lower() == 'programming']
    prog_rows_sorted = sorted(prog_rows, key=lambda x: float(x['Normalized_Weight']), reverse=True)
    return prog_rows_sorted[:n]


def main():
    rows = process_and_export(SKILLS_CSV, IT_CODES_CSV, OUTPUT_CSV)
    index = build_index(rows)

    top10 = top_n_programming(rows, 10)
    print("Top 10 job Titles by 'Programming' normalized weight:")
    for r in top10:
        print(f"{r['Title']} -> {r['Normalized_Weight']}")

    # Expose get_job_skill_vector for imports
    return rows, index


if __name__ == '__main__':
    main()
