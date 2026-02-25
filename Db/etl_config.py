"""
ETL Pipeline Configuration
Kiểm soát số lượng job crawl và timeout cho mỗi bước
"""

# Số lượng job tối đa để crawl từ mỗi source
JOB_LIMITS = {
    "itviec": 10,
    "linkedin": 10,
    "careerviet": 10,
    "vietnamworks": 10
}

# Timeout (giây) cho từng bước
CRAWLER_TIMEOUT = 600      # 10 phút cho crawl
CLEAN_TIMEOUT = 300        # 5 phút cho clean
IMPORT_TIMEOUT = 600       # 10 phút cho import
