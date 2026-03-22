-- Đổi primary key bảng jobs sang fingerprint
-- 1. Xóa ràng buộc khóa chính hiện tại (job_id)
ALTER TABLE jobs DROP CONSTRAINT jobs_pkey;

-- 2. Nếu fingerprint chưa có UNIQUE, thêm vào (bạn đã có rồi thì bỏ qua bước này)
-- ALTER TABLE jobs ADD CONSTRAINT jobs_fingerprint_key UNIQUE (fingerprint);

-- 3. Đặt fingerprint làm PRIMARY KEY mới
ALTER TABLE jobs ADD PRIMARY KEY (fingerprint);

-- Nếu cần, đổi lại kiểu cột job_id (nếu trước đó là SERIAL PRIMARY KEY)
-- ALTER TABLE jobs ALTER COLUMN job_id TYPE BIGINT;
