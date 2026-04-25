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
from datetime import datetime
import unicodedata
import re

# Import schema
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from schema import RawJobData
from date_filter import describe_date_filter, is_posted_date_allowed, parse_iso_date, parse_relative_time_to_date

# Try to use cloudscraper if available, fallback to requests
try:
    import cloudscraper
    session = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    print("Using cloudscraper to bypass CloudFlare")
except ImportError:
    print("cloudscraper not available, using requests (may face 403 errors)")
    session = requests.Session()

# Headers giả lập browser
def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }
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
                    return parsed

    posted_elem = job_soup.find("span", string=re.compile(r"Posted\s+\d+\s+\w+\s+ago", re.I))
    if posted_elem:
        parsed = parse_relative_time_to_date(posted_elem.get_text(" ", strip=True))
        if parsed:
            return parsed
    return None

# Lấy số trang tối đa
def get_max_page(keyword, location):
    q = urllib.parse.quote(keyword)
    loc = urllib.parse.quote(location)
    url = f"https://itviec.com/it-jobs/{q}/{loc}"
    resp = session.get(url, headers=get_headers(), timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    pages = soup.select("ul.pagination li a")
    if not pages:
        return 1
    try:
        return max(int(p.text.strip()) for p in pages if p.text.strip().isdigit())
    except:
        return 1

# Lấy danh sách link job theo từ khóa + địa điểm
def get_job_list(keyword, location):
    keyword = keyword.replace(" ", "-").lower().strip()
    location = location.replace(" ", "-").lower().strip()
    if(location == "ho-chi-minh"):
        location+="-hcm"
    job_links = []
    max_page = get_max_page(keyword, location)
    print(f"Found {max_page} pages for {keyword} in {location}")

    for page in range(1, max_page + 1):
        list_url = f"https://itviec.com/it-jobs/{keyword}/{location}?page={page}"
        response = session.get(list_url, headers=get_headers(), timeout=15)
        print(f"Page {page} - Status: {response.status_code}, Content length: {len(response.text)}")
        if response.status_code != 200:
            print(f"Failed to fetch page {page} - Status: {response.status_code}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        job_items = soup.find_all("div", {"data-controller": "search--job-selection"})
        print(f"Found {len(job_items)} job items on page {page}")
        
        # Debug: save HTML if no jobs found
        if len(job_items) == 0:
            debug_file = f"debug_page_{page}.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
            print(f"Saved HTML to {debug_file} for debugging")
        
        for job_item in job_items:
            try:
                # Lấy URL từ data attribute
                job_url_path = job_item.get("data-search--job-selection-job-url-value")
                if not job_url_path:
                    continue
                # Loại bỏ query params và /content suffix
                job_url_path = job_url_path.split("?")[0]
                if job_url_path.endswith("/content"):
                    job_url_path = job_url_path[:-8]  # Remove "/content"
                full_url = f"https://itviec.com{job_url_path}"
                job_links.append(full_url)
            except Exception as e:
                print(f"Error scraping job link on page {page}: {e}")
                continue

        time.sleep(random.uniform(3, 7))

    return job_links

# Lấy chi tiết job từ từng link
def scrape_job_detail(job_url: str) -> RawJobData | None:
    # Initialize default values
    title = None
    description_html = ""
    location_raw = None
    salary_raw = None
    experience_raw = None
    employment_type = None
    posted_date = None
    expiry_date = None
    tags = []
    company_name = None
    company_website = None
    company_address = None
    company_size_raw = None
    company_industry = None
    requirements_text = None
    benefits_text = None

    def clean_section_html(section):
        # Remove non-content elements like buttons/scripts/styles
        for tag in section.find_all(["button", "script", "style"]):
            tag.decompose()
        return str(section)

    def find_full_job_preview_block(soup):
        """Return the full preview block that contains header, info, content and employer box."""
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

    def extract_company_from_block(soup):
        """Extract company info from job page employer block. Returns dict with extracted values."""
        result = {"size": None, "industry": None, "address": None}
        block = soup.select_one(".job-show-employer-info")
        if not block:
            return result
        
        rows = block.select("div.row")
        for row in rows:
            cols = row.select(".col")
            if len(cols) < 2:
                continue
            
            label_text = cols[0].get_text(" ", strip=True).lower()
            value_elem = cols[1]
            value_text = value_elem.get_text(" ", strip=True)
            
            if not value_text or not label_text:
                continue
            
            if "company size" in label_text:
                result["size"] = value_text.replace("\n", " ").strip()
            elif "company industry" in label_text:
                result["industry"] = value_text
            elif "company type" in label_text and not result["industry"]:
                result["industry"] = value_text
            elif "country" in label_text:
                result["address"] = value_text
        
        return result

    def extract_tags_from_skills_block(soup):
        nonlocal tags
        if tags:
            return
        skills_label = soup.find(lambda tag: tag.name in ["div", "span"] and tag.get_text(strip=True).lower() == "skills:")
        if skills_label:
            sibling = skills_label.find_next_sibling()
            if sibling:
                anchors = sibling.find_all("a")
                tags = [a.get_text(strip=True) for a in anchors if a.get_text(strip=True)]

    def extract_industry_from_job_domain(soup):
        nonlocal company_industry
        if company_industry:
            return
        
        # Find the "Job Domain:" label and extract tags from next sibling
        all_divs = soup.find_all("div")
        for i, div in enumerate(all_divs):
            if div.get_text(strip=True).lower() == "job domain:":
                # Look for sibling with tags
                parent = div.parent
                if parent:
                    tags_container = parent.find_next_sibling()
                    if tags_container:
                        domain_tags = tags_container.find_all("div", class_="itag")
                        if domain_tags:
                            company_industry = domain_tags[0].get_text(strip=True)
                return

    def slugify(text: str) -> str:
        if not text:
            return ""
        norm = unicodedata.normalize("NFKD", text)
        ascii_text = norm.encode("ascii", "ignore").decode("ascii")
        return "-".join(
            filter(None, "".join(ch if ch.isalnum() else " " for ch in ascii_text).lower().split())
        )

    try:
        job_detail = session.get(job_url, headers=get_headers(), timeout=15)
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
        posted_dt = extract_itviec_posted_date(job_soup)
        if not is_posted_date_allowed(posted_dt):
            print(f"[SKIP OLD JOB] {job_url} - posted_date={posted_dt}")
            return None
        
        # Extract minimal fields only (match vietnamworks)
        title_elem = job_soup.select_one("div.job-header-info h1")
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"
        
        # Extract company name
        company_name_elem = job_soup.select_one(".employer-name, h2.employer-long-overview__name")
        company_name = company_name_elem.text.strip() if company_name_elem else None
        
        # Prefer the full preview block users see on the job page:
        # header + info strip + job content + employer info box.
        full_preview_block = find_full_job_preview_block(job_soup)

        # Extract full job content section (main job-content section with all details)
        job_content_section = job_soup.select_one("section.job-content, section[data-jobs--jd-scroll-target='jobContent']")
        employer_info_section = job_soup.select_one("section.job-show-employer-info")
        
        if full_preview_block:
            description_html = clean_section_html(full_preview_block)
        elif job_content_section:
            # Keep the main job content and append employer info so output matches
            # the information users see on the ITViec job page.
            parts = [clean_section_html(job_content_section)]
            if employer_info_section:
                parts.append(clean_section_html(employer_info_section))
            description_html = "\n".join(part for part in parts if part)
        else:
            # Fallback: Build description HTML from description sections
            desc_sections = job_soup.find_all("div", class_="job-description__item--content")
            desc_parts = []
            
            if desc_sections:
                if len(desc_sections) > 0:
                    desc_parts.append(f"<h3>Job Description</h3>{clean_section_html(desc_sections[0])}")
                if len(desc_sections) > 1:
                    desc_parts.append(f"<h3>Job Requirements</h3>{clean_section_html(desc_sections[1])}")
                if len(desc_sections) > 2:
                    desc_parts.append(f"<h3>Benefits</h3>{clean_section_html(desc_sections[2])}")
            else:
                # Alternative layout: use h2/h3 headings
                section_map = {}
                for heading in job_soup.find_all(["h2", "h3"]):
                    name = heading.get_text(strip=True).lower()
                    key = None
                    if "job description" in name:
                        key = "description"
                    elif "skills" in name or "experience" in name:
                        key = "requirements"
                    elif "love working here" in name or "benefits" in name:
                        key = "benefits"
                    if not key:
                        continue
                    
                    blocks = []
                    sib = heading.find_next_sibling()
                    while sib and sib.name not in ["h2", "h3"]:
                        if sib.name in ["button", "script", "style"]:
                            sib = sib.find_next_sibling()
                            continue
                        blocks.append(str(sib))
                        sib = sib.find_next_sibling()
                    section_map[key] = "\n".join(blocks).strip()
                
                if "description" in section_map:
                    desc_parts.append(f"<h3>Job Description</h3>{section_map['description']}")
                if "requirements" in section_map:
                    desc_parts.append(f"<h3>Job Requirements</h3>{section_map['requirements']}")
                if "benefits" in section_map:
                    desc_parts.append(f"<h3>Benefits</h3>{section_map['benefits']}")
            
            if employer_info_section:
                desc_parts.append(clean_section_html(employer_info_section))

            description_html = "\n".join(str(p) for p in desc_parts) if desc_parts else ""
        
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
    
    # Return RawJobData object (minimal - match vietnamworks)
    return RawJobData(
        source_name="itviec",
        job_url=job_url,
        job_source_id=job_url.rstrip("/").split("/")[-1],
        title=title,
        description_html=description_html,
        location_raw=None,
        salary_raw=None,
        employment_type=None,
        experience_raw=None,
        posted_date=None,
        expiry_date=None,
        scraped_at=datetime.now().isoformat(),
        tags=[],
        benefits=[],
        company_name=company_name,
        company_source_id=None,
        company_website=None,
        company_address=None,
        company_size_raw=None,
        company_industry=None,
        requirements_text=None
    )

# Export functions
def export_to_json(data, out_prefix=None):
    out = 'jobs.json'
    if out_prefix:
        out_dir = os.path.dirname(out_prefix)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        out = f"{out_prefix}.json"
        print(f"[BEFORE SAVE] out_prefix: {out_prefix}")
        print(f"[BEFORE SAVE] out_dir: {out_dir}")
        print(f"[BEFORE SAVE] final out: {out}")
    # Convert RawJobData objects to dict
    data_dicts = [job.to_dict() if hasattr(job, 'to_dict') else job for job in data]
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data_dicts, f, ensure_ascii=False, indent=4)
    
    # Print after save
    actual_path = os.path.abspath(out)
    print(f"[AFTER SAVE] File saved at: {actual_path}")
    print(f"[AFTER SAVE] File exists: {os.path.exists(actual_path)}")

def export_to_csv(data, out_prefix=None):
    if data:
        # Convert to dicts first
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
    # Convert to dicts first
    data_dicts = [job.to_dict() if hasattr(job, 'to_dict') else job for job in data]
    df = pd.DataFrame(data_dicts)
    out = 'jobs.xlsx'
    if out_prefix:
        os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
        out = f"{out_prefix}.xlsx"
    df.to_excel(out, index=False)

def scrape_data(keyword, location, max_jobs=None, search_keyword=None):
    print(f"[INFO] Dang crawl danh sach job cho '{keyword}' tai '{location}'...")
    print(f"[INFO] Date filter mode: {describe_date_filter()}")
    job_links = get_job_list(keyword, location)
    print(f"[INFO] Tim thay {len(job_links)} job. Dang scrape chi tiet...")

    # Giới hạn số job nếu max_jobs được chỉ định
    if max_jobs and max_jobs > 0:
        job_links = job_links[:max_jobs]
    
    jobs_data = []
    for i, job_url in enumerate(job_links, 1):
        print(f"[{i}/{len(job_links)}] Scraping {job_url}")
        detail = scrape_job_detail(job_url)
        if detail is None:
            continue
        detail.search_keyword = search_keyword or keyword  # Set search keyword
        jobs_data.append(detail)

    return jobs_data

# Main execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape ITviec jobs")
    parser.add_argument("--keyword", default="software engineer", help="Job keyword to search")
    parser.add_argument("--location", default="Ho Chi Minh", help="Location (Ho Chi Minh, Hanoi, Da Nang, Can Tho, Hai Phong)")
    parser.add_argument("--out_prefix", default=None, help="Output prefix path without extension")
    args = parser.parse_args()

    # Tự động tạo output prefix nếu không được cung cấp
    if not args.out_prefix:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(__file__)
        output_dir = os.path.join(base_dir, "../../output")
        args.out_prefix = os.path.join(output_dir, f"{args.keyword}_{args.location.lower().replace(' ', '_')}_{timestamp}")

    print(f"Scraping '{args.keyword}' in '{args.location}'...")
    jobs_data = scrape_data(args.keyword, args.location)
    
    if jobs_data:
        export_to_json(jobs_data, args.out_prefix)
        print(f"✓ Completed! Output: {args.out_prefix}.json ({len(jobs_data)} jobs)")
    else:
        print("[WARN] No jobs found!")
