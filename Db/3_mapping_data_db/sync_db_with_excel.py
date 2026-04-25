"""
Script đồng bộ DB với file Excel Lần 2
Mục đích: Đảm bảo DB có đầy đủ 5648 skills từ file Excel
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
print("ĐỒNG BỘ DB VỚI FILE EXCEL")
print("=" * 80)

# 1. Lấy skills hiện tại từ DB
print("\n1️⃣ LẤY SKILLS TỪ DB...")
cur.execute("SELECT LOWER(TRIM(skill_name)) FROM skills")
db_skills = set(row[0] for row in cur.fetchall())
print(f"   📊 DB hiện có: {len(db_skills)} unique skills")

# 2. Đọc file Excel
print("\n2️⃣ ĐỌC FILE EXCEL...")
df = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)
df = df.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
excel_skills = set(df['NAME'].str.lower().str.strip())
print(f"   📄 Excel có: {len(excel_skills)} unique skills")

# 3. So sánh
print("\n3️⃣ SO SÁNH...")
missing_in_db = excel_skills - db_skills  # Ở Excel nhưng không ở DB
already_in_db = excel_skills & db_skills   # Ở cả 2

print(f"   ✅ Đã có ở DB: {len(already_in_db)} skills")
print(f"   ❌ Thiếu ở DB: {len(missing_in_db)} skills")

# 4. INSERT những skills thiếu
if len(missing_in_db) > 0:
    print(f"\n4️⃣ INSERT {len(missing_in_db)} SKILLS THIẾU...")
    
    insert_count = 0
    for skill_name_lower in missing_in_db:
        # Tìm tên gốc từ Excel
        df_match = df[df['NAME'].str.lower().str.strip() == skill_name_lower]
        if len(df_match) > 0:
            original_name = df_match.iloc[0]['NAME']
            category = df_match.iloc[0]['SUBCATEGORY_NAME']
            
            try:
                cur.execute(
                    "INSERT INTO skills (skill_name, category) VALUES (%s, %s)",
                    (original_name, category)
                )
                conn.commit()
                insert_count += 1
                
                if insert_count % 50 == 0:
                    print(f"   ⏳ Đã insert {insert_count}/{len(missing_in_db)}...")
                    
            except Exception as e:
                conn.rollback()
                print(f"   ❌ Lỗi insert '{original_name}': {e}")
    
    print(f"   ✅ Đã insert {insert_count} skills")

# 5. Kiểm tra kết quả
print("\n5️⃣ KIỂM TRA KẾT QUẢ...")
cur.execute("SELECT COUNT(*) FROM skills")
total_now = cur.fetchone()[0]
print(f"   📊 DB hiện tại: {total_now} skills")
print(f"   📄 Excel có: {len(excel_skills)} skills")

if total_now >= len(excel_skills):
    print(f"\n✅ ĐỒng bộ thành công! DB ≥ Excel")
else:
    print(f"\n⚠️  DB ({total_now}) < Excel ({len(excel_skills)}) - cần kiểm tra")

# 6. Hiển thị sample thiếu
if len(missing_in_db) > 0:
    print(f"\n6️⃣ SAMPLE {min(10, len(missing_in_db))} SKILLS VỪA THÊM:")
    for i, skill in enumerate(sorted(list(missing_in_db))[:10], 1):
        print(f"   {i:2d}. {skill}")
    if len(missing_in_db) > 10:
        print(f"   ... và {len(missing_in_db) - 10} skills khác")

cur.close()
conn.close()

print("\n" + "=" * 80)
print("✅ HOÀN THÀNH")
print("=" * 80)
