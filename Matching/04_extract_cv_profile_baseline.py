import json
import re
from pathlib import Path
from typing import List, Dict, Any

import easyocr
from constants import ALL_SKILLS


# optional: only used when CV is pdf/doc/docx/txt
try:
    from pyresparser import ResumeParser
    HAS_PYRESPARSER = True
except Exception:
    HAS_PYRESPARSER = False

SCRIPT_DIR = Path(__file__).resolve().parent
CV_DIR = SCRIPT_DIR / "Dataset" / "test"
OUTPUT_PATH = SCRIPT_DIR / "cv_profiles_baseline.json"

reader = easyocr.Reader(["vi", "en"])


def unique_keep_order(items):
    seen = set()
    result = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result


def normalize_text(text: str) -> str:
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


TITLE_MAP = {
    "tester intern": "Tester Intern",
    "qa tester": "QA Tester",
    "it helpdesk": "IT Helpdesk",
    "front-end developer": "Front-end Developer",
    "frontend developer": "Frontend Developer",
    "back-end developer": "Back-end Developer",
    "backend developer": "Backend Developer",
    "full-stack developer": "Full-stack Developer",
    "business analyst": "Business Analyst",
    "data analyst": "Data Analyst",
}

SKILL_NORMALIZATION = {
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "sql": "SQL",
    "selenium": "Selenium",
    "agile": "Agile",
    "scrum": "Scrum",
    "jira": "JIRA",
    "html": "HTML",
    "css": "CSS",
    "github": "GitHub",
    "postman": "Postman",
    "testrail": "TestRail",
    "uat": "UAT",
    "api testing": "API Testing",
    "functional testing": "Functional Testing",
    "regression testing": "Regression Testing",
    "chrome devtools": "Chrome DevTools",
    "waterfall": "Waterfall",
    "lan": "LAN",
    "wan": "WAN",
    "email": "Email",
    "file server": "File Server",
    "domain controller": "Domain Controller",
    "technical support": "Technical Support",
    "troubleshooting": "Troubleshooting",
    "hardware": "Hardware",
    "software": "Software",
    "windows": "Windows",
    "networking": "Networking",
    "it support": "IT Support",
}

def normalize_skills(skills):
    normalized = []
    seen = set()

    for skill in skills:
        key = skill.strip().lower()
        canonical = SKILL_NORMALIZATION.get(key, skill.strip())

        dedupe_key = canonical.lower()
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            normalized.append(canonical)

    return normalized

def extract_name(lines: List[str]) -> str:
    banned_keywords = [
        "INTERN", "DEVELOPER", "TESTER", "HELPDESK", "ENGINEER",
        "ANALYST", "QA", "FRONT-END", "BACK-END", "FULLSTACK",
        "KỸ NĂNG", "GIỚI THIỆU", "HỌC VẤN", "CHỨNG CHỈ",
        "KINH NGHIỆM", "MỤC TIÊU"
    ]

    candidates = []

    for line in lines[:12]:
        clean = line.strip()
        if not clean:
            continue
        if any(keyword in clean.upper() for keyword in banned_keywords):
            continue
        if any(ch.isdigit() for ch in clean):
            continue
        if len(clean) < 6 or len(clean) > 40:
            continue

        words = clean.split()
        if len(words) < 2 or len(words) > 6:
            continue

        alpha_chars = [c for c in clean if c.isalpha()]
        if not alpha_chars:
            continue

        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)

        score = 0
        if upper_ratio >= 0.6:
            score += 2
        if len(words) in [3, 4]:
            score += 2
        if all(word[:1].isupper() for word in words if word):
            score += 2

        candidates.append((score, clean))

    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][1]

    return ""


def extract_title(raw_text: str) -> str:
    text = normalize_text(raw_text).lower()
    head = text[:1200]

    for key, display in TITLE_MAP.items():
        if key in head:
            return display

    for line in raw_text.splitlines():
        line_norm = normalize_text(line).lower()
        for key, display in TITLE_MAP.items():
            if key in line_norm:
                return display

    return ""


def extract_certifications(lines: List[str]) -> List[str]:
    cert_keywords = [
        "ISTQB", "TOEIC", "IELTS", "MOS", "AWS", "AZURE",
        "FOUNDATION LEVEL"
    ]

    certs = []
    for line in lines:
        if any(keyword in line.upper() for keyword in cert_keywords):
            certs.append(line)

    return unique_keep_order(certs)


def extract_skills(raw_text: str) -> List[str]:
    text_lower = raw_text.lower()
    found = []

    for skill in ALL_SKILLS:
        skill_clean = skill.strip()
        if len(skill_clean) < 2:
            continue

        pattern = r"(?<![a-zA-Z0-9])" + re.escape(skill_clean.lower()) + r"(?![a-zA-Z0-9])"
        if re.search(pattern, text_lower):
            found.append(skill_clean)

    extra_rules = {
        "API Testing": ["kiểm thử api"],
        "Functional Testing": ["kiểm thử chức năng"],
        "Regression Testing": ["kiểm thử hồi quy"],
        "UAT": ["uat", "kiểm thử uat"],
        "Agile": ["agile"],
        "Scrum": ["scrum"],
        "SQL": ["truy vấn sql", "sql đơn giản", "kiểm tra dữ liệu"],
        "Postman": ["postman"],
        "Selenium": ["selenium"],
        "JIRA": ["jira"],
        "TestRail": ["testrail"],
        "Python": ["python"],
        "JavaScript": ["javascript", "javascrift"],
        "HTML": ["html", "html5", "htmls"],
        "CSS": ["css", "css3"],
        "GitHub": ["github", "githubard"],
        "Chrome DevTools": ["chrome devtools"],
        "Waterfall": ["waterfall"],
        "Technical Support": ["hỗ trợ kỹ thuật", "technical support"],
        "Troubleshooting": ["xử lý sự cố", "troubleshooting"],
        "Hardware": ["phần cứng", "hardware"],
        "Software": ["phần mềm", "software"],
        "Windows": ["windows", "hệ điều hành windows"],
        "Networking": ["mạng máy tính", "network", "networking"],
        "IT Support": ["it support", "it helpdesk"],
    }

    for canonical_skill, patterns in extra_rules.items():
        for p in patterns:
            if p in text_lower:
                found.append(canonical_skill)
                break

    return normalize_skills(unique_keep_order(found))

def infer_skills(title: str, skills_extracted: List[str]) -> List[str]:
    inferred = []
    title_upper = title.upper()
    lower_skills = {s.lower() for s in skills_extracted}

    if "TESTER" in title_upper or "QA" in title_upper:
        for s in ["Kiểm thử hướng chất lượng", "Quy trình kiểm thử phần mềm", "Tư duy kiểm thử"]:
            inferred.append(s)

    if "HELPDESK" in title_upper:
        for s in ["Hỗ trợ kỹ thuật", "Xử lý sự cố", "Giao tiếp với người dùng"]:
            inferred.append(s)

    if "FRONT-END" in title_upper or "DEVELOPER" in title_upper:
        for s in ["Xây dựng giao diện web", "Tích hợp giao diện", "Tối ưu hiển thị đa trình duyệt"]:
            inferred.append(s)

    return unique_keep_order(inferred)


def parse_with_pyresparser(file_path: Path) -> Dict[str, Any]:
    if not HAS_PYRESPARSER:
        return {}

    if file_path.suffix.lower() not in {".pdf", ".doc", ".docx", ".txt"}:
        return {}

    try:
        data = ResumeParser(str(file_path)).get_extracted_data() or {}
        return {
            "name": data.get("name") or "",
            "title": (data.get("designation")[0] if isinstance(data.get("designation"), list) and data.get("designation") else "") or "",
            "skills_extracted": data.get("skills") or [],
            "certifications": [],
            "inferred_skills": []
        }
    except Exception:
        return {}


def parse_with_ocr_and_rules(file_path: Path) -> Dict[str, Any]:
    ocr_lines = reader.readtext(str(file_path), detail=0)
    full_text = normalize_text("\n".join(ocr_lines))
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]

    name = extract_name(lines)
    title = extract_title(full_text)
    skills_extracted = extract_skills(full_text)
    certifications = extract_certifications(lines)
    inferred_skills = infer_skills(title, skills_extracted)

    return {
        "raw_text": full_text,
        "name": name,
        "title": title,
        "skills_extracted": skills_extracted,
        "certifications": certifications,
        "inferred_skills": inferred_skills
    }


def merge_profiles(lib_profile: Dict[str, Any], fallback_profile: Dict[str, Any]) -> Dict[str, Any]:
    if not lib_profile:
        return fallback_profile

    return {
        "raw_text": fallback_profile.get("raw_text", ""),
        "name": lib_profile.get("name") or fallback_profile.get("name", ""),
        "title": lib_profile.get("title") or fallback_profile.get("title", ""),
        "skills_extracted": unique_keep_order(
            (lib_profile.get("skills_extracted") or []) + (fallback_profile.get("skills_extracted") or [])
        ),
        "certifications": unique_keep_order(
            (lib_profile.get("certifications") or []) + (fallback_profile.get("certifications") or [])
        ),
        "inferred_skills": fallback_profile.get("inferred_skills", [])
    }


def main():
    files = sorted([
        *CV_DIR.glob("*.png"),
        *CV_DIR.glob("*.jpg"),
        *CV_DIR.glob("*.jpeg"),
        *CV_DIR.glob("*.pdf"),
        *CV_DIR.glob("*.doc"),
        *CV_DIR.glob("*.docx"),
        *CV_DIR.glob("*.txt"),
    ])

    results = []

    for idx, file_path in enumerate(files, start=1):
        lib_profile = parse_with_pyresparser(file_path)

        if file_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            fallback_profile = parse_with_ocr_and_rules(file_path)
        else:
            try:
                raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                raw_text = ""

            raw_text = normalize_text(raw_text)
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            name = extract_name(lines)
            title = extract_title(raw_text)
            skills_extracted = extract_skills(raw_text)

            fallback_profile = {
                
                "raw_text": raw_text,
                "name": name,
                "title": title,
                "skills_extracted": skills_extracted,
                "certifications": extract_certifications(lines),
                "inferred_skills": infer_skills(title, skills_extracted),
            }

        profile = merge_profiles(lib_profile, fallback_profile)
        profile["cv_id"] = f"cv_{idx:02d}"
        profile["file_name"] = file_path.name
        results.append(profile)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(results)} CV profiles to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()