#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

try:
    from matching_cv.matching_engine import calculate_match_score, generate_match_report
except Exception:
    # fallback when running the script from inside matching_cv/ (no package in path)
    from matching_engine import calculate_match_score, generate_match_report


def parse_skills(s: str):
    s = s.strip()
    # try JSON array first
    if s.startswith('['):
        try:
            return json.loads(s)
        except Exception:
            pass
    # comma-separated
    return [x.strip() for x in s.split(',') if x.strip()]



def main():
    p = argparse.ArgumentParser()
    p.add_argument('--skills', required=False, help='Comma-separated skills or JSON array string')
    p.add_argument('--mock-file', required=False, help='Path to JSON file with named skill lists')
    p.add_argument('--case', required=False, help='Case name inside mock file to use (e.g., CV1_Specialist)')
    p.add_argument('--job', required=False, help='Job title to test (defaults to job_title in mock file if present)')
    p.add_argument('--master', default='Master_IT_Job_Profiles.csv', help='Master CSV path')
    p.add_argument('--out', default='', help='Optional output JSON file')
    args = p.parse_args()

    skills = None

    # load from mock file + case if provided
    if args.mock_file:
        fp = Path(args.mock_file)
        if not fp.exists():
            raise SystemExit(f"Mock file not found: {fp}")
        data = json.loads(fp.read_text(encoding='utf-8'))
        if not args.case:
            raise SystemExit("When using --mock-file you must provide --case CASE_NAME")
        if args.case not in data:
            raise SystemExit(f"Case '{args.case}' not found in {fp}")
        skills = data[args.case]
        # if job not given, try to use job_title from file
        if not args.job and isinstance(data.get('job_title'), str):
            args.job = data.get('job_title')

    if skills is None and args.skills:
        skills = parse_skills(args.skills)

    if not skills:
        raise SystemExit('No skills provided. Use --skills or --mock-file + --case')

    if not args.job:
        raise SystemExit('No job title provided. Use --job or include "job_title" in mock file')

    cs = calculate_match_score(skills, args.job, master_csv=args.master)
    rep = generate_match_report(skills, args.job, master_csv=args.master)

    out = {
        'job': args.job,
        'skills': skills,
        'calculate_match_score': cs,
        'generate_match_report': rep,
    }

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
        print(f'Wrote {args.out}')
    else:
        print(text)


if __name__ == '__main__':
    main()
