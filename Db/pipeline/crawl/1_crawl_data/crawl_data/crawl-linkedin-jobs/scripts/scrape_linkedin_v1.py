import time, re, random, os, argparse, platform
from typing import Dict, List
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

# CẤU HÌNH: Khai báo danh sách 10 Proxy Webshare của bạn tại đây
# Định dạng chuẩn: "http://username:password@ip:port"
WEBSHARE_PROXIES = [
    "http://njjmwucc:xvp3yzigvw0n@38.154.203.95:5863/",
    "http://njjmwucc:xvp3yzigvw0n@198.105.121.200:6462/",
    "http://njjmwucc:xvp3yzigvw0n@64.137.96.74:6641/",
    "http://njjmwucc:xvp3yzigvw0n@209.127.138.10:5784/",
    "http://njjmwucc:xvp3yzigvw0n@38.154.185.97:6370/", 
    "http://njjmwucc:xvp3yzigvw0n@84.247.60.125:6095/",
    "http://njjmwucc:xvp3yzigvw0n@142.111.67.146:5611/", 
    "http://njjmwucc:xvp3yzigvw0n@191.96.254.138:6185/",
    "http://njjmwucc:xvp3yzigvw0n@31.58.9.4:6077/",
    "http://njjmwucc:xvp3yzigvw0n@64.137.10.153:5803/"
]


USE_PROXY = True

def get_random_proxy_config() -> Dict | None:
    """Bốc ngẫu nhiên 1 proxy trong danh sách để cấu hình cho thư viện requests."""
    if not USE_PROXY:
        return None
    if not WEBSHARE_PROXIES or "ip1:port" in WEBSHARE_PROXIES[0]:
        return None
    proxy = random.choice(WEBSHARE_PROXIES)
    return {
        "http": proxy,
        "https": proxy
    }

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

def extract_job_ids(keywords: str, location:str, max_jobs: int = 100) -> List:
    keywords = keywords.replace(" ", "%20")
    loc = location.replace(" ", "%20").lower()
    id_list = []
    start = 0

    # Lặp đến khi đủ job hoặc API không trả về job mới
    while len(id_list) < max_jobs:
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keywords}&location={loc}&start={start}"
        
        response = None
        retries = 3
        while retries > 0:
            try:
                proxy = get_random_proxy_config()
                response = requests.get(url, proxies=proxy, timeout=15)
                break
            except Exception as e:
                retries -= 1
                print(f"[WARN] Lỗi kết nối/proxy ({e}). Thử lại... (Còn {retries} lần thử)")
                time.sleep(2)
                
        if response is None or response.status_code != 200 or not response.text.strip():
            status_str = response.status_code if response else "No Response"
            print(f"Hết job để lấy hoặc bị chặn kết nối (Status: {status_str}). Dừng lấy job IDs và tiếp tục crawl thông tin đã thu thập.")
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
        
        # Tạo độ trễ ngẫu nhiên nhỏ để tăng tính tự nhiên
        time.sleep(random.uniform(1, 3))

    print(f"Tổng số job thu được: {len(id_list)}")
    return id_list

def extract_company_detail(company_url: str) -> Dict:
    if not company_url:
        return {}
    
    # Remove locale/language prefix from LinkedIn company URLs (e.g., vi.linkedin.com -> linkedin.com)
    company_url = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", company_url)
    
    # CẬP NHẬT: Thêm proxy xoay vòng ngẫu nhiên
    try:
        response = requests.get(company_url, proxies=get_random_proxy_config(), timeout=15)
        if response.status_code != 200:
            return {}
    except:
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
    
    # CẬP NHẬT: Thêm proxy xoay vòng ngẫu nhiên
    try:
        job_response = requests.get(job_url, proxies=get_random_proxy_config(), timeout=15)
        job_soup = BeautifulSoup(job_response.text, "html.parser")
    except Exception as e:
        print(f"[WARN] Request failed for job_id {job_id}: {e}")
        return {}
        
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
    
    # Description parsing
    try:
        desc_div = job_soup.find("div", {"class": "description__text"})
        if desc_div:
            markup_div = desc_div.find("div", {"class": "show-more-less-html__markup"}) or desc_div

            # lấy tất cả header dạng thẻ
            headers = markup_div.find_all(["strong", "b", "h3"])

            # thêm text thuần nếu trùng key quan trọng
            for tag in markup_div.find_all(string=True):
                txt = tag.strip().lower()
                if txt in ["requirements", "responsibilities", "job description", 
                        "desired skills and experience", "benefits"]:
                    headers.append(tag)

            for section in headers:
                # lấy header text
                if hasattr(section, "get_text"):
                    header = section.get_text(strip=True).lower()
                else:  # là text node
                    header = section.strip().lower()

                # tìm nội dung liền sau
                text_content = ""
                next_el = section.find_next() if hasattr(section, "find_next") else None
                if next_el:
                    ul = next_el.find_next("ul")
                    if ul:
                        text_content = "-".join(li.get_text(strip=True) for li in ul.find_all("li"))
                    else:
                        next_p = next_el.find_next("p")
                        if next_p:
                            text_content = next_p.get_text(strip=True)
                
                # Description/Mota
                if any(key in header for key in ["responsibilities", "job description", "mô tả", "description", "main duties", "nhiệm vụ", "mission"]):
                    job_post["desc_mota"] = text_content
                
                # Requirements/Yeucau
                elif any(key in header for key in ["requirement", "yêu cầu", "qualification", "skill", "requirements", "qualifications"]):
                    job_post["desc_yeucau"] = text_content
                
                # Benefits/Quyenloi
                elif any(key in header for key in ["benefit", "quyền lợi", "phúc lợi", "chế độ", "benefits"]):
                    job_post["desc_quyenloi"] = text_content
                
                # Working time
                elif any(key in header for key in ["working time", "thời gian làm việc", "giờ làm việc"]):
                    job_post["working_times"] = text_content
                
                # Working location
                elif any(key in header for key in ["working location", "địa điểm làm việc", "workplace"]):
                    job_post["working_addresses"] = text_content
                
                # Salary
                elif any(key in header for key in ["salary", "lương", "remuneration", "compensation"]):
                    job_post["detail_salary"] = text_content
                    job_post["salary_list"] = text_content.split("-") if "-" in text_content else [text_content]
                
                # Experience 
                elif any(key in header for key in ["experience", "kinh nghiệm", "years of experience"]):
                    job_post["detail_experience"] = text_content
                    job_post["exp_list"] = [text_content]
                
                # Deadline
                elif any(key in header for key in ["deadline", "hạn nộp", "apply by"]):
                    job_post["deadline"] = text_content 
    except:
        pass
    
    # Extract company details if company_url available
    if job_post["company_url"]:
        company_info = extract_company_detail(job_post["company_url"])
        job_post.update(company_info)
        
    # Giãn cách thời gian nghỉ nhỏ giữa các lần lấy chi tiết bài viết tuyển dụng
    time.sleep(random.uniform(1.5, 3.5))
    
    return job_post

def scrape_data(keyword: str, location: str, max_jobs: int = 100) -> List[Dict]:
    id_list = extract_job_ids(keyword, location, max_jobs)
    job_list = []

    # Loop through the list of job IDs and get each URL
    for i, job_id in enumerate(id_list, 1):
        print(f"[{i}/{len(id_list)}] Extracting job detail via proxy for ID: {job_id}")
        job_post = extract_job_detail(job_id)
        if job_post:
            job_list.append(job_post)
        
    return job_list
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper (Selenium)")
    parser.add_argument("--title", required=True, help="Tên công việc cần tìm, ví dụ: 'Software Engineer'")
    parser.add_argument("--location", required=True, help="Vị trí, ví dụ: 'Vietnam'")
    parser.add_argument("--out_prefix", default="output/jobs", help="Tên file output (không kèm đuôi)")
    parser.add_argument("--limit", type=int, default=100, help="Số lượng job tối đa cần crawl (mặc định: 100)")
    parser.add_argument("--no-proxy", action="store_true", help="Không sử dụng proxy")
    parser.add_argument("--proxy-file", help="Đường dẫn đến file text chứa danh sách proxy (mỗi dòng một proxy)")
    parser.add_argument("--proxy", help="Địa chỉ proxy đơn lẻ muốn dùng, ví dụ: 'http://user:pass@ip:port'")

    args = parser.parse_args()

    if args.no_proxy:
        USE_PROXY = False
        print("[INFO] Đã tắt sử dụng Proxy.")
    elif args.proxy_file:
        if os.path.exists(args.proxy_file):
            with open(args.proxy_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
            if lines:
                WEBSHARE_PROXIES = lines
                print(f"[INFO] Đã nạp {len(WEBSHARE_PROXIES)} proxies từ file: {args.proxy_file}")
            else:
                print(f"[WARN] File proxy {args.proxy_file} trống. Sử dụng danh sách mặc định.")
        else:
            print(f"[WARN] File proxy {args.proxy_file} không tồn tại. Sử dụng danh sách mặc định.")
    elif args.proxy:
        WEBSHARE_PROXIES = [args.proxy]
        print(f"[INFO] Sử dụng proxy đơn lẻ: {args.proxy}")

    print(f"[INFO] Đang tìm việc: {args.title} tại {args.location} (Giới hạn: {args.limit} jobs) ...")
    jobs = scrape_data(args.title, args.location, args.limit)

    if not jobs:
        print("[WARN] Không tìm thấy kết quả nào.")
    else:
        jobs_df = pd.DataFrame(jobs)
        os.makedirs(os.path.dirname(args.out_prefix), exist_ok=True)

        out_csv = f"{args.out_prefix}_combined.csv"
        out_xlsx = f"{args.out_prefix}_combined.xlsx"

        print(jobs_df)
        jobs_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        try:
            jobs_df.to_excel(out_xlsx, index=False)
            out_json = f"{args.out_prefix}_combined.json"
            jobs_df.to_json(out_json, orient="records", force_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] XLSX write failed: {e}")
        print(f"[OK] Saved: {out_csv}, {out_xlsx}")