# matching_cv

Mục tiêu module
- Trích xuất văn bản CV, gọi LLM để nhận diện kỹ năng của ứng viên, chuẩn hóa kỹ năng với embedding cache từ pipeline của `Db`, lấy trọng số kỹ năng của một `search_group` từ PostgreSQL, tính điểm tương thích (match) và các khoảng cách (gaps).

Cách chạy CLI
- Script chính: [matching_cv/match_cv.py](matching_cv/match_cv.py)
- Ví dụ chạy:

```bash
python matching_cv/match_cv.py --cv path/to/cv.pdf --search-group "backend engineer"
```

- Tham số bổ sung (tùy chọn): `--dry-run` để tránh thay đổi DB (hiện tại script chỉ đọc).

Input / Output mẫu
- Input: file CV (PDF hoặc ảnh) và tên `search_group` (chuỗi) có trong bảng `job_group_skill_weights`.
- Output: JSON in ra stdout, ví dụ:

```json
{
  "job_title": "backend engineer",
  "match_score": 0.523456,
  "match_percent": 52.35,
  "student_skills": [
    {"original_skill": "Python", "skill_id": 123, "skill_name": "Python", "similarity_score": 0.98}
  ],
  "matched_skills": [{"skill_id": 123, "skill_name": "Python", "weight": 0.3, "similarity": 1.0, "contribution": 0.3}],
  "skill_gaps": [{"skill_id": 456, "skill_name": "Django", "weight": 0.2, "similarity": 0.1, "gap": 0.18}]
}
```

Các bảng DB sử dụng
- `public.job_group_skill_weights` — bảng trọng số kỹ năng theo `search_group` (cột: `skill_id`, `weight_wi`, `search_group`).
- `public.skills` — mapping `skill_id` -> `skill_name`.
- (Pipeline normalization dùng `public.skills` để sinh cache embeddings.)

Công thức
- match_score = sum_i (weight_i * sim_i), với sim_i ∈ [0,1] là độ tương đồng của ứng viên với skill i.
- match_percent = match_score * 100.
- gap_i = weight_i * (1 - sim_i).

Các lỗi thường gặp và hướng xử lý
- Không tìm thấy `Db/.env` hoặc biến GEMINI_API_KEY_*: đảm bảo bạn có file `Db/.env` với biến PG_* (PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD) và GEMINI_API_KEY_1... để gọi LLM.
- Không tìm thấy `skills_embedding.pkl`: chạy pipeline normalize trong `Db` để tạo cache embeddings (tệp: `Db/pipeline/normalize/cache/skills_embedding.pkl`).
- Thiếu thư viện: cài đặt các phụ thuộc chính:

```bash
pip install psycopg2-binary sentence-transformers numpy pdfplumber pytesseract pdf2image pillow
```

- OCR thất bại: cài `tesseract` executable (hệ điều hành) và đảm bảo `pytesseract` được cài; hoặc cung cấp CV dưới dạng text-first PDF.
- LLM trả về JSON không hợp lệ: kiểm tra biến GEMINI key, và thử chạy với số lượng mẫu nhỏ; raw LLM output được lọc regex để tìm mảng JSON.

Ghi chú
- Script hiện dùng adapter LLM của `Db/llm` cho các cuộc gọi LLM và cache embeddings do pipeline tạo. Nếu muốn đổi model embedding, chỉnh `matching_cv/normalizer.py`.
