-- ==========================================================
-- FILE: CREATE_DATABASE_V2.sql
-- MÔ TẢ: Script tạo cấu trúc database tuyển dụng (Phiên bản tối ưu)
-- ==========================================================

-- ==========================================================
-- 1. DANH MỤC (NHÓM LÕI & ƯU TIÊN) - Chứa dữ liệu chuẩn hóa
-- ==========================================================

-- Bảng: skills
-- Mục đích: Lưu trữ danh sách chuẩn hóa các kỹ năng (Hard/Soft skill) để tái sử dụng.
CREATE TABLE IF NOT EXISTS skills (
    -- Khóa chính tự tăng, định danh nội bộ cho kỹ năng
    skill_id SERIAL PRIMARY KEY,
    
    -- Mã định danh duy nhất (Slug), ví dụ: 'python-core', 'microsoft-excel'. 
    -- Dùng để mapping dữ liệu tránh trùng lặp.
    skill_abr VARCHAR(100) UNIQUE, 
    
    -- Tên hiển thị đầy đủ của kỹ năng, ví dụ: 'Python Programming'
    skill_name VARCHAR(255) NOT NULL,
    
    -- Phân loại kỹ năng: 'Hard Skill', 'Soft Skill', hoặc 'Tool'
    category VARCHAR(50),          
    
    -- Thời điểm tạo bản ghi
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng: industries
-- Mục đích: Danh mục các ngành nghề hoạt động (IT, Xây dựng, Marketing...)
CREATE TABLE IF NOT EXISTS industries (
    industry_id SERIAL PRIMARY KEY,
    
    -- Tên ngành nghề, đảm bảo không trùng lặp
    industry_name VARCHAR(255) NOT NULL UNIQUE
);

-- Bảng: benefits
-- Mục đích: Danh mục chuẩn hóa các phúc lợi (Health Insurance, Remote Work, Training...)
CREATE TABLE IF NOT EXISTS benefits (
    benefit_id SERIAL PRIMARY KEY,
    
    -- Tên phúc lợi chuẩn hóa (tiếng Anh), ví dụ: 'health insurance', 'remote work'
    benefit_name VARCHAR(255) NOT NULL UNIQUE,
    
    -- Phân loại phúc lợi: 'Work_Flexibility', 'Compensation', 'Health_Insurance', etc.
    category VARCHAR(100),
    
    -- Thời điểm tạo bản ghi
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- 2. THÔNG TIN CÔNG TY
-- ==========================================================

-- Bảng: companies
-- Mục đích: Lưu thông tin chi tiết về nhà tuyển dụng
CREATE TABLE IF NOT EXISTS companies (
    -- ID này nên lấy từ nguồn dữ liệu gốc (ví dụ LinkedIn ID) để dễ cập nhật/đồng bộ
    company_id BIGINT PRIMARY KEY,
    
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Thay vì dùng mã số 0-7, dùng min-max để lọc theo quy mô nhân sự thực tế
    company_size_min INT, -- Ví dụ: 50
    company_size_max INT, -- Ví dụ: 200
    
    country VARCHAR(100),
    city VARCHAR(100),
    address TEXT,
    
    -- Link đến trang LinkedIn hoặc Website công ty
    url VARCHAR(500)
);

-- ==========================================================
-- 3. BẢNG CÔNG VIỆC (DỮ LIỆU THU THẬP TỪ BÀI POST)
-- ==========================================================

-- Bảng: jobs
-- Mục đích: Bảng trung tâm chứa thông tin bài đăng tuyển dụng
CREATE TABLE IF NOT EXISTS jobs (
    -- ID bài đăng (giữ nguyên ID từ nguồn gốc như LinkedIn)
    job_id BIGINT PRIMARY KEY,
    
    -- Liên kết với công ty. Nếu xóa công ty, set field này về NULL để giữ lại bài đăng (tùy chọn)
    company_id BIGINT REFERENCES companies(company_id) ON DELETE SET NULL,
    
    -- Tiêu đề bài đăng (Dữ liệu quan trọng nhất để gợi ý ban đầu)
    title VARCHAR(500) NOT NULL, 
    
    -- ĐOẠN VĂN QUAN TRỌNG: Chỉ chứa text mô tả kỹ năng, dùng cho NLP/Keyword Search
    skills_desc TEXT,            
    
    -- Toàn bộ nội dung mô tả công việc (JD)
    description TEXT,            
    
    -- CÁC BỘ LỌC (FILTER) QUAN TRỌNG:
    formatted_experience_level VARCHAR(100), -- Cấp độ: 'Entry', 'Senior', 'Director'...
    work_type VARCHAR(100),                  -- Loại hình: 'Full-time', 'Contract'...
    location VARCHAR(255),
    is_remote BOOLEAN DEFAULT FALSE,         -- True: Cho phép làm từ xa
    
    -- METADATA QUẢN LÝ:
    listed_time TIMESTAMP WITH TIME ZONE,    -- Thời điểm bài được đăng lên
    expiry_time TIMESTAMP WITH TIME ZONE,    -- Thời điểm bài hết hạn
    job_posting_url TEXT,                    -- Link gốc tới bài đăng
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Thời điểm hệ thống cào dữ liệu về
    
    -- THỐNG KÊ ĐỘ HOT (Dùng để sắp xếp Trending):
    applies INT DEFAULT 0, -- Số lượt ứng tuyển
    views INT DEFAULT 0,    -- Số lượt xem
    
    -- Optional: Thêm cột fingerprint để tránh trùng lặp bài đăng
    fingerprint VARCHAR(32) UNIQUE
);

-- ==========================================================
-- 4. CÁC BẢNG LIÊN KẾT (TRÁI TIM CỦA THUẬT TOÁN GỢI Ý)
-- ==========================================================

-- Bảng: job_skills
-- Mục đích: Liên kết N-N giữa Job và Skill.
-- Một Job có nhiều Skill, một Skill thuộc về nhiều Job.
CREATE TABLE IF NOT EXISTS job_skills (
    job_id BIGINT REFERENCES jobs(job_id) ON DELETE CASCADE, -- Xóa Job thì xóa luôn dòng này
    skill_id INT REFERENCES skills(skill_id) ON DELETE CASCADE,
    
    -- Cờ quan trọng: 
    -- TRUE = Do AI tự suy luận từ văn bản (có thể sai sót). 
    -- FALSE = Dữ liệu chính xác do người đăng chọn.
    is_inferred BOOLEAN DEFAULT FALSE,
    
    PRIMARY KEY (job_id, skill_id) -- Khóa chính kép, đảm bảo 1 job không trùng 1 skill 2 lần
);

-- Bảng: job_industries
-- Mục đích: Liên kết N-N giữa Job và Industry.
CREATE TABLE IF NOT EXISTS job_industries (
    job_id BIGINT REFERENCES jobs(job_id) ON DELETE CASCADE,
    industry_id INT REFERENCES industries(industry_id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, industry_id)
);

-- ==========================================================
-- 5. DỮ LIỆU BỔ TRỢ (NHÓM 3)
-- ==========================================================

-- Bảng: salaries
-- Mục đích: Tách riêng thông tin lương vì cấu trúc phức tạp và không bắt buộc
CREATE TABLE IF NOT EXISTS salaries (
    salary_id SERIAL PRIMARY KEY,
    job_id BIGINT REFERENCES jobs(job_id) ON DELETE CASCADE,
    
    min_salary DECIMAL(18, 2),
    max_salary DECIMAL(18, 2),
    med_salary DECIMAL(18, 2), -- Lương trung vị (Median)
    
    currency VARCHAR(10) DEFAULT 'VND', -- Đơn vị tiền tệ
    pay_period VARCHAR(20) -- Kỳ trả lương: 'MONTHLY', 'YEARLY', 'HOURLY'
);

-- Bảng: job_benefits
-- Mục đích: Liên kết N-N giữa Job và Benefit
CREATE TABLE IF NOT EXISTS job_benefits (
    job_id BIGINT REFERENCES jobs(job_id) ON DELETE CASCADE,
    benefit_id INT REFERENCES benefits(benefit_id) ON DELETE CASCADE,
    
    -- Cờ quan trọng: 
    -- TRUE = Do AI tự suy luận từ văn bản (có thể sai sót). 
    -- FALSE = Dữ liệu chính xác do người đăng chọn.
    is_inferred BOOLEAN DEFAULT FALSE,
    
    PRIMARY KEY (job_id, benefit_id)
);

-- ==========================================================
-- 6. TỐI ƯU HÓA (INDEXES) - BẮT BUỘC ĐỂ CHẠY NHANH
-- ==========================================================

-- Index cho tìm kiếm nhanh theo tiêu đề job
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);

-- Index cho bộ lọc theo kinh nghiệm (Bộ lọc phổ biến nhất)
CREATE INDEX IF NOT EXISTS idx_jobs_experience ON jobs(formatted_experience_level);

-- Index Full-text Search (GIN Index): 
-- Giúp tìm kiếm từ khóa trong cột skills_desc cực nhanh (thay vì dùng LIKE %...%)
CREATE INDEX IF NOT EXISTS idx_jobs_skills_search ON jobs USING GIN (to_tsvector('english', skills_desc));
