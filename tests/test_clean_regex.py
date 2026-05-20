import sys
from pathlib import Path

# Add the directory containing clean_job_text to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
CLEAN_DIR = WORKSPACE_ROOT / "Db" / "pipeline" / "clean" / "2_clean_data"
sys.path.insert(0, str(CLEAN_DIR))

try:
    from clean_job_text import clean_description_html
except ImportError as e:
    print(f"Error importing clean_description_html: {e}")
    sys.exit(1)

def run_tests():
    test_cases = [
        {
            "id": 1,
            "name": "Toán tử toán học đơn lẻ (< 3 năm)",
            "input": "Yêu cầu ứng viên có < 3 năm kinh nghiệm lập trình.",
            "expect_contains": ["< 3 năm", "kinh nghiệm"]
        },
        {
            "id": 5,
            "name": "Toán tử toán học kép (< và >)",
            "input": "Yêu cầu ứng viên có < 5 năm kinh nghiệm và lương > 20 triệu.",
            "expect_contains": ["< 5 năm", "lương > 20 triệu"]
        },
        {
            "id": 2,
            "name": "Generic Type (List<String>)",
            "input": "Thành thạo Java Collections như List<String> hoặc Map<Integer, Object>.",
            "expect_contains": ["List<String>", "Map<Integer, Object>"]
        },
        {
            "id": 3,
            "name": "Thẻ HTML chuẩn (div/p)",
            "input": "<div><p>Nội dung mô tả công việc hợp lệ</p></div>",
            "expect_contains": ["Nội dung mô tả công việc hợp lệ"],
            "expect_excludes": ["<div>", "<p>", "</p>", "</div>"]
        },
        {
            "id": 4,
            "name": "Mã rác (script/style)",
            "input": "<script>alert('hack');</script> Ngôn ngữ Python <style>body {}</style>",
            "expect_contains": ["Ngôn ngữ Python"],
            "expect_excludes": ["<script>", "alert('hack')", "<style>", "body {}"]
        }
    ]

    print("="*60)
    print("RUNNING HTML CLEANING REGEX TESTS")
    print("="*60)

    all_passed = True
    for tc in test_cases:
        output = clean_description_html(tc["input"])
        print(f"\n[Case {tc['id']}] {tc['name']}")
        print(f"  Input:  {tc['input']}")
        print(f"  Output: {output}")

        passed = True
        
        # Check expected contents
        for ec in tc.get("expect_contains", []):
            if ec not in output:
                print(f"  [-] FAIL: Expected to contain '{ec}' but did not.")
                passed = False
                
        # Check excluded contents
        for ex in tc.get("expect_excludes", []):
            if ex in output:
                print(f"  [-] FAIL: Expected NOT to contain '{ex}' but it did.")
                passed = False

        if passed:
            print("  [+] PASS")
        else:
            all_passed = False

    if all_passed:
        print("\n=== ALL TESTS PASSED ===")
    else:
        print("\n=== SOME TESTS FAILED ===")

if __name__ == "__main__":
    run_tests()
