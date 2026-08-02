import re
import unicodedata
import ast
from typing import Any, List, Optional, Set

# 34 standard provinces/cities requested by user
TARGET_34_PROVINCES: Set[str] = {
    "Hà Nội", "Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ", "Huế",
    "An Giang", "Bắc Ninh", "Cà Mau", "Cao Bằng", "Đắk Lắk", "Điện Biên",
    "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Tĩnh", "Hưng Yên", "Khánh Hòa",
    "Lai Châu", "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Nghệ An", "Ninh Bình",
    "Phú Thọ", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị", "Sơn La", "Tây Ninh",
    "Thái Nguyên", "Thanh Hóa", "Tuyên Quang", "Vĩnh Long"
}

# Các giá trị canonical là QUỐC GIA (không phải tỉnh/thành) — dùng để loại bỏ
# đuôi quốc gia khi rút gọn địa điểm về tỉnh/thành. Khớp với nhóm "# Countries"
# trong LOCATION_MAP bên dưới.
COUNTRY_CANONICAL: Set[str] = {
    "Việt Nam", "Singapore", "Nhật Bản", "Hàn Quốc", "Hoa Kỳ", "Đức",
    "Australia", "Đài Loan", "Malaysia", "Bỉ", "Na Uy", "Hà Lan",
    "Phần Lan", "Lào",
}

# Mapping of normalized base strings (without diacritics/accents) to canonical names
LOCATION_MAP = {
    # 34 Target Provinces/Cities
    "ha noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "tp ha noi": "Hà Nội",
    "tp. ha noi": "Hà Nội",
    "thanh pho ha noi": "Hà Nội",
    
    "ho chi minh": "Hồ Chí Minh",
    "hcm": "Hồ Chí Minh",
    "tphcm": "Hồ Chí Minh",
    "tp hcm": "Hồ Chí Minh",
    "tp.hcm": "Hồ Chí Minh",
    "tp. hcm": "Hồ Chí Minh",
    "ho chi minh city": "Hồ Chí Minh",
    "tp ho chi minh": "Hồ Chí Minh",
    "tp. ho chi minh": "Hồ Chí Minh",
    "thanh pho ho chi minh": "Hồ Chí Minh",
    "saigon": "Hồ Chí Minh",
    "sai gon": "Hồ Chí Minh",
    "thu duc": "Hồ Chí Minh",
    "quan thu duc": "Hồ Chí Minh",
    
    "da nang": "Đà Nẵng",
    "danang": "Đà Nẵng",
    "thanh pho da nang": "Đà Nẵng",
    
    "hai phong": "Hải Phòng",
    "haiphong": "Hải Phòng",
    "thanh pho hai phong": "Hải Phòng",
    
    "can tho": "Cần Thơ",
    "cantho": "Cần Thơ",
    "thanh pho can tho": "Cần Thơ",
    
    "hue": "Huế",
    "thua thien hue": "Huế",
    "tinh thua thien hue": "Huế",
    
    "an giang": "An Giang",
    "bac ninh": "Bắc Ninh",
    "ca mau": "Cà Mau",
    "cao bang": "Cao Bằng",
    
    "dak lak": "Đắk Lắk",
    "daklak": "Đắk Lắk",
    "dac lac": "Đắk Lắk",
    "buon ma thuot": "Đắk Lắk",
    
    "dien bien": "Điện Biên",
    "dong nai": "Đồng Nai",
    "bien hoa": "Đồng Nai",
    
    "dong thap": "Đồng Tháp",
    "cao lanh": "Đồng Tháp",
    
    "gia lai": "Gia Lai",
    "pleiku": "Gia Lai",
    
    "ha tinh": "Hà Tĩnh",
    "hung yen": "Hưng Yên",
    
    "khanh hoa": "Khánh Hòa",
    "nha trang": "Khánh Hòa",
    
    "lai chau": "Lai Châu",
    
    "lam dong": "Lâm Đồng",
    "da lat": "Lâm Đồng",
    
    "lang son": "Lạng Sơn",
    "lao cai": "Lào Cai",
    
    "nghe an": "Nghệ An",
    "vinh": "Nghệ An",
    
    "ninh binh": "Ninh Bình",
    
    "phu tho": "Phú Thọ",
    "viet tri": "Phú Thọ",
    
    "quang ngai": "Quảng Ngãi",
    
    "quang ninh": "Quảng Ninh",
    "ha long": "Quảng Ninh",
    
    "quang tri": "Quảng Trị",
    "son la": "Sơn La",
    "tay ninh": "Tây Ninh",
    "thai nguyen": "Thái Nguyên",
    "thanh hoa": "Thanh Hóa",
    "tuyen quang": "Tuyên Quang",
    "vinh long": "Vĩnh Long",

    # Other Provinces/Regions in Vietnam (to clean up the rest of the database)
    "binh duong": "Bình Dương",
    "thuan an": "Bình Dương",
    "thu dau mot": "Bình Dương",
    "tan uyen": "Bình Dương",
    "di an": "Bình Dương",
    
    "ba ria vung tau": "Bà Rịa - Vũng Tàu",
    "ba ria - vung tau": "Bà Rịa - Vũng Tàu",
    "vung tau": "Bà Rịa - Vũng Tàu",
    "phu my": "Bà Rịa - Vũng Tàu",
    
    "long an": "Long An",
    "ben luc": "Long An",
    "tan an": "Long An",
    
    "kien giang": "Kiên Giang",
    "phu quoc": "Kiên Giang",
    "rach gia": "Kiên Giang",
    
    "hai duong": "Hải Dương",
    "ha nam": "Hà Nam",
    "thai binh": "Thái Bình",
    "hoa binh": "Hòa Bình",
    "binh thuan": "Bình Thuận",
    "ninh thuan": "Ninh Thuận",
    "binh phuoc": "Bình Phước",
    "dak nong": "Đắk Nông",
    "phu yen": "Phú Yên",
    "quang nam": "Quảng Nam",
    "kon tum": "Kon Tum",
    "vinh phuc": "Vĩnh Phúc",
    "bac giang": "Bắc Giang",
    "nam dinh": "Nam Định",
    "ha giang": "Hà Giang",
    "bac kan": "Bắc Kạn",
    "yen bai": "Yên Bái",
    "tra vinh": "Trà Vinh",
    "soc trang": "Sóc Trăng",
    "bac lieu": "Bạc Liêu",
    "hau giang": "Hậu Giang",
    "tien giang": "Tiền Giang",
    "ben tre": "Bến Tre",
    
    # Countries
    "vietnam": "Việt Nam",
    "viet nam": "Việt Nam",
    "vn": "Việt Nam",
    
    "singapore": "Singapore",
    "sg": "Singapore",
    
    "japan": "Nhật Bản",
    "jp": "Nhật Bản",
    
    "korea": "Hàn Quốc",
    "south korea": "Hàn Quốc",
    "kr": "Hàn Quốc",
    
    "united states": "Hoa Kỳ",
    "us": "Hoa Kỳ",
    "usa": "Hoa Kỳ",
    
    "germany": "Đức",
    "de": "Đức",
    
    "australia": "Australia",
    "au": "Australia",
    
    "taiwan": "Đài Loan",
    "tw": "Đài Loan",
    
    "malaysia": "Malaysia",
    "my": "Malaysia",
    
    "belgium": "Bỉ",
    "be": "Bỉ",
    
    "norway": "Na Uy",
    "no": "Na Uy",
    
    "netherlands": "Hà Lan",
    "nl": "Hà Lan",
    
    "finland": "Phần Lan",
    "fi": "Phần Lan",
    
    "laos": "Lào",
    "lao": "Lào",
    "vientiane": "Lào",
}

def remove_diacritics(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in normalized if not unicodedata.combining(c))
    return cleaned.replace("đ", "d").replace("Đ", "D")

def clean_key(text: str) -> str:
    cleaned = remove_diacritics(text.lower())
    # Replace non-alphanumeric characters with spaces, strip extra spaces
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    return " ".join(cleaned.split())

def unwrap_location_string(v: Any) -> Any:
    if not v:
        return v
    
    # If it is a dictionary, unwrap directly
    if isinstance(v, dict):
        for k in ["value", "Value", "location", "Location"]:
            if k in v:
                return v[k]
        return v
        
    if isinstance(v, str):
        s = v.strip()
        # Check if it looks like a stringified dict
        if s.startswith("{") and s.endswith("}"):
            try:
                # ast.literal_eval is safe for parsing stringified python dicts
                parsed = ast.literal_eval(s)
                if isinstance(parsed, dict):
                    for k in ["value", "Value", "location", "Location"]:
                        if k in parsed:
                            return parsed[k]
            except Exception:
                # regex fallback for malformed string representations like:
                # "{'Value': 'Hà Nội, Bắc Ninh, Thái Bình, 'Confidence': 95}"
                match = re.search(r"['\"]Value['\"]\s*:\s*['\"](.*?)['\"]", s, re.IGNORECASE)
                if match:
                    # Clean up trailing commas/quotes if present
                    val = match.group(1).strip()
                    if val.endswith(",") or val.endswith("'") or val.endswith('"'):
                        val = val.rstrip(",'\"").strip()
                    return val
    return v

def normalize_location(raw_location: Any) -> Optional[str]:
    # First, unwrap stringified dictionaries/objects
    raw_location = unwrap_location_string(raw_location)
    if raw_location is None:
        return None
    
    s = str(raw_location).strip()
    if not s:
        return None

    # Handle composite location separators: comma, semicolon, slash, or " and " / " & "
    parts = re.split(r"[,;/]|\band\b|&", s, flags=re.IGNORECASE)

    # Rút gọn về ĐÚNG MỘT tỉnh/thành: nếu bất kỳ phần nào (quận/phường/thành phố)
    # map tới một tỉnh/thành trong LOCATION_MAP thì trả về đúng tên tỉnh/thành đó,
    # bỏ quận/phường và đuôi quốc gia. Nhờ vậy mọi biến thể của cùng một thành phố
    # ("Quận 1, Hồ Chí Minh, Việt Nam", "Thủ Đức", "District 1, HCM"...) gộp về một
    # giá trị duy nhất -> danh sách thành phố sạch và filter theo thành phố chính xác.
    for p in parts:
        canonical = LOCATION_MAP.get(clean_key(p.strip()))
        if canonical and canonical not in COUNTRY_CANONICAL:
            return canonical

    # Không nhận diện được tỉnh/thành: giữ hành vi title-case cũ nhưng loại bỏ mọi
    # cụm quốc gia (mọi alias, không chỉ "vietnam") để tránh đuôi quốc gia thừa.
    normalized_parts = []
    for p in parts:
        p_clean = p.strip()
        if not p_clean:
            continue
        if LOCATION_MAP.get(clean_key(p_clean)) in COUNTRY_CANONICAL:
            continue
        normalized_parts.append(p_clean.title())

    if not normalized_parts:
        return None

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for part in normalized_parts:
        if part not in seen:
            seen.add(part)
            deduped.append(part)

    return ", ".join(deduped)

def normalize_country(raw_country: Any) -> Optional[str]:
    # First, unwrap stringified dictionaries/objects
    raw_country = unwrap_location_string(raw_country)
    if raw_country is None:
        return None
    
    s = str(raw_country).strip()
    if not s:
        return None

    key = clean_key(s)
    if key in LOCATION_MAP:
        return LOCATION_MAP[key]
    
    # Fallback to Title case
    return s.title()

