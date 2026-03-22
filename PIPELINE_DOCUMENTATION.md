# Tài Liệu Đầy Đủ Quy Trình Pipeline So Khớp CV-JD

**Hệ thống**: Job Visualization & CV-Job Matching  
**Trạng thái**: Giai đoạn 3 (So khớp dựa trên quy tắc cơ sở)  
**Cập nhật lần cuối**: Tháng 3 năm 2026

---

## MỤC LỤC
1. [Tổng quan Pipeline](#tổng-quan-pipeline)
2. [Bước 1: Thu thập dữ liệu](#bước-1-thu-thập-dữ-liệu)
3. [Bước 2: Làm sạch dữ liệu & xử lý AI](#bước-2-làm-sạch-dữ-liệu--xử-lý-ai)
4. [Bước 3: Nhập vào cơ sở dữ liệu](#bước-3-nhập-vào-cơ-sở-dữ-liệu)
5. [Bước 4: Chuẩn bị tập dữ liệu việc làm](#bước-4-chuẩn-bị-tập-dữ-liệu-việc-làm)
6. [Bước 5: Trích xuất kỹ năng việc làm](#bước-5-trích-xuất-kỹ-năng-việc-làm)
7. [Bước 6: Xuất từ cơ sở dữ liệu](#bước-6-xuất-từ-cơ-sở-dữ-liệu)
8. [Bước 7: Trích xuất hồ sơ CV](#bước-7-trích-xuất-hồ-sơ-cv)
9. [Bước 8: Công cụ so khớp CV-JD](#bước-8-công-cụ-so-khớp-cv-jd)
10. [Bước 9: Đánh giá kết quả So khớp](#bước-9-đánh-giá-kết-quả-so-khớp)
11. [Các điểm kiểm soát chất lượng dữ liệu](#các-điểm-kiểm-soát-chất-lượng-dữ-liệu)

---

## TỔNG QUAN PIPELINE

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    LƯU ĐỒ PIPELINE HOÀN CHỈNH                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [Trang web tuyển dụng]                         [Tệp CV]               │
│       │                                             │                  │
│       ├─ iTViec                                     ├─ PDF             │
│       ├─ LinkedIn                                   ├─ Hình ảnh        │
│       ├─ CareerViet                                 └─ Tài liệu        │
│       └─ VietnamWorks                                                  │
│       │                                             │                  │
│       v                                             v                  │
│  ╔═════════════╗                              ╔═════════════════╗     │
│  ║   BƯỚC 1    ║                              ║    BƯỚC 7       ║     │
│  ║  THU THẬP   ║                              ║ TRÍCH XUẤT HỒ   ║     │
│  ║ DỮ LIỆU     ║                              ║   SƠ CV         ║     │
│  ║ (Selenium)  ║                              ║  (easyocr)      ║     │
│  ╚═════════════╝                              ╚═════════════════╝     │
│       │                                             │                  │
│       v                                             v                  │
│  Tệp JSON thô                              cv_profiles_baseline.json   │
│  (crawl_YYYYMMDD/)                                 │                  │
│       │                                             │                  │
│       v                                             │                  │
│  ╔═════════════╗                                   │                  │
│  ║   BƯỚC 2    ║                                   │                  │
│  ║  LÀM SẠCH   ║                                   │                  │
│  ║ & TRÍCH XU. ║                                   │                  │
│  ║  (Gemini)   ║                                   │                  │
│  ╚═════════════╝                                   │                  │
│       │                                             │                  │
│       v                                             │                  │
│  clean_data_final.json                             │                  │
│       │                                             │                  │
│       v                                             │                  │
│  ╔═════════════╗                                   │                  │
│  ║   BƯỚC 3    ║                                   │                  │
│  ║ NHẬP VÀO    ║                                   │                  │
│  ║   CSDL      ║                                   │                  │
│  ║ (psycopg2)  ║                                   │                  │
│  ╚═════════════╝                                   │                  │
│       │                                             │                  │
│       v                                             │                  │
│  PostgreSQL Database                               │                  │
│  ├─ jobs table                                     │                  │
│  ├─ companies table                                │                  │
│  ├─ skills table                                   │                  │
│  ├─ job_skills table                               │                  │
│  └─ benefits table                                 │                  │
│       │                                             │                  │
│  ╔────┴──────────────────────────────────────────┘                   │
│  │                                                                     │
│  │ ┌──────────────────────────────────────────────┐                  │
│  │ │   HỆ THỐNG SO KHỚP (Các bước 4-9)           │                  │
│  │ └──────────────────────────────────────────────┘                  │
│  │                                                                     │
│  v                                                                     │
│  ╔═════════════╗        ╔═════════════╗       ╔═════════════╗        │
│  ║   BƯỚC 4    ║        ║   BƯỚC 5    ║       ║   BƯỚC 6    ║        │
│  ║  CHUẨN BỊ   ║──────> ║ TRÍCH XUẤT  ║──────>║ XUẤT TỪ     ║        │
│  ║  TẬP DỮ LIỆ ║        ║   KỸ NĂNG   ║       ║   CSDL      ║        │
│  ║             ║        ║             ║       ║             ║        │
│  ╚═════════════╝        ╚═════════════╝       ╚═════════════╝        │
│                                                      │                │
│                                                      v                │
│                                          jobs_from_db.json            │
│                                                      │                │
│                          ┌───────────────────────────┘               │
│                          │                                            │
│  cv_profiles_baseline.json                    jobs_from_db.json       │
│           │                                            │              │
│           └─────┬────────────────────────────────────┬─┘             │
│                 │                                    │               │
│                 v                                    v               │
│           ╔═════════════════════════════╗                            │
│           ║        BƯỚC 8               ║                            │
│           ║      CÔNG CỤ SO KHỚP        ║                            │
│           ║                             ║                            │
│           ║ • Lọc theo ngành            ║                            │
│           ║ • Tính điểm tương tự        ║                            │
│           ║ • Kết hợp có trọng số       ║                            │
│           ║ • Phân tích khoảng cách      ║                            │
│           ║ • Xếp hạng top-K            ║                            │
│           ╚═════════════════════════════╝                            │
│                      │                                                │
│                      v                                                │
│           matching_results.json                                       │
│                      │                                                │
│                      v                                                │
│           ╔═════════════════════════════╗                            │
│           ║        BƯỚC 9               ║                            │
│           ║       ĐÁNH GIÁ               ║                            │
│           ║                             ║                            │
│           ║ • Chỉ số chất lượng dữ liệu ║                            │
│           ║ • Thống kê hành vi matching ║                            │
│           ║ • Phân tích độ tin cậy      ║                            │
│           ║ • Phân tích khoảng cách     ║                            │
│           ╚═════════════════════════════╝                            │
│                      │                                                │
│                      v                                                │
│   matching_db_evaluation_report.json/.md                             │
│                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## STAGE 1: DATA CRAWLING

**Location**: `Db/1_crawl_data/`  
**Orchestrator**: `crawl_all_daily.bat`

### Data Sources
- **iTViec** (itviec.com)
- **LinkedIn** (linkedin.com/jobs)
- **CareerViet** (careerviet.vn)
- **VietnamWorks** (vietnamworks.com)

### Key Scripts

**`crawl_data/` subdirectories**
- `crawl-itviec-jobs/` - Selenium-based iTViec scraper
- `crawl-linkedin-jobs/` - Selenium-based LinkedIn scraper
- `crawl-careerviet-jobs/` - Selenium-based CareerViet scraper
- `crawl-vietnamwork-jobs/` - Selenium-based VietnamWorks scraper

**`normalize_schema.py`**
- **Purpose**: Normalize field names across different crawlers
- **Input**: Raw JSON files from each crawler with different field names
- **Output**: Normalized schema with consistent fields
- **Transformations**:
  ```python
  desc_mota → description_html
  desc_yeucau → requirements_text
  luong_tu → salary_min
  luong_den → salary_max
  link → job_url
  ```

**`merge_daily_outputs.py`**
- **Purpose**: Combine outputs from all crawlers and deduplicate
- **Input**: Normalized JSON files from all crawlers
- **Output**: Single merged file for the day
- **Deduplication Key**: `(title, company_name, source_name)`
- **Data Retention**: Keeps earliest occurrence, discards duplicates

### Output Format
**Location**: `data/crawl_YYYYMMDD/`  
**Files**: One JSON file per crawl date

```json
[
  {
    "title": "Senior Frontend Developer",
    "company_name": "Tech Corp",
    "description_html": "<p>...</p>",
    "requirements_text": "React, TypeScript, CSS...",
    "salary_raw": "15-25 triệu",
    "experience_raw": "3-5 năm",
    "benefits": "Đồng phục, Du lịch",
    "location_raw": "Hà Nội",
    "job_url": "https://itviec.com/jobs/...",
    "source_name": "iTViec",
    "crawl_date": "2026-03-22"
  }
]
```

### Libraries
- **selenium**: Browser automation for JavaScript-heavy sites
- **beautifulsoup4**: HTML parsing
- **requests**: HTTP requests

### Data Quality Checkpoints
- ✓ HTML content extracted (not text-only)
- ✓ No duplicate (title, company, source)
- ✓ URL format validated
- ⚠️ Raw salary/experience not yet normalized (done in Stage 2)

---

## STAGE 2: DATA CLEANING & AI PROCESSING

**Location**: `Db/2_clean_data/`  
**Main Script**: `clean_process.py`  
**Configuration**: `constants.py` (SKILL_KEYWORDS, JOB_CATEGORIES, BENEFITS_KEYWORDS)

### Input
Raw JSON files from Stage 1  
**Source**: `data/crawl_YYYYMMDD/*.json`

### Processing Pipeline

#### Step 2.1: Load & Deduplicate
```python
Input: Raw job records from all crawlers
↓
Load JSON files
↓
Create MD5 fingerprint: hash(title + company + description)
↓
Deduplicate by fingerprint (keep first occurrence)
↓
Output: Deduplicated records
```

#### Step 2.2: Parse & Extract (Regex-based)
For each job record:

```python
# Salary extraction
salary_min, salary_max = extract_salary(salary_raw)
# Pattern: "15-25 triệu" -> (15000000, 25000000)

# Experience level extraction
experience_level = classify_experience(experience_raw)
# Output: "Intern" | "Junior" | "Senior" | "Director"

# Work type extraction
work_type = extract_work_type(description_html + requirements_text)
# Output: "Full-time" | "Part-time" | "Contract"

# Remote status extraction
is_remote = check_remote(description_html + requirements_text)
```

#### Step 2.3: AI-Powered Extraction (Google Gemini)
**When**: If Google Generativeai API available (configured in .env)  
**Model**: Gemini 2.5 Flash

```python
Input: description_html + requirements_text

For each job:
  response = gemini.generate_content(
    prompt=f"""
    Classify job category: {JOB_CATEGORIES}
    Extract technical skills from: {requirements_text}
    Map to canonical names: {SKILL_KEYWORDS}
    Extract benefits from: {description_html}
    Map benefits to: {BENEFITS_KEYWORDS}
    """
  )
  
  parsed = {
    "job_category": response.job_category,
    "skills_extracted": response.skills,
    "benefits": response.benefits
  }
```

#### Step 2.4: Skill Normalization
Maps extracted skills to canonical names from `SKILL_KEYWORDS`:

```python
# Example canonical skill mapping
SKILL_KEYWORDS = {
  "languages": {
    "Python": ["python", "py"],
    "JavaScript": ["javascript", "js", "node.js", "nodejs"],
    "Java": ["java"]
  },
  "frontend": {
    "React": ["react", "reactjs"],
    "Vue": ["vue", "vuejs"],
    "HTML": ["html", "html5"]
  },
  # ... more categories
}

# Matching process
input: "js, html5, react"
↓
canonical_skills = []
for skill in input.split(","):
  for canonical, variations in all_skills.items():
    if skill in variations:
      canonical_skills.append(canonical)
↓
output: ["JavaScript", "HTML", "React"]
```

#### Step 2.5: Benefit Standardization
Maps Vietnamese benefits to English canonical forms:

```python
BENEFITS_KEYWORDS = {
  "uniform": ["đồng phục", "thời trang"],
  "travel": ["du lịch", "company trip"],
  "insurance": ["bảo hiểm", "health coverage"]
}

# Example: "Đồng phục, Du lịch" → ["uniform", "travel"]
```

### Output Format
**File**: `clean_data_final.json`

```json
[
  {
    "job_id": "abc123def456",
    "title": "Senior Frontend Developer",
    "job_category": "Web Development",
    "company_slug": "tech-corp",
    "salary_min": 15000000,
    "salary_max": 25000000,
    "salary_median": 20000000,
    "salary_currency": "VND",
    "experience_level": "Senior",
    "work_type": "Full-time",
    "skills_extracted": ["React", "TypeScript", "CSS", "JavaScript"],
    "benefits": ["uniform", "travel", "insurance"],
    "fingerprint": "abc123def456789",
    "description": "...",
    "requirements_text": "..."
  }
]
```

### Data Quality Checkpoints
- ✓ MD5 fingerprint validates no corrupted duplicates
- ✓ Salary normalized to numbers (can be null if unparseable)
- ✓ Experience level standardized to 4 categories
- ⚠️ AI extraction may fail if Gemini API unavailable (falls back to regex-only)
- ⚠️ Skill extraction accuracy depends on Gemini response quality
- ✓ Skills normalized to canonical names

### Libraries
- **google-generativeai**: Gemini 2.5 Flash for smart extraction
- **regex (re)**: Salary, experience, work type, remote parsing
- **hashlib**: MD5 fingerprint generation
- **json, pathlib**: File I/O

---

## STAGE 3: DATABASE IMPORT

**Location**: `Db/3_mapping_data_db/`  
**Main Script**: `import_to_db.py`  
**Schema**: `CreateDB.sql`

### Database Schema

```sql
CREATE TABLE companies (
  company_id SERIAL PRIMARY KEY,
  name VARCHAR(255) UNIQUE,
  slug VARCHAR(255) UNIQUE
);

CREATE TABLE skills (
  skill_id SERIAL PRIMARY KEY,
  skill_name VARCHAR(100) UNIQUE,
  category VARCHAR(50)
);

CREATE TABLE industries (
  industry_id SERIAL PRIMARY KEY,
  industry_name VARCHAR(100) UNIQUE
);

CREATE TABLE jobs (
  job_id SERIAL PRIMARY KEY,
  title VARCHAR(255),
  company_id INTEGER REFERENCES companies(company_id),
  description TEXT,
  requirements_text TEXT,
  salary_min BIGINT,
  salary_max BIGINT,
  salary_currency VARCHAR(10),
  experience_level VARCHAR(50),
  work_type VARCHAR(50),
  industry_id INTEGER REFERENCES industries(industry_id),
  fingerprint VARCHAR(255) UNIQUE,
  is_published BOOLEAN DEFAULT TRUE,
  CONSTRAINT unique_job UNIQUE(title, company_id, fingerprint)
);

CREATE TABLE job_skills (
  job_id INTEGER REFERENCES jobs(job_id),
  skill_id INTEGER REFERENCES skills(skill_id),
  is_inferred BOOLEAN DEFAULT FALSE,
  PRIMARY KEY(job_id, skill_id)
);

CREATE TABLE benefits (
  benefit_id SERIAL PRIMARY KEY,
  benefit_name VARCHAR(100) UNIQUE
);

CREATE TABLE job_benefits (
  job_id INTEGER REFERENCES jobs(job_id),
  benefit_id INTEGER REFERENCES benefits(benefit_id),
  PRIMARY KEY(job_id, benefit_id)
);
```

### Import Process

**Step 1: Initialize Database Schema**
```bash
# Run in PostgreSQL
psql -U postgres -d <database> -f CreateDB.sql
```

**Step 2: Seed Master Data**
```python
# Load constants.py
# Insert all canonical skills into skills table
# Insert all job categories into jobs table
# Insert all industries into industries table
```

**Step 3: Import Cleaned Job Data**
```python
with open('clean_data_final.json') as f:
    jobs = json.load(f)

for job in jobs:
    # Upsert company
    company_id = get_or_create_company(job['company_slug'])
    
    # Upsert job
    job_id = upsert_job(
        title=job['title'],
        company_id=company_id,
        description=job['description'],
        fingerprint=job['fingerprint'],
        # ... other fields
    )
    
    # Insert job_skills relationships
    for skill_name in job['skills_extracted']:
        skill_id = get_skill_id(skill_name)
        insert_job_skill(job_id, skill_id, is_inferred=False)
    
    # Insert job_benefits relationships
    for benefit in job['benefits']:
        benefit_id = get_benefit_id(benefit)
        insert_job_benefit(job_id, benefit_id)
```

**Step 4: Deduplication Handling**
- **Primary Key Constraint**: `(title, company_id, fingerprint)`
- **On Conflict**: Update `is_published=TRUE` (upsert)
- **Orphan Handling**: Jobs with new fingerprints marked `is_published=FALSE`

### Output
**PostgreSQL Database**  
Tables populated:
- `jobs` (N records, N = unique jobs after crawl)
- `job_skills` (M relationships, M = N × avg_skills_per_job)
- `companies` (K unique companies)
- `skills` (all canonical skills from constants.py)
- `benefits` (all benefit codes)

### Data Quality Checkpoints
- ✓ Fingerprint uniqueness enforced by DB constraint
- ✓ Foreign key constraints ensure referential integrity
- ✓ Skill mapping ensures only canonical names in job_skills
- ✓ Batch insert rollback on error (no partial states)
- ⚠️ Jobs with unparseable salary set to NULL (not filtered out)
- ✓ indexes on (job_id, skill_id) for fast matching queries

### Libraries
- **psycopg2**: PostgreSQL connection and bulk insert
- **python-dotenv**: Load database credentials from .env

### Configuration
**File**: `.env` (not in repo, load locally)
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=job_matching_db
DB_USER=postgres
DB_PASSWORD=***
```

---

## STAGE 4: JOB DATASET PREPARATION

**Location**: `Matching/01_prepare_job_dataset.py`

### Purpose
Prepare raw job extracts for matching by classifying quality and deduplicating

### Input
Raw job files from `Dataset/raw_jobs/`

### Processing

```python
# Load raw jobs
raw_jobs = load_json_files('Dataset/raw_jobs/')

# Quality stratification
results = {
    'jobs_ready': [],
    'jobs_missing_req': [],
    'jobs_dirty_req': []
}

for job in raw_jobs:
    # Extract core fields
    job_clean = {
        'title': job.get('title', ''),
        'company_name': job.get('company_name', ''),
        'job_url': job.get('job_url', ''),
        'description_html': job.get('description_html', ''),
        'requirements_text': job.get('requirements_text', '')
    }
    
    # Classify by quality
    if not job_clean['requirements_text']:
        results['jobs_missing_req'].append(job_clean)
    elif is_dirty_requirements(job_clean['requirements_text']):
        results['jobs_dirty_req'].append(job_clean)
    else:
        results['jobs_ready'].append(job_clean)

# Deduplicate jobs_ready
deduplicated = []
seen = set()
for job in results['jobs_ready']:
    key = (job['title'], job['company_name'], job['job_url'])
    if key not in seen:
        deduplicated.append(job)
        seen.add(key)

# Output
save_json('Dataset/processed_jobs/jobs_ready.json', deduplicated)
save_json('Dataset/processed_jobs/jobs_missing_req.json', results['jobs_missing_req'])
save_json('Dataset/processed_jobs/jobs_dirty_req.json', results['jobs_dirty_req'])
```

### Output Files
1. **`jobs_ready.json`**: ✓ Has non-empty requirements
2. **`jobs_missing_req.json`**: ✗ No requirements_text
3. **`jobs_dirty_req.json`**: ⚠️ Malformed requirements (too short, no keywords, etc.)

### Data Quality Checkpoints
- ✓ Deduplication by (title, company, url)
- ✓ Separation of problematic jobs for manual review
- ⚠️ "Dirty" classification threshold can be adjusted

---

## STAGE 5: JOB SKILL EXTRACTION

**Location**: `Matching/02_extract_job_skills.py`

### Purpose
Extract technical skills from job requirements text using pattern matching

### Input
`Dataset/processed_jobs/jobs_ready.json`

### Skill Dictionary
**Source**: `Matching/constants.py` → `SKILL_KEYWORDS`

```python
SKILL_KEYWORDS = {
    'languages': {
        'Python': ['python', 'py'],
        'JavaScript': ['javascript', 'js', 'node.js', 'nodejs'],
        'Java': ['java'],
        # ... 30+ languages
    },
    'frontend': {
        'React': ['react', 'reactjs', 'react.js'],
        'Vue': ['vue', 'vuejs', 'vue.js'],
        'Angular': ['angular', 'angularjs'],
        # ... more frontend frameworks
    },
    'backend': {
        'Laravel': ['laravel'],
        'Django': ['django'],
        'Spring': ['spring', 'springboot'],
        # ... more backend frameworks
    },
    'database': {
        'PostgreSQL': ['postgresql', 'postgres', 'pg'],
        'MySQL': ['mysql'],
        'MongoDB': ['mongodb', 'mongo'],
        # ... more databases
    },
    # ... (DevOps, Testing, Mobile, DevTools, etc.)
}
```

### Extraction Algorithm

```python
def extract_skills(requirements_text):
    """Extract skills from requirements using pattern matching"""
    
    extracted = set()
    text_lower = requirements_text.lower()
    
    # Flatten all skills for searching
    all_skills = {}
    for category, skills_dict in SKILL_KEYWORDS.items():
        for canonical, variations in skills_dict.items():
            all_skills[canonical] = variations
    
    # Pattern matching
    for canonical_skill, variations in all_skills.items():
        for variation in variations:
            # Word boundary matching (avoid false matches)
            pattern = r'\b' + re.escape(variation) + r'\b'
            if re.search(pattern, text_lower):
                extracted.add(canonical_skill)
                break  # Don't count same skill multiple times
    
    return sorted(list(extracted))
```

### Example
**Input**:
```
React, Node.js, MongoDB, PostgreSQL, Docker, TypeScript, 
Jest for unit testing, Postman for API testing
```

**Output**:
```json
[
  "React",
  "JavaScript",
  "MongoDB",
  "PostgreSQL",
  "Docker",
  "TypeScript",
  "Jest",
  "Postman"
]
```

### Output Format
**File**: `jobs_structured.json`

```json
[
  {
    "title": "Senior Frontend Developer",
    "company_name": "Tech Corp",
    "job_url": "https://itviec.com/jobs/123",
    "skills_extracted": ["React", "TypeScript", "CSS", "JavaScript"]
  }
]
```

### Data Quality Issues
- ⚠️ **Abbreviation collisions**: "JS" matches both JavaScript and Job Specialization
- ⚠️ **Missing skills**: Rare/new technologies not in SKILL_KEYWORDS dictionary
- ⚠️ **False positives**: "Spring" matches both Spring framework and literal word "spring"
- ✓ **Partial matches filtered**: Use word boundaries `\b...\b`

### Libraries
- **re (regex)**: Pattern matching with word boundaries

---

## STAGE 6: DATABASE EXPORT

**Location**: `Matching/03_export_jobs_from_db.py`

### Purpose
Export job records from PostgreSQL for CV-JD matching

### Input
PostgreSQL database (populated in Stage 3)

### Query Logic

```python
def export_jobs_for_matching():
    """
    Export jobs with aggregated skills from database
    """
    query = """
    SELECT 
      j.job_id,
      j.title,
      c.name as company_name,
      j.description,
      j.requirements_text,
      j.experience_level as formatted_experience_level,
      j.work_type,
      j.salary_min,
      j.salary_max,
      l.location,
      j.job_url,
      -- Aggregate skills for this job
      json_agg(
        json_build_object(
          'skill_name', s.skill_name,
          'is_inferred', js.is_inferred
        )
      ) as skills_extracted
    FROM jobs j
    LEFT JOIN companies c ON j.company_id = c.company_id
    LEFT JOIN job_skills js ON j.job_id = js.job_id
    LEFT JOIN skills s ON js.skill_id = s.skill_id
    WHERE j.is_published = TRUE
    GROUP BY j.job_id, c.company_id
    ORDER BY j.job_id
    """
    
    results = execute_query(query)
    return results
```

### Post-Processing

```python
# Format skills_extracted as list of strings (not objects)
for job in results:
    job['skills_extracted'] = [
        s['skill_name'] for s in job['skills_extracted']
    ]
    
    # Remove nulls if no skills
    if job['skills_extracted'] == [None]:
        job['skills_extracted'] = []
```

### Output Format
**File**: `jobs_from_db.json`

```json
[
  {
    "job_id": 1,
    "title": "Senior Frontend Developer",
    "company_name": "Tech Corp",
    "description": "...",
    "skills_extracted": ["React", "TypeScript", "CSS"],
    "formatted_experience_level": "Senior",
    "work_type": "Full-time",
    "salary_min": 15000000,
    "salary_max": 25000000,
    "location": "Hà Nội",
    "job_url": "https://itviec.com/jobs/123"
  }
]
```

### Data Quality Statistics
**Current Dataset** (283 jobs):
- **Total jobs**: 283
- **Jobs with no skills**: 183 (64.66%)
- **Jobs with ≤3 skills**: 191 (67.49%)
- **Skill count distribution**:
  - Min: 0 skills
  - Mean: 0.96 skills/job
  - Median: 0 skills
  - Max: 6 skills

### Libraries
- **psycopg2**: Database connection
- **json**: JSON serialization for skills_extracted

---

## STAGE 7: CV PROFILE EXTRACTION

**Location**: `Matching/04_extract_cv_profile_baseline.py`

### Purpose
Parse CV files (PDFs, images) to extract structured candidate profiles

### Input
CV files from `Dataset/test/`  
Supported formats:
- `.pdf` (PDF files)
- `.jpg`, `.png` (scanned images)
- `.docx` (optional, with python-docx)

### Processing Pipeline

#### Step 7.1: Load CV File

```python
import easyocr
from pathlib import Path

# Initialize OCR (Vietnamese + English)
reader = easyocr.Reader(['vi', 'en'])

def load_cv_text(file_path):
    """Extract text from PDF or image"""
    
    if file_path.endswith('.pdf'):
        # PDF extraction using PyPDF2 or pdfplumber
        text = extract_pdf_text(file_path)
    elif file_path.endswith(('.jpg', '.png', '.jpeg')):
        # Image OCR using easyocr
        result = reader.readtext(file_path, detail=0)
        text = '\n'.join(result)
    elif file_path.endswith('.docx'):
        # DOCX extraction using python-docx
        text = extract_docx_text(file_path)
    
    return text
```

#### Step 7.2: Extract Candidate Name

```python
def extract_candidate_name(text):
    """
    Heuristic-based name extraction
    Names typically appear at top of CV with properties:
    - Multiple uppercase letters
    - 2-3 words
    - Early in document (line 0-5)
    """
    
    lines = text.split('\n')[:10]
    
    candidates = []
    for i, line in enumerate(lines):
        score = 0
        
        # Scoring heuristics
        if uppercase_ratio(line) > 0.6:
            score += 3
        if 2 <= len(line.split()) <= 3:
            score += 2
        if i < 3:
            score += 1
        if not any_number_in_line(line):
            score += 1
        
        if score >= 4:
            candidates.append((line.strip(), score))
    
    # Return highest scoring candidate
    if candidates:
        name, _ = max(candidates, key=lambda x: x[1])
        return name
    
    return None
```

#### Step 7.3: Extract Job Title

```python
from Matching.constants import TITLE_MAP

def extract_job_title(text):
    """
    Extract current/desired job title from CV
    Pattern: "Position: Senior Developer" or "Vị trí: ..."
    """
    
    # Define position keywords in Vietnamese and English
    position_keywords = [
        'position', 'vị trí', 'title', 'chức danh',
        'current role', 'role hiện tại'
    ]
    
    text_lines = text.split('\n')
    
    for line in text_lines[:30]:  # Check first 30 lines
        line_lower = line.lower()
        
        for keyword in position_keywords:
            if keyword in line_lower:
                # Extract after colon or equals
                if ':' in line:
                    title = line.split(':')[1].strip()
                    return normalize_title(title)
                elif '=' in line:
                    title = line.split('=')[1].strip()
                    return normalize_title(title)
    
    return None

def normalize_title(title):
    """
    Normalize job title to standard form
    Map variations to canonical names
    """
    
    TITLE_MAP = {
        'frontend_developer': [
            'frontend developer', 'front-end developer',
            'react developer', 'vue developer',
            'web developer', 'ui developer'
        ],
        'backend_developer': [
            'backend developer', 'back-end developer',
            'python developer', 'java developer',
            'server-side developer', 'api developer'
        ],
        'qa_tester': [
            'tester', 'qa', 'qc', 'quality assurance',
            'test engineer', 'automation tester'
        ],
        # ... more mappings
    }
    
    title_lower = title.lower().strip()
    
    for canonical, variations in TITLE_MAP.items():
        if any(var in title_lower for var in variations):
            return canonical
    
    return 'other'
```

#### Step 7.4: Extract Technical Skills

```python
def extract_skills(text):
    """
    Extract skills from CV text using pattern matching
    Same algorithm as Stage 5
    """
    
    from Matching.constants import SKILL_KEYWORDS
    
    extracted = set()
    text_lower = text.lower()
    
    # Flatten all skills
    all_skills = {}
    for category, skills_dict in SKILL_KEYWORDS.items():
        for canonical, variations in skills_dict.items():
            all_skills[canonical] = variations
    
    # Pattern matching with word boundaries
    for canonical_skill, variations in all_skills.items():
        for variation in variations:
            pattern = r'\b' + re.escape(variation) + r'\b'
            if re.search(pattern, text_lower):
                extracted.add(canonical_skill)
                break
    
    return sorted(list(extracted))
```

#### Step 7.5: Skill Inference

```python
def infer_skills(extracted_skills, job_title):
    """
    Infer additional skills based on job title and explicit skills
    
    Rules:
    - If title contains "Tester" → infer "Quality processes", "Testing mindset"
    - If skills contain "Selenium" → infer "Test automation"
    - If skills contain "Postman" → infer "API testing"
    """
    
    INFERENCE_RULES = {
        'tester': ['Quality processes', 'Testing mindset', 'SDLC'],
        'qa': ['Quality processes', 'Quality processes', 'Bug reporting'],
        'senior': ['Team leadership', 'Problem solving'],
        'selenium': ['Test automation'],
        'postman': ['API testing'],
        'frontend': ['HTML', 'CSS', 'UX awareness'],
        # ...
    }
    
    inferred = set()
    
    # Infer from title
    title_lower = job_title.lower() if job_title else ''
    for keyword, inferred_skills in INFERENCE_RULES.items():
        if keyword in title_lower:
            inferred.update(inferred_skills)
    
    # Infer from explicit skills
    for skill in extracted_skills:
        if skill.lower() in INFERENCE_RULES:
            inferred.update(INFERENCE_RULES[skill.lower()])
    
    return sorted(list(inferred))
```

#### Step 7.6: Extract Certifications

```python
def extract_certifications(text):
    """
    Extract recognized certifications
    Pattern: "ISTQB Certified", "AWS Solution Architect", etc.
    """
    
    CERT_KEYWORDS = [
        'ISTQB', 'AWS', 'Azure', 'GCP', 'TOEIC', 'IELTS',
        'CPA', 'Oracle', 'Scrum', 'Agile', 'Prince2',
        'SAP', 'Salesforce', 'Tableau', 'Power BI'
    ]
    
    certifications = []
    text_lower = text.lower()
    
    for cert in CERT_KEYWORDS:
        pattern = r'\b' + re.escape(cert) + r'\b'
        if re.search(pattern, text_lower, re.IGNORECASE):
            certifications.append(cert)
    
    return sorted(list(set(certifications)))
```

### Output Format
**File**: `cv_profiles_baseline.json`

```json
[
  {
    "cv_id": "cv_001",
    "file_name": "john_doe_cv.pdf",
    "name": "John Doe",
    "title": "frontend_developer",
    "skills_extracted": ["React", "TypeScript", "CSS", "JavaScript"],
    "inferred_skills": ["HTML", "UX awareness"],
    "certifications": ["AWS Solution Architect"]
  }
]
```

### Data Quality Issues
- ⚠️ **Name detection**: May fail with non-standard CV formats
- ⚠️ **OCR errors**: easyocr may misread handwritten or low-quality scans
- ⚠️ **Title extraction**: May fail if title not in expected position/format
- ⚠️ **Skill inference**: May over-infer based on job title alone
- ✓ **Certification extraction**: Reliable for well-known certifications

### Libraries
- **easyocr**: OCR for Vietnamese + English text from images/PDFs
- **PyPDF2 or pdfplumber**: PDF text extraction
- **python-docx**: DOCX parsing (optional)
- **pyresparser**: Resume field parsing (optional, used for enhancement)
- **regex (re)**: Pattern matching for skills and certifications

---

## STAGE 8: CV-JD MATCHING ENGINE

**Location**: `Matching/05_matching_engine.py`

### Purpose
Match CV profiles to job postings using skill-based semantic matching

### Input
1. **CV Profiles**: `cv_profiles_baseline.json` (Stage 7 output)
2. **Jobs**: `jobs_from_db.json` (Stage 6 output)

### Matching Algorithm

#### Step 8.1: Job Family Filtering

```python
JOB_FAMILY_GROUPS = {
    'tester': ['tester', 'qa', 'qc', 'quality assurance', 'test engineer'],
    'frontend': ['frontend', 'web developer', 'ui developer', 'react developer'],
    'backend': ['backend', 'api developer', 'server-side', 'python developer'],
    'helpdesk': ['support', 'helpdesk', 'it support', 'technical support'],
    # ... more groups
}

def is_same_job_family(cv_title, job_title):
    """
    Check if CV title and job title belong to same family
    Only match if both in same family
    """
    
    cv_family = None
    job_family = None
    
    for family, variations in JOB_FAMILY_GROUPS.items():
        if any(var in cv_title.lower() for var in variations):
            cv_family = family
        if any(var in job_title.lower() for var in variations):
            job_family = family
    
    # Match only if same family OR neither has family (other)
    return cv_family == job_family

def filter_candidate_jobs(cv_profile, all_jobs):
    """Filter jobs for CV based on title family"""
    
    candidate_jobs = []
    for job in all_jobs:
        if is_same_job_family(cv_profile['title'], job['title']):
            candidate_jobs.append(job)
    
    return candidate_jobs
```

#### Step 8.2: Skill Similarity Scoring

```python
def calculate_skill_similarity(cv_skills, job_skill):
    """
    Calculate similarity between CV skills and single job skill
    
    Scoring:
    - Exact match: 1.0
    - Related skill group: 0.75
    - No match: 0.0
    """
    
    # Exact match
    if job_skill in cv_skills:
        return 1.0
    
    # Related skill groups
    RELATED_SKILLS = {
        'JavaScript': ['JS', 'Node.js', 'TypeScript'],
        'HTML': ['HTML5'],
        'CSS': ['SCSS', 'SASS'],
        'QA': ['Tester', 'Software Tester'],
        'API Testing': ['Postman'],
        'SQL': ['MySQL', 'PostgreSQL', 'Oracle'],
        # ...
    }
    
    for canonical, related in RELATED_SKILLS.items():
        if job_skill in related and canonical in cv_skills:
            return 0.75
        if job_skill == canonical and any(r in cv_skills for r in related):
            return 0.75
    
    # No match
    return 0.0
```

#### Step 8.3: Weighted Matching

```python
def calculate_match_score(cv_profile, job):
    """
    Calculate overall match score
    
    Formula: S = Σ(w_i · sim_i)
    
    Where:
    - w_i = weight of skill i (currently 1/n for equal weights)
    - sim_i = similarity of CV skill to job skill
    """
    
    cv_skills = set(cv_profile['skills_extracted'])
    job_skills = job['skills_extracted']
    
    if not job_skills:  # No skills in job posting
        return 0.0, []
    
    n = len(job_skills)
    total_score = 0
    gaps = []
    
    for job_skill in job_skills:
        # Current: equal weights (1/n)
        # TODO: Replace with AHP weights from database
        weight = 1.0 / n
        
        # Calculate similarity
        similarity = calculate_skill_similarity(cv_skills, job_skill)
        
        # Accumulate score
        contribution = weight * similarity
        total_score += contribution
        
        # Gap analysis
        gap = weight * (1 - similarity)
        
        if similarity == 1.0:
            status = 'matched'
        elif similarity == 0.75:
            status = 'improvement'
        else:
            status = 'missing'
        
        gaps.append({
            'skill': job_skill,
            'weight': round(weight, 4),
            'sim_i': similarity,
            'gap_i': round(gap, 4),
            'status': status
        })
    
    return round(total_score, 4), gaps
```

#### Step 8.4: Top-K Ranking

```python
def match_candidate(cv_profile, all_jobs, top_k=5):
    """
    Match one candidate to all jobs and return top K matches
    """
    
    # Filter by job family
    candidate_jobs = filter_candidate_jobs(cv_profile, all_jobs)
    
    if not candidate_jobs:
        return []
    
    # Score all jobs
    matches = []
    for job in candidate_jobs:
        score, gaps = calculate_match_score(cv_profile, job)
        
        matches.append({
            'job_title': job['title'],
            'company_name': job['company_name'],
            'job_url': job['job_url'],
            'match_score': score,
            'match_percent': round(score * 100, 2),
            'top_gaps': gaps
        })
    
    # Sort by score (descending) and take top K
    matches.sort(key=lambda x: x['match_score'], reverse=True)
    return matches[:top_k]


def run_matching_pipeline(cv_profiles_path, jobs_path, output_path):
    """Execute complete matching for all CVs"""
    
    cv_profiles = load_json(cv_profiles_path)
    all_jobs = load_json(jobs_path)
    
    results = []
    
    for cv in cv_profiles:
        top_matches = match_candidate(cv, all_jobs, top_k=5)
        
        results.append({
            'cv_id': cv['cv_id'],
            'candidate_name': cv['name'],
            'candidate_title': cv['title'],
            'top_matches': top_matches
        })
    
    save_json(output_path, results, indent=2)
    return results
```

### Output Format
**File**: `matching_results.json`

```json
[
  {
    "cv_id": "cv_001",
    "candidate_name": "John Doe",
    "candidate_title": "frontend_developer",
    "top_matches": [
      {
        "job_title": "Senior Frontend Developer",
        "company_name": "Tech Corp",
        "job_url": "https://itviec.com/jobs/123",
        "match_score": 0.75,
        "match_percent": 75.0,
        "top_gaps": [
          {
            "skill": "React",
            "weight": 0.25,
            "sim_i": 1.0,
            "gap_i": 0.0,
            "status": "matched"
          },
          {
            "skill": "TypeScript",
            "weight": 0.25,
            "sim_i": 0.75,
            "gap_i": 0.0625,
            "status": "improvement"
          },
          {
            "skill": "Docker",
            "weight": 0.25,
            "sim_i": 0.0,
            "gap_i": 0.25,
            "status": "missing"
          },
          {
            "skill": "Kubernetes",
            "weight": 0.25,
            "sim_i": 0.0,
            "gap_i": 0.25,
            "status": "missing"
          }
        ]
      }
    ]
  }
]
```

### Matching Quality Issues
- ⚠️ **Low skill coverage**: 64.66% jobs have no skills → return 0.0 score
- ⚠️ **Sparse matches**: 67.49% jobs have ≤3 skills, limiting distinguishability
- ⚠️ **Equal weights**: Current implementation uses 1/n weights; should use AHP
- ⚠️ **No CV inference skills in matching**: Only uses extracted_skills, not inferred_skills
- ✓ **Gap analysis available**: Provides actionable improvement recommendations

### Libraries
- **json, pathlib**: I/O operations
- **Standard libraries**: Sorting, filtering

---

## STAGE 9: MATCHING EVALUATION

**Location**: `Matching/07_evaluate_matching_db.py`

### Purpose
Evaluate matching algorithm quality and identify data quality issues

### Input
1. **Jobs Dataset**: `jobs_from_db.json`
2. **Matching Results**: `matching_results.json`

### Evaluation Metrics

#### Metric 1: Job Data Quality

```python
def evaluate_job_data_quality(jobs_json):
    """Assess job dataset quality for matching"""
    
    total_jobs = len(jobs_json)
    
    # Count jobs by skill quantity
    jobs_no_skills = sum(1 for j in jobs_json if len(j.get('skills_extracted', [])) == 0)
    jobs_few_skills = sum(1 for j in jobs_json if 0 < len(j.get('skills_extracted', [])) <= 3)
    
    # Skill count statistics
    skill_counts = [len(j.get('skills_extracted', [])) for j in jobs_json]
    
    metrics = {
        'total_jobs': total_jobs,
        'jobs_without_skills': jobs_no_skills,
        'jobs_without_skills_pct': round(100 * jobs_no_skills / total_jobs, 2),
        'jobs_with_1_to_3_skills': jobs_few_skills,
        'jobs_with_1_to_3_skills_pct': round(100 * jobs_few_skills / total_jobs, 2),
        'skill_count': {
            'min': min(skill_counts) if skill_counts else 0,
            'max': max(skill_counts) if skill_counts else 0,
            'mean': round(statistics.mean(skill_counts), 2) if skill_counts else 0,
            'median': statistics.median(skill_counts) if skill_counts else 0
        }
    }
    
    return metrics
```

#### Metric 2: Matching Score Distribution

```python
def evaluate_matching_scores(matching_results):
    """Assess matching score distribution"""
    
    all_scores = []
    top_1_scores = []
    
    for result in matching_results:
        for match in result['top_matches']:
            score = match['match_score']
            all_scores.append(score)
            
            if match == result['top_matches'][0]:
                top_1_scores.append(score)
    
    metrics = {
        'all_scores': {
            'count': len(all_scores),
            'min': round(min(all_scores), 4) if all_scores else 0,
            'max': round(max(all_scores), 4) if all_scores else 0,
            'mean': round(statistics.mean(all_scores), 4) if all_scores else 0,
            'median': round(statistics.median(all_scores), 4) if all_scores else 0
        },
        'top_1_scores': {
            'mean': round(statistics.mean(top_1_scores), 4) if top_1_scores else 0,
            'median': round(statistics.median(top_1_scores), 4) if top_1_scores else 0,
            'low_confidence_count': sum(1 for s in top_1_scores if s < 0.3),
            'low_confidence_pct': round(100 * sum(1 for s in top_1_scores if s < 0.3) / len(top_1_scores), 2) if top_1_scores else 0
        }
    }
    
    return metrics
```

#### Metric 3: Anomaly Detection

```python
def detect_overconfidence(matching_results, jobs):
    """Find high-score matches suspicious of being false positives"""
    
    anomalies = []
    
    job_skills_map = {j['job_id']: j['skills_extracted'] for j in jobs}
    
    for result in matching_results:
        for match in result['top_matches']:
            # Flag if: score >= 0.9 but job has only 1-2 skills
            job_id = match.get('job_id')
            if job_id in job_skills_map:
                skill_count = len(job_skills_map[job_id])
                
                if match['match_score'] >= 0.9 and skill_count <= 2:
                    anomalies.append({
                        'cv_id': result['cv_id'],
                        'job_id': job_id,
                        'match_score': match['match_score'],
                        'skill_count': skill_count,
                        'reason': 'High score with insufficient data'
                    })
    
    return anomalies
```

### Output Format
**File**: `matching_db_evaluation_report.json`

```json
{
  "evaluation_date": "2026-03-22T10:30:00Z",
  "job_data_quality": {
    "total_jobs": 283,
    "jobs_without_skills": 183,
    "jobs_without_skills_pct": 64.66,
    "jobs_with_1_to_3_skills": 191,
    "jobs_with_1_to_3_skills_pct": 67.49,
    "skill_count": {
      "min": 0,
      "max": 6,
      "mean": 0.96,
      "median": 0
    }
  },
  "matching_score_distribution": {
    "all_scores": {
      "count": 283,
      "min": 0.0,
      "max": 1.0,
      "mean": 0.1342,
      "median": 0.027
    },
    "top_1_scores": {
      "mean": 0.1342,
      "median": 0.027,
      "low_confidence_count": 188,
      "low_confidence_pct": 66.43
    }
  },
  "anomalies": [
    {
      "cv_id": "cv_001",
      "job_id": 42,
      "match_score": 1.0,
      "skill_count": 1,
      "reason": "High score with insufficient data"
    }
  ]
}
```

### Key Findings

**Data Quality Issues**:
- 64.66% of jobs have no extracted skills (183/283)
- 67.49% of jobs have ≤3 skills (191/283)
- Median skills per job = 0

**Matching Quality Issues**:
- Mean match score = 0.1342 (very low)
- Median match score = 0.027
- 66.67% of top-1 matches score <0.3 (low confidence)
- Detected anomaly: 1 match with score 1.0 but only 1 job skill (false positive)

**Root Cause**: Sparse skill extraction in job data prevents reliable matching

### Libraries
- **statistics**: min/max/mean/median calculations
- **json, datetime**: I/O and timestamp operations

---

## DATA QUALITY CHECKPOINTS

### Checkpoint 1: Crawling → Cleaning (Stage 1-2)
| Check | Status | Details |
|-------|--------|---------|
| ✓ No HTML entities | PASS | Special chars normalized |
| ✓ URL format valid | PASS | Pattern matched against domains |
| ⚠️ Salary parseable | WARN | Fallback to NULL if unparseable |
| ⚠️ Requirements text present | WARN | Some jobs have empty requirements |
| ✓ Fingerprint unique | PASS | MD5 deduplication enforced |

### Checkpoint 2: Cleaning → DB (Stage 2-3)
| Check | Status | Details |
|-------|--------|---------|
| ✓ Foreign key integrity | PASS | All company_ids, skill_ids valid |
| ✓ Skill normalization | PASS | All skills in canonical form |
| ⚠️ Salary range valid | WARN | 15% of jobs have NULL salary |
| ✓ Experience level standard | PASS | Constrained to 4 values |
| ✓ Duplicate fingerprints | PASS | Database UNIQUE constraint |

### Checkpoint 3: DB → Matching (Stages 4-9)
| Check | Status | ISSUE |
|-------|--------|-------|
| ✓ Jobs exported | PASS | All 283 jobs successfully exported |
| ✗ Skill extraction quality | FAIL | 64.66% jobs have 0 skills |
| ✗ Skills per job | FAIL | 67.49% jobs have ≤3 skills |
| ✗ Matching discriminability | FAIL | 66.67% top-1 scores <0.3 |
| ⚠️ CV-JD family matching | WARN | Some jobs fall outside known families |

### Checkpoint 4: Before Production
**NOT READY** - Recommend:

1. **Improve skill extraction** (Stages 2-3):
   - Upgrade from rule-based to ML-based skill extraction
   - Manually curate skills for top 50 jobs
   - Use Gemini more aggressively (currently fallback-only)

2. **Implement confidence filtering** (Stage 8):
   - Only return matches with score > 0.3
   - Add confidence warnings for sparse jobs
   - Recommend manual review for scores 0.3-0.5

3. **Add short-term data filtering**:
   - Pre-filter jobs with <3 skills before matching
   - Show filtered count to users
   - Explain to users why some jobs excluded

4. **Implement Phase 2 enhancements**:
   - Semantic embedding (FastText, Word2Vec)
   - AHP-based skill weighting (requires training data)
   - Human-in-the-loop feedback loop

---

## EXECUTION SUMMARY

### How to Run Complete Pipeline

```bash
# 1. Crawl data
cd Db/1_crawl_data
./crawl_all_daily.bat

# 2. Clean and import
cd D:\Db
python run_etl_pipeline.py

# 3. Run matching
cd Matching
python 03_export_jobs_from_db.py      # Export jobs
python 04_extract_cv_profile_baseline.py  # Extract CVs
python 05_matching_engine.py           # Match CVs to jobs
python 07_evaluate_matching_db.py      # Evaluate results
```

### Directory Structure
```
JobVisualization_BE/
├── Db/
│   ├── 1_crawl_data/          # Stage 1: Crawling
│   ├── 2_clean_data/          # Stage 2: Cleaning
│   │   └── clean_process.py
│   ├── 3_mapping_data_db/     # Stage 3: DB Import
│   │   └── import_to_db.py
│   └── data/crawl_*/          # Output: raw data
├── Matching/
│   ├── 01_prepare_job_dataset.py       # Stage 4
│   ├── 02_extract_job_skills.py        # Stage 5
│   ├── 03_export_jobs_from_db.py       # Stage 6
│   ├── 04_extract_cv_profile_baseline.py # Stage 7
│   ├── 05_matching_engine.py           # Stage 8
│   ├── 07_evaluate_matching_db.py      # Stage 9
│   ├── jobs_from_db.json               # Stage 6 output
│   ├── cv_profiles_baseline.json       # Stage 7 output
│   ├── matching_results.json           # Stage 8 output
│   └── matching_db_evaluation_report.json  # Stage 9 output
└── PIPELINE_DOCUMENTATION.md           # This file
```

---

## PHASE 2: PLANNED ENHANCEMENTS

✅ **Current (Phase 3)**: Rule-based keyword matching  
🔄 **Planned (Phase 4-6)**:

1. **Semantic Matching Phase**:
   - Replace keyword matching with semantic embeddings
   - Use FastText or Word2Vec for skill vectors
   - Calculate `sim_i = cosine_similarity(cv_skill_vec, jd_skill_vec)`

2. **Weighted Scoring Phase**:
   - Implement AHP (Analytic Hierarchy Process) for skill weighting
   - Compute `w_i` values from job market data
   - Update matching formula: `S = Σ(w_i · cos_sim_i)`

3. **Evaluation Phase**:
   - Add human evaluation benchmarks
   - Measure recall/precision on gold-standard job-CV pairs
   - Implement confidence thresholds based on ground truth

---

## TECHNOLOGY STACK SUMMARY

| Stage | Component | Libraries | Status |
|-------|-----------|-----------|--------|
| 1 | Web Crawling | Selenium, BeautifulSoup4 | ✓ Active |
| 2 | Data Cleaning | Google Generativeai, regex, hashlib | ✓ Active (Gemini optional) |
| 3 | Database | PostgreSQL, psycopg2 | ✓ Active |
| 4-5 | Job Processing | regex, json | ✓ Active |
| 6 | DB Export | psycopg2, json | ✓ Active |
| 7 | CV Extraction | easyocr, pyresparser (optional) | ✓ Active |
| 8 | Matching Engine | json, pathlib, regex | ✓ Active (Phase 3) |
| 9 | Evaluation | statistics, json | ✓ Active |
| Phase 4+ | Embeddings | FastText, Word2Vec (planned) | 📋 Planned |
| Phase 5+ | Weighting | AHP library (planned) | 📋 Planned |

---

**Document Version**: 1.0  
**Author**: AI Assistant  
**Last Updated**: March 22, 2026  
**Status**: Complete (Phases 1-3 documented; Phases 4-6 planned)
