# ETL Pipeline - Hướng Dẫn Chạy

## Cấu Trúc Pipeline

ETL Pipeline có 4 bước chính:
1. **CRAWL**: Crawl dữ liệu từ các nguồn (ITviec, LinkedIn, CareerViet, VietnamWorks)
2. **MERGE**: Merge các file crawl thành 1 file duy nhất
3. **CLEAN**: Làm sạch và chuẩn hóa schema dữ liệu
4. **IMPORT**: Import dữ liệu vào Database

## Cách Chạy

### 1. Chạy toàn bộ pipeline (mặc định)
```bash
python run_etl_pipeline.py
```
Chạy tất cả 4 bước: CRAWL → MERGE → CLEAN → IMPORT

### 2. Chỉ chạy CRAWL + MERGE (bỏ qua CLEAN + IMPORT)
```bash
$env:STEP_CLEAN='false'
$env:STEP_IMPORT='false'
python run_etl_pipeline.py
```

### 3. Chỉ chạy CRAWL (bỏ qua MERGE, CLEAN, IMPORT)
```bash
$env:STEP_MERGE='false'
$env:STEP_CLEAN='false'
$env:STEP_IMPORT='false'
python run_etl_pipeline.py
```

### 4. Chỉ chạy CLEAN + IMPORT (bỏ qua CRAWL)
```bash
$env:STEP_CRAWL='false'
python run_etl_pipeline.py
```

### 5. Chỉ chạy CLEAN (bỏ qua CRAWL, MERGE, IMPORT)
```bash
$env:STEP_CRAWL='false'
$env:STEP_MERGE='false'
$env:STEP_IMPORT='false'
python run_etl_pipeline.py
```

## Environment Variables

Các biến để control bước nào chạy:
- `STEP_CRAWL` (default: true) - Chạy crawl dữ liệu
- `STEP_MERGE` (default: true) - Merge kết quả crawl
- `STEP_CLEAN` (default: true) - Làm sạch dữ liệu
- `STEP_IMPORT` (default: true) - Import vào Database

Giá trị nhận: `true`, `false`, `1`, `0`, `yes`, `no`

## Cấu Hình

File `etl_config.py` điều khiển:
- `JOB_LIMITS`: Số lượng job max từ mỗi source (default: 100)
- `CRAWLER_TIMEOUT`: Timeout crawl (default: 600s)
- `CLEAN_TIMEOUT`: Timeout clean (default: 300s)
- `IMPORT_TIMEOUT`: Timeout import (default: 600s)

## Output Locations

Các file output được lưu ở:
- **Raw Crawl**: `data/raw/crawl_YYYYMMDD/`
- **Cleaned Data**: `data/crawl_YYYYMMDD/clean/`
- **Merged File**: `data/raw/crawl_YYYYMMDD/jobs_combined.json`
- **Normalized File**: `data/raw/crawl_YYYYMMDD/jobs_normalized.json`
- **Final Clean**: `data/crawl_YYYYMMDD/clean/clean_data_final_YYYYMMDD.json`

## Ví Dụ Thực Tế

### Scenario 1: Chạy crawl hôm nay
```bash
python run_etl_pipeline.py
```

### Scenario 2: Chỉ crawl, không import
```bash
$env:STEP_IMPORT='false'
python run_etl_pipeline.py
```

### Scenario 3: Test clean + import trên dữ liệu cũ
```bash
$env:STEP_CRAWL='false'
$env:STEP_MERGE='false'
python run_etl_pipeline.py
```

### Scenario 4: Chạy lại clean với config khác
1. Sửa file clean_process.py
2. Chạy:
```bash
$env:STEP_CRAWL='false'
$env:STEP_MERGE='false'
$env:STEP_IMPORT='false'
python run_etl_pipeline.py
```

## Xem Log Output

Pipeline sẽ print chi tiết từng bước:
- `[CRAWL]` - Thông tin crawl
- `[MERGE]` - Thông tin merge
- `[CLEAN]` - Thông tin clean
- `[IMPORT]` - Thông tin import

## Troubleshooting

- **Crawl timeout**: Tăng `CRAWLER_TIMEOUT` trong `etl_config.py`
- **Clean không hoạt động**: Kiểm tra input file ở `data/raw/crawl_YYYYMMDD/`
- **Import lỗi**: Kiểm tra Database connection trong `3_mapping_data_db/import_to_db.py`
