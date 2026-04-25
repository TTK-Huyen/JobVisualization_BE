# 📋 Hệ Thống Chuẩn Hóa Kỹ Năng Công Việc

> **Cho người không phải lập trình viên**: Đây là công cụ tự động để **làm sạch và sắp xếp danh sách kỹ năng** từ các tin tuyển dụng. Nó biến "Python", "python", "Python 3" → thành "Python" (mỗi cái chỉ 1 lần)

---

## 📁 Cấu Trúc Thư Mục

```
Db/2_clean_data/                 ← Thư mục chính
├── clean_process.py             ← Chương trình làm sạch dữ liệu ⭐ CẦN CHẠY
├── test_fuzzy_performance.py    ← Kiểm tra tốc độ + đúng đắn
├── constants.py                 ← Danh sách 5,648 kỹ năng chuẩn
├── requirements.txt             ← Thư viện cần cài đặt
├── .env                         ← Mã API, tài khoản
├── cache/                       ← Bộ nhớ đệm (tránh làm lặp lại)
├── input/                       ← Dữ liệu vào (tin tuyển dụng thô)
├── output/                      ← Dữ liệu ra (tin đã chuẩn hóa)
└── [data files]                 ← Ví dụ để test
```

## 🔧 Chức Năng Từng File (Giải Thích Dễ Hiểu)

| File | Làm Gì | Vai Trò |
|------|--------|--------|
| `clean_process.py` | **Chương trình chính**: Tự động làm sạch danh sách kỹ năng | Điều hành 2 bước: Fuzzy (78%) + Google AI (22%) |
| `test_fuzzy_performance.py` | Đo tốc độ: "Chương trình chạy nhanh không?" | Kiểm tra xem bước 1 (Fuzzy) hoạt động đúng |
| `constants.py` | Kho từ điển 5,648 kỹ năng chuẩn (Python, Java, ...) | Nguồn gốc: PostgreSQL database |
| `requirements.txt` | Danh sách công cụ cần cài | Chứa fuzzywuzzy, google-generativeai, psycopg2 |
| `.env` | Mã khóa (bí mật) để gọi dịch vụ Google AI | Google AI chỉ tìm trong 5648 kỹ năng, **không tạo ra mới** |

## 🚀 Pipeline Flow: "Con Đường" Từ Dữ Liệu Thô Đến Sạch

### **Bước 1: Lấy Dữ Liệu Thô** 📥
```
Một tin tuyển dụng trên LinkedIn, GlassDoor
         ↓
Google AI đọc tin + tìm kỹ năng yêu cầu
         ↓
Kế quả: ["Python", "node js", "ReactJS framework", "spring-boot", "python"]
        (có lặp, không chuẩn, viết tắt khác nhau)
```

### **Bước 2: Làm Sạch Nhanh (78% - MÁY HỌC) ⚡**
```
CÁCH LÀM (Tìm kiếm trong 5648 kỹ năng từ thư viện):

  1. Xem "python" → Tìm trong từ điển (exact match)
     💡 "Python" có trong từ điển → ✅ FIND (lấy category: "Backend")
     Kết quả: {"tên": "Python", "category": "Backend"}

  2. Xem "node js" → Exact match? Không → Tìm gần đúng?
     💡 "Node.js" có trong từ điển, gần giống "node js" → ✅ FUZZY (lấy category)
     Kết quả: {"tên": "Node.js", "category": "Backend"}

  3. Xem "spring-boot" → Exact? Không → Fuzzy? "spring boot" gần!
     💡 Match được 90% → Lấy "spring boot" từ điển (category: "Backend")
     Kết quả: {"tên": "spring boot", "category": "Backend"}

  4. Xem "react frontend" → Không khớp cái nào → ❌ SKIP (chuyển bước 3)

  5. Xem "python" lần 2 → Đã có trong cache → Skip (nhanh hơn)

KẾT QUẢ: 3/4 kỹ năng → chuẩn hóa xong (từ thư viện)
THỜI GIAN: Cực nhanh (76 kỹ năng/giây)
CHI PHÍ: $0 (không cần Google AI)
```

### **Bước 3: Làm Sạch Kỹ (Nếu Cần) (22% - GOOGLE AI) 🤖**
```
Những kỹ năng KHÔNG khớp ở bước 2:

Hành động:
  1. Gom từng batch 20 kỹ năng lại
  2. Hỏi Google AI: "Cụm từ này map với kỹ năng chuẩn nào trong từ điển? Category là gì?"
     (Google NOT tạo ra từ điển mới, chỉ tìm trong 5648 kỹ năng có sẵn)
  3. Google trả lời → Ghi vào CACHE (bộ nhớ) để lần sau "xyz" = "Python" luôn

💡 QUAN TRỌNG:
   • Từ điển = 5648 kỹ năng chuẩn (cố định, từ PostgreSQL)
   • Category = tên từ thư viện (ví dụ: Backend, Frontend, Database, ...)
   • Cache = bộ nhớ (nếu thấy "python" rồi → nhớ ra là "Python" ngay, không hỏi Google lần 2)

CHÍ PHÍ: $0.55 cho 50,000 tin tuyển dụng (Rất rẻ!)
(So sánh: Gọi từng cái 1 lần = $11, ĐẮT 20x)

KẾT QUẨ: Tổng cộng 90%+ chính xác
```
