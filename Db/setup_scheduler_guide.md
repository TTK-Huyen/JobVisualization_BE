# Hướng Dẫn Cài Đặt Task Scheduler Crawl Tự Động (Cho Máy Khác/Máy Mới)

Tài liệu này hướng dẫn bạn từng bước cài đặt và lập lịch tự động chạy ETL pipeline cho **132 từ khóa** hàng ngày trên một máy tính Windows mới.

---

## 📌 BƯỚC 1: Chuẩn Bị Dự Án Trên Máy Mới

1. **Copy hoặc Clone dự án** vào một thư mục trên máy mới (ví dụ: `C:\JobVisualization_BE` hoặc `D:\JobVisualization_BE`).
2. **Cài đặt môi trường ảo Python (.venv)**:
   * Mở CMD hoặc PowerShell tại thư mục `Db` của dự án và chạy:
     ```powershell
     python -m venv .venv
     ```
   * Kích hoạt môi trường ảo và cài đặt các thư viện cần thiết:
     ```powershell
     .\.venv\Scripts\activate
     pip install -r requirements.txt
     ```

---

## 🛠️ BƯỚC 2: Cấu Hình Chạy Trong Windows Task Scheduler

Bạn có thể lựa chọn 1 trong 2 cách thiết lập dưới đây trong Task Scheduler tùy thuộc vào nhu cầu của mình.

### Cách 1: Thiết lập chạy trực tiếp file Python (Không cần file `.bat`)
Cách này tối giản, không cần file trung gian, Windows sẽ gọi trực tiếp file Python của môi trường ảo.

1. Tại phần **Action** của Task Scheduler -> Chọn **Start a program**:
   * **Program/script**: Trỏ tới file `python.exe` trong môi trường ảo của dự án trên máy mới:
     ```text
     C:\ĐƯỜNG_DẪN_PROJECT\JobVisualization_BE\Db\.venv\Scripts\python.exe
     ```
   * **Add arguments (optional)**: Nhập tên script chạy batches và tham số reset từ khóa:
     ```text
     run_all_daily_batches.py --reset-keywords
     ```
   * **Start in (optional)**: Nhập thư mục làm việc (bắt buộc để python định vị được file):
     ```text
     C:\ĐƯỜNG_DẪN_PROJECT\JobVisualization_BE\Db
     ```
2. Nhấn **OK** và **Finish**.

---

### Cách 2: Thiết lập chạy qua file Batch `.bat` (Dễ theo dõi Log)
Cách này giúp bạn tự động ghi lại log console của Python ra file `.log` để dễ dàng kiểm tra lỗi sau này.

1. Chỉnh sửa file **`run_daily_scheduler.bat`** tại thư mục `Db` trên máy mới, thay đường dẫn cho đúng với thực tế:
   ```batch
   @echo off
   cd /d "C:\ĐƯỜNG_DẪN_PROJECT\JobVisualization_BE\Db"
   call .venv\Scripts\activate.bat
   python run_all_daily_batches.py --reset-keywords >> all_daily_batches.log 2>&1
   ```
2. Tại phần **Action** của Task Scheduler -> Chọn **Start a program**:
   * **Program/script**: Trỏ tới file `.bat` bạn vừa lưu ở trên:
     ```text
     C:\ĐƯỜNG_DẪN_PROJECT\JobVisualization_BE\Db\run_daily_scheduler.bat
     ```
3. Nhấn **OK** và **Finish**.

---

## 🛠️ BƯỚC 3: Thiết Lập Cài Đặt Chung Cho Task Scheduler

### 1. Tạo Task mới:
* Mở **Task Scheduler** từ Windows Search.
* Tại cột **Actions** bên phải, click chọn **Create Task...** (Không chọn *Create Basic Task*).

### 2. Tab General (Cấu hình chung):
* **Name**: Đặt tên bất kỳ (ví dụ: `Daily_Job_Crawl_Pipeline`).
* **Security options**:
  * Tích chọn **Run whether user is logged on or not** *(Chạy ngầm kể cả khi bạn khóa máy hoặc không đăng nhập)*.
  * Tích chọn **Run with highest privileges** *(Chạy với quyền Administrator cao nhất)*.
* **Configure for**: Chọn **Windows 10** hoặc **Windows 11** tùy hệ điều hành máy đó.

### 3. Tab Triggers (Thời gian chạy):
* Nhấn **New...**
* **Begin the task**: Chọn **On a schedule**.
* Chọn **Daily** (Hàng ngày).
* **Start**: Chọn mốc thời gian bắt đầu chạy hàng ngày (nên chọn khoảng từ **1:00 AM** đến **3:00 AM** đêm để tối ưu tốc độ mạng và tránh bị chặn).
* Nhấn **OK**.

### 4. Tab Conditions (Điều kiện nguồn điện):
* Nhấp vào tab **Conditions**.
* Tại mục **Power**:
  * **Bỏ tích** dòng `Start the task only if the computer is on AC power` *(để máy laptop vẫn tự chạy kể cả khi dùng pin)*.
  * **Tích chọn** dòng `Wake the computer to run this task` *(để tự đánh thức máy tính dậy chạy nếu đang Sleep)*.

### 5. Hoàn tất & Xác nhận:
* Nhấn **OK** để lưu Task.
* Hệ thống sẽ hiển thị bảng yêu cầu **nhập Mật khẩu Windows** (mật khẩu mở máy tính) của bạn để xác thực quyền chạy ngầm. Hãy nhập mật khẩu rồi nhấn **OK**.

---

## 🔍 Cách Theo Dõi Hoạt Động Trên Máy Mới

* **Xem Log chi tiết (Nếu dùng Cách 2)**:
  Vào thư mục `Db` trên máy mới, mở file `all_daily_batches.log` để xem tiến độ crawl từng đợt 4 keyword.
* **Chạy thử thủ công**:
  Trong phần quản lý **Task Scheduler Library**, bạn có thể nhấp chuột phải vào Task vừa tạo (`Daily_Job_Crawl_Pipeline`) và chọn **Run** để kiểm tra xem hệ thống có tự kích hoạt chạy thành công hay không.
