#!/usr/bin/env python3
"""
Thống kê crawl data từ 1/4/2026 - 19/5/2026
Tổng hợp tất cả các runs của cùng một ngày
"""
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = Path("Db/data")

def estimate_job_count(size_mb):
    """Ước lượng job count từ file size (tương đối)"""
    # Ở mục nhân viên, 7.3 MB ~ 1000 jobs, tức ~7.3 KB/job
    return max(0, int(size_mb / 7.3 * 1000))

def get_crawl_date(dirname):
    """Extract ngày từ crawl_YYYYMMDD_HHMMSS"""
    try:
        parts = dirname.split("_")
        if len(parts) >= 2:
            date_str = parts[1]
            return datetime.strptime(date_str, "%Y%m%d")
    except:
        pass
    return None

def get_data_size_mb(crawl_dir):
    """Get total data size from a crawl directory"""
    total_size = 0
    
    # Check extracted.json
    extracted = crawl_dir / "clean" / "extracted.json"
    if extracted.exists():
        total_size += extracted.stat().st_size
    
    # Check crawl/jobs_combined.json
    combined = crawl_dir / "crawl" / "jobs_combined.json"
    if combined.exists():
        total_size += combined.stat().st_size
    
    # Check raw files
    raw_dir = crawl_dir / "raw"
    if raw_dir.exists():
        for json_file in raw_dir.glob("*.json"):
            total_size += json_file.stat().st_size
    
    return total_size / (1024 * 1024)

# Get all crawl directories
crawl_dirs = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])

# Aggregate by date
daily_stats = defaultdict(lambda: {"total_mb": 0, "runs": 0})

for crawl_dir in crawl_dirs:
    date_obj = get_crawl_date(crawl_dir.name)
    if not date_obj:
        continue
    
    # Only process April 1 - May 19
    if date_obj < datetime(2026, 4, 1) or date_obj > datetime(2026, 5, 19):
        continue
    
    date_key = date_obj.strftime("%Y-%m-%d")
    size_mb = get_data_size_mb(crawl_dir)
    
    daily_stats[date_key]["total_mb"] += size_mb
    daily_stats[date_key]["runs"] += 1

# Print results
print("=" * 80)
print("📊 THỐNG KÊ CRAWL DATA: 1/4/2026 - 19/5/2026")
print("=" * 80)
print("\nNGÀY         │  SỐ JOBS (ước)  │  SIZE (MB)  │  RUNS")
print("-" * 80)

target_start = datetime(2026, 4, 1)
target_end = datetime(2026, 5, 19)

current = target_start
total_jobs_global = 0
days_with_data = 0
gaps = []
under_target = []

while current <= target_end:
    date_key = current.strftime("%Y-%m-%d")
    
    if date_key in daily_stats:
        stats = daily_stats[date_key]
        jobs = estimate_job_count(stats["total_mb"])
        size_mb = stats["total_mb"]
        runs = stats["runs"]
        
        total_jobs_global += jobs
        days_with_data += 1
        
        # Status
        if jobs < 100:
            status = "⚠️  UNDER TARGET"
            under_target.append((date_key, jobs))
        else:
            status = "✅"
        
        print(f"{date_key}  │  {jobs:6d}        │  {size_mb:6.1f}      │  {runs:2d}    {status}")
    else:
        gaps.append(date_key)
        print(f"{date_key}  │  ❌ MISSING")
    
    current += timedelta(days=1)

# Summary
print("\n" + "=" * 80)
print("📈 SUMMARY:")
print("=" * 80)

expected_days = (target_end - target_start).days + 1
print(f"Ngày kỳ vọng:    {expected_days}")
print(f"Ngày có data:    {days_with_data}")
print(f"Ngày thiếu:      {len(gaps)}")
print(f"Tổng jobs:       ~{total_jobs_global}")
print(f"Trung bình/ngày: ~{total_jobs_global // days_with_data if days_with_data > 0 else 0}")
print(f"Target/ngày:     100 jobs")

# Recommendations
print("\n" + "=" * 80)
print("💡 KHUYẾN NGHỊ:")
print("=" * 80)

if gaps:
    print(f"\n❌ Các ngày THIẾU ({len(gaps)} ngày):")
    gap_ranges = []
    start = None
    prev = None
    
    for gap_date in gaps:
        gap_dt = datetime.strptime(gap_date, "%Y-%m-%d")
        if start is None:
            start = gap_dt
            prev = gap_dt
        elif (gap_dt - prev).days > 1:
            gap_ranges.append((start, prev))
            start = gap_dt
            prev = gap_dt
        else:
            prev = gap_dt
    
    if start:
        gap_ranges.append((start, prev))
    
    for start_dt, end_dt in gap_ranges:
        if start_dt == end_dt:
            print(f"   • {start_dt.strftime('%Y-%m-%d (%A)')}")
        else:
            days_count = (end_dt - start_dt).days + 1
            print(f"   • {start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')} ({days_count} days)")

if under_target:
    print(f"\n⚠️  Các ngày UNDER-TARGET ({len(under_target)} ngày, < 100 jobs):")
    for date_key, count in sorted(under_target):
        print(f"   • {date_key}: {count} jobs")

if not gaps and not under_target:
    print("\n✅ Data hoàn chỉnh! Sẵn sàng cho bước normalization & import.")
else:
    total_missing = len(gaps) * 100 + sum(100 - count for _, count in under_target)
    print(f"\n💼 Cần crawl bổ sung: ~{total_missing} jobs")

print("=" * 80)
