# 📁 Input Data - Static Files

Chứa all file tĩnh cần thiết cho crawl pipeline.

## 📋 Files

- `keywords_daily.json` - Danh sách keywords chạy (tier1, tier2, tier3)

## 🔧 Cách Load

```python
# Option 1: Load keywords
from input import load_keywords

keywords = load_keywords()
print(keywords["tier1"])  # Main keywords
print(keywords["tier2"])  # Secondary keywords

# Option 2: Get count
from input import get_keywords_count

counts = get_keywords_count()
# Output: {"tier1": 8, "tier2": 2, "tier3": 1, "total": 11}

# Option 3: Get path
from input import DATA_DIR

keywords_file = DATA_DIR / "keywords_daily.json"
```

## 📝 keywords_daily.json Format

```json
{
  "tier1": [
    "python developer",
    "java developer",
    ...
  ],
  "tier2": [
    "frontend developer",
    "backend developer"
  ],
  "tier3": [
    "devops engineer"
  ]
}
```

Tier1: 8 keywords (chạy daily)
Tier2: 2 keywords (secondary)
Tier3: 1 keyword (occasional)

## ➕ Thêm File Mới

1. Tạo file tĩnh (ví dụ: `skills_master.json`)
2. Đặt trong `input/data/`
3. Update `input/__init__.py` để thêm loader function
4. Import và dùng!

---

Example:
```python
def load_skills_master():
    """Load skills_master.json"""
    skills_file = DATA_DIR / "skills_master.json"
    with open(skills_file) as f:
        return json.load(f)
```
