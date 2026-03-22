-- Đặt lại job_id là SERIAL PRIMARY KEY, fingerprint là UNIQUE

-- 1. Xóa các ràng buộc cũ
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_pkey;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_fingerprint_key;

-- 2. Đổi job_id thành SERIAL (nếu chưa phải)
ALTER TABLE jobs ALTER COLUMN job_id DROP DEFAULT;
ALTER TABLE jobs ALTER COLUMN job_id TYPE BIGSERIAL;
ALTER TABLE jobs ALTER COLUMN job_id SET NOT NULL;

-- 3. Đặt lại PRIMARY KEY cho job_id
ALTER TABLE jobs ADD PRIMARY KEY (job_id);

-- 4. Đặt UNIQUE cho fingerprint
ALTER TABLE jobs ADD CONSTRAINT jobs_fingerprint_key UNIQUE (fingerprint);

-- 5. Đảm bảo các bảng phụ có foreign key đúng
ALTER TABLE job_skills DROP CONSTRAINT IF EXISTS job_skills_job_id_fkey;
ALTER TABLE job_skills ADD CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE job_industries DROP CONSTRAINT IF EXISTS job_industries_job_id_fkey;
ALTER TABLE job_industries ADD CONSTRAINT job_industries_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE salaries DROP CONSTRAINT IF EXISTS salaries_job_id_fkey;
ALTER TABLE salaries ADD CONSTRAINT salaries_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE job_benefits DROP CONSTRAINT IF EXISTS job_benefits_job_id_fkey;
ALTER TABLE job_benefits ADD CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;
