# JobVisualization Backend

Hệ thống backend cho nền tảng phân tích và trực quan hóa thị trường tuyển dụng IT. Pipeline tự động thu thập dữ liệu tuyển dụng từ nhiều nguồn, chuẩn hóa skill bằng AI/Embedding, tính trọng số TF-IDF, và hỗ trợ matching CV với yêu cầu công việc.

---

## Mục lục

- [Kiến trúc tổng quan](#kiến-trúc-tổng-quan)
- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt môi trường](#cài-đặt-môi-trường)
- [Cấu hình](#cấu-hình)
- [Khởi tạo cơ sở dữ liệu](#khởi-tạo-cơ-sở-dữ-liệu)
- [Chạy ETL Pipeline (Crawl → Clean → Import)](#chạy-etl-pipeline)
- [Cập nhật trọng số Skill (SkillWeighting)](#cập-nhật-trọng-số-skill)
- [Matching CV](#matching-cv)
- [Chạy từng bước riêng lẻ](#chạy-từng-bước-riêng-lẻ)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Troubleshooting](#troubleshooting)

---

## Kiến trúc tổng quan

```
┌─────────────────────────────────────────────────────────────────┐
│                        ETL PIPELINE                             │
│  Db/run_etl_pipeline.py  (Orchestrator chính)                   │
│                                                                 │
│  BƯỚC 1 - CRAWL                                                 │
│  ├─ ITviec / LinkedIn / CareerViet / VietnamWorks               │
│  └─ merge_daily_outputs.py  →  raw/jobs_combined.json          │
│                                                                 │
│  BƯỚC 2 - CLEAN & EXTRACT & NORMALIZE                          │
│  ├─ clean_process.py          →  pending_llm.json              │
│  ├─ process_pending_llm.py    →  extracted.json  (Gemini LLM)  │
│  └─ normalize_embeddings.py   →  normalized.json (+ cache)     │
│                                                                 │
│  BƯỚC 3 - IMPORT                                               │
│  └─ import.py → PostgreSQL (job_skills, unmatched_skills…)     │
│       └── auto-trigger: tf_idf.py / build_skill_weights.py     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    SKILL WEIGHTING (SkillWeighting/)            │
│  tf_idf.py              – Tính TF-IDF nhanh từ DB              │
│  build_skill_weights.py – Build weight có LLM (deep mode)      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      CV MATCHING (matching_cv/)                 │
│  match_cv.py  – Gemini extract + Embedding normalize + Score   │
└─────────────────────────────────────────────────────────────────┘
```

**Luồng dữ liệu đầy đủ:**

```
[Trang tuyển dụng] → Crawl → Raw JSON
    → Clean (fuzzy dedup) → pending_llm.json
    → Gemini LLM Extract → extracted.json
    → Embedding Normalize (cache) → normalized.json
    → Import → PostgreSQL
    → TF-IDF Weight Update → public.skill_weights
    → CV Matching → Kết quả điểm tương đồng
```

---

## Yêu cầu hệ thống

| Thành phần | Phiên bản tối thiểu |
|---|---|
| Python | 3.10+ |
| PostgreSQL | 14+ |
| RAM | 4 GB (8 GB khuyến nghị cho embedding) |
| OS | Windows 10+ / Ubuntu 20.04+ |

---

## Cài đặt môi trường

### 1. Clone repository

```bash
git clone <repo-url>
cd JobVisualization_BE
```

### 2. Tạo và kích hoạt môi trường ảo (Virtual Environment)

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

> **Lưu ý:** Toàn bộ script trong project sẽ tự động sử dụng `.venv` nếu tìm thấy trong thư mục gốc. Không cần kích hoạt thủ công khi chạy qua `run_etl_pipeline.py`.

### 3. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

Các thư viện chính bao gồm:
- `psycopg2-binary` – Kết nối PostgreSQL
- `sentence-transformers` – Embedding model (all-MiniLM-L6-v2)
- `google-generativeai` – Gemini API (LLM extract)
- `python-dotenv` – Quản lý cấu hình .env
- `numpy`, `scipy` – Tính toán similarity

---

## Cấu hình

### 1. Sao chép file cấu hình mẫu

```bash
cp .env.example .env
```

### 2. Chỉnh sửa `.env` (ở thư mục gốc dự án)

```env
# ── DATABASE ──────────────────────────────────────────────
DB_HOST=localhost
DB_PORT=5432
DB_NAME=job_db
DB_USER=postgres
DB_PASSWORD=your_password

# ── GEMINI API KEYS (tự động rotate khi hết quota) ────────
GEMINI_API_KEY_1=your_api_key_1
GEMINI_API_KEY_2=your_api_key_2   # thêm tùy ý

# ── CRAWL SOURCES (0 = bỏ qua, ≥1 = kích hoạt) ───────────
CRAWL_ITVIEC_JOBS=1
CRAWL_CAREERVIET_JOBS=1
CRAWL_LINKEDIN_JOBS=0
CRAWL_VIETNAMWORKS_JOBS=1

# ── SỐ JOB MỖI KEYWORD ────────────────────────────────────
JOBS_PER_KEYWORD=5

# ── KEYWORD SELECTION ──────────────────────────────────────
TIER1_NUM_KEYWORDS=2
TIER1_SELECTION_METHOD=random     # "random" hoặc "sequential"

# ── PIPELINE STEPS (bật/tắt từng bước) ────────────────────
PIPELINE_CRAWL=true
PIPELINE_CLEAN=true
PIPELINE_IMPORT=true
```

> **Quan trọng:** File `Db/.env` chứa cấu hình riêng cho pipeline bên trong thư mục `Db/`. Đây là file được pipeline orchestrator load trực tiếp. Hãy chỉnh sửa file này cho môi trường production.

### 3. Lấy Gemini API Key

1. Truy cập [Google AI Studio](https://aistudio.google.com/)
2. Tạo API Key mới
3. Điền vào `GEMINI_API_KEY_1` trong `.env`

> Hệ thống hỗ trợ nhiều API key (`GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, ...) và tự động rotate sang key tiếp theo khi hết quota.

---

## Khởi tạo cơ sở dữ liệu

### 1. Tạo database PostgreSQL

```sql
-- Chạy trong psql hoặc pgAdmin
CREATE DATABASE job_db;
```

### 2. Áp dụng schema

```bash
# Import toàn bộ schema (bảng, index, constraint)
psql -U postgres -d job_db -f schema_only.sql

# (Tùy chọn) Import master data mẫu (skills, search groups…)
psql -U postgres -d job_db -f master_data.sql
```

### 3. Kiểm tra kết nối

```bash
.venv/Scripts/python.exe -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv('Db/.env')
conn = psycopg2.connect(host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT',5432), dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
print('Connected:', conn.get_dsn_parameters())
conn.close()
"
```

---

## Chạy ETL Pipeline

Pipeline chính được điều phối bởi [`Db/run_etl_pipeline.py`](Db/run_etl_pipeline.py). Mỗi lần chạy tạo ra một thư mục lưu trữ theo timestamp: `Db/data/crawl_YYYYMMDD_HHMMSS/`.

### Chạy toàn bộ pipeline (Crawl → Clean → Import)

```bash
# Chạy từ thư mục Db/
cd Db
.venv/Scripts/python.exe run_etl_pipeline.py
```

Hoặc từ thư mục gốc:

```bash
.venv/Scripts/python.exe Db/run_etl_pipeline.py
```

**Các bước sẽ được thực hiện tự động:**

| Bước | Script | Mô tả |
|------|--------|--------|
| 1. Crawl | `crawl-itviec-jobs/`, `crawl-careerviet-jobs/`, ... | Thu thập job từ các trang tuyển dụng |
| 1b. Merge | `merge_daily_outputs.py` | Gộp output của các crawler thành `jobs_combined.json` |
| 2a. Clean | `clean_process.py` | Làm sạch, loại trùng lặp → `pending_llm.json` |
| 2b. Extract | `process_pending_llm.py` | Gemini trích xuất skill → `extracted.json` |
| 2c. Normalize | `normalize_embeddings.py` | Chuẩn hóa skill qua embedding + cache → `normalized.json` |
| 3. Import | `import.py` | Đưa dữ liệu vào PostgreSQL, tự cập nhật trọng số |

### Các tùy chọn chạy

```bash
# Chỉ chạy bước Crawl
python run_etl_pipeline.py --crawl-only

# Chỉ chạy bước Clean (dùng file có sẵn)
python run_etl_pipeline.py --clean-only --input Db/data/crawl_20260522_103000/raw/jobs_combined.json

# Chỉ chạy bước Import
python run_etl_pipeline.py --import-only

# Bỏ qua bước Import (crawl + clean only)
python run_etl_pipeline.py --skip-import

# Bỏ qua LLM extract (dùng file extracted sẵn)
python run_etl_pipeline.py --extracted path/to/extracted.json

# Bỏ qua Normalize (dùng file normalized sẵn)
python run_etl_pipeline.py --normalized path/to/normalized.json

# Chỉ chạy một bước cụ thể
python run_etl_pipeline.py --step crawl
python run_etl_pipeline.py --step clean
python run_etl_pipeline.py --step import
python run_etl_pipeline.py --step extract --input path/to/pending_llm.json
```

### Output sau khi chạy

```
Db/data/crawl_YYYYMMDD_HHMMSS/
├── raw/
│   └── jobs_combined.json       ← Dữ liệu thô từ crawler
├── clean/
│   ├── pending_llm.json         ← Sau bước clean
│   ├── extracted.json           ← Sau bước LLM extract
│   └── normalized.json          ← Sau bước normalize (input cho import)
├── fallback/
│   └── import_fallback.json     ← Jobs import thất bại
└── logs/
    └── pipeline.log
```

---

## Cập nhật trọng số Skill

Trọng số TF-IDF được **tự động tính lại** mỗi khi import xong. Tuy nhiên, bạn cũng có thể chạy thủ công:

### Cập nhật nhanh (chỉ TF-IDF từ DB)

```bash
# Chạy từ thư mục gốc
.venv/Scripts/python.exe SkillWeighting/tf_idf.py
```

Tính TF-IDF từ dữ liệu `job_skills` hiện có trong DB và upsert vào bảng `skill_weights`.

### Cập nhật đầy đủ (TF-IDF + LLM-based weighting)

```bash
# Chạy cho toàn bộ search groups
.venv/Scripts/python.exe SkillWeighting/build_skill_weights.py

# Chỉ một search group cụ thể
.venv/Scripts/python.exe SkillWeighting/build_skill_weights.py --search-group "backend developer"

# Dry run (không ghi vào DB)
.venv/Scripts/python.exe SkillWeighting/build_skill_weights.py --dry-run

# Giới hạn số search groups xử lý
.venv/Scripts/python.exe SkillWeighting/build_skill_weights.py --limit 5

# Ghi đè toàn bộ (xóa data cũ trước khi ghi)
.venv/Scripts/python.exe SkillWeighting/build_skill_weights.py --replace
```

---

## Matching CV

Module [`matching_cv/match_cv.py`](matching_cv/match_cv.py) thực hiện:
1. Trích xuất text từ file CV (PDF/PNG/JPG)
2. Gemini extract danh sách skill từ CV text
3. Chuẩn hóa skill CV qua Lightcast Normalizer + embedding cache
4. Tính điểm tương đồng với `skill_weights` trong DB
5. Lưu skill không match vào `unmatched_skill_sources`

### Cú pháp

```bash
.venv/Scripts/python.exe -m matching_cv.match_cv \
    --cv path/to/cv.pdf \
    --search-group "backend developer" \
    [--threshold-possessed 0.75] \
    [--threshold-partial 0.3] \
    [--confidence-threshold 0.85] \
    [--source-id 123]
```

### Tham số

| Tham số | Bắt buộc | Mặc định | Mô tả |
|---------|----------|---------|-------|
| `--cv` | ✅ | — | Đường dẫn file CV (PDF, PNG, JPG, JPEG) |
| `--search-group` | ✅ | — | Nhóm công việc cần so sánh (ví dụ: `"backend developer"`) |
| `--threshold-possessed` | ❌ | `0.75` | Ngưỡng similarity để coi là "có skill" |
| `--threshold-partial` | ❌ | `0.30` | Ngưỡng similarity để coi là "partial match" |
| `--confidence-threshold` | ❌ | `0.85` | Ngưỡng confidence của Gemini khi extract skill |
| `--source-id` | ❌ | `0` | ID sinh viên/ứng viên (để lưu vào DB) |

### Ví dụ

```bash
# Match CV của sinh viên với yêu cầu vị trí Backend Developer
.venv/Scripts/python.exe -m matching_cv.match_cv \
    --cv matching_cv/cv/student_cv.pdf \
    --search-group "backend developer" \
    --source-id 42

# Xem danh sách search_group có sẵn trong DB
psql -U postgres -d job_db -c "SELECT DISTINCT search_group FROM skill_weights ORDER BY 1;"
```

### Output mẫu

```
2026-05-22 23:30:00 INFO Fetching weights from database for search group: backend developer
2026-05-22 23:30:01 INFO Loaded 87 target skills for 'backend developer' from DB.
2026-05-22 23:30:02 INFO Extracted 24 skills from CV using Gemini.
2026-05-22 23:30:03 INFO Successfully normalized and mapped 21 skills to DB skill IDs.
2026-05-22 23:30:04 INFO Logging 3 unmatched CV skills to database (source_id: 42)...

=== MATCHING RESULT ===
Total target skills  : 87
Possessed skills     : 15  (17.2%)
Partial match skills : 4   (4.6%)
Missing skills       : 68  (78.2%)
Match score          : 62.4 / 100
```

---

## Chạy từng bước riêng lẻ

### Chỉ crawl một nguồn cụ thể

```bash
cd Db/pipeline/crawl/1_crawl_data
python crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py
```

### Chỉ normalize một file

```bash
.venv/Scripts/python.exe Db/pipeline/normalize/2_1_normalized_data/normalize_embeddings.py \
    --input Db/data/crawl_20260522_103000/clean/extracted.json \
    --output Db/data/crawl_20260522_103000/clean/normalized.json
```

### Kiểm tra cache mapping skill

```bash
# Xem cache đã có bao nhiêu entry
python -c "
import json; from pathlib import Path
cache = Path('Db/pipeline/normalize/2_1_normalized_data/cache/mapped_skills_cache.json')
data = json.loads(cache.read_text()) if cache.exists() else {}
print(f'Cache entries: {len(data)}')
"
```

### Import thủ công từ file normalized

```bash
.venv/Scripts/python.exe Db/pipeline/import/3_import/import.py \
    --input Db/data/crawl_20260522_103000/clean/normalized.json \
    --fallback Db/data/crawl_20260522_103000/fallback/import_fallback.json
```

### Kiểm tra nhanh kiến trúc hệ thống

```bash
.venv/Scripts/python.exe "C:\Users\ASUS\.gemini\antigravity\brain\c0b2cb5c-6a5a-4110-9858-2895d0e057a3\scratch\verify_architecture.py"
```

---

## Cấu trúc thư mục

```
JobVisualization_BE/
│
├── .env                          ← Cấu hình toàn dự án
├── .env.example                  ← Template cấu hình mẫu
├── requirements.txt              ← Python dependencies
├── schema_only.sql               ← Database schema
├── master_data.sql               ← Dữ liệu mẫu (skills, categories…)
│
├── Db/                           ← ETL Pipeline chính
│   ├── run_etl_pipeline.py       ← Orchestrator (điểm vào chính)
│   ├── .env                      ← Cấu hình pipeline riêng
│   ├── input/                    ← Config keywords, API keys…
│   └── pipeline/
│       ├── crawl/
│       │   └── 1_crawl_data/
│       │       ├── crawl_data/
│       │       │   ├── crawl-itviec-jobs/
│       │       │   ├── crawl-careerviet-jobs/
│       │       │   ├── crawl-linkedin-jobs/
│       │       │   └── crawl-vietnamwork-jobs/
│       │       └── merge_daily_outputs.py
│       ├── clean/
│       │   └── 2_clean_data/
│       │       └── clean_process.py
│       ├── extract/
│       │   └── process_pending_llm.py    ← Gemini skill extraction
│       ├── normalize/
│       │   └── 2_1_normalized_data/
│       │       ├── normalize_embeddings.py  ← Embedding + cache
│       │       └── cache/
│       │           └── mapped_skills_cache.json  ← Cache mapping
│       └── import/
│           └── 3_import/
│               └── import.py             ← DB import + weight trigger
│
├── SkillWeighting/               ← Tính trọng số skill
│   ├── tf_idf.py                 ← TF-IDF nhanh từ DB
│   ├── build_skill_weights.py    ← Build weight đầy đủ (LLM+TF-IDF)
│   └── fetch_job_skills.py       ← Fetch raw data từ DB
│
└── matching_cv/                  ← CV Matching
    ├── match_cv.py               ← Entry point chính
    ├── matching_engine.py        ← Thuật toán tính điểm
    ├── normalizer.py             ← Chuẩn hóa skill CV
    ├── utils.py                  ← Tiện ích (extract PDF, load env…)
    ├── cv/                       ← Thư mục chứa file CV
    └── prompts/
        └── extract_cv_skills.md  ← Prompt Gemini extract skill
```

---

## Troubleshooting

### Lỗi kết nối Database

```
psycopg2.OperationalError: could not connect to server
```
→ Kiểm tra PostgreSQL đang chạy và thông tin trong `.env` / `Db/.env` chính xác.

---

### Lỗi Gemini API quota

```
RuntimeError: No active Gemini API keys available. All keys may be in cooldown.
```
→ Thêm API key dự phòng (`GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`) trong `.env`. Hệ thống tự rotate.

---

### Lỗi encoding trên Windows

```
UnicodeEncodeError: 'charmap' codec can't encode character
```
→ Đặt biến môi trường trước khi chạy:
```powershell
$env:PYTHONIOENCODING = "utf-8"
python run_etl_pipeline.py
```

---

### Embedding model chậm / OOM

Lần đầu chạy `normalize_embeddings.py` sẽ tải model `all-MiniLM-L6-v2` (~90MB). Sau đó cache sẽ được dùng để bỏ qua re-embedding cho các cặp skill đã biết.

Nếu hết RAM, giảm batch size trong `Db/.env`:
```env
ETL_CLEAN_BATCH_SIZE=20
```

---

### Crawl không lấy được dữ liệu

→ Kiểm tra các nguồn được kích hoạt trong `Db/.env`:
```env
CRAWL_ITVIEC_JOBS=1   # phải > 0 mới crawl
```
→ Kiểm tra timeout crawler nếu mạng chậm:
```env
ETL_LLM_TIMEOUT=3600  # tăng lên 1 giờ
```

---

### Re-run từ bước normalize trở đi (bỏ qua crawl và extract)

Nếu đã có file `extracted.json` và chỉ muốn chạy lại từ normalize + import:

```bash
python Db/run_etl_pipeline.py \
    --extracted Db/data/crawl_20260522_103000/clean/extracted.json
```

Hoặc nếu đã có `normalized.json`:

```bash
python Db/run_etl_pipeline.py \
    --normalized Db/data/crawl_20260522_103000/clean/normalized.json \
    --import-only
```

---

## Lịch chạy tự động (Tùy chọn)

Để chạy pipeline hàng ngày, tạo Windows Scheduled Task hoặc cron job:

**Windows Task Scheduler:**
```powershell
# Chạy pipeline lúc 2:00 AM mỗi ngày
schtasks /create /tn "JobVisualization ETL" /tr "powershell -File C:\path\to\run_daily.ps1" /sc daily /st 02:00
```

**`run_daily.ps1`:**
```powershell
Set-Location "F:\HCMUS_KH\LuanVan\JobVisualization_BE\Db"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe run_etl_pipeline.py
```

---

*Được tạo tự động bởi hệ thống phân tích kiến trúc · JobVisualization_BE*
