-- Xóa ràng buộc UNIQUE fingerprint nếu có
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_fingerprint_key;

-- Bổ sung fingerprint cho các job bị NULL, chỉ khi fingerprint sinh ra chưa tồn tại
UPDATE jobs j
SET fingerprint = md5(coalesce(title,'') || coalesce(company_id::text,'') || coalesce(listed_time::text,''))
WHERE fingerprint IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM jobs x
    WHERE x.fingerprint = md5(coalesce(j.title,'') || coalesce(j.company_id::text,'') || coalesce(j.listed_time::text,''))
  );

-- Xóa các dòng jobs bị trùng fingerprint, chỉ giữ lại 1 dòng cho mỗi fingerprint
DELETE FROM jobs a
USING jobs b
WHERE a.fingerprint = b.fingerprint
  AND a.ctid > b.ctid;

-- Kiểm tra lại các fingerprint còn trùng không
SELECT fingerprint, COUNT(*) FROM jobs GROUP BY fingerprint HAVING COUNT(*) > 1;
