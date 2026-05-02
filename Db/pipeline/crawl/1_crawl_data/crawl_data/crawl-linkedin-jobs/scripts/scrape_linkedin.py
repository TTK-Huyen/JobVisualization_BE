import time, re, random, os, argparse, platform, json
from typing import Dict, List, Optional
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
    get_active_cutoff_date,
)
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import requests
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


def parse_linkedin_posted_age_to_hours(value: str) -> Optional[float]:
    """Parse LinkedIn-style relative time strings into hours (float).
    Returns None if cannot parse.
    Examples handled: "just now", "30 minutes ago", "2 hours ago", "1 day ago", "3 weeks ago", "7 months ago".
    """
    if not value:
        return None
    s = value.strip().lower()
    if s in ("just now", "now"):
        return 0.0
    if s == "today":
        return 0.0

    m = re.search(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago", s)
    if not m:
        return None
    try:
        amount = int(m.group(1))
    except Exception:
        return None
    unit = m.group(2)
    if "minute" in unit:
        return amount / 60.0
    if "hour" in unit:
        return float(amount)
    if "day" in unit:
        return float(amount * 24)
    if "week" in unit:
        return float(amount * 24 * 7)
    if "month" in unit:
        return float(amount * 24 * 30)
    if "year" in unit:
        return float(amount * 24 * 365)
    return None


def is_recent_job(posted_text: Optional[str], max_hours: int = 72) -> Optional[bool]:
    """Return True if posted_text indicates a job <= max_hours old.
    Returns None if posted_text cannot be parsed (unknown).
    """
    if not posted_text:
        return None
    hours = parse_linkedin_posted_age_to_hours(posted_text)
    if hours is None:
        return None
    return hours <= float(max_hours)

def build_driver():
    chrome_options = Options()
    # Allow toggling headless mode via env var LINKEDIN_HEADLESS (default true)
    headless_env = os.environ.get("LINKEDIN_HEADLESS", "true").lower()
    if headless_env not in ("false", "0", "no"):
        chrome_options.add_argument("--headless=new")   # chạy ẩn
    else:
        debug_log("Selenium running with visible browser (headless disabled)")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

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

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver


def get_rendered_job_soup(job_id: str, driver):
    if not driver:
        return None

    try:
        # Get optimized sleep delay from environment (default 0.4s - 60% faster than original 1s)
        delay_env = os.environ.get("LINKEDIN_SLEEP_DELAY", "0.4")
        try:
            base_delay = float(delay_env)
        except ValueError:
            base_delay = 0.4
        
        # Add random jitter (0-0.15s) to avoid pattern detection
        delay = base_delay + random.uniform(0, 0.15)
        
        job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        
        # DEBUG: Track navigation time
        nav_start = time.time()
        driver.get(job_url)
        nav_time = time.time() - nav_start
        
        if nav_time > 3:
            debug_log(f"SLOW NAV [{job_id}] took {nav_time:.2f}s", "WARN")
        
        # DEBUG: Track sleep
        time.sleep(delay)
        
        # DEBUG: Get page source
        page_start = time.time()
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_time = time.time() - page_start
        
        if page_time > 1:
            debug_log(f"SLOW PARSE [{job_id}] took {page_time:.2f}s", "WARN")
        
        debug_log(f"[{job_id}] nav={nav_time:.2f}s + sleep={delay:.2f}s + parse={page_time:.2f}s")
        
        return soup
    except Exception as e:
        debug_log(f"ERROR [{job_id}] {str(e)}", "ERROR")
        return None


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


def build_guest_about_company_html(company_url: str):
    company_info = extract_company_detail(company_url) if company_url else {}
    company_name = company_info.get("company_name_full") if company_info else None
    company_website = company_info.get("company_website") if company_info else None
    company_size = company_info.get("company_size") if company_info else None
    company_industry = company_info.get("company_industry") if company_info else None
    company_address = company_info.get("company_address") if company_info else None
    company_description = company_info.get("company_description") if company_info else None

    meta_parts = [part for part in [company_industry, company_size, company_address] if part]
    company_title = company_name or "Company"
    company_link = company_title
    if company_url:
        company_link = f'<a href="{company_url}">{company_title}</a>'

    website_html = ""
    if company_website:
        href = company_website if company_website.startswith("http") else f"https://{company_website}"
        website_html = f'<p class="linkedin-company-website"><a href="{href}">{company_website}</a></p>'

    description_html = ""
    if company_description:
        description_html = f'<p class="linkedin-company-description">{company_description}</p>'

    meta_html = ""
    if meta_parts:
        meta_html = f'<p class="linkedin-company-meta">{" | ".join(meta_parts)}</p>'

    if not any([company_name, company_url, website_html, meta_html, description_html]):
        return ""

    return (
        '<section class="linkedin-about-company">'
        '<h2 class="linkedin-about-company-title">About the company</h2>'
        f'<p class="linkedin-about-company-name">{company_link}</p>'
        f"{meta_html}"
        f"{website_html}"
        f"{description_html}"
        "</section>"
    )

def extract_job_ids(keywords: str, location:str, max_jobs: int = 100) -> List:
    keywords = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20").lower()
    id_list = []
    start = 0
    request_count = 0

    # Lặp đến khi đủ job hoặc API không trả về job mới
    while len(id_list) < max_jobs:
        request_count += 1
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keywords}&location={loc}&start={start}"
        
        # DEBUG: Track request
        req_start = time.time()
        response = requests.get(url)
        req_time = time.time() - req_start
        
        # Check rate limit
        if response.status_code == 429:
            debug_log(f"⚠️  RATE LIMIT (429) on request #{request_count}", "WARN")
            time.sleep(5)  # Wait before retry
            continue
        elif response.status_code != 200:
            debug_log(f"❌ HTTP {response.status_code} on request #{request_count}", "ERROR")
            break
        
        if req_time > 2:
            debug_log(f"SLOW REQUEST #{request_count}: {req_time:.2f}s", "WARN")
        
        if not response.text.strip():
            debug_log("Empty response - no more jobs")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        jobs = soup.find_all("div", {"class": "base-card"})
        if not jobs:
            debug_log("No job cards found in page")
            break

        added_this_page = 0
        for job in jobs:
            job_id = job.get("data-entity-urn")
            if job_id:
                job_id = job_id.split(":")[3]
                if job_id not in id_list:  # Tránh duplicate nếu có
                    id_list.append(job_id)
                    added_this_page += 1
                    if len(id_list) >= max_jobs:
                        break

        debug_log(f"Page {start}: got {added_this_page} jobs, total {len(id_list)}")
        
        if added_this_page == 0:
            debug_log("No new jobs added - stopping")
            break
        start += added_this_page  # Tăng start dựa trên số job mới thêm

    debug_log(f"Total IDs extracted: {len(id_list)} from {request_count} requests")
    return id_list


def extract_cards_from_search(keywords: str, location: str, driver, max_jobs: int = 100, max_scrolls: int = 8) -> List[Dict]:
    """Load LinkedIn search results page and extract visible job cards from DOM.

    Returns list of dicts with: title, company, location, time_posted, job_url, job_id (if found)
    """
    kws = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20")
    search_url = f"https://www.linkedin.com/jobs/search?keywords={kws}&location={loc}"

    # If an hours-based cutoff is requested, attempt to add LinkedIn search filter param `f_TPR`.
    # Map common window sizes to LinkedIn r<seconds> tokens: 24h -> r86400, 72h -> r259200, 7d -> r604800
    hours_old_env = os.environ.get("LINKEDIN_HOURS_OLD")
    try:
        if hours_old_env:
            hours_val = int(hours_old_env)
            if hours_val <= 24:
                secs = 86400
            elif hours_val <= 72:
                secs = 259200
            elif hours_val <= 168:
                secs = 604800
            else:
                secs = None
            if secs:
                # append f_TPR param to encourage LinkedIn to return recent results
                search_url = search_url + f"&f_TPR=r{secs}"
                debug_log(f"Applied LinkedIn search param f_TPR=r{secs} for hours_old={hours_val}")
    except Exception:
        pass

    driver.get(search_url)
    time.sleep(float(os.environ.get("LINKEDIN_SLEEP_DELAY", "0.6")))

    seen_urls = set()
    cards = []
    no_new = 0

    for scroll_idx in range(max_scrolls):
        # Collect potential card elements (multiple selectors for robustness)
        elems = []
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, "li.jobs-search-results__list-item, div.job-card-container, div.base-card")
        except Exception:
            pass

        added = 0
        for el in elems:
            try:
                outer = el.get_attribute('outerHTML') or ''
                soup = BeautifulSoup(outer, 'html.parser')

                # Title
                title = None
                t = soup.select_one('.job-card-list__title, .base-card__title, h3')
                if t:
                    title = t.get_text(strip=True)

                # Company
                company = None
                c = soup.select_one('.job-card-container__company-name, .base-card__subtitle, .job-card-container__company-url')
                if c:
                    company = c.get_text(strip=True)

                # Location
                location_raw = None
                loc_el = soup.select_one('.job-card-container__metadata-item, .base-card__metadata-item, .job-card-list__location')
                if loc_el:
                    location_raw = loc_el.get_text(strip=True)

                # Posted time
                time_posted = None
                time_el = soup.select_one('time, .job-card-container__listed-time, .job-card-list__footer-wrapper')
                if time_el:
                    time_posted = time_el.get_text(strip=True)
                # Fallback: try to find relative time phrases inside the card text (e.g., "7 months ago")
                if not time_posted:
                    try:
                        txt = soup.get_text(" ", strip=True)
                        m = re.search(r"\b(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|today)\b", txt, re.I)
                        if m:
                            time_posted = m.group(1)
                    except Exception:
                        pass

                # Job URL
                job_url = None
                a = soup.find('a', href=True)
                if a:
                    href = a['href']
                    # normalize
                    if href.startswith('/'):
                        job_url = 'https://www.linkedin.com' + href
                    else:
                        job_url = normalize_linkedin_url(href)

                # Try to extract job id from url
                job_id = None
                if job_url:
                    m = re.search(r'/jobs/view/(\d+)', job_url)
                    if m:
                        job_id = m.group(1)

                # Skip duplicates by URL
                key = job_url or (title or '') + '|' + (company or '')
                if key in seen_urls:
                    continue
                seen_urls.add(key)

                cards.append({
                    'title': title,
                    'company': company,
                    'location': location_raw,
                    'time_posted': time_posted,
                    'job_url': job_url,
                    'job_id': job_id,
                })
                added += 1
                if len(cards) >= max_jobs:
                    break
            except Exception:
                continue

        if added == 0:
            no_new += 1
        else:
            no_new = 0

        if len(cards) >= max_jobs or no_new >= 2:
            break

        # Scroll to load more
        try:
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        except Exception:
            pass
        time.sleep(float(os.environ.get('LINKEDIN_SLEEP_DELAY', '0.6')) + random.uniform(0, 0.2))

    debug_log(f"EXTRACTED {len(cards)} cards from search DOM")

    # --- Apply date cutoff and prefer newest first ---
    try:
        # Allow an hours-based cutoff (compatible with jobspy style)
        hours_old_env = os.environ.get("LINKEDIN_HOURS_OLD")
        cutoff_dt = None
        now = datetime.now()
        if hours_old_env:
            try:
                hours = int(hours_old_env)
                cutoff_dt = now - timedelta(hours=hours)
            except Exception:
                cutoff_dt = None

        # If no hours cutoff provided, use active cutoff date from date_filter
        if cutoff_dt is None:
            active_cutoff_date = get_active_cutoff_date()
            if active_cutoff_date:
                # accept jobs posted on or after this date (start of day)
                cutoff_dt = datetime.combine(active_cutoff_date, datetime.min.time())

        # Parse card timestamps to datetimes and filter out older ones
        if cutoff_dt:
            total_cards = len(cards)
            kept = 0
            dropped = 0
            unknown = 0
            filtered = []
            for c in cards:
                tp = c.get("time_posted")
                dt = None
                if tp:
                    dt = parse_relative_time_to_datetime(tp)
                    if dt is None:
                        # fallback: parse into hours then convert
                        hrs = parse_linkedin_posted_age_to_hours(tp)
                        if hrs is not None:
                            dt = now - timedelta(hours=hrs)

                if dt is None:
                    # cannot determine posted time -> keep conservatively
                    unknown += 1
                    c["_parsed_time"] = None
                    filtered.append(c)
                elif dt >= cutoff_dt:
                    kept += 1
                    c["_parsed_time"] = dt
                    filtered.append(c)
                else:
                    dropped += 1

            debug_log(f"Date filter: total={total_cards} kept={kept} dropped={dropped} unknown={unknown}")
            cards = filtered

        # Sort newest first by parsed time when available
        cards.sort(key=lambda x: x.get("_parsed_time") or datetime.min, reverse=True)
    except Exception as e:
        debug_log(f"Date filter/sort failed: {e}", "WARN")

    return cards


def extract_job_detail_from_url(job_url: str, driver) -> Dict:
    """Visit job_url with Selenium and extract basic detail (title, company, desc_html, time_posted)."""
    try:
        job_url = normalize_linkedin_url(job_url)
        driver.get(job_url)
        time.sleep(float(os.environ.get('LINKEDIN_SLEEP_DELAY', '0.4')) + random.uniform(0, 0.15))
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    except Exception as e:
        debug_log(f"Failed to load job_url {job_url}: {e}", 'ERROR')
        return {'job_id': None, 'title': None, 'job_url': job_url, 'company': None, 'desc_html': None, 'time_posted': None}

    # Attempt to parse same fields as extract_job_detail
    title = None
    company = None
    desc_html = None
    time_posted = None
    try:
        te = soup.find('h2', {'class': 'top-card-layout__title'}) or soup.find('h1')
        if te:
            title = te.get_text(strip=True)
    except:
        pass
    try:
        company_tag = soup.find('a', {'class': 'topcard__org-name-link'})
        if company_tag:
            company = company_tag.get_text(strip=True)
    except:
        pass
    try:
        full_detail_block = None
        # look for description blocks
        desc_div = soup.find('div', {'class': 'description__text'})
        if desc_div:
            markup_div = desc_div.find('div', {'class': 'show-more-less-html__markup'}) or desc_div
            desc_html = str(markup_div)
        else:
            # fallback: entire page
            desc_html = str(soup)
    except:
        desc_html = None
    try:
        time_el = soup.find('span', {'class': 'posted-time-ago__text'}) or soup.find('time')
        if time_el:
            time_posted = time_el.get_text(strip=True)
    except:
        pass

    # Fallback: search whole page text for relative time phrases
    if not time_posted:
        try:
            txt = soup.get_text(" ", strip=True)
            m = re.search(r"\b(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|today)\b", txt, re.I)
            if m:
                time_posted = m.group(1)
        except Exception:
            pass

    # attempt to extract job_id from url
    job_id = None
    try:
        m = re.search(r'/jobs/view/(\d+)', job_url)
        if m:
            job_id = m.group(1)
    except:
        pass

    return {
        'job_id': job_id,
        'title': title,
        'job_url': job_url,
        'company': company,
        'desc_html': desc_html,
        'time_posted': time_posted,
    }

def extract_company_detail(company_url: str) -> Dict:
    if not company_url:
        return {}
    
    # Remove locale/language prefix from LinkedIn company URLs (e.g., vi.linkedin.com -> linkedin.com)
    company_url = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", company_url)
    response = requests.get(company_url)
    if response.status_code != 200:
        return {}
    
    soup = BeautifulSoup(response.text, "html.parser")
    company_info = {
        "company_name_full": None,
        "company_website": None,
        "company_size": None,
        "company_industry": None,
        "company_address": None,
        "company_description": None,
    }
    
    # Extract full company name
    try:
        company_info["company_name_full"] = soup.find("h1", {"class": "org-top-card-summary__title"}).text.strip()
    except:
        pass
    
    # Extract definitions from dl
    dl = soup.find("dl", {"class": "org-page-details__definition-list"})
    if dl:
        terms = dl.find_all("dt")
        for dt in terms:
            term = dt.text.strip()
            dd = dt.find_next("dd")
            if dd:
                value = dd.text.strip()
                if "Website" in term:
                    company_info["company_website"] = value
                elif "size" in term.lower():
                    company_info["company_size"] = value
                elif "industry" in term.lower():
                    company_info["company_industry"] = value
                elif "headquarters" in term.lower():
                    company_info["company_address"] = value
    
    # Extract description
    try:
        desc_elem = soup.find("p", {"class": "org-about-us__text"})
        if not desc_elem:
            desc_elem = soup.find("span", {"class": "about-us__description"})
        if desc_elem:
            company_info["company_description"] = desc_elem.text.strip()
    except:
        pass
    
    return company_info

def extract_job_detail(job_id):
    job_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    job_response = requests.get(job_url)
    job_soup = BeautifulSoup(job_response.text, "html.parser")
    
    # Initialize all fields to None or appropriate default
    job_post = {
        "title": None,
        "detail_title": None,
        "job_url": None,
        "company": None,
        "company_name_full": None,
        "company_url": None,
        "company_url_from_job": None,
        "salary_list": None,
        "detail_salary": None,
        "address_list": None,
        "detail_location": None,
        "exp_list": None,
        "detail_experience": None,
        "deadline": None,
        "tags": None,
        "working_addresses": None,
        "working_times": None,
        "desc_mota": None,
        "desc_yeucau": None,
        "desc_quyenloi": None,
        "company_website": None,
        "company_size": None,
        "company_industry": None,
        "company_address": None,
        "company_description": None,
    }
    
    # Job title
    try:
        job_post["title"] = job_soup.find("h2", {"class": "top-card-layout__title"}).text.strip()
        job_post["detail_title"] = job_post["title"]
    except:
        pass
    
    # Job URL
    try:
        link_tag = job_soup.find("a", {"class": "topcard__link"})
        if link_tag:
            # Remove locale/language prefix from LinkedIn URLs (e.g., vi.linkedin.com -> linkedin.com)
            job_post["job_url"] = re.sub(r"https?://[a-z]{2,3}.linkedin.com", "https://www.linkedin.com", link_tag["href"])
        else:
            job_post["job_url"] = f"https://www.linkedin.com/jobs/view/{job_id}"
    except:
        pass
    
    # Company
    try:
        company_tag = job_soup.find("a", {"class": "topcard__org-name-link"})
        if company_tag:
            job_post["company"] = company_tag.text.strip()
            # Remove locale/language prefix from LinkedIn URLs (e.g., sg.linkedin.com -> linkedin.com)
            company_url = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", company_tag["href"])
            job_post["company_url_from_job"] = company_url
            job_post["company_url"] = company_url
    except:
        pass
    
    # Location
    try:
        job_post["detail_location"] = job_soup.find("span", {"class": "topcard__flavor topcard__flavor--bullet"}).text.strip()
        job_post["address_list"] = [addr.strip() for addr in job_post["detail_location"].split(",")] if job_post["detail_location"] else None
    except:
        pass
    
    # Time posted
    try:
        job_post["time_posted"] = job_soup.find("span", {"class": "posted-time-ago__text"}).text.strip()
    except:
        pass
    
    # Extract job criteria (experience, working times, tags)
    try:
        criteria_list = job_soup.find("ul", {"class": "description__job-criteria-list"})
        if criteria_list:
            for item in criteria_list.find_all("li"):
                h3_text = item.find("h3").text.strip()
                span_text = item.find("span").text.strip()
                if "Seniority level" in h3_text:
                    job_post["detail_experience"] = span_text
                    job_post["exp_list"] = [span_text] if span_text else None
                elif "Employment type" in h3_text:
                    job_post["working_times"] = span_text
                elif "Job function" in h3_text:
                    job_post["tags"] = span_text
                elif "Industries" in h3_text:
                    job_post["company_industry"] = span_text  # Temporary, can be overwritten by company detail
    except:
        pass
    
    # Description parsing (capture HTML + structured lists)
    try:
        desc_div = job_soup.find("div", {"class": "description__text"})
        if desc_div:
            markup_div = desc_div.find("div", {"class": "show-more-less-html__markup"}) or desc_div

            # Save full HTML for description
            try:
                job_post["desc_html"] = str(markup_div)
            except Exception:
                job_post["desc_html"] = None

            # collect headers
            headers = list(markup_div.find_all(["strong", "b", "h3"]))

            # also include text nodes that look like headings
            for tag in markup_div.find_all(string=True):
                txt = tag.strip().lower()
                if txt in [
                    "requirements", "responsibilities", "job description",
                    "desired skills and experience", "benefits", "qualification",
                    "qualifications", "skills",
                ]:
                    headers.append(tag)

            for section in headers:
                # header text
                header = section.get_text(strip=True).lower() if hasattr(section, "get_text") else str(section).strip().lower()

                # find nearest following list or paragraph
                text_content = ""
                items_list = []
                next_el = section.find_next() if hasattr(section, "find_next") else None
                if next_el:
                    ul = next_el.find_next("ul")
                    if ul:
                        items_list = [li.get_text(strip=True) for li in ul.find_all("li")]
                        text_content = " - ".join(items_list)
                    else:
                        next_p = next_el.find_next("p")
                        if next_p:
                            text_content = next_p.get_text(strip=True)

                # Description
                if any(key in header for key in ["responsibilities", "job description", "mô tả", "description", "main duties", "nhiệm vụ", "mission"]):
                    job_post["desc_mota"] = text_content or job_post.get("desc_mota")

                # Requirements
                elif any(key in header for key in ["requirement", "yêu cầu", "qualification", "skill", "requirements", "qualifications", "skills"]):
                    job_post["desc_yeucau"] = text_content or job_post.get("desc_yeucau")
                    if items_list:
                        job_post["requirements_items"] = items_list

                # Benefits
                elif any(key in header for key in ["benefit", "quyền lợi", "phúc lợi", "chế độ", "benefits"]):
                    job_post["desc_quyenloi"] = text_content or job_post.get("desc_quyenloi")
                    if items_list:
                        job_post["benefits_items"] = items_list

                # Working time
                elif any(key in header for key in ["working time", "thời gian làm việc", "giờ làm việc"]):
                    job_post["working_times"] = text_content or job_post.get("working_times")

                # Working location
                elif any(key in header for key in ["working location", "địa điểm làm việc", "workplace"]):
                    job_post["working_addresses"] = text_content or job_post.get("working_addresses")

                # Salary
                elif any(key in header for key in ["salary", "lương", "remuneration", "compensation"]):
                    job_post["detail_salary"] = text_content or job_post.get("detail_salary")
                    if text_content:
                        job_post["salary_list"] = text_content.split("-") if "-" in text_content else [text_content]

                # Experience
                elif any(key in header for key in ["experience", "kinh nghiệm", "years of experience"]):
                    job_post["detail_experience"] = text_content or job_post.get("detail_experience")
                    if text_content:
                        job_post["exp_list"] = [text_content]

                # Deadline
                elif any(key in header for key in ["deadline", "hạn nộp", "apply by"]):
                    job_post["deadline"] = text_content or job_post.get("deadline")
    except Exception:
        pass
    
    # Extract company details if company_url available
    if job_post["company_url"]:
        company_info = extract_company_detail(job_post["company_url"])
        job_post.update(company_info)
    
    return job_post

def convert_to_raw_job_data(job_post: Dict) -> RawJobData:
    """Convert LinkedIn job dict to RawJobData schema (minimal - match vietnamworks)"""
    try:
        return RawJobData(
            source_name="linkedin",
            job_url=job_post.get("job_url", ""),
            job_source_id="",
            title=job_post.get("title", ""),
            description_html=job_post.get("desc_html") or job_post.get("desc_mota", ""),
            location_raw=None,
            salary_raw=None,
            employment_type=None,
            experience_raw=None,
            posted_date=None,
            expiry_date=None,
            scraped_at=datetime.now().isoformat(),
            tags=[],
            benefits=[],
            company_name=job_post.get("company", ""),
            company_source_id=None,
            company_website=None,
            company_address=None,
            company_size_raw=None,
            company_industry=None,
            requirements_text=None
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


# Override to keep LinkedIn output aligned with CareerViet/ITViec:
# raw HTML only, do not extract metadata or company detail page fields.
def extract_job_detail(job_id, driver=None):
    rendered_job_soup = get_rendered_job_soup(str(job_id), driver)
    job_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    job_response = requests.get(job_url)
    guest_job_soup = BeautifulSoup(job_response.text, "html.parser")
    job_soup = rendered_job_soup or guest_job_soup

    def clean_detail_block(node):
        clone = BeautifulSoup(str(node), "html.parser")
        for css in [
            "[data-sdui-component='com.linkedin.sdui.generated.jobseeker.dsl.impl.similarJobs']",
            "[componentkey*='SimilarJobs']",
        ]:
            for item in clone.select(css):
                item.decompose()
        return str(clone)

    def find_full_job_detail_block(soup):
        direct_lazy_column = soup.find(
            lambda tag: (
                getattr(tag, "name", None) == "div"
                and tag.get("data-testid") == "lazy-column"
            )
        )
        if direct_lazy_column:
            return direct_lazy_column

        about_job = soup.find(
            lambda tag: (
                getattr(tag, "name", None) == "div"
                and tag.get("data-sdui-component") == "com.linkedin.sdui.generated.jobseeker.dsl.impl.aboutTheJob"
            )
        )
        if not about_job:
            return None

        node = about_job
        while node:
            if getattr(node, "name", None) == "div" and node.get("data-testid") == "lazy-column":
                return node
            node = node.parent if getattr(node, "parent", None) else None
        return None

    title = None
    company_name = None
    company_url = None
    canonical_job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
    desc_html = ""
    time_posted = None

    try:
        title_elem = job_soup.find("h2", {"class": "top-card-layout__title"})
        if title_elem:
            title = title_elem.text.strip()
    except Exception:
        pass

    try:
        link_tag = job_soup.find("a", {"class": "topcard__link"}) or guest_job_soup.find("a", {"class": "topcard__link"})
        if link_tag and link_tag.get("href"):
            canonical_job_url = re.sub(
                r"https?://[a-z]{2,3}\.linkedin\.com",
                "https://www.linkedin.com",
                link_tag["href"],
            )
    except Exception:
        pass

    try:
        company_tag = job_soup.find("a", {"class": "topcard__org-name-link"}) or guest_job_soup.find("a", {"class": "topcard__org-name-link"})
        if company_tag:
            company_name = company_tag.text.strip()
            company_url = company_tag.get("href")
    except Exception:
        pass

    try:
        full_detail_block = find_full_job_detail_block(job_soup)
        if full_detail_block:
            desc_html = clean_detail_block(full_detail_block)
        else:
            desc_div = guest_job_soup.find("div", {"class": "description__text"}) or job_soup.find("div", {"class": "description__text"})
            if desc_div:
                markup_div = desc_div.find("div", {"class": "show-more-less-html__markup"}) or desc_div
                desc_html = (
                    build_guest_header_html(guest_job_soup)
                    + build_guest_about_company_html(company_url)
                    + str(markup_div)
                )
    except Exception:
        pass

    try:
        time_elem = job_soup.find("span", {"class": "posted-time-ago__text"}) or guest_job_soup.find("span", {"class": "posted-time-ago__text"})
        if time_elem:
            time_posted = time_elem.text.strip()
    except Exception:
        pass

    # Fallback: scan the rendered/guest soup text for relative time phrases
    if not time_posted:
        try:
            combined_txt = (str(job_soup.get_text(" ", strip=True)) if job_soup else "") + " " + (str(guest_job_soup.get_text(" ", strip=True)) if guest_job_soup else "")
            m = re.search(r"\b(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|today)\b", combined_txt, re.I)
            if m:
                time_posted = m.group(1)
        except Exception:
            pass

    return {
        "job_id": str(job_id),
        "title": title,
        "job_url": canonical_job_url,
        "company": company_name,
        "desc_html": desc_html,
        "time_posted": time_posted,
    }


def convert_to_raw_job_data(job_post: Dict) -> RawJobData:
    return RawJobData(
        source_name="linkedin",
        job_url=job_post.get("job_url", ""),
        job_source_id=str(job_post.get("job_id", "")),
        title=job_post.get("title", ""),
        description_html=job_post.get("desc_html") or "",
        location_raw=None,
        salary_raw=None,
        employment_type=None,
        experience_raw=None,
        posted_date=None,
        expiry_date=None,
        scraped_at=datetime.now().isoformat(),
        tags=[],
        benefits=[],
        company_name=job_post.get("company"),
        company_source_id=None,
        company_website=None,
        company_address=None,
        company_size_raw=None,
        company_industry=None,
        requirements_text=None,
    )

def scrape_data(keyword: str, location: str, search_keyword: str = None, max_jobs: int = None) -> List[RawJobData]:
    keyword_start = time.time()
    
    debug_log(f"START KEYWORD [{keyword}]")
    print(f"[INFO] Date filter mode: {describe_date_filter()}")
    
    # Get optimization flags from environment
    detail_scrape_str = os.environ.get("LINKEDIN_DETAIL_SCRAPE", "true").lower()
    detail_scrape_enabled = detail_scrape_str in ("true", "1", "yes")
    
    # Use parameter first, then env var, then default to 100
    if max_jobs is None:
        max_jobs_env = os.environ.get("LINKEDIN_MAX_JOBS")
        max_jobs = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else 100
    
    print(f"[INFO] Max jobs to crawl: {max_jobs}")
    print(f"[INFO] Detail scraping: {'ENABLED (full JD, optimized)' if detail_scrape_enabled else 'DISABLED (basic only)'}")
    
    delay_env = os.environ.get("LINKEDIN_SLEEP_DELAY", "0.4")
    print(f"[INFO] Sleep delay: {delay_env}s + jitter (0-0.15s)")
    # Per-job delay between processing detail pages (helps avoid rate limits)
    job_delay = float(os.environ.get("LINKEDIN_JOB_DELAY", "1.0"))
    print(f"[INFO] Per-job delay: {job_delay}s + small jitter")
    
    job_list = []
    driver = None

    # If detail scraping enabled, create driver and prefer DOM-based card extraction
    cards = None
    if detail_scrape_enabled:
        try:
            driver_start = time.time()
            driver = build_driver()
            driver_time = time.time() - driver_start
            debug_log(f"DRIVER READY in {driver_time:.2f}s")

            # Extract visible job cards from search DOM
            cards = extract_cards_from_search(keyword, location, driver, max_jobs=max_jobs)
        except Exception as e:
            debug_log(f"DRIVER ERROR: {str(e)}", "ERROR")
            detail_scrape_enabled = False

    # Fallback: if no cards collected, use guest API ids
    if not cards:
        id_start = time.time()
        id_list = extract_job_ids(keyword, location, max_jobs=max_jobs)
        id_time = time.time() - id_start
        debug_log(f"EXTRACTED {len(id_list)} job IDs in {id_time:.2f}s")

        # Convert id_list to card-like dicts
        cards = []
        for jid in id_list:
            cards.append({'job_id': jid, 'job_url': f"https://www.linkedin.com/jobs/view/{jid}", 'title': None, 'company': None, 'location': None, 'time_posted': None})

    try:
        for i, card in enumerate(cards, 1):
            job_start = time.time()

            # Prefer rendered detail via job_id when available
            job_post = None
            if detail_scrape_enabled and driver:
                if card.get('job_id'):
                    job_post = extract_job_detail(card.get('job_id'), driver=driver)
                elif card.get('job_url'):
                    job_post = extract_job_detail_from_url(card.get('job_url'), driver=driver)
            else:
                # Basic fallback info
                job_post = {
                    'job_id': card.get('job_id') or '',
                    'title': card.get('title') or (card.get('job_url') or '')[:80],
                    'company': card.get('company') or 'LinkedIn',
                    'job_url': card.get('job_url'),
                    'desc_html': None,
                    'time_posted': card.get('time_posted') or 'Recent',
                }

            job_time = time.time() - job_start
            debug_log(f"[{i}/{len(cards)}] Processed card in {job_time:.2f}s")

            # First, allow an hours-based cutoff override via env LINKEDIN_HOURS_OLD
            hours_old_env = os.environ.get("LINKEDIN_HOURS_OLD")
            if hours_old_env and job_post.get('time_posted'):
                try:
                    hours = int(hours_old_env)
                    cutoff_dt = datetime.now() - timedelta(hours=hours)
                    parsed_dt = parse_relative_time_to_datetime(job_post.get('time_posted'))
                    if parsed_dt and parsed_dt < cutoff_dt:
                        print(f"[SKIP] card {i} - older than {hours} hours: {parsed_dt}")
                        time.sleep(job_delay + random.uniform(0, 0.3))
                        continue
                except Exception:
                    pass

            # Fallback to date_filter logic (import/realtime/off)
            posted_date = parse_relative_time_to_date(job_post.get('time_posted'))
            if not is_posted_date_allowed(posted_date):
                print(f"[SKIP] card {i} - posted_date={posted_date}")
                # still delay between jobs when skipping
                time.sleep(job_delay + random.uniform(0, 0.3))
                continue

            raw_job = convert_to_raw_job_data(job_post)
            raw_job.search_keyword = search_keyword or keyword
            job_list.append(raw_job)
            if len(job_list) >= max_jobs:
                break
            # delay between jobs to reduce request rate
            time.sleep(job_delay + random.uniform(0, 0.3))
    finally:
        if driver:
            try:
                driver.quit()
                debug_log('DRIVER CLOSED')
            except Exception:
                pass
    
    keyword_time = time.time() - keyword_start
    debug_log(f"KEYWORD [{keyword}] DONE: {len(job_list)} jobs in {keyword_time:.2f}s total")
    
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
        print(f"✓ Found {len(jobs)} jobs")
        export_to_json(jobs, args.out_prefix)
        print(f"✓ Completed! Output: {args.out_prefix}.json")
