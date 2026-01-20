import json
import re
import unicodedata
from datetime import datetime

# Import file constants chứa dữ liệu chuẩn
try:
    import constants
    print("✅ Đã load dữ liệu từ constants.py")
except ImportError:
    print("❌ Lỗi: Không tìm thấy file constants.py cùng thư mục.")
    exit()

def slugify(text):
    """
    Hàm chuẩn hóa chuỗi (giống hệt trong process_data_v3.py)
    để đảm bảo slug trong DB khớp với slug lúc xử lý data.
    """
    if not text: return ""
    # Xử lý đặc biệt cho các từ khóa tech thông dụng trước khi bỏ dấu
    text = text.lower().replace("c++", "cpp").replace("c#", "c-sharp").replace(".net", "dot-net")
    # Bỏ dấu tiếng Việt và ký tự lạ
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text)
    # Thay khoảng trắng bằng gạch ngang
    return re.sub(r'[-\s]+', '-', text).strip('-')

def sql_escape(text):
    """Xử lý ký tự đặc biệt trong SQL (như dấu nháy đơn)"""
    return text.replace("'", "''")

def generate_sql_file(output_file='seed_data.sql'):
    print(f"🔄 Đang tạo file SQL: {output_file}...")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("-- ==========================================================\n")
        f.write(f"-- SEED DATA GENERATED FROM CONSTANTS.PY\n")
        f.write(f"-- Generated at: {datetime.now()}\n")
        f.write("-- ==========================================================\n\n")

        # ---------------------------------------------------------
        # 1. TẠO DỮ LIỆU BẢNG INDUSTRIES (Từ JOB_CATEGORIES keys)
        # ---------------------------------------------------------
        f.write("-- 1. Insert Industries (Dựa trên Keys của JOB_CATEGORIES)\n")
        if hasattr(constants, 'JOB_CATEGORIES'):
            for industry_name in constants.JOB_CATEGORIES.keys():
                safe_name = sql_escape(industry_name)
                # Dùng ON CONFLICT DO NOTHING để tránh lỗi nếu chạy lại script
                sql = f"INSERT INTO industries (industry_name) VALUES ('{safe_name}') ON CONFLICT (industry_name) DO NOTHING;\n"
                f.write(sql)
            print(f"   -> Đã ghi {len(constants.JOB_CATEGORIES)} ngành nghề.")
        else:
            print("   ⚠️ Không tìm thấy JOB_CATEGORIES trong constants.py")
        
        f.write("\n")

        # ---------------------------------------------------------
        # 2. TẠO DỮ LIỆU BẢNG SKILLS (Từ SKILL_KEYWORDS)
        # ---------------------------------------------------------
        f.write("-- 2. Insert Skills (Dựa trên SKILL_KEYWORDS)\n")
        skill_count = 0
        if hasattr(constants, 'SKILL_KEYWORDS'):
            for category, skills_list in constants.SKILL_KEYWORDS.items():
                for skill in skills_list:
                    # Tạo slug chuẩn
                    slug = slugify(skill)
                    safe_name = sql_escape(skill)
                    safe_cat = sql_escape(category)
                    
                    # Insert vào DB
                    # Lưu ý: skill_abr là UNIQUE, nên dùng làm key để check conflict
                    sql = (
                        f"INSERT INTO skills (skill_abr, skill_name, category) "
                        f"VALUES ('{slug}', '{safe_name}', '{safe_cat}') "
                        f"ON CONFLICT (skill_abr) DO UPDATE "
                        f"SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi\n"
                    )
                    f.write(sql)
                    skill_count += 1
            print(f"   -> Đã ghi {skill_count} kỹ năng.")
        else:
            print("   ⚠️ Không tìm thấy SKILL_KEYWORDS trong constants.py")

    print(f"\n✅ Hoàn tất! File '{output_file}' đã sẵn sàng.")
    print("👉 Bạn có thể mở tool quản lý DB (pgAdmin, DBeaver) và chạy file này.")

if __name__ == "__main__":
    generate_sql_file()