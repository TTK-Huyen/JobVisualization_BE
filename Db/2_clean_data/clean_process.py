import json
import re
import unicodedata
import os
import time
import sys
import hashlib  # <--- [NEW] Thư viện tạo mã băm (Digital Fingerprint)
from datetime import datetime
from pathlib import Path

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

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
# CẤU HÌNH API KEYS (Hỗ trợ multiple keys và fallback)
# ==============================================================================
# ==============================================================================
# CẤU HÌNH API KEYS & MODEL (Hỗ trợ multiple keys và fallback)
# ==============================================================================
def load_env_config():
    """Load configuration từ .env file"""
    config = {
        "api_keys": [],
        "model": "gemini-2.5-flash-preview-09-2025"
    }
    
    # Try load from .env file first
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY_"):
                        key = line.split('=', 1)[1].strip()
                        if key and not key.startswith("your_"):
                            config["api_keys"].append(key)
                    elif line.startswith("GEMINI_MODEL="):
                        model = line.split('=', 1)[1].strip()
                        if model:
                            config["model"] = model
        except Exception as e:
            print(f"⚠️  Warning: Could not read .env file: {e}")
    
    # Fallback to environment variables
    if not config["api_keys"]:
        env_key = os.environ.get("GEMINI_API_KEY", "")
        if env_key:
            config["api_keys"].append(env_key)
    
    # Allow environment variable to override model
    env_model = os.environ.get("GEMINI_MODEL", "")
    if env_model:
        config["model"] = env_model
    
    return config

CONFIG = load_env_config()
API_KEYS = CONFIG["api_keys"]
GEMINI_MODEL = CONFIG["model"]
CURRENT_KEY_INDEX = 0

print(f"🔧 Configuration loaded:")
print(f"   Model: {GEMINI_MODEL}")
print(f"   API Keys: {len(API_KEYS)} key(s) available")

def get_current_api_key():
    """Get current API key to use"""
    global CURRENT_KEY_INDEX
    if not API_KEYS:
        return ""
    if CURRENT_KEY_INDEX >= len(API_KEYS):
        CURRENT_KEY_INDEX = 0
    return API_KEYS[CURRENT_KEY_INDEX]

def switch_to_next_api_key():
    """Fallback to next API key when current one is exhausted"""
    global CURRENT_KEY_INDEX
    CURRENT_KEY_INDEX += 1
    if CURRENT_KEY_INDEX >= len(API_KEYS):
        print(f"❌ All {len(API_KEYS)} API keys exhausted!")
        CURRENT_KEY_INDEX = 0
        return False
    
    next_key = get_current_api_key()
    print(f"🔄 Switching to API key #{CURRENT_KEY_INDEX + 1}")
    return True

GEMINI_API_KEY = get_current_api_key()

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
        
        # Token usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.api_calls_count = 0

        # Load keywords từ file constants.py của bạn
        self.skill_keywords = constants.SKILL_KEYWORDS if constants else {}
        self.job_categories = constants.JOB_CATEGORIES if constants and hasattr(constants, 'JOB_CATEGORIES') else {}
        self.benefits_keywords = constants.BENEFITS_KEYWORDS if constants and hasattr(constants, 'BENEFITS_KEYWORDS') else {}
        self.vn_to_en_benefits = constants.VIETNAMESE_TO_ENGLISH_BENEFITS if constants and hasattr(constants, 'VIETNAMESE_TO_ENGLISH_BENEFITS') else {}
        
        # Flatten all skills list từ constants để dùng cho validation
        self.ALL_SKILLS = [skill for group in self.skill_keywords.values() for skill in group] if self.skill_keywords else []
        
        # [NEW] Valid categories từ constants - strict validation
        self.VALID_CATEGORIES = set(self.job_categories.keys()) if self.job_categories else set()
        if "Other" in self.VALID_CATEGORIES:
            self.VALID_CATEGORIES.discard("Other")  # Remove "Other" - chỉ dùng khi thực sự cần
        
        print(f"📋 Valid job categories from constants: {sorted(self.VALID_CATEGORIES)}")
        
        # Cấu hình AI
        self.use_ai = False
        self.current_api_key = GEMINI_API_KEY
        
        if HAS_GEMINI and API_KEYS:
            try:
                genai.configure(api_key=self.current_api_key)
                self.model = genai.GenerativeModel(GEMINI_MODEL, 
                                                  generation_config={"response_mime_type": "application/json"})
                self.use_ai = True
                self.job_buffer = [] 
                self.BATCH_SIZE = 10 
                print(f"✅ AI Mode: ACTIVATED")
                print(f"   Model: {GEMINI_MODEL}")
                print(f"   API Keys: #{CURRENT_KEY_INDEX + 1}/{len(API_KEYS)}")
            except Exception as e:
                print(f"❌ AI initialization failed: {e}")
                print("Falling back to Regex Mode")
        else:
            if not HAS_GEMINI:
                print("⚠️  google-generativeai not installed")
            elif not API_KEYS:
                print("⚠️  No Gemini API keys found in .env")
            print("📋 Regex Mode: ACTIVATED")

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
        """Tách chuỗi benefits thành list và chuẩn hóa theo BENEFITS_KEYWORDS
        Ưu tiên map Vietnamese -> English canonical forms
        CHỈ CHẤP NHẬN benefits có trong danh sách constants, không bổ sung thêm
        """
        if not benefit_text: return []
        
        # Tách dựa trên các ký tự đầu dòng phổ biến hoặc dấu phẩy/chấm phẩy
        splitters = r'[\n•\-\+;]|\s{2,}'
        raw_items = re.split(splitters, benefit_text)
        clean_items = [item.strip().lower() for item in raw_items if len(item.strip()) > 3]
        
        # Chuẩn hóa benefits theo keywords (so khớp theo từ/cụm, tránh match bên trong "laptop" -> "pto")
        normalized_benefits = []
        for item in clean_items:
            matched = False
            
            # Step 1: Check Vietnamese-to-English mapping first
            if self.vn_to_en_benefits:
                for vn_keyword, en_canonical in self.vn_to_en_benefits.items():
                    pattern = r"\b" + re.escape(vn_keyword.lower()) + r"\b"
                    if re.search(pattern, item):
                        normalized_benefits.append(en_canonical)
                        matched = True
                        break
            
            # Step 2: Check English benefits keywords
            if not matched and self.benefits_keywords:
                for category, keywords in self.benefits_keywords.items():
                    for keyword in keywords:
                        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
                        if re.search(pattern, item):
                            normalized_benefits.append(keyword)
                            matched = True
                            break
                    if matched:
                        break

            # Step 3: Nếu không match -> BỎ QUA (không giữ lại)
            # Chỉ chấp nhận benefits có trong constants.BENEFITS_KEYWORDS

        return list(set(normalized_benefits))  # Loại bỏ duplicate

    def normalize_benefit_items(self, items):
        """Chuẩn hóa list benefits (đầu vào là list đã tách) theo BENEFITS_KEYWORDS
        Ưu tiên map Vietnamese -> English canonical forms
        """
        if not items: return []
        normalized = []
        for raw in items:
            item = str(raw).strip().lower()
            if not item:
                continue
            matched = False
            
            # Step 1: Check Vietnamese-to-English mapping first
            if self.vn_to_en_benefits:
                for vn_keyword, en_canonical in self.vn_to_en_benefits.items():
                    pattern = r"\b" + re.escape(vn_keyword.lower()) + r"\b"
                    if re.search(pattern, item):
                        normalized.append(en_canonical)
                        matched = True
                        break
            
            # Step 2: Check English benefits keywords
            if not matched and self.benefits_keywords:
                for category, keywords in self.benefits_keywords.items():
                    for keyword in keywords:
                        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
                        if re.search(pattern, item):
                            normalized.append(keyword)
                            matched = True
                            break
                    if matched:
                        break
            
            # Step 3: If no match, keep original (truncated)
            if not matched:
                normalized.append(item[:100])
        
        return list(set(normalized))
    
    def validate_category(self, category):
        """
        [NEW] Strict validation - chỉ chấp nhận categories từ constants
        Nếu category không hợp lệ, trả về None để reprocess
        """
        if category in self.VALID_CATEGORIES:
            return category
        
        # "Other" chỉ được phép nếu thực sự không match
        if category == "Other" and "Other" in self.job_categories:
            return "Other"
        
        # Invalid category - trả về None
        return None
    
    def extract_category_regex(self, title, description="", requirements=""):
        """
        Phân loại job dựa trên title, description, requirements
        Sử dụng keyword matching với fallback thông minh
        """
        if not self.job_categories or not title:
            return "Other"
        
        title_lower = title.lower()
        full_text = f"{title} {description} {requirements}".lower()
        
        # Bản đồ keyword thêm để phát hiện category
        category_keywords_map = {
            "Software/Web/Mobile": [
                "engineer", "developer", "programmer", "backend", "frontend", "full stack",
                "web", "mobile", "android", "ios", "react", "vue", "angular", "spring",
                "nodejs", "python dev", "java dev", "php dev", "golang", "ruby", ".net",
                "qa", "test", "tester", "automation", "tech lead", "principal", "architect",
                "video editor", "graphics", "ux", "ui designer", "game", "unity", "unreal"
            ],
            "Data/AI": [
                "data analyst", "analyst", "data engineer", "bi ", "business intelligence",
                "data scientist", "scientist", "machine learning", "ml ", "ai ", "ai engineer",
                "nlp", "computer vision", "deep learning", "neural", "tensorflow", "pytorch",
                "mlops", "applied scientist", "abap", "sap", "statistics", "bigdata"
            ],
            "DevOps/Cloud/Infra": [
                "devops", "sre", "site reliability", "cloud", "aws", "azure", "gcp",
                "kubernetes", "docker", "terraform", "infrastructure", "platform engineer",
                "system admin", "linux", "network", "database admin", "dba", "system engineer"
            ],
            "Security": [
                "security", "cybersecurity", "soc", "penetration", "pentest", "hacker",
                "devsecops", "iam", "compliance", "incident", "audit"
            ],
            "Product/Design": [
                "product manager", "product owner", "scrum master", "designer", "ux", "ui",
                "product designer", "design", "sales", "manager", "director", "supervisor"
            ]
        }
        
        # Điểm số cho mỗi category
        category_scores = {cat: 0 for cat in self.job_categories.keys()}
        
        # Tính điểm dựa trên keyword matching
        for category, keywords in category_keywords_map.items():
            for kw in keywords:
                # Kiểm tra trong title (điểm cao hơn)
                if kw.lower() in title_lower:
                    category_scores[category] += 3
                # Kiểm tra trong full text
                elif kw.lower() in full_text:
                    category_scores[category] += 1
        
        # Cũng kiểm tra chính xác từ constant keywords
        for category, keywords in self.job_categories.items():
            if not keywords:  # Skip empty categories like "Other"
                continue
            for kw in keywords:
                if kw.lower() in title_lower:
                    category_scores[category] += 5  # Ưu tiên cao nhất
        
        # Tìm category có điểm cao nhất
        best_category = max(category_scores, key=category_scores.get)
        best_score = category_scores[best_category]
        
        # Nếu có match với score > 0, return nó
        if best_score > 0:
            return best_category
        
        # Nếu không có match nào, kiểm tra từ tiếp theo
        # VD: "Technical Manager" → check "Manager" → "Product/Design"
        if best_score == 0:
            # Thử tìm từ cuối cùng trong title
            words = title_lower.split()
            for word in reversed(words):
                if len(word) > 3:  # Bỏ qua từ quá ngắn
                    for category, keywords in self.job_categories.items():
                        if keywords and any(word in kw.lower() for kw in keywords):
                            return category
        
        # Last resort: nếu có từ "engineer", "developer", "specialist" → Software
        if any(word in title_lower for word in ["engineer", "developer", "programmer", "specialist"]):
            return "Software/Web/Mobile"
        
        # Fallback: "Other" chỉ khi thực sự không match
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

        # Tạo danh sách skill, category, benefit gợi ý để AI tham khảo
        skills_context = ""
        category_context = ""
        benefits_context = ""
        if self.skill_keywords:
            skills_context = "STANDARD SKILLS LIST: " + json.dumps(self.skill_keywords)
        if self.job_categories:
            category_context = "STANDARD JOB CATEGORIES: " + json.dumps(list(self.job_categories.keys()))
        if self.benefits_keywords:
            flat_benefits = sorted({kw for kws in self.benefits_keywords.values() for kw in kws})
            benefits_context = "STANDARD BENEFITS KEYWORDS: " + json.dumps(flat_benefits)

        prompt = f"""
        You are a Tech HR Expert. Analyze job data to normalize & extract info.
        
        {skills_context}
        {category_context}
        {benefits_context}
        
        INSTRUCTIONS:
        1. **SKILLS:** Extract specific TECH SKILLS from the 'requirements'. Map them to the STANDARD SKILLS LIST keys (e.g., 'aws') if applicable.
        2. **CATEGORY:** Classify the job into ONE of the STANDARD JOB CATEGORIES based on the Title and Description. If none fit, use "Other".
        3. **CLEANING:** Clean Salary, Experience Level, Work Type, Remote status.
        4. **BENEFITS NORMALIZATION (CRITICAL):**
           - Extract ALL benefits from 'requirements' and 'benefits_str' fields
           - Map EACH benefit to the closest match in STANDARD BENEFITS KEYWORDS (exact match preferred)
           - If a benefit phrase contains multiple standard benefits, split them into separate items
           - For Vietnamese benefits, translate to English and map to standard keywords
           - Only output benefits that exist in the STANDARD BENEFITS KEYWORDS list
           - Examples:
             * "chế độ bảo hiểm" → "health insurance"
             * "13th month salary + performance bonus" → ["13th month salary", "performance bonus"]
             * "laptop, health insurance, training" → ["company laptop", "health insurance", "training budget"]
           - DO NOT output: fragments, metadata, or non-benefit text
           - DO NOT keep original text if it doesn't match standard benefits

        INPUT JSON: {{raw_data}}
        
        OUTPUT JSON SCHEMA (Array):
        [
            {{
                "original_id": 1,
                "clean_title": "AI Engineer",
                "job_category": "Data/AI", 
                "min_salary": 1000, "max_salary": 2000, "currency": "USD",
                "extracted_skills": ["python", "aws", "tensorflow", "agile"], 
                "benefits_list": ["health insurance", "13th month salary", "company laptop", "training budget"],
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
            ben_text = j.get('raw_benefits', '')
            
            # Nếu requirements quá ngắn, gộp thêm description
            analyze_text = req_text if len(req_text) > 50 else (req_text + "\n" + desc_text)

            mini_batch.append({
                "original_id": j['temp_id'],
                "title": j['title'],
                "salary_str": j.get('raw_salary', ''),
                "requirements": analyze_text[:1500], # Cắt ngắn để tiết kiệm token
                "benefits_str": ben_text[:800],  # Thêm benefits để AI phân tích
                "description_snippet": desc_text[:500]  # Thêm snippet description để AI có context
            })
            
        try:
            response = self.model.generate_content(prompt.replace("{raw_data}", json.dumps(mini_batch)))
            
            # Track token usage
            if hasattr(response, 'usage_metadata'):
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                self.total_input_tokens += input_tokens
                self.total_output_tokens += output_tokens
                self.api_calls_count += 1
                print(f"   📊 Tokens: Input={input_tokens}, Output={output_tokens}, Total={input_tokens + output_tokens}")
            
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
                        min_salary = res.get('min_salary') if res.get('min_salary') is not None else 0
                        max_salary = res.get('max_salary') if res.get('max_salary') is not None else 0
                        med_salary = (min_salary + max_salary) / 2 if max_salary else min_salary
                        self.processed_salaries.append({
                            "job_temp_id": job['temp_id'],
                            "min_salary": min_salary,
                            "max_salary": max_salary,
                            "med_salary": med_salary,
                            "currency": res.get('currency', 'VND'),
                            "pay_period": "MONTHLY"
                        })

                    # Benefits List Update
                    if res.get('benefits_list'):
                        normalized_benefits = self.normalize_benefit_items(res.get('benefits_list'))
                        if normalized_benefits:
                            self.processed_job_benefits = [b for b in self.processed_job_benefits if b['job_temp_id'] != job['temp_id']]
                            for ben in normalized_benefits:
                                self.processed_job_benefits.append({
                                    "job_temp_id": job['temp_id'],
                                    "benefit_name": ben,
                                    "is_inferred": True
                                })
                    
                    # --- AI SKILL EXTRACTION & MAPPING ---
                    if res.get('extracted_skills'):
                        ai_skills = res.get('extracted_skills', [])
                        existing_skill_ids = {s['skill_temp_id'] for s in self.processed_job_skills if s['job_temp_id'] == job['temp_id']}
                        
                        # CHỈ CHẤP NHẬN skills có trong SKILL_KEYWORDS từ constants
                        # Lọc ra những skills không hợp lệ - BỎ QUA hoàn toàn
                        valid_skills = []
                        for skill_name in ai_skills:
                            # Kiểm tra xem skill có trong ALL_SKILLS (từ constants) hay không
                            if skill_name.lower() in [s.lower() for s in self.ALL_SKILLS]:
                                valid_skills.append(skill_name)
                            # else: Bỏ qua skill không hợp lệ, không thêm vào database
                        
                        for skill_name in valid_skills:
                            slug = self.slugify(skill_name)
                            if slug not in self.skills_map:
                                self.skills_map[slug] = {
                                    "temp_id": len(self.skills_map) + 1,
                                    "skill_name": skill_name, 
                                    "category": "Methodology"  # Dùng category hợp lệ từ constants
                                }
                            skill_id = self.skills_map[slug]["temp_id"]
                            if skill_id not in existing_skill_ids:
                                self.processed_job_skills.append({
                                    "job_temp_id": job['temp_id'],
                                    "skill_temp_id": skill_id,
                                    "is_inferred": True
                                })
                                existing_skill_ids.add(skill_id)

            print(f"   ✨ AI cleaned batch of {len(mini_batch)} jobs.")
            time.sleep(1) 

        except Exception as e:
            error_msg = str(e)
            
            # Check if quota exceeded error
            if "quota" in error_msg.lower() or "rate_limit" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                print(f"   ⚠️  Current API key quota exceeded: {e}")
                
                # Try to switch to next API key
                if switch_to_next_api_key():
                    print(f"   🔄 Retrying with new API key...")
                    try:
                        genai.configure(api_key=API_KEYS[CURRENT_KEY_INDEX])
                        self.model = genai.GenerativeModel(GEMINI_MODEL, 
                                                          generation_config={"response_mime_type": "application/json"})
                        # Retry the batch
                        response = self.model.generate_content(prompt.replace("{raw_data}", json.dumps(mini_batch)))
                        ai_results = json.loads(response.text)
                        result_map = {item['original_id']: item for item in ai_results}
                        print(f"   ✅ Retry successful with new API key!")
                        # Continue processing...
                    except Exception as retry_error:
                        print(f"   ❌ Retry also failed: {retry_error}. Keeping Regex values.")
                else:
                    print(f"   ❌ No more API keys available. Keeping Regex values.")
            else:
                print(f"   ❌ AI Error: {e}. Keeping Regex values.")

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
            try:
                print(f"❌ Error {file_path.name}: {e}")
            except UnicodeEncodeError:
                print(f"Error processing {file_path.name}: {str(e)}")

    def transform_job(self, raw_job):
        title_raw = raw_job.get('title', '')
        if not title_raw: return
        
        # === PHASE 1: CLEAN & NORMALIZE (strip HTML, unify fields, fingerprint) ===
        # Map fields từ các scrapers khác nhau
        company_raw = (raw_job.get('company_name') or 
                      raw_job.get('company_name_full') or 
                      raw_job.get('company', 'Unknown'))
        
        # Description có thể từ nhiều nguồn -> remove HTML tags
        desc_html = (raw_job.get('description_html') or 
                    raw_job.get('desc_mota') or 
                    raw_job.get('description', ''))
        clean_desc = self.clean_text_regex(desc_html)
        
        # Requirements
        req_text = (raw_job.get('requirements_text') or 
                   raw_job.get('desc_yeucau') or 
                   raw_job.get('requirements', ''))
        clean_req = self.clean_text_regex(req_text)
        if not clean_req and clean_desc:
            clean_req = clean_desc  # fallback khi crawler không có requirements riêng
        
        # Benefits
        ben_text = ''
        if raw_job.get('benefits'):
            if isinstance(raw_job['benefits'], list):
                ben_text = ' '.join(raw_job['benefits'])
            else:
                ben_text = str(raw_job['benefits'])
        if not ben_text:
            ben_text = raw_job.get('desc_quyenloi', '')
        clean_ben = self.clean_text_regex(ben_text)
        
        # --- [IMPROVED] DUPLICATION CHECK (MD5 CONTENT HASH) ---
        # Thay vì chỉ dựa vào Title + Company (dễ trùng nếu tuyển nhiều vị trí giống tên)
        # Chúng ta dùng thêm Nội dung mô tả (Description) để tạo Fingerprint.
        
        # Tạo chuỗi duy nhất: Tên công ty + Tiêu đề + mô tả
        signature_source = f"{self.slugify(company_raw)}_{self.slugify(title_raw)}_{clean_desc[:500]}"
        
        # Tạo mã băm MD5 (nhanh và ngắn gọn)
        job_hash = hashlib.md5(signature_source.encode('utf-8')).hexdigest()
        
        if job_hash in self.seen_signatures:
            self.duplicate_count += 1
            # Bỏ qua job này, không xử lý tiếp
            return
            
        self.seen_signatures.add(job_hash)
        # ---------------------------------------------

        # --- 1. Company ---
        company_name = self.clean_text_regex(company_raw)
        if company_name not in self.companies_map:
            self.companies_map[company_name] = {
                "temp_id": len(self.companies_map) + 1,
                "name": company_name,
                "website": raw_job.get('company_website', ''),
                "size": raw_job.get('company_size_raw') or raw_job.get('company_size', ''),
                "address": raw_job.get('company_address', ''),
                "industry_raw": raw_job.get('company_industry', ''),
                # [NEW] Preserve source ID
                "source_id": raw_job.get('company_source_id', '')
            }
        
        comp_obj = self.companies_map[company_name]
        
        # --- 2. Metadata Inference ---
        exp_raw = raw_job.get('experience_raw') or raw_job.get('exp_list', '')
        is_remote, work_type, level = self.extract_metadata(title_raw, clean_desc, exp_raw)
        
        # [NEW] Phân loại Job Category bằng Regex + Smart matching
        job_category = self.extract_category_regex(title_raw, clean_desc, clean_req)
        
        # [NEW] Validate category - chỉ chấp nhận categories từ constants
        validated_category = self.validate_category(job_category)
        if validated_category is None:
            # Invalid category - force reassign with smarter logic
            print(f"⚠️  Invalid category '{job_category}' for '{title_raw[:50]}' - reassigning...")
            # Reassign: mặc định là Software/Web/Mobile nếu có từ "engineer"/"developer"
            if any(word in title_raw.lower() for word in ["engineer", "developer", "programmer"]):
                job_category = "Software/Web/Mobile"
            else:
                # Kiểm tra nội dung
                full_check_text = f"{title_raw} {clean_desc} {clean_req}".lower()
                if any(word in full_check_text for word in ["data", "ai", "ml", "analyst", "science"]):
                    job_category = "Data/AI"
                elif any(word in full_check_text for word in ["devops", "cloud", "infra", "kubernetes", "docker"]):
                    job_category = "DevOps/Cloud/Infra"
                elif any(word in full_check_text for word in ["security", "secure", "cyber"]):
                    job_category = "Security"
                elif any(word in full_check_text for word in ["product", "design", "manager", "ux", "ui"]):
                    job_category = "Product/Design"
                else:
                    # Last resort: Software/Web/Mobile as catch-all
                    job_category = "Software/Web/Mobile"
        else:
            job_category = validated_category
        
        # --- 3. Job Object (Full Fields) ---
        job_temp_id = len(self.processed_jobs) + 1
        job_obj = {
            "temp_id": job_temp_id,
            "company_temp_id": comp_obj["temp_id"],
            "title": title_raw,
            "job_category": job_category, 
            "fingerprint": job_hash,
            "job_url": raw_job.get('job_url', ''),
            "description": clean_desc,
            "requirements": clean_req,
            "benefits_raw": clean_ben, 
            "formatted_work_type": work_type,
            "formatted_experience_level": level,
            "remote_allowed": is_remote,
            "views": 0,
            "applies": 0,
            "posted_date": raw_job.get('posted_date') or datetime.now().strftime("%Y-%m-%d"),
            # [NEW] Preserve source attributes
            "source_name": raw_job.get('source_name', 'unknown'),
            "job_source_id": raw_job.get('job_source_id', ''),
            "employment_type": raw_job.get('employment_type', ''),
            "experience_raw": raw_job.get('experience_raw', ''),
            "scraped_at": raw_job.get('scraped_at', datetime.now().isoformat()),
        }
        self.processed_jobs.append(job_obj)

        # --- 4. Salaries ---
        salary_str = raw_job.get('salary_raw') or raw_job.get('salary_list') or raw_job.get('detail_salary')
        min_s, max_s, med_s, curr, period = self.parse_salary_regex(salary_str)
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
        full_text = f"{title_raw} {clean_desc} {clean_req} {raw_job.get('tags', '')}"
        extracted = self.extract_skills_regex(full_text)
        
        # Handle tags (can be string or list)
        tags = raw_job.get('tags')
        if tags:
            if isinstance(tags, str):
                # String format: split by semicolon
                extracted.extend([(t.strip(), 'Other') for t in tags.split(';') if t.strip()])
            elif isinstance(tags, list):
                # List format: use directly
                extracted.extend([(t.strip(), 'Other') for t in tags if t and str(t).strip()])

        for name, cat in extracted:
            slug = self.slugify(name)
            if slug not in self.skills_map:
                self.skills_map[slug] = {
                    "temp_id": len(self.skills_map) + 1,
                    "skill_name": name, 
                    "category": cat
                }
            self.processed_job_skills.append({
                "job_temp_id": job_temp_id,
                "skill_temp_id": self.skills_map[slug]["temp_id"],
                "is_inferred": False
            })
        
        # --- 7. Industries ---
        self.process_industry(job_temp_id, comp_obj.get('industry_raw'))
        
        # === PHASE 2: OPTIONAL AI ENRICHMENT (Gemini) ===
        # Đẩy vào buffer để Gemini phân tích & chuẩn hóa thêm (skills/benefits/category...)
        if self.use_ai:
            self.job_buffer.append({
                "temp_id": job_temp_id,
                "title": title_raw,
                "description": clean_desc,
                "requirements": clean_req,
                "raw_salary": raw_job.get('salary_list') or raw_job.get('detail_salary') or raw_job.get('salary_raw'),
                "raw_exp": raw_job.get('experience_raw') or raw_job.get('exp_list'),
                "raw_benefits": clean_ben
            })

    def export_data(self, output_file='clean_data_full.json'):
        if self.use_ai and self.job_buffer:
            self.process_batch_with_gemini()

        # [NEW] Validate all categories before export
        invalid_categories = []
        for job in self.processed_jobs:
            cat = job.get('job_category')
            if cat not in self.VALID_CATEGORIES and cat != "Other":
                invalid_categories.append((job.get('temp_id'), job.get('title'), cat))
        
        if invalid_categories:
            print(f"\n⚠️  VALIDATION ERROR: {len(invalid_categories)} jobs with invalid categories!")
            print("Valid categories:", sorted(self.VALID_CATEGORIES))
            for job_id, title, cat in invalid_categories[:5]:
                print(f"  Job {job_id} ({title[:50]}): {cat}")
            raise ValueError(f"Cannot export data with invalid categories")

        final_data = {
            "metadata": {
                "total_jobs": len(self.processed_jobs), 
                "timestamp": str(datetime.now()),
                "duplicates_removed": self.duplicate_count,  # Thống kê số lượng bị trùng
                "ai_usage": {
                    "enabled": self.use_ai,
                    "api_calls": self.api_calls_count,
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens,
                    "total_tokens": self.total_input_tokens + self.total_output_tokens,
                    "avg_tokens_per_job": round((self.total_input_tokens + self.total_output_tokens) / len(self.processed_jobs), 2) if self.processed_jobs else 0
                }
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
        
        if self.use_ai:
            total_tokens = self.total_input_tokens + self.total_output_tokens
            
            # Tính toán token còn lại
            daily_quota = 15_000_000  # 15M tokens/day free quota
            tokens_remaining = max(0, daily_quota - total_tokens)
            avg_tokens_per_job = round(total_tokens / len(self.processed_jobs), 2) if self.processed_jobs else 0
            jobs_can_process = int(tokens_remaining / avg_tokens_per_job) if avg_tokens_per_job > 0 else 0
            
            print(f"\n📊 TOKEN USAGE:")
            print(f"   Đã dùng: {total_tokens:,} tokens")
            print(f"   Trung bình/job: {avg_tokens_per_job:,.0f} tokens")
            print(f"   Còn lại hôm nay: {tokens_remaining:,} tokens")
            print(f"   Có thể xử lý thêm: {jobs_can_process:,} jobs")

# --- MAIN ---
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean job data from crawl output')
    parser.add_argument('--input', type=str, help='Input JSON file or folder path')
    parser.add_argument('--output', type=str, help='Output JSON file path')
    args = parser.parse_args()
    
    processor = DataProcessor()
    
    current_dir = Path(__file__).parent
    ignore_patterns = ['package.json', 'package-lock.json', 'clean_data']
    
    # Nếu có --input argument, dùng nó; nếu không, search trong folder
    if args.input:
        input_path = Path(args.input)
        if input_path.is_file() and input_path.suffix == '.json':
            processor.process_file(input_path)
        elif input_path.is_dir():
            # Scan folder for JSON files
            json_files = list(input_path.glob("*.json"))
            for f in json_files:
                if not any(ig in f.name for ig in ignore_patterns):
                    processor.process_file(f)
        else:
            print(f"❌ Input path không hợp lệ: {input_path}")
            sys.exit(1)
    else:
        # Default: look for jobs_combined.json in current directory
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