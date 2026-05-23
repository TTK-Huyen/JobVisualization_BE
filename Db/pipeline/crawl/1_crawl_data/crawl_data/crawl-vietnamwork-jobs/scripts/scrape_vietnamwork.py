import time
import re
import random
import sys
import os
import json
import platform

from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, urlencode, parse_qsl
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[WARN] Selenium not available - raw HTML may be incomplete for JS pages")

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from schema import RawJobData
from date_filter import describe_date_filter, is_posted_date_allowed, parse_iso_date

BASE = "https://www.vietnamworks.com"

if platform.system() == "Windows":
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
else:
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )

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
        total=6,
        connect=3,
        read=3,
        status=6,
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


def smart_sleep(min_s: float = 0.7, max_s: float = 1.5):
    time.sleep(random.uniform(min_s, max_s))


def get_rendered_html_selenium(url: str, wait_seconds: int = 5) -> Optional[str]:
    if not SELENIUM_AVAILABLE:
        return None
    url = url.split("?")[0]  # Strip query parameters for Selenium fallback
    driver = None
    try:
        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={USER_AGENT}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": USER_AGENT})
        driver.set_page_load_timeout(30)
        driver.get(url)

        try:
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception:
            pass

        time.sleep(2)
        return driver.page_source

    except Exception as e:
        print(f"[WARN] Selenium failed for {url}: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    last_response = None

    for attempt in range(1, 6):
        r = session.get(url, timeout=30)
        last_response = r

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 5 * attempt
            wait += random.uniform(0.5, 1.5)
            print(f"[WARN] 429 {url} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue

        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")

    if last_response is not None:
        last_response.raise_for_status()

    return BeautifulSoup("", "lxml")


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


def is_job_fresh(job_dict: Dict) -> bool:
    """Keep only jobs allowed by the active date-filter mode."""
    online_on = job_dict.get("online_on")
    job_date = parse_iso_date(online_on)
    return is_posted_date_allowed(job_date)


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


def _extract_jobs_from_next_data(soup: BeautifulSoup) -> List[Dict]:
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

        if not (
            {"id", "title"} <= keys
            or {"jobId", "jobTitle"} <= keys
            or any("job" in k.lower() for k in keys)
        ):
            continue

        for d in arr:
            try:
                title = d.get("jobTitle") or d.get("title") or d.get("name")

                company_name = d.get("companyName") or d.get("employerName")
                comp_field = d.get("company")
                company_href = d.get("companyUrl")

                if isinstance(comp_field, dict):
                    company_name = company_name or comp_field.get("name")
                    company_href = company_href or comp_field.get("url")
                elif isinstance(comp_field, str):
                    company_name = company_name or comp_field

                job_href = d.get("jobUrl") or d.get("url") or d.get("href") or d.get("seoUrl")
                if not job_href:
                    slug = d.get("slug") or d.get("jobSlug") or ""
                    jid = d.get("id") or d.get("jobId")
                    if slug and jid:
                        job_href = f"/{slug}-{jid}-jv"

                if title and job_href:
                    results.append(
                        {
                            "title": title,
                            "job_url": urljoin(BASE, str(job_href)),
                            "company": company_name,
                            "company_url": urljoin(BASE, company_href) if company_href else None,
                            "online_on": d.get("onlineOn"),  # Include job freshness timestamp
                        }
                    )
            except Exception:
                continue

        if results:
            break

    return results


def parse_search_page(session: requests.Session, url: str, prefer_next: bool = True) -> List[Dict]:
    soup = get_soup(session, url)

    if prefer_next:
        jobs_from_next = _extract_jobs_from_next_data(soup)
        if jobs_from_next:
            return jobs_from_next

    jobs: List[Dict] = []

    cards = soup.select(
        "article.job-item, div.job-item, div.job-card, li.job, div.search-job, div.results div.job-item"
    )
    if not cards:
        cards = [a.parent for a in soup.select("a[href*='-jv']")]

    # If no cards found, try Selenium to render JavaScript and load async jobs
    if not cards:
        print(f"[INFO] No jobs found in static HTML - trying Selenium rendering...")
        html_rendered = get_rendered_html_selenium(url, wait_seconds=5)
        if html_rendered:
            soup = BeautifulSoup(html_rendered, "lxml")
            cards = soup.select(
                "article.job-item, div.job-item, div.job-card, li.job, div.search-job, div.results div.job-item, div.search_list.new-job-card"
            )
            if cards:
                print(f"[INFO] Found {len(cards)} cards from Selenium rendering")
            else:
                cards = [a.parent for a in soup.select("a[href*='-jv']")]
                if cards:
                    print(f"[INFO] Found {len(cards)} cards via -jv fallback from Selenium")

    for card in cards:
        a_title = None
        for css in [
            "a.job-title[href]",
            "h2 a[href*='-jv']",
            "h3 a[href*='-jv']",
            "a[href*='-jv']",
            "a[href*='/viec-lam/']",
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
            "a[href*='/nha-tuyen-dung/']",
            "a[href*='/company']",
            ".company a[href]",
        ]:
            comp_a = card.select_one(css)
            if comp_a:
                break

        company = text(comp_a) or text(card.select_one(".company, .company-name, .job-company"))
        company_url = urljoin(BASE, comp_a.get("href")) if comp_a and comp_a.has_attr("href") else None

        jobs.append(
            {
                "title": title,
                "job_url": job_url,
                "company": company,
                "company_url": company_url,
            }
        )

    return jobs


def scrape_job_detail_raw(session: requests.Session, job_url: str, use_selenium: bool = True) -> Dict:
    html_raw = None

    if use_selenium and SELENIUM_AVAILABLE:
        html_raw = get_rendered_html_selenium(job_url)

    if not html_raw:
        r = session.get(job_url, timeout=30)
        r.raise_for_status()
        html_raw = r.text

    soup = BeautifulSoup(html_raw, "lxml")
    smart_sleep()

    title = None
    page_title = soup.select_one("title")
    if page_title:
        title = text(page_title)

    vietnam_tz = timezone(timedelta(hours=7))

    return {
        "detail_title": title,
        "html_raw": html_raw,
        "scraped_at": datetime.now(vietnam_tz).isoformat(),
    }


def convert_to_raw_job_data(job_dict: Dict, detail_dict: Dict) -> RawJobData:
    return RawJobData(
        source_name="vietnamworks",
        job_url=job_dict.get("job_url"),
        job_source_id=extract_job_source_id(job_dict.get("job_url", "")) or "",
        title=job_dict.get("title") or detail_dict.get("detail_title") or "",
        description_html=detail_dict.get("html_raw") or "",
        location_raw=None,
        salary_raw=None,
        employment_type=None,
        experience_raw=None,
        posted_date=None,
        expiry_date=None,
        scraped_at=detail_dict.get("scraped_at"),
        tags=[],
        benefits=[],
        company_name=job_dict.get("company"),
        company_source_id=None,
        company_website=None,
        company_address=None,
        company_size_raw=None,
        company_industry=None,
        requirements_text=None,
    )


def crawl_list_url_to_raw_jobs(
    list_url_page1: str,
    start_page: int = 1,
    end_page: int = 1,
    delay_between_pages=(0.6, 1.2),
    prefer_next: bool = True,
    fetch_company: bool = False,
    max_jobs: int = 10,
    search_keyword: str = None,
) -> List[RawJobData]:
    raw_jobs: List[RawJobData] = []
    seen_jobs = set()
    s = build_session()
    print(f"[INFO] Date filter mode: {describe_date_filter()}")

    for page in range(start_page, end_page + 1):
        url = with_page(list_url_page1, page)
        print(f"[INFO] Crawling search page {page}: {url}")

        jobs = parse_search_page(s, url, prefer_next=prefer_next)
        if not jobs:
            print(f"[INFO] Trang {page} không còn job - dừng sớm.")
            break

        # Track if this page had any jobs that pass the date threshold
        page_has_fresh_jobs = False

        for j in jobs:
            job_url = j["job_url"]
            job_id = urlparse(job_url).path

            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)

            # Check if this job passes the date threshold
            is_fresh = is_job_fresh(j)
            if is_fresh:
                page_has_fresh_jobs = True
            else:
                print(f"[SKIP OLD JOB] {job_url} | online_on={j.get('online_on')}")
                continue

            try:
                detail = scrape_job_detail_raw(s, job_url)
            except Exception as e:
                print(f"[WARN] Lỗi job detail {job_url}: {e}")
                detail = {
                    "detail_title": None,
                    "html_raw": None,
                    "scraped_at": None,
                }

            try:
                raw_job = convert_to_raw_job_data(j, detail)
                raw_job.search_keyword = search_keyword  # Add search keyword
                raw_jobs.append(raw_job)

                html_len = len(raw_job.description_html or "")
                status = "OK" if html_len > 0 else "EMPTY_HTML"
                freshness = "FRESH" if is_fresh else "OLD"

                print(f"[{len(raw_jobs)}] {status} {freshness} | ID={raw_job.job_source_id} | TITLE={raw_job.title} | HTML_LEN={html_len}")
                print(f"     URL: {raw_job.job_url}")

                if max_jobs and len(raw_jobs) >= max_jobs:
                    return raw_jobs

            except Exception as e:
                print(f"[ERROR] Không thể convert job {job_url}: {e}")

        # Stop if page has no fresh jobs
        if not page_has_fresh_jobs:
            print(f"[INFO] Trang {page} toàn job cũ - dừng crawl")
            break
        else:
            print(f"[INFO] Trang {page} có job mới - tiếp tục crawl")

        smart_sleep(*delay_between_pages)

    return raw_jobs
