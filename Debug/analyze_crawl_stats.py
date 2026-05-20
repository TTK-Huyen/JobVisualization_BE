#!/usr/bin/env python3
"""
Thống kê crawl data từ 1/4/2026 - 19/5/2026
Phân tích lỗ hổng thời gian (< 100 jobs/ngày hoặc missing days)
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Base path
BASE_DIR = Path(__file__).parent / "Db" / "data"

def parse_crawl_date(dirname: str):
    """Extract YYYYMMDD from crawl_YYYYMMDD_HHMMSS"""
    try:
        parts = dirname.split("_")
        if len(parts) >= 2:
            date_str = parts[1]  # YYYYMMDD
            return datetime.strptime(date_str, "%Y%m%d")
    except:
        pass
    return None

def count_json_objects(file_path: Path) -> int:
    """Fast JSON object count by parsing incrementally"""
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            # Read entire content (fast on disk)
            content = f.read()
            
            # Quick check: if it's a JSON array
            if content.strip().startswith('['):
                # Count opening braces at depth 1
                depth = 0
                count = 0
                in_string = False
                escape = False
                
                for char in content:
                    if escape:
                        escape = False
                        continue
                    if char == '\\':
                        escape = True
                        continue
                    if char == '"':
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    
                    if char == '{':
                        depth += 1
                        if depth == 1:
                            count += 1
                    elif char == '}':
                        depth -= 1
                
                return count
    except Exception as e:
        pass
    
    return 0

def get_job_count(crawl_dir: Path) -> int:
    """Get job count from crawl/jobs_combined.json or extracted.json"""
    
    # Try crawl/jobs_combined.json first
    combined_file = crawl_dir / "crawl" / "jobs_combined.json"
    if combined_file.exists():
        return count_json_objects(combined_file)
    
    # Try extracted.json from clean folder
    extracted_file = crawl_dir / "clean" / "extracted.json"
    if extracted_file.exists():
        return count_json_objects(extracted_file)
    
    # Fallback: Count raw files
    raw_dir = crawl_dir / "raw"
    if raw_dir.exists():
        total = 0
        for json_file in sorted(raw_dir.glob("*.json")):
            count = count_json_objects(json_file)
            total += count
        return total
    
    return 0

def main():
    print("=" * 80)
    print("PHÂN TÍCH CRAWL DATA: 1/4/2026 - 19/5/2026")
    print("=" * 80)
    
    # Get all crawl directories
    crawl_dirs = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])
    
    # Parse crawl data
    crawl_stats = {}
    for crawl_dir in crawl_dirs:
        date_obj = parse_crawl_date(crawl_dir.name)
        if date_obj:
            job_count = get_job_count(crawl_dir)
            date_key = date_obj.strftime("%Y-%m-%d")
            
            if date_key not in crawl_stats:
                crawl_stats[date_key] = []
            
            crawl_stats[date_key].append({
                "dir": crawl_dir.name,
                "date": date_obj,
                "count": job_count
            })
    
    # Consolidate by day (sum multiple crawls per day)
    daily_stats = {}
    for date_key, runs in crawl_stats.items():
        total_count = sum(r["count"] for r in runs)
        daily_stats[date_key] = {
            "total_jobs": total_count,
            "runs": runs,
            "date": runs[0]["date"]
        }
    
    # Sort by date
    sorted_dates = sorted(daily_stats.keys())
    
    # Print detailed stats
    print("\n📊 CRAWL STATISTICS BY DAY:")
    print("-" * 80)
    
    target_start = datetime(2026, 4, 1)
    target_end = datetime(2026, 5, 19)
    
    for date_key in sorted_dates:
        stats = daily_stats[date_key]
        jobs = stats["total_jobs"]
        date_obj = stats["date"]
        
        # Color code based on job count
        if jobs < 100:
            status = "⚠️  UNDER TARGET"
        elif jobs >= 100:
            status = "✅ OK"
        else:
            status = "❌ NO DATA"
        
        print(f"{date_key}  │  {jobs:5d} jobs  │  {status}")
        
        # Show individual runs if multiple
        if len(stats["runs"]) > 1:
            for run in stats["runs"]:
                print(f"  └─ {run['dir']:30s}  {run['count']:5d} jobs")
    
    # Calculate gaps
    print("\n" + "=" * 80)
    print("📍 MISSING DAYS & UNDER-TARGET DAYS:")
    print("-" * 80)
    
    current = target_start
    gaps = []
    under_target = []
    
    while current <= target_end:
        date_key = current.strftime("%Y-%m-%d")
        
        if date_key not in daily_stats:
            gaps.append(date_key)
        elif daily_stats[date_key]["total_jobs"] < 100:
            under_target.append((date_key, daily_stats[date_key]["total_jobs"]))
        
        current += timedelta(days=1)
    
    # Print gaps
    if gaps:
        print(f"\n❌ MISSING DAYS ({len(gaps)} days):")
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
                print(f"  • {start_dt.strftime('%Y-%m-%d (%A)')}")
            else:
                days_count = (end_dt - start_dt).days + 1
                print(f"  • {start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')} ({days_count} days)")
    else:
        print("✅ No missing days!")
    
    # Print under target
    if under_target:
        print(f"\n⚠️  UNDER-TARGET DAYS ({len(under_target)} days, < 100 jobs):")
        for date_key, count in under_target:
            print(f"  • {date_key}  ({count} jobs)")
    else:
        print("\n✅ All days have >= 100 jobs!")
    
    # Summary
    print("\n" + "=" * 80)
    print("📈 SUMMARY:")
    print("-" * 80)
    
    total_jobs = sum(s["total_jobs"] for s in daily_stats.values())
    total_days = len(daily_stats)
    expected_days = (target_end - target_start).days + 1
    
    print(f"Date range:       {target_start.strftime('%Y-%m-%d')} → {target_end.strftime('%Y-%m-%d')}")
    print(f"Expected days:    {expected_days}")
    print(f"Crawled days:     {total_days}")
    print(f"Missing days:     {len(gaps)}")
    print(f"Total jobs:       {total_jobs}")
    print(f"Avg/day:          {total_jobs / total_days:.1f}")
    print(f"Target/day:       100 jobs")
    print(f"Crawl coverage:   {total_days / expected_days * 100:.1f}%")
    
    # Recommendation
    print("\n" + "=" * 80)
    print("💡 RECOMMENDATION:")
    print("-" * 80)
    
    if gaps:
        gap_jobs = len(gaps) * 100
        print(f"⚠️  Need to crawl {len(gaps)} missing days (~{gap_jobs} jobs)")
    
    if under_target:
        under_jobs = sum(100 - count for _, count in under_target)
        print(f"⚠️  Need to supplement {len(under_target)} under-target days (~{under_jobs} jobs)")
    
    if not gaps and not under_target:
        print("✅ Data looks complete! Ready for normalization & import.")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
