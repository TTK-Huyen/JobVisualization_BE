# constants.py - Danh sách từ khóa chuẩn hóa cho ETL pipeline
# Sử dụng để chuẩn hóa dữ liệu trước khi import vào PostgreSQL

# ==============================================================================
# 1. JOB TITLES (Phân loại công việc)
# ==============================================================================
JOB_CATEGORIES = {
    "Software/Web/Mobile": [
        # Core Software Engineering
        "software engineer", "software developer", "programmer",
        "backend engineer", "frontend engineer", "full stack engineer",
        
        # Web & Mobile Development
        "web developer", "mobile developer", "android developer", "ios developer", 
        "flutter developer", "react native developer",
        
        # Language-specific developers
        "java developer", ".net developer", "python developer", "nodejs developer", 
        "php developer", "golang developer",
        
        # QA & Testing
        "qa engineer", "test engineer", "software tester", "automation tester", "sdet",
        
        # Senior / Leadership
        "tech lead", "engineering lead", "principal engineer", "architect", "solutions architect"
    ],
    
    "Data/AI": [
        # Analytics
        "data analyst", "business analyst",
        
        # Data Engineering
        "data engineer", "analytics engineer", "bi developer",
        
        # Data Science
        "data scientist", "applied scientist",
        
        # Machine Learning & AI
        "machine learning engineer", "ai engineer", "mlops engineer",
        "computer vision engineer", "nlp engineer"
    ],
    
    "DevOps/Cloud/Infra": [
        # DevOps
        "devops engineer", "site reliability engineer", "sre",
        
        # Cloud
        "cloud engineer", "cloud architect",
        
        # Infrastructure
        "platform engineer", "infrastructure engineer",
        "system administrator", "linux administrator",
        
        # Network & Database
        "network engineer", "network administrator",
        "database administrator", "dba"
    ],
    
    "Security": [
        "cybersecurity analyst", "security engineer",
        "soc analyst", "incident responder",
        "penetration tester", "ethical hacker",
        "application security engineer", "devsecops",
        "iam engineer"
    ],
    
    "Product/Design": [
        "product manager", "technical product manager",
        "product owner", "scrum master",
        "ux designer", "ui designer", "product designer"
    ],
    
    "Other": []  # Default fallback
}


# ==============================================================================
# 2. SKILLS (Kỹ năng kỹ thuật)
# ==============================================================================
SKILL_KEYWORDS = {
    # A. Programming Languages
    "Languages": [
        "python", "java", "javascript", "typescript", "c#", "c++", "c/c++", "go", "php", 
        "kotlin", "swift", "ruby", "rust", "scala", "r", "dart", "sql"
    ],
    
    # B. Frameworks & Libraries
    "Frontend_Frameworks": [
        "react", "next.js", "next", "vue", "angular", "svelte"
    ],
    
    "Backend_Frameworks": [
        "node.js", "express", "nestjs", "spring", "spring boot", 
        ".net", "asp.net core", "django", "flask", "fastapi", "laravel"
    ],
    
    "Mobile_Frameworks": [
        "flutter", "react native", "android sdk", "swiftui", "uikit"
    ],
    
    "Testing_Frameworks": [
        "junit", "pytest", "jest", "cypress", "playwright", "selenium"
    ],
    
    # C. Data & AI Stack
    "Data_AI_Libraries": [
        "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow", "keras",
        "spark", "hadoop", "kafka", "airflow", "dbt",
        "mlflow", "kubeflow",
        "llm", "prompt engineering", "rag", "langchain"
    ],
    
    # D. Cloud & DevOps
    "DevOps_Tools": [
        "docker", "kubernetes", "helm",
        "ci/cd", "github actions", "gitlab ci", "jenkins",
        "terraform", "ansible",
        "linux", "bash", "nginx"
    ],
    
    "Cloud_Platforms": [
        "aws", "azure", "gcp"
    ],
    
    "Observability": [
        "prometheus", "grafana", "elk", "opentelemetry"
    ],
    
    # E. Databases & Storage
    "SQL_Databases": [
        "postgresql", "mysql", "sql server", "oracle"
    ],
    
    "NoSQL_Databases": [
        "mongodb", "redis", "elasticsearch"
    ],
    
    "Data_Warehouses": [
        "snowflake", "bigquery", "redshift", "databricks", "delta lake"
    ],
    
    # F. Security Skills
    "Security_Tools": [
        "owasp", "burp suite", "metasploit", "siem", "splunk",
        "iam", "oauth2", "oidc", "sso",
        "threat modeling", "vuln assessment", "pentest"
    ],
    
    # G. Methodologies
    "Methodologies": [
        "agile", "scrum", "kanban",
        "system design", "microservices", "clean architecture",
        "oop", "design patterns",
        "tdd", "bdd",
        "rest api", "graphql", "grpc"
    ]
}

# Gộp tất cả skills thành 1 list để quét nhanh
ALL_SKILLS = [skill for group in SKILL_KEYWORDS.values() for skill in group]


# ==============================================================================
# 3. JOB BENEFITS (Quyền lợi)
# ==============================================================================
BENEFITS_KEYWORDS = {
    # Work Style / Flexibility
    "Work_Flexibility": [
        "remote work", "hybrid work", "work from home", "wfh",
        "flexible working hours", "flexible schedule",
        "compressed workweek", "no overtime", "limited overtime"
    ],
    
    # Compensation & Financial
    "Compensation": [
        "competitive salary", "performance bonus", "annual bonus", "year-end bonus",
        "project bonus", "stock options",
        "salary review", "annual salary review", "bi-annual salary review",
        "sign-on bonus", "referral bonus", "overtime pay",
        "13th month salary"
    ],
    
    # Health & Insurance
    "Health_Insurance": [
        "health insurance", "private health insurance",
        "dental insurance", "vision insurance",
        "mental health support", "annual health check",
        "wellness program", "social insurance"
    ],
    
    # Learning & Career Growth
    "Learning_Development": [
        "training budget", "learning allowance",
        "certification sponsorship",
        "paid courses", "udemy", "coursera", "pluralsight",
        "conference sponsorship",
        "career path", "career roadmap",
        "mentorship program", "internal mobility"
    ],
    
    # Leave & Work-Life Balance
    "Leave_Benefits": [
        "paid time off", "pto", "annual leave", "sick leave",
        "personal leave", "parental leave", "maternity leave", "paternity leave",
        "birthday leave", "mental health day"
    ],
    
    # Equipment & Work Setup
    "Equipment": [
        "company laptop", "macbook provided",
        "work-from-home allowance", "ergonomic equipment",
        "software license provided"
    ],
    
    # Culture & Environment
    "Culture": [
        "international working environment", "multicultural team",
        "english-speaking environment", "flat organization",
        "open culture", "innovation-driven culture"
    ],
    
    # Legal / Contract
    "Contract_Benefits": [
        "full-time contract", "probation salary 100%",
        "tax support"
    ]
}

# Gộp tất cả benefits
ALL_BENEFITS = [benefit for group in BENEFITS_KEYWORDS.values() for benefit in group]

# ==============================================================================
# 4. VIETNAMESE TO ENGLISH BENEFIT MAPPING
# ==============================================================================
# Map Vietnamese benefit keywords to their English canonical forms
VIETNAMESE_TO_ENGLISH_BENEFITS = {
    # Insurance & Healthcare
    "chế độ bảo hiểm": "health insurance",
    "bảo hiểm y tế": "health insurance",
    "bảo hiểm xã hội": "social insurance",
    "bhxh": "social insurance",
    "chăm sóc sức khỏe": "health insurance",
    "chăm sóc sức khoẻ": "health insurance",
    "khám sức khỏe định kỳ": "annual health check",
    "khám sức khỏe": "annual health check",
    
    # Training & Development
    "đào tạo": "training budget",
    "học tập": "learning allowance",
    "nâng cao trình độ": "career path",
    
    # Compensation
    "tăng lương": "salary review",
    "tăng lương định kỳ": "salary review",
    "xét tăng lương": "salary review",
    "thưởng": "performance bonus",
    "chế độ thưởng": "performance bonus",
    "thưởng hiệu quả": "performance bonus",
    "thưởng tháng 13": "13th month salary",
    "lương tháng 13": "13th month salary",
    "thưởng cuối năm": "year-end bonus",
    
    # Leave & Time Off
    "nghỉ phép năm": "annual leave",
    "nghỉ phép": "paid time off",
    "ngày nghỉ phép": "annual leave",
    "nghỉ lễ": "paid time off",
    "nghỉ sinh nhật": "birthday leave",
    
    # Allowances
    "phụ cấp": "work-from-home allowance",
    "phụ cấp ăn trưa": "work-from-home allowance",
    "phụ cấp điện thoại": "work-from-home allowance",
    "phụ cấp xăng xe": "work-from-home allowance",
    "công tác phí": "work-from-home allowance",
    "chi phí công tác": "work-from-home allowance",
    
    # Travel & Activities
    "du lịch": "annual leave",
    "du lịch công ty": "annual leave",
    "du lịch hàng năm": "annual leave",
    "du lịch nước ngoài": "annual leave",
    "hoạt động nhóm": "open culture",
    "team building": "open culture",
    "dã ngoại": "open culture",
    
    # Equipment
    "laptop": "company laptop",
    "máy tính": "company laptop",
    "trang thiết bị làm việc": "ergonomic equipment",
    "đồng phục": "company laptop",
    "xe đưa đón": "work-from-home allowance",
    "xe buýt công ty": "work-from-home allowance",
    
    # Facilities
    "bãi đổ xe": "ergonomic equipment",
    "chỗ đậu xe": "ergonomic equipment",
    "phòng gym": "wellness program",
    "khu thể thao": "wellness program",
    "căng tin": "open culture",
    "ăn uống": "open culture"
}
