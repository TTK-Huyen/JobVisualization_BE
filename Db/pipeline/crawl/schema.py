from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional, Union


def _parse_date_like(value: Union[str, date, datetime, None]) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, time.min)

    value_text = str(value).strip()
    if not value_text:
        return None

    normalized_text = value_text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized_text)
    except ValueError:
        pass

    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value_text, pattern)
        except ValueError:
            continue

    return None

@dataclass
class RawJobData:
    """
    Lớp này định nghĩa cấu trúc dữ liệu chuẩn mà mọi Scraper bắt buộc phải trả về.
    Nếu thiếu trường bắt buộc, code sẽ báo lỗi ngay lập tức.
    """
    # 1. Identity
    source_name: str       # vd: 'careerviet'
    job_url: str
    job_source_id: str
    
    # 2. Job Info
    title: str
    description_html: str
    
    # 3. Attributes (Cho phép None nhưng phải khai báo)
    location_raw: Optional[str] = None
    salary_raw: Optional[str] = None
    employment_type: Optional[str] = None
    experience_raw: Optional[str] = None
    posted_date: Optional[str] = None
    expiry_date: Optional[str] = None
    scraped_at: Optional[str] = None  # Thời điểm crawler lấy dữ liệu (ISO 8601 format)
    search_keyword: Optional[str] = None  # Từ khóa tìm kiếm được sử dụng (vd: "software engineer")
    
    # 4. Lists (Mặc định là list rỗng nếu không có)
    tags: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)
    
    # 5. Company Info
    company_name: Optional[str] = None
    company_source_id: Optional[str] = None
    company_website: Optional[str] = None
    company_address: Optional[str] = None
    company_size_raw: Optional[str] = None
    company_industry: Optional[str] = None
    requirements_text: Optional[str] = None # Text thuần của phần Yêu cầu (để AI học)

    def to_dict(self):
        data = self.__dict__.copy()

        posted_date = _parse_date_like(data.get("posted_date"))
        if posted_date is not None:
            data["posted_date"] = posted_date.date().isoformat() + "T00:00:00"

        expiry_date = _parse_date_like(data.get("expiry_date"))
        if expiry_date is not None:
            data["expiry_date"] = expiry_date.date().isoformat() + "T00:00:00"

        scraped_at = _parse_date_like(data.get("scraped_at"))
        if scraped_at is not None:
            data["scraped_at"] = scraped_at.date().isoformat() + "T00:00:00"

        return data