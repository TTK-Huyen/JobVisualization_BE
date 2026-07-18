# Hướng Dẫn Sử Dụng Thuật Toán Matching CV & Kỹ Năng

Tài liệu này hướng dẫn chi tiết cách cấu hình, chạy thử nghiệm và giải thích kết quả của thuật toán đối sánh CV ứng viên với bộ kỹ năng nghề nghiệp từ cơ sở dữ liệu (`public.job_group_skill_weights`).

---

## 📌 1. Cài đặt và cấu hình (Installation & Setup)

Để chạy được thuật toán, vui lòng hoàn thành đầy đủ các bước chuẩn bị dưới đây:

### 📥 A. Cài đặt các thư viện phụ thuộc (Dependencies)
Cài đặt các thư viện Python cần thiết thông qua `pip`:
```bash
pip install psycopg2-binary sentence-transformers numpy pdfplumber pytesseract pdf2image pillow python-dotenv google-generativeai sqlalchemy tqdm
```

### ⚙️ B. Cài đặt các công cụ bổ trợ hệ thống (System Tools)
Nếu CV của ứng viên ở định dạng hình ảnh (`.png`, `.jpg`, `.jpeg`) hoặc PDF dạng quét ảnh (Scan), hệ thống sẽ kích hoạt luồng **OCR** dự phòng. Luồng này yêu cầu cài đặt và thêm vào biến môi trường `PATH`:
1.  **Tesseract OCR**:
    *   **Windows**: Tải và cài đặt [Tesseract OCR for Windows](https://github.com/UB-Mannheim/tesseract/wiki). Thêm đường dẫn thư mục cài đặt (ví dụ: `C:\Program Files\Tesseract-OCR`) vào biến môi trường `PATH` của hệ thống.
2.  **Poppler** (dành cho thư viện `pdf2image` để chuyển trang PDF thành ảnh trước khi OCR):
    *   **Windows**: Tải bản build Poppler cho Windows (ví dụ từ [giải pháp này](http://blog.alivate.com.au/poppler-windows/) hoặc conda), giải nén và thêm thư mục `bin` vào biến môi trường `PATH`.

### 🔑 C. Cấu hình file Môi trường (`Db/.env`)
Chương trình tự động tìm kiếm file `.env` tại đường dẫn `Db/.env` (quét ngược từ thư mục hiện tại lên thư mục gốc). Hãy cấu hình các thông số sau:

1.  **Kết nối Database PostgreSQL**:
    ```ini
    PG_HOST=localhost
    PG_PORT=5432
    PG_DB=job_vis_clone       # Tên database của bạn
    PG_USER=postgres
    PG_PASSWORD=123456        # Mật khẩu kết nối
    ```
2.  **API Keys cho Gemini (Dùng để trích xuất kỹ năng từ CV)**:
    Khai báo ít nhất một API Key hợp lệ. Chương trình hỗ trợ tự động xoay vòng và cách ly key khi bị lỗi quota limit:
    ```ini
    GEMINI_API_KEY_1=AIzaSyDQxrq774EQeZ_7...
    GEMINI_API_KEY_2=AIzaSyCpTgN1I4z-wvu...
    ```

### 💾 D. Tạo file Cache Embeddings (`skills_embedding.pkl`)
Chương trình tối ưu hiệu năng bằng cách sử dụng bộ nhớ cache được tạo trước thay vì tính lại embeddings cho hàng ngàn kỹ năng mỗi lần chạy.
*   **Đường dẫn yêu cầu**: `Db/pipeline/normalize/cache/skills_embedding.pkl`
*   *Lưu ý*: Hãy đảm bảo đã chạy pipeline chuẩn hóa dữ liệu tối thiểu một lần để tạo ra tệp tin này trước khi chạy thuật toán khớp CV.

---

## 🚀 2. Hướng dẫn chạy thuật toán (CLI)

Chạy chương trình trực tiếp qua Command Prompt hoặc PowerShell từ thư mục gốc của dự án.

### 🔹 Cú pháp cơ bản
```powershell
python matching_cv/match_cv.py --cv <ĐƯỜNG_DẪN_CV> --search-group "<TÊN_NHÓM_CÔNG_VIỆC>"
```

### 🔹 Ví dụ chạy thực tế
```powershell
python matching_cv/match_cv.py --cv matching_cv/cv/CV_Business_Analyst.pdf --search-group "business systems analyst"
```

### 🔹 Các tham số nâng cao tùy chọn (Optional Flags)
*   `--threshold-possessed`: Điểm ngưỡng tương đồng tối thiểu để công nhận ứng viên **đã có** kỹ năng đó (mặc định: `0.75`).
*   `--threshold-partial`: Điểm ngưỡng tương đồng tối thiểu để đánh giá kỹ năng ở mức **cần bổ sung thêm** (mặc định: `0.30`).
*   `--confidence-threshold`: Ngưỡng tin cậy của Gemini khi trích xuất kỹ năng (mặc định: `0.85`, các kỹ năng dưới ngưỡng sẽ bị lọc bỏ).

---

## 📊 3. Ví dụ thực tế: Input & Output

### 📥 A. Ví dụ Input đầu vào
*   **Tham số `--cv`**: `matching_cv/cv/CV_Business_Analyst.pdf` (Một CV dạng PDF chứa các thông tin cá nhân, dự án và danh sách kỹ năng như SQL, Python, Agile, Scrum, JIRA, Microsoft Office, v.v.)
*   **Tham số `--search-group`**: `"business systems analyst"`

### 📤 B. Ví dụ Output đầu ra (Định dạng JSON in ra stdout)
Khi chạy lệnh thành công, chương trình sẽ in ra luồng dữ liệu JSON chi tiết dưới đây:

```json
{
  "job_title": "business systems analyst",
  "match_score": 0.456816,
  "match_percent": 45.68,
  "student_skills": [
    {
      "original_skill": "Agile/Scrum",
      "skill_id": 3842,
      "skill_name": "Scrum (Software Development)",
      "similarity_score": 0.8812
    },
    {
      "original_skill": "Project Management",
      "skill_id": 3,
      "skill_name": "Project Design",
      "similarity_score": 0.7541
    },
    {
      "original_skill": "System Analysis",
      "skill_id": 5875,
      "skill_name": "Systems Analysis",
      "similarity_score": 0.9323
    },
    {
      "original_skill": "SQL",
      "skill_id": 5629,
      "skill_name": "SQL (Programming Language)",
      "similarity_score": 1.0
    },
    {
      "original_skill": "Python",
      "skill_id": 5671,
      "skill_name": "Python (Programming Language)",
      "similarity_score": 1.0
    },
    {
      "original_skill": "D3.js",
      "skill_id": 5319,
      "skill_name": "D3.js (Javascript Library)",
      "similarity_score": 1.0
    },
    {
      "original_skill": "Jira",
      "skill_id": 3840,
      "skill_name": "JIRA",
      "similarity_score": 1.0
    },
    {
      "original_skill": "Microsoft Office",
      "skill_id": 252,
      "skill_name": "Microsoft Office",
      "similarity_score": 1.0
    },
    {
      "original_skill": "Excel",
      "skill_id": 123,
      "skill_name": "Microsoft Excel",
      "similarity_score": 0.9659
    },
    {
      "original_skill": "PowerPoint",
      "skill_id": 268,
      "skill_name": "Microsoft PowerPoint",
      "similarity_score": 0.9523
    },
    {
      "original_skill": "GitHub",
      "skill_id": 5994,
      "skill_name": "Github",
      "similarity_score": 1.0
    },
    {
      "original_skill": "English",
      "skill_id": 194,
      "skill_name": "English Language",
      "similarity_score": 0.8638
    },
    {
      "original_skill": "Vietnamese",
      "skill_id": 118,
      "skill_name": "Vietnamese Language",
      "similarity_score": 0.913
    }
  ],
  "matched_skills": [
    {
      "skill_id": 3840,
      "skill_name": "JIRA",
      "weight": 0.1552,
      "similarity": 1.0,
      "contribution": 0.1552
    },
    {
      "skill_id": 3839,
      "skill_name": "Agile Software Development",
      "weight": 0.0907,
      "similarity": 0.7951,
      "contribution": 0.072116,
      "matched_via": "Scrum (Software Development)"
    }
  ],
  "partially_matched_skills": [
    {
      "skill_id": 259,
      "skill_name": "Non-Verbal Communication",
      "weight": 0.1968,
      "similarity": 0.3257,
      "contribution": 0.064092,
      "gap": 0.132708,
      "matched_via": "English Language"
    },
    {
      "skill_id": 171,
      "skill_name": "Consulting",
      "weight": 0.1676,
      "similarity": 0.3376,
      "contribution": 0.056588,
      "gap": 0.111012,
      "matched_via": "Project Design"
    },
    {
      "skill_id": 236,
      "skill_name": "Problem Solving",
      "weight": 0.0239,
      "similarity": 0.4226,
      "contribution": 0.010099,
      "gap": 0.013801,
      "matched_via": "Systems Analysis"
    },
    {
      "skill_id": 165,
      "skill_name": "Communication",
      "weight": 0.0239,
      "similarity": 0.4435,
      "contribution": 0.0106,
      "gap": 0.0133,
      "matched_via": "English Language"
    }
  ],
  "missing_skills": [
    {
      "skill_id": 4203,
      "skill_name": "Atlassian Confluence",
      "weight": 0.2583,
      "similarity": 0.2619,
      "gap": 0.190644
    },
    {
      "skill_id": 116,
      "skill_name": "Analytical Skills",
      "weight": 0.0836,
      "similarity": 0.2448,
      "gap": 0.063135
    }
  ]
}
```

---

## 🔍 4. Giải thích chi tiết cấu trúc Output JSON

### 🔹 Định nghĩa các trường dữ liệu chung

| Tên trường dữ liệu | Kiểu dữ liệu | Ý nghĩa giải thích |
| :--- | :--- | :--- |
| `job_title` | `String` | Tên nhóm công việc mục tiêu dùng để so khớp. |
| `match_score` | `Float` | Điểm số khớp trung bình có trọng số (phạm vi từ `0.0` đến `1.0`). |
| `match_percent` | `Float` | Tỷ lệ phần trăm khớp CV tương ứng (`match_score * 100`). |
| `student_skills` | `Array` | Danh sách kỹ năng thô được trích xuất từ CV sau khi được chuẩn hóa thành công sang kỹ năng tương ứng trong DB. |
| `matched_skills` | `Array` | **Danh sách kỹ năng đã có** (đạt độ tương đồng ngữ nghĩa $\ge 0.75$ với kỹ năng yêu cầu trong cơ sở dữ liệu). |
| `partially_matched_skills` | `Array` | **Danh sách kỹ năng cần bổ sung thêm** (có điểm tương đồng ngữ nghĩa nằm trong khoảng $[0.3, 0.75)$). Các kỹ năng này thường được map gián tiếp thông qua một kỹ năng khác tương tự của ứng viên (được thể hiện ở cột `matched_via`). |
| `missing_skills` | `Array` | **Danh sách kỹ năng chưa có** (độ tương đồng ngữ nghĩa $< 0.3$). Đây là các lỗ hổng kỹ năng lớn nhất cần đào tạo thêm cho ứng viên. |

### 🔹 Giải thích thông số kỹ năng cụ thể
Trong mỗi kỹ năng thuộc 3 danh sách phân loại trên (`matched_skills`, `partially_matched_skills`, `missing_skills`) sẽ có các thông số:
*   `weight`: Trọng số tầm quan trọng ($W_i$) của kỹ năng này đối với vị trí công việc (lấy từ cơ sở dữ liệu `public.job_group_skill_weights`).
*   `similarity`: Độ tương đồng ngữ nghĩa cao nhất giữa kỹ năng yêu cầu này với các kỹ năng ứng viên có.
*   `contribution`: Đóng góp thực tế vào điểm số chung của ứng viên (`weight * similarity`).
*   `gap`: Khoảng cách thiếu hụt kỹ năng (`weight * (1.0 - similarity)`).
*   `matched_via`: Tên kỹ năng của ứng viên đã được sử dụng để khớp ngữ nghĩa với kỹ năng yêu cầu (chỉ hiển thị nếu không phải khớp trực tiếp qua ID).
