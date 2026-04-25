# 📁 Input Package - Configuration Made Easy

Tất cả config dễ chỉnh ở **một chỗ**. Chỉ cần edit 4 bảng, không code phức tạp!

---

## 📋 4 Bảng Chính (Edit ĐÂY!)

### 1️⃣ JOBS_PER_KEYWORD - Mỗi keyword crawl bao nhiêu jobs?
```python
JOBS_PER_KEYWORD = 3  # Mỗi keyword crawl 3 jobs
```

### 2️⃣ JOB_LIMITS - Chọn source nào crawl?
```python
JOB_LIMITS = {
    "careerviet": 0,      # 0 = skip, >0 = crawl
    "itviec": 3,
    "linkedin": 0,
    "vietnamworks": 2,
}
```

### 3️⃣ KEYWORD_SELECTION_CONFIG - Chọn bao nhiều keywords từ mỗi tier?
```python
KEYWORD_SELECTION_CONFIG = {
    "tier1": {
        "num_to_crawl": 1,              # Chọn 1 keyword
        "selection_method": "random",   # "random" hoặc "sequential"
        "enabled": True                 # Auto-set from num_to_crawl
    },
    "tier2": {"num_to_crawl": 0, ...},  # 0 = disable
    "tier3": {"num_to_crawl": 0, ...},
}
```

### 4️⃣ CRAWL_SETTINGS_TABLE - Settings khác (tùy chọn)
```python
CRAWL_SETTINGS_TABLE = {
    "parallel_crawlers": 4,
    "request_delay_min": 0.5,
    "request_delay_max": 1.5,
    "max_retries": 2,
}
```

---

## 🔧 Lựa Chọn: Edit `.env` hoặc `config_jobs.py`?

### Option A: Edit `config_jobs.py` (một lần)
```python
# Db/input/config_jobs.py
JOBS_PER_KEYWORD = 5
JOB_LIMITS = {"careerviet": 3, ...}
```

### Option B: Dùng `.env` Override (thay đổi nhanh)
```bash
# .env file
JOBS_PER_KEYWORD=5
CRAWL_CAREERVIET_JOBS=3
TIER1_NUM_KEYWORDS=2
```

**Priority:** `.env` > `config_jobs.py` (`.env` override)

---

## 📊 Ví Dụ Thực Tế

### Ví dụ 1: Quick Test
```python
# Kết quả: 1 keyword tier1 × 3 jobs/keyword = 3 jobs
JOBS_PER_KEYWORD = 3
JOB_LIMITS = {"careerviet": 3, ...others 0}
KEYWORD_SELECTION_CONFIG["tier1"]["num_to_crawl"] = 1
```

### Ví dụ 2: Heavy Production
```python
# Kết quả: 5 keywords × 5 jobs/keyword per source = nhiều jobs
JOBS_PER_KEYWORD = 5
JOB_LIMITS = {"itviec": 5, "linkedin": 3}
KEYWORD_SELECTION_CONFIG["tier1"]["num_to_crawl"] = 3
KEYWORD_SELECTION_CONFIG["tier2"]["num_to_crawl"] = 2
```

---

## 🧪 Xem Config Hiện Tại

```bash
cd JobVisualization_BE
python -m Db.input.config_jobs
```

Output:
```
📊 KEYWORD & JOB CONFIGURATION
Tier       Num to Crawl    Method       Enabled
tier1      1               random       ✓
tier2      0               sequential   ✗
...
💼 JOBS CONFIGURATION:
  Jobs per keyword: 3
🌐 CRAWL SOURCES:
  ✓ careerviet: 3 jobs/keyword
...
```

---

## 📂 File Structure

```
input/
├── __init__.py              # Exports everything
├── config_api.py            # API keys (auto-detect from .env)
├── config_jobs.py           # ← EDIT THIS (jobs + keywords)
├── config_db.py             # Database (fixed)
├── README.md                # ← You're here!
└── data/
    ├── keywords_daily.json  # Static keywords
    └── README.md
```

---

## 🔑 API Keys - Auto-Detect

**File:** `config_api.py`

Scan `.env` tự động:
```bash
# .env
GEMINI_API_KEY_1=key1
GEMINI_API_KEY_2=key2
GEMINI_API_KEY_3=key3
GEMINI_API_KEY_4=key4  # ← Thêm key mới - không cần edit code!
```

**Dùng:**
```python
from Db.input import get_api_key
key = get_api_key("gemini")
```

---

## 📁 Keywords - Static Data

**File:** `data/keywords_daily.json`

```json
{
  "tier1": ["python", "java", "javascript", ...],
  "tier2": ["frontend", "backend", ...],
  "tier3": ["devops", ...]
}
```

**Load:**
```python
from Db.input import load_keywords, get_keywords_count

keywords = load_keywords()
counts = get_keywords_count()  # {"tier1": 8, "tier2": 5, "tier3": 3, "total": 16}
```

---

## 💻 Code Usage

```python
# Import configs
from Db.input import (
    JOB_LIMITS,
    JOBS_PER_KEYWORD,
    KEYWORD_SELECTION_CONFIG,
    load_keywords,
    calculate_total_keywords,
    calculate_total_jobs,
    estimate_crawl_time,
    print_config,
)

# Use
print_config()  # Pretty print
jobs = calculate_total_jobs()  # {"keywords": 1, "jobs_per_keyword": 3, "total_jobs": 3, ...}
keywords = load_keywords()  # {"tier1": [...], "tier2": [...], ...}
```

---

## ✅ Validation

Chạy test:
```bash
python -m Db.input.config_jobs
python -m Db.input.config_api
python -m Db.input.config_db
```

---

## 🎯 Cheat Sheet

| Want to | Where | How |
|---------|-------|-----|
| Change jobs/keyword | `config_jobs.py` line 22 | `JOBS_PER_KEYWORD = 5` |
| Enable source | `config_jobs.py` line 25+ | `"itviec": 5` |
| Choose keywords/tier | `config_jobs.py` line 41+ | `"num_to_crawl": 2` |
| Override in .env | `.env` | `JOBS_PER_KEYWORD=5` |
| Add API key | `.env` | `GEMINI_API_KEY_4=xxx` |
| Update keywords | `data/keywords_daily.json` | Edit keywords array |

---

✨ **Tất cả config tập trung ở một chỗ - dễ hiểu, dễ chỉnh!**
