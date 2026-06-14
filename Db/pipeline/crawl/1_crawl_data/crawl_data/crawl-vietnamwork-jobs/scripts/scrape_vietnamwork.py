import time
import re
import random
import sys
import os
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qsl
from datetime import datetime, timezone, timedelta

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import tempfile

# Standard console config for Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from schema import RawJobData
from date_filter import is_posted_date_allowed, parse_iso_date, parse_vietnamworks_date
from central_filters import filter_recent_jobs, filter_existing_jobs_by_url, stats_collector


BASE = "https://www.vietnamworks.com"

def init_selenium_driver():
    """Initialize Selenium WebDriver with Chrome options"""
    chrome_options = ChromeOptions()
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='vnworks_chrome_')}")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# Keep compatibility helper functions
def build_session() -> requests.Session:
    s = requests.Session()
    return s

def text(el) -> Optional[str]:
    if not el:
        return None
    t = el.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", t) if t else None

def smart_sleep(min_s: float = 0.7, max_s: float = 1.5):
    time.sleep(random.uniform(min_s, max_s))

def decode_html_response(response):
    response.encoding = response.apparent_encoding or "utf-8"
    return response

def _extract_first_value(data, keys):
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if value:
                return value
        for value in data.values():
            found = _extract_first_value(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_first_value(item, keys)
            if found:
                return found
    return None

def load_page_with_retry(driver, url: str, wait_seconds: int = 15, retries: int = 2):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            WebDriverWait(driver, wait_seconds).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )
            return
        except WebDriverException as exc:
            last_error = exc
            print(f"[WARN] Page load attempt {attempt}/{retries} failed: {type(exc).__name__}: {exc}")
            if attempt < retries:
                smart_sleep(1.0, 2.0)
    raise last_error

def extract_job_source_id(job_url: str) -> Optional[str]:
    if not job_url:
        return None
    try:
        m = re.search(r"-(\d+)(?:[/?]|$)", job_url)
        if m:
            return m.group(1)
        path = urlparse(job_url).path.strip("/")
        return path.split("/")[-1] if path else job_url
    except Exception:
        return None

def parse_keyword_from_url(url: str) -> str:
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query)).get("q")
    return q if q else "backend"

def build_paginated_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query))
    query["page"] = str(page)
    new_query = "&".join([f"{key}={value}" for key, value in query.items()])
    return parsed._replace(query=new_query).geturl()

def call_vietnamworks_search_api(keyword: str, page: int, hits_per_page: int = 50) -> Dict:
    url = "https://ms.vietnamworks.com/job-search/v1.0/search"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.vietnamworks.com",
        "Referer": "https://www.vietnamworks.com/",
        "X-Source": "Page-Container",
    }
    payload = {
        "userId": 0,
        "query": keyword,
        "filter": [],
        "ranges": [],
        "order": [{"field": "approvedOn", "value": "desc"}],
        "hitsPerPage": hits_per_page,
        "page": page
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    stats_collector.record_http_status("VietnamWorks", r.status_code)
    r.raise_for_status()
    return r.json()

def fetch_and_parse_full_job_details(job_url: str) -> tuple:
    """
    Fetch the job detail page and extract untruncated jobDescription and jobRequirement from Next.js RSC payload.
    """
    import html
    import re
    from bs4 import BeautifulSoup
    import requests
    from datetime import datetime
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    }
    try:
        r = requests.get(job_url, headers=headers, timeout=15)
        decode_html_response(r)
        stats_collector.record_http_status("VietnamWorks", r.status_code)
        if r.status_code != 200:
            print(f"[WARN] Failed to fetch job detail from {job_url}: Status {r.status_code}")
            return None, None, None, None
            
        soup = BeautifulSoup(r.text, 'html.parser')

        posted_date_iso = None
        posted_label = soup.find(lambda tag: getattr(tag, "name", None) == "label" and tag.get_text(" ", strip=True).strip().upper() == "NGÀY ĐĂNG")
        if posted_label:
            posted_block = posted_label.find_parent("div")
            if posted_block:
                posted_text_elem = posted_block.find("p")
                posted_text = posted_text_elem.get_text(" ", strip=True) if posted_text_elem else None
                if posted_text:
                    try:
                        posted_date_iso = datetime.strptime(posted_text, "%d/%m/%Y").date().isoformat()
                    except Exception:
                        posted_date_iso = None

        html_expiry_date = None
        expiry_span = soup.find("span", attrs={"name": "paragraph"}, string=re.compile(r"Hết hạn", re.I))
        if expiry_span:
            expiry_text = expiry_span.get_text(" ", strip=True)
            match = re.search(r"(\d+)", expiry_text)
            if match:
                try:
                    html_expiry_date = (datetime.now() + timedelta(days=int(match.group(1)))).date().isoformat()
                except Exception:
                    html_expiry_date = None
        
        # Concatenate all push strings
        rsc_parts = []
        for script in soup.find_all('script'):
            if script.string and 'self.__next_f.push' in script.string:
                matches = re.findall(r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*"(.*)"\s*\]\s*\)', script.string)
                for m in matches:
                    try:
                        decoded = bytes(m, "utf-8").decode("unicode-escape")
                        rsc_parts.append(decoded)
                    except Exception:
                        rsc_parts.append(m)
                        
        full_rsc_text = "".join(rsc_parts)
        if not full_rsc_text:
                                    return None, None, None, soup
            
        normalized = full_rsc_text.replace('\\"', '"').replace('\\/', '/')
        
        # Regex matching double-quoted string with escapes
        desc_val_match = re.search(r'"jobDescription"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        req_val_match = re.search(r'"jobRequirement"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        approved_on_match = re.search(r'"approvedOn"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        created_on_match = re.search(r'"createdOn"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        th_start_match = re.search(r'"serviceCode"\s*:\s*"TH"[^\{\}]*?"startOn"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        date_posted_match = re.search(r'"datePosted"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        online_on_match = re.search(r'"onlineOn"\s*:\s*"((?:[^"\\]|\\.)*)"', normalized)
        
        raw_date_text = None
        if approved_on_match:
            raw_date_text = approved_on_match.group(1)
        elif created_on_match:
            raw_date_text = created_on_match.group(1)
        elif th_start_match:
            raw_date_text = th_start_match.group(1)
        elif date_posted_match:
            raw_date_text = date_posted_match.group(1)
        elif online_on_match:
            raw_date_text = online_on_match.group(1)
        
        if not desc_val_match or not req_val_match:
            return None, None, raw_date_text, soup
            
        desc_val = desc_val_match.group(1)
        req_val = req_val_match.group(1)
        
        def extract_slot_content(val):
            if val.startswith('$') and len(val) > 1 and val[1:].isalnum():
                slot_id = val[1:]
                pattern = rf'(?:^|[\"\'\s,]){slot_id}:T([0-9a-fA-F]+),'
                matches = list(re.finditer(pattern, full_rsc_text))
                if not matches:
                    pattern = rf'{slot_id}:T([0-9a-fA-F]+),'
                    matches = list(re.finditer(pattern, full_rsc_text))
                if not matches:
                    return None
                match = matches[-1]
                hex_len = match.group(1)
                content_len = int(hex_len, 16)
                start_idx = match.end()
                return full_rsc_text[start_idx:start_idx + content_len]
            else:
                return val
                
        desc_content = extract_slot_content(desc_val)
        req_content = extract_slot_content(req_val)
        
        if desc_content:
            if not desc_val.startswith('$'):
                desc_content = desc_content.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n')
            desc_content = html.unescape(desc_content)
            try:
                desc_content = desc_content.encode('latin1').decode('utf-8', errors='ignore')
            except Exception:
                pass
            
        if req_content:
            if not req_val.startswith('$'):
                req_content = req_content.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n')
            req_content = html.unescape(req_content)
            try:
                req_content = req_content.encode('latin1').decode('utf-8', errors='ignore')
            except Exception:
                pass
            
        return desc_content, req_content, raw_date_text, soup
    except Exception as e:
        print(f"[WARN] Error fetching/parsing job detail from {job_url}: {e}")
        return None, None, None, None

def map_api_job_to_raw_job_data(job: dict, search_keyword: Optional[str] = None) -> RawJobData:
    job_id = str(job.get("jobId", ""))
    job_url = job.get("jobUrl") or f"https://www.vietnamworks.com/{job.get('alias')}-{job_id}-jv"
    title = job.get("jobTitle", "")
    
    # Try fetching full description & requirements from job detail page
    full_desc, full_req, full_posted_text, detail_soup = fetch_and_parse_full_job_details(job_url)
    
    # Use full text if successfully retrieved, otherwise fallback to truncated search API values
    job_desc = full_desc if full_desc else job.get("jobDescription", "")
    job_req = full_req if full_req else job.get("jobRequirement", "")
    payload_posted_date_value = parse_iso_date(full_posted_text)
    api_posted_date_text = _extract_first_value(job, ("onlineOn", "datePosted", "postedDate"))
    api_posted_date_value = parse_iso_date(api_posted_date_text)
    extracted_posted_date = None
    html_expiry_date = None
    if detail_soup:
        import unicodedata

        info_title = detail_soup.find(
            lambda tag: getattr(tag, "name", None) == "h2"
            and tag.get_text(" ", strip=True).strip().lower() == "thông tin việc làm"
        )
        info_root = info_title.find_parent("div") if info_title else detail_soup
        label_node = None
        for node in info_root.find_all("label", attrs={"name": "label"}):
            text_norm = unicodedata.normalize("NFD", node.get_text(" ", strip=True))
            text_norm = "".join(ch for ch in text_norm if unicodedata.category(ch) != "Mn").lower()
            if "ngay dang" in text_norm:
                label_node = node
                break
        if label_node:
            date_block = label_node.find_parent("div")
            p_node = date_block.find("p", attrs={"name": "paragraph"}) if date_block else label_node.find_next("p")
            if p_node:
                raw_html_date = p_node.get_text(strip=True)
                try:
                    extracted_posted_date = datetime.strptime(raw_html_date, "%d/%m/%Y").date().isoformat()
                except Exception:
                    extracted_posted_date = None

        expiry_span = detail_soup.find("span", attrs={"name": "paragraph"}, string=re.compile(r"Hết hạn", re.I))
        if expiry_span:
            expiry_text = expiry_span.get_text(" ", strip=True)
            match = re.search(r"(\d+)", expiry_text)
            if match:
                try:
                    html_expiry_date = (datetime.now() + timedelta(days=int(match.group(1)))).date().isoformat()
                except Exception:
                    html_expiry_date = None

    posted_date = extracted_posted_date or (payload_posted_date_value.isoformat() if payload_posted_date_value else (api_posted_date_value.isoformat() if api_posted_date_value else None))
    
    # Combine description HTML
    desc_parts = []
    if job_desc:
        desc_parts.append(f"<h3>Mô tả công việc</h3>{job_desc}")
    if job_req:
        desc_parts.append(f"<h3>Yêu cầu công việc</h3>{job_req}")
    if job.get("companyProfile"):
        desc_parts.append(f"<h3>Thông tin công ty</h3><p>{job['companyProfile']}</p>")
    description_html = "\n".join(desc_parts)

    # Locations
    locs = job.get("workingLocations", [])
    location_raw = ", ".join([l.get("address") for l in locs if l.get("address")]) if locs else job.get("address")
    
    # Salary
    salary_raw = job.get("prettySalary")
    
    # Experience
    years_exp = job.get("yearsOfExperience")
    experience_raw = f"{years_exp} năm" if years_exp is not None else None
    
    # Dates
    expiry_date = html_expiry_date or job.get("expiredOn")
    
    # Tags / skills
    skills = job.get("skills", [])
    tags = [s.get("skillName") for s in skills if s.get("skillName")]
    
    # Benefits
    benefits_list = job.get("benefits", [])
    benefits = [b.get("benefitValue") for b in benefits_list if b.get("benefitValue")]
    
    # Company Info
    company_name = job.get("companyName")
    company_source_id = str(job.get("companyId")) if job.get("companyId") else None
    company_website = job.get("companyUrl") or None
    company_address = job.get("address")
    company_size = job.get("companySizeVI") or job.get("companySize")
    
    # Industry
    inds = job.get("industriesV3", [])
    company_industry = ", ".join([ind.get("industryV3NameVI") for ind in inds if ind.get("industryV3NameVI")]) if inds else None
    requirements_text = job_req

    vietnam_tz = timezone(timedelta(hours=7))
    scraped_at = datetime.now(vietnam_tz).isoformat()

    return RawJobData(
        source_name="vietnamworks",
        job_url=job_url,
        job_source_id=job_id,
        title=title,
        description_html=description_html,
        location_raw=location_raw,
        salary_raw=salary_raw,
        employment_type="Full-time",
        experience_raw=experience_raw,
        posted_date=posted_date,
        expiry_date=expiry_date,
        scraped_at=scraped_at,
        search_keyword=search_keyword,
        tags=tags,
        benefits=benefits,
        company_name=company_name,
        company_source_id=company_source_id,
        company_website=company_website,
        company_address=company_address,
        company_size_raw=company_size,
        company_industry=company_industry,
        requirements_text=requirements_text,
    )

def crawl_list_url_to_raw_jobs(
    list_url_page1: str,
    start_page: int = 1,
    end_page: int = 1,
    delay_between_pages=(0.6, 1.2),
    prefer_next: bool = True,
    fetch_company: bool = False,
    max_jobs: int = 20,
    search_keyword: str = None,
) -> List[RawJobData]:
    """
    Crawl vietnamworks using Selenium WebDriver
    
    Args:
        list_url_page1: URL of first search page
        start_page: Starting page number
        end_page: Ending page number
        delay_between_pages: Tuple of (min_delay, max_delay) between page loads
        prefer_next: Whether to prefer pagination
        fetch_company: Whether to fetch company details
        max_jobs: Maximum jobs to crawl (default 20 per keyword)
        search_keyword: Search keyword
    
    Returns:
        List of RawJobData objects
    """
    stats_collector.set_active_keyword(search_keyword or parse_keyword_from_url(list_url_page1))
    stats_collector.record_max_jobs("VietnamWorks", max_jobs or 0)
    if max_jobs is not None and max_jobs <= 0:
        print("[INFO] max_jobs is 0 or negative. Skipping crawl and returning empty list.")
        return []
    raw_jobs: List[RawJobData] = []
    seen_jobs = set()
    driver = None
    
    keyword = search_keyword or parse_keyword_from_url(list_url_page1)
    print(f"[INFO] Crawling keyword: '{keyword}' using Selenium")
    print(f"[INFO] Max jobs per keyword: {max_jobs}")
    
    # Respect caller-provided max_jobs; default to a safe value only when omitted.
    if max_jobs is None:
        max_jobs = 20
    
    try:
        driver = init_selenium_driver()
        
        for page in range(start_page, end_page + 1):
            print(f"\n[INFO] Processing page {page} for keyword '{keyword}'...")
            api_page = max(page - 1, 0)
            
            # Build search URL
            if page == 1:
                search_url = list_url_page1
            else:
                search_url = build_paginated_url(list_url_page1, page)
            stats_collector.record_search_list_url("VietnamWorks", search_url)
            print(f"[INFO] Loading: {search_url}")
            
            try:
                load_page_with_retry(driver, search_url, wait_seconds=15, retries=2)
            except TimeoutException:
                print(f"[ERROR] Timeout waiting for job list on page {page}")
                break
            except WebDriverException as exc:
                print(f"[ERROR] Browser session failed on page {page}: {type(exc).__name__}: {exc}")
                break
            
            page_has_fresh_jobs = False
            
            # Build UI dates map
            ui_dates = {}
            try:
                from bs4 import BeautifulSoup
                html = driver.page_source
                list_soup = BeautifulSoup(html, "html.parser")
                job_links = list_soup.find_all("a", href=lambda h: h and "-jv" in h)
                for link in job_links:
                    href = link.get("href", "")
                    m = re.search(r"-(\d+)-jv", href)
                    if not m:
                        m = re.search(r"-(\d+)(?:[/?]|$)", href)
                    if m:
                        jid = m.group(1)
                        parent = link
                        raw_date = None
                        for _ in range(8):
                            if parent is None:
                                break
                            text_nodes = parent.find_all(string=lambda t: t and ("ngày trước" in t.lower() or "hôm nay" in t.lower() or "giờ trước" in t.lower() or "phút trước" in t.lower() or "ngày" in t.lower()))
                            time_texts = []
                            for t in text_nodes:
                                norm = t.strip()
                                if re.search(r"(đăng|cập nhật|hôm nay|trước)", norm, re.I):
                                    time_texts.append(norm)
                            if time_texts:
                                raw_date = time_texts[0]
                                break
                            parent = parent.parent
                        if raw_date:
                            ui_dates[jid] = raw_date
            except Exception as e:
                print(f"[WARN] Failed to extract UI dates: {e}")
            
            try:
                api_res = call_vietnamworks_search_api(keyword, api_page, hits_per_page=50)
                jobs_list = api_res.get("data", [])
                print(f"[INFO] Found {len(jobs_list)} jobs from API for web page {page} (api page {api_page})")

                stats_collector.record_list_count("VietnamWorks", len(jobs_list))

                if not jobs_list:
                    print(f"[INFO] Page {page} has no job data - stopping.")
                    break

                # DB Deduplication: Filter out jobs that already exist in the database
                original_count = len(jobs_list)
                job_url_map = {}
                for job in jobs_list:
                    jid = str(job.get("jobId"))
                    jurl = job.get("jobUrl") or f"https://www.vietnamworks.com/{job.get('alias')}-{jid}-jv"
                    job_url_map[jurl] = job
                
                filtered_urls = set(filter_existing_jobs_by_url(list(job_url_map.keys()), source="VietnamWorks"))
                jobs_list = [job_url_map[u] for u in job_url_map if u in filtered_urls]
                filtered_count = len(jobs_list)
                if original_count != filtered_count:
                    print(f"[DB_FILTER] Bỏ qua {original_count - filtered_count} jobs trên trang {page} đã tồn tại trong database. Còn lại {filtered_count} jobs.")

                for job in jobs_list:
                    try:
                        job_id = str(job.get("jobId"))
                        if job_id in seen_jobs:
                            print(f"[SKIP DUPLICATE] ID={job_id}")
                            continue

                        job_url = job.get("jobUrl") or f"https://www.vietnamworks.com/{job.get('alias')}-{job_id}-jv"

                        # Check raw date text from UI map or fallback
                        raw_date_text = ui_dates.get(job_id)
                        
                        # Date filter logic
                        posted_date = None
                        if raw_date_text:
                            posted_date = parse_vietnamworks_date(raw_date_text)
                        else:
                            online_on = _extract_first_value(job, ("onlineOn", "datePosted", "postedDate"))
                            posted_date = parse_iso_date(online_on)
                            if posted_date:
                                days_ago = (datetime.now().date() - posted_date).days
                                if days_ago == 0:
                                    raw_date_text = "Cập nhật hôm nay"
                                else:
                                    raw_date_text = f"Đăng {days_ago} ngày trước"
                        
                        if posted_date and not is_posted_date_allowed(posted_date):
                            print(f"[FILTER] Dropped VietnamWorks job: ID={job_id} (date: {raw_date_text})")
                            stats_collector.record_date_dropped("VietnamWorks", 1, [job_url])
                            continue

                        seen_jobs.add(job_id)
                        page_has_fresh_jobs = True

                        if os.environ.get("CRAWL_ONLY") == "true":
                            raw_job = RawJobData(
                                source_name="vietnamworks",
                                job_url=job_url,
                                job_source_id=job_id,
                                title=job.get("jobTitle", "Crawl Only Mock"),
                                description_html="Crawl Only Mock",
                                posted_date=posted_date.isoformat() if posted_date else None,
                                scraped_at=datetime.now().isoformat()
                            )
                            raw_job.search_keyword = keyword


                        else:
                            raw_job = map_api_job_to_raw_job_data(job, search_keyword=keyword)

                        raw_jobs.append(raw_job)

                        html_len = len(raw_job.description_html or "")
                        print(f"[{len(raw_jobs)}] OK | ID={raw_job.job_source_id} | {raw_job.title[:60]} | HTML_LEN={html_len}")
                        print(f"     Location: {raw_job.location_raw} | Salary: {raw_job.salary_raw}")

                        if len(raw_jobs) >= max_jobs:
                            print(f"\n[INFO] Reached max_jobs limit of {max_jobs} for keyword '{keyword}'")
                            stats_collector.record_detail_scraped("VietnamWorks", len(raw_jobs), [j.job_url for j in raw_jobs])
                            stats_collector.calculate_missing_fields("VietnamWorks", raw_jobs)
                            return raw_jobs

                    except Exception as e:
                        print(f"[ERROR] Failed to process job: {e}")
                        continue

                    smart_sleep(0.3, 0.6)
                
            except Exception as e:
                print(f"[ERROR] Failed to parse job list on page {page}: {e}")
                break
            
            if not page_has_fresh_jobs:
                print(f"[INFO] Page {page} contains only old jobs - stopping crawl.")
                break
            
            # Delay between pages
            if page < end_page:
                print(f"[INFO] Waiting {delay_between_pages[0]:.1f}-{delay_between_pages[1]:.1f}s before next page...")
                smart_sleep(*delay_between_pages)
        
    finally:
        if driver:
            print(f"[INFO] Closing Selenium driver...")
            driver.quit()
    
    print(f"\n[INFO] Crawl completed. Total jobs collected: {len(raw_jobs)}")
    stats_collector.record_detail_scraped("VietnamWorks", len(raw_jobs), [j.job_url for j in raw_jobs])
    stats_collector.calculate_missing_fields("VietnamWorks", raw_jobs)
    
    # Apply central recent-job filter bypassed per user request (relying on early filter at list crawl phase)
    return raw_jobs


if __name__ == "__main__":
    import argparse
    import json
    from urllib.parse import quote_plus
    from pathlib import Path
    try:
        from dotenv import load_dotenv
        # Tìm thư mục Db và load .env
        p = Path(__file__).resolve()
        for parent in p.parents:
            if parent.name.lower() == "db":
                env_path = parent / ".env"
                if env_path.exists():
                    load_dotenv(env_path)
                    print(f"[INFO] Loaded environment from {env_path}")
                break
    except Exception as e:
        print(f"[WARN] Failed to load .env: {e}")

    parser = argparse.ArgumentParser(description="Crawl VietnamWorks jobs")
    parser.add_argument("--keyword", default=os.getenv("CRAWL_KEYWORD") or os.getenv("KEYWORD") or "software engineer", help="Job keyword to search")
    parser.add_argument("--location", default=os.getenv("CRAWL_LOCATION") or os.getenv("LOCATION") or "Vietnam", help="Location")
    parser.add_argument("--max_jobs", type=int, default=int(os.getenv("JOBS_PER_KEYWORD") or os.getenv("MAX_JOBS") or "20"), help="Max jobs to crawl")
    parser.add_argument("--crawl-only", action="store_true", default=os.getenv("CRAWL_ONLY", "false").lower() in ("true", "1", "yes"), help="Only crawl list cards (mock details)")
    parser.add_argument("--out_prefix", default=None, help="Output prefix path without extension")
    args = parser.parse_args()

    if args.crawl_only:
        os.environ["CRAWL_ONLY"] = "true"

    if not args.out_prefix:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(__file__)
        output_dir = os.path.join(base_dir, "../../output")
        args.out_prefix = os.path.join(output_dir, f"{args.keyword}_{timestamp}")

    # Build search URL
    clean_query = " ".join(args.keyword.replace("/", " ").split())
    list_url = f"https://www.vietnamworks.com/viec-lam?q={quote_plus(clean_query)}&sorting=lasted"

    # 1 page has 50 jobs in VietnamWorks search API
    end_page = max(1, (args.max_jobs + 49) // 50)

    print(f"Scraping '{args.keyword}' on VietnamWorks (max_jobs={args.max_jobs}, pages=1..{end_page}, crawl_only={args.crawl_only})...")
    raw_jobs = crawl_list_url_to_raw_jobs(
        list_url_page1=list_url,
        start_page=1,
        end_page=end_page,
        max_jobs=args.max_jobs,
        search_keyword=args.keyword
    )

    # In báo cáo thống kê crawler & scraper chi tiết
    try:
        from central_filters import stats_collector
        stats_collector.end_time = datetime.now()
        print(stats_collector.get_summary_report())
    except Exception as e:
        print(f"[WARN] Failed to print summary report: {e}")

    if raw_jobs:
        output_file = f"{args.out_prefix}.json"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([job.to_dict() for job in raw_jobs], f, ensure_ascii=False, indent=2)
        print(f"✓ Completed! Output generated at: {os.path.abspath(output_file)}")
    else:
        print("[WARN] No jobs found!")

