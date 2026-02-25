import time, re, random, sys, os
from typing import Dict, List, Optional, Iterable
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, urlencode, parse_qsl

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

import requests
import pandas as pd
import json
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import platform
from datetime import datetime, timezone, timedelta

# Selenium imports for JS rendering
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[WARN] Selenium not available - job descriptions may be incomplete")

# Import RawJobData schema
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from schema import RawJobData

BASE = "https://www.vietnamworks.com"
if platform.system() == "Windows":
    USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/123.0.0.0 Safari/537.36")
else:
    USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/123.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.vietnamworks.com/",
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
    t = el.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", t) if t else None

def smart_sleep(min_s=0.7, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))

def get_rendered_html_selenium(url: str, wait_seconds: int = 5) -> Optional[str]:
    """Get fully rendered HTML using Selenium (for JS-heavy pages)"""
    if not SELENIUM_AVAILABLE:
        return None
    
    driver = None
    try:
        options = ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument(f'user-agent={USER_AGENT}')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": USER_AGENT})
        driver.set_page_load_timeout(30)
        
        driver.get(url)
        
        # Wait for content to load
        try:
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except:
            pass
        
        time.sleep(2)  # Additional wait for dynamic content
        html = driver.page_source
        return html
        
    except Exception as e:
        print(f"[WARN] Selenium failed for {url}: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    for attempt in range(1, 6):
        r = session.get(url, timeout=30)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 5 * attempt
            wait += random.uniform(0.5, 1.5)
            print(f"[WARN] 429 {url} → ngủ {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    r.raise_for_status()
    return BeautifulSoup("", "lxml")

# ---------- Helpers for schema conversion ----------
def extract_job_source_id(job_url: str) -> Optional[str]:
    if not job_url:
        return None
    try:
        # Prefer numeric id at end if present, else last path segment
        m = re.search(r"-(\d+)(?:[/?]|$)", job_url)
        if m:
            return m.group(1)
        path = urlparse(job_url).path.strip("/")
        return path.split("/")[-1] if path else job_url
    except Exception:
        return None

def extract_company_source_id(company_url: Optional[str]) -> Optional[str]:
    if not company_url:
        return None
    try:
        path = urlparse(company_url).path.strip("/")
        seg = path.split("/")[-1]
        return seg
    except Exception:
        return None

# ---------- Paging helpers ----------
def with_page(url: str, page: int) -> str:
    if "{page}" in url:
        return url.format(page=page)
    if page <= 1:
        return url
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["page"] = str(page)
    new_query = urlencode(q, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

# ---------- Search page ----------
def _extract_jobs_from_next_data(soup: BeautifulSoup) -> List[Dict]:
    """
    Đọc JSON Next.js (__NEXT_DATA__) và cố gắng tìm mảng job để lấy đủ kết quả.
    """
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except Exception:
        return []

    def iter_lists(obj):
        if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from iter_lists(v)

    results: List[Dict] = []
    for arr in iter_lists(data):
        keys = set().union(*(set(d.keys()) for d in arr)) if arr else set()
        if not keys:
            continue
        # Heuristic: list có dấu hiệu chứa job
        if not ({"id", "title"} <= keys or {"jobId", "jobTitle"} <= keys or any("job" in k.lower() for k in keys)):
            continue
        for d in arr:
            try:
                # Title
                title = d.get("jobTitle") or d.get("title") or d.get("name")

                # Company (can be str or dict)
                company_name = d.get("companyName") or d.get("employerName")
                comp_field = d.get("company")
                company_href = d.get("companyUrl")
                if isinstance(comp_field, dict):
                    company_name = company_name or comp_field.get("name")
                    company_href = company_href or comp_field.get("url")
                elif isinstance(comp_field, str):
                    company_name = company_name or comp_field

                # Job URL
                job_href = d.get("jobUrl") or d.get("url") or d.get("href") or d.get("seoUrl")
                if not job_href:
                    slug = d.get("slug") or d.get("jobSlug") or ""
                    jid = d.get("id") or d.get("jobId")
                    if slug and jid:
                        job_href = f"/{slug}-{jid}-jv"

                # Salary / Location / Experience
                salary = d.get("salary") or d.get("salaryDisplay") or d.get("salaryStr")
                location = d.get("location") or d.get("workPlace") or d.get("provinceName") or d.get("locations")
                if isinstance(location, list):
                    location = ", ".join([str(x) for x in location if x])
                exp = d.get("yearsOfExperience") or d.get("experience") or d.get("exp")

                if title and job_href:
                    results.append({
                        "title": title,
                        "job_url": urljoin(BASE, str(job_href)),
                        "company": company_name,
                        "company_url": urljoin(BASE, company_href) if company_href else None,
                        "salary_list": salary,
                        "address_list": location,
                        "exp_list": exp,
                    })
            except Exception:
                # Bỏ qua item hỏng để tránh vỡ toàn bộ trang
                continue
        if results:
            break
    return results

def parse_search_page(session: requests.Session, url: str, prefer_next: bool = True) -> List[Dict]:
    soup = get_soup(session, url)
    jobs: List[Dict] = []

    # Ưu tiên lấy từ __NEXT_DATA__ để có đủ job khi trang render bằng JS
    if prefer_next:
        jobs_from_next = _extract_jobs_from_next_data(soup)
        if jobs_from_next:
            return jobs_from_next

    # Thẻ card có thể thay đổi theo A/B test, liệt kê nhiều selector dự phòng
    cards = soup.select(
        "article.job-item, div.job-item, div.job-card, li.job, div.search-job, div.results div.job-item"
    )
    if not cards:
        # Fallback: link đến job detail thường có hậu tố -jv
        cards = [a.parent for a in soup.select("a[href*='-jv']")]

    for card in cards:
        a_title = None
        for css in [
            "a.job-title[href]", "h2 a[href*='-jv']", "h3 a[href*='-jv']",
            "a[href*='-jv']", "a[href*='/viec-lam/']"
        ]:
            a_title = card.select_one(css)
            if a_title:
                break
        if not a_title:
            continue

        title = text(a_title)
        job_url = urljoin(BASE, a_title.get("href"))

        comp_a = None
        for css in ["a[href*='/nha-tuyen-dung/']", "a[href*='/company']", ".company a[href]"]:
            comp_a = card.select_one(css)
            if comp_a:
                break
        company = text(comp_a) or text(card.select_one(".company, .company-name, .job-company"))
        company_url = urljoin(BASE, comp_a.get("href")) if comp_a and comp_a.has_attr("href") else None

        def pick_one(css_list):
            for c in css_list:
                el = card.select_one(c)
                if el and text(el):
                    return text(el)
            return None

        salary = pick_one([".salary", ".job-salary", "li.salary", ".tag-salary"])
        address = pick_one([".location", ".job-location", "li.location", ".address"])
        exp = pick_one([".experience", ".job-exp", "li.experience", "span[title*='Kinh nghiệm']"])

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
    containers = [
        ".job-overview", ".job-summary", ".job-details", "section#job-details",
        ".job-attributes", ".job-info", ".job-meta"
    ]
    for css in containers:
        c = soup.select_one(css)
        if not c:
            continue
        for row in c.select("li, .row, .item, .info-item, .overview-item, .detail-item"):
            row_text = text(row) or ""
            label_el = row.find(["label", "strong", "b", "span"])
            label = (text(label_el) or "").lower()
            value = row_text
            if label_el:
                value = re.sub(re.escape(text(label_el) or ""), "", value, flags=re.I).strip(" :-–—")
            for kw in label_keywords:
                if kw.lower() in label or kw.lower() in row_text.lower():
                    m = re.split(r"[:：]", row_text, maxsplit=1)
                    if len(m) == 2:
                        return m[1].strip()
                    return value
    return None

def extract_deadline(soup: BeautifulSoup) -> Optional[str]:
    cand = soup.find(string=re.compile(r"Hạn nộp|Hết hạn|Deadline", re.I))
    if cand:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", cand)
        if m:
            return m.group(1)
    return pick_info_value(soup, ["Hạn nộp", "Hết hạn", "Deadline"])

def extract_tags(soup: BeautifulSoup):
    tags = []
    for css in [".tags a", ".job-tags a", "ul.tags a", ".skills a", ".tag-list a"]:
        tags.extend([text(a) for a in soup.select(css) if text(a)])
    # meta keywords fallback
    meta_kw = soup.select_one("meta[name='keywords']")
    if meta_kw and meta_kw.get("content"):
        tags.extend([t.strip() for t in meta_kw["content"].split(",") if t.strip()])
    return list(dict.fromkeys(tags))

def extract_detail_from_next_data(soup: BeautifulSoup) -> Dict:
    """Parse __NEXT_DATA__ on job detail page for richer fields."""
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
    except Exception:
        return {}

    def find_job(obj):
        if isinstance(obj, dict):
            if "jobDetail" in obj and isinstance(obj["jobDetail"], dict):
                return obj["jobDetail"]
            if all(k in obj for k in ["title", "jobDescription"]):
                return obj
            for v in obj.values():
                res = find_job(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for v in obj:
                res = find_job(v)
                if res:
                    return res
        return None

    job = find_job(data)
    if not job:
        return {}

    def pick(*keys):
        for k in keys:
            if k in job and job[k]:
                return job[k]
        return None

    title = pick("jobTitle", "title", "name")
    salary = pick("salary", "salaryDisplay", "salaryStr", "jobSalary")
    location = pick("location", "workPlace", "provinceName", "workingLocations")
    if isinstance(location, list):
        location = ", ".join([str(x) for x in location if x])
    experience = pick("experience", "yearsOfExperience", "exp", "experienceLevel")
    posted_date = pick("postedDate", "createdDate", "publishedDate")
    expiry = pick("expiryDate", "deadline")
    employment_type = pick("employmentType", "workingTime", "workType", "jobType")
    desc_html = pick("jobDescription", "descriptionHtml", "description")
    tags = pick("tags", "skills", "keywords")
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[;,]", tags) if t.strip()]
    elif isinstance(tags, list):
        tags = [str(t) for t in tags if t]
    else:
        tags = []
    benefits = pick("benefits")
    if isinstance(benefits, str):
        benefits = [b.strip() for b in re.split(r"[;\n,]", benefits) if b.strip()]
    elif isinstance(benefits, list):
        benefits = [str(b) for b in benefits if b]
    else:
        benefits = []

    return {
        "detail_title": title,
        "detail_salary": salary,
        "detail_location": location,
        "detail_experience": experience,
        "deadline": expiry,
        "tags_list": tags,
        "benefits_list": benefits,
        "employment_type": employment_type,
        "posted_date": posted_date,
        "description_html_raw": desc_html,
    }

def extract_description_html(soup: BeautifulSoup) -> Optional[str]:
    """Best-effort grab of full description HTML from detail page"""
    for css in [
        ".job-description", ".job-content", "section.job-description", "article.job-description",
        "article", "#job-description", "div.description", "div.job-body", "div.job-detail"
    ]:
        el = soup.select_one(css)
        if el and el.decode_contents().strip():
            return el.decode_contents().strip()
    return None

def extract_posted_date(soup: BeautifulSoup) -> Optional[str]:
    cand = soup.find(string=re.compile(r"(đăng|posted|cập nhật)", re.I))
    if cand:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", cand)
        if m:
            return m.group(1)
    # meta datetime
    meta_time = soup.select_one("meta[property='article:published_time']")
    if meta_time and meta_time.get("content"):
        return meta_time["content"]
    return pick_info_value(soup, ["Ngày đăng", "Ngày cập nhật", "Đăng ngày"])

def extract_desc_blocks(soup: BeautifulSoup):
    data = {}
    for h in soup.select("h2, h3"):
        ht = (text(h) or "").lower()
        if any(k in ht for k in ["mô tả công việc", "yêu cầu", "quyền lợi", "phúc lợi", "benefit"]):
            wrap = h.find_parent(class_=re.compile("section|block|desc|description|content")) or h.parent
            content = None
            if wrap:
                for cand in [wrap.select_one(".content, .description, .section-content, div"), h.find_next_sibling()]:
                    if cand and text(cand):
                        content = text(cand)
                        break
            if content:
                if "mô tả" in ht:
                    data["Mô tả công việc"] = content
                elif "yêu cầu" in ht:
                    data["Yêu cầu ứng viên"] = content
                elif "quyền lợi" in ht or "phúc lợi" in ht or "benefit" in ht:
                    data["Quyền lợi"] = content
    return data

def extract_company_link_from_job(soup: BeautifulSoup) -> Optional[str]:
    cand = soup.select_one("a[href*='/nha-tuyen-dung/']") or soup.select_one("a[href*='/company']")
    return urljoin(BASE, cand["href"]) if cand and cand.has_attr("href") else None

def scrape_job_detail(session: requests.Session, job_url: str, use_selenium: bool = True) -> Dict:
    # Try Selenium first for JS-rendered content
    html_text = None
    if use_selenium and SELENIUM_AVAILABLE:
        html_text = get_rendered_html_selenium(job_url)
    
    # Fallback to requests if Selenium unavailable or failed
    if not html_text:
        r = session.get(job_url, timeout=30)
        r.raise_for_status()
        html_text = r.text
    
    soup = BeautifulSoup(html_text, "lxml")
    smart_sleep()

    # Try Next.js data for richer fields first
    next_detail = extract_detail_from_next_data(soup)

    title = next_detail.get("detail_title") or text(soup.select_one("h1, .job-title, .job-detail h1"))
    salary = next_detail.get("detail_salary") or pick_info_value(soup, ["Mức lương", "Lương"])
    location = next_detail.get("detail_location") or pick_info_value(soup, ["Địa điểm", "Nơi làm việc", "Làm việc tại"])
    experience = next_detail.get("detail_experience") or pick_info_value(soup, ["Kinh nghiệm"])
    deadline = next_detail.get("deadline") or extract_deadline(soup)
    tags = next_detail.get("tags_list") or extract_tags(soup)
    desc_blocks = extract_desc_blocks(soup)
    posted_date = next_detail.get("posted_date") or extract_posted_date(soup)
    desc_html = next_detail.get("description_html_raw") or extract_description_html(soup)

    # Fallback: structured data (ld+json)
    if not desc_html or not posted_date:
        for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(s.string or "")
            except Exception:
                continue
            records = data if isinstance(data, list) else [data]
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                if not desc_html and rec.get("description"):
                    desc_html = rec.get("description")
                if not posted_date and rec.get("datePosted"):
                    posted_date = rec.get("datePosted")
            if desc_html and posted_date:
                break

    # Regex fallback on raw HTML for jobDescription / postedDate
    if not desc_html:
        m = re.search(r'"(jobDescription|description)"\s*:\s*"(.*?)"', html_text, re.S)
        if m:
            try:
                desc_html = json.loads(f'"{m.group(2)}"')
            except Exception:
                desc_html = m.group(2)
    if not posted_date:
        m = re.search(r'"(postedDate|createdDate|publishedDate)"\s*:\s*"(.*?)"', html_text)
        if m:
            posted_date = m.group(2)
    company_url_detail = extract_company_link_from_job(soup)

    working_addresses = pick_info_value(soup, ["Địa điểm làm việc", "Nơi làm việc"])
    working_times = next_detail.get("employment_type") or pick_info_value(soup, ["Thời gian làm việc", "Giờ làm việc", "Hình thức", "Loại công việc", "Hình thức làm việc"])

    return {
        "detail_title": title,
        "detail_salary": salary,
        "detail_location": location,
        "detail_experience": experience,
        "deadline": deadline,
        "tags": "; ".join(tags) if tags else None,
        "desc_mota": desc_blocks.get("Mô tả công việc"),
        "desc_yeucau": desc_blocks.get("Yêu cầu ứng viên"),
        "desc_quyenloi": desc_blocks.get("Quyền lợi"),
        "working_addresses": working_addresses,
        "working_times": working_times,
        "company_url_from_job": company_url_detail,
        "posted_date": posted_date,
        "description_html_raw": desc_html,
        "benefits_list": next_detail.get("benefits_list"),
    }

# ---------- Company page ----------
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

    company_name = None
    for css in ["h1", ".company-name h1", "meta[property='og:title']", "title"]:
        el = soup.select_one(css)
        if el:
            company_name = el.get("content") if el.name == "meta" else text(el)
            if company_name:
                break

    website = size = industry = address = None
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
        if "website" in ln or "trang web" in ln:
            website = value
        elif "quy mô" in ln or "size" in ln or "nhân sự" in ln:
            size = value
        elif "lĩnh vực" in ln or "industry" in ln or "ngành" in ln:
            industry = value
        elif "địa chỉ" in ln or "address" in ln or "trụ sở" in ln:
            address = value

    description = None
    for css in [
        "div.company-description", "#readmore-company", "#company-description",
        "section.company-description", "div.description", "div#readmore-content"
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

# ---------- Convert to RawJobData ----------
def convert_to_raw_job_data(job_dict: Dict, detail_dict: Dict, company_dict: Dict) -> RawJobData:
    """Map VietnamWorks scraped dicts to RawJobData schema"""
    # Build description_html from raw html if available, else from blocks
    if detail_dict.get("description_html_raw"):
        description_html = detail_dict["description_html_raw"]
    else:
        desc_parts: List[str] = []
        if detail_dict.get("desc_mota"):
            desc_parts.append(f"<h3>Mô tả công việc</h3><p>{detail_dict['desc_mota']}</p>")
        if detail_dict.get("desc_yeucau"):
            desc_parts.append(f"<h3>Yêu cầu ứng viên</h3><p>{detail_dict['desc_yeucau']}</p>")
        if detail_dict.get("desc_quyenloi"):
            desc_parts.append(f"<h3>Quyền lợi</h3><p>{detail_dict['desc_quyenloi']}</p>")
        description_html = "\n".join([p for p in desc_parts if p])
    
    # Note: VietnamWorks uses client-side rendering (React/Next.js)
    # Description may be empty if JS not executed. Consider using Selenium/Playwright for full content.
    if not description_html:
        description_html = f"<p>[VietnamWorks job - description requires JavaScript rendering]</p><p>Job URL: {job_dict.get('job_url')}</p>"

    # Tags list
    tags_list: List[str] = []
    if detail_dict.get("tags"):
        tags_list = [t.strip() for t in re.split(r"[;,]", detail_dict["tags"]) if t.strip()]

    # Benefits list
    benefits_list: List[str] = []
    if detail_dict.get("benefits_list"):
        benefits_list = detail_dict["benefits_list"]
    elif detail_dict.get("desc_quyenloi"):
        benefits_list = [b.strip() for b in re.split(r"[;\n,]", detail_dict["desc_quyenloi"]) if b.strip()]

    # Determine fields with fallbacks
    location = detail_dict.get("detail_location") or detail_dict.get("working_addresses")
    if not location and job_dict.get("address_list"):
        location = ", ".join(job_dict["address_list"]) if isinstance(job_dict["address_list"], list) else job_dict["address_list"]

    salary = detail_dict.get("detail_salary") or job_dict.get("salary_list")
    experience = detail_dict.get("detail_experience") or job_dict.get("exp_list")
    company_url = detail_dict.get("company_url_from_job") or job_dict.get("company_url")

    # Employment type
    employment_type = detail_dict.get("working_times") or detail_dict.get("employment_type")

    # scraped_at with VN timezone
    vietnam_tz = timezone(timedelta(hours=7))
    scraped_at = datetime.now(vietnam_tz).isoformat()

    return RawJobData(
        source_name="vietnamworks",
        job_url=job_dict.get("job_url"),
        job_source_id=extract_job_source_id(job_dict.get("job_url", "")) or "",
        title=detail_dict.get("detail_title") or job_dict.get("title") or "",
        description_html=description_html or "",
        location_raw=location,
        salary_raw=salary,
        employment_type=employment_type,
        experience_raw=experience,
        posted_date=detail_dict.get("posted_date"),
        expiry_date=detail_dict.get("deadline"),
        scraped_at=scraped_at,
        tags=tags_list,
        benefits=benefits_list,
        company_name=company_dict.get("company_name_full") or job_dict.get("company"),
        company_source_id=extract_company_source_id(company_url),
        company_website=company_dict.get("company_website"),
        company_address=company_dict.get("company_address") or location,
        company_size_raw=company_dict.get("company_size"),
        company_industry=company_dict.get("company_industry"),
        requirements_text=detail_dict.get("desc_yeucau"),
    )

# ---------- Pipeline ----------
def crawl_list_url_to_dataframe(list_url_page1: str, start_page: int = 1, end_page: int = 1,
                                delay_between_pages=(0.6, 1.2),
                                prefer_next: bool = True,
                                fetch_company: bool = True) -> pd.DataFrame:
    rows: List[Dict] = []
    seen_jobs = set()
    s = build_session()

    for page in range(start_page, end_page + 1):
        url = with_page(list_url_page1, page)
        print(f"[INFO] Crawling search page {page}: {url}")
        jobs = parse_search_page(s, url, prefer_next=prefer_next)
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
                    "working_times", "company_url_from_job"
                ]}

            # Company detail (tùy chọn)
            comp = {k: None for k in [
                "company_name_full", "company_website", "company_size",
                "company_industry", "company_address", "company_description"
            ]}
            if fetch_company:
                company_url = detail.get("company_url_from_job") or j.get("company_url")
                try:
                    comp = scrape_company(s, company_url)
                except Exception as e:
                    print(f"[WARN] Lỗi company {company_url}: {e}")

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
        "working_addresses", "working_times",
        "desc_mota", "desc_yeucau", "desc_quyenloi",
        "company_website", "company_size", "company_industry",
        "company_address", "company_description",
    ]
    cols = [c for c in cols if c in df.columns]
    return df.loc[:, cols] if cols else df

def crawl_many_lists(list_urls: Iterable[str], start_page: int = 1, end_page: int = 1,
                     delay_between_pages=(0.6, 1.2), sleep_between_lists=(0.8, 1.6),
                     prefer_next: bool = True, fetch_company: bool = True) -> pd.DataFrame:
    all_frames: List[pd.DataFrame] = []
    for url in list_urls:
        df_one = crawl_list_url_to_dataframe(
            url, start_page, end_page, delay_between_pages,
            prefer_next=prefer_next, fetch_company=fetch_company
        )
        if not df_one.empty:
            all_frames.append(df_one)
        smart_sleep(*sleep_between_lists)
    if not all_frames:
        return pd.DataFrame()
    df = pd.concat(all_frames, ignore_index=True)
    if "job_url" in df.columns:
        df = df.drop_duplicates(subset=["job_url"])
    return df

# ---------- RawJobData pipeline ----------
def crawl_list_url_to_raw_jobs(list_url_page1: str, start_page: int = 1, end_page: int = 1,
                               delay_between_pages=(0.6, 1.2), prefer_next: bool = True,
                               fetch_company: bool = True) -> List[RawJobData]:
    raw_jobs: List[RawJobData] = []
    seen_jobs = set()
    s = build_session()

    for page in range(start_page, end_page + 1):
        url = with_page(list_url_page1, page)
        print(f"[INFO] Crawling search page {page}: {url}")
        jobs = parse_search_page(s, url, prefer_next=prefer_next)
        if not jobs:
            print(f"[INFO] Trang {page} không còn job — dừng sớm.")
            break

        for j in jobs:
            job_url = j["job_url"]
            job_id = urlparse(job_url).path
            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)

            try:
                detail = scrape_job_detail(s, job_url)
            except Exception as e:
                print(f"[WARN] Lỗi job detail {job_url}: {e}")
                detail = {k: None for k in [
                    "detail_title", "detail_salary", "detail_location",
                    "detail_experience", "deadline", "tags", "desc_mota",
                    "desc_yeucau", "desc_quyenloi", "working_addresses",
                    "working_times", "company_url_from_job"
                ]}

            comp = {k: None for k in [
                "company_name_full", "company_website", "company_size",
                "company_industry", "company_address", "company_description"
            ]}
            if fetch_company:
                company_url = detail.get("company_url_from_job") or j.get("company_url")
                try:
                    comp = scrape_company(s, company_url)
                except Exception as e:
                    print(f"[WARN] Lỗi company {company_url}: {e}")

            try:
                raw_job = convert_to_raw_job_data(j, detail, comp)
                raw_jobs.append(raw_job)
                print(f"[OK] Scraped: {raw_job.title} - ID: {raw_job.job_source_id}")
            except Exception as e:
                print(f"[ERROR] Không thể convert job {job_url}: {e}")

        smart_sleep(*delay_between_pages)

    return raw_jobs

if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser(description="Crawl VietnamWorks jobs (schema như TopCV/CareerViet) và lưu CSV/XLSX.")
    parser.add_argument("--list-urls", "-u", nargs="+", required=True,
                        help="URL danh mục trang 1 hoặc template có {page}. VD: https://www.vietnamworks.com/viec-lam?q=backend")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=1)
    parser.add_argument("--out-prefix", default="../data-files/vietnamworks_it_jobs", help="Prefix file đầu ra (không kèm đuôi).")
    parser.add_argument("--no-company", action="store_true", help="Bỏ crawl trang công ty (tránh 404/yêu cầu đăng nhập).")
    parser.add_argument("--no-next", action="store_true", help="Không đọc __NEXT_DATA__, chỉ parse HTML.")
    args = parser.parse_args()

    print(f"[INFO] Crawling {len(args.list_urls)} danh mục | pages {args.start_page}..{args.end_page}")
    df = crawl_many_lists(
        args.list_urls,
        start_page=args.start_page,
        end_page=args.end_page,
        prefer_next=not args.no_next,
        fetch_company=not args.no_company,
    )

    os.makedirs(os.path.dirname(args.out_prefix), exist_ok=True)
    out_csv = f"{args.out_prefix}_combined.csv"
    out_xlsx = f"{args.out_prefix}_combined.xlsx"

    print(df.head())
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    try:
        df.to_excel(out_xlsx, index=False)
    except Exception as e:
        print(f"[WARN] XLSX write failed: {e}")
    print(f"[OK] Saved: {out_csv}")