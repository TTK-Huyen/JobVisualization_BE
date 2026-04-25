import pandas as pd

print("=" * 80)
print("GIẢI THÍCH TẠI SAO 5648 EXCEL ≠ 5131 DB")
print("=" * 80)

# Đọc 2 file
df1 = pd.read_excel('Keyword Skill.xlsx', sheet_name=0)
df2 = pd.read_excel('Keyword ver2. 110426.xlsx', sheet_name=0)

# Clean
df1_clean = df1.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')
df2_clean = df2.dropna(subset=['NAME']).drop_duplicates(subset=['NAME'], keep='first')

# Convert to sets
set1 = set(df1_clean['NAME'].str.lower().str.strip())
set2 = set(df2_clean['NAME'].str.lower().str.strip())

print(f"\n📊 FILE SIZE:")
print(f"   Lần 1: {len(set1)} unique skills")
print(f"   Lần 2: {len(set2)} unique skills")

# So sánh
same = set1 & set2  # Có ở cả 2
only_1 = set1 - set2  # Chỉ ở Lần 1
only_2 = set2 - set1  # Chỉ ở Lần 2

print(f"\n📌 SO SÁNH:")
print(f"   Có ở cả 2 lần: {len(same)} skills")
print(f"   Chỉ ở Lần 1: {len(only_1)} skills")
print(f"   Chỉ ở Lần 2: {len(only_2)} skills")

print(f"\n🔍 CHI TIẾT:")
print(f"   Lần 2 = {len(same)} (same) + {len(only_2)} (new) = {len(same) + len(only_2)}")
print(f"   Hiện tại: {len(same)} + {len(only_2)} = {len(set2)} ✓")

print(f"\n💡 VỚI FUZZY MATCHING (95%):")
print(f"   Khi import Lần 2:")
print(f"   - {len(same)} skills ở cả 2 lần:")
print(f"     → Tìm thấy match ở DB (từ Lần 1)")
print(f"     → UPDATE (category/type)")
print(f"     → KHÔNG INSERT MỚI")
print(f"")
print(f"   - {len(only_2)} skills chỉ ở Lần 2:")
print(f"     → Không tìm thấy match")
print(f"     → INSERT MỚI")
print(f"")
print(f"   Result: DB = 5009 (Lần 1) + {len(only_2)} (mới) = {5009 + len(only_2)}")

print(f"\n✅ TỔNG KẾT:")
print(f"   | Excel | Lần 1 | Lần 2 | DB |")
print(f"   |-------|-------|-------|-----|")
print(f"   | Rows  | {len(df1):5d} | {len(df2):5d} | - |")
print(f"   | Unique| {len(set1):5d} | {len(set2):5d} | ? |")
print(f"   | New   | 137   | {len(only_2):5d} | 259 |")
print(f"   | DB    | -     | -     | 5131|")

print(f"\n📝 SAMPLE 10 SKILLS ở CÁCH 2 LẦN (UPDATE, không INSERT):")
for i, skill in enumerate(sorted(same)[:10], 1):
    print(f"   {i:2d}. {skill}")
print(f"   ... và {len(same) - 10} skills khác\n")

print(f"📝 SAMPLE 10 SKILLS CHỈ ở LẦN 2 (INSERT MỚI):")
for i, skill in enumerate(sorted(only_2)[:10], 1):
    print(f"   {i:2d}. {skill}")
if len(only_2) > 10:
    print(f"   ... và {len(only_2) - 10} skills khác")
