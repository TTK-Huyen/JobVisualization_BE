import os
import json
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
SCHEMA_PATH = os.path.join(ROOT, "input", "crawl_schema.json")
DATA_DIR = os.path.join(ROOT, "data")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_item(item, required, optional):
    issues = []
    if not isinstance(item, dict):
        issues.append(("not_object", "Item is not a JSON object"))
        return issues
    for key in required:
        if key not in item:
            issues.append(("missing", key))
    # unexpected keys
    allowed = set(required) | set(optional)
    for key in item.keys():
        if key not in allowed:
            issues.append(("unexpected", key))
    return issues


def main():
    try:
        schema = load_json(SCHEMA_PATH)
    except Exception as e:
        print("ERROR: Cannot read schema:", e)
        sys.exit(2)

    required = schema.get("required", [])
    optional = schema.get("optional", [])

    if not os.path.isdir(DATA_DIR):
        print("No data directory found at:", DATA_DIR)
        sys.exit(0)

    total_files = 0
    total_items = 0
    total_issues = 0
    issues_list = []

    for root, dirs, files in os.walk(DATA_DIR):
        for fname in files:
            if not fname.lower().endswith('.json'):
                continue
            path = os.path.join(root, fname)
            total_files += 1
            try:
                data = load_json(path)
            except Exception as e:
                issues_list.append((path, None, f"invalid JSON: {e}"))
                total_issues += 1
                continue

            items = data if isinstance(data, list) else [data]
            for idx, item in enumerate(items):
                total_items += 1
                issues = check_item(item, required, optional)
                if issues:
                    total_issues += len(issues)
                    for code, info in issues:
                        issues_list.append((path, idx if len(items)>1 else None, code+':'+str(info)))

    print("Validation summary:")
    print("- data dir:", DATA_DIR)
    print(f"- files checked: {total_files}")
    print(f"- items checked: {total_items}")
    print(f"- total issues: {total_issues}")
    if issues_list:
        print("\nFirst 50 issues:")
        for i, it in enumerate(issues_list[:50], 1):
            path, idx, msg = it
            loc = f"{path}"
            if idx is not None:
                loc += f" [item {idx}]"
            print(f"{i}. {loc} -> {msg}")
        print("\nTo inspect more, run the script directly: python scripts/validate_crawls.py")
        sys.exit(1)
    else:
        print("All checked items conform to the simple schema (required fields present, no unexpected keys).")
        sys.exit(0)


if __name__ == '__main__':
    main()
