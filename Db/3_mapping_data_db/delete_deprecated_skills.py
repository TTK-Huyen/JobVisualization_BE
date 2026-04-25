"""
Xóa 471 deprecated skills khỏi DB
Giữ lại chỉ những skills ở Excel Lần 2
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
print("XÓA 471 DEPRECATED SKILLS")
print("=" * 80)

# 1. Lấy Excel Lần 2
print("\n1️⃣ ĐỌC EXCEL LẦN 2...")
df = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)
df = df.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
excel_skills = set(df['NAME'].str.lower().str.strip())
print(f"   Excel: {len(excel_skills)} unique skills")

# 2. Lấy DB
print("\n2️⃣ LẤY SKILLS TỪ DB...")
cur.execute("SELECT skill_id, skill_name FROM skills")
all_db_skills = cur.fetchall()
db_skills_dict = {row[1].lower().strip(): row[0] for row in all_db_skills}
print(f"   DB: {len(db_skills_dict)} skills")

# 3. Tìm skills cần xóa
print("\n3️⃣ TÌM SKILLS CẦN XÓA...")
skills_to_delete = []
for skill_name_lower, skill_id in db_skills_dict.items():
    if skill_name_lower not in excel_skills:
        skills_to_delete.append((skill_id, skill_name_lower))

print(f"   Cần xóa: {len(skills_to_delete)} skills")

# 4. Xóa
if len(skills_to_delete) > 0:
    print(f"\n4️⃣ XÓA {len(skills_to_delete)} SKILLS...")
    
    delete_count = 0
    for skill_id, skill_name in skills_to_delete:
        try:
            # Xóa skill
            cur.execute("DELETE FROM skills WHERE skill_id = %s", (skill_id,))
            conn.commit()
            delete_count += 1
            
            if delete_count % 50 == 0:
                print(f"   ⏳ Đã xóa {delete_count}/{len(skills_to_delete)}...")
                
        except Exception as e:
            conn.rollback()
            print(f"   ❌ Lỗi xóa skill_id {skill_id}: {e}")
    
    print(f"   ✅ Đã xóa {delete_count} skills")

# 5. Kiểm tra kết quả
print("\n5️⃣ KIỂM TRA KẾT QUẢ...")
cur.execute("SELECT COUNT(*) FROM skills")
total_after = cur.fetchone()[0]

print(f"   📊 DB sau cleanup: {total_after} skills")
print(f"   📄 Excel Lần 2: {len(excel_skills)} skills")

if total_after == len(excel_skills):
    print(f"   ✅ DB = Excel (hoàn hảo!)")
elif total_after > len(excel_skills):
    print(f"   ✅ DB ≥ Excel (+ {total_after - len(excel_skills)} từ nguồn khác)")
else:
    print(f"   ❌ DB < Excel (thiếu {len(excel_skills) - total_after})")

# 6. Show deleted skills
deleted_names = sorted([name for _, name in skills_to_delete])
print(f"\n6️⃣ SAMPLE 20 SKILLS VỪA XÓA:")
for i, name in enumerate(deleted_names[:20], 1):
    print(f"   {i:2d}. {name}")
if len(deleted_names) > 20:
    print(f"   ... và {len(deleted_names) - 20} skills khác")

cur.close()
conn.close()

print("\n" + "=" * 80)
print("✅ XÓA HOÀN THÀNH")
print("=" * 80)
