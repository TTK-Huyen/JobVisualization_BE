import time, re, random, os, argparse, platform, json
from typing import Dict, List
from datetime import datetime
import sys

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from schema import RawJobData
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import requests
BASE = "https://www.linkedin.com"

def build_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")   # chạy ẩn, bỏ nếu muốn thấy browser
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

def extract_job_ids(keywords: str, location:str) -> List:
    keywords = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20").lower()
    max_jobs = 100
    id_list = []
    start = 0

    # Lặp đến khi đủ job hoặc API không trả về job mới
    while len(id_list) < max_jobs:
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keywords}&location={loc}&start={start}"
        response = requests.get(url)
        if response.status_code != 200 or not response.text.strip():
            print("Hết job để lấy.")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        jobs = soup.find_all("div", {"class": "base-card"})
        if not jobs:
            print("Không còn job nào.")
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

        print(f"Trang {start}: thu được {len(id_list)} job")
        if added_this_page == 0:
            break
        start += added_this_page  # Tăng start dựa trên số job mới thêm

    print(f"Tổng số job thu được: {len(id_list)}")
    return id_list

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
    """Convert LinkedIn job dict to RawJobData schema"""
    try:
        # Extract job ID from URL (prefer numeric id at end)
        job_source_id = ""
        if job_post.get("job_url"):
            m = re.search(r"/jobs/view/.*?-(\d+)(?:[/?]|$)", job_post["job_url"])  # slug-<id>
            if not m:
                m = re.search(r"/jobs/view/(\d+)(?:[/?]|$)", job_post["job_url"])  # /view/<id>
            if m:
                job_source_id = m.group(1)
        
        # Extract company source ID from company URL
        company_source_id = ""
        if job_post.get("company_url"):
            match = re.search(r'/company/([^/?]+)', job_post["company_url"])
            if match:
                company_source_id = match.group(1)
        
        # Parse benefits list
        benefits = []
        if job_post.get("benefits_items"):
            benefits = [b for b in job_post["benefits_items"] if b]
        elif job_post.get("desc_quyenloi"):
            # Split by common delimiters and clean up
            raw = job_post["desc_quyenloi"].replace("•", "-")
            for sep in ["-", "\n", "\u2022"]:
                parts = [p.strip() for p in raw.split(sep) if p and p.strip()]
                if len(parts) > 1:
                    benefits = parts
                    break
            if not benefits:
                benefits = [raw.strip()]
        benefits = benefits[:10]
        
        # Parse tags from job function and detect skills from description
        tags = []
        if job_post.get("tags"):
            tags.extend([job_post["tags"]] if isinstance(job_post["tags"], str) else job_post["tags"])
        # simple skills detection from description text
        text_blob = " ".join(filter(None, [job_post.get("desc_mota"), job_post.get("desc_yeucau")]))
        skills = [
            "python", "java", "c#", "c++", "go", "golang", "javascript", "typescript",
            "react", "angular", "vue", "node", "django", "flask", "spring", "dotnet", 
            "aws", "azure", "gcp", "kubernetes", "docker", "sql", "postgres", "mysql",
            "mongodb", "redis", "spark", "hadoop", "airflow", "terraform", "ansible",
        ]
        low = (text_blob or "").lower()
        detected = []
        for s in skills:
            if s in low:
                detected.append(s.capitalize() if s.isalpha() else s)
        if detected:
            tags.extend(detected)
        # de-duplicate, preserve order
        seen = set()
        tags = [t for t in tags if not (t in seen or seen.add(t))]
        
        return RawJobData(
            source_name="linkedin",
            job_url=job_post.get("job_url", ""),
            job_source_id=job_source_id,
            title=job_post.get("title", ""),
            description_html= job_post.get("desc_html") or job_post.get("desc_mota", ""),
            location_raw=job_post.get("detail_location", ""),
            salary_raw=job_post.get("detail_salary"),
            employment_type=job_post.get("working_times"),
            experience_raw=job_post.get("detail_experience"),
            posted_date=job_post.get("time_posted"),
            expiry_date=job_post.get("deadline"),
            scraped_at=datetime.now().isoformat(),
            tags=tags,
            benefits=benefits,
            company_name=job_post.get("company", ""),
            company_source_id=company_source_id,
            company_website=job_post.get("company_website"),
            company_address= job_post.get("company_address") or job_post.get("detail_location"),
            company_size_raw=job_post.get("company_size"),
            company_industry=job_post.get("company_industry"),
            requirements_text=job_post.get("desc_yeucau")
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

def scrape_data(keyword: str, location: str) -> List[RawJobData]:
    id_list = extract_job_ids(keyword, location)
    job_list = []

    # Loop through the list of job IDs and get each URL
    for job_id in id_list:
        job_post = extract_job_detail(job_id)
        raw_job = convert_to_raw_job_data(job_post)
        job_list.append(raw_job)
        
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
