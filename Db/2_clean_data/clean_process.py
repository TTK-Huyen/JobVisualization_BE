import json
import re
import unicodedata
import os
import time
import sys
import hashlib  # <--- [NEW] Thư viện tạo mã băm (Digital Fingerprint)
from datetime import datetime
from pathlib import Path

# --- CONFIG ---
# Từ khóa để phát hiện metadata (Giữ nguyên cấu hình metadata)
KEYWORDS_CONFIG = {
    "remote": ["remote", "làm việc từ xa", "hybrid", "work from home", "wfh"],
    "part_time": ["part-time", "part time", "bán thời gian", "thực tập", "intern"],
    "contract": ["contract", "hợp đồng", "freelance", "thời vụ"],
    "level": {
        "Intern": ["intern", "thực tập", "fresher", "sinh viên"],
        "Junior": ["junior", "1 năm", "1 year", "1-2 năm", "1-3 năm", "mới tốt nghiệp"],
        "Senior": ["senior", "lead", "trưởng nhóm", "quản lý", "manager", "3-5", "5+"],
        "Director": ["director", "giám đốc", "head of", "vp"]
    }
}

# --- THÊM THƯ VIỆN GOOGLE GEMINI ---
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    # Tránh lỗi encoding khi chạy từ subprocess
    try:
        print("WARNING: 'google-generativeai' not installed. Run 'pip install google-generativeai' to use AI features.")
    except:
        pass

# --- IMPORT CONSTANTS CỦA BẠN ---
try:
    import constants
    print("Found constants.py! Using standardized skills list.")
except ImportError:
    constants = None
    print("WARNING: constants.py not found. Please place this file in the same directory.")

# ==============================================================================
# CẤU HÌNH API KEY 
# ==============================================================================
GEMINI_API_KEY = "AIzaSyDvs_IL30dtSvYq3MpdMinYkVC8ZYKeli8"
if 'google.colab' in sys.modules:
    try:
        from google.colab import userdata
        GEMINI_API_KEY = userdata.get('GEMINI_API_KEY')
    except: pass
if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

class DataProcessor:
    def __init__(self):
        self.companies_map = {} 
        self.skills_map = {}
        self.industries_map = {} 
        
        self.processed_jobs = []
        self.processed_salaries = []
        self.processed_job_skills = []
        self.processed_job_benefits = [] 
        self.processed_job_industries = [] 
        
        # [NEW] Set chứa các chữ ký (fingerprints) để kiểm tra trùng lặp
        self.seen_signatures = set()
        self.duplicate_count = 0

        # Load keywords từ file constants.py của bạn
        self.skill_keywords = constants.SKILL_KEYWORDS if constants else {}
        self.job_categories = constants.JOB_CATEGORIES if constants and hasattr(constants, 'JOB_CATEGORIES') else {}
        
        # Cấu hình AI
        self.use_ai = False
        if HAS_GEMINI and GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025', 
                                              generation_config={"response_mime_type": "application/json"})
            self.use_ai = True
            self.job_buffer = [] 
            self.BATCH_SIZE = 10 
            print("AI Mode: ACTIVATED")
        else:
            print("Regex Mode: ACTIVATED")

    # --------------------------------------------------------------------------
    # HELPER FUNCTIONS (REGEX & CLEANING)
    # --------------------------------------------------------------------------
    def clean_text_regex(self, text):
        if not text: return ""
        clean = re.sub(r'<[^>]+>', ' ', str(text)) # Bỏ HTML
        clean = re.sub(r'[\r\n]+', '\n', clean)    # Chuẩn hóa xuống dòng
        return re.sub(r'\s+', ' ', clean).strip()

    def slugify(self, text):
        if not text: return ""
        text = text.lower().replace("c++", "cpp").replace("c#", "c-sharp").replace(".net", "dot-net")
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s-]', '', text)
        return re.sub(r'[-\s]+', '-', text).strip('-')

    def parse_salary_regex(self, salary_str):
        if not salary_str: return None, None, None, 'VND', 'MONTHLY'
        salary_str = salary_str.lower().replace(',', '')
        currency = 'USD' if '$' in salary_str or 'usd' in salary_str else 'VND'
        # Default pay period
        pay_period = 'MONTHLY' 
        
        multiplier = 1_000_000 if any(x in salary_str for x in ['tr', 'triệu', 'million']) else 1
        numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', salary_str)]
        
        min_s, max_s, med_s = 0, 0, 0
        
        if not numbers: return None, None, None, 'VND', 'MONTHLY'
        
        if len(numbers) == 1:
            val = numbers[0] * multiplier
            if 'up to' in salary_str or 'tới' in salary_str: max_s = val
            elif 'from' in salary_str or 'từ' in salary_str: min_s = val
            else: min_s = max_s = med_s = val
        elif len(numbers) >= 2:
            min_s = numbers[0] * multiplier
            max_s = numbers[1] * multiplier
            med_s = (min_s + max_s) / 2

        return min_s, max_s, med_s, currency, pay_period

    def extract_metadata(self, title, desc, exp_str):
        """Suy luận các trường còn thiếu từ text"""
        full_text = (title + " " + desc + " " + str(exp_str)).lower()
        
        # 1. Remote Allowed
        is_remote = any(k in full_text for k in KEYWORDS_CONFIG["remote"])
        
        # 2. Work Type
        work_type = "Full-time"
        if any(k in full_text for k in KEYWORDS_CONFIG["part_time"]):
            work_type = "Part-time"
        elif any(k in full_text for k in KEYWORDS_CONFIG["contract"]):
            work_type = "Contract"
            
        # 3. Experience Level
        level = "Associate" # Default
        for lvl_name, keys in KEYWORDS_CONFIG["level"].items():
            if any(k in full_text for k in keys):
                level = lvl_name
                break
                
        return is_remote, work_type, level

    def extract_benefits_list(self, benefit_text):
        """Tách chuỗi benefits thành list"""
        if not benefit_text: return []
        # Tách dựa trên các ký tự đầu dòng phổ biến hoặc dấu phẩy/chấm phẩy
        splitters = r'[\n•\-\+;]|\s{2,}'
        raw_items = re.split(splitters, benefit_text)
        return [item.strip() for item in raw_items if len(item.strip()) > 3]
    
    def extract_category_regex(self, title):
        """Phân loại job dựa trên title và dictionary trong constants.py"""
        if not self.job_categories or not title:
            return "Other"
            
        title_lower = title.lower()
        for category, keywords in self.job_categories.items():
            for kw in keywords:
                # Kiểm tra keyword có trong title không (đơn giản)
                if kw.lower() in title_lower:
                    return category
        return "Other"

    def extract_skills_regex(self, full_text):
        """Quét text để tìm skills dựa trên constants.SKILL_KEYWORDS"""
        found_skills = set()
        text_lower = full_text.lower()
        
        if not self.skill_keywords:
            return []

        for category, skills in self.skill_keywords.items():
            for skill in skills:
                # Dùng regex \b để tìm chính xác từ (tránh tìm 'java' trong 'javascript')
                pattern = r'\b' + re.escape(skill.lower()) + r'\b'
                
                # Xử lý ngoại lệ cho C++, C#, .NET
                if skill.lower() in ['c++', 'c#', '.net']:
                    if skill.lower() in text_lower:
                        found_skills.add((skill, category))
                else:
                    if re.search(pattern, text_lower):
                        found_skills.add((skill, category))
        
        return list(found_skills)

    def process_industry(self, job_temp_id, industry_str):
        """Xử lý ngành nghề"""
        if not industry_str: return
        # Tách nhiều ngành nghề (VD: "IT Software; Education")
        inds = [i.strip() for i in re.split(r'[;,]', industry_str) if i.strip()]
        
        for ind_name in inds:
            slug = self.slugify(ind_name)
            if slug not in self.industries_map:
                self.industries_map[slug] = {
                    "temp_id": len(self.industries_map) + 1,
                    "industry_name": ind_name
                }
            
            # Link Job -> Industry
            self.processed_job_industries.append({
                "job_temp_id": job_temp_id,
                "industry_temp_id": self.industries_map[slug]["temp_id"]
            })

    # --------------------------------------------------------------------------
    # AI LOGIC
    # --------------------------------------------------------------------------
    def process_batch_with_gemini(self):
        if not self.job_buffer: return

        # Tạo danh sách skill và category gợi ý để AI tham khảo
        skills_context = ""
        category_context = ""
        if self.skill_keywords:
            skills_context = "STANDARD SKILLS LIST: " + json.dumps(self.skill_keywords)
        if self.job_categories:
            category_context = "STANDARD JOB CATEGORIES: " + json.dumps(list(self.job_categories.keys()))

        prompt = f"""
        You are a Tech HR Expert. Analyze job data to normalize & extract info.
        
        {skills_context}
        {category_context}
        
        INSTRUCTIONS:
        1. **SKILLS:** Extract specific TECH SKILLS from the 'requirements'. Map them to the STANDARD SKILLS LIST keys (e.g., 'aws') if applicable.
        2. **CATEGORY:** Classify the job into ONE of the STANDARD JOB CATEGORIES based on the Title and Description. If none fit, use "Other".
        3. **CLEANING:** Clean Salary, Experience Level, Work Type, Remote status, and Benefits list.

        INPUT JSON: {{raw_data}}
        
        OUTPUT JSON SCHEMA (Array):
        [
            {{
                "original_id": 1,
                "clean_title": "AI Engineer",
                "job_category": "Data/AI", 
                "min_salary": 1000, "max_salary": 2000, "currency": "USD",
                "extracted_skills": ["python", "aws", "tensorflow", "agile"], 
                "benefits_list": ["Macbook Pro", "Health Insurance"],
                "experience_level": "Senior",
                "work_type": "Full-time",
                "is_remote": true
            }}
        ]
        """
        mini_batch = []
        for j in self.job_buffer:
            # Ưu tiên lấy desc_yeucau (requirements) để phân tích skills
            req_text = j.get('requirements', '')
            desc_text = j.get('description', '')
            
            # Nếu requirements quá ngắn, gộp thêm description
            analyze_text = req_text if len(req_text) > 50 else (req_text + "\n" + desc_text)

            mini_batch.append({
                "original_id": j['temp_id'],
                "title": j['title'],
                "salary_str": j.get('raw_salary', ''),
                "requirements": analyze_text[:1500], # Cắt ngắn để tiết kiệm token
                "benefits_str": j.get('raw_benefits', '')
            })
            
        try:
            response = self.model.generate_content(prompt.replace("{raw_data}", json.dumps(mini_batch)))
            ai_results = json.loads(response.text)
            result_map = {item['original_id']: item for item in ai_results}
            
            for job in self.processed_jobs:
                if job['temp_id'] in result_map:
                    res = result_map[job['temp_id']]
                    
                    # Update fields
                    job['title'] = res.get('clean_title', job['title'])
                    job['job_category'] = res.get('job_category', job['job_category']) # Cập nhật Category từ AI
                    job['formatted_experience_level'] = res.get('experience_level', job['formatted_experience_level'])
                    job['formatted_work_type'] = res.get('work_type', job['formatted_work_type'])
                    job['remote_allowed'] = res.get('is_remote', job['remote_allowed'])
                    
                    # Salary Update
                    if res.get('min_salary') or res.get('max_salary'):
                        # Remove regex salary if exists
                        self.processed_salaries = [s for s in self.processed_salaries if s['job_temp_id'] != job['temp_id']]
                        self.processed_salaries.append({
                            "job_temp_id": job['temp_id'],
                            "min_salary": res.get('min_salary'),
                            "max_salary": res.get('max_salary'),
                            "med_salary": (res.get('min_salary',0) + res.get('max_salary',0))/2 if res.get('max_salary') else res.get('min_salary'),
                            "currency": res.get('currency', 'VND'),
                            "pay_period": "MONTHLY"
                        })

                    # Benefits List Update
                    if res.get('benefits_list'):
                        self.processed_job_benefits = [b for b in self.processed_job_benefits if b['job_temp_id'] != job['temp_id']]
                        for ben in res.get('benefits_list'):
                            self.processed_job_benefits.append({
                                "job_temp_id": job['temp_id'],
                                "benefit_name": ben,
                                "is_inferred": True
                            })
                    
                    # --- AI SKILL EXTRACTION & MAPPING ---
                    if res.get('extracted_skills'):
                        ai_skills = res.get('extracted_skills', [])
                        existing_skill_ids = {s['skill_temp_id'] for s in self.processed_job_skills if s['job_temp_id'] == job['temp_id']}
                        
                        for skill_name in ai_skills:
                            slug = self.slugify(skill_name)
                            if slug not in self.skills_map:
                                self.skills_map[slug] = {
                                    "temp_id": len(self.skills_map) + 1,
                                    "skill_name": skill_name, 
                                    "skill_abr": slug,
                                    "category": "AI_Extracted" 
                                }
                            skill_id = self.skills_map[slug]["temp_id"]
                            if skill_id not in existing_skill_ids:
                                self.processed_job_skills.append({
                                    "job_temp_id": job['temp_id'],
                                    "skill_temp_id": skill_id
                                })
                                existing_skill_ids.add(skill_id)

            print(f"   ✨ AI cleaned batch of {len(mini_batch)} jobs.")
            time.sleep(1) 

        except Exception as e:
            print(f"   ❌ AI Fail: {e}. Keeping Regex values.")
            pass

        self.job_buffer = []

    # --------------------------------------------------------------------------
    # MAIN PROCESSING
    # --------------------------------------------------------------------------
    def process_file(self, file_path: Path):
        print(f"Reading: {file_path.name}") 
        try:
            content = file_path.read_text(encoding='utf-8')
            data = json.loads(content)
            if isinstance(data, dict): data = [data]
            
            for raw_job in data:
                self.transform_job(raw_job)
            
            if self.use_ai and len(self.job_buffer) >= self.BATCH_SIZE:
                self.process_batch_with_gemini()
                
        except Exception as e:
            print(f"❌ Error {file_path.name}: {e}")

    def transform_job(self, raw_job):
        title_raw = raw_job.get('title', '')
        if not title_raw: return
        
        # --- CLEAN TEXT FIRST FOR HASHING ---
        # Chúng ta cần làm sạch sơ bộ để Hash chính xác (loại bỏ khoảng trắng thừa, html)
        company_raw = raw_job.get('company_name_full') or raw_job.get('company', 'Unknown')
        clean_desc_for_hash = self.clean_text_regex(raw_job.get('desc_mota', ''))
        
        # --- [IMPROVED] DUPLICATION CHECK (MD5 CONTENT HASH) ---
        # Thay vì chỉ dựa vào Title + Company (dễ trùng nếu tuyển nhiều vị trí giống tên)
        # Chúng ta dùng thêm Nội dung mô tả (Description) để tạo Fingerprint.
        
        # Tạo chuỗi duy nhất: Tên công ty + Tiêu đề + 200 ký tự đầu của mô tả (hoặc toàn bộ)
        # Việc thêm mô tả giúp phân biệt các job cùng tên nhưng khác nội dung chi tiết.
        signature_source = f"{self.slugify(company_raw)}_{self.slugify(title_raw)}_{clean_desc_for_hash}"
        
        # Tạo mã băm MD5 (nhanh và ngắn gọn)
        job_hash = hashlib.md5(signature_source.encode('utf-8')).hexdigest()
        
        if job_hash in self.seen_signatures:
            self.duplicate_count += 1
            # Bỏ qua job này, không xử lý tiếp
            return
            
        self.seen_signatures.add(job_hash)
        # ---------------------------------------------

        # Tiếp tục xử lý các trường còn lại
        clean_req = self.clean_text_regex(raw_job.get('desc_yeucau', ''))
        clean_ben = self.clean_text_regex(raw_job.get('desc_quyenloi', ''))
        
        # --- 1. Company ---
        company_name = self.clean_text_regex(company_raw) # Đã lấy ở trên
        if company_name not in self.companies_map:
            self.companies_map[company_name] = {
                "temp_id": len(self.companies_map) + 1,
                "name": company_name,
                "website": raw_job.get('company_website', ''),
                "size": raw_job.get('company_size', ''),
                "address": raw_job.get('company_address', ''),
                "industry_raw": raw_job.get('company_industry', '')
            }
        
        comp_obj = self.companies_map[company_name]
        
        # --- 2. Metadata Inference ---
        is_remote, work_type, level = self.extract_metadata(title_raw, clean_desc_for_hash, raw_job.get('exp_list'))
        
        # [NEW] Phân loại Job Category bằng Regex
        job_category = self.extract_category_regex(title_raw)
        
        # --- 3. Job Object (Full Fields) ---
        job_temp_id = len(self.processed_jobs) + 1
        job_obj = {
            "temp_id": job_temp_id,
            "company_temp_id": comp_obj["temp_id"],
            "title": title_raw,
            "job_category": job_category, 
            "fingerprint": job_hash, # <--- [NEW] Thêm trường fingerprint vào output để lưu DB
            "job_url": raw_job.get('job_url', ''),
            "description": clean_desc_for_hash,
            "requirements": clean_req,
            "benefits_raw": clean_ben, 
            "formatted_work_type": work_type,
            "formatted_experience_level": level,
            "remote_allowed": is_remote,
            "views": 0,
            "applies": 0,
            "posted_date": datetime.now().strftime("%Y-%m-%d"),
        }
        self.processed_jobs.append(job_obj)

        # --- 4. Salaries ---
        min_s, max_s, med_s, curr, period = self.parse_salary_regex(raw_job.get('salary_list') or raw_job.get('detail_salary'))
        if min_s or max_s:
            self.processed_salaries.append({
                "job_temp_id": job_temp_id,
                "min_salary": min_s, "max_salary": max_s, "med_salary": med_s,
                "currency": curr, "pay_period": period
            })

        # --- 5. Benefits List ---
        ben_list = self.extract_benefits_list(clean_ben)
        for ben in ben_list:
            self.processed_job_benefits.append({
                "job_temp_id": job_temp_id,
                "benefit_name": ben,
                "is_inferred": False
            })

        # --- 6. Skills ---
        full_text = f"{title_raw} {clean_desc_for_hash} {clean_req} {raw_job.get('tags', '')}"
        extracted = self.extract_skills_regex(full_text)
        
        if raw_job.get('tags'):
             extracted.extend([(t.strip(), 'Other') for t in raw_job.get('tags').split(';') if t.strip()])

        for name, cat in extracted:
            slug = self.slugify(name)
            if slug not in self.skills_map:
                self.skills_map[slug] = {
                    "temp_id": len(self.skills_map) + 1,
                    "skill_name": name, 
                    "skill_abr": slug, 
                    "category": cat
                }
            self.processed_job_skills.append({
                "job_temp_id": job_temp_id,
                "skill_temp_id": self.skills_map[slug]["temp_id"]
            })
        
        # --- 7. Industries ---
        self.process_industry(job_temp_id, comp_obj.get('industry_raw'))
        
        # Add to AI Buffer
        if self.use_ai:
            self.job_buffer.append({
                "temp_id": job_temp_id,
                "title": title_raw,
                "description": clean_desc_for_hash,
                "requirements": clean_req,
                "raw_salary": raw_job.get('salary_list') or raw_job.get('detail_salary'),
                "raw_exp": raw_job.get('exp_list'),
                "raw_benefits": clean_ben
            })

    def export_data(self, output_file='clean_data_full.json'):
        if self.use_ai and self.job_buffer:
            self.process_batch_with_gemini()

        final_data = {
            "metadata": {
                "total_jobs": len(self.processed_jobs), 
                "timestamp": str(datetime.now()),
                "duplicates_removed": self.duplicate_count  # Thống kê số lượng bị trùng
            },
            "companies": list(self.companies_map.values()),
            "skills_master": list(self.skills_map.values()),
            "industries": list(self.industries_map.values()),
            "jobs": self.processed_jobs,
            "salaries": self.processed_salaries,
            "job_benefits": self.processed_job_benefits,
            "job_industries": self.processed_job_industries,
            "job_skills": self.processed_job_skills 
        }
        Path(output_file).write_text(json.dumps(final_data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\nSUCCESS: Data Exported to {output_file} | Jobs: {len(self.processed_jobs)} | Duplicates Removed: {self.duplicate_count}")

# --- MAIN ---
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean job data from crawl output')
    parser.add_argument('--input', type=str, help='Input JSON file path')
    parser.add_argument('--output', type=str, help='Output JSON file path')
    args = parser.parse_args()
    
    processor = DataProcessor()
    
    current_dir = Path(__file__).parent
    ignore_patterns = ['package.json', 'package-lock.json', 'clean_data']
    
    # Nếu có --input argument, dùng nó; nếu không, search trong folder
    if args.input:
        input_file = Path(args.input)
        if input_file.exists():
            processor.process_file(input_file)
        else:
            print(f"❌ Input file không tồn tại: {input_file}")
            sys.exit(1)
    else:
        combined_file = current_dir / 'jobs_combined.json'
        if combined_file.exists():
            processor.process_file(combined_file)
        else:
            print("🔍 Scanning folder recursively...")
            json_files = list(current_dir.rglob("*.json"))
            for f in json_files:
                if not any(ig in f.name for ig in ignore_patterns):
                    processor.process_file(f)
    
    # Nếu có --output argument, dùng nó; nếu không dùng mặc định
    output_file = args.output if args.output else 'clean_data_final.json'
    processor.export_data(output_file)