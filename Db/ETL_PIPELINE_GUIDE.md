# ETL Pipeline - Job Visualization

Đây là pipeline tự động chạy quy trình ETL: **Crawl → Clean → Import to DB**

## 📋 Cấu trúc Pipeline

```
Step 1: CRAWL
  └─ Db/1_crawl_data/crawl_all_daily.bat
     Output → Db/1_crawl_data/output/crawl_DD_MM_YY/job_combined_[TIMESTAMP].json

Step 2: CLEAN
  └─ Db/2_clean_data/clean_process.py
     Input: crawl output → Process → Output Db/2_clean_data/output/clean_DD_MM_YY/clean_data_final_[TIMESTAMP].json

Step 3: IMPORT TO DATABASE
  └─ Db/3_mapping_data_db/import_to_db.py
     Input: clean output → PostgreSQL database
```

## 🚀 Cách Chạy

### Windows (Recommended)
```bash
cd Db
run_etl_pipeline.bat
```

### Linux / macOS
```bash
cd Db
python run_etl_pipeline.py
```

### Manual (từng bước)
```bash
# Step 1: Crawl
cd Db/1_crawl_data
crawl_all_daily.bat
# Output: output/crawl_DD_MM_YY/job_combined_[TIMESTAMP].json

# Step 2: Clean
cd ../2_clean_data
python clean_process.py --input ../1_crawl_data/output/crawl_DD_MM_YY/job_combined_[TIMESTAMP].json --output output/clean_DD_MM_YY/clean_data_final_[TIMESTAMP].json

# Step 3: Import
cd ../3_mapping_data_db
python import_to_db.py --input ../2_clean_data/output/clean_DD_MM_YY/clean_data_final_[TIMESTAMP].json
```

## 📊 Output Files

```
Db/
├── 1_crawl_data/output/crawl_DD_MM_YY/
│   └── job_combined_[TIMESTAMP].json        # Raw crawl data
├── 2_clean_data/output/clean_DD_MM_YY/
│   └── clean_data_final_[TIMESTAMP].json    # Cleaned & standardized data
├── 3_mapping_data_db/
│   └── (Data imported to PostgreSQL)
└── etl_pipeline.log                         # Pipeline execution log
```

## ⚙️ Cấu hình

### Biến môi trường
Mỗi folder có file `.env.example` - copy thành `.env` và sửa:

```bash
# 1_crawl_data/.env
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password

# 2_clean_data/.env
GEMINI_API_KEY=your_api_key

# 3_mapping_data_db/.env
PG_DB=job_visualization
PG_USER=postgres
PG_PASSWORD=your_password
PG_HOST=localhost
PG_PORT=5432
```

### Database Setup
```bash
# Tạo database (nếu chưa có)
createdb job_visualization -U postgres

# Script sẽ tự tạo bảng khi chạy import_to_db.py
```

## 📈 Dữ liệu được xử lý

- **Jobs**: Raw job postings → Cleaned & standardized
- **Skills**: Extracted từ requirements using constants.py + AI analysis
- **Salaries**: Parsed từ text
- **Companies**: Deduplicated & structured
- **Industries**: Categorized
- **Benefits**: Extracted & listed
- **Relationships**: Job ↔ Skills, Job ↔ Industries, Salary data

## 🔍 Monitoring

### Log files
```bash
# Pipeline log
cat Db/etl_pipeline.log

# Crawl logs
cat Db/1_crawl_data/logs/all_daily_[TIMESTAMP].log

# Check database
psql -d job_visualization -U postgres -c "SELECT COUNT(*) FROM jobs;"
```

### Database Stats
```sql
-- Check imported jobs
SELECT COUNT(*) as total_jobs FROM jobs;

-- Check skills
SELECT COUNT(*) as total_skills FROM skills;

-- Check job-skill relationships
SELECT COUNT(*) as job_skill_links FROM job_skills;

-- Sample job
SELECT j.title, COUNT(s.skill_id) as skills_count 
FROM jobs j 
LEFT JOIN job_skills js ON j.job_id = js.job_id
LEFT JOIN skills s ON js.skill_id = s.skill_id
GROUP BY j.job_id, j.title 
LIMIT 5;
```

## ⚠️ Troubleshooting

### "ModuleNotFoundError: No module named 'google.generativeai'"
```bash
pip install google-generativeai
```

### "ModuleNotFoundError: No module named 'psycopg2'"
```bash
pip install psycopg2-binary
```

### Database connection error
- Check PostgreSQL is running: `psql -U postgres -c "\l"`
- Check `.env` file in `3_mapping_data_db`
- Verify database exists: `psql -d job_visualization`

### No crawl output
- Check crawl_all_daily.bat runs successfully
- Check `Db/1_crawl_data/logs/` for errors
- Make sure selenium/webdriver is installed

## 📝 Notes

- Pipeline creates date-based folders automatically
- All timestamps use `YYYYMMDD_HHMMSS` format
- Duplicates are automatically removed in clean step
- Failed steps don't proceed to next step
- Check `etl_pipeline.log` for detailed error messages

## 🔄 Scheduling

### Windows Task Scheduler
```powershell
# Create scheduled task (run daily at 2 AM)
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
$action = New-ScheduledTaskAction -Execute "C:\path\to\Db\run_etl_pipeline.bat"
Register-ScheduledTask -TaskName "JobVisualization-ETL" -Trigger $trigger -Action $action -RunLevel Highest
```

### Linux Cron
```bash
# Run daily at 2 AM
0 2 * * * cd /path/to/Db && python run_etl_pipeline.py >> etl_pipeline.log 2>&1
```

---

**Last Updated**: 2026-01-13
