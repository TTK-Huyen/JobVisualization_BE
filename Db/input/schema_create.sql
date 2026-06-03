-- ============================================================================
-- PostgreSQL Database Creation Script (Clean Schema)
-- Generated from schema_only.sql
-- Contains only CREATE TABLE, ADD CONSTRAINT (PK, FK, UNIQUE), and CREATE INDEX
-- ============================================================================

-- BẬT ĐỊNH DẠNG SCHEMA (NẾU CẦN)
CREATE SCHEMA IF NOT EXISTS public;
SET search_path TO public;

-- ==========================================
-- 1. TẠO CÁC BẢNG (CREATE TABLE)
-- ==========================================

CREATE TABLE public.benefits (
    benefit_id integer NOT NULL,
    benefit_name character varying(255) NOT NULL,
    category character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.companies (
    company_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    company_size_min integer,
    company_size_max integer,
    country character varying(100),
    city character varying(100),
    address text,
    url character varying(500),
    industry character varying(255)
);

CREATE TABLE public.company_industries (
    company_id bigint NOT NULL,
    industry_id integer NOT NULL
);

CREATE TABLE public.cv_job_matches (
    match_type character varying(50) NOT NULL,
    search_group character varying(100),
    job_id bigint,
    match_score numeric(5,2),
    radar_data jsonb,
    gap_report jsonb,
    model_version character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    match_id uuid DEFAULT gen_random_uuid() NOT NULL,
    cv_id uuid,
    CONSTRAINT cv_job_matches_match_type_check CHECK (((match_type)::text = ANY ((ARRAY['search_group'::character varying, 'existing_job'::character varying, 'url_job'::character varying])::text[]))),
    CONSTRAINT cv_job_matches_score_check CHECK (((match_score IS NULL) OR ((match_score >= (0)::numeric) AND (match_score <= (100)::numeric)))),
    CONSTRAINT cv_job_matches_target_check CHECK (((((match_type)::text = 'search_group'::text) AND (search_group IS NOT NULL) AND (job_id IS NULL)) OR (((match_type)::text = ANY ((ARRAY['existing_job'::character varying, 'url_job'::character varying])::text[])) AND (job_id IS NOT NULL))))
);

CREATE TABLE public.industries (
    industry_id integer NOT NULL,
    industry_name character varying(255) NOT NULL
);

CREATE TABLE public.job_benefits (
    job_id bigint NOT NULL,
    benefit_id integer NOT NULL,
    is_inferred boolean DEFAULT false
);

CREATE TABLE public.job_group_skill_weights (
    search_group character varying(100) NOT NULL,
    skill_id integer NOT NULL,
    weight_wi numeric(8,4) NOT NULL
);

CREATE TABLE public.job_group_skill_weights_backup (
    search_group character varying(100),
    skill_id integer,
    weight_wi numeric(8,4)
);

CREATE TABLE public.job_skills (
    job_id bigint NOT NULL,
    skill_id integer NOT NULL,
    is_inferred boolean DEFAULT false,
    reason character varying(50),
    model_name character varying(100),
    similarity_score numeric(4,3),
    lib_version character varying(20),
    raw_skill_name character varying(255)
);

CREATE TABLE public.jobs (
    job_id bigint DEFAULT nextval('public.jobs_job_id_seq'::regclass) NOT NULL,
    company_id bigint,
    title character varying(500) NOT NULL,
    skills_desc text,
    description text,
    formatted_experience_level character varying(100),
    work_type character varying(100),
    location character varying(255),
    is_remote boolean DEFAULT false,
    listed_time timestamp with time zone,
    expiry_time timestamp with time zone,
    job_posting_url text,
    scraped_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    applies integer DEFAULT 0,
    views integer DEFAULT 0,
    fingerprint character varying(32),
    job_category character varying(100),
    search_group character varying(100),
    source_name character varying(50),
    source_id character varying(255)
);

CREATE TABLE public.notification_templates (
    template_id uuid DEFAULT gen_random_uuid() NOT NULL,
    template_code character varying(100) NOT NULL,
    channel character varying(30) DEFAULT 'in_app'::character varying NOT NULL,
    type character varying(50) DEFAULT 'system'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    title_template character varying(255) NOT NULL,
    message_template text NOT NULL,
    action_url_template text,
    metadata_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp(6) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(6) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.notifications (
    notification_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    type character varying(50) DEFAULT 'system'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    message text NOT NULL,
    action_url text,
    entity_type character varying(50),
    entity_id text,
    status character varying(20) DEFAULT 'unread'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    read_at timestamp(6) without time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp(6) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(6) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.salaries (
    salary_id integer NOT NULL,
    job_id bigint,
    min_salary numeric(18,2),
    max_salary numeric(18,2),
    med_salary numeric(18,2),
    currency character varying(10) DEFAULT 'VND'::character varying,
    pay_period character varying(20)
);

CREATE TABLE public.search_group_keywords (
    id integer NOT NULL,
    group_key character varying(255) NOT NULL,
    keyword character varying(255) NOT NULL
);

CREATE TABLE public.skills (
    skill_id integer NOT NULL,
    skill_name character varying(255) NOT NULL,
    category character varying(255),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    type character varying(100)
);

CREATE TABLE public.unmatched_skill_sources (
    source_id bigint NOT NULL,
    unmatched_id integer NOT NULL,
    source_type character varying(50) NOT NULL,
    occurrence_count integer DEFAULT 1,
    max_similarity_score numeric(4,3),
    first_seen timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    last_seen timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.unmatched_skills (
    unmatched_id integer NOT NULL,
    raw_skill_name character varying(255) NOT NULL,
    occurrence_count integer DEFAULT 1,
    max_similarity_score numeric(4,3),
    analysis_type character varying(50),
    first_seen timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    last_seen timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    top_candidate_skill_id integer,
    top_candidate_skill_name character varying(255)
);

CREATE TABLE public.user_auth_providers (
    provider character varying(50) NOT NULL,
    provider_user_id character varying(255) NOT NULL,
    provider_email character varying(255),
    provider_name character varying(255),
    provider_avatar_url text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    last_login_at timestamp without time zone,
    auth_provider_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    CONSTRAINT user_auth_provider_check CHECK (((provider)::text = ANY ((ARRAY['local'::character varying, 'google'::character varying, 'facebook'::character varying])::text[])))
);

CREATE TABLE public.user_cv_skills (
    skill_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    raw_skill character varying(255),
    cv_id uuid NOT NULL
);

CREATE TABLE public.user_cvs (
    file_name character varying(255),
    file_url text,
    extracted_text text,
    uploaded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    cv_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid
);

CREATE TABLE public.users (
    full_name character varying(255),
    email character varying(255),
    password_hash text,
    avatar_url text,
    role character varying(50) DEFAULT 'student'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    is_active boolean DEFAULT false NOT NULL,
    verify_token character varying(255),
    verify_token_expires timestamp without time zone,
    user_id uuid DEFAULT gen_random_uuid() NOT NULL,
    CONSTRAINT users_role_check CHECK (((role)::text = ANY ((ARRAY['student'::character varying, 'admin'::character varying])::text[])))
);

-- ==========================================
-- 2. TẠO CÁC CHỈ MỤC (CREATE INDEX)
-- ==========================================

CREATE INDEX idx_jobs_experience ON public.jobs USING btree (formatted_experience_level);

CREATE INDEX idx_jobs_skills_search ON public.jobs USING gin (to_tsvector('english'::regconfig, skills_desc));

CREATE INDEX idx_jobs_title ON public.jobs USING btree (title);

CREATE INDEX idx_unmatched_skills_analysis_type ON public.unmatched_skills USING btree (analysis_type);

CREATE INDEX idx_unmatched_skills_raw_name ON public.unmatched_skills USING btree (raw_skill_name);

CREATE INDEX idx_user_auth_providers_user_id ON public.user_auth_providers USING btree (user_id);

-- ==========================================
-- 3. RÀNG BUỘC KHÓA CHÍNH, KHÓA NGOẠI, UNIQUE (ALTER TABLE ADD CONSTRAINT)
-- ==========================================

-- Khóa chính và các ràng buộc Unique
ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT benefits_benefit_name_key UNIQUE (benefit_name);
ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT benefits_pkey PRIMARY KEY (benefit_id);
ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT unique_benefit_name UNIQUE (benefit_name);
ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (company_id);
ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_pkey PRIMARY KEY (company_id, industry_id);
ALTER TABLE ONLY public.cv_job_matches
    ADD CONSTRAINT cv_job_matches_pkey PRIMARY KEY (match_id);
ALTER TABLE ONLY public.industries
    ADD CONSTRAINT industries_industry_name_key UNIQUE (industry_name);
ALTER TABLE ONLY public.industries
    ADD CONSTRAINT industries_pkey PRIMARY KEY (industry_id);
ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_pkey PRIMARY KEY (job_id, benefit_id);
ALTER TABLE ONLY public.job_group_skill_weights
    ADD CONSTRAINT job_group_skill_weights_pkey PRIMARY KEY (search_group, skill_id);
ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_pkey PRIMARY KEY (job_id, skill_id);
ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_fingerprint_key UNIQUE (fingerprint);
ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (job_id);
ALTER TABLE ONLY public.notification_templates
    ADD CONSTRAINT notification_templates_pkey PRIMARY KEY (template_id);
ALTER TABLE ONLY public.notification_templates
    ADD CONSTRAINT notification_templates_template_code_key UNIQUE (template_code);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (notification_id);
ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_pkey PRIMARY KEY (salary_id);
ALTER TABLE ONLY public.search_group_keywords
    ADD CONSTRAINT search_group_keywords_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (skill_id);
ALTER TABLE ONLY public.skills
    ADD CONSTRAINT unique_skill_name UNIQUE (skill_name);
ALTER TABLE ONLY public.unmatched_skill_sources
    ADD CONSTRAINT unmatched_skill_sources_pkey PRIMARY KEY (source_id, unmatched_id, source_type);
ALTER TABLE ONLY public.unmatched_skills
    ADD CONSTRAINT unmatched_skills_pkey PRIMARY KEY (unmatched_id);
ALTER TABLE ONLY public.unmatched_skills
    ADD CONSTRAINT uq_unmatched_skills_raw_name UNIQUE (raw_skill_name);
ALTER TABLE ONLY public.user_auth_providers
    ADD CONSTRAINT user_auth_provider_unique UNIQUE (provider, provider_user_id);
ALTER TABLE ONLY public.user_auth_providers
    ADD CONSTRAINT user_auth_providers_pkey PRIMARY KEY (auth_provider_id);
ALTER TABLE ONLY public.user_cv_skills
    ADD CONSTRAINT user_cv_skills_pkey PRIMARY KEY (cv_id, skill_id);
ALTER TABLE ONLY public.user_cvs
    ADD CONSTRAINT user_cvs_pkey PRIMARY KEY (cv_id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);

-- Khóa ngoại liên kết giữa các bảng
ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_industry_id_fkey FOREIGN KEY (industry_id) REFERENCES public.industries(industry_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.cv_job_matches
    ADD CONSTRAINT cv_job_matches_cv_id_fkey FOREIGN KEY (cv_id) REFERENCES public.user_cvs(cv_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.cv_job_matches
    ADD CONSTRAINT cv_job_matches_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE SET NULL;
ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_benefit_id_fkey FOREIGN KEY (benefit_id) REFERENCES public.benefits(benefit_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.job_group_skill_weights
    ADD CONSTRAINT job_group_skill_weights_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE SET NULL;
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.unmatched_skill_sources
    ADD CONSTRAINT fk_unmatched_skill_sources_unmatched FOREIGN KEY (unmatched_id) REFERENCES public.unmatched_skills(unmatched_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.unmatched_skills
    ADD CONSTRAINT fk_unmatched_skills_candidate FOREIGN KEY (top_candidate_skill_id) REFERENCES public.skills(skill_id) ON DELETE SET NULL;
ALTER TABLE ONLY public.user_auth_providers
    ADD CONSTRAINT user_auth_providers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.user_cv_skills
    ADD CONSTRAINT user_cv_skills_cv_id_fkey FOREIGN KEY (cv_id) REFERENCES public.user_cvs(cv_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.user_cv_skills
    ADD CONSTRAINT user_cv_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.user_cvs
    ADD CONSTRAINT user_cvs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;
