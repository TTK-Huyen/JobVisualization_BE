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
def scrape_job_detail(job_url: str) -> RawJobData:
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
            # Return minimal valid object
            return RawJobData(
                source_name="itviec",
                job_url=job_url,
                job_source_id=job_url.rstrip("/").split("/")[-1],
                title="Failed to scrape",
                description_html=""
            )

        job_soup = BeautifulSoup(job_detail.text, "html.parser")

        # Extract job_source_id from URL (slug)
        job_source_id = job_url.rstrip("/").split("/")[-1]

        # Thông tin job
        title_elem = job_soup.select_one("div.job-header-info h1")
        if title_elem:
            title = title_elem.get_text(strip=True)
        
        # Salary
        salary_elem = job_soup.select_one("div.salary, span.salary, .imy-3")
        salary_raw = salary_elem.get_text(strip=True) if salary_elem else "Login to view"
        
        # Work Location and related info are in span.normal-text sequence
        location_spans = job_soup.select("span.normal-text")
        if len(location_spans) >= 2:
            location_raw = location_spans[1].get_text(strip=True)
        elif location_spans:
            location_raw = location_spans[0].get_text(strip=True)

        # Employment type often appears as the third span (e.g., Hybrid/Onsite/Remote)
        if len(location_spans) >= 3:
            employment_type = location_spans[2].get_text(strip=True)

        # Posted date sometimes listed after a span with text "Posted" or inside the same span
        for idx, sp in enumerate(location_spans):
            text = sp.get_text(" ", strip=True)
            if "posted" in text.lower():
                cleaned = text.replace("Posted", "").strip()
                posted_date = cleaned if cleaned else None
                if not posted_date and idx + 1 < len(location_spans):
                    posted_date = location_spans[idx + 1].get_text(" ", strip=True)
                break

        # Expiry date / closing date if present (skip scripts/styles and very long blobs)
        expiry_candidates = job_soup.find_all(
            lambda tag: tag.name in ["span", "div", "p", "li"]
            and tag.get_text(strip=True)
            and "expire" in tag.get_text(strip=True).lower()
        )
        for cand in expiry_candidates:
            text = cand.get_text(" ", strip=True)
            if len(text) > 80:
                continue
            match = re.search(r"(?:expire[s]?|closing)[:\-\s]*(.*)", text, re.IGNORECASE)
            candidate = match.group(1).strip() if match else text
            if candidate and len(candidate) <= 60:
                expiry_date = candidate
                break

        # Skills as tags
        tags = [a.get_text(strip=True) for a in job_soup.select("div:has(> .fw-600:-soup-contains('Skills')) a")]
        extract_tags_from_skills_block(job_soup)
        
        # Experience
        exp_elem = job_soup.find("div", string=lambda t: t and "experience" in t.lower() if t else False)
        if exp_elem:
            experience_raw = exp_elem.get_text(strip=True)


        # Description sections (fallback if old selector not found)
        desc_sections = job_soup.find_all("div", class_="job-description__item--content")
        desc_parts = []

        if desc_sections:
            if len(desc_sections) > 0:
                desc_parts.append(f"<h3>Job Description</h3>{clean_section_html(desc_sections[0])}")
            if len(desc_sections) > 1:
                requirements_text = desc_sections[1].get_text("\n", strip=True)
                desc_parts.append(f"<h3>Job Requirements</h3>{clean_section_html(desc_sections[1])}")
            if len(desc_sections) > 2:
                benefits_text = desc_sections[2].get_text("\n", strip=True)
                desc_parts.append(f"<h3>Benefits</h3>{clean_section_html(desc_sections[2])}")
        else:
            # New layout fallback: use h2/h3 headings
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
                requirements_text = BeautifulSoup(section_map["requirements"], "html.parser").get_text("\n", strip=True)
                desc_parts.append(f"<h3>Job Requirements</h3>{section_map['requirements']}")
            if "benefits" in section_map:
                benefits_text = BeautifulSoup(section_map["benefits"], "html.parser").get_text("\n", strip=True)
                desc_parts.append(f"<h3>Benefits</h3>{section_map['benefits']}")

            # Fallback: explicitly grab list under "Your skills and experience"
            if not requirements_text:
                req_heading = job_soup.find(lambda tag: tag.name in ["h2", "h3"] and "skills" in tag.get_text(strip=True).lower())
                if req_heading:
                    req_list = req_heading.find_next_sibling("ul")
                    if req_list:
                        requirements_text = req_list.get_text("\n", strip=True)

        description_html = "\n".join(str(p) for p in desc_parts)

        # Thông tin công ty
        company_name_elem = job_soup.select_one(".employer-name, h2.employer-long-overview__name")
        company_name = company_name_elem.text.strip() if company_name_elem else None

        # Inline company info block on job page - extract before company page scraping
        emp_info = extract_company_from_block(job_soup)
        if emp_info["size"]:
            company_size_raw = emp_info["size"]
        if emp_info["industry"]:
            company_industry = emp_info["industry"]
        if emp_info["address"]:
            company_address = emp_info["address"]
        
        extract_industry_from_job_domain(job_soup)
        
        # If address still empty, use location_raw as fallback
        if not company_address and location_raw:
            company_address = location_raw

        # Company link: try multiple patterns and match by name if possible
        company_url = None
        header_block = job_soup.select_one(".job-header-info")
        first_part_name = company_name.split("|")[0].strip() if company_name else None

        candidates = []
        if header_block:
            candidates.extend(header_block.find_all("a", href=lambda h: h and "/companies/" in h))
        candidates.extend(job_soup.find_all("a", href=lambda h: h and "/companies/" in h))

        for link in candidates:
            text = link.get_text(strip=True)
            if first_part_name and first_part_name.lower() not in text.lower():
                continue
            href = link.get("href")
            if not href:
                continue
            company_url = href if href.startswith("http") else f"https://itviec.com{href}"
            break

        # Fallback: guess company URL from company_name slug if no link found
        if not company_url and company_name:
            guessed_slug = slugify(company_name)
            if guessed_slug:
                guess_url = f"https://itviec.com/companies/{guessed_slug}"
                try:
                    resp_guess = session.get(guess_url, headers=get_headers(), timeout=8)
                    if resp_guess.status_code == 200:
                        company_url = guess_url
                    else:
                        print(f"[INFO] Guessed company URL {guess_url} returned {resp_guess.status_code}")
                except Exception:
                    pass

        # Scrape company page nếu có link
        if company_url:
            try:
                comp_resp = session.get(company_url, headers=get_headers(), timeout=10)
                if comp_resp.status_code == 200:
                    comp_soup = BeautifulSoup(comp_resp.text, "html.parser")
                    
                    website_elem = comp_soup.find("a", {"rel": "nofollow noopener noreferrer"})
                    company_website = website_elem["href"] if website_elem and website_elem.has_attr("href") else None
                    
                    size_elem = comp_soup.find("svg", class_="fi-rr-users-alt")
                    if not company_size_raw:
                        company_size_raw = size_elem.parent.parent.text.strip() if size_elem and size_elem.parent and size_elem.parent.parent else None
                    
                    industry_elem = comp_soup.find("svg", class_="fi-rr-briefcase")
                    if not company_industry:
                        company_industry = industry_elem.parent.parent.text.strip() if industry_elem and industry_elem.parent and industry_elem.parent.parent else None
                    
                    address_elem = comp_soup.find("svg", class_="fi-rr-marker")
                    if not company_address:
                        company_address = address_elem.parent.parent.text.strip() if address_elem and address_elem.parent and address_elem.parent.parent else None
            except Exception as e:
                print(f"[WARN] Failed to scrape company page: {e}")

        time.sleep(random.uniform(2, 5))
    except Exception as e:
        print(f"[ERROR] scrape_job_detail({job_url}): {e}")
        # Return minimal valid object on error
        return RawJobData(
            source_name="itviec",
            job_url=job_url,
            job_source_id=job_url.rstrip("/").split("/")[-1],
            title=title or "Error",
            description_html=""
        )

    # Extract company_source_id from company URL
    company_source_id = None
    if company_url:
        company_source_id = company_url.split("/")[-1] if "/" in company_url else None

    # Build benefits list from benefits_text if available
    benefits = []
    if benefits_text:
        # Split by newlines or bullet points
        raw_benefits = [b.strip() for b in benefits_text.split("\n") if b.strip()]
        excluded = {"benefits", "cultural values", "equal opportunity"}
        benefits = []
        for b in raw_benefits:
            norm = re.sub(r"[^a-z0-9]+", " ", b.lower()).strip()
            if norm in excluded or len(norm) <= 2:
                continue
            benefits.append(b)

    # Return RawJobData object
    return RawJobData(
        source_name="itviec",
        job_url=job_url,
        job_source_id=job_source_id,
        title=title or "Unknown",
        description_html=description_html,
        location_raw=location_raw,
        salary_raw=salary_raw,
        employment_type=employment_type,
        experience_raw=experience_raw,
        posted_date=posted_date,
        expiry_date=expiry_date,
        scraped_at=datetime.now().isoformat(),
        tags=tags,
        benefits=benefits,
        company_name=company_name,
        company_source_id=company_source_id,
        company_website=company_website,
        company_address=company_address,
        company_size_raw=company_size_raw,
        company_industry=company_industry,
        requirements_text=requirements_text
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

def scrape_data(keyword, location, max_jobs=None):
    print(f"[INFO] Dang crawl danh sach job cho '{keyword}' tai '{location}'...")
    job_links = get_job_list(keyword, location)
    print(f"[INFO] Tim thay {len(job_links)} job. Dang scrape chi tiet...")

    # Giới hạn số job nếu max_jobs được chỉ định
    if max_jobs and max_jobs > 0:
        job_links = job_links[:max_jobs]
    
    jobs_data = []
    for i, job_url in enumerate(job_links, 1):
        print(f"[{i}/{len(job_links)}] Scraping {job_url}")
        detail = scrape_job_detail(job_url)
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