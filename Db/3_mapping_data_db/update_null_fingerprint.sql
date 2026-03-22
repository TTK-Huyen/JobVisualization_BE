-- Cập nhật fingerprint cho các dòng bị NULL trong bảng jobs
-- Sử dụng hash MD5 của title + company_id + listed_time làm fingerprint tạm
UPDATE jobs
SET fingerprint = md5(coalesce(title,'') || coalesce(company_id::text,'') || coalesce(listed_time::text,''))
WHERE fingerprint IS NULL;

-- Kiểm tra lại các dòng còn NULL fingerprint
SELECT * FROM jobs WHERE fingerprint IS NULL;
