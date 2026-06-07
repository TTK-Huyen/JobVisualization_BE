import sys
import io
# Enforce UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matching_cv.match_cv import extract_student_skills_keyword_fallback, get_db_connection

def main():
    print("=" * 70)
    print("TEST CHỨC NĂNG TRÍCH XUẤT FALLBACK KHI HẾT KEY/TOKEN GEMINI")
    print("=" * 70)

    conn = get_db_connection()
    try:
        # Mock nội dung CV
        cv_text = """
        Nguyen Van A
        Backend Engineer Intern
        
        EXPERIENCE
        - Built REST APIs using FastAPI and Python.
        - Managed relational database with PostgreSQL.
        - Configured containers using Docker.
        - Version control with Git.
        - Basic programming in C and Go.
        """
        
        print(f"\nNội dung CV test:\n{cv_text.strip()}\n")
        
        # Chạy thử hàm fallback trích xuất từ khóa từ DB
        extracted = extract_student_skills_keyword_fallback(cv_text, conn)
        
        print("\nKết quả trích xuất kỹ năng bằng Khớp từ khóa (Database Fallback):")
        print("-" * 70)
        for i, item in enumerate(extracted, 1):
            print(f"  {i}. {item['skill']:<30} | Evidence: {item['evidence']}")
            
        # Kiểm tra xem có trích xuất đúng các skill nổi tiếng
        skills_found = [item['skill'] for item in extracted]
        assert "FastAPI" in skills_found, "Lỗi: Không tìm thấy FastAPI"
        assert "PostgreSQL" in skills_found, "Lỗi: Không tìm thấy PostgreSQL"
        assert "Docker (Software)" in skills_found or "Dockerfile" in skills_found or any("Docker" in s for s in skills_found), "Lỗi: Không tìm thấy Docker"
        
        print("\n=> TEST SUCCESSFUL: Hàm fallback khớp từ khóa hoạt động hoàn hảo!")

    except Exception as e:
        print(f"\n=> TEST FAILED: Gặp lỗi {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
