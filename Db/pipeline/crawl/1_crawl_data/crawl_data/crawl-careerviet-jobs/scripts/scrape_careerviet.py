import time
import re
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Iterable
from urllib.parse import urljoin, urlparse

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# Import schema chuẩn
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from schema import RawJobData
from date_filter import describe_date_filter, is_posted_date_allowed, parse_iso_date
from central_filters import filter_recent_jobs

BASE = "https://careerviet.vn"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/123.0.0.0 Safari/537.36"),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://careerviet.vn/",
    "Connection": "keep-alive",
}

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=6, connect=3, read=3, status=6,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    try:
        s.get(BASE, timeout=20)
        time.sleep(0.6)
    except requests.RequestException:
        pass
    return s

def text(el) -> Optional[str]:
    if not el:
        return None

    import re as _re
    try:
        t = el.get_text(" ", strip=True)
    except Exception:
        try:
            t = str(el)
        except Exception:
            t = None
    return _re.sub(r"\s+", " ", t) if t else None


def extract_careerviet_posted_date(soup: BeautifulSoup):
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                parsed = parse_iso_date(item.get("datePosted"))
                if parsed:
                    return parsed

    html = str(soup)
    for pattern in [r'"job_active_date":"([^"]+)"', r'"date_view":"([^"]+)"', r'"datePosted":"([^"]+)"']:
        match = re.search(pattern, html)
        if match:
            parsed = parse_iso_date(match.group(1))
            if parsed:
                return parsed

    for li in soup.select("div.detail-box.has-background li"):
        label = li.find("strong")
        if not label:
            continue
        label_text = text(label) or ""
        if not re.search(r"Ngày cập nhật", label_text, re.I):
            continue

        value_node = li.find("p")
        container_text = text(value_node) or text(li) or ""
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", container_text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
            except Exception:
                pass

    update_label = soup.find(string=re.compile(r"Ngày cập nhật", re.I))
    if update_label:
        parent = update_label.parent if hasattr(update_label, "parent") else None
        container_text = text(parent) or text(parent.parent if parent and hasattr(parent, "parent") else None) or ""
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", container_text)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
            except Exception:
                pass

    return None
    import re as _re
    try:
        # Lấy tất cả text node và filter None
        text_parts = [str(s) for s in el.strings if s]
        if not text_parts:
            return None
        t = " ".join(text_parts)
        return _re.sub(r"\s+", " ", t) if t else None
    except (TypeError, AttributeError):
        return None

def smart_sleep(min_s=0.6, max_s=1.4):
    time.sleep(random.uniform(min_s, max_s))

def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    for attempt in range(1, 6):
        r = session.get(url, timeout=30)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = int(retry_after)
                except ValueError:
                    wait = 5 * attempt
            else:
                wait = 5 * attempt
            wait += random.uniform(0.5, 1.5)
            print(f"[WARN] 429 tại {url} → ngủ {wait:.1f}s (attempt {attempt})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    r.raise_for_status()
    return BeautifulSoup("", "lxml")

# ---------- Paging helpers ----------
def build_paged_url(list_url_page1: str, page: int) -> str:
    """
    CareerViet page 2 mẫu: https://careerviet.vn/viec-lam/ai-k-trang-2-vi.html
    Quy tắc: chèn '-trang-{page}-' trước 'vi.html'. Trang 1 giữ nguyên URL gốc.
    """
    if page <= 1:
        return list_url_page1
    # Thay ...-vi.html -> ...-trang-{page}-vi.html
    return re.sub(r"-vi\.html$", f"-trang-{page}-vi.html", list_url_page1)

# ---------- Search page ----------
def parse_search_page(session: requests.Session, url: str) -> List[Dict]:
    soup = get_soup(session, url)
    jobs: List[Dict] = []

    # Nhiều bố cục khả dĩ, thử lần lượt
    cards = soup.select(
        "div.job-item, div.job-item-list, div.job, li.job, div#jobs-found div.job-item"
    )
    if not cards:
        # Fallback: bất kỳ thẻ có link tới trang job detail
        cards = [a.parent for a in soup.select("a[href*='/vi/tim-viec-lam/']")]

    for card in cards:
        a_title = None
        for css in [
            "a.job_link[href]",
            "h2 a[href*='/vi/tim-viec-lam/']",
            "h3 a[href*='/vi/tim-viec-lam/']",
            "a[href*='/vi/tim-viec-lam/']",
        ]:
            a_title = card.select_one(css)
            if a_title:
                break
        if not a_title:
            continue

        title = text(a_title)
        job_url = urljoin(BASE, a_title.get("href"))

        comp_a = None
        for css in [
            "a[href*='/vi/nha-tuyen-dung/']",
            ".company a[href]",
            "a.company[href]",
        ]:
            comp_a = card.select_one(css)
            if comp_a:
                break
        company = text(comp_a) if comp_a else text(card.select_one(".company, .job-company"))
        company_url = urljoin(BASE, comp_a.get("href")) if comp_a and comp_a.has_attr("href") else None

        # Thông tin tóm tắt (có thể rải rác)
        salary = None
        for css in [".salary", ".job-salary", ".content-salary", ".tag-salary", "li.salary"]:
            el = card.select_one(css)
            if el and text(el):
                salary = text(el)
                break

        address = None
        for css in [".location", ".job-location", ".content-location", ".work-location", "li.location"]:
            el = card.select_one(css)
            if el and text(el):
                address = text(el)
                break

        exp = None
        for css in [".experience", ".job-exp", "li.experience", "li:contains('Kinh nghiệm')"]:
            el = card.select_one(css) if ":contains" not in css else None
            if el and text(el):
                exp = text(el)
                break

        jobs.append({
            "title": title,
            "job_url": job_url,
            "company": company,
            "company_url": company_url,
            "salary_list": salary,
            "address_list": address,
            "exp_list": exp,
        })
    return jobs

# ---------- Job detail ----------
def pick_info_value(soup: BeautifulSoup, label_keywords: Iterable[str]) -> Optional[str]:
    """
    Quét các vùng 'thông tin công việc' để tìm giá trị theo nhãn (VD: Mức lương/Địa điểm/Kinh nghiệm).
    Hỗ trợ cấu trúc: <li><strong>Label</strong><p>Value</p></li>
    """
    # Tìm tất cả <li> elements trong toàn bộ trang
    for li in soup.select("li"):
        # Tìm <strong> tag trong li
        strong_el = li.find("strong")
        if not strong_el:
            continue
        
        label = (text(strong_el) or "").lower().strip()
        
        # Kiểm tra nếu label khớp với keywords
        for kw in label_keywords:
            if kw.lower() in label:
                # Tìm <p> tag trong cùng li
                p_el = li.find("p")
                if p_el:
                    value = text(p_el)
                    if value:
                        return value.strip()
                # Fallback: lấy text sau strong
                li_text = text(li) or ""
                value = li_text.replace(text(strong_el) or "", "", 1).strip()
                if value:
                    return value
    
    # Fallback: Quét các container cũ
    containers = [
        "ul.job-info", ".job-summary", ".job-attributes", ".job-detail", ".section-content", "div#job-summary"
    ]
    for css in containers:
        container = soup.select_one(css)
        if not container:
            continue
        for row in container.select("li, .row, .item, .info-item"):
            row_text = text(row) or ""
            label_el = None
            for lab_css in ["label", "span.label", "span.lbl", "strong", "b"]:
                label_el = row.select_one(lab_css)
                if label_el:
                    break
            label = (text(label_el) or "").lower()
            value = row_text
            if label:
                value = re.sub(re.escape(text(label_el) or ""), "", value).strip(" :-–—")
            for kw in label_keywords:
                if kw.lower() in label or kw.lower() in row_text.lower():
                    # Làm sạch value lần nữa
                    m = re.split(r"[:：]", row_text, maxsplit=1)
                    if len(m) == 2:
                        value = m[1].strip()
                    return value
    return None

def extract_deadline(soup: BeautifulSoup) -> Optional[str]:
    """Extract deadline từ các cấu trúc khác nhau trong trang job detail."""
    # Cách 1: Tìm text chứa date pattern gần 'Hết hạn nộp'
    for container in soup.select("li, div.item-blue, .detail-box"):
        cont_text = text(container) or ""
        if "Hết hạn nộp" in cont_text or "Hạn nộp" in cont_text:
            # Tìm date pattern trong container hoặc sibling
            date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", cont_text)
            if date_match:
                return date_match.group(1)
            # Kiểm tra <p> sibling
            p = container.find("p")
            if p:
                p_text = text(p)
                if p_text:
                    date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", p_text)
                    if date_match:
                        return date_match.group(1)
    
    # Cách 2: Find string với date pattern gần 'Hết hạn nộp'
    cand = soup.find(string=re.compile(r"Hạn nộp|Hết hạn|Deadline|Hết hạn nộp", re.I))
    if cand:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", cand)
        if m:
            return m.group(1)
        # Kiểm tra parent hoặc next sibling
        for sibling in cand.parent.find_all(["p", "span", "li"], recursive=False):
            sib_text = text(sibling)
            if sib_text:
                date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", sib_text)
                if date_match:
                    return date_match.group(1)
    
    return None

def extract_tags(soup: BeautifulSoup):
    tags = []
    for css in [".tags a", ".job-tags a", "ul.tags a", ".skills a", ".tag-list a"]:
        tags.extend([text(a) for a in soup.select(css) if text(a)])
    return list(dict.fromkeys(tags))

def extract_desc_blocks(soup: BeautifulSoup):
    """
    Tìm các mục mô tả theo heading 'Mô tả Công việc', 'Yêu Cầu Công Việc', 'Quyền lợi/Phúc lợi'
    Nắm bắt đầy đủ content từ lists, paragraphs, và divs sau heading.
    Hỗ trợ cấu trúc welfare-list đặc biệt cho phúc lợi.
    """
    data = {}
    
    for h in soup.select("h2, h3, h4"):
        ht = (text(h) or "").lower()
        section_type = None
        
        if "mô tả" in ht and "công việc" in ht:
            section_type = "Mô tả công việc"
        elif "yêu cầu" in ht and "công việc" in ht:
            section_type = "Yêu cầu ứng viên"
        elif "yêu cầu" in ht and "ứng viên" in ht:
            section_type = "Yêu cầu ứng viên"
        elif ("quyền lợi" in ht or "phúc lợi" in ht) and "công việc" not in ht:
            section_type = "Quyền lợi"
        
        if not section_type:
            continue
        
        # Gom các content sau heading
        content_parts = []
        
        # Tìm parent container (thường là div.detail-row hoặc div.detail-row.reset-bullet)
        parent = h.find_parent(class_=re.compile("detail-row")) or h.parent
        
        # Nếu là phúc lợi, lấy từ ul.welfare-list
        if section_type == "Quyền lợi":
            welfare_list = parent.select_one("ul.welfare-list")
            if welfare_list:
                for li in welfare_list.select("li"):
                    item_text = text(li)
                    if item_text:
                        content_parts.append(item_text)
        else:
            # Cho mô tả và yêu cầu, lấy từ paragraphs sau heading
            nxt = h.find_next_sibling()
            max_length = 5000
            
            while nxt and len(" ".join(content_parts)) < max_length:
                # Dừng nếu gặp heading mới cùng cấp hoặc cao hơn, hoặc div.detail-row
                if nxt.name and nxt.name.lower() in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    break
                if nxt.get("class") and "detail-row" in " ".join(nxt.get("class", [])):
                    break
                
                # Xử lý danh sách (ul/ol) - bỏ qua welfare-list
                if nxt.name in ("ul", "ol") and "welfare" not in (" ".join(nxt.get("class", []))):
                    for li in nxt.select("li"):
                        item_text = text(li)
                        if item_text:
                            content_parts.append(item_text)
                # Xử lý paragraph
                elif nxt.name == "p":
                    p_text = text(nxt)
                    if p_text:
                        content_parts.append(p_text)
                # Xử lý div có content
                elif nxt.name == "div":
                    div_text = text(nxt)
                    if div_text and len(div_text) > 10:
                        content_parts.append(div_text)
                
                nxt = nxt.find_next_sibling()
        
        # Join tất cả content
        if content_parts:
            full_content = " ".join([p for p in content_parts if p]).strip()
            # Làm sạch: loại bỏ các dòng trống
            full_content = re.sub(r"\s+", " ", full_content)
            if full_content:
                data[section_type] = full_content
    
    return data

def extract_other_info(soup: BeautifulSoup) -> Dict:
    """
    Trích xuất thông tin khác như bằng cấp, độ tuổi từ phần "Thông tin khác"
    """
    other_info = {
        "degree": None,
        "age_requirement": None,
    }
    
    # Tìm section "Thông tin khác"
    for h3 in soup.select("h3.detail-title"):
        if "Thông tin khác" in (text(h3) or ""):
            # Tìm parent div.detail-row
            parent = h3.find_parent(class_="detail-row")
            if parent:
                # Tìm div.content_fck
                content_div = parent.select_one(".content_fck")
                if content_div:
                    for li in content_div.select("li"):
                        li_text = (text(li) or "").strip()
                        if "Bằng cấp" in li_text or "bằng cấp" in li_text.lower():
                            # Tách giá trị
                            parts = li_text.split(":", 1)
                            if len(parts) == 2:
                                other_info["degree"] = parts[1].strip()
                        elif "Độ tuổi" in li_text or "độ tuổi" in li_text.lower():
                            parts = li_text.split(":", 1)
                            if len(parts) == 2:
                                other_info["age_requirement"] = parts[1].strip()
            break
    
    return other_info

def extract_company_link_from_job(soup: BeautifulSoup) -> Optional[str]:
    """Extract company URL từ job detail page"""
    cand = soup.select_one("a[href*='/vi/nha-tuyen-dung/']")
    return urljoin(BASE, cand["href"]) if cand and cand.has_attr("href") else None

def extract_job_source_id(job_url: str) -> Optional[str]:
    """Extract job ID từ URL"""
    # URL format: https://careerviet.vn/vi/tim-viec-lam/ai-engineer.35C5D54A.html
    # Extract: 35C5D54A
    match = re.search(r'\.([A-Z0-9]+)\.html$', job_url)
    if match:
        return match.group(1)
    return None

def extract_company_source_id(company_url: str) -> Optional[str]:
    """Extract company ID từ URL"""
    # URL format: https://careerviet.vn/vi/nha-tuyen-dung/cong-ty-co-phan-canifa.35A66CA5.html
    # Extract: 35A66CA5
    if not company_url:
        return None
    match = re.search(r'\.([A-Z0-9]+)\.html$', company_url)
    if match:
        return match.group(1)
    return None



def extract_employer_info_from_job(soup: BeautifulSoup) -> Dict:
    """
    Extract company info embedded directly on the job detail page.
    Supports `.job-show-employer-info` when present.
    """
    info = {
        "company_name_from_job": None,
        "company_logo_url": None,
        "company_profile_summary": None,
        "company_type": None,
        "company_industry_from_job": None,
        "company_size_from_job": None,
        "company_country": None,
        "company_working_days": None,
        "company_overtime_policy": None,
        "company_rating": None,
        "company_review_url": None,
    }

    block = soup.select_one("section.job-show-employer-info, .job-show-employer-info")
    if not block:
        return info

    name_anchor = block.select_one("h3 a[href], a[href*='/companies/']")
    if name_anchor:
        info["company_name_from_job"] = text(name_anchor)

    logo = block.select_one("img.employer-logo, img[src], img[data-src]")
    if logo:
        logo_url = logo.get("src") or logo.get("data-src")
        if logo_url:
            info["company_logo_url"] = logo_url.strip()

    summary = block.select_one(".imt-5 p, .imt-xl-4 p")
    if summary:
        info["company_profile_summary"] = text(summary)

    review_anchor = block.select_one("a[href*='/review']")
    if review_anchor and review_anchor.has_attr("href"):
        info["company_review_url"] = urljoin(BASE, review_anchor["href"])

    rating_node = block.select_one(".h4.ips-2.text-it-black, .h4.text-it-black")
    if rating_node:
        info["company_rating"] = text(rating_node)

    label_map = {
        "company type": "company_type",
        "company industry": "company_industry_from_job",
        "company size": "company_size_from_job",
        "country": "company_country",
        "working days": "company_working_days",
        "overtime policy": "company_overtime_policy",
    }

    for row in block.select("div.row"):
        cols = row.select(".col")
        if len(cols) < 2:
            continue

        label = re.sub(r"\s+", " ", (text(cols[0]) or "").strip().lower())
        value = (text(cols[1]) or "").strip()
        mapped_key = label_map.get(label)
        if mapped_key and value:
            info[mapped_key] = value

    return info

def merge_company_info(primary: Dict, fallback: Dict) -> Dict:
    """Keep values from primary when present, otherwise use fallback."""
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged

def _serialize_bs4_root(fragment: BeautifulSoup) -> str:
    if fragment.body and fragment.body.contents:
        for node in fragment.body.contents:
            if getattr(node, "name", None):
                return str(node)
        return "".join(str(node) for node in fragment.body.contents)
    return str(fragment)


def _build_company_tab_node(company_html: str) -> Optional[BeautifulSoup]:
    company_fragment = BeautifulSoup(company_html, "lxml")
    company_root = None

    if company_fragment.body:
        for node in company_fragment.body.contents:
            if getattr(node, "name", None):
                company_root = node
                break

    if company_root and company_root.name == "div" and company_root.get("id") == "tab-2":
        return company_root

    wrapper = BeautifulSoup(
        '<div class="tab-content" id="tab-2" style="display: block;"></div>',
        "lxml",
    )
    tab_node = wrapper.select_one("div.tab-content#tab-2")
    if not tab_node:
        return None

    if company_fragment.body:
        for node in list(company_fragment.body.contents):
            if getattr(node, "name", None):
                tab_node.append(node)

    return tab_node


def extract_job_detail_html(soup: BeautifulSoup, fallback_company_tab_html: Optional[str] = None) -> str:
    """
    Return the raw HTML block that contains the job detail page content.
    Prefer preserving the full CareerViet tabs wrapper so both tab-1 and tab-2
    are kept together. If tab-2 is empty on the job page, inject fallback
    company HTML into a synthetic/existing tab-2 node.
    """
    tabs_node = soup.select_one("div.tabs")
    if tabs_node:
        tabs_clone = BeautifulSoup(str(tabs_node), "lxml")
        for css in [
            "#related-jobs-new",
            ".job-detail-bottom",
            ".share-this-job",
            ".job-tags",
            ".detail-row.request",
        ]:
            for node in tabs_clone.select(css):
                node.decompose()

        tab2_clone = tabs_clone.select_one("div.tab-content#tab-2, #tab-2")
        tab2_has_content = bool(tab2_clone and tab2_clone.get_text(" ", strip=True))

        if fallback_company_tab_html and not tab2_has_content:
            replacement_tab2 = _build_company_tab_node(fallback_company_tab_html)
            if replacement_tab2:
                if tab2_clone:
                    tab2_clone.replace_with(replacement_tab2)
                else:
                    tab1_clone = tabs_clone.select_one("div.tab-content#tab-1, #tab-1")
                    if tab1_clone:
                        tab1_clone.insert_after(replacement_tab2)
                    else:
                        nav_clone = tabs_clone.select_one("nav.job-result-nav")
                        if nav_clone:
                            nav_clone.insert_after(replacement_tab2)
                        else:
                            tabs_root = tabs_clone.select_one("div.tabs")
                            if tabs_root:
                                tabs_root.append(replacement_tab2)

        return _serialize_bs4_root(tabs_clone)

    header_node = soup.select_one("div.job-desc")
    detail_node = (
        soup.select_one("section.job-detail-content")
        or soup.select_one("div.tab-content#tab-1")
        or soup.select_one("#tab-1")
    )

    html_parts = []
    if header_node:
        html_parts.append(str(header_node))

    if detail_node:
        detail_clone = BeautifulSoup(str(detail_node), "lxml")
        for css in [
            "#related-jobs-new",
            ".job-detail-bottom",
            ".share-this-job",
            ".job-tags",
            ".detail-row.request",
        ]:
            for node in detail_clone.select(css):
                node.decompose()
        html_parts.append(_serialize_bs4_root(detail_clone))

    if fallback_company_tab_html:
        html_parts.append(fallback_company_tab_html)

    if html_parts:
        return "\n".join(part for part in html_parts if part)

    selectors = [
        "div.job-detail",
        "section.job-detail",
        ".job-desc",
        "main",
        "body",
    ]
    for css in selectors:
        node = soup.select_one(css)
        if node:
            return str(node)
    return str(soup)


def extract_company_overview_html_from_company_page(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract the company overview block from the employer page so it can be
    appended when the job detail response does not include tab-2 directly.
    """
    for css in [
        "section.jobsby-company.cb-section",
        "section.jobsby-company",
        "div.tab-content#tab-2",
        "#tab-2",
        "section.company-overview.company-profile",
        "div.company-overview.company-profile",
        "div.company-overview",
        "div.company-introduction",
    ]:
        node = soup.select_one(css)
        if node:
            return str(node)
    return None

def scrape_job_detail(session: requests.Session, job_url: str) -> Dict:
    soup = get_soup(session, job_url)
    smart_sleep()

    title = text(soup.select_one("h1, .job-title, .job-detail h1"))
    salary = pick_info_value(soup, ["Mức lương", "Lương"])
    location = pick_info_value(soup, ["Địa điểm", "Nơi làm việc", "Làm việc tại"])
    experience = pick_info_value(soup, ["Kinh nghiệm"])
    deadline = extract_deadline(soup)
    tags = extract_tags(soup)
    desc_blocks = extract_desc_blocks(soup)
    company_url_detail = extract_company_link_from_job(soup)
    employer_info = extract_employer_info_from_job(soup)
    
    # Trích xuất thông tin khác (bằng cấp, độ tuổi)
    other_info = extract_other_info(soup)

    # Địa điểm/thời gian làm việc nếu có khối riêng
    working_addresses = None
    for lab in ["Địa điểm làm việc", "Nơi làm việc"]:
        val = pick_info_value(soup, [lab])
        if val:
            working_addresses = val
            break

    working_times = pick_info_value(soup, ["Thời gian làm việc", "Giờ làm việc"])
    
    # Employment type (Hình thức): Nhân viên chính thức, Thực tập, v.v.
    employment_type = pick_info_value(soup, ["Hình thức"])

    return {
        "detail_title": title,
        "detail_salary": salary,
        "detail_location": location,
        "detail_experience": experience,
        "detail_posted_date": extract_careerviet_posted_date(soup),
        "deadline": deadline,
        "tags": "; ".join(tags) if tags else None,
        "desc_mota": desc_blocks.get("Mô tả công việc"),
        "desc_yeucau": desc_blocks.get("Yêu cầu ứng viên"),
        "desc_quyenloi": desc_blocks.get("Quyền lợi"),
        "working_addresses": working_addresses,
        "working_times": working_times,
        "employment_type": employment_type,
        "degree": other_info.get("degree"),
        "age_requirement": other_info.get("age_requirement"),
        "company_url_from_job": company_url_detail,
        "company_name_from_job": employer_info.get("company_name_from_job"),
        "company_logo_url": employer_info.get("company_logo_url"),
        "company_profile_summary": employer_info.get("company_profile_summary"),
        "company_type": employer_info.get("company_type"),
        "company_industry_from_job": employer_info.get("company_industry_from_job"),
        "company_size_from_job": employer_info.get("company_size_from_job"),
        "company_country": employer_info.get("company_country"),
        "company_working_days": employer_info.get("company_working_days"),
        "company_overtime_policy": employer_info.get("company_overtime_policy"),
        "company_rating": employer_info.get("company_rating"),
        "company_review_url": employer_info.get("company_review_url"),
        "job_detail_html": extract_job_detail_html(soup),
    }

def convert_to_raw_job_data(job_dict: Dict, detail_dict: Dict, company_dict: Dict) -> RawJobData:
    """
    Convert CareerViet data to RawJobData schema (minimal - match vietnamworks)
    
    Args:
        job_dict: Dict từ parse_search_page (title, job_url, company, ...)
        detail_dict: Dict từ scrape_job_detail (detail_title, desc_mota, ...)
        company_dict: Dict từ scrape_company (company_name_full, company_website, ...)
    
    Returns:
        RawJobData object with minimal fields (title, description_html, company_name)
    """
    def _extract_benefits_from_desc(desc_text: Optional[str]) -> List[str]:
        if not desc_text:
            return []

        text_value = re.sub(r"\s+", " ", str(desc_text)).strip()
        if not text_value:
            return []

        parts = re.split(r"(?:\s*[•\-]\s+|\s*\|\s*|\s*;\s*|\s*\n\s*)", text_value)
        items = []
        for part in parts:
            item = re.sub(r"^\s*(?:Benefits?|Quyền lợi|Phúc lợi)\s*[:：-]?\s*", "", part, flags=re.I).strip()
            if item and item not in items:
                items.append(item)
        return items or [text_value]

    # Build full description HTML (kết hợp các phần mô tả)
    desc_parts = []
    if detail_dict.get("desc_mota"):
        desc_parts.append(f"<h3>Mô tả công việc</h3><p>{detail_dict['desc_mota']}</p>")
    if detail_dict.get("desc_yeucau"):
        desc_parts.append(f"<h3>Yêu cầu ứng viên</h3><p>{detail_dict['desc_yeucau']}</p>")
    if detail_dict.get("desc_quyenloi"):
        desc_parts.append(f"<h3>Quyền lợi</h3><p>{detail_dict['desc_quyenloi']}</p>")
    
    description_html = detail_dict.get("job_detail_html") or (
        "\n".join([p for p in desc_parts if p]) if desc_parts else ""
    )
    
    return RawJobData(
        # Identity
        source_name="careerviet",
        job_url=job_dict["job_url"],
        job_source_id=extract_job_source_id(job_dict["job_url"]),
        
        # Job Info
        title=detail_dict.get("detail_title") or job_dict["title"],
        description_html=description_html,
        
        # Attributes
        location_raw=detail_dict.get("working_addresses") or detail_dict.get("detail_location") or job_dict.get("address_list") or job_dict.get("location"),
        salary_raw=detail_dict.get("detail_salary") or job_dict.get("salary_list"),
        employment_type=detail_dict.get("employment_type"),
        experience_raw=detail_dict.get("detail_experience") or job_dict.get("exp_list"),
        posted_date=detail_dict.get("detail_posted_date").isoformat() if hasattr(detail_dict.get("detail_posted_date"), "isoformat") else detail_dict.get("detail_posted_date"),
        expiry_date=detail_dict.get("deadline").isoformat() if hasattr(detail_dict.get("deadline"), "isoformat") else detail_dict.get("deadline"),
        scraped_at=datetime.now().isoformat(),
        
        # Lists
        tags=[t.strip() for t in (detail_dict.get("tags") or "").split(";") if t.strip()],
        benefits=_extract_benefits_from_desc(detail_dict.get("desc_quyenloi")),
        
        # Company Info
        company_name=company_dict.get("company_name_full") or detail_dict.get("company_name_from_job") or job_dict.get("company") or job_dict.get("company_name"),
        company_source_id=extract_company_source_id(detail_dict.get("company_url_from_job") or job_dict.get("company_url")),
        company_website=company_dict.get("company_website"),
        company_address=company_dict.get("company_address") or detail_dict.get("company_country"),
        company_size_raw=company_dict.get("company_size") or detail_dict.get("company_size_from_job"),
        company_industry=company_dict.get("company_industry") or detail_dict.get("company_industry_from_job") or detail_dict.get("company_type"),
        requirements_text=detail_dict.get("desc_yeucau"),
    )

# ---------- Company page ----------
def scrape_company_website_improved(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract company website from company profile page.
    Tries multiple strategies to find the correct URL.
    """
    
    # Strategy 1: Look for links in company info sections
    for container in soup.select("div.company-info, div.company-overview, div.company-profile, li, .row"):
        container_text = (container.get_text(" ", strip=True) or "").lower()
        
        # Check if this container mentions website
        if "website" in container_text or "trang web" in container_text:
            # Try to find HTTP links in this container
            for a in container.select("a[href]"):
                href = (a.get("href") or "").strip()
                if href and not href.startswith("#"):
                    # Filter out internal careerviet links and relative links
                    if href.startswith("http") and "careerviet.vn" not in href:
                        return href
                    # Skip internal links
                    if href.startswith("/"):
                        continue
    
    # Strategy 2: Parse text content for "Website: URL" pattern
    text_content = soup.get_text("\n", strip=True)
    
    # Match patterns like "Website: https://..." or "Trang web: ..."
    patterns = [
        r'(?:Website|Trang\s*web)\s*[:：]\s*(https?://[^\s\n]+)',
        r'(?:Website|Trang\s*web)\s*[:：]\s*([a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}[^\s\n]*)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text_content, re.IGNORECASE)
        for match in matches:
            url = match.strip()
            # Skip internal careerviet URLs
            if "careerviet.vn" in url.lower():
                continue
            # Ensure it's a valid URL
            if not url.lower().startswith("http"):
                url = "https://" + url
            if url.startswith("http"):
                return url
    
    # Strategy 3: Check input field (as fallback)
    website_input = soup.select_one("input#emp_websitets")
    if website_input:
        value = (website_input.get("value") or "").strip()
        if value and "careerviet.vn" not in value:
            if not value.startswith("http"):
                value = "https://" + value
            return value if value.startswith("http") else None
    
    return None


def scrape_company_overview_tab(soup: BeautifulSoup) -> Dict:
    """
    Trích xuất thông tin công ty từ tab "Tổng quan công ty" (tab-2)
    Lấy: địa chỉ, quy mô, lĩnh vực, mô tả, website
    """
    info = {
        "company_address": None,
        "company_size": None,
        "company_industry": None,
        "company_description": None,
        "company_website": None,
    }
    
    # ========== Cách 1: Tìm từ các <li> hoặc <div> chứa thông tin chi tiết ==========
    # Địa điểm (Địa chỉ) - Tìm trong nhiều cấu trúc
    # Pattern 1: <div class="content"> với <strong>Địa điểm</strong>
    for container in soup.select("div.content, li, div.box-info .content"):
        strong_el = container.find("strong")
        if strong_el and "Địa điểm" in (text(strong_el) or ""):
            # Clone container để xử lý
            temp_container = container.__copy__()
            # Xóa strong tag
            for strong in temp_container.find_all("strong"):
                strong.decompose()
            # Xóa hr tag
            for hr in temp_container.find_all("hr"):
                hr.decompose()
            # Lấy text còn lại - dùng get_text() trực tiếp để tránh lỗi NoneType
            try:
                address_text = temp_container.get_text(" ", strip=True)
                if address_text:
                    address = re.sub(r'\s+', ' ', address_text).strip()
                    if address and len(address) > 5:
                        info["company_address"] = address
                        break
            except (TypeError, AttributeError):
                pass
    
    # Quy mô công ty (Quy mô)
    for li in soup.select("li"):
        li_text = text(li) or ""
        if "Quy mô công ty" in li_text or "Quy mô" in li_text:
            # Format: "Quy mô công ty: XXX nhân viên" hoặc "Quy mô: XXX"
            parts = li_text.split(":", 1)
            if len(parts) == 2:
                size = parts[1].strip()
                if size:
                    info["company_size"] = size
            break
    
    # Lĩnh vực công ty (Industry) - Extract "Lĩnh vực" field
    for li in soup.select("li"):
        li_text = text(li) or ""
        if "lĩnh vực" in li_text.lower() or "ngành" in li_text.lower():
            # Format: "Lĩnh vực: XXX" hoặc "Ngành: XXX"
            parts = li_text.split(":", 1)
            if len(parts) == 2:
                industry = parts[1].strip()
                if industry and len(industry) > 2:  # Filter out empty/short values
                    info["company_industry"] = industry
            break
    
    # Loại hình hoạt động (Alternative industry field)
    if not info["company_industry"]:
        for li in soup.select("li"):
            li_text = text(li) or ""
            if "loại hình" in li_text.lower():
                parts = li_text.split(":", 1)
                if len(parts) == 2:
                    industry = parts[1].strip()
                    if industry:
                        info["company_industry"] = industry
                break
    
    # ========== Cách 2: Tìm mô tả công ty từ .intro-section-1 ==========
    intro_section = soup.select_one(".intro-section-1 .main-text")
    if intro_section:
        description = text(intro_section)
        if description:
            info["company_description"] = description
    
    # ========== Cách 3: Tìm website từ hàm cải tiến ==========
    if not info["company_website"]:
        info["company_website"] = scrape_company_website_improved(soup)
    
    return info

def scrape_company(session: requests.Session, company_url: Optional[str]) -> Dict:
    if not company_url:
        return {
            "company_name_full": None,
            "company_website": None,
            "company_size": None,
            "company_industry": None,
            "company_address": None,
            "company_description": None,
        }
    soup = get_soup(session, company_url)
    smart_sleep()

    # Tên công ty
    company_name = None
    for css in ["h1", ".company-name h1", "meta[property='og:title']", "title"]:
        el = soup.select_one(css)
        if el:
            company_name = el.get("content") if el.name == "meta" else text(el)
            if company_name:
                break

    website = size = industry = address = description = None
    
    # ========== Cách 1: Tìm từ tab "Tổng quan công ty" (Ưu tiên cao nhất) ==========
    overview_info = scrape_company_overview_tab(soup)
    if overview_info.get("company_address"):
        address = overview_info["company_address"]
    if overview_info.get("company_size"):
        size = overview_info["company_size"]
    if overview_info.get("company_industry"):
        industry = overview_info["company_industry"]
    if overview_info.get("company_description"):
        description = overview_info["company_description"]
    if overview_info.get("company_website"):
        website = overview_info["company_website"]
    
    # Nếu vẫn không có website từ overview_info, dùng hàm cải tiến
    if not website:
        website = scrape_company_website_improved(soup)
    
    # ========== Cách 2: Tìm từ modal maps (.box-info, .box-contact) ==========
    # Phần "Thông tin tuyển dụng" trong modal
    if not address or not size or not industry:
        box_info = soup.select_one(".box-info")
        if box_info:
            # Tìm table trong modal
            table = box_info.select_one("table")
            if table:
                for tr in table.select("tr"):
                    cells = tr.select("td")
                    if len(cells) >= 2:
                        label = (text(cells[0]) or "").lower()
                        value = text(cells[1])
                        if not value:
                            continue
                        if not size and ("quy mô" in label or "size" in label):
                            size = value
                        elif not industry and ("lĩnh vực" in label or "industry" in label or "ngành" in label):
                            industry = value
                        elif not address and ("địa chỉ" in label or "address" in label):
                            address = value
    
    # ========== Cách 3: Tìm từ company profile page ==========
    # Các khối khả dĩ chứa thông tin
    containers = [
        "div.company-profile", "div.company-info", "section#company", "div.company-overview",
        "div#company-info", "div.company-content", "div.company-intro"
    ]
    container = None
    for css in containers:
        c = soup.select_one(css)
        if c:
            container = c
            break
    if container is None:
        container = soup

    # Tìm thông tin chi tiết
    rows = container.select("li, .row, .item, .info-item, .company-info-item, dl, .d-flex")
    for row in rows:
        row_text = text(row) or ""
        label = None
        value = None
        strong = row.find(["strong", "b", "label", "dt", "span"])
        if strong:
            label = text(strong)
            value = row_text
            if label:
                value = re.sub(re.escape(label), "", value, flags=re.I).strip(" :-–—")
        else:
            m = re.match(r"^([^:：]+)[:：]\s*(.+)$", row_text)
            if m:
                label, value = m.group(1).strip(), m.group(2).strip()

        if not label or not value:
            continue

        ln = re.sub(r"\s+", " ", label.lower())
        if not website and ("website" in ln or "trang web" in ln):
            website = value
        elif not size and ("quy mô" in ln or "size" in ln or "nhân sự" in ln):
            size = value
        elif not industry and ("lĩnh vực" in ln or "industry" in ln or "ngành" in ln):
            industry = value
        elif not address and ("địa chỉ" in ln or "address" in ln or "trụ sở" in ln):
            address = value

    # Tìm phần mô tả công ty
    if not description:
        for css in [
            "div.company-description", "#readmore-company", "#company-description",
            "section.company-description", "div.description", "div#readmore-content",
            "div.box-about .content"  # Từ modal maps
        ]:
            el = soup.select_one(css)
            if el and text(el):
                description = text(el)
                break

    return {
        "company_name_full": company_name,
        "company_website": website,
        "company_size": size,
        "company_industry": industry,
        "company_address": address,
        "company_description": description,
    }






# ---------- Pipeline ----------
def crawl_list_url_to_raw_jobs(list_url_page1: str, start_page: int = 1, end_page: int = 1,
                                delay_between_pages=(0.5, 1.0), search_keyword: str = None,
                                max_jobs: int = None) -> List[RawJobData]:
    """
    Pipeline chính: Crawl jobs và trả về danh sách RawJobData objects
    
    Returns:
        List[RawJobData]: Danh sách các job đã được chuẩn hóa theo schema
    """
    if max_jobs is not None and max_jobs <= 0:
        print("[INFO] max_jobs is 0 or negative. Skipping crawl and returning empty list.")
        return []
    raw_jobs: List[RawJobData] = []
    seen_jobs = set()
    s = build_session()

    for page in range(start_page, end_page + 1):
        url = build_paged_url(list_url_page1, page)
        print(f"[INFO] Crawling search page {page}: {url}")
        jobs = parse_search_page(s, url)
        if not jobs:
            print(f"[INFO] Trang {page} không còn job — dừng sớm.")
            break

        for j in jobs:
            if max_jobs and len(raw_jobs) >= max_jobs:
                print(f"[INFO] Reached max limit ({max_jobs} jobs), stopping.")
                break

            job_url = j["job_url"]
            job_id = urlparse(job_url).path
            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)

            # Job detail
            try:
                detail = scrape_job_detail(s, job_url)
            except Exception as e:
                print(f"[WARN] Lỗi job detail {job_url}: {e}")
                detail = {k: None for k in [
                    "detail_title", "detail_salary", "detail_location",
                    "detail_experience", "deadline", "tags", "desc_mota",
                    "desc_yeucau", "desc_quyenloi", "working_addresses",
                    "working_times", "employment_type", "degree",
                    "age_requirement", "company_url_from_job",
                    "company_name_from_job", "company_logo_url",
                    "company_profile_summary", "company_type",
                    "company_industry_from_job", "company_size_from_job",
                    "company_country", "company_working_days",
                    "company_overtime_policy", "company_rating",
                    "company_review_url", "job_detail_html"
                ]}

            company_url = detail.get("company_url_from_job") or j.get("company_url")

            # Company detail
            try:
                comp = scrape_company(s, company_url)
            except Exception as e:
                print(f"[WARN] Lỗi company {company_url}: {e}")
                comp = {k: None for k in [
                    "company_name_full", "company_website", "company_size",
                    "company_industry", "company_address", "company_description"
                ]}

            comp = merge_company_info(comp, {
                "company_name_full": detail.get("company_name_from_job"),
                "company_size": detail.get("company_size_from_job"),
                "company_industry": detail.get("company_industry_from_job") or detail.get("company_type"),
                "company_address": detail.get("company_country"),
                "company_description": detail.get("company_profile_summary"),
            })

            # Convert sang RawJobData
            try:
                raw_job = convert_to_raw_job_data(j, detail, comp)
                raw_job.search_keyword = search_keyword  # Add search keyword
                raw_jobs.append(raw_job)
                print(f"[OK] Scraped: {raw_job.title} - ID: {raw_job.job_source_id}")
            except Exception as e:
                print(f"[ERROR] Không thể convert job {job_url}: {e}")

        smart_sleep(*delay_between_pages)

        if max_jobs and len(raw_jobs) >= max_jobs:
            break

    # Apply central recent-job filter before returning
    try:
        filtered = filter_recent_jobs(raw_jobs)
        return filtered
    except Exception:
        return raw_jobs

def crawl_list_url_to_dataframe(list_url_page1: str, start_page: int = 1, end_page: int = 1,
                                delay_between_pages=(0.5, 1.0)) -> pd.DataFrame:
    """
    Pipeline cũ: Crawl jobs và trả về DataFrame (để backward compatibility)
    Khuyến nghị sử dụng crawl_list_url_to_raw_jobs() để có dữ liệu chuẩn hóa
    """
    rows: List[Dict] = []
    seen_jobs = set()
    s = build_session()

    for page in range(start_page, end_page + 1):
        url = build_paged_url(list_url_page1, page)
        print(f"[INFO] Crawling search page {page}: {url}")
        jobs = parse_search_page(s, url)
        if not jobs:
            print(f"[INFO] Trang {page} không còn job — dừng sớm.")
            break

        for j in jobs:
            job_url = j["job_url"]
            job_id = urlparse(job_url).path
            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)

            # Job detail
            try:
                detail = scrape_job_detail(s, job_url)
            except Exception as e:
                print(f"[WARN] Lỗi job detail {job_url}: {e}")
                detail = {k: None for k in [
                    "detail_title", "detail_salary", "detail_location",
                    "detail_experience", "deadline", "tags", "desc_mota",
                    "desc_yeucau", "desc_quyenloi", "working_addresses",
                    "working_times", "employment_type", "degree",
                    "age_requirement", "company_url_from_job",
                    "company_name_from_job", "company_logo_url",
                    "company_profile_summary", "company_type",
                    "company_industry_from_job", "company_size_from_job",
                    "company_country", "company_working_days",
                    "company_overtime_policy", "company_rating",
                    "company_review_url", "job_detail_html"
                ]}

            company_url = detail.get("company_url_from_job") or j.get("company_url")

            # Company detail
            try:
                comp = scrape_company(s, company_url)
            except Exception as e:
                print(f"[WARN] Lỗi company {company_url}: {e}")
                comp = {k: None for k in [
                    "company_name_full", "company_website", "company_size",
                    "company_industry", "company_address", "company_description"
                ]}

            comp = merge_company_info(comp, {
                "company_name_full": detail.get("company_name_from_job"),
                "company_size": detail.get("company_size_from_job"),
                "company_industry": detail.get("company_industry_from_job") or detail.get("company_type"),
                "company_address": detail.get("company_country"),
                "company_description": detail.get("company_profile_summary"),
            })

            row = {**j, **detail, **comp}
            rows.append(row)

        smart_sleep(*delay_between_pages)

    df = pd.DataFrame(rows)
    cols = [
        "title", "detail_title",
        "job_url",
        "company", "company_name_full",
        "company_url", "company_url_from_job",
        "salary_list", "detail_salary",
        "address_list", "detail_location",
        "exp_list", "detail_experience",
        "deadline", "tags",
        "employment_type", "degree", "age_requirement",
        "working_addresses", "working_times", "job_detail_html",
        "desc_mota", "desc_yeucau", "desc_quyenloi",
        "company_name_from_job", "company_logo_url",
        "company_profile_summary", "company_type",
        "company_industry_from_job", "company_size_from_job",
        "company_country", "company_working_days",
        "company_overtime_policy", "company_rating",
        "company_review_url",
        "company_website", "company_size", "company_industry",
        "company_address", "company_description",
    ]
    cols = [c for c in cols if c in df.columns]
    return df.loc[:, cols] if cols else df

def crawl_many_lists(list_urls: Iterable[str], start_page: int = 1, end_page: int = 1,
                     delay_between_pages=(0.5, 1.0), sleep_between_lists=(0.8, 1.6)) -> pd.DataFrame:
    all_frames: List[pd.DataFrame] = []
    for url in list_urls:
        df_one = crawl_list_url_to_dataframe(url, start_page, end_page, delay_between_pages)
        if not df_one.empty:
            all_frames.append(df_one)
        smart_sleep(*sleep_between_lists)
    if not all_frames:
        return pd.DataFrame()
    df = pd.concat(all_frames, ignore_index=True)
    if "job_url" in df.columns:
        df = df.drop_duplicates(subset=["job_url"])
    return df


if __name__ == "__main__":
    import os
    import json
    
    # ========== TEST SCHEMA: Crawl 5 jobs và export theo RawJobData ==========
    print("[TEST SCHEMA] Testing with RawJobData schema...")
    test_url = "https://careerviet.vn/viec-lam/ai-k-vi.html"
    
    # Crawl 5 jobs với schema chuẩn
    raw_jobs = crawl_list_url_to_raw_jobs(test_url, start_page=1, end_page=1)
    
    if raw_jobs:
        # Export to JSON
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_files_dir = os.path.join(script_dir, "..", "data-files")
        os.makedirs(data_files_dir, exist_ok=True)
        
        # Export raw schema
        schema_json_file = os.path.join(data_files_dir, "test_raw_schema.json")
        raw_jobs_dicts = [job.to_dict() for job in raw_jobs[:5]]  # Giới hạn 5 jobs
        
        with open(schema_json_file, "w", encoding="utf-8") as f:
            json.dump(raw_jobs_dicts, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*80}")
        print(f"[OK] Exported {len(raw_jobs_dicts)} jobs (RawJobData schema) to:")
        print(f"     {schema_json_file}")
        print(f"{'='*80}")
        
        # Show sample
        if raw_jobs_dicts:
            print("\n[SAMPLE] First job with RawJobData schema:")
            first_job = raw_jobs_dicts[0]
            for key, value in first_job.items():
                val_str = str(value)[:80] + ("..." if len(str(value)) > 80 else "")
                print(f"  {key:25} : {val_str}")
    
    print("\n" + "="*80)
    
    # ========== TEST 5 MẪU CÔNG VIỆC (ĐẦY ĐỦ THÔNG TIN - OLD FORMAT) ==========
    print("\n[TEST OLD FORMAT] Testing 5 sample jobs with full info (backward compatibility)...")
    s = build_session()
    
    # Crawl search page
    test_list_url = "https://careerviet.vn/viec-lam/ai-k-vi.html"
    print(f"\n[1] Parsing search page: {test_list_url}")
    jobs = parse_search_page(s, test_list_url)
    
    if not jobs:
        print("[ERROR] No jobs found in search page!")
    else:
        # Lấy 5 jobs đầu tiên
        test_count = min(5, len(jobs))
        print(f"[2] Found {len(jobs)} jobs, testing first {test_count}:")
        
        all_rows = []
        
        for idx, job in enumerate(jobs[:test_count], 1):
            print(f"\n{'='*80}")
            print(f"[Job {idx}/{test_count}] {job['title']}")
            print(f"URL: {job['job_url']}")
            print(f"{'='*80}")
            
            try:
                # Crawl job detail
                print(f"  [3.{idx}] Scraping job detail...")
                detail = scrape_job_detail(s, job['job_url'])
                
                # Crawl company info
                company_url = detail.get("company_url_from_job") or job.get("company_url")
                print(f"  [4.{idx}] Scraping company info...")
                company = scrape_company(s, company_url)
                
                # Merge all info
                full_row = {**job, **detail, **company}
                all_rows.append(full_row)
                
                print(f"  ✓ Job {idx} completed successfully")
                
            except Exception as e:
                print(f"  ✗ Error processing job {idx}: {e}")
                continue
        
        # Export to JSON
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_files_dir = os.path.join(script_dir, "..", "data-files")
        os.makedirs(data_files_dir, exist_ok=True)
        test_json_file = os.path.join(data_files_dir, "test_5_jobs.json")
        
        with open(test_json_file, "w", encoding="utf-8") as f:
            json.dump(all_rows, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*80}")
        print(f"[OK] Exported {len(all_rows)} test jobs to: {test_json_file}")
        print(f"Full path: {os.path.abspath(test_json_file)}")
        print(f"{'='*80}")
        
        # Show summary
        print("\nSummary of extracted fields:")
        if all_rows:
            first_job = all_rows[0]
            print(f"Total fields: {len(first_job)}")
            print("\nSample data from first job:")
            for k, v in list(first_job.items())[:10]:
                val_str = str(v)[:100] + ("..." if len(str(v)) > 100 else "")
                print(f"  {k:30} : {val_str}")
    
    # ========== CRAWL TOÀN BỘ (BỎ COMMENT NẾU SỰ DỤNG) ==========
    """
    parser = argparse.ArgumentParser(description="Crawl CareerViet jobs (giữ nguyên schema như TopCV) và lưu CSV/XLSX.")
    parser.add_argument("--list-urls", "-u", nargs="+", required=False, default=[
        "https://careerviet.vn/viec-lam/ai-k-vi.html",
        "https://careerviet.vn/viec-lam/backend-k-vi.html",
        "https://careerviet.vn/viec-lam/cntt-phan-mem-c1-vi.html",
    ], help="URL danh mục trang 1. VD: -u https://careerviet.vn/viec-lam/ai-k-vi.html")
    parser.add_argument("--start-page", type=int, default=1, help="CareerViet trang tối đa thường là 1")
    parser.add_argument("--end-page", type=int, default=1, help="Nếu >=2 sẽ dùng dạng -trang-{page}-vi.html")
    parser.add_argument("--out-prefix", default="../data-files/careerviet_it_jobs", help="Prefix file đầu ra (không kèm đuôi).")
    args = parser.parse_args()

    print(f"[INFO] Crawling {len(args.list_urls)} danh mục | pages {args.start_page}..{args.end_page}")
    df = crawl_many_lists(args.list_urls, start_page=args.start_page, end_page=args.end_page)

    os.makedirs(os.path.dirname(args.out_prefix), exist_ok=True)
    out_csv = f"{args.out_prefix}_combined.csv"
    out_xlsx = f"{args.out_prefix}_combined.xlsx"
    out_json = f"{args.out_prefix}_combined.json"

    print(df.head())
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    try:
        df.to_excel(out_xlsx, index=False)
    except Exception as e:
        print(f"[WARN] XLSX write failed: {e}")
    print(f"[OK] Saved: {out_csv}")
    """
