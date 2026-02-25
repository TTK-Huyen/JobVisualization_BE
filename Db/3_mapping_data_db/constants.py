# constants.py - Danh sách từ khóa chuẩn hóa cho ETL pipeline
# Updated: Strictly mapped from Keyword (2).docx

# ==============================================================================
# 1. JOB TITLES (Phân loại công việc)
# ==============================================================================
JOB_CATEGORIES = {
    "Software/Web/Mobile": [
        # A. Software / Web / Mobile [cite: 2]
        "software engineer", "software developer", "programmer", # [cite: 3]
        "backend engineer", "frontend engineer", "full stack engineer", # [cite: 4]
        
        "web developer", "mobile developer", "android developer", "ios developer", 
        "flutter developer", "react native developer", # [cite: 5]
        
        "java developer", ".net developer", "python developer", "nodejs developer", 
        "php developer", "golang developer", # [cite: 6]
        
        "qa engineer", "test engineer", "software tester", "automation tester", "sdet", # [cite: 7]
        
        "tech lead", "engineering lead", "principal engineer", "architect", "solutions architect" # [cite: 8]
    ],
    
    "Data/AI": [
        # B. Data / AI [cite: 9]
        "data analyst", "business analyst", "IT BA", "tech BA", # [cite: 10]
        "data engineer", "analytics engineer", "bi developer", # [cite: 11]
        
        "data scientist", "applied scientist", # [cite: 12]
        
        "machine learning engineer", "ai engineer", # [cite: 13]
        "mlops engineer", # [cite: 14]
        "computer vision engineer", "nlp engineer" # [cite: 15]
    ],
    
    "DevOps/Cloud/Infra": [
        # C. DevOps / Cloud / Infra [cite: 16]
        "devops engineer", "site reliability engineer", "sre", # [cite: 17]
        
        "cloud engineer", "cloud architect", # [cite: 18]
        
        "platform engineer", "infrastructure engineer", # [cite: 19]
        
        "system administrator", "linux administrator", # [cite: 20]
        
        "network engineer", "network administrator", # [cite: 21]
        
        "database administrator", "dba" # [cite: 22]
    ],
    
    "Security": [
        # D. Security [cite: 23]
        "cybersecurity analyst", "security engineer", # [cite: 24]
        "soc analyst", "incident responder", # [cite: 25]
        "penetration tester", "ethical hacker", # [cite: 26]
        "application security engineer", # [cite: 27]
        "iam engineer" # [cite: 28]
    ],
    
    "Product/Design": [
        # E. Product / Design [cite: 29]
        "product manager", "technical product manager", # [cite: 30]
        "product owner", "scrum master", # [cite: 31]
        "ux designer", "ui designer", "product designer" # [cite: 32]
    ],
    
    "Other": []
}

# ==============================================================================
# 2. SKILLS (Kỹ năng kỹ thuật)
# ==============================================================================
SKILL_KEYWORDS = {
    # A. Language [cite: 34]
    "Languages": [
        "python", "java", "javascript", "typescript", "c#", "c/c++", "go", "php", 
        "kotlin", "swift", "ruby", "rust", "scala", "r", "dart", "sql" # [cite: 35]
    ],
    
    # B. Framework / Library [cite: 36]
    "Frontend_Frameworks": [
        "react", "next.js", "vue", "next", "angular", "svelte" # [cite: 37]
    ],
    
    "Backend_Frameworks": [
        "node.js", "express", "nestjs", "spring", "spring boot", ".net", 
        "asp.net core", "django", "flask", "fastapi", "laravel" # [cite: 38]
    ],
    
    "Mobile_Frameworks": [
        "flutter", "react native", "android sdk", "swiftui", "uikit" # [cite: 39]
    ],
    
    "Testing_Frameworks": [
        "junit", "pytest", "jest", "cypress", "playwright", "selenium" # [cite: 40]
    ],
    
    # C. Data / AI stack [cite: 41]
    "Data_AI_Stack": [
        "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow", "keras",
        "spark", "hadoop", "kafka", 
        "airflow", "dbt", 
        "mlflow", "kubeflow", 
        "llm", "prompt engineering", "rag", "langchain" # [cite: 42]
    ],
    
    # D. Cloud / DevOps [cite: 43]
    "Cloud_DevOps_Tools": [
        "docker", "kubernetes", "helm", 
        "ci/cd", "github actions", "gitlab ci", "jenkins", 
        "terraform", "ansible", 
        "aws", "azure", "gcp", 
        "linux", "bash", "nginx", 
        "observability", "prometheus", "grafana", "elk", "opentelemetry" # [cite: 44]
    ],
    
    # E. Database / Storage [cite: 45]
    "Databases_Storage": [
        "postgresql", "mysql", "sql server", "oracle", 
        "mongodb", "redis", "elasticsearch", 
        "data warehouse", "snowflake", "bigquery", "redshift", 
        "lakehouse", "databricks", "delta lake" # [cite: 46]
    ],
    
    # F. Security skills [cite: 47]
    "Security_Tools": [
        "owasp", "burp suite", "metasploit", 
        "siem", "splunk", 
        "iam", "oauth2", "oidc", "sso", 
        "threat modeling", "vuln assessment", "pentest" # [cite: 48]
    ],
    
    # G. Methods [cite: 49]
    "Methodologies": [
        "agile", "scrum", "kanban", 
        "system design", "microservices", "clean architecture", 
        "oop", "design patterns", 
        "tdd", "bdd", 
        "rest api", "graphql", "grpc" # [cite: 50]
    ]
}

# Gộp tất cả skills thành 1 list để quét nhanh
ALL_SKILLS = list(set([skill for group in SKILL_KEYWORDS.values() for skill in group]))


# ==============================================================================
# 3. JOB BENEFITS (Quyền lợi) [cite: 51]
# ==============================================================================
BENEFITS_KEYWORDS = {
    # Work Style / Flexibility [cite: 52]
    "Work_Flexibility": [
        "remote work", "hybrid work", "work from home", "wfh",
        "flexible working hours", "flexible schedule",
        "compressed workweek", "no overtime", "limited overtime" # [cite: 53-59]
    ],
    
    # Compensation & Financial [cite: 60]
    "Compensation": [
        "competitive salary", "performance bonus", 
        "annual bonus", "year-end bonus",
        "project bonus", "stock options", 
        "salary review", "sign-on bonus", "referral bonus", 
        "overtime pay" # [cite: 61-69]
    ],
    
    # Health & Insurance [cite: 70]
    "Insurance_Health": [
        "health insurance", "private health insurance",
        "dental insurance", "vision insurance",
        "mental health support", "annual health check", "wellness program" # [cite: 71-77]
    ],
    
    # Learning & Career Growth [cite: 78]
    "Learning_Growth": [
        "training budget", "learning allowance", 
        "certification sponsorship",
        "paid courses", "udemy", "coursera", "pluralsight",
        "conference sponsorship",
        "career path", "career roadmap", 
        "mentorship program", "internal mobility" # [cite: 79-86]
    ],
    
    # Leave & Work–Life Balance [cite: 87]
    "Leave_TimeOff": [
        "paid time off", "pto", 
        "annual leave", "sick leave", "personal leave",
        "parental leave", "maternity leave", "paternity leave",
        "birthday leave", "mental health day" # [cite: 88-94]
    ],
    
    # Equipment & Work Setup [cite: 95]
    "Equipment_Environment": [
        "company laptop", "macbook provided",
        "work-from-home allowance", "ergonomic equipment",
        "software license provided" # [cite: 96-100]
    ],
    
    # Culture & Environment [cite: 101]
    "Culture": [
        "international working environment", "multicultural team",
        "english-speaking environment", "flat organization",
        "open culture", "innovation-driven culture" # [cite: 102-107]
    ],
    
    # Legal / Contract [cite: 108]
    "Legal_Contract": [
        "full-time contract", "probation salary 100%",
        "13th month salary", "social insurance", "tax support" # [cite: 109-113]
    ]
}

# Danh sách phẳng benefits
ALL_BENEFITS = list(set([benefit for group in BENEFITS_KEYWORDS.values() for benefit in group]))