"""
Script import Keyword ver2 với fuzzy matching + type
Logic:
- Fuzzy match 95%+ → UPDATE type, return skill_id
- Fuzzy match < 95% → INSERT mới
"""

import os
import sys
import pandas as pd
import psycopg2
from pathlib import Path
import re
import unicodedata

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded environment variables from .env")
except ImportError:
    print("⚠ python-dotenv not installed")

try:
    from fuzzywuzzy import fuzz
    HAS_FUZZY = True
    print("✓ fuzzywuzzy available for fuzzy matching")
except ImportError:
    HAS_FUZZY = False
    print("⚠ fuzzywuzzy not installed - fallback to exact matching only")

# Database config
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

def find_skill_match(skill_name, cur, threshold=95):
    """Tìm skill match trong DB (exact > substring > fuzzy)"""
    
    skill_lower = skill_name.lower().strip()
    
    # 1. Exact match
    cur.execute("SELECT skill_id FROM skills WHERE LOWER(skill_name) = %s", (skill_lower,))
    result = cur.fetchone()
    if result:
        return {'skill_id': result[0], 'match_type': 'exact', 'score': 100}
    
    # 2. Fuzzy matching nếu available
    if not HAS_FUZZY:
        return None
    
    # Lấy tất cả skill từ DB
    cur.execute("SELECT skill_id, skill_name FROM skills")
    all_skills = cur.fetchall()
    
    best_match = None
    best_score = 0
    
    for db_skill_id, db_skill_name in all_skills:
        score = fuzz.token_set_ratio(skill_lower, db_skill_name.lower())
        
        if score > best_score and score >= threshold:
            best_score = score
            best_match = {
                'skill_id': db_skill_id,
                'match_type': 'fuzzy',
                'score': best_score
            }
    
    return best_match

def import_skills_with_type(excel_file):
    """Import dữ liệu từ Excel với type"""
    
    print(f"\n📂 Đọc file Excel: {excel_file}")
    try:
        df = pd.read_excel(excel_file, sheet_name=0)
        print(f"✓ Đã đọc {len(df)} dòng từ Excel")
    except Exception as e:
        print(f"❌ Lỗi đọc file Excel: {e}")
        return False
    
    # Kiểm tra cột
    required_columns = ['NAME', 'TYPE']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        print(f"❌ Thiếu cột: {missing_cols}")
        print(f"📋 Các cột có sẵn: {list(df.columns)}")
        return False
    
    print(f"✓ Các cột bắt buộc có mặt: {required_columns}")
    
    # Chuẩn bị dữ liệu
    print("\n📝 Chuẩn bị dữ liệu...")
    df = df.dropna(subset=['NAME'])
    df['NAME'] = df['NAME'].astype(str).str.strip()
    df['TYPE'] = df['TYPE'].astype(str).str.strip()
    
    skills_data = df[['NAME', 'TYPE']].copy()
    skills_data = skills_data.drop_duplicates(subset=['NAME'], keep='first')
    
    print(f"✓ Chuẩn bị xong: {len(skills_data)} skills sẽ import")
    print(f"\n📊 Sample dữ liệu:")
    print(skills_data.head(10))
    
    # Kết nối database
    conn = get_connection()
    if not conn:
        return False
    
    print(f"\n💾 Bắt đầu import vào database...")
    try:
        cur = conn.cursor()
        
        insert_count = 0
        update_count = 0
        skip_count = 0
        fuzzy_matches = []
        updated_skills = []
        new_skills = []
        
        for idx, row in skills_data.iterrows():
            skill_name = row['NAME']
            skill_type = row['TYPE']
            
            try:
                # Tìm skill match
                match_result = find_skill_match(skill_name, cur, threshold=95)
                
                if match_result:
                    # Update type + return ID
                    skill_id = match_result['skill_id']
                    match_type = match_result['match_type']
                    score = match_result['score']
                    
                    cur.execute(
                        "UPDATE skills SET type = %s WHERE skill_id = %s",
                        (skill_type, skill_id)
                    )
                    conn.commit()
                    update_count += 1
                    
                    updated_skills.append({
                        'skill_id': skill_id,
                        'skill_name': skill_name,
                        'type': skill_type,
                        'match_type': match_type,
                        'score': score
                    })
                    
                    if match_type == 'fuzzy':
                        fuzzy_matches.append({
                            'from': skill_name,
                            'score': score
                        })
                else:
                    # Insert mới
                    cur.execute(
                        "INSERT INTO skills (skill_name, type) VALUES (%s, %s) RETURNING skill_id",
                        (skill_name, skill_type)
                    )
                    new_id = cur.fetchone()[0]
                    conn.commit()
                    insert_count += 1
                    
                    new_skills.append({
                        'skill_id': new_id,
                        'skill_name': skill_name,
                        'type': skill_type
                    })
                
                if (insert_count + update_count) % 100 == 0:
                    print(f"  ⏳ Đã xử lý {insert_count + update_count} records...")
                    
            except Exception as e:
                conn.rollback()
                print(f"  ❌ Lỗi xử lý skill '{skill_name}': {e}")
                skip_count += 1
        
        print(f"\n✅ Import thành công!")
        print(f"  📝 Thêm mới: {insert_count} skills")
        print(f"  🔄 Cập nhật type: {update_count} skills")
        print(f"  ❌ Lỗi: {skip_count}")
        
        # Hiệu thống kê
        if fuzzy_matches:
            print(f"\n🔗 {len(fuzzy_matches)} fuzzy matches (95%+):")
            for match in fuzzy_matches[:10]:
                print(f"  - '{match['from']}' (score: {match['score']}%)")
            if len(fuzzy_matches) > 10:
                print(f"  ... và {len(fuzzy_matches) - 10} matches khác")
        
        # Hiển thị updated skills (top 10)
        if updated_skills:
            print(f"\n📌 10 skills vừa được cập nhật type:")
            for skill in updated_skills[:10]:
                print(f"  [ID: {skill['skill_id']}] {skill['skill_name']} → Type: {skill['type']}")
        
        # Hiển thị new skills (top 10)
        if new_skills:
            print(f"\n✨ 10 skills mới thêm:")
            for skill in new_skills[:10]:
                print(f"  [ID: {skill['skill_id']}] {skill['skill_name']} → Type: {skill['type']}")
        
        # Total count
        cur.execute("SELECT COUNT(*) FROM skills")
        total = cur.fetchone()[0]
        print(f"\n📈 Tổng skills trong database: {total}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi import: {e}")
        conn.close()
        return False

def main():
    print("=" * 60)
    print("IMPORT SKILLS VỚI TYPE TỪ EXCEL")
    print("=" * 60)
    
    excel_file = "Keyword ver2. 110426.xlsx"
    
    if not Path(excel_file).exists():
        print(f"❌ File không tồn tại: {excel_file}")
        print(f"💡 Cách dùng: python import_skills_with_type.py [path_to_file.xlsx]")
        return
    
    success = import_skills_with_type(excel_file)
    
    if success:
        print("\n✅ Hoàn thành!")
    else:
        print("\n❌ Import thất bại!")

if __name__ == "__main__":
    main()
