import sys
import io
# Enforce UTF-8 output for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matching_cv.match_cv import upsert_user_cv, save_user_cv_skills, save_cv_job_match, get_db_connection

def main():
    print("=" * 70)
    print("MÔ PHỎNG CHẠY PIPELINE LƯU TRỮ KẾT QUẢ VÀO DATABASE")
    print("=" * 70)
    
    # 1. Đọc dữ liệu mock đã được extract và chuẩn hóa
    json_path = PROJECT_ROOT / "test_run" / "sample_extracted_normalized_cv_skills.json"
    if not json_path.exists():
        print(f"Lỗi: Không tìm thấy file {json_path}")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    student_skills = data["student_skills"]
    print(f"\n1. Đã load thành công {len(student_skills)} skill đã chuẩn hóa từ file JSON:")
    for skill in student_skills:
        print(f"   - {skill['original_skill']} -> {skill['skill_name']} (ID: {skill['skill_id']}, Similarity: {skill['similarity_score']})")

    # 2. Kết nối CSDL
    print("\n2. Đang kết nối tới database PostgreSQL...")
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        user_id = "c4743039-70e5-458b-a709-14b8a37fd538" # Minh Anh (User test có sẵn trong DB)
        file_name = "mock_cv_test.pdf"
        file_url = "f:/HCMUS_KH/LuanVan/JobVisualization_BE/matching_cv/cv/mock_cv_test.pdf"
        cv_text = "Dương Minh Anh. Backend Developer. Skills: Python, FastAPI, PostgreSQL, Docker, Git."
        search_group = "backend developer"
        match_percent = 78.50
        
        # Tạo dữ liệu match mẫu
        matched_skills = [
            {"skill_id": 5671, "skill_name": "Python (Programming Language)", "weight": 0.08, "similarity": 1.0, "contribution": 0.08},
            {"skill_id": 3850, "skill_name": "FastAPI", "weight": 0.07, "similarity": 0.95, "contribution": 0.0665},
            {"skill_id": 4787, "skill_name": "PostgreSQL", "weight": 0.06, "similarity": 0.98, "contribution": 0.0588}
        ]
        partially_matched_skills = [
            {"skill_id": 5822, "skill_name": "Docker (Software)", "weight": 0.05, "similarity": 0.92, "contribution": 0.0460, "gap": 0.0040}
        ]
        missing_skills = [
            {"skill_id": 4825, "skill_name": "Apache Kafka", "weight": 0.05, "similarity": 0.15, "gap": 0.0425}
        ]

        print("\n3. Đang thực thi các câu lệnh cập nhật CSDL (Đoạn tiếp theo của Pipeline)...")
        
        # --- BẢNG 1: public.user_cvs ---
        print("\n   [BẢNG 1]: public.user_cvs (Lưu thông tin tệp CV của sinh viên)")
        cv_id = upsert_user_cv(conn, user_id, file_name, file_url, cv_text)
        print(f"   => Upsert thành công vào bảng 'user_cvs'. Nhận được cv_id: {cv_id}")
        
        # --- BẢNG 2: public.user_cv_skills ---
        print("\n   [BẢNG 2]: public.user_cv_skills (Lưu các kỹ năng đã được chuẩn hóa của CV)")
        save_user_cv_skills(conn, cv_id, student_skills)
        print(f"   => Đã xóa kỹ năng cũ và insert {len(student_skills)} dòng vào bảng 'user_cv_skills'")
        
        # --- BẢNG 3: public.cv_job_matches ---
        print("\n   [BẢNG 3]: public.cv_job_matches (Lưu kết quả so khớp điểm số và phân tích gap)")
        save_cv_job_match(
            conn,
            cv_id,
            search_group,
            match_percent,
            matched_skills,
            partially_matched_skills,
            missing_skills
        )
        print(f"   => Upsert thành công kết quả so khớp vào bảng 'cv_job_matches' với điểm số {match_percent}%")
        
        conn.commit()
        print("\n4. Đã COMMIT thành công các thay đổi vào CSDL.")
        
        # 5. Truy vấn kiểm tra lại dữ liệu vừa cập nhật để xác thực
        print("\n5. Truy vấn kiểm tra dữ liệu thực tế trong các bảng:")
        print("-" * 70)
        
        # Query user_cvs
        cur.execute("SELECT cv_id, user_id, file_name, file_url, updated_at FROM public.user_cvs WHERE cv_id = %s", (cv_id,))
        cv_row = cur.fetchone()
        print(f"Dữ liệu trong bảng [user_cvs]:")
        print(f"  - cv_id      : {cv_row[0]}")
        print(f"  - user_id    : {cv_row[1]}")
        print(f"  - file_name  : {cv_row[2]}")
        print(f"  - file_url   : {cv_row[3]}")
        print(f"  - updated_at : {cv_row[4]}")
        
        # Query user_cv_skills
        cur.execute("""
            SELECT ucs.skill_id, s.skill_name, ucs.raw_skill, ucs.created_at
            FROM public.user_cv_skills ucs
            INNER JOIN public.skills s ON ucs.skill_id = s.skill_id
            WHERE ucs.cv_id = %s
        """, (cv_id,))
        skill_rows = cur.fetchall()
        print(f"\nDữ liệu trong bảng [user_cv_skills] ({len(skill_rows)} dòng):")
        for r in skill_rows:
            print(f"  - Skill ID: {r[0]} | Tên chuẩn hóa: {r[1]:<35} | Tên gốc CV: {r[2]}")
            
        # Query cv_job_matches
        cur.execute("""
            SELECT match_id, search_group, match_score, created_at, updated_at
            FROM public.cv_job_matches
            WHERE cv_id = %s
        """, (cv_id,))
        match_rows = cur.fetchall()
        print(f"\nDữ liệu trong bảng [cv_job_matches] ({len(match_rows)} dòng):")
        for r in match_rows:
            print(f"  - Match ID: {r[0]}")
            print(f"  - Nhóm ngành: {r[1]}")
            print(f"  - Điểm match: {r[2]}%")
            print(f"  - Tạo lúc: {r[3]} | Cập nhật lúc: {r[4]}")
            
    except Exception as e:
        conn.rollback()
        print(f"\n[LỖI] Đã có lỗi xảy ra. Tiến trình rollback database. Chi tiết: {e}")
    finally:
        cur.close()
        conn.close()
        print("\n" + "=" * 70)
        print("KẾT THÚC TIẾN TRÌNH MÔ PHỎNG")
        print("=" * 70)

if __name__ == "__main__":
    main()
