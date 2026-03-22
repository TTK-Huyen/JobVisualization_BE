# Quy Trình Pipeline So Khớp CV-JD

**Hệ thống**: Job Visualization & CV-Job Matching  
**Trạng thái**: Giai đoạn 1-3 Hoàn thành | Giai đoạn 4-7 Triển khai

---

## MỤC LỤC
1. [Tổng quan Pipeline](#tổng-quan-pipeline)
2. [Bước 1: Thu thập dữ liệu (Crawling)](#bước-1-thu-thập-dữ-liệu-crawling)
3. [Bước 2: Làm sạch dữ liệu & xử lý AI](#bước-2-làm-sạch-dữ-liệu--xử-lý-ai)
4. [Bước 3: Nhập vào cơ sở dữ liệu](#bước-3-nhập-vào-cơ-sở-dữ-liệu)
5. [Bước 4: Xuất từ cơ sở dữ liệu](#bước-4-xuất-từ-cơ-sở-dữ-liệu)
6. [Bước 5: Trích xuất hồ sơ CV](#bước-5-trích-xuất-hồ-sơ-cv)
7. [Bước 6: Công cụ so khớp CV-JD](#bước-6-công-cụ-so-khớp-cv-jd)
8. [Bước 7: Đánh giá kết quả so khớp](#bước-7-đánh-giá-kết-quả-so-khớp)
9. [Ngăn xếp công nghệ](#ngăn-xếp-công-nghệ)

---

## TỔNG QUAN PIPELINE

```
┌────────────────────────────────────────────────────────────────────────┐
│                  LƯU ĐỒ PIPELINE HOÀN CHỈNH                            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│ [Trang web tuyển dụng]              CRAWLING (Db/1_crawl_data/)   [CV] │
│      │                                                               │  │
│      ├─ iTViec                                                      │  │
│      ├─ LinkedIn                                                    │  │
│      ├─ CareerViet                                                  │  │
│      └─ VietnamWorks                                                │  │
│      │                                                               │  │
│      v                                                               v  │
│  Tệp JSON thô          crawl_all_daily.bat (Orchestrator)    PDF/Hình │
│  (jobs_itviec.json,    4 Crawlers chạy song song             ảnh      │
│   jobs_linkedin.json,   • requests + BeautifulSoup                 │  │
│   jobs_careerviet.json, • (Selenium cho LinkedIn)                  │  │
│   jobs_vietnamwork.json) merge_daily_outputs.py              │  │
│      │                 normalize_schema.py                      │  │
│      v                                                           v  │
│  data/crawl_YYYYMMDD/raw/                        ╔════════════════╗ │
│      │                                             ║    BƯỚC 5     ║ │
│      v                                             ║ TRÍCH XUẤT    ║ │
│  ╔═════════════════╗                              ║   HỒ SƠ CV   ║ │
│  ║    BƯỚC 1       ║                              ║  (easyocr)    ║ │
│  ║   CRAWLING      ║                              ╚════════════════╝ │
│  ║ (4 crawlers)    ║                                    │           │
│  ╚═════════════════╝                                    v           │
│        │                                    cv_profiles_baseline.json │
│        v                                             │               │
│  jobs_combined.json                                  │               │
│  (đã loại bỏ trùng lặp)                            │               │
│        │                                             │               │
│        v                                             │               │
│  clean_data_final.json                              │               │
│        │                                             │               │
│        v                                             │               │
│  ╔═════════════════╗                                │               │
│  ║    BƯỚC 2       ║                                │               │
│  ║  LÀM SẠCH DỮ   ║                                │               │
│  ║  LIỆ & XỬ LÝ   ║                                │               │
│  ║     AI          ║                                │               │
│  ║   (Gemini)      ║                                │               │
│  ╚═════════════════╝                                │               │
│        │                                             │               │
│        v                                             │               │
│  PostgreSQL Database                                │               │
│        │                                             │               │
│  ╔─────┴────────────────────────────────────────────┘               │
│  │                                                                   │
│  │  ╔═══════════════════════════════════════════════╗              │
│  │  ║   HỆ THỐNG SO KHỚP (Các bước 4-7)            ║              │
│  │  ╚═══════════════════════════════════════════════╝              │
│  │                                                                   │
│  v                                                                   │
│  ╔═════════════╗       ╔═════════════╗      ╔═════════════╗         │
│  ║   BƯỚC 4    ║
│  ║   XUẤT TỪ   ║
│  ╚═════════════╝       ╚═════════════╝      ╚═════════════╝         │
│                                                      │               │
│                                                      v               │
│                                         jobs_from_db.json           │
│                                                      │               │
│                     ┌────────────────────────────────┘              │
│                     │                                               │
│  cv_profiles_baseline.json ────┬──────────────────> jobs_from_db.json
│                                 │                       │           │
│                                 v                       v           │
│                         ╔═══════════════════════╗                   │
│                         ║     BƯỚC 6            ║                   │
│                         ║   CÔNG CỤ SO KHỚP    ║                   │
│                         ║                       ║                   │
│                         ║ • Lọc theo ngành      ║                   │
│                         ║ • Tính điểm tương tự  ║                   │
│                         ║ • Kết hợp có trọng số ║                   │
│                         ║ • Phân tích khoảng    ║                   │
│                         ║ • Xếp hạng top-K      ║                   │
│                         ╚═══════════════════════╝                   │
│                              │                                      │
│                              v                                      │
│                     matching_results.json                           │
│                              │                                      │
│                              v                                      │
│                     ╔═══════════════════════╗                       │
│                     ║     BƯỚC 7            ║                       │
│                     ║    ĐÁNH GIÁ KỲ        ║                       │
│                     ║                       ║                       │
│                     ║ • Chỉ số chất lượng   ║                       │
│                     ║ • Thống kê hành vi    ║                       │
│                     ║ • Phân tích độ tin    ║                       │
│                     ║   cậy                 ║                       │
│                     ╚═══════════════════════╝                       │
│                                         │
│                                         v
│                        matching_db_evaluation_report.json/.md
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

## BƯỚC 1: THU THẬP DỮ LIỆU (CRAWLING)

**Vị trí**: `Db/1_crawl_data/` | **Tần suất**: Hàng ngày tự động

**Kiến trúc**: 4 crawlers song song (iTViec, LinkedIn, CareerViet, VietnamWorks)
- **Orchestrator**: `crawl_all_daily.bat` → chạy 4 daily runners tuần tự
- **Chuẩn hóa**: `normalize_schema.py` → ánh xạ các tên trường khác nhau
- **Hợp nhất**: `merge_daily_outputs.py` → loại bỏ trùng lặp dựa trên MD5(title, company, description)
- **Công nghệ**: requests + BeautifulSoup (iTViec, CareerViet, VietnamWorks); Selenium (LinkedIn)
- **Đầu ra**: `data/crawl_YYYYMMDD/raw/jobs_combined.json` (~300-500 jobs/ngày)

---

## BƯỚC 2: LÀM SẠCH DỮ LIỆU & XỬ LÝ AI

**Vị trí**: `Db/2_clean_data/clean_process.py` | **Input**: jobs_combined.json

**Quy trình**:
1. **Loại bỏ trùng lặp**: MD5 fingerprint(title, company, description)
2. **Trích xuất Regex**: Lương (regex), Kinh nghiệm (classify_experience), Loại công việc, Remote
3. **Trích xuất AI (Gemini)**: Job category, Kỹ năng (optional), Lợi ích
4. **Chuẩn hóa**: Map kỹ năng tùy ý → tên chính tắc (SKILL_KEYWORDS); Lợi ích Tiếng Việt → English

**Đầu ra**: `Db/2_clean_data/output/clean_data_final.json` (đã chuẩn hóa lương, kinh nghiệm, kỹ năng)

---

## BƯỚC 3: NHẬP VÀO CƠ SỞ DỮ LIỆU  

**Vị trị**: `Db/3_mapping_data_db/` | **CSDL**: PostgreSQL

**Schema** (11 bảng):
```
companies → jobs ← job_skills ← skills
                ├─ job_benefits ← benefits
                └─ industries
```

**Quy trình**:
1. Khởi tạo schema SQL (bảng companies, jobs, skills, job_skills, benefits, job_benefits, industries)
2. Seed dữ liệu chính từ constants.py (SKILL_KEYWORDS, JOB_CATEGORIES, BENEFITS_KEYWORDS)
3. Upsert công việc + relationships: (title, company_id, fingerprint) = khóa chính
4. Lưu trữ công việc cũ (is_published=FALSE) khi cặp khóa trùng

---

## BƯỚC 4: XUẤT TỪ CƠ SỞ DỮ LIỆU

**Script**: `Matching/03_export_jobs_from_db.py`

SQL query `json_agg()` để lấy jobs + kỹ năng tính từ PostgreSQL:
```sql
SELECT j.job_id, j.title, c.name, j.experience_level, 
       json_agg(s.skill_name) as skills_extracted
FROM jobs j LEFT JOIN job_skills js ON j.job_id = js.job_id
            LEFT JOIN skills s ON js.skill_id = s.skill_id
WHERE j.is_published = TRUE GROUP BY j.job_id
```

**Đầu ra**: `Matching/jobs_from_db.json` (283 công việc)

**Vấn đề dữ liệu**:
- 🔴 **64.66% công việc không có kỹ năng** (183/283)
- 🔴 **67.49% công việc có ≤3 kỹ năng** (191/283)  
- Median kỹ năng/công việc = 0 → **Ảnh hưởng trực tiếp đến chất lượng matching**
