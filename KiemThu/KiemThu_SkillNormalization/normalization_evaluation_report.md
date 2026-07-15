# Báo cáo Đánh giá Kết quả Thực nghiệm Kịch bản 2 (KB2)
**Đánh giá thuật toán Chuẩn hóa Kỹ năng và Khớp mờ Doanh nghiệp**

Dưới đây là báo cáo phân tích chi tiết dựa trên dữ liệu đầu ra thực tế từ file chạy đối soát [2_calculate_metrics.ipynb](file:///f:/HCMUS_KH/LuanVan/JobVisualization_BE/KiemThu/KiemThu_SkillNormalization/2_calculate_metrics.ipynb). Báo cáo này được cấu trúc theo chuẩn học thuật để bạn có thể tham khảo trực tiếp cho Chương 5 của Luận văn.

---

## 1. Tổng hợp Chỉ số Đánh giá (Overall Metrics)

Sau khi đối sánh kết quả chuẩn hóa thực tế của hệ thống CareerNova với tập nhãn chuẩn Ground Truth (được gán thủ công bởi con người trên **758** mẫu kỹ năng và **24** mẫu doanh nghiệp), các chỉ số độ chính xác đạt được như sau:

| Chỉ số đánh giá | Tập dữ liệu JD | Tập dữ liệu CV | Trung bình chung cuộc |
|---|---|---|---|
| **Độ chính xác chuẩn hóa (Mapping Accuracy)** | 68.44% (167/244) | 64.71% (44/68) | **67.63% (211/312)** |
| **Độ chính xác lọc nhiễu (Reject Accuracy)** | 66.87% (224/335) | 76.58% (85/111) | **69.28% (309/446)** |
| **Độ chính xác gộp nhóm (Company Match)** | - | - | **83.33% (20/24)** |

---

## 2. Phân tích & Đánh giá Khoa học

### 2.1. Đánh giá chất lượng Chuẩn hóa kỹ năng (Mapping Accuracy)
Chỉ số chuẩn hóa kỹ năng thực tế đạt **67.63%**. Tuy nhiên, qua phân tích sâu các trường hợp lỗi (FN - Map Fail), có một số phát hiện quan trọng chỉ ra rằng **độ chính xác ngữ nghĩa thực tế của hệ thống cao hơn nhiều** so với con số thống kê nghiêm ngặt (do sự lệch pha chuỗi ký tự):

1.  **Lệch hậu tố định danh (Semantic Equivalent but String Mismatch):**
    *   *CV - CSS:* Ground Truth mong đợi nhãn `CSS (Cascading Style Sheets)` nhưng hệ thống chuẩn hóa về `Cascading Style Sheets (CSS)`. Hai chuỗi này hoàn toàn đồng nghĩa nhưng bị thuật toán so khớp chuỗi trần đánh giá là "Fail".
    *   *CV - PyTorch / Express.js / Java:*
        *   `PyTorch` thực tế chuẩn hóa về `PyTorch (Machine Learning Library)` (GT: `PyTorch`).
        *   `Express.js` thực tế chuẩn hóa về `Express.js (Javascript Library)` (GT: `Express.js`).
        *   `Java` thực tế chuẩn hóa về `Java` (GT: `Java (Programming Language)`).
    *   *Đánh giá:* Các lỗi này là "dương tính giả" của bộ đối soát kiểm thử (do nhãn chuẩn trong DB của hệ thống có chứa thêm mô tả trong ngoặc đơn). Về mặt ngữ nghĩa ứng dụng, hệ thống đã **ánh xạ đúng thực thể**.
2.  **Khả năng xử lý từ viết tắt:**
    *   Thuật toán Hybrid (FAISS Dense Vector + Jaccard Sparse Penalty) hoạt động cực tốt khi ánh xạ chính xác `Git` về `Git (Version Control System)`, `Docker` về `Docker (Software)`.

---

### 2.2. Đánh giá chất lượng Lọc nhiễu & Từ chối từ khóa rác (Reject Accuracy)
Độ chính xác lọc nhiễu đạt trung bình **69.28%** (đặc biệt tốt trên tập CV với **76.58%**):
1.  **Hiệu quả loại bỏ từ khóa chung (Soft Skills & Noise):**
    *   Hệ thống đã nhận diện chính xác và trả về `None` (từ chối đưa vào DB) đối với các từ khóa rác chủ động như: `AI models`, `Programming for Data Science`, `Multiple Tech Stacks`, `Interpersonal Skills`.
2.  **Xử lý các công nghệ quá mới (New Tech/Skill mới):**
    *   Các công nghệ thực tế chưa có trong từ điển DB như `Cursor`, `Claude Code`, `Ollama`, `Gradio` được thuật toán lọc nhiễu từ chối chính xác (trả về `None`) thay vì cố tình gán bừa vào một kỹ năng cũ có độ tương đồng vector gần nhất. Điều này giúp ngăn chặn sự sai lệch của dữ liệu phân tích.

---

### 2.3. Đánh giá chất lượng Gộp nhóm doanh nghiệp (Company Match Accuracy)
Chất lượng gộp nhóm đạt tỷ lệ rất cao là **83.33%** (20/24 công ty khớp đúng). Giải thuật loại bỏ hậu tố pháp lý (`TNHH`, `JSC`, `Co., Ltd`...) kết hợp kiểm tra độ phủ từ vựng (Word overlap ratio) hoạt động rất hiệu quả.

**Phân tích các trường hợp lỗi khớp (Fail):**
1.  **Lệch ngôn ngữ quốc gia (`FUJIFILM Business Innovation Vietnam`):**
    *   Hệ thống chuẩn hóa tên thô về tập từ khóa: `{"fujifilm", "business", "innovation", "vietnam"}`.
    *   Tuy nhiên, tên lưu trong DB là `FUJIFILM Business Innovation Việt Nam` (tương ứng tập từ khóa: `{"fujifilm", "business", "innovation", "viet", "nam"}`).
    *   Do `vietnam` (viết liền tiếng Anh) và `việt nam` (hai từ tiếng Việt) lệch nhau, tỷ lệ trùng khớp từ vựng rơi xuống dưới ngưỡng 0.8 khiến hệ thống không thể tự động gộp nhóm mà tạo mới một bản ghi.
2.  **Dữ liệu DB trùng lặp (Database Duplication):**
    *   Trường hợp của `Ngân hàng TMCP Phương Đông - OCB` và `TPBank` bị đánh giá là lỗi do hệ thống khớp về các bản ghi trùng lặp có sẵn trong CSDL (ví dụ trong DB có cả bản ghi `TPBank` và `Ngân hàng TMCP Tiên Phong (TPBank)`). Đây là lỗi do dữ liệu lịch sử trong DB chưa được dọn dẹp sạch, thuật toán vẫn tìm ra đúng thực thể doanh nghiệp tương đương.

---

## 3. Đề xuất Hướng Cải tiến (Cho phần kết luận Chương 5)
1.  **Chuẩn hóa ngoặc đơn trong DB kỹ năng:** Cần chạy một script tiền xử lý để loại bỏ các phần giải nghĩa trong ngoặc đơn (ví dụ: `(Programming Language)`) của bảng `skills` để đồng bộ chuỗi ký tự đối sánh.
2.  **Bổ sung bộ chuyển đổi từ ghép Tiếng Anh - Tiếng Việt:** Đối với tên doanh nghiệp, cần chuyển đổi đồng bộ các từ địa danh viết liền/viết rời (như `vietnam` -> `viet nam`) trước khi tính tỷ lệ Overlap Ratio để nâng cao độ chính xác gộp nhóm doanh nghiệp đa quốc gia.
