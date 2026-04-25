# 📁 Db Module - Cấu Trúc Thư Mục và Vai Trò File

## 🎯 Mục Đích Module
**Db** (Database) là module chính chịu trách nhiệm:
- 🔍 **CRAWL**: Thu thập dữ liệu từ các job sites
- 🧹 **CLEAN**: Làm sạch, chuẩn hóa dữ liệu
- 📤 **IMPORT**: Đưa dữ liệu vào PostgreSQL database

---

## 📂 Cấu Trúc Thư Mục

```
Db/
├── 📄 FILES CHÍNH (Root Level)
│   ├── etl_config.py              ← Cấu hình pipeline (JOB_LIMITS, timeout)
│   ├── run_etl_pipeline.py        ← Script chính chạy full pipeline (CRAWL+CLEAN+IMPORT)
│   ├── quick_test.py              ← Script test nhanh (8 keywords × 1 job ≈ 2 phút)
│   ├── requirements.txt           ← Python dependencies
│   ├── keywords_daily.json        ← Danh sách keywords cho crawl (tier1, tier2, tier3)
│   ├── .env                       ← Environment variables (password, API keys)
│   ├── .env.example               ← Template .env
│   └── README.md                  ← Documentation
│
├── 🔍 1_crawl_data/               ← BỘ PHẬN 1: Crawling
│   ├── crawl_data/
│   │   ├── crawl-itviec-jobs/
│   │   │   └── scripts/daily_itviec_runner.py
│   │   ├── crawl-linkedin-jobs/
│   │   │   └── scripts/daily_linkedin_runner.py
│   │   ├── crawl-careerviet-jobs/
│   │   │   └── scripts/daily_careerviet_runner.py
│   │   └── crawl-vietnamwork-jobs/
│   │       └── scripts/daily_vietnamworks_runner.py
│   ├── merge_daily_outputs.py     ← Merge output từ 4 crawlers
│   ├── normalize_schema.py        ← Normalize schema
│   └── keywords_daily.json        ← Keywords config
│
├── 🧹 2_clean_data/               ← BỘ PHẬN 2: Cleaning & Normalization  
│   ├── clean_process.py           ← Main cleaning script
│   ├── batch_process_daily.py     ← Batch processing (LLM + Fuzzy)
│   ├── constants.py               ← 5648 kỹ năng chuẩn
│   ├── skill_extraction_llm.py    ← Google AI extraction
│   ├── skill_translator.py        ← Dịch kỹ năng
│   ├── embedding_matcher.py       ← Fuzzy matching
│   ├── cache_manager.py           ← Cache management
│   ├── .env                       ← Google API keys
│   ├── requirements.txt           ← Dependencies
│   ├── cache/                     ← Cache folder (skills, merged results)
│   ├── input/                     ← Input folder
│   ├── output/                    ← Output folder
│   └── README.md
│
├── 📤 3_mapping_data_db/          ← BỘ PHẬN 3: Import to Database
│   ├── import_to_db.py            ← Main import script
│   ├── CreateDB.sql               ← Schema definition
│   ├── import_skills_with_type.py ← Import skills master data
│   ├── sync_db_with_excel.py      ← Sync with Excel
│   ├── .env                       ← DB connection config
│   ├── requirements.txt
│   ├── DatabaseStructure.md       ← DB schema docs
│   └── sql/                       ← SQL scripts (alter, reset, etc.)
│
├── 💾 data/                       ← OUTPUT: Archive dữ liệu theo ngày
│   ├── crawl_20260414_144553/     (Format: crawl_YYYYMMDD_HHMMSS)
│   │   ├── raw/                   ← Raw data từ crawlers
│   │   │   ├── itviec_*.json
│   │   │   ├── linkedin_*.json
│   │   │   └── jobs_combined.json  (Merged)
│   │   └── clean/                 ← Cleaned data
│   │       ├── jobs_clean_merged.json
│   │       └── batch_*.json        (Batch files)
│   ├── crawl_20260413_152250/     (Previous run)
│   └── ...
│
├── 🐛 debug/                      ← DEBUG: Logs & diagnostics
│   └── log.md                     ← Debug log file
│
└── 🔧 .venv/                      ← Python virtual environment (tự động)
```

---

## 📋 Vai Trò Từng File / Thư Mục

### **Root Level Files**

| File | Vai Trò | Bắt Buộc? |
|------|---------|----------|
| `etl_config.py` | Config pipeline: job limits, timeouts | ✅ Yes |
| `run_etl_pipeline.py` | Chạy full pipeline (crawl → clean → import) | ✅ Yes |
| `quick_test.py` | Test nhanh: 8 keywords × 1 job ≈ 2 phút | ⚠️ Optional |
| `requirements.txt` | Python dependencies | ✅ Yes |
| `keywords_daily.json` | Danh sách keywords (tier1, tier2, tier3) | ✅ Yes |
| `.env` | Environment secrets (passwords, API keys) | ✅ Yes |
| `.env.example` | Template .env để guide cấu hình | ⚠️ Optional |
| `README.md` | Documentation tổng quát | ⚠️ Optional |

### **1_crawl_data/ - Crawling Phase**

| Component | Vai Trò |
|-----------|---------|
| `crawl-itviec-jobs/` | ITviec crawler (nhanh nhất: ~8s/job) |
| `crawl-linkedin-jobs/` | LinkedIn crawler (chậm: ~18s/job) |
| `crawl-careerviet-jobs/` | CareerViet crawler (~12s/job) |
| `crawl-vietnamwork-jobs/` | VietnamWorks crawler (~15s/job) |
| `merge_daily_outputs.py` | Merge & deduplicate từ 4 sources |
| `normalize_schema.py` | Chuẩn hóa schema dữ liệu |

**Output:** `data/crawl_YYYYMMDD_HHMMSS/raw/jobs_combined.json`

### **2_clean_data/ - Cleaning Phase**

| Component | Vai Trò |
|-----------|---------|
| `batch_process_daily.py` | **Main**: Xử lý batch jobs (Fuzzy 78% + Google AI 22%) |
| `skill_extraction_llm.py` | Google Generative AI extraction |
| `embedding_matcher.py` | Fuzzy matching against 5648 skills |
| `constants.py` | Kho 5648 kỹ năng chuẩn từ DB |
| `cache_manager.py` | Lưu cache tránh call API lặp lại |
| `cache/` | Folder cache (skills, merged results) |

**Input:** `data/crawl_YYYYMMDD_HHMMSS/raw/jobs_combined.json`
**Output:** `data/crawl_YYYYMMDD_HHMMSS/clean/jobs_clean_merged.json`

### **3_mapping_data_db/ - Import Phase**

| Component |Vai Trò |
|-----------|---------|
| `import_to_db.py` | **Main**: Import cleaned data vào PostgreSQL |
| `CreateDB.sql` | Schema definition (jobs table, skills table, etc.) |
| `import_skills_with_type.py` | Import Master Skills data từ Excel |
| `DatabaseStructure.md` | DB schema documentation |
| `sql/` | Utility scripts (alter, reset, sync) |

**Input:** `data/crawl_YYYYMMDD_HHMMSS/clean/jobs_clean_merged.json`
**Destination:** PostgreSQL database

### **data/ - Archive Folder**

```
data/
├── crawl_20260414_152250/      ← 1 run = 1 folder
│   ├── raw/                    ← Raw crawled files
│   │   ├── itviec_*.json       ← Individual job files
│   │   ├── linkedin_*.json
│   │   └── jobs_combined.json  ← Merged
│   └── clean/                  ← Cleaned files
│       └── jobs_clean_merged.json
├── crawl_20260413_144553/      ← Previous run
└── ...                         ← Archived for future reference
```

**Naming Convention:** `crawl_YYYYMMDD_HHMMSS`
- **YYYY** = Year (2026)
- **MM** = Month (04)
- **DD** = Day (14)
- **HH** = Hour (15)
- **MM** = Minute (22)
- **SS** = Second (50)

---

## 🔄 Data Flow

```
keywords_daily.json (8 tier1 + 2 tier2 keywords)
        ↓
[CRAWL PHASE - 1_crawl_data/]
    ├─→ daily_itviec_runner.py     (iTviec: ~8s/job)
    ├─→ daily_linkedin_runner.py   (LinkedIn: ~18s/job)
    ├─→ daily_careerviet_runner.py (CareerViet: ~12s/job)
    └─→ merge_daily_outputs.py     → jobs_combined.json
        ↓
    data/crawl_YYYYMMDD_HHMMSS/raw/
        ↓
[CLEAN PHASE - 2_clean_data/]
    batch_process_daily.py:
        ├─→ Fuzzy match (78%) → embedding_matcher.py
        ├─→ Google AI (22%) → skill_extraction_llm.py
        ├─→ Cache results → cache_manager.py
        └─→ Output → jobs_clean_merged.json
        ↓
    data/crawl_YYYYMMDD_HHMMSS/clean/
        ↓
[IMPORT PHASE - 3_mapping_data_db/]
    import_to_db.py:
        ├─→ Validate fingerprint (no duplicates)
        ├─→ Insert jobs, skills, benefits
        └─→ Map relationships
        ↓
    PostgreSQL Database
```

---

## ⚙️ Key Configurations

### etl_config.py
```python
JOB_LIMITS = {
    "itviec": 0,           # Số jobs/source (0 = skip)
    "linkedin": 0,
    "careerviet": 0,
    "vietnamworks": 0
}
TIER1_JOBS_PER_KEYWORD = 10  # Jobs per keyword
TIER2_JOBS_PER_KEYWORD = 8
CRAWLER_TIMEOUT = 1200  # 20 phút
CLEAN_TIMEOUT = 600     # 10 phút
IMPORT_TIMEOUT = 900    # 15 phút
```

### .env (Secrets)
```
GOOGLE_API_KEY=xxx
POSTGRES_USER=postgres
POSTGRES_PASSWORD=xxx
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=job_db
```

---

## 🚀 Quickstart

### **Test Nhanh (2 phút)**
```bash
cd Db
python quick_test.py
```

### **Full Pipeline Production (10+ phút)**
```bash
python run_etl_pipeline.py
```

### **Just Crawl**
```bash
cd 1_crawl_data
python crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py
```

### **Just Clean**
```bash
cd 2_clean_data
python batch_process_daily.py <input_file>
```

### **Just Import**
```bash
cd 3_mapping_data_db
python import_to_db.py --input <cleaned_file>
```

---

## 📊 Performance Benchmarks

| Phase | Nguồn | Jobs | Time | Notes |
|-------|-------|-------|------|-------|
| **CRAWL** | iTviec | 8 keywords × 1 job | ~60s | Nhanh nhất |
| **CRAWL** | LinkedIn | 8 keywords × 1 job | ~150s | Chậm nhất |
| **MERGE** | All | ~10 files | ~10s | Nhanh |
| **CLEAN** | Batch | 6-10 jobs | ~40-60s | Phụ thuộc API |
| **IMPORT** | DB | ~10 jobs | ~30s | Nhanh |
| **TOTAL** | End-to-end | Full clean | ~3-5 phút | Test config |

---

## 🔧 Troubleshooting Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Crawl timeout" | Quá nhiều jobs | Giảm `JOB_LIMITS` hoặc `TIER1_JOBS_PER_KEYWORD` |
| "Clean timeout" | Batch quá lớn | Giảm `BATCH_SIZE` từ 10 → 5 |
| "API rate limit" | Gọi Google API quá nhanh | Tăng delay trong `skill_extraction_llm.py` |
| "DB connection error" | .env config sai | Check `POSTGRES_*` vars trong `.env` |
| "Duplicate jobs" | Fingerprint không unique | Run `reset_jobs_pk_uniq.sql` |

---

## 📝 File không cần thiết (có thể xóa)

Các file sau có thể xóa nếu không sử dụng:
- `run_etl_pipeline_test.py` (replaced by quick_test.py)
- `config_api.py` (old config)
- `estimate_runtime.py` (merged vào run_etl_pipeline.py)
- Các `.bak`, `temp_*.json` files

Mặc dù folder `data/debug/` được tạo tự động, những file trong đó có thể xóa để giải phóng dung lượng.

---

## 📚 Next Steps

1. **Configure .env** → Add POSTGRES credentials
2. **Run quick_test.py** → Verify setup works
3. **Setup database** → Run `3_mapping_data_db/CreateDB.sql`
4. **Full run** → `python run_etl_pipeline.py`
5. **Analyze results** → Check `data/crawl_YYYYMMDD_HHMMSS/clean/` folder
