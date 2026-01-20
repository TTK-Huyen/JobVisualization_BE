-- ==========================================================
-- SEED DATA GENERATED FROM CONSTANTS.PY
-- Generated at: 2026-01-13 16:56:32.605705
-- ==========================================================

-- 1. Insert Industries (Dựa trên Keys của JOB_CATEGORIES)
INSERT INTO industries (industry_name) VALUES ('Software/Web/Mobile') ON CONFLICT (industry_name) DO NOTHING;
INSERT INTO industries (industry_name) VALUES ('Data/AI') ON CONFLICT (industry_name) DO NOTHING;
INSERT INTO industries (industry_name) VALUES ('DevOps/Infra') ON CONFLICT (industry_name) DO NOTHING;
INSERT INTO industries (industry_name) VALUES ('Security') ON CONFLICT (industry_name) DO NOTHING;
INSERT INTO industries (industry_name) VALUES ('Product/Design') ON CONFLICT (industry_name) DO NOTHING;

-- 2. Insert Skills (Dựa trên SKILL_KEYWORDS)
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('python', 'python', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('java', 'java', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('javascript', 'javascript', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('typescript', 'typescript', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('c-sharp', 'c#', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('ccpp', 'c/c++', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('go', 'go', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('php', 'php', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('kotlin', 'kotlin', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('swift', 'swift', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('ruby', 'ruby', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('rust', 'rust', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('scala', 'scala', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('r', 'r', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('dart', 'dart', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('sql', 'sql', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('html', 'html', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('css', 'css', 'Languages') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('react', 'react', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('nextjs', 'next.js', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('vue', 'vue', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('angular', 'angular', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('svelte', 'svelte', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('nodejs', 'node.js', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('express', 'express', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('nestjs', 'nestjs', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('spring-boot', 'spring boot', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('spring', 'spring', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('dot-net', '.net', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('aspdot-net', 'asp.net', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('django', 'django', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('flask', 'flask', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('fastapi', 'fastapi', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('laravel', 'laravel', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('flutter', 'flutter', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('react-native', 'react native', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('android-sdk', 'android sdk', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('swiftui', 'swiftui', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('uikit', 'uikit', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('junit', 'junit', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('pytest', 'pytest', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('jest', 'jest', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('cypress', 'cypress', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('playwright', 'playwright', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('selenium', 'selenium', 'Frameworks_Libs') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('pandas', 'pandas', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('numpy', 'numpy', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('scikit-learn', 'scikit-learn', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('pytorch', 'pytorch', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('tensorflow', 'tensorflow', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('keras', 'keras', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('spark', 'spark', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('hadoop', 'hadoop', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('kafka', 'kafka', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('airflow', 'airflow', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('dbt', 'dbt', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('mlflow', 'mlflow', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('kubeflow', 'kubeflow', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('llm', 'llm', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('prompt-engineering', 'prompt engineering', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('rag', 'rag', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('langchain', 'langchain', 'Data_AI') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('docker', 'docker', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('kubernetes', 'kubernetes', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('helm', 'helm', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('cicd', 'ci/cd', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('github-actions', 'github actions', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('gitlab-ci', 'gitlab ci', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('jenkins', 'jenkins', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('terraform', 'terraform', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('ansible', 'ansible', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('aws', 'aws', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('azure', 'azure', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('gcp', 'gcp', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('linux', 'linux', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('bash', 'bash', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('nginx', 'nginx', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('prometheus', 'prometheus', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('grafana', 'grafana', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('elk', 'elk', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('opentelemetry', 'opentelemetry', 'Cloud_DevOps') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('postgresql', 'postgresql', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('mysql', 'mysql', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('sql-server', 'sql server', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('oracle', 'oracle', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('mongodb', 'mongodb', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('redis', 'redis', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('elasticsearch', 'elasticsearch', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('snowflake', 'snowflake', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('bigquery', 'bigquery', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('redshift', 'redshift', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('databricks', 'databricks', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('delta-lake', 'delta lake', 'Database') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('owasp', 'owasp', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('burp-suite', 'burp suite', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('metasploit', 'metasploit', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('siem', 'siem', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('splunk', 'splunk', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('iam', 'iam', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('oauth2', 'oauth2', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('oidc', 'oidc', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('sso', 'sso', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('pentest', 'pentest', 'Security') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('agile', 'agile', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('scrum', 'scrum', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('kanban', 'kanban', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('microservices', 'microservices', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('clean-architecture', 'clean architecture', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('oop', 'oop', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('design-patterns', 'design patterns', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('tdd', 'tdd', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('bdd', 'bdd', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('rest-api', 'rest api', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('graphql', 'graphql', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
INSERT INTO skills (skill_abr, skill_name, category) VALUES ('grpc', 'grpc', 'Methods') ON CONFLICT (skill_abr) DO UPDATE SET category = EXCLUDED.category; -- Cập nhật category nếu có thay đổi
