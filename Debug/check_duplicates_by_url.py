#!/usr/bin/env python3
"""
Kiểm tra duplicates trong crawl data bằng job_url
Phân tích xem có bao nhiêu jobs bị trùng lặp giữa các ngày
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = Path("Db/data")

def estimate_job_count(size_mb):
    """Ước lượng job count từ file size"""
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

def extract_urls_from_json(json_path):
    """Extract job URLs từ một JSON file"""
    urls = set()
    try:
        with open(json_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            
            # Quick parse để lấy job_url values
            import re
            # Pattern: "job_url": "https://..."
            pattern = r'"job_url"\s*:\s*"([^"]+)"'
            matches = re.findall(pattern, content)
            urls.update(matches)
    except Exception as e:
        pass
    
    return urls

def count_unique_jobs(crawl_dirs_list):
    """Count unique jobs across multiple crawl directories (optimized for extracted.json only)"""
    all_urls = {}  # url -> first_date
    url_sources = defaultdict(list)  # url -> [dates]
    
    processed = 0
    for crawl_dir, date_obj in crawl_dirs_list:
        date_key = date_obj.strftime("%Y-%m-%d")
        
        # Only check extracted.json (already cleaned) for speed
        extracted = crawl_dir / "clean" / "extracted.json"
        if extracted.exists():
            urls = extract_urls_from_json(extracted)
            for url in urls:
                if url not in all_urls:
                    all_urls[url] = date_key
                url_sources[url].append(date_key)
            
            processed += 1
            if processed % 50 == 0:
                print(f"  ✓ Processed {processed}/{len(crawl_dirs_list)} directories...")
    
    # Count duplicates
    duplicates = {url: dates for url, dates in url_sources.items() if len(dates) > 1}
    
    return len(all_urls), len(duplicates), duplicates

# Get all crawl directories for April 1 - May 19
crawl_dirs = sorted([d for d in BASE_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])

crawl_dirs_filtered = []
for crawl_dir in crawl_dirs:
    date_obj = get_crawl_date(crawl_dir.name)
    if not date_obj:
        continue
    
    if date_obj < datetime(2026, 4, 1) or date_obj > datetime(2026, 5, 19):
        continue
    
    crawl_dirs_filtered.append((crawl_dir, date_obj))

print("=" * 80)
print("🔍 DUPLICATE CHECK: Kiểm tra job_url duplicates")
print("=" * 80)
print(f"\nPhân tích {len(crawl_dirs_filtered)} crawl directories...")
print("(Đây có thể mất 2-5 phút để đọc tất cả JSON files)\n")

unique_count, dup_count, duplicates = count_unique_jobs(crawl_dirs_filtered)

print("=" * 80)
print("📊 KẾT QUẢ:")
print("=" * 80)
print(f"Tổng job URLs duy nhất:      {unique_count}")
print(f"Số jobs bị duplicate:        {dup_count}")
print(f"Duplicate rate:              {dup_count/unique_count*100:.1f}%")

# Show top duplicates
if duplicates:
    print(f"\n📋 Top 20 jobs bị duplicate nhiều nhất:")
    print("-" * 80)
    
    sorted_dups = sorted(
        [(url, dates) for url, dates in duplicates.items()],
        key=lambda x: len(x[1]),
        reverse=True
    )
    
    for i, (url, dates) in enumerate(sorted_dups[:20], 1):
        print(f"{i:2d}. [{len(dates)} lần] {url[:70]}")
        print(f"     Xuất hiện: {', '.join(sorted(set(dates)))}")
        if i < 5:
            print()

print("\n" + "=" * 80)
print("💡 GỢI Ý:")
print("=" * 80)

if dup_count == 0:
    print("✅ TUYỆT VỜI! Không có duplicates - tất cả jobs đều là unique")
    print(f"   → Có thể tin tưởng con số {unique_count} jobs")
else:
    print(f"⚠️  Phát hiện {dup_count} jobs bị trùng lặp ({dup_count/unique_count*100:.1f}%)")
    print(f"   → Số job thực: {unique_count} (đã remove duplicates)")
    print(f"   → Cần merge dữ liệu sử dụng job_url làm key")

print("=" * 80)
