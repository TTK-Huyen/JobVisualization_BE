-- Script: alter_jobs_to_serial.sql
-- Mục đích: Chuyển job_id thành SERIAL PRIMARY KEY để tự động tăng

BEGIN;

-- 1. Đổi tên cột job_id cũ để backup (nếu cần)
-- ALTER TABLE jobs RENAME COLUMN job_id TO job_id_old;

-- 2. Xóa các ràng buộc liên quan (nếu có)
ALTER TABLE job_skills DROP CONSTRAINT IF EXISTS job_skills_job_id_fkey;
ALTER TABLE job_industries DROP CONSTRAINT IF EXISTS job_industries_job_id_fkey;
ALTER TABLE salaries DROP CONSTRAINT IF EXISTS salaries_job_id_fkey;
ALTER TABLE job_benefits DROP CONSTRAINT IF EXISTS job_benefits_job_id_fkey;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_pkey;

-- 3. Đổi kiểu job_id thành SERIAL (hoặc BIGSERIAL)
ALTER TABLE jobs ALTER COLUMN job_id TYPE BIGSERIAL;
ALTER TABLE jobs ALTER COLUMN job_id SET NOT NULL;

-- 4. Đặt lại PRIMARY KEY
ALTER TABLE jobs ADD PRIMARY KEY (job_id);

-- 5. Thêm lại các ràng buộc foreign key
ALTER TABLE job_skills ADD CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;
ALTER TABLE job_industries ADD CONSTRAINT job_industries_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;
ALTER TABLE salaries ADD CONSTRAINT salaries_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;
ALTER TABLE job_benefits ADD CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

COMMIT;

-- Nếu có lỗi duplicate key, hãy xóa các dòng trùng job_id trước khi chạy script này.