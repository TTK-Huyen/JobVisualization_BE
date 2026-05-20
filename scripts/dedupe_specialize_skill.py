#!/usr/bin/env python3
"""Deduplicate Db/Specialize_skill.csv by the first column (skill name).
Backs up the original file to Db/Specialize_skill.csv.bak before writing.
"""
from pathlib import Path
import csv
import shutil

csv_path = Path(__file__).resolve().parents[1] / 'Db' / 'Specialize_skill.csv'
backup_path = csv_path.with_suffix('.csv.bak')

if not csv_path.exists():
    print(f"File not found: {csv_path}")
    raise SystemExit(1)

seen = set()
rows = []
dup_count = 0
with csv_path.open('r', encoding='utf-8') as fh:
    reader = csv.reader(fh)
    for r in reader:
        if not r:
            continue
        key = r[0].strip()
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        rows.append(r)

print(f"Total unique skills: {len(rows)}")
print(f"Total duplicates found: {dup_count}")

# Check specifically for 'Wireless Technologies'
count_wireless = sum(1 for r in rows if r[0].strip() == 'Wireless Technologies')
# But duplicates removed from rows; need to count original occurrences
orig_count_wireless = 0
with csv_path.open('r', encoding='utf-8') as fh:
    for line in fh:
        if line.strip().startswith('Wireless Technologies'):
            orig_count_wireless += 1

print(f"Original occurrences of 'Wireless Technologies': {orig_count_wireless}")
print(f"Occurrences after dedupe: {count_wireless}")

if dup_count == 0:
    print('No duplicates to remove. No changes made.')
    raise SystemExit(0)

# Backup original
shutil.copy2(str(csv_path), str(backup_path))
print(f"Backup written to: {backup_path}")

# Write back deduped file
with csv_path.open('w', encoding='utf-8', newline='') as fh:
    writer = csv.writer(fh)
    for r in rows:
        writer.writerow(r)

print('Deduplication applied. Original backed up.')
