"""
Script import dữ liệu Skill & Category từ file Excel vào PostgreSQL

Mapping:
- NAME (Excel) -> skill_name (DB)
- SUBCATEGORY_NAME (Excel) -> category (DB)
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2 import extras
import re
import unicodedata
from pathlib import Path

# Ensure console uses UTF-8 to avoid UnicodeEncodeError on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded environment variables from .env")
except ImportError:
    print("⚠ python-dotenv not installed. Using system environment variables.")

# Fuzzy matching
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
    print("✓ fuzzywuzzy available - sẽ dùng fuzzy matching")
except ImportError:
    FUZZY_AVAILABLE = False
    print("⚠ fuzzywuzzy not installed - chỉ dùng exact matching")
    print("  💡 Cài đặt: pip install fuzzywuzzy python-Levenshtein")

# Database configuration
DB_CONFIG = {
    "dbname": os.getenv("PG_DB", "postgre"),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", "123456"),
    "host": os.getenv("PG_HOST", "localhost"),
    "port": os.getenv("PG_PORT", "5432")
}

def get_connection():
    """Kết nối tới database"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ Lỗi kết nối database: {e}")
        print(f"🔍 Kiểm tra cấu hình: {DB_CONFIG}")
        return None

def find_similar_skill(skill_name, cur, threshold=85):
    """Tìm skill tương tự trong DB (exact hoặc fuzzy)"""
    
    # 1. Tìm exact match (case-insensitive)
    cur.execute(
        "SELECT skill_id, skill_name FROM skills WHERE LOWER(skill_name) = LOWER(%s)",
        (skill_name,)
    )
    exact_match = cur.fetchone()
    if exact_match:
        return {
            'skill_id': exact_match[0],
            'skill_name': exact_match[1],
            'match_type': 'exact',
            'score': 100
        }
    
    # 2. Nếu không có exact match và fuzzy available → dùng fuzzy
    if not FUZZY_AVAILABLE:
        return None
    
    # Lấy tất cả skill từ DB
    cur.execute("SELECT skill_id, skill_name FROM skills")
    all_skills = cur.fetchall()
    
    best_match = None
    best_score = 0
    
    for db_skill_id, db_skill_name in all_skills:
        # Dùng Token Set Ratio - tốt hơn cho chuỗi dài
        score = fuzz.token_set_ratio(skill_name.lower(), db_skill_name.lower())
        
        if score > best_score:
            best_score = score
            best_match = {
                'skill_id': db_skill_id,
                'skill_name': db_skill_name,
                'match_type': 'fuzzy',
                'score': best_score
            }
    
    # Chỉ trả về nếu score > threshold
    if best_match and best_score >= threshold:
        return best_match
    
    return None

def slugify(text):
    """Tạo slug từ text để dùng cho skill_abr"""
    if not text:
        return ""
    text = str(text).lower()
    text = text.replace("c++", "cpp").replace("c#", "c-sharp").replace(".net", "dot-net")
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text

def import_skills(excel_file, sheet_name=0):
    """Import dữ liệu từ Excel vào bảng skills"""
    
    # 1. Đọc file Excel
    print(f"\n📂 Đọc file Excel: {excel_file}")
    try:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        print(f"✓ Đã đọc {len(df)} dòng từ Excel")
    except Exception as e:
        print(f"❌ Lỗi đọc file Excel: {e}")
        return False
    
    # 2. Kiểm tra cột cần thiết
    required_columns = ['NAME', 'SUBCATEGORY_NAME']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        print(f"❌ Thiếu cột: {missing_cols}")
        print(f"📋 Các cột có sẵn: {list(df.columns)}")
        return False
    
    print(f"✓ Các cột bắt buộc có mặt: {required_columns}")
    
    # 3. Chuẩn bị dữ liệu
    print("\n📝 Chuẩn bị dữ liệu...")
    
    # Xóa dòng trống
    df = df.dropna(subset=['NAME'])
    df['NAME'] = df['NAME'].astype(str).str.strip()
    df['SUBCATEGORY_NAME'] = df['SUBCATEGORY_NAME'].astype(str).str.strip()
    
    # Tạo slug
    df['skill_abr'] = df['NAME'].apply(slugify)
    
    # Rename cột theo mapping
    df['skill_name'] = df['NAME']
    df['category'] = df['SUBCATEGORY_NAME']
    
    # Chọn cột cần import
    skills_data = df[['skill_name', 'category', 'skill_abr']].copy()
    
    # Kiểm tra trùng lặp theo skill_name
    duplicate_skills = skills_data[skills_data.duplicated(subset=['skill_name'], keep=False)]
    if len(duplicate_skills) > 0:
        print(f"\n⚠️  Phát hiện {len(duplicate_skills)} dòng trùng skill_name:")
        for idx, row in duplicate_skills.iterrows():
            print(f"    - {row['skill_name']} (Category: {row['category']})")
        print("   💡 Sẽ giữ lại dòng đầu tiên, các dòng sau sẽ bị bỏ qua")
    
    # Xóa duplicate theo skill_name (giữ dòng đầu)
    skills_data = skills_data.drop_duplicates(subset=['skill_name'], keep='first')
    
    print(f"✓ Chuẩn bị xong: {len(skills_data)} skills sẽ import (sau khi loại trùng)")
    print(f"\n📊 Sample dữ liệu:")
    print(skills_data.head(10))
    
    # 4. Kết nối database
    conn = get_connection()
    if not conn:
        return False
    
    # 5. Import vào database
    print(f"\n💾 Bắt đầu import vào database...")
    try:
        cur = conn.cursor()
        
        # Xóa dữ liệu cũ (tùy chọn - comment out để giữ dữ liệu)
        # cur.execute("DELETE FROM skills;")
        # print("✓ Xóa dữ liệu cũ")
        
        # Insert dữ liệu
        insert_count = 0
        update_count = 0
        skip_count = 0
        updated_skills = []
        fuzzy_matches = []
        
        for idx, row in skills_data.iterrows():
            skill_name = row['skill_name']
            category = row['category']
            skill_abr = row['skill_abr']
            
            try:
                # Tìm skill tương tự (exact hoặc fuzzy)
                match_result = find_similar_skill(skill_name, cur, threshold=90)
                
                if match_result:
                    # Nếu tìm thấy → UPDATE
                    existing_id = match_result['skill_id']
                    match_type = match_result['match_type']
                    score = match_result['score']
                    
                    cur.execute("""
                        UPDATE skills 
                        SET category = %s
                        WHERE skill_id = %s
                    """, (category, existing_id))
                    conn.commit()  # Commit sau mỗi update thành công
                    update_count += 1
                    
                    updated_skills.append({
                        'skill_name': skill_name,
                        'matched_to': match_result['skill_name'],
                        'category': category,
                        'skill_id': existing_id,
                        'match_type': match_type,
                        'score': score
                    })
                    
                    # Ghi nhận fuzzy match
                    if match_type == 'fuzzy':
                        fuzzy_matches.append({
                            'from': skill_name,
                            'to': match_result['skill_name'],
                            'score': score
                        })
                else:
                    # Nếu không tìm thấy → INSERT
                    cur.execute("""
                        INSERT INTO skills (skill_name, category)
                        VALUES (%s, %s)
                    """, (skill_name, category))
                    conn.commit()  # Commit sau mỗi insert thành công
                    insert_count += 1
                
                if (insert_count + update_count) % 50 == 0:
                    print(f"  ⏳ Đã xử lý {insert_count + update_count} records...")
                    
            except Exception as e:
                conn.rollback()  # Rollback transaction bị lỗi
                print(f"  ❌ Lỗi xử lý skill '{skill_name}': {e}")
                skip_count += 1
        print(f"\n✅ Đồng bộ thành công!")
        print(f"  📝 Thêm mới: {insert_count} skills")
        print(f"  🔄 Cập nhật: {update_count} skills")
        print(f"  ❌ Lỗi: {skip_count}")
        
        # Hiển thị danh sách skills bị cập nhật
        if updated_skills:
            print(f"\n📌 {len(updated_skills)} skills vừa được cập nhật:")
            for skill in updated_skills[:20]:  # Show top 20
                if skill['match_type'] == 'exact':
                    print(f"  [ID: {skill['skill_id']}] {skill['skill_name']} → Category: {skill['category']}")
                else:
                    print(f"  [ID: {skill['skill_id']}] {skill['skill_name']} ≈ {skill['matched_to']} ({skill['score']}%) → Category: {skill['category']}")
            if len(updated_skills) > 20:
                print(f"  ... và {len(updated_skills) - 20} skills khác")
        
        # Hiển thị fuzzy matches
        if fuzzy_matches:
            print(f"\n🔗 {len(fuzzy_matches)} fuzzy matches được áp dụng:")
            for match in fuzzy_matches[:15]:
                print(f"  '{match['from']}' ≈ '{match['to']}' ({match['score']}%)")
            if len(fuzzy_matches) > 15:
                print(f"  ... và {len(fuzzy_matches) - 15} matches khác")
        
        # 6. Kiểm tra kết quả
        cur.execute("SELECT COUNT(*) FROM skills;")
        total_skills = cur.fetchone()[0]
        print(f"\n📈 Tổng skills trong database: {total_skills}")
        
        # Hiển thị 10 skills vừa import
        cur.execute("""
            SELECT skill_id, skill_name, category
            FROM skills
            ORDER BY skill_id DESC
            LIMIT 10
        """)
        print(f"\n📌 10 skills gần nhất:")
        for skill in cur.fetchall():
            print(f"  [{skill[0]}] {skill[1]} → Category: {skill[2]}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi import: {e}")
        conn.rollback()
        conn.close()
        return False

def main():
    """Hàm chính"""
    print("=" * 60)
    print("IMPORT SKILLS & CATEGORY TỪ EXCEL VÀO DATABASE")
    print("=" * 60)
    
    # Tìm file Excel
    excel_file = None
    
    # 1. Tìm file trong thư mục hiện tại
    if Path("Keyword Skill.xlsx").exists():
        excel_file = "Keyword Skill.xlsx"
    
    # 2. Tìm trong workspace root
    if not excel_file and Path("../../Keyword Skill.xlsx").exists():
        excel_file = "../../Keyword Skill.xlsx"
    
    # 3. Lấy từ argument dòng lệnh
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
    
    if not excel_file:
        print("❌ Không tìm thấy file Excel 'Keyword Skill.xlsx'")
        print("💡 Cách dùng: python import_skills_from_excel.py [path_to_file.xlsx]")
        return
    
    if not Path(excel_file).exists():
        print(f"❌ File không tồn tại: {excel_file}")
        return
    
    # Import dữ liệu
    success = import_skills(excel_file)
    
    if success:
        print("\n✅ Hoàn thành!")
    else:
        print("\n❌ Import thất bại!")

if __name__ == "__main__":
    main()
