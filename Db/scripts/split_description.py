import re
import os
import json
import argparse
import html
from pathlib import Path
from bs4 import BeautifulSoup

def _looks_like_html(content: str) -> bool:
    return bool(re.search(r"</?[a-zA-Z][a-zA-Z0-9:-]*(\s+[^>]*)?>", content or ""))

def _normalize_spaces(content: str) -> str:
    return re.sub(r"\s+", " ", content or "").strip()

def _format_plain_text_for_ui(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""

    heading_patterns = [
        r"Mô tả Công việc",
        r"Yêu Cầu Công Việc",
        r"Quyền lợi",
        r"Phúc lợi",
        r"TRÁCH NHIỆM CHÍNH",
        r"YÊU CẦU",
        r"Job description",
        r"What you will do",
        r"Your skills and experience",
        r"Why you'll love working here",
        r"Top 3 reasons to join us",
        r"Requirements",
        r"Responsibilities",
    ]

    # Old DB rows may be flattened into one long line. Reintroduce structural
    # breaks before headings and list markers so the UI can render readable HTML.
    text = re.sub(r"\s*•\s*", "\n• ", text)
    for pattern in heading_patterns:
        text = re.sub(rf"\s*({re.escape(pattern)})\s*", r"\n\1\n", text, flags=re.I)

    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]

    html_parts = []
    list_items = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            html_parts.append("<ul>")
            html_parts.extend(f"<li>{item}</li>" for item in list_items)
            html_parts.append("</ul>")
            list_items = []

    def is_heading(line: str) -> bool:
        low = line.lower()
        if len(line) > 90:
            return False
        normalized_headings = [h.lower() for h in heading_patterns]
        if low in normalized_headings:
            return True
        return bool(re.fullmatch(r"[A-Z0-9\s/&,-]{4,}", line))

    for line in lines:
        bullet_match = re.match(r"^(?:•|-|\*)\s*(.+)$", line)
        if bullet_match:
            list_items.append(html.escape(bullet_match.group(1).strip()))
            continue

        flush_list()
        escaped = html.escape(line)
        if is_heading(line):
            html_parts.append(f"<h3>{escaped}</h3>")
        else:
            html_parts.append(f"<p>{escaped}</p>")

    flush_list()
    return "\n".join(html_parts)

def _trim_plain_text_from_marker(content: str, start_patterns: list[str], stop_patterns: list[str] | None = None) -> str:
    text = content or ""
    if not text.strip():
        return ""

    start_at = None
    for pattern in start_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match and (start_at is None or match.start() < start_at):
            start_at = match.start()

    if start_at is None:
        return _format_plain_text_for_ui(text)

    trimmed = text[start_at:].strip()
    stop_at = None
    for pattern in stop_patterns or []:
        match = re.search(pattern, trimmed, flags=re.I)
        if match and match.start() > 0 and (stop_at is None or match.start() < stop_at):
            stop_at = match.start()

    if stop_at is not None:
        trimmed = trimmed[:stop_at].strip()

    return _format_plain_text_for_ui(trimmed or text)

def clean_itviec_description(html_content: str) -> str:
    """
    Extracts only the job content section (JD, requirements, benefits) from ITviec HTML.
    Removes the job header (title, salary) and employer information section.
    """
    if not html_content:
        return ""

    if not _looks_like_html(html_content):
        return _trim_plain_text_from_marker(
            html_content,
            [
                r"\bjob description\b",
                r"\byour skills and experience\b",
                r"\btop\s+\d+\s+reasons?\s+to\s+join\s+us\b",
            ],
            [
                r"\babout\s+company\b",
                r"\bcompany\s+overview\b",
                r"\bmore\s+jobs?\s+from\b",
            ],
        )
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Try to find the job content section
    content_sec = soup.select_one("section.job-content, section[data-jobs--jd-scroll-target='jobContent']")
    if content_sec:
        # Decompose any script, style, or buttons inside it
        for tag in content_sec.find_all(["button", "script", "style"]):
            tag.decompose()
        return str(content_sec)
        
    # If not found directly, check if the full preview block was passed, and decompose header & employer info
    for css in [".job-show-header", "section.job-show-employer-info", ".job-show-employer-info"]:
        for elem in soup.select(css):
            elem.decompose()
            
    for tag in soup.find_all(["button", "script", "style"]):
        tag.decompose()
        
    return str(soup)

def clean_careerviet_description(html_content: str) -> str:
    """
    Extracts only the job details tab (tab-1) from CareerViet HTML,
    and keeps only the content from "Mô tả Công việc" heading downwards.
    """
    if not html_content:
        return ""

    if not _looks_like_html(html_content):
        return _trim_plain_text_from_marker(
            html_content,
            [
                r"mô\s+tả\s+công\s+việc",
                r"mo\s+ta\s+cong\s+viec",
                r"mÃ´\s+táº£\s+cÃ´ng\s+viá»‡c",
            ],
            [
                r"thông\s+tin\s+công\s+ty",
                r"thong\s+tin\s+cong\s+ty",
                r"thÃ´ng\s+tin\s+cÃ´ng\s+ty",
                r"việc\s+làm\s+tương\s+tự",
                r"viec\s+lam\s+tuong\s+tu",
            ],
        )
        
    soup = BeautifulSoup(html_content, "lxml")
    
    # Check if tabs wrapper is present
    tab1 = soup.select_one("div.tab-content#tab-1, #tab-1")
    target_node = tab1 if tab1 else soup
    
    # Decompose general unrelated elements first
    for css in [
        "#related-jobs-new",
        ".job-detail-bottom",
        ".share-this-job",
        ".job-tags",
        ".detail-row.request",
        "#tab-2",
        "nav.job-result-nav",
        ".job-result-nav",
        ".job-detail-tool",
        ".tabs-toggle",
    ]:
        for node in target_node.select(css):
            node.decompose()

    # Find the "Mô tả Công việc" container
    jd_container = None
    for row in target_node.find_all(class_=re.compile(r"detail-row|content_fck")):
        title_elem = row.find(class_=re.compile(r"detail-title|title"))
        title_text = title_elem.get_text().lower() if title_elem else ""
        if "mô tả" in title_text and "công việc" in title_text:
            jd_container = row
            break
            
    if not jd_container:
        # Fallback to direct headings
        for h in target_node.find_all(["h2", "h3", "h4"]):
            h_text = h.get_text().lower()
            if "mô tả" in h_text and "công việc" in h_text:
                jd_container = h.parent if h.parent else h
                break
                
    if jd_container:
        # Decompose all preceding siblings of the job description container
        parent = jd_container.parent
        if parent:
            siblings = list(parent.contents)
            try:
                idx = siblings.index(jd_container)
                for node in siblings[:idx]:
                    if hasattr(node, "decompose"):
                        node.decompose()
            except ValueError:
                pass
                
    if tab1:
        if tab1.body and tab1.body.contents:
            return "".join(str(node) for node in tab1.body.contents)
        return str(tab1)
        
    if soup.body and soup.body.contents:
        for node in soup.body.contents:
            if getattr(node, "name", None):
                return str(node)
        return "".join(str(node) for node in soup.body.contents)
    return str(soup)

def clean_vietnamworks_description(html_content: str) -> str:
    """
    Removes the company profile (Thông tin công ty) block from VietnamWorks HTML.
    """
    if not html_content:
        return ""

    if not _looks_like_html(html_content):
        return _trim_plain_text_from_marker(
            html_content,
            [
                r"mô\s+tả\s+công\s+việc",
                r"mo\s+ta\s+cong\s+viec",
                r"\bjob\s+description\b",
                r"\bwhat\s+you\s+will\s+do\b",
            ],
            [
                r"thông\s+tin\s+công\s+ty",
                r"thong\s+tin\s+cong\s+ty",
                r"việc\s+làm\s+tương\s+tự",
                r"viec\s+lam\s+tuong\s+tu",
            ],
        )
        
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Find heading "Thông tin công ty"
    company_heading = soup.find(["h3", "h2", "h4", "p"], string=re.compile(r"Thông tin công ty", re.I))
    if company_heading:
        # Remove the heading and all subsequent elements
        siblings_to_remove = []
        curr = company_heading
        while curr:
            siblings_to_remove.append(curr)
            curr = curr.next_sibling
            
        for node in siblings_to_remove:
            if hasattr(node, "decompose"):
                node.decompose()
                
    return str(soup)

def clean_linkedin_description(html_content: str) -> str:
    """
    Removes the custom top header metadata section from LinkedIn HTML
    and prepends '<h2>About the job</h2>' at the top.
    """
    if not html_content:
        return ""

    if not _looks_like_html(html_content):
        return _trim_plain_text_from_marker(
            html_content,
            [
                r"\babout\s+the\s+job\b",
                r"\bjob\s+description\b",
                r"\bresponsibilities\b",
                r"\bwhat\s+you(?:'|’)?ll\s+do\b",
            ],
            [
                r"\babout\s+the\s+company\b",
                r"\bcompany\s+overview\b",
                r"\bequal\s+opportunity\b",
                r"\bseniority\s+level\b",
                r"\bemployment\s+type\b",
                r"\bjob\s+function\b",
                r"\bindustries\b",
            ],
        )
        
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Find and remove class "linkedin-job-header"
    header = soup.select_one("section.linkedin-job-header")
    if header:
        header.decompose()
        
    cleaned_html = str(soup).strip()
    if not cleaned_html.lower().startswith("<h2>about the job</h2>"):
        cleaned_html = f"<h2>About the job</h2>\n{cleaned_html}"
        
    return cleaned_html

def extract_clean_job_description(source: str, html_content: str) -> str:
    """
    Unified router to extract only core job details (JD, requirements, benefits)
    from raw description_html depending on the source platform.
    """
    if not html_content or not source:
        return html_content or ""
        
    src_lower = source.strip().lower()
    
    if "itviec" in src_lower:
        return clean_itviec_description(html_content)
    elif "careerviet" in src_lower:
        return clean_careerviet_description(html_content)
    elif "vietnamworks" in src_lower:
        return clean_vietnamworks_description(html_content)
    elif "linkedin" in src_lower:
        return clean_linkedin_description(html_content)
        
    return html_content

def process_jobs_file(input_path: str, output_path: str):
    """
    Helper CLI function to test description splitting on a JSON file containing job dicts.
    """
    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        return
        
    with open(input_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
        
    print(f"🔄 Processing {len(jobs)} jobs from {input_path}...")
    
    processed_count = 0
    for job in jobs:
        src = job.get("source_name") or job.get("source")
        raw_desc = job.get("description_html") or ""
        
        if raw_desc and src:
            cleaned_desc = extract_clean_job_description(src, raw_desc)
            job["description_html_original"] = raw_desc # Keep backup
            job["description_html"] = cleaned_desc
            processed_count += 1
            
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Successfully processed and saved {processed_count} jobs description to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split and clean job descriptions independently")
    parser.add_argument("--input", help="Path to jobs_combined.json file")
    parser.add_argument("--output", help="Path to save processed output JSON file")
    args = parser.parse_args()
    
    if args.input and args.output:
        process_jobs_file(args.input, args.output)
    else:
        # Run self-tests on mock HTML strings
        print("Running self-test on splitting code...")
        
        # Test LinkedIn
        mock_li = '<section class="linkedin-job-header"><h2 class="linkedin-title">Dev</h2></section><div>JD Content</div>'
        assert "linkedin-title" not in clean_linkedin_description(mock_li)
        assert "JD Content" in clean_linkedin_description(mock_li)
        
        # Test VietnamWorks
        mock_vnw = '<div>JD</div><h3>Thông tin công ty</h3><p>MB Bank details</p>'
        assert "MB Bank details" not in clean_vietnamworks_description(mock_vnw)
        assert "JD" in clean_vietnamworks_description(mock_vnw)
        
        print("Self-tests passed successfully!")
