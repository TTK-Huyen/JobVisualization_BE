"""
Fix DB: Update category và type từ Excel file
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
print("FIX DB: UPDATE CATEGORY + TYPE TỪ EXCEL")
print("=" * 80)

# 1. Đọc Excel
print("\n1️⃣ ĐỌC FILE EXCEL...")
df_excel = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)
df_excel = df_excel.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
print(f"   ✓ Excel: {len(df_excel)} records")

# 2. Update category + type
print("\n2️⃣ UPDATE CATEGORY + TYPE...")

update_count = 0
error_count = 0

for idx, row in df_excel.iterrows():
    skill_name = row['NAME']
    category = row['SUBCATEGORY_NAME']
    skill_type = row['TYPE']
    
    try:
        cur.execute("""
            UPDATE skills 
            SET category = %s, type = %s
            WHERE LOWER(TRIM(skill_name)) = LOWER(TRIM(%s))
        """, (category, skill_type, skill_name))
        conn.commit()
        update_count += 1
        
        if update_count % 200 == 0:
            print(f"   ⏳ Đã update {update_count}/{len(df_excel)}...")
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ Lỗi update '{skill_name}': {e}")
        error_count += 1

print(f"   ✅ Đã update {update_count} records")
if error_count > 0:
    print(f"   ❌ Lỗi: {error_count}")

# 3. Kiểm tra kết quả
print("\n3️⃣ KIỂM TRA KẾT QUẢ...")

# Check NULL type
cur.execute("SELECT COUNT(*) FROM skills WHERE type IS NULL")
null_type_count = cur.fetchone()[0]
print(f"   Type NULL: {null_type_count}")

# Check category
cur.execute("""
SELECT COUNT(DISTINCT category) FROM skills
""")
category_count = cur.fetchone()[0]
print(f"   Unique categories: {category_count}")

# Check type
cur.execute("""
SELECT COUNT(DISTINCT type) FROM skills WHERE type IS NOT NULL
""")
type_count = cur.fetchone()[0]
print(f"   Unique types: {type_count}")

# 4. Verify bằng compare lại
print("\n4️⃣ VERIFY...")
cur.execute("""
SELECT skill_id, skill_name, category, type
FROM skills
ORDER BY skill_id
""")
db_data = cur.fetchall()
db_df = pd.DataFrame(db_data, columns=['skill_id', 'skill_name', 'category', 'type'])

# Map Excel data
excel_skill_to_data = {}
for idx, row in df_excel.iterrows():
    skill_lower = row['NAME'].lower().strip()
    excel_skill_to_data[skill_lower] = {
        'category': row['SUBCATEGORY_NAME'],
        'type': row['TYPE']
    }

# Compare
category_mismatch = 0
type_mismatch = 0

for idx, row in db_df.iterrows():
    skill_lower = row['skill_name'].lower().strip()
    if skill_lower in excel_skill_to_data:
        excel_data = excel_skill_to_data[skill_lower]
        if (row['category'] or "").lower().strip() != (excel_data['category'] or "").lower().strip():
            category_mismatch += 1
        if (row['type'] or "").lower().strip() != (excel_data['type'] or "").lower().strip():
            type_mismatch += 1

print(f"   Category mismatch: {category_mismatch}")
print(f"   Type mismatch: {type_mismatch}")
print(f"   Type NULL: {null_type_count}")

# 5. Tổng kết
print("\n" + "=" * 80)
if category_mismatch == 0 and type_mismatch == 0 and null_type_count == 0:
    print("✅ DB VÀ EXCEL HOÀN TOÀN GIỐNG NHAU!")
    print(f"\n📈 {len(db_df)} skills với:")
    print(f"   • skill_name: ✓")
    print(f"   • category: ✓")
    print(f"   • type: ✓ (không NULL)")
else:
    print(f"⚠️  VẪN CÒN VẤNĐỀ:")
    print(f"   Category mismatch: {category_mismatch}")
    print(f"   Type mismatch: {type_mismatch}")
    print(f"   Type NULL: {null_type_count}")

cur.close()
conn.close()

print("=" * 80)
