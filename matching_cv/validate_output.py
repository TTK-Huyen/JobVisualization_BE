import csv
from collections import defaultdict
import sys

CSV_PATH = 'Final_IT_Skills_Weights.csv'

def main():
    titles = set()
    missing = []
    by_title = defaultdict(dict)
    try:
        with open(CSV_PATH, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                title = r['Title'].strip()
                elem = r['Element Name'].strip()
                w = r['Normalized_Weight'].strip()
                titles.add(title)
                if w == '' or w.lower() in ('nan', 'none'):
                    missing.append((title, elem))
                else:
                    try:
                        by_title[title][elem] = float(w)
                    except Exception:
                        missing.append((title, elem))
    except FileNotFoundError:
        print(f"ERROR: {CSV_PATH} not found")
        sys.exit(2)

    print(f"Unique job titles in output: {len(titles)}")
    if missing:
        print(f"Found {len(missing)} missing/invalid weight entries (sample 10):")
        for m in missing[:10]:
            print(' -', m)
    else:
        print("No missing/invalid weight entries found.")

    # Print full skill vector for Software Developers
    key = 'Software Developers'
    if key in by_title:
        print(f"\nFull skill vector for '{key}' ({len(by_title[key])} skills):")
        for k,v in sorted(by_title[key].items()):
            print(f"{k}: {v:.3f}")
    else:
        print(f"Job title '{key}' not found in output.")

if __name__ == '__main__':
    main()
