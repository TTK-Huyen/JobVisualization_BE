import requests
from bs4 import BeautifulSoup
import time
import random
import urllib.parse
import json
import pandas as pd
import csv
import argparse
import os
import sys
import math
from datetime import datetime, timedelta
import unicodedata
import re

# Import schema
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from schema import RawJobData
from date_filter import describe_date_filter, is_posted_date_allowed, parse_iso_date, parse_relative_time_to_date
from central_filters import filter_recent_jobs

# Sử dụng User-Agent macOS sạch, có tỉ lệ vượt Cloudflare cao
_ITVIEC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Headers giả lập browser tối giản
def get_headers():
    return {
        "User-Agent": _ITVIEC_UA
    }

def decode_html_response(response):
    response.encoding = response.apparent_encoding or "utf-8"
    return response

def parse_itviec_relative_time_to_date(value: str):
    if not value:
        return None
    normalized = value.strip().lower()
    match = re.search(r"(?:posted\s+)?(?P<days>\d{1,2})\s+days?\s+ago\b", normalized)
    if not match:
        return None
    days = int(match.group("days"))
    return (datetime.now() - timedelta(days=days)).date()

def extract_itviec_posted_date(job_soup: BeautifulSoup):
    for script in job_soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, list):
            items = data
        else:
            items = [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting" and item.get("datePosted"):
                parsed = parse_iso_date(item.get("datePosted"))
                if parsed:
                    return parsed, item.get("datePosted")

    posted_elem = job_soup.find("span", string=re.compile(r"Posted\s+\d+\s+\w+\s+ago", re.I))
    if posted_elem:
        raw_date_text = posted_elem.get_text(" ", strip=True)
        parsed = parse_itviec_relative_time_to_date(raw_date_text)
        if parsed:
            return parsed, raw_date_text
    return None, None

# Tách biệt URL Toàn quốc (Vietnam) để tránh lỗi định tuyến đường dẫn của ITViec
def get_max_page(keyword, location):
    q = urllib.parse.quote(keyword)
    
    if not location or location.lower().strip() in ["vietnam", "viet-nam", "all", "nationwide"]:
        url = f"https://itviec.com/it-jobs/{q}"
    else:
        loc = urllib.parse.quote(location)
        url = f"https://itviec.com/it-jobs/{q}/{loc}"
        
    try:
        resp = requests.get(url, headers=get_headers(), timeout=15)
        decode_html_response(resp)
        print(f"[DEBUG] get_max_page - Status: {resp.status_code}, Url: {url}")
        if resp.status_code != 200:
            return 1
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        total_jobs_elem = soup.select_one("h1.search-page-title, h1")
        if total_jobs_elem:
            text = total_jobs_elem.get_text()
            match = re.search(r'\d+', text)
            if match:
                total_jobs = int(match.group())
                calculated_pages = (total_jobs + 19) // 20
                print(f"[DEBUG] Trích xuất thành công: {total_jobs} jobs -> Tính toán max_page: {calculated_pages}")
                return calculated_pages

        pages = soup.select("ul.pagination li a, div.pagination a")
        if not pages:
            return 1
        return max(int(p.text.strip()) for p in pages if p.text.strip().isdigit())
    except Exception as e:
        print(f"[WARN] Error fetching max page: {e}")
        return 1

# Thêm tham số test_mode để điều khiển số lượng job lấy trên mỗi page
def get_job_list(keyword, location, test_mode=False, max_jobs=None):
    keyword = keyword.replace(" ", "-").lower().strip()
    
    loc_clean = location.lower().strip() if location else ""
    if loc_clean in ["vietnam", "viet-nam", "all", "nationwide", ""]:
        loc_clean = ""
    elif loc_clean in ["ho-chi-minh", "ho chi minh", "hcm"]:
        loc_clean = "ho-chi-minh-hcm"
    elif loc_clean in ["ha-noi", "hanoi", "ha noi"]:
        loc_clean = "ha-noi"
    elif loc_clean in ["da-nang", "danang", "da nang"]:
        loc_clean = "da-nang"
        
    job_links = []
    max_page = get_max_page(keyword, loc_clean)
    if max_jobs and max_jobs > 0:
        requested_pages = max(3, math.ceil(max_jobs / 20))
    else:
        requested_pages = 3
    effective_max_page = min(max_page, requested_pages)
    
    if test_mode:
        print(f"[TEST MODE] Đang kích hoạt mode test. Sẽ quét tối đa {effective_max_page} trang, mỗi trang chỉ lấy 1 job.")
    else:
        if loc_clean:
            print(f"[ESTIMATE] Found {max_page} pages in total. System will crawl {effective_max_page} pages for {keyword} in {loc_clean}")
        else:
            print(f"[ESTIMATE] Found {max_page} pages in total. System will crawl {effective_max_page} pages for {keyword} (Toàn quốc / Vietnam)")

    for page in range(1, effective_max_page + 1):
        if loc_clean:
            list_url = f"https://itviec.com/it-jobs/{keyword}/{loc_clean}?page={page}"
        else:
            list_url = f"https://itviec.com/it-jobs/{keyword}?page={page}"
            
        try:
            response = requests.get(list_url, headers=get_headers(), timeout=15)
            decode_html_response(response)
            print(f"Page {page} - Status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"Failed to fetch page {page} - Status: {response.status_code}")
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            job_items = soup.find_all("div", {"data-controller": "search--job-selection"})
            
            # Nếu ở chế độ test, giới hạn danh sách job_items của trang đó xuống còn 1 phần tử duy nhất
            if test_mode and len(job_items) > 0:
                job_items = [job_items[0]]
                
            print(f"Found {len(job_items)} job items on page {page}")
            
            for job_item in job_items:
                try:
                    job_url_path = job_item.get("data-search--job-selection-job-url-value")
                    if not job_url_path:
                        title_elem = job_item.find("h3", {"data-search--job-selection-target": "jobTitle"})
                        if title_elem and title_elem.has_attr("data-url"):
                            job_url_path = title_elem["data-url"]
                            
                    if not job_url_path:
                        continue
                        
                    job_url_path = job_url_path.split("?")[0]
                    if job_url_path.endswith("/content"):
                        job_url_path = job_url_path[:-8]
                        
                    full_url = f"https://itviec.com{job_url_path}" if not job_url_path.startswith("http") else job_url_path
                    job_links.append(full_url)
                except Exception as e:
                    print(f"Error scraping job link on page {page}: {e}")
                    continue
        except Exception as e:
            print(f"Network error on page {page}: {e}")
            continue

        time.sleep(random.uniform(3, 7))

    return job_links

# Gửi request độc lập kết hợp cơ chế sleep 2-5 giây để lấy dữ liệu chi tiết
def scrape_job_detail(job_url: str) -> RawJobData | None:
    title = None
    description_html = ""
    company_name = None
    job_container = None

    def clean_section_html(section):
        for tag in section.find_all(["button", "script", "style"]):
            tag.decompose()
        return str(section)

    def find_full_job_preview_block(soup):
        content_section = soup.select_one("section.job-content, section[data-jobs--jd-scroll-target='jobContent']")
        if not content_section:
            return None
        node = content_section
        while node:
            classes = node.get("class", [])
            if node.name == "div" and "row" in classes and "im-0" in classes and "ip-0" in classes:
                return node
            node = node.parent if getattr(node, "parent", None) else None
        return None

    try:
        job_detail = requests.get(job_url, headers=get_headers(), timeout=15)
        decode_html_response(job_detail)
        if job_detail.status_code != 200:
            print(f"[WARN] Failed to fetch job details for {job_url} - Status: {job_detail.status_code}")
            return RawJobData(
                source_name="itviec",
                job_url=job_url,
                job_source_id=job_url.rstrip("/").split("/")[-1],
                title="Failed to scrape",
                description_html=""
            )
            
        job_soup = BeautifulSoup(job_detail.text, "html.parser")
        
        posted_dt, raw_date_text = extract_itviec_posted_date(job_soup)
        posted_date_str = posted_dt.isoformat() if posted_dt else None
        print(f"[CHECK DATE] Source: itviec | Raw Text: {raw_date_text} | Parsed Date: {posted_date_str}")
        
        title_elem = job_soup.select_one("div.job-header-info h1")
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"
        
        company_name_elem = job_soup.select_one(".employer-name, h2.employer-long-overview__name")
        company_name = company_name_elem.text.strip() if company_name_elem else None
        
        full_preview_block = find_full_job_preview_block(job_soup)
        job_content_section = job_soup.select_one("section.job-content, section[data-jobs--jd-scroll-target='jobContent']")
        employer_info_section = job_soup.select_one("section.job-show-employer-info")
        job_container = full_preview_block or job_content_section
        
        if full_preview_block:
            description_html = clean_section_html(full_preview_block)
        elif job_content_section:
            parts = [clean_section_html(job_content_section)]
            if employer_info_section:
                parts.append(clean_section_html(employer_info_section))
            description_html = "\n".join(part for part in parts if part)
        else:
            desc_sections = job_soup.find_all("div", class_="job-description__item--content")
            desc_parts = []
            if desc_sections:
                if len(desc_sections) > 0:
                    desc_parts.append(f"<h3>Job Description</h3>{clean_section_html(desc_sections[0])}")
                if len(desc_sections) > 1:
                    desc_parts.append(f"<h3>Job Requirements</h3>{clean_section_html(desc_sections[1])}")
                if len(desc_sections) > 2:
                    desc_parts.append(f"<h3>Benefits</h3>{clean_section_html(desc_sections[2])}")
            if employer_info_section:
                desc_parts.append(clean_section_html(employer_info_section))
            description_html = "\n".join(str(p) for p in desc_parts) if desc_parts else ""

        # Extract metadata fields
        locations = []
        for elem in job_soup.select("div.d-inline-block.text-dark-grey, div.preview-header-item"):
            svg = elem.find("svg")
            if svg and svg.find("use") and "map-pin" in svg.find("use").get("href", ""):
                span = elem.find("span", class_="normal-text")
                if span:
                    locations.append(span.get_text(strip=True))
        location_raw = ", ".join(locations) if locations else None

        salary_elem = job_soup.select_one("div.salary")
        salary_raw = None
        if salary_elem:
            sign_in_link = salary_elem.find("a", class_="sign-in-view-salary")
            if sign_in_link:
                salary_raw = "Sign in to view salary"
            else:
                salary_raw = salary_elem.get_text(strip=True)

        tags = []
        if job_container:
            for a in job_container.select("a.itag"):
                href = a.get("href", "")
                if "/it-jobs/" in href and "click_source=Skill" in href:
                    tags.append(a.get_text(strip=True))
        print(f"[CHECK TAGS] Job: {title} | Total Tags: {len(tags)} | Details: {tags}")

        company_size_raw = None
        company_industry = None
        employer_section = job_soup.select_one("section.job-show-employer-info")
        if employer_section:
            for row in employer_section.select(".row.ipy-2"):
                cols = row.select(".col")
                if len(cols) == 2:
                    label = cols[0].get_text(strip=True).lower()
                    val = cols[1].get_text(" ", strip=True)
                    if "company size" in label:
                        company_size_raw = val
                    elif "company type" in label or "industry" in label:
                        company_industry = val

        requirements_text = None
        req_heading = job_soup.find("h2", string=re.compile(r"skills and experience", re.I))
        if req_heading:
            parent = req_heading.parent
            if parent:
                requirements_text = parent.get_text("\n", strip=True)

        time.sleep(random.uniform(2, 5))
        
    except Exception as e:
        print(f"[ERROR] scrape_job_detail({job_url}): {e}")
        return RawJobData(
            source_name="itviec",
            job_url=job_url,
            job_source_id=job_url.rstrip("/").split("/")[-1],
            title="Error",
            description_html=""
        )
    
    return RawJobData(
        source_name="itviec",
        job_url=job_url,
        job_source_id=job_url.rstrip("/").split("/")[-1],
        title=title,
        description_html=description_html,
        location_raw=location_raw,
        salary_raw=salary_raw,
        employment_type="Full-time",
        experience_raw=None,
        posted_date=posted_date_str,
        expiry_date=None,
        scraped_at=datetime.now().isoformat(),
        tags=tags,
        benefits=[],
        company_name=company_name,
        company_source_id=None,
        company_website=None,
        company_address=location_raw,
        company_size_raw=company_size_raw,
        company_industry=company_industry,
        requirements_text=requirements_text
    )

def export_to_json(data, out_prefix=None):
    out = 'jobs.json'
    if out_prefix:
        out_dir = os.path.dirname(out_prefix)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        out = f"{out_prefix}.json"
    data_dicts = [job.to_dict() if hasattr(job, 'to_dict') else job for job in data]
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data_dicts, f, ensure_ascii=False, indent=4)

def export_to_csv(data, out_prefix=None):
    if data:
        data_dicts = [job.to_dict() if hasattr(job, 'to_dict') else job for job in data]
        fields = data_dicts[0].keys()
        out = 'jobs.csv'
        if out_prefix:
            os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
            out = f"{out_prefix}.csv"
        with open(out, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data_dicts)

def export_to_excel(data, out_prefix=None):
    data_dicts = [job.to_dict() if hasattr(job, 'to_dict') else job for job in data]
    df = pd.DataFrame(data_dicts)
    out = 'jobs.xlsx'
    if out_prefix:
        os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
        out = f"{out_prefix}.xlsx"
    df.to_excel(out, index=False)

def scrape_data(keyword, location, max_jobs=None, search_keyword=None, test_mode=False):
    if max_jobs is not None and max_jobs <= 0:
        print("[INFO] max_jobs is 0 or negative. Skipping crawl and returning empty list.")
        return []
    print(f"[INFO] Dang crawl danh sach job cho '{keyword}' tai '{location}'...")
    print(f"[INFO] Date filter mode: {describe_date_filter()}")
    job_links = get_job_list(keyword, location, test_mode=test_mode, max_jobs=max_jobs)
    print(f"[INFO] Tim thay {len(job_links)} job. Dang scrape chi tiet...")

    if max_jobs and max_jobs > 0:
        job_links = job_links[:max_jobs]
    
    jobs_data = []
    for i, job_url in enumerate(job_links, 1):
        print(f"[{i}/{len(job_links)}] Scraping {job_url}")
        detail = scrape_job_detail(job_url)
        if detail is None:
            continue
        detail.search_keyword = search_keyword or keyword
        jobs_data.append(detail)

    # Apply central recent-job filter (window from env DAYS_BACK/REALTIME_DAYS or default 72h)
    try:
        filtered = filter_recent_jobs(jobs_data)
        return filtered
    except Exception:
        return jobs_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape ITviec jobs")
    parser.add_argument("--keyword", default="software engineer", help="Job keyword to search")
    parser.add_argument("--location", default="Vietnam", help="Location")
    parser.add_argument("--out_prefix", default=None, help="Output prefix path without extension")
    parser.add_argument("--test_mode", action="store_true", help="Kich hoat mode test: 1 trang lay 1 job")
    args = parser.parse_args()

    if not args.out_prefix:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(__file__)
        output_dir = os.path.join(base_dir, "../../output")
        args.out_prefix = os.path.join(output_dir, f"{args.keyword}_{args.location.lower().replace(' ', '_')}_{timestamp}")

    print(f"Scraping '{args.keyword}' in '{args.location}'...")
    jobs_data = scrape_data(args.keyword, args.location, test_mode=args.test_mode)
    
    if jobs_data:
        export_to_json(jobs_data, args.out_prefix)
        export_to_csv(jobs_data, args.out_prefix)
        export_to_excel(jobs_data, args.out_prefix)
        print(f"✓ Completed! Output generated at: {args.out_prefix}")
    else:
        print("[WARN] No jobs found!")