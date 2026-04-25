"""
So sánh DB với Excel file - Check ID, skill_name, category, type có giống nhau không
"""

import pandas as pd
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('PG_HOST'),
    database=os.getenv('PG_DB'),
    user=os.getenv('PG_USER'),
    password=os.getenv('PG_PASSWORD')
)
cur = conn.cursor()

print("=" * 80)
print("SO SÁNH DB VỚI FILE EXCEL")
print("=" * 80)

# 1. Lấy DB
print("\n1️⃣ LẤY DATA TỪ DB...")
cur.execute("""
SELECT skill_id, skill_name, category, type
FROM skills
ORDER BY skill_id
""")
db_data = cur.fetchall()
db_df = pd.DataFrame(db_data, columns=['skill_id', 'skill_name', 'category', 'type'])
print(f"   ✓ DB: {len(db_df)} records")

# 2. Đọc Excel
print("\n2️⃣ ĐỌC FILE EXCEL...")
df_excel = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)
df_excel = df_excel.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
df_excel_clean = df_excel[['NAME', 'SUBCATEGORY_NAME', 'TYPE']].copy()
df_excel_clean.columns = ['skill_name', 'category', 'type']
df_excel_clean = df_excel_clean.reset_index(drop=True)
print(f"   ✓ Excel: {len(df_excel_clean)} records")

# 3. So sánh skill_name
print("\n3️⃣ SO SÁNH SKILL_NAME...")
db_names = set(db_df['skill_name'].str.lower().str.strip())
excel_names = set(df_excel_clean['skill_name'].str.lower().str.strip())

names_match = len(db_names & excel_names)
names_only_db = db_names - excel_names
names_only_excel = excel_names - db_names

print(f"   ✓ Giống nhau: {names_match}")
print(f"   ❌ Chỉ ở DB: {len(names_only_db)}")
print(f"   ❌ Chỉ ở Excel: {len(names_only_excel)}")

if len(names_only_db) > 0 or len(names_only_excel) > 0:
    print(f"\n   ⚠️  Có sự khác biệt trong skill_name!")
    if names_only_db:
        print(f"   Sample chỉ ở DB: {list(names_only_db)[:5]}")
    if names_only_excel:
        print(f"   Sample chỉ ở Excel: {list(names_only_excel)[:5]}")
else:
    print(f"   ✅ HOÀN HẢO: Tất cả skill_name giống nhau")

# 4. So sánh category
print("\n4️⃣ SO SÁNH CATEGORY...")
# Tạo map skill_name -> category từ cả 2 source
db_skill_to_category = dict(zip(
    db_df['skill_name'].str.lower().str.strip(),
    db_df['category']
))
excel_skill_to_category = dict(zip(
    df_excel_clean['skill_name'].str.lower().str.strip(),
    df_excel_clean['category']
))

category_mismatches = []
for skill_lower, db_cat in db_skill_to_category.items():
    if skill_lower in excel_skill_to_category:
        excel_cat = excel_skill_to_category[skill_lower]
        if (db_cat or "").lower().strip() != (excel_cat or "").lower().strip():
            category_mismatches.append({
                'skill': skill_lower,
                'db_category': db_cat,
                'excel_category': excel_cat
            })

if len(category_mismatches) == 0:
    print(f"   ✅ HOÀN HẢO: Tất cả category giống nhau")
else:
    print(f"   ⚠️  Phát hiện {len(category_mismatches)} category khác nhau:")
    for i, mismatch in enumerate(category_mismatches[:10], 1):
        print(f"   {i}. '{mismatch['skill']}'")
        print(f"      DB: {mismatch['db_category']}")
        print(f"      Excel: {mismatch['excel_category']}")
    if len(category_mismatches) > 10:
        print(f"   ... và {len(category_mismatches) - 10} khác")

# 5. So sánh type
print("\n5️⃣ SO SÁNH TYPE...")
db_skill_to_type = dict(zip(
    db_df['skill_name'].str.lower().str.strip(),
    db_df['type']
))
excel_skill_to_type = dict(zip(
    df_excel_clean['skill_name'].str.lower().str.strip(),
    df_excel_clean['type']
))

type_mismatches = []
type_null_in_db = []
for skill_lower, excel_type in excel_skill_to_type.items():
    if skill_lower in db_skill_to_type:
        db_type = db_skill_to_type[skill_lower]
        
        # Check nếu DB có NULL
        if db_type is None or str(db_type).lower().strip() in ['', 'none', 'nan']:
            type_null_in_db.append(skill_lower)
        # Check nếu khác nhau
        elif (db_type or "").lower().strip() != (excel_type or "").lower().strip():
            type_mismatches.append({
                'skill': skill_lower,
                'db_type': db_type,
                'excel_type': excel_type
            })

print(f"   Type NULL trong DB: {len(type_null_in_db)}")
if len(type_null_in_db) > 0:
    print(f"   Sample: {type_null_in_db[:5]}")

print(f"   Type không khớp: {len(type_mismatches)}")
if len(type_mismatches) > 0:
    print(f"   Sample:")
    for mismatch in type_mismatches[:3]:
        print(f"      '{mismatch['skill']}'")
        print(f"         DB: {mismatch['db_type']}")
        print(f"         Excel: {mismatch['excel_type']}")

if len(type_null_in_db) == 0 and len(type_mismatches) == 0:
    print(f"   ✅ HOÀN HẢO: Tất cả type giống nhau, không có NULL")

# 6. Tổng kết
print("\n" + "=" * 80)
print("📊 TỔNG KẾT")
print("=" * 80)

total_issues = len(names_only_db) + len(names_only_excel) + len(category_mismatches) + len(type_mismatches) + len(type_null_in_db)

if total_issues == 0:
    print("""
✅ DB VÀ EXCEL HOÀN TOÀN GIỐNG NHAU!
   • skill_name: ✓
   • category: ✓
   • type: ✓ (không NULL)
   
📈 Database sẵn sàng dùng cho job matching.
""")
else:
    print(f"""
⚠️  PHÁT HIỆN {total_issues} VẤNĐỀ:
   • skill_name khác: {len(names_only_db) + len(names_only_excel)}
   • category khác: {len(category_mismatches)}
   • type NULL: {len(type_null_in_db)}
   • type khác: {len(type_mismatches)}

💡 Cần review/fix trước khi dùng.
""")

cur.close()
conn.close()
