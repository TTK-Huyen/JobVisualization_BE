import os
from datetime import datetime, timedelta
from typing import List, Any

from date_filter import parse_iso_date, parse_relative_time_to_date


def _parse_job_datetime(job: Any):
    # job may be RawJobData object or dict
    posted = None
    scraped = None
    try:
        posted = getattr(job, "posted_date", None) if not isinstance(job, dict) else job.get("posted_date")
    except Exception:
        posted = None
    try:
        scraped = getattr(job, "scraped_at", None) if not isinstance(job, dict) else job.get("scraped_at")
    except Exception:
        scraped = None

    # Try ISO parse first
    if posted:
        try:
            return datetime.fromisoformat(posted.replace("Z", "+00:00"))
        except Exception:
            pass
    # Try parse as ISO date (YYYY-MM-DD)
    if posted:
        try:
            d = parse_iso_date(posted)
            if d:
                return datetime.combine(d, datetime.min.time())
        except Exception:
            pass

    # Try relative parse (returns date)
    if posted:
        try:
            d = parse_relative_time_to_date(posted)
            if d:
                return datetime.combine(d, datetime.min.time())
        except Exception:
            pass

    # Fallback to scraped_at
    if scraped:
        try:
            return datetime.fromisoformat(scraped.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.fromisoformat(scraped)
            except Exception:
                pass

    return None


def filter_recent_jobs(jobs: List[Any], window_hours: int = None) -> List[Any]:
    """Keep only jobs whose posted/scraped datetime is within window_hours.

    If window_hours is None, read from env `REALTIME_DAYS` or `DAYS_BACK` and use 72h as default.
    """
    job_date_mode = str(os.environ.get("JOB_DATE_MODE", "")).strip().lower()
    if job_date_mode in {"off", "all", "none"}:
        print(f"[FILTER] Skipped recent-job filter (JOB_DATE_MODE={job_date_mode})")
        return jobs

    if window_hours is None:
        try:
            days = int(os.environ.get("DAYS_BACK") or os.environ.get("REALTIME_DAYS") or "3")
            window_hours = max(1, days) * 24
        except Exception:
            window_hours = 72

    cutoff = datetime.now() - timedelta(hours=window_hours)
    kept = []
    removed = 0
    for job in jobs:
        dt = _parse_job_datetime(job)
        if dt is None:
            # cannot determine -> keep (conservative)
            kept.append(job)
            continue
        if dt >= cutoff:
            kept.append(job)
        else:
            removed += 1

    print(f"[FILTER] Kept {len(kept)} jobs; removed {removed} older than {window_hours} hours (cutoff={cutoff.isoformat()})")
    return kept


def filter_existing_jobs_by_url(urls: List[str], source: str = None) -> List[str]:
    """Kiểm tra danh sách URLs và chỉ giữ lại các URL chưa tồn tại trong database public.jobs."""
    if not urls:
        return []

    # Tải .env từ thư mục Db
    try:
        from pathlib import Path
        from dotenv import load_dotenv
        p = Path(__file__).resolve()
        for parent in p.parents:
            if parent.name.lower() == "db":
                env_path = parent / ".env"
                if env_path.exists():
                    load_dotenv(env_path)
                    break
    except Exception as e:
        print(f"[DB_FILTER] Không thể nạp file .env: {e}")

    # Lấy thông tin connection
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pg_host = os.getenv("PG_HOST", "localhost")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_db = os.getenv("PG_DB", "job_vis_clone")
        pg_user = os.getenv("PG_USER", "postgres")
        pg_pass = os.getenv("PG_PASSWORD", "123456")
        db_url = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    conn = None
    cur = None
    existing_urls = set()

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Sử dụng ANY(%s) để truyền danh sách list vào query duy nhất
        cur.execute(
            "SELECT job_posting_url FROM public.jobs WHERE job_posting_url = ANY(%s);",
            (urls,)
        )
        rows = cur.fetchall()
        for row in rows:
            if row[0]:
                existing_urls.add(row[0].strip())
    except Exception as e:
        print(f"[WARN] [DB_FILTER] Kiểm tra lặp URL thất bại: {e}. Bỏ qua bộ lọc trùng database.")
        # Fallback an toàn: Trả về danh sách gốc
        return urls
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    # Chỉ giữ lại các URL chưa có trong database
    filtered_urls = [u for u in urls if u.strip() not in existing_urls]
    skipped_count = len(urls) - len(filtered_urls)
    
    if skipped_count > 0:
        print(f"[DB_FILTER] Đã bỏ qua {skipped_count} job(s) do URL đã tồn tại trong database public.jobs.")
        if source:
            dropped_urls = [u for u in urls if u.strip() in existing_urls]
            stats_collector.record_db_dropped(source, skipped_count, dropped_urls)
    
    return filtered_urls


import threading

class CrawlStatsCollector:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_time = datetime.now()
        self.end_time = None
        self.stats = {}
        self.thread_local = threading.local()
        self.keyword_stats = {}  # dict: keyword -> {source -> {"scraped_list": int, "detail_scraped": int}}
        
    def reset(self):
        with self.lock:
            self.start_time = datetime.now()
            self.end_time = None
            self.stats = {}
            self.keyword_stats = {}
            self.thread_local = threading.local()

    def load_from_disk(self, filepath: str):
        import json
        if not os.path.exists(filepath):
            return
        try:
            with self.lock:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Merge stats
                saved_stats = data.get("stats", {})
                for src, s_data in saved_stats.items():
                    self._init_source(src)
                    self.stats[src]["max_jobs"] = max(self.stats[src]["max_jobs"], s_data.get("max_jobs", 0))
                    self.stats[src]["total_scraped_list"] += s_data.get("total_scraped_list", 0)
                    self.stats[src]["date_filter_dropped"] += s_data.get("date_filter_dropped", 0)
                    
                    # Merge sample urls
                    for u in s_data.get("date_filter_dropped_sample_urls", []):
                        if u not in self.stats[src]["date_filter_dropped_sample_urls"]:
                            self.stats[src]["date_filter_dropped_sample_urls"].append(u)
                            
                    self.stats[src]["db_filter_dropped"] += s_data.get("db_filter_dropped", 0)
                    for u in s_data.get("db_filter_dropped_sample_urls", []):
                        if u not in self.stats[src]["db_filter_dropped_sample_urls"]:
                            self.stats[src]["db_filter_dropped_sample_urls"].append(u)
                            
                    self.stats[src]["detail_scraped_count"] += s_data.get("detail_scraped_count", 0)
                    for u in s_data.get("detail_scraped_urls", []):
                        if u not in self.stats[src]["detail_scraped_urls"]:
                            self.stats[src]["detail_scraped_urls"].append(u)
                            
                    for u in s_data.get("search_list_urls", []):
                        if u not in self.stats[src]["search_list_urls"]:
                            self.stats[src]["search_list_urls"].append(u)
                            
                    # Merge http status codes
                    for code, count in s_data.get("http_status_codes", {}).items():
                        self.stats[src]["http_status_codes"][code] = self.stats[src]["http_status_codes"].get(code, 0) + count
                        
                    # Merge missing fields
                    for field, count in s_data.get("missing_fields", {}).items():
                        self.stats[src]["missing_fields"][field] = self.stats[src]["missing_fields"].get(field, 0) + count
                
                # Merge keyword_stats
                saved_kw_stats = data.get("keyword_stats", {})
                for kw, src_map in saved_kw_stats.items():
                    self.keyword_stats.setdefault(kw, {})
                    for src, counts in src_map.items():
                        self.keyword_stats[kw].setdefault(src, {"scraped_list": 0, "detail_scraped": 0})
                        self.keyword_stats[kw][src]["scraped_list"] += counts.get("scraped_list", 0)
                        self.keyword_stats[kw][src]["detail_scraped"] += counts.get("detail_scraped", 0)
                        
                # Merge start_time (keep the earliest start time)
                if "start_time" in data:
                    try:
                        saved_start = datetime.fromisoformat(data["start_time"])
                        if saved_start < self.start_time:
                            self.start_time = saved_start
                    except Exception:
                        pass
        except Exception as e:
            print(f"[WARN] Failed to load accumulated stats from disk: {e}")

    def save_to_disk(self, filepath: str):
        import json
        try:
            # Ensure folder exists
            dir_name = os.path.dirname(filepath)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with self.lock:
                data = {
                    "start_time": self.start_time.isoformat() if self.start_time else None,
                    "stats": self.stats,
                    "keyword_stats": self.keyword_stats
                }
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[WARN] Failed to save accumulated stats to disk: {e}")
            
    def set_active_keyword(self, keyword: str):
        self.thread_local.keyword = str(keyword).strip()
            
    def _init_source(self, source: str):
        if source not in self.stats:
            self.stats[source] = {
                "max_jobs": 0,
                "total_scraped_list": 0,
                "date_filter_dropped": 0,
                "date_filter_dropped_sample_urls": [],
                "db_filter_dropped": 0,
                "db_filter_dropped_sample_urls": [],
                "detail_scraped_count": 0,
                "detail_scraped_urls": [],
                "search_list_urls": [],
                "missing_fields": {},
                "http_status_codes": {}
            }

    def record_max_jobs(self, source: str, max_jobs: int):
        with self.lock:
            self._init_source(source)
            self.stats[source]["max_jobs"] = max_jobs
            
    def record_search_list_url(self, source: str, url: str):
        with self.lock:
            self._init_source(source)
            current_urls = self.stats[source]["search_list_urls"]
            if url not in current_urls:
                current_urls.append(url)

    def record_list_count(self, source: str, count: int):
        with self.lock:
            self._init_source(source)
            self.stats[source]["total_scraped_list"] += count
            
            # Record per keyword
            kw = getattr(self.thread_local, "keyword", "unknown")
            self.keyword_stats.setdefault(kw, {})
            self.keyword_stats[kw].setdefault(source, {"scraped_list": 0, "detail_scraped": 0})
            self.keyword_stats[kw][source]["scraped_list"] += count
            
    def record_date_dropped(self, source: str, count: int, sample_urls: List[str]):
        with self.lock:
            self._init_source(source)
            self.stats[source]["date_filter_dropped"] += count
            current_samples = self.stats[source]["date_filter_dropped_sample_urls"]
            for url in sample_urls:
                if url not in current_samples:
                    current_samples.append(url)
                    
    def record_db_dropped(self, source: str, count: int, sample_urls: List[str]):
        with self.lock:
            self._init_source(source)
            self.stats[source]["db_filter_dropped"] += count
            current_samples = self.stats[source]["db_filter_dropped_sample_urls"]
            for url in sample_urls:
                if url not in current_samples:
                    current_samples.append(url)
                    
    def record_detail_scraped(self, source: str, count: int, urls: List[str] = None):
        with self.lock:
            self._init_source(source)
            self.stats[source]["detail_scraped_count"] += count
            if urls:
                current_urls = self.stats[source]["detail_scraped_urls"]
                for url in urls:
                    if url not in current_urls:
                        current_urls.append(url)
                        
            # Record per keyword
            kw = getattr(self.thread_local, "keyword", "unknown")
            self.keyword_stats.setdefault(kw, {})
            self.keyword_stats[kw].setdefault(source, {"scraped_list": 0, "detail_scraped": 0})
            self.keyword_stats[kw][source]["detail_scraped"] += count

    def record_http_status(self, source: str, status_code: int):
        with self.lock:
            self._init_source(source)
            status_str = str(status_code)
            self.stats[source]["http_status_codes"].setdefault(status_str, 0)
            self.stats[source]["http_status_codes"][status_str] += 1

    def calculate_missing_fields(self, source: str, jobs: List[Any]):
        """Tính toán tỷ lệ khuyết các trường thông tin quan trọng."""
        with self.lock:
            self._init_source(source)
            if not jobs:
                return
                
            fields_to_check = [
                "title", "description_html", "location_raw", "salary_raw", 
                "employment_type", "experience_raw", "posted_date", "expiry_date", 
                "company_name", "company_website", "company_address", 
                "company_size_raw", "company_industry", "requirements_text"
            ]
            
            for field in fields_to_check:
                self.stats[source]["missing_fields"].setdefault(field, 0)
                
            for job in jobs:
                job_dict = job.to_dict() if hasattr(job, "to_dict") else (job if isinstance(job, dict) else job.__dict__)
                for field in fields_to_check:
                    val = job_dict.get(field)
                    is_missing = False
                    if val is None:
                        is_missing = True
                    elif isinstance(val, str) and not val.strip():
                        is_missing = True
                    elif isinstance(val, (list, tuple, set)) and not val:
                        is_missing = True
                        
                    if is_missing:
                        self.stats[source]["missing_fields"][field] += 1

    def get_summary_report(self) -> str:
        with self.lock:
            if not self.start_time:
                duration_str = "N/A"
            else:
                end = self.end_time or datetime.now()
                duration = end - self.start_time
                duration_str = f"{duration.total_seconds():.2f} giây"
                
            report = []
            report.append("\n" + "="*80)
            report.append("📊 BÁO CÁO THỐNG KÊ CHI TIẾT CRAWLER & SCRAPER (LŨY KẾ NGÀY)")
            report.append("  * GHI CHÚ: Số liệu trong các bảng dưới đây là LŨY KẾ (CỘNG DỒN) từ tất cả các Batch đã chạy.")
            report.append("="*80)
            
            # 1. Thông tin cấu hình
            report.append(f"\n⚙️  Thông tin Cấu hình:")
            report.append(f"  - DAYS_BACK (Khoảng lọc ngày) : {os.getenv('DAYS_BACK') or os.getenv('REALTIME_DAYS') or '3'} ngày")
            report.append(f"  - JOB_DATE_MODE (Chế độ lọc) : {os.getenv('JOB_DATE_MODE', 'realtime')}")
            report.append(f"  - CRAWL_ONLY (Chỉ lấy list)   : {os.getenv('CRAWL_ONLY', 'false')}")
            report.append(f"  - Thời gian thực thi cào     : {duration_str}")
            
            sources = ["CareerViet", "ITviec", "VietnamWorks", "LinkedIn"]
            
            metrics = [
                ("max_jobs", "Giới hạn cào (Max Jobs)"),
                ("total_scraped_list", "Số lượng job duyệt qua"),
                ("date_filter_dropped", "Loại do lọc ngày"),
                ("db_filter_dropped", "Loại do trùng DB"),
                ("detail_scraped_count", "Được cào chi tiết")
            ]
            
            # Bảng 1: Số lượng jobs
            report.append("\n📈 BẢNG THỐNG KÊ SỐ LƯỢNG JOBS THEO NGUỒN (LŨY KẾ):")
            header = f"| {'Chỉ số / Metric':<30} | " + " | ".join(f"{src:<12}" for src in sources) + " |"
            separator = f"|{'-'*32}|" + "|".join(f"{'-'*14}" for _ in sources) + "|"
            report.append(separator)
            report.append(header)
            report.append(separator)
            
            for key, label in metrics:
                row_parts = []
                for src in sources:
                    val = 0
                    if src in self.stats:
                        val = self.stats[src].get(key, 0)
                    row_parts.append(f"{val:<12}")
                row_str = f"| {label:<30} | " + " | ".join(row_parts) + " |"
                report.append(row_str)
            report.append(separator)
            
            # Bảng 1b: Số lượng job duyệt qua / cào chi tiết theo keyword của các nguồn
            if self.keyword_stats:
                report.append("\n📈 BẢNG THỐNG KÊ SỐ JOB DUYỆT QUA / CÀO CHI TIẾT THEO KEYWORD (DUYỆT / CÀO) (LŨY KẾ):")
                header_kw = f"| {'Từ khóa / Keyword':<30} | " + " | ".join(f"{src:<12}" for src in sources) + " | " + f"{'Tổng':<10} |"
                separator_kw = f"|{'-'*32}|" + "|".join(f"{'-'*14}" for _ in sources) + f"|{'-'*12}|"
                report.append(separator_kw)
                report.append(header_kw)
                report.append(separator_kw)
                
                for kw, src_map in sorted(self.keyword_stats.items()):
                    row_parts = []
                    total_scraped = 0
                    total_detail = 0
                    for src in sources:
                        scraped = src_map.get(src, {}).get("scraped_list", 0)
                        detail = src_map.get(src, {}).get("detail_scraped", 0)
                        total_scraped += scraped
                        total_detail += detail
                        row_parts.append(f"{f'{scraped} / {detail}':<12}")
                    kw_display = kw if len(kw) <= 30 else kw[:27] + "..."
                    row_str = f"| {kw_display:<30} | " + " | ".join(row_parts) + f" | {f'{total_scraped} / {total_detail}':<10} |"
                    report.append(row_str)
                report.append(separator_kw)
 
            # Thu thập tất cả các HTTP Status Code có trong các nguồn
            all_status_codes = set()
            for src in sources:
                if src in self.stats:
                    all_status_codes.update(self.stats[src].get("http_status_codes", {}).keys())
            
            # Bảng 2: HTTP Status Rate
            if all_status_codes:
                report.append("\n🌐 BẢNG TỈ LỆ HTTP STATUS RATE:")
                header_http = f"| {'HTTP Status':<30} | " + " | ".join(f"{src:<12}" for src in sources) + " |"
                separator_http = f"|{'-'*32}|" + "|".join(f"{'-'*14}" for _ in sources) + "|"
                report.append(separator_http)
                report.append(header_http)
                report.append(separator_http)
                
                for code in sorted(all_status_codes):
                    row_parts = []
                    for src in sources:
                        rate_str = "-"
                        if src in self.stats:
                            status_map = self.stats[src].get("http_status_codes", {})
                            if status_map:
                                total_reqs = sum(status_map.values())
                                count = status_map.get(code, 0)
                                if count > 0:
                                    rate = (count / total_reqs) * 100
                                    rate_str = f"{rate:.1f}%({count}/{total_reqs})"
                        row_parts.append(f"{rate_str:<12}")
                    row_str = f"| {f'Code {code}':<30} | " + " | ".join(row_parts) + " |"
                    report.append(row_str)
                report.append(separator_http)
            
            # Bảng 3: Tỷ lệ khuyết các trường
            has_details = False
            for src in sources:
                if src in self.stats and self.stats[src].get("detail_scraped_count", 0) > 0:
                    has_details = True
                    break
            
            if has_details:
                report.append("\n⚠️ BẢNG TỶ LỆ KHUYẾT CÁC TRƯỜNG THÔNG TIN SAU SCRAPER:")
                fields_to_check = [
                    "title", "description_html", "location_raw", "salary_raw", 
                    "employment_type", "experience_raw", "posted_date", "expiry_date", 
                    "company_name", "company_website", "company_address", 
                    "company_size_raw", "company_industry", "requirements_text"
                ]
                
                header_missing = f"| {'Trường Thông Tin / Field':<30} | " + " | ".join(f"{src:<12}" for src in sources) + " |"
                separator_missing = f"|{'-'*32}|" + "|".join(f"{'-'*14}" for _ in sources) + "|"
                report.append(separator_missing)
                report.append(header_missing)
                report.append(separator_missing)
                
                for field in fields_to_check:
                    row_parts = []
                    for src in sources:
                        rate_str = "-"
                        if src in self.stats:
                            total_jobs = self.stats[src].get("detail_scraped_count", 0)
                            if total_jobs > 0:
                                missing_count = self.stats[src].get("missing_fields", {}).get(field, 0)
                                rate = (missing_count / total_jobs) * 100
                                rate_str = f"{rate:.1f}%({missing_count}/{total_jobs})"
                        row_parts.append(f"{rate_str:<12}")
                    row_str = f"| {field:<30} | " + " | ".join(row_parts) + " |"
                    report.append(row_str)
                report.append(separator_missing)
                
            # 3. Định nghĩa helper để vẽ bảng URL phẳng
            def build_flat_url_table(title: str, key_in_stats: str, empty_msg: str) -> str:
                table_parts = []
                table_parts.append(f"\n🔗 {title}:")
                
                max_url_len = 60
                has_data = False
                
                rows_data = []
                for src in sources:
                    if src in self.stats:
                        urls = self.stats[src].get(key_in_stats, [])
                        if urls:
                            has_data = True
                            for u in urls:
                                rows_data.append((src, u))
                                if len(u) > max_url_len:
                                    max_url_len = len(u)
                                    
                if not has_data:
                    table_parts.append(f"  {empty_msg}")
                    return "\n".join(table_parts)
                
                # If verbose mode is disabled and there are more than 5 items, print a concise summary
                verbose_active = os.environ.get("PIPELINE_VERBOSE") == "true"
                if not verbose_active and key_in_stats != "search_list_urls":
                    if len(rows_data) > 5:
                        table_parts.append(f"  - Tổng số lượng: {len(rows_data)} jobs")
                        
                        def get_id_from_url(url):
                            parts = [p for p in url.strip().split('/') if p]
                            if parts:
                                last = parts[-1]
                                if '?' in last:
                                    last = last.split('?')[0]
                                if '-' in last:
                                    last = last.split('-')[-1]
                                return last
                            return "URL"
                        
                        subset = rows_data[:5]
                        samples = [f"{src}: {get_id_from_url(u)}" for src, u in subset]
                        table_parts.append(f"  - 5 mẫu đầu tiên: {', '.join(samples)}")
                        table_parts.append(f"  - [Đã ẩn bớt {len(rows_data) - 5} dòng. Xem tệp log pipeline hoặc chạy với --verbose để xem toàn bộ.]")
                        return "\n".join(table_parts)
                
                max_url_len = min(max_url_len, 100) # Giới hạn tối đa 100 ký tự cột URL để giao diện cân đối
                
                header = f"| {'Nguồn / Source':<15} | {'URL':<{max_url_len}} |"
                sep = f"|{'-'*17}|{'-'*(max_url_len+2)}|"
                table_parts.append(sep)
                table_parts.append(header)
                table_parts.append(sep)
                
                for src, u in rows_data:
                    u_display = u if len(u) <= max_url_len else u[:max_url_len-3] + "..."
                    table_parts.append(f"| {src:<15} | {u_display:<{max_url_len}} |")
                    
                table_parts.append(sep)
                return "\n".join(table_parts)
 
            # 4. Xuất các bảng URL chi tiết
            report.append(build_flat_url_table(
                "BẢNG CÁC TRANG DANH SÁCH ĐÃ CÀO (SEARCH LIST URLS) (LŨY KẾ)",
                "search_list_urls",
                "(Không cào trang danh sách nào)"
            ))
            
            report.append(build_flat_url_table(
                "BẢNG CÁC JOB ĐƯỢC CÀO CHI TIẾT (SCRAPED JOB URLS) (LŨY KẾ)",
                "detail_scraped_urls",
                "(Không có job nào được cào chi tiết)"
            ))
            
            report.append(build_flat_url_table(
                "BẢNG CÁC JOB BỊ LOẠI DO LỌC NGÀY (DATE FILTERED JOB URLS) (LŨY KẾ)",
                "date_filter_dropped_sample_urls",
                "(Không có job nào bị loại do lọc ngày)"
            ))
            
            report.append(build_flat_url_table(
                "BẢNG CÁC JOB BỊ LOẠI DO TRÙNG DB (DB DUPLICATE JOB URLS) (LŨY KẾ)",
                "db_filter_dropped_sample_urls",
                "(Không có job nào bị loại do trùng DB)"
            ))
            
            report.append("="*80)
            return "\n".join(report)

stats_collector = CrawlStatsCollector()

