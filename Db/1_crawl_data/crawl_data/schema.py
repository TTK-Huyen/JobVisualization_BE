from dataclasses import dataclass, field
from typing import List, Optional

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
        return self.__dict__