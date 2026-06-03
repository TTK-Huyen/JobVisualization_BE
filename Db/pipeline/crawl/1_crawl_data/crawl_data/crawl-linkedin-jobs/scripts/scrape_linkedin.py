import time, re, random, os, argparse, json
from typing import Dict, List
from datetime import datetime, timedelta
import sys
import psutil
from pathlib import Path
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except Exception:
    DOTENV_AVAILABLE = False

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ============================================================================
# DEBUG UTILITIES
# ============================================================================
def get_memory_usage():
    """Get current process memory in MB"""
    try:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024  # MB
    except:
        return 0

def debug_log(msg, level="INFO"):
    """Print debug log with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    mem = get_memory_usage()
    print(f"[{timestamp}] [{level}] [MEM:{mem:.1f}MB] {msg}")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
def _load_db_env():
    try:
        # Walk ancestors to find folder named 'Db' (case-insensitive)
        p = Path(__file__).resolve()
        for parent in p.parents:
            if parent.name.lower() == "db":
                env_path = parent / ".env"
                if env_path.exists():
                    if DOTENV_AVAILABLE:
                        load_dotenv(env_path, override=False)
                        debug_log(f"Loaded environment from {env_path}")
                    else:
                        debug_log(f"python-dotenv not installed; skipping load of {env_path}", "WARN")
                return
    except Exception as e:
        debug_log(f"Failed loading Db/.env: {e}", "WARN")

# Attempt to load Db/.env (do not override terminal env vars)
_load_db_env()
from schema import RawJobData
from date_filter import (
    describe_date_filter,
    is_posted_date_allowed,
    parse_relative_time_to_date,
)
from bs4 import BeautifulSoup
import requests

try:
    import platform
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except Exception:
    SELENIUM_AVAILABLE = False

# ============================================================================
# PROXY UTILITIES & MONKEY-PATCHING
# ============================================================================
from urllib.parse import quote_plus, urlparse

GLOBAL_PROXY_STR = None
LINKEDIN_PROXIES = []
_current_proxy_index = 0

def load_proxies():
    global LINKEDIN_PROXIES
    proxies_env = os.environ.get("LINKEDIN_PROXIES", "")
    if proxies_env:
        LINKEDIN_PROXIES = [p.strip() for p in proxies_env.split(",") if p.strip()]
        debug_log(f"Loaded {len(LINKEDIN_PROXIES)} proxies for rotation.")

load_proxies()

def get_next_proxy():
    global _current_proxy_index, LINKEDIN_PROXIES
    if not LINKEDIN_PROXIES:
        return None
    proxy = LINKEDIN_PROXIES[_current_proxy_index % len(LINKEDIN_PROXIES)]
    _current_proxy_index += 1
    return proxy

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip().rstrip("/")
    if proxy_str.startswith(("http://", "https://")):
        parsed = urlparse(proxy_str)
        if parsed.hostname and parsed.port:
            return {
                "host": parsed.hostname,
                "port": int(parsed.port),
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
    parts = proxy_str.split(":")
    if len(parts) == 4:
        return {
            "host": parts[0],
            "port": int(parts[1]),
            "username": parts[2],
            "password": parts[3]
        }
    elif len(parts) == 2:
        return {
            "host": parts[0],
            "port": int(parts[1]),
            "username": "",
            "password": ""
        }
    return None

def get_requests_proxies(proxy_str):
    proxy = parse_proxy(proxy_str)
    if not proxy:
        return None
    if proxy["username"]:
        url = f"http://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"
    else:
        url = f"http://{proxy['host']}:{proxy['port']}"
    return {
        "http": url,
        "https": url
    }


def get_request_proxy_for_linkedin():
    """Rotate proxy per LinkedIn request, matching the stable behavior from v1."""
    proxy_str = get_next_proxy() if LINKEDIN_PROXIES else GLOBAL_PROXY_STR
    return get_requests_proxies(proxy_str) if proxy_str else None


def get_request_proxy_debug_label(proxies):
    if not proxies:
        return "direct"
    try:
        parsed = urlparse(proxies.get("https") or proxies.get("http") or "")
        if parsed.hostname and parsed.port:
            return f"{parsed.hostname}:{parsed.port}"
    except Exception:
        pass
    return "proxy"


_original_requests_get = requests.get
def _is_linkedin_url(url: str) -> bool:
    try:
        return "linkedin.com" in (url or "").lower()
    except Exception:
        return False

def proxied_requests_get(url, *args, **kwargs):
    global GLOBAL_PROXY_STR
    if _is_linkedin_url(url) and 'proxies' not in kwargs:
        proxies = get_request_proxy_for_linkedin()
        if proxies:
            kwargs['proxies'] = proxies
        debug_log(f"LinkedIn request via {get_request_proxy_debug_label(kwargs.get('proxies'))}")
    if _is_linkedin_url(url):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        )
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        headers.setdefault("Cache-Control", "no-cache")
        headers.setdefault("Pragma", "no-cache")
        kwargs["headers"] = headers
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 15
    return _original_requests_get(url, *args, **kwargs)
requests.get = proxied_requests_get

BASE = "https://www.linkedin.com"


def normalize_linkedin_url(url: str) -> str:
    """Normalize country-specific linkedin domains to the canonical www.linkedin.com."""
    try:
        if not url:
            return url
        return re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", url)
    except Exception:
        return url


def parse_relative_time_to_datetime(value: str):
    """Parse relative time strings like '2 hours ago', '3 days ago' into a datetime (naive, local time).
    Returns None if parsing fails or value is falsy.
    """
    if not value:
        return None
    s = value.strip().lower()
    now = datetime.now()

    # direct shortcuts
    if s in ("just now", "now", "today"):
        return now

    m = re.search(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago", s)
    if not m:
        return None

    try:
        amount = int(m.group(1))
    except Exception:
        return None
    unit = m.group(2)

    if "minute" in unit:
        return now - timedelta(minutes=amount)
    if "hour" in unit:
        return now - timedelta(hours=amount)
    if "day" in unit:
        return now - timedelta(days=amount)
    if "week" in unit:
        return now - timedelta(weeks=amount)
    if "month" in unit:
        return now - timedelta(days=amount * 30)
    if "year" in unit:
        return now - timedelta(days=amount * 365)
    return None


def build_driver(proxy_str=None):
    if not SELENIUM_AVAILABLE:
        debug_log("Selenium not available; using guest API flow.", "WARN")
        return None

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    if proxy_str:
        try:
            parsed = urlparse(proxy_str if proxy_str.startswith(("http://", "https://")) else f"http://{proxy_str}")
            if parsed.hostname and parsed.port:
                chrome_options.add_argument(f"--proxy-server=http://{parsed.hostname}:{parsed.port}")
        except Exception:
            pass

    if platform.system() == "Windows":
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    else:
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        return driver
    except Exception as exc:
        debug_log(f"Failed to initialize Selenium driver: {exc}", "WARN")
        return None


def _should_enable_selenium_fallback() -> bool:
    raw = (os.environ.get("LINKEDIN_SELENIUM_FALLBACK") or "auto").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return os.environ.get("PIPELINE_CRAWL_MODE", "").strip().lower() == "bootstrap"


def _build_linkedin_search_url(keywords: str, location: str, start: int, search_tpr: str) -> str:
    keywords_q = quote_plus(keywords)
    location_q = quote_plus(location.lower())
    params = [
        f"keywords={keywords_q}",
        f"location={location_q}",
        f"start={start}",
    ]
    if search_tpr not in {"", "off", "all", "none"}:
        params.append(f"f_TPR={quote_plus(search_tpr)}")
    return "https://www.linkedin.com/jobs/search/?" + "&".join(params)


def _collect_job_ids_from_soup(soup, id_list: List[str], max_jobs: int) -> int:
    jobs = soup.find_all("div", {"class": "base-card"})
    if not jobs:
        return 0

    added_this_page = 0
    for job in jobs:
        job_id = job.get("data-entity-urn")
        if not job_id:
            continue
        job_id = job_id.split(":")[-1]
        if job_id not in id_list:
            id_list.append(job_id)
            added_this_page += 1
            if len(id_list) >= max_jobs:
                break
    return added_this_page


def extract_job_ids_with_selenium(
    keywords: str,
    location: str,
    max_jobs: int,
    driver=None,
) -> List[str]:
    if not SELENIUM_AVAILABLE:
        return []

    search_tpr = os.environ.get("LINKEDIN_SEARCH_TPR", "r259200").strip().lower()
    max_pages_env = os.environ.get("LINKEDIN_SELENIUM_MAX_PAGES") or os.environ.get("CRAWL_MAX_PAGES") or "5"
    try:
        max_pages = max(1, int(max_pages_env))
    except Exception:
        max_pages = 5

    owns_driver = False
    selenium_driver = driver
    if selenium_driver is None:
        selenium_driver = build_driver(get_next_proxy() if LINKEDIN_PROXIES else GLOBAL_PROXY_STR)
        owns_driver = selenium_driver is not None

    if selenium_driver is None:
        return []

    selenium_ids: List[str] = []
    try:
        for page_index in range(max_pages):
            start = page_index * 25
            url = _build_linkedin_search_url(keywords, location, start, search_tpr)
            try:
                selenium_driver.get(url)
                time.sleep(float(os.environ.get("LINKEDIN_SELENIUM_LOAD_WAIT", "3")))
                for _ in range(2):
                    selenium_driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.0)
            except Exception as exc:
                debug_log(f"Selenium search page load failed at start={start}: {exc}", "WARN")
                break

            soup = BeautifulSoup(selenium_driver.page_source or "", "html.parser")
            added_this_page = _collect_job_ids_from_soup(soup, selenium_ids, max_jobs)
            debug_log(f"Selenium search page {start}: got {added_this_page} new jobs, total {len(selenium_ids)}")

            if len(selenium_ids) >= max_jobs or added_this_page == 0:
                break
    finally:
        if owns_driver:
            try:
                selenium_driver.quit()
            except Exception:
                pass

    return selenium_ids


def build_guest_header_html(soup):
    def text_or_none(node):
        return node.get_text(" ", strip=True) if node else None

    title = text_or_none(soup.find("h2", {"class": "top-card-layout__title"}))
    company_node = soup.find("a", {"class": "topcard__org-name-link"})
    company = text_or_none(company_node)
    company_href = company_node.get("href") if company_node else None
    location = text_or_none(soup.find("span", {"class": "topcard__flavor topcard__flavor--bullet"}))
    posted = text_or_none(soup.find("span", {"class": "posted-time-ago__text"}))
    applicants = text_or_none(
        soup.find(
            lambda tag: getattr(tag, "name", None) == "figcaption"
            and "applicant" in tag.get_text(" ", strip=True).lower()
        )
    )

    criteria_html = ""
    criteria_section = soup.find("ul", {"class": "description__job-criteria-list"})
    if criteria_section:
        criteria_html = str(criteria_section)
    else:
        chips = []
        for span in soup.find_all("span"):
            text = span.get_text(" ", strip=True)
            if text and text in {"Hybrid", "On-site", "Remote", "Full-time", "Part-time", "Contract", "Internship", "Temporary"}:
                chips.append(text)
        if chips:
            chips_html = "".join(f"<li>{chip}</li>" for chip in dict.fromkeys(chips))
            criteria_html = f'<ul class="linkedin-top-chips">{chips_html}</ul>'

    meta_parts = [part for part in [location, posted, applicants] if part]
    company_html = company
    if company and company_href:
        company_html = f'<a href="{company_href}">{company}</a>'

    if not any([title, company, meta_parts, criteria_html]):
        return ""

    company_section = f'<p class="linkedin-company">{company_html}</p>' if company_html else ""
    title_section = f'<h2 class="linkedin-title">{title}</h2>' if title else ""
    meta_section = f'<p class="linkedin-meta">{" | ".join(meta_parts)}</p>' if meta_parts else ""

    return (
        '<section class="linkedin-job-header">'
        f"{company_section}"
        f"{title_section}"
        f"{meta_section}"
        f"{criteria_html}"
        "</section>"
    )


def convert_to_raw_job_data(job_post: Dict) -> RawJobData:
    """Convert LinkedIn job dict to RawJobData schema"""
    try:
        description_html = job_post.get("desc_html") or job_post.get("desc_mota", "")
        requirements_text = job_post.get("requirements_text") or job_post.get("desc_yeucau")
        if not requirements_text:
            requirements_items = job_post.get("requirements_items")
            if isinstance(requirements_items, (list, tuple, set)):
                requirements_text = "\n".join(
                    str(item).strip() for item in requirements_items if str(item).strip()
                ) or None
            else:
                requirements_text = requirements_items
        if not requirements_text:
            requirements_text = description_html

        return RawJobData(
            source_name="linkedin",
            job_url=job_post.get("job_url", ""),
            job_source_id=str(job_post.get("job_id") or ""),
            title=job_post.get("title", ""),
            description_html=description_html,
            location_raw=job_post.get("location_raw"),
            salary_raw=job_post.get("salary_raw"),
            employment_type="Full-time",
            experience_raw=job_post.get("experience_raw"),
            posted_date=job_post.get("posted_date"),
            expiry_date=None,
            scraped_at=datetime.now().isoformat(),
            tags=[],
            benefits=[],
            company_name=job_post.get("company", ""),
            company_source_id=None,
            company_website=None,
            company_address=job_post.get("location_raw"),
            company_size_raw=None,
            company_industry=None,
            requirements_text=requirements_text
        )
    except Exception as e:
        print(f"[ERROR] convert_to_raw_job_data: {e}")
        raise

def export_to_json(jobs_data: List[RawJobData], out_prefix: str):
    """Export RawJobData list to JSON"""
    output_file = f"{out_prefix}.json"
    out_dir = os.path.dirname(output_file) or "."
    os.makedirs(out_dir, exist_ok=True)
    print(f"[BEFORE SAVE] out_prefix: {out_prefix}")
    print(f"[BEFORE SAVE] output_file: {output_file}")
    print(f"[BEFORE SAVE] out_dir: {out_dir}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump([job.to_dict() for job in jobs_data], f, ensure_ascii=False, indent=2)
    
    # Print after save
    actual_path = os.path.abspath(output_file)
    print(f"[AFTER SAVE] File saved at: {actual_path}")
    print(f"[AFTER SAVE] File exists: {os.path.exists(actual_path)}")


# Clean production path:
# - keep the public scraper signature/output unchanged for the pipeline
# - use the guest API flow from the source scraper
# - avoid Selenium job pages and company pages because they multiply requests and trigger rate limits
def linkedin_request_get(url: str, label: str, retries: int = 3):
    response = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url)
        except Exception as e:
            debug_log(f"{label} request failed on attempt {attempt}/{retries}: {e}", "WARN")
            time.sleep(2 + random.uniform(0, 1.5))
            continue

        if response.status_code == 429:
            wait_seconds = 2 + attempt * 2 + random.uniform(0, 2)
            debug_log(f"RATE LIMIT (429) on {label}, attempt {attempt}/{retries}. Rotate proxy and sleep {wait_seconds:.1f}s", "WARN")
            time.sleep(wait_seconds)
            continue

        return response
    return response


def extract_job_ids(keywords: str, location: str, max_jobs: int = 100) -> List:
    search_tpr = os.environ.get("LINKEDIN_SEARCH_TPR", "r259200").strip().lower()
    id_list = []
    start = 0
    request_count = 0

    configured_max_pages = int(os.getenv("CRAWL_MAX_PAGES", "3"))
    estimated_pages_needed = max(3, ((max_jobs + 7) // 8) + 2)
    max_pages = max(configured_max_pages, estimated_pages_needed)

    while len(id_list) < max_jobs and request_count < max_pages:
        request_count += 1
        url = _build_linkedin_search_url(keywords, location, start, search_tpr).replace("/jobs/search/", "/jobs-guest/jobs/api/seeMoreJobPostings/search")
        response = linkedin_request_get(url, f"search page start={start}")

        if response is None:
            debug_log("No response while extracting job IDs", "ERROR")
            break
        if response.status_code != 200:
            debug_log(f"HTTP {response.status_code} while extracting job IDs; stop with collected IDs", "WARN")
            break
        if not response.text.strip():
            debug_log("Empty search response - no more jobs")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        added_this_page = _collect_job_ids_from_soup(soup, id_list, max_jobs)
        if added_this_page == 0:
            debug_log("No job cards found in search response")
            break

        debug_log(f"Search page {start}: got {added_this_page} new jobs, total {len(id_list)}")
        start += added_this_page
        time.sleep(random.uniform(1.0, 3.0))

    debug_log(f"Total IDs extracted: {len(id_list)} from {request_count} search requests")
    return id_list


def extract_job_detail(job_id, driver=None):
    job_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    response = linkedin_request_get(job_url, f"job detail {job_id}")
    if response is None or response.status_code != 200 or not response.text.strip():
        status = response.status_code if response is not None else "no response"
        debug_log(f"Cannot fetch job detail {job_id}: {status}", "WARN")
        return {}

    job_soup = BeautifulSoup(response.text, "html.parser")
    canonical_job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
    title = None
    company_name = None
    desc_html = ""
    time_posted = None
    location_raw = None

    try:
        title_elem = job_soup.find("h2", {"class": "top-card-layout__title"})
        if title_elem:
            title = title_elem.get_text(" ", strip=True)
    except Exception:
        pass

    try:
        link_tag = job_soup.find("a", {"class": "topcard__link"})
        if link_tag and link_tag.get("href"):
            canonical_job_url = normalize_linkedin_url(link_tag["href"])
    except Exception:
        pass

    try:
        company_tag = job_soup.find("a", {"class": "topcard__org-name-link"})
        if company_tag:
            company_name = company_tag.get_text(" ", strip=True)
    except Exception:
        pass

    try:
        desc_div = job_soup.find("div", {"class": "description__text"})
        if desc_div:
            markup_div = desc_div.find("div", {"class": "show-more-less-html__markup"}) or desc_div
            desc_html = build_guest_header_html(job_soup) + str(markup_div)
    except Exception:
        pass

    try:
        time_elem = job_soup.find("span", {"class": "posted-time-ago__text"})
        if time_elem:
            time_posted = time_elem.get_text(" ", strip=True)
    except Exception:
        pass

    try:
        loc_tag = job_soup.find("span", class_="topcard__flavor--bullet") or job_soup.find("span", class_="topcard__flavor")
        if loc_tag:
            location_raw = loc_tag.get_text(" ", strip=True)
    except Exception:
        pass

    posted_date_str = None
    if time_posted:
        try:
            parsed_dt = parse_relative_time_to_date(time_posted)
            if parsed_dt:
                posted_date_str = parsed_dt.isoformat()
        except Exception:
            pass

    return {
        "job_id": str(job_id),
        "title": title,
        "job_url": canonical_job_url,
        "company": company_name,
        "desc_html": desc_html,
        "time_posted": time_posted,
        "location_raw": location_raw,
        "posted_date": posted_date_str,
    }


def scrape_data(
    keyword: str,
    location: str,
    search_keyword: str = None,
    max_jobs: int = None,
    driver=None,
    close_driver: bool = True,
) -> List[RawJobData]:
    if max_jobs is not None and max_jobs <= 0:
        print("[INFO] max_jobs is 0 or negative. Skipping crawl and returning empty list.")
        return []
    keyword_start = time.time()

    if max_jobs is None:
        max_jobs_env = os.environ.get("LINKEDIN_MAX_JOBS")
        max_jobs = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else 999999

    debug_log(f"START KEYWORD [{keyword}]")
    print(f"[INFO] Date filter mode: {describe_date_filter()}")
    print(f"[INFO] Max jobs to crawl: {'unlimited' if max_jobs == 999999 else max_jobs}")
    print("[INFO] Detail scraping: guest API first, Selenium fallback optional")

    job_delay = float(os.environ.get("LINKEDIN_JOB_DELAY", "1.5"))
    print(f"[INFO] Per-job delay: {job_delay}s + jitter")

    id_list = extract_job_ids(keyword, location, max_jobs=max_jobs)

    selenium_fallback_enabled = _should_enable_selenium_fallback()
    selenium_fallback_min_ids = int(os.environ.get("LINKEDIN_SELENIUM_FALLBACK_MIN_IDS", "150"))
    selenium_fallback_max_jobs_env = os.environ.get("LINKEDIN_SELENIUM_MAX_JOBS")
    selenium_fallback_max_jobs = max_jobs
    if selenium_fallback_max_jobs_env and selenium_fallback_max_jobs_env.isdigit():
        selenium_fallback_max_jobs = min(max_jobs, int(selenium_fallback_max_jobs_env))

    if selenium_fallback_enabled and len(id_list) < selenium_fallback_min_ids:
        print(
            f"[INFO] Guest API returned {len(id_list)} job IDs, below fallback threshold "
            f"{selenium_fallback_min_ids}. Trying Selenium fallback..."
        )
        try:
            selenium_ids = extract_job_ids_with_selenium(keyword, location, selenium_fallback_max_jobs, driver=driver)
            if selenium_ids:
                merged_ids = []
                seen_ids = set()
                for job_id in id_list + selenium_ids:
                    if job_id not in seen_ids:
                        seen_ids.add(job_id)
                        merged_ids.append(job_id)
                id_list = merged_ids[:max_jobs]
                print(f"[INFO] Selenium fallback added {len(id_list)} total job IDs after merge")
            else:
                print("[WARN] Selenium fallback did not add any job IDs")
        except Exception as exc:
            debug_log(f"Selenium fallback failed; continue with guest API results only: {exc}", "WARN")

    job_list = []

    # Emergency breaker to avoid excessive requests/processing
    try:
        MAX_JOBS_LIMIT = int(os.environ.get("LINKEDIN_MAX_JOBS_LIMIT", "500"))
    except Exception:
        MAX_JOBS_LIMIT = 500

    for i, job_id in enumerate(id_list, 1):
        job_start = time.time()
        job_post = extract_job_detail(job_id)
        debug_log(f"[{i}/{len(id_list)}] Processed job_id={job_id} in {time.time() - job_start:.2f}s")

        if not job_post:
            time.sleep(job_delay + random.uniform(0, 0.8))
            continue

        hours_old_env = os.environ.get("LINKEDIN_HOURS_OLD")
        if hours_old_env and job_post.get("time_posted"):
            try:
                hours = int(hours_old_env)
                cutoff_dt = datetime.now() - timedelta(hours=hours)
                parsed_dt = parse_relative_time_to_datetime(job_post.get("time_posted"))
                if parsed_dt and parsed_dt < cutoff_dt:
                    print(f"[SKIP] job_id={job_id} - older than {hours} hours: {parsed_dt}")
                    time.sleep(job_delay + random.uniform(0, 0.8))
                    continue
            except Exception:
                pass

        posted_date = parse_relative_time_to_date(job_post.get("time_posted"))
        if not is_posted_date_allowed(posted_date):
            print(f"[SKIP] job_id={job_id} - posted_date={posted_date}")
            time.sleep(job_delay + random.uniform(0, 0.8))
            continue

        raw_job = convert_to_raw_job_data(job_post)
        raw_job.search_keyword = search_keyword or keyword
        job_list.append(raw_job)
        debug_log(f"[OK] [{len(job_list)}/{max_jobs if max_jobs != 999999 else len(id_list)}] job_id={raw_job.job_source_id} title='{(raw_job.title or '')[:80]}'")

        if len(job_list) >= max_jobs:
            break
        # emergency breaker
        if len(job_list) >= MAX_JOBS_LIMIT:
            print(f"[BREAK] Reached emergency MAX_JOBS_LIMIT={MAX_JOBS_LIMIT}; stopping LinkedIn crawl for this keyword.")
            break
        time.sleep(job_delay + random.uniform(0, 0.8))

    if driver and close_driver:
        try:
            driver.quit()
        except Exception:
            pass

    debug_log(f"KEYWORD [{keyword}] DONE: {len(job_list)} jobs in {time.time() - keyword_start:.2f}s total")
    return job_list
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper (Selenium)")
    parser.add_argument("--keyword", default="software engineer", help="Job keyword to search")
    parser.add_argument("--location", default="Vietnam", help="Location")
    parser.add_argument("--out_prefix", default=None, help="Output prefix path without extension")

    args = parser.parse_args()

    # Auto-generate output prefix with timestamp if not provided
    if not args.out_prefix:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(os.path.dirname(__file__), "../../output")
        args.out_prefix = os.path.join(output_dir, f"{args.keyword}_{args.location.lower().replace(' ', '_')}_{timestamp}")

    print(f"[INFO] Scraping: {args.keyword} in {args.location} ...")
    jobs = scrape_data(args.keyword, args.location)

    if not jobs:
        print("[WARN] No jobs found.")
    else:
        print(f"[OK] Found {len(jobs)} jobs")
        export_to_json(jobs, args.out_prefix)
        print(f"[OK] Completed! Output: {args.out_prefix}.json")

