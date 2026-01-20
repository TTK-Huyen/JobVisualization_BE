# constants.py - Danh sách từ khóa chuẩn hóa

# 1. DANH SÁCH KỸ NĂNG (SKILLS) - Dùng để quét trong Tags và Mô tả
# Key: Tên nhóm (để tham khảo), Value: List từ khóa con
SKILL_KEYWORDS = {
    "Languages": [
        "python", "java", "javascript", "typescript", "c#", "c/c++", "go", "php", 
        "kotlin", "swift", "ruby", "rust", "scala", "r", "dart", "sql", "html", "css"
    ],
    "Frameworks_Libs": [
        "react", "next.js", "vue", "angular", "svelte", # FE
        "node.js", "express", "nestjs", "spring boot", "spring", ".net", "asp.net", "django", "flask", "fastapi", "laravel", # BE
        "flutter", "react native", "android sdk", "swiftui", "uikit", # Mobile
        "junit", "pytest", "jest", "cypress", "playwright", "selenium" # Testing
    ],
    "Data_AI": [
        "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow", "keras", 
        "spark", "hadoop", "kafka", "airflow", "dbt", "mlflow", "kubeflow", 
        "llm", "prompt engineering", "rag", "langchain"
    ],
    "Cloud_DevOps": [
        "docker", "kubernetes", "helm", "ci/cd", "github actions", "gitlab ci", "jenkins",
        "terraform", "ansible", "aws", "azure", "gcp", "linux", "bash", "nginx",
        "prometheus", "grafana", "elk", "opentelemetry"
    ],
    "Database": [
        "postgresql", "mysql", "sql server", "oracle", "mongodb", "redis", "elasticsearch",
        "snowflake", "bigquery", "redshift", "databricks", "delta lake"
    ],
    "Security": [
        "owasp", "burp suite", "metasploit", "siem", "splunk", "iam", "oauth2", "oidc", "sso", "pentest"
    ],
    "Methods": [
        "agile", "scrum", "kanban", "microservices", "clean architecture", "oop", "design patterns", "tdd", "bdd", "rest api", "graphql", "grpc"
    ]
}

# Gộp tất cả skill lại thành 1 list duy nhất để quét cho nhanh
ALL_SKILLS = [skill for group in SKILL_KEYWORDS.values() for skill in group]


# 2. DANH SÁCH PHÂN LOẠI JOB (TITLES)
# Dùng để đoán category dựa trên Title
JOB_CATEGORIES = {
    "Software/Web/Mobile": [
        "software engineer", "software developer", "programmer", "backend", "frontend", "full stack", 
        "web developer", "mobile developer", "android", "ios", "flutter", "react native", 
        "java developer", ".net developer", "python developer", "nodejs developer", "php developer", "golang",
        "qa engineer", "test engineer", "software tester", "automation tester", "sdet",
        "tech lead", "engineering lead", "architect"
    ],
    "Data/AI": [
        "data analyst", "business analyst", "data engineer", "analytics engineer", "bi developer",
        "data scientist", "applied scientist", "machine learning", "ai engineer", "mlops",
        "computer vision", "nlp engineer"
    ],
    "DevOps/Infra": [
        "devops", "sre", "site reliability", "cloud engineer", "cloud architect", 
        "platform engineer", "infrastructure", "system admin", "linux admin", "network engineer", "dba"
    ],
    "Security": [
        "cybersecurity", "security engineer", "soc analyst", "incident responder", 
        "penetration tester", "ethical hacker", "appsec", "iam engineer"
    ],
    "Product/Design": [
        "product manager", "product owner", "scrum master", "ux designer", "ui designer", "product designer"
    ]
}