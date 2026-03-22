-- Script: alter_jobs_to_serial_fixed.sql
-- Mục đích: Chuyển job_id thành SERIAL PRIMARY KEY (chuẩn PostgreSQL)

BEGIN;

-- 1. Xóa các ràng buộc liên quan (nếu có)
ALTER TABLE job_skills DROP CONSTRAINT IF EXISTS job_skills_job_id_fkey;
ALTER TABLE job_industries DROP CONSTRAINT IF EXISTS job_industries_job_id_fkey;
ALTER TABLE salaries DROP CONSTRAINT IF EXISTS salaries_job_id_fkey;
ALTER TABLE job_benefits DROP CONSTRAINT IF EXISTS job_benefits_job_id_fkey;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_pkey;

-- 2. Thiết lập sequence tự tăng cho job_id (PostgreSQL không có kiểu bigserial trực tiếp qua ALTER)
CREATE SEQUENCE IF NOT EXISTS jobs_job_id_seq OWNED BY jobs.job_id;
ALTER TABLE jobs ALTER COLUMN job_id SET DEFAULT nextval('jobs_job_id_seq');

-- 3. Đảm bảo job_id là NOT NULL
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