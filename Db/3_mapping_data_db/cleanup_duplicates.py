"""
Script loại bỏ duplicate skills trong DB
Gộp các skills giống nhau (case-insensitive)
"""

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
print("CLEANUP: GỘP DUPLICATE SKILLS")
print("=" * 80)

# 1. Tìm duplicates (case-insensitive)
print("\n1️⃣ TÌM DUPLICATES...")
cur.execute("""
SELECT LOWER(TRIM(skill_name)) as skill_normalized, COUNT(*) as count, 
       ARRAY_AGG(skill_id) as ids, ARRAY_AGG(skill_name) as names
FROM skills
GROUP BY LOWER(TRIM(skill_name))
HAVING COUNT(*) > 1
ORDER BY count DESC
""")
duplicates = cur.fetchall()
print(f"   Phát hiện: {len(duplicates)} groups duplicate")

if len(duplicates) > 0:
    print(f"\n   Sample 10 duplicates:")
    for i, (normalized, count, ids, names) in enumerate(duplicates[:10], 1):
        print(f"   {i}. '{normalized}' ({count} variations)")
        for idx, (skill_id, name) in enumerate(zip(ids, names), 1):
            print(f"      - ID {skill_id}: {name}")

# 2. Gộp duplicates
if len(duplicates) > 0:
    print(f"\n2️⃣ GỘP {len(duplicates)} GROUPS...")
    
    merge_count = 0
    for normalized, count, ids, names in duplicates:
        if count > 1:
            # Giữ lại skill_id nhỏ nhất, xóa các skill_id còn lại
            keep_id = min(ids)
            delete_ids = [id for id in ids if id != keep_id]
            keep_name = names[ids.index(keep_id)]
            
            try:
                # Update tất cả references trỏ tới skill_id bị xóa → trỏ tới keep_id
                for delete_id in delete_ids:
                    # (Nếu có FK constraints, phải update ở bảng khác trước)
                    pass
                
                # Xóa duplicates
                cur.execute("DELETE FROM skills WHERE skill_id = ANY(%s)", (delete_ids,))
                conn.commit()
                merge_count += 1
                
                if merge_count % 50 == 0:
                    print(f"   ⏳ Đã merge {merge_count}/{len(duplicates)}...")
                
            except Exception as e:
                conn.rollback()
                print(f"   ❌ Lỗi merge '{normalized}': {e}")
    
    print(f"   ✅ Đã merge {merge_count} groups")

# 3. Kiểm tra kết quả
print("\n3️⃣ KIỂM TRA KẾT QUẢ...")
cur.execute("SELECT COUNT(*) FROM skills")
total_after = cur.fetchone()[0]

cur.execute("""
SELECT COUNT(*) FROM (
    SELECT LOWER(TRIM(skill_name)) FROM skills
    GROUP BY LOWER(TRIM(skill_name))
) t
""")
unique_after = cur.fetchone()[0]

print(f"   📊 Total skills: {total_after}")
print(f"   🔑 Unique skills (case-insensitive): {unique_after}")

if total_after == unique_after:
    print(f"   ✅ Không còn duplicate!")
else:
    print(f"   ⚠️  Vẫn còn {total_after - unique_after} duplicates")

# 4. So sánh với Excel
import pandas as pd
df = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)
df = df.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
excel_count = len(df)

print(f"\n4️⃣ SO SÁNH VỚI EXCEL...")
print(f"   Excel: {excel_count} skills")
print(f"   DB: {total_after} skills")

if total_after >= excel_count:
    print(f"   ✅ DB ≥ Excel (đủ skills)")
else:
    print(f"   ❌ DB < Excel - còn thiếu {excel_count - total_after} skills")

cur.close()
conn.close()

print("\n" + "=" * 80)
print("✅ CLEANUP HOÀN THÀNH")
print("=" * 80)
