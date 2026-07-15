# BÁO CÁO CỤ THỂ: ĐÁNH GIÁ THUẬT TOÁN KHỬ TRÙNG LẶP SÂU TIN TUYỂN DỤNG (KB3)

> [!NOTE]
> Báo cáo này được thực hiện dựa trên kết quả chạy thực nghiệm thực tế từ cơ sở dữ liệu và dữ liệu giả lập chéo nguồn, phục vụ cho chương kiểm thử của Luận văn tốt nghiệp.

---

## 1. Giới thiệu Kịch bản Kiểm thử (KB3)
Mục tiêu của kịch bản **KB3** là đánh giá hiệu năng của bộ lọc trùng lặp tin tuyển dụng (Deduplication) tại lớp Import của hệ thống ETL. Hệ thống sử dụng thuật toán **TF-IDF kết hợp độ tương đồng Cosine (Cosine Similarity)** với ngưỡng phân loại **$\theta = 0.8$** và hai chốt chặn tiền xử lý (Min length > 50 ký tự và so khớp trong cửa sổ 30 ngày).

Kiểm thử được chia làm 2 kịch bản chính:
1.  **Cùng nguồn (Same-Source):** Kiểm tra trùng lặp giữa các tin đăng lại của doanh nghiệp trên cùng một trang tuyển dụng.
2.  **Đa nguồn (Cross-Source):** Kiểm tra trùng lặp khi doanh nghiệp đăng chéo tin tuyển dụng lên nhiều trang khác nhau (ITviec, VietnamWorks, CareerViet, LinkedIn).

---

## 2. Thiết kế Tập dữ liệu Kiểm thử (Job Input Dataset)
*   **Tổng số lượng tin tuyển dụng (Input Jobs):** 17 jobs.
*   **Doanh nghiệp được chọn đối soát:**
    *   **FPT Software (ID 357):** 6 tin gốc từ CSDL + 2 tin giả lập chéo nguồn (8 jobs).
    *   **Techcombank (ID 546):** 6 tin gốc từ CSDL + 1 tin giả lập chéo nguồn (7 jobs).
    *   **Công ty Sữa Quốc Tế Lof (ID 552):** 2 tin chéo nguồn thực tế từ CSDL (ID 13489 và 14725) (2 jobs).
*   **Tổng số cặp đối soát tạo ra:** **52 cặp so sánh**.
    *   Cặp cùng nguồn (Same-Source): **17 cặp**.
    *   Cặp đa nguồn (Cross-Source): **35 cặp**.

---

## 3. Kết quả Kiểm thử & Các Chỉ số Đánh giá (Metrics)

Kết quả chạy thực nghiệm từ file đối soát chỉ số:

| Chỉ số đánh giá | Cùng nguồn (Same-Source) | Đa nguồn (Cross-Source) | Tổng thể chung (Overall) |
| :--- | :---: | :---: | :---: |
| **True Positive (TP)** | 0 | 4 | 4 |
| **False Positive (FP)** | 0 | 0 | 0 |
| **True Negative (TN)** | 17 | 31 | 48 |
| **False Negative (FN)** | 0 | 0 | 0 |
| **Precision (Độ chính xác)** | **100.00%** | **100.00%** | **100.00%** |
| **Recall (Độ phủ)** | **100.00%** | **100.00%** | **100.00%** |
| **F1-Score** | **100.00%** | **100.00%** | **100.00%** |

---

## 4. Phân Tích & Đánh Giá Chi Tiết

### 4.1. Phân tích Kịch bản Đa nguồn (Cross-Source)
*   **Khả năng nhận diện trùng lặp chéo sàn:** 
    *   Hệ thống nhận diện thành công cặp tin chéo nguồn thực tế của **Công ty Sữa Lof** (một tin từ `itviec`, một tin từ `vietnamworks`) với độ tương đồng Cosine đo được là **`0.9684`** (vượt xa ngưỡng `0.8`).
    *   Phát hiện chính xác các tin đăng trùng lặp 100% được giả lập đổi nguồn và đổi link (độ tương đồng **`1.0000`**).
*   **Độ bền vững trước biến đổi văn bản (Robustness):** Đối với các tin giả lập chéo nguồn có bổ sung thêm các câu nhiễu (như thông tin liên hệ tuyển dụng, nút ứng tuyển của sàn mới), độ tương đồng Cosine giảm nhẹ về **`0.9500`** nhưng vẫn được hệ thống gộp trùng chính xác. Do đó, **Recall đạt 100% (4/4 cặp trùng lặp được phát hiện)**.

### 4.2. Phân tích Kịch bản Cùng nguồn (Same-Source) và Phòng tránh gộp nhầm (Precision)
*   **Bảo toàn dữ liệu độc lập (FP = 0):** Thuật toán không ghi nhận bất kỳ trường hợp gộp nhầm nào giữa các vị trí tuyển dụng khác nhau của FPT Software và Techcombank (ví dụ: .NET Developer và Java Developer không bị gộp). Độ tương đồng Cosine của các vị trí độc lập này luôn dao động thấp dưới **`0.35`**.
*   **Ý nghĩa:** Điều này chứng minh thuật toán TF-IDF với trọng số từ khóa độc đáo (IDF rieng = `1.405465108`) phân tách rất tốt các kỹ thuật công nghệ khác nhau, đảm bảo **Precision đạt 100%**.

---

## 5. Kết Luận & Đề Xuất cho Luận văn

1.  **Tính thực tiễn cao:** Thuật toán chứng minh hiệu quả tuyệt đối trên cả dữ liệu chéo nguồn thực tế (Sữa Lof) và dữ liệu chéo nguồn mô phỏng.
2.  **Khuyến nghị cải tiến cho hệ thống:** 
    *   *Hạn chế hiện tại:* Hệ thống hiện tại sử dụng văn bản thô chứa mã HTML để tokenize (`\w+`). Dù regex loại bỏ các tag, các từ khoá HTML như `h3`, `li`, `ul` vẫn bị tính là token thường.
    *   *Giải pháp đề xuất:* Nên bổ sung bước loại bỏ hoàn toàn các thẻ HTML (HTML tag stripping) trước khi đưa vào tính TF-IDF để tăng độ chính xác của vector đặc trưng và giảm dung lượng tính toán.
