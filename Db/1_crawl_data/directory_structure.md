# Cây thư mục dự án — Job Analysis

Dưới đây là cấu trúc thư mục chính kèm mô tả ngắn chức năng từng phần.

```
job_analysis/
├── README.md                 # Hướng dẫn, cách cài đặt và chạy dự án
├── DatabaseStructure.md      # Mô tả schema/ bảng để lưu dữ liệu
├── requirements.txt          # Danh sách dependency Python
├── pyproject.toml            # Cấu hình project Python (nếu có)
├── crawl_linkedin_daily.bat  # Batch để chạy crawl LinkedIn hàng ngày
├── enhanced_job_collector.py # Công cụ chính: thu thập + phân tíc(TopCV)
├── topcv_to_pg.py            # Import/chuyển dữ liệu sang PostgreSQL
├── collected_job_data/       # Thư mục lưu kết quả thu thập (CSV/JSON/XLSX)
│   └── collected_jobs_*.csv / .json / .xlsx
├── output/                   # File tổng hợp cuối cùng (ví dụ jobs_combined.*)
└── crawl_data/               # Bộ crawlers theo từng nguồn
    ├── crawl-linkedin-jobs/
    │   ├── scripts/          # Scraper LinkedIn (scripts/scrape_linkedin.py)
    │   ├── data-files/       # Đầu ra CSV/JSON/XLSX từ crawler LinkedIn
    │   └── README.md
    ├── crawl-vietnamwork-jobs/
    │   ├── scripts/          # Scraper VietnamWorks (scrape_vietnamwork.py)
    │   └── data-files/
    ├── crawl-itviec-jobs/
    │   ├── scripts/          # Scraper ITViec (scrape_itviec.py)
    │   └── data-files/       # Ví dụ: jobs.csv, jobs.json
    ├── crawl-careerviet-jobs/
    │   ├── scripts/          # Scraper CareerViet (scrape_careerviet.py)
    │   └── data-files/
    └── data-files/           # Dữ liệu tổng hợp/tiện ích dùng chung cho các crawler

# File/Thư mục không cần quan tâm
- __pycache__/                # Bytecode Python (tự động) — bỏ qua
- .venv/                      # Virtual environment (cục bộ) — bỏ qua
- .git/                       # Thông tin git
```

Nếu bạn muốn, tôi có thể:
- Thêm mô tả chi tiết hơn cho một script cụ thể (ví dụ `enhanced_job_collector.py`),
- Hoặc xuất cấu trúc này thành `tree` có định dạng khác (ví dụ CSV hoặc JSON).
