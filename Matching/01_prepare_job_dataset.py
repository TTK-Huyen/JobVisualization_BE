import json
import os
import re

MATCHING_DIR = os.path.dirname(__file__)
DATASET_DIR = os.path.join(MATCHING_DIR, "Dataset")
RAW_DIR = os.path.join(DATASET_DIR, "raw_jobs")
PROCESSED_DIR = os.path.join(DATASET_DIR, "processed_jobs")
TEST_DIR = os.path.join(DATASET_DIR, "test")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "clean_jobs.json")

FIELDS = ["title", "company_name", "source_name", "job_url", "description_html", "requirements_text"]

# Keywords that indicate benefits/offers mixed into requirements_text
DIRTY_PATTERNS = re.compile(
    r"WHAT WE OFFER|WE OFFER|QUYỀN LỢI|Quyền lợi|"
    r"CHẾ ĐỘ PHÚC LỢI|PHÚC LỢI|Benefits:|"
    r"Lương thỏa thuận theo năng lực|Lương tháng 13|"
    r"BHXH, BHYT, BHTN",
    re.IGNORECASE,
)


def classify(req: str | None) -> str:
    """Return 'missing', 'dirty', or 'ok'."""
    if not req:
        return "missing"
    if DIRTY_PATTERNS.search(req):
        return "dirty"
    return "ok"


def load_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Strip JS-style single-line comments (// ...) at start of line only
    raw = re.sub(r"^\s*//[^\r\n]*", "", raw, flags=re.MULTILINE)
    return json.loads(raw, strict=False)


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(TEST_DIR, exist_ok=True)

    all_jobs = []
    for fname in sorted(os.listdir(RAW_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(RAW_DIR, fname)
        try:
            data = load_json_file(fpath)
        except Exception as e:
            print(f"[SKIP] {fname}: {e}")
            continue

        if not isinstance(data, list):
            print(f"[SKIP] {fname}: not a list")
            continue

        for job in data:
            if not isinstance(job, dict):
                continue
            clean = {field: job.get(field) for field in FIELDS}
            clean["quality"] = classify(clean["requirements_text"])
            all_jobs.append(clean)

    # Deduplicate by (title, company_name, source_name)
    seen = set()
    deduped = []
    for job in all_jobs:
        key = (job.get("title"), job.get("company_name"), job.get("source_name"))
        if key not in seen:
            seen.add(key)
            deduped.append(job)
    removed = len(all_jobs) - len(deduped)
    if removed:
        print(f"[dedup] Removed {removed} duplicate(s)")
    all_jobs = deduped

    # Write combined file with quality field
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    # Write 3 separate group files
    groups = {"ok": [], "missing": [], "dirty": []}
    for job in all_jobs:
        groups[job["quality"]].append(job)

    group_files = {
        "ok":      os.path.join(PROCESSED_DIR, "jobs_ready.json"),
        "missing": os.path.join(PROCESSED_DIR, "jobs_missing_req.json"),
        "dirty":   os.path.join(PROCESSED_DIR, "jobs_dirty_req.json"),
    }
    for key, path in group_files.items():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(groups[key], f, ensure_ascii=False, indent=2)

    print(f"Total: {len(all_jobs)} jobs")
    print(f"  ok      (ready)   : {len(groups['ok'])}  → jobs_ready.json")
    print(f"  dirty   (bẩn)     : {len(groups['dirty'])}  → jobs_dirty_req.json")
    print(f"  missing (thiếu)   : {len(groups['missing'])}  → jobs_missing_req.json")


if __name__ == "__main__":
    main()
