#!/usr/bin/env python3
"""Normalize job benefit values in JSON crawl files to a canonical list.

Dry-run by default: collects matches and writes a report to
`normalize_benefits_report.json`. Use `--apply` to overwrite files (creates .bak).

Also outputs the path to the SQL migration at `../input/migrations/normalize_benefits.sql`.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List


def load_canonical(path: Path) -> List[Dict[str, str]]:
    return json.loads(path.read_text(encoding='utf-8'))


def strip_html(s: str) -> str:
    return re.sub(r'<[^>]+>', ' ', s)


def extract_benefit_text(job: Dict) -> str:
    texts: List[str] = []
    if 'benefits' in job:
        b = job['benefits']
        if isinstance(b, list):
            for item in b:
                if isinstance(item, dict):
                    for k in ('benefitName', 'benefitValue', 'benefitNameVI'):
                        if k in item and item[k]:
                            texts.append(str(item[k]))
                else:
                    texts.append(str(item))
        else:
            texts.append(str(b))
    if 'jobBenefits' in job and job['jobBenefits']:
        texts.append(strip_html(str(job['jobBenefits'])))
    return ' '.join(texts).lower()


def build_keyword_map(canonical: List[Dict[str, str]]) -> Dict[str, str]:
    # Map many small keywords to canonical names for heuristic matching
    m: Dict[str, str] = {}
    for c in canonical:
        name = c['name']
        key = name.lower()
        m[key] = name
    # common keyword variants
    variants = {
        'remote': 'Remote work',
        'work from home': 'Work from home (wfh)',
        'wfh': 'Work from home (wfh)',
        'hybrid': 'Hybrid work',
        'flexible': 'Flexible working hours',
        'compressed': 'Compressed workweek',
        'no overtime': 'No overtime / Limited overtime',
        'overtime': 'Overtime pay',
        'bonus': 'Performance bonus',
        '13th': '13th month salary',
        'year-end': 'Annual bonus / Year-end bonus',
        'stock': 'Stock options',
        'salary review': 'Salary review (annual / bi-annual)',
        'sign-on': 'Sign-on bonus',
        'referral': 'Referral bonus',
        'health': 'Health insurance',
        'dental': 'Dental insurance',
        'vision': 'Vision insurance',
        'mental': 'Mental health support',
        'wellness': 'Wellness program',
        'training': 'Training budget',
        'udemy': 'Paid courses (Udemy, Coursera, Pluralsight)',
        'coursera': 'Paid courses (Udemy, Coursera, Pluralsight)',
        'pluralsight': 'Paid courses (Udemy, Coursera, Pluralsight)',
        'conference': 'Conference sponsorship',
        'career path': 'Career path / career roadmap',
        'mentorship': 'Mentorship program',
        'pto': 'Paid time off (pto)',
        'paid time off': 'Paid time off (pto)',
        'annual leave': 'Annual leave',
        'sick': 'Sick leave',
        'personal leave': 'Personal leave',
        'parental': 'Parental leave / maternity leave / paternity leave',
        'maternity': 'Parental leave / maternity leave / paternity leave',
        'paternity': 'Parental leave / maternity leave / paternity leave',
        'birthday': 'Birthday leave',
        'company laptop': 'Company laptop',
        'macbook': 'MacBook provided',
        'ergonomic': 'Ergonomic equipment',
        'software license': 'Software license provided',
        'international': 'International working environment',
        'multicultural': 'Multicultural team',
        'english': 'English-speaking environment',
        'flat': 'Flat organization',
        'open culture': 'Open culture',
        'innovation': 'Innovation-driven culture',
        'full-time': 'Full-time contract',
        'probation': 'Probation salary 100%',
        'social insurance': 'Social insurance',
        'tax': 'Tax support',
    }
    m.update(variants)
    return m


def normalize_file(path: Path, keyword_map: Dict[str, str], canonical_order: List[str], apply: bool) -> Dict:
    try:
        text = path.read_text(encoding='utf-8')
        job = json.loads(text)
    except Exception:
        return {'path': str(path), 'error': 'parse_error'}

    benefit_text = extract_benefit_text(job)
    found = set()
    # check canonical names
    for canon in canonical_order:
        if canon.lower() in benefit_text:
            found.add(canon)
    # check keyword_map
    for kw, canon in keyword_map.items():
        if kw in benefit_text:
            found.add(canon)

    # preserve canonical ordering
    ordered = [c for c in canonical_order if c in found]

    if apply:
        # backup
        bak = path.with_suffix(path.suffix + '.bak')
        if not bak.exists():
            path.rename(bak)
            # write updated file
            job['benefits'] = [{'benefitName': n} for n in ordered]
            path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
            return {'path': str(path), 'applied': True, 'benefits': ordered}
        else:
            return {'path': str(path), 'error': 'backup_exists'}
    else:
        return {'path': str(path), 'applied': False, 'benefits': ordered}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data-dir', default=str(Path(__file__).resolve().parents[1] / 'data'))
    p.add_argument('--canonical', default=str(Path(__file__).resolve().parents[1] / 'input' / 'canonical_benefits.json'))
    p.add_argument('--apply', action='store_true', help='Overwrite files (creates .bak)')
    p.add_argument('--report', default='normalize_benefits_report.json')
    args = p.parse_args()

    canonical = load_canonical(Path(args.canonical))
    canonical_order = [c['name'] for c in canonical]
    keyword_map = build_keyword_map(canonical)

    data_dir = Path(args.data_dir)
    results = []
    for root, _, files in os.walk(data_dir):
        for fn in files:
            if fn.endswith('.json'):
                path = Path(root) / fn
                res = normalize_file(path, keyword_map, canonical_order, args.apply)
                results.append(res)

    Path(args.report).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Report written to', args.report)
    print('SQL migration:', str(Path(__file__).resolve().parents[1] / 'input' / 'migrations' / 'normalize_benefits.sql'))


if __name__ == '__main__':
    main()
