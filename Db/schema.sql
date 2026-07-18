-- DROP SCHEMA public;

CREATE SCHEMA public AUTHORIZATION pg_database_owner;

-- DROP SEQUENCE public.benefits_benefit_id_seq;

CREATE SEQUENCE public.benefits_benefit_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.industries_industry_id_seq;

CREATE SEQUENCE public.industries_industry_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.jobs_job_id_seq;

CREATE SEQUENCE public.jobs_job_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.salaries_salary_id_seq;

CREATE SEQUENCE public.salaries_salary_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.search_group_keywords_id_seq;

CREATE SEQUENCE public.search_group_keywords_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.skills_skill_id_seq;

CREATE SEQUENCE public.skills_skill_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.unmatched_skills_unmatched_id_seq;

CREATE SEQUENCE public.unmatched_skills_unmatched_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;-- public.benefits definition

-- Drop table

-- DROP TABLE public.benefits;

CREATE TABLE public.benefits (
	benefit_id serial4 NOT NULL,
	benefit_name varchar(255) NOT NULL,
	category varchar(100) NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT benefits_pkey PRIMARY KEY (benefit_id)
);
CREATE UNIQUE INDEX benefits_benefit_name_key ON public.benefits USING btree (benefit_name);


-- public.companies definition

-- Drop table

-- DROP TABLE public.companies;

CREATE TABLE public.companies (
	company_id int8 NOT NULL,
	"name" varchar(255) NOT NULL,
	description text NULL,
	company_size_min int4 NULL,
	company_size_max int4 NULL,
	country varchar(100) NULL,
	city varchar(100) NULL,
	address text NULL,
	url varchar(500) NULL,
	industry varchar(255) NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT companies_pkey PRIMARY KEY (company_id)
);


-- public.courses definition

-- Drop table

-- DROP TABLE public.courses;

CREATE TABLE public.courses (
	course_id uuid NOT NULL,
	course_title varchar(500) NOT NULL,
	provider_name varchar(100) NOT NULL,
	source_url text NULL,
	thumbnail_icon varchar(50) NULL,
	duration_hours int4 NOT NULL,
	rating numeric(3, 2) DEFAULT 4.5 NOT NULL,
	total_learners varchar(50) NOT NULL,
	price numeric(10, 2) DEFAULT 0.00 NOT NULL,
	currency varchar(10) DEFAULT 'USD'::character varying NOT NULL,
	skills_tags _text NULL,
	is_recommended bool DEFAULT false NOT NULL,
	CONSTRAINT courses_pkey PRIMARY KEY (course_id)
);


-- public.industries definition

-- Drop table

-- DROP TABLE public.industries;

CREATE TABLE public.industries (
	industry_id serial4 NOT NULL,
	industry_name varchar(255) NOT NULL,
	CONSTRAINT industries_pkey PRIMARY KEY (industry_id)
);
CREATE UNIQUE INDEX industries_industry_name_key ON public.industries USING btree (industry_name);


-- public.learning_paths definition

-- Drop table

-- DROP TABLE public.learning_paths;

CREATE TABLE public.learning_paths (
	path_id uuid NOT NULL,
	path_title varchar(255) NOT NULL,
	path_description text NOT NULL,
	path_level varchar(50) DEFAULT 'Intermediate'::character varying NOT NULL,
	path_icon varchar(50) DEFAULT 'rocket'::character varying NOT NULL,
	estimated_duration_months varchar(50) DEFAULT '2 months'::character varying NOT NULL,
	skill_key varchar(255) NOT NULL,
	CONSTRAINT learning_paths_pkey PRIMARY KEY (path_id)
);


-- public.notification_templates definition

-- Drop table

-- DROP TABLE public.notification_templates;

CREATE TABLE public.notification_templates (
	template_id uuid NOT NULL,
	template_code varchar(100) NOT NULL,
	channel varchar(30) DEFAULT 'in_app'::character varying NOT NULL,
	"type" varchar(50) DEFAULT 'system'::character varying NOT NULL,
	priority varchar(20) DEFAULT 'normal'::character varying NOT NULL,
	title_template varchar(255) NOT NULL,
	message_template text NOT NULL,
	action_url_template text NULL,
	metadata_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
	is_active bool DEFAULT true NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT notification_templates_pkey PRIMARY KEY (template_id)
);
CREATE INDEX idx_notification_templates_active ON public.notification_templates USING btree (is_active);
CREATE UNIQUE INDEX notification_templates_template_code_key ON public.notification_templates USING btree (template_code);


-- public.search_group_keywords definition

-- Drop table

-- DROP TABLE public.search_group_keywords;

CREATE TABLE public.search_group_keywords (
	id serial4 NOT NULL,
	group_key varchar(255) NOT NULL,
	keyword varchar(255) NOT NULL,
	CONSTRAINT search_group_keywords_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_search_group_keywords_keyword ON public.search_group_keywords USING btree (keyword);
CREATE UNIQUE INDEX search_group_keywords_keyword_key ON public.search_group_keywords USING btree (keyword);


-- public.skills definition

-- Drop table

-- DROP TABLE public.skills;

CREATE TABLE public.skills (
	skill_id serial4 NOT NULL,
	skill_name varchar(255) NOT NULL,
	category varchar(255) NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	"type" varchar(100) NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT skills_pkey PRIMARY KEY (skill_id)
);
CREATE UNIQUE INDEX skills_skill_name_key ON public.skills USING btree (skill_name);


-- public.company_industries definition

-- Drop table

-- DROP TABLE public.company_industries;

CREATE TABLE public.company_industries (
	company_id int8 NOT NULL,
	industry_id int4 NOT NULL,
	CONSTRAINT company_industries_pkey PRIMARY KEY (company_id, industry_id),
	CONSTRAINT company_industries_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT company_industries_industry_id_fkey FOREIGN KEY (industry_id) REFERENCES public.industries(industry_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.job_group_skill_weights definition

-- Drop table

-- DROP TABLE public.job_group_skill_weights;

CREATE TABLE public.job_group_skill_weights (
	search_group varchar(100) NOT NULL,
	skill_id int4 NOT NULL,
	weight_wi numeric(8, 4) NOT NULL,
	CONSTRAINT job_group_skill_weights_pkey PRIMARY KEY (search_group, skill_id),
	CONSTRAINT job_group_skill_weights_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.jobs definition

-- Drop table

-- DROP TABLE public.jobs;

CREATE TABLE public.jobs (
	job_id bigserial NOT NULL,
	company_id int8 NULL,
	title varchar(500) NOT NULL,
	skills_desc text NULL,
	description text NULL,
	formatted_experience_level text NULL,
	work_type text NULL,
	"location" varchar(255) NULL,
	is_remote bool DEFAULT false NULL,
	listed_time timestamptz(6) NULL,
	expiry_time timestamptz(6) NULL,
	job_posting_url text NULL,
	scraped_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	applies int4 DEFAULT 0 NULL,
	"views" int4 DEFAULT 0 NULL,
	fingerprint varchar(32) NULL,
	job_category text NULL,
	search_group text NULL,
	source_name varchar(50) NULL,
	source_id varchar(255) NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT jobs_pkey PRIMARY KEY (job_id),
	CONSTRAINT jobs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE INDEX idx_jobs_company_id ON public.jobs USING btree (company_id);
CREATE INDEX idx_jobs_experience ON public.jobs USING btree (formatted_experience_level);
CREATE INDEX idx_jobs_expiry_time ON public.jobs USING btree (expiry_time);
CREATE INDEX idx_jobs_job_category ON public.jobs USING btree (job_category);
CREATE INDEX idx_jobs_listed_time ON public.jobs USING btree (listed_time);
CREATE INDEX idx_jobs_search_group ON public.jobs USING btree (search_group);
CREATE INDEX idx_jobs_source_name ON public.jobs USING btree (source_name);
CREATE INDEX idx_jobs_title ON public.jobs USING btree (title);
CREATE UNIQUE INDEX jobs_fingerprint_key ON public.jobs USING btree (fingerprint);


-- public.path_courses definition

-- Drop table

-- DROP TABLE public.path_courses;

CREATE TABLE public.path_courses (
	path_id uuid NOT NULL,
	course_id uuid NOT NULL,
	sort_order int4 DEFAULT 0 NOT NULL,
	CONSTRAINT path_courses_pkey PRIMARY KEY (path_id, course_id),
	CONSTRAINT path_courses_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.courses(course_id) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT path_courses_path_id_fkey FOREIGN KEY (path_id) REFERENCES public.learning_paths(path_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.salaries definition

-- Drop table

-- DROP TABLE public.salaries;

CREATE TABLE public.salaries (
	salary_id serial4 NOT NULL,
	job_id int8 NULL,
	min_salary numeric(18, 2) NULL,
	max_salary numeric(18, 2) NULL,
	med_salary numeric(18, 2) NULL,
	currency varchar(10) DEFAULT 'VND'::character varying NULL,
	pay_period varchar(20) NULL,
	CONSTRAINT salaries_pkey PRIMARY KEY (salary_id),
	CONSTRAINT salaries_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX idx_salaries_job_id ON public.salaries USING btree (job_id);


-- public.unmatched_skills definition

-- Drop table

-- DROP TABLE public.unmatched_skills;

CREATE TABLE public.unmatched_skills (
	unmatched_id serial4 NOT NULL,
	raw_skill_name varchar(255) NOT NULL,
	occurrence_count int4 DEFAULT 1 NULL,
	max_similarity_score numeric(4, 3) NULL,
	analysis_type varchar(50) NULL,
	first_seen timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	last_seen timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	top_candidate_skill_id int4 NULL,
	top_candidate_skill_name varchar(255) NULL,
	CONSTRAINT unmatched_skills_pkey PRIMARY KEY (unmatched_id),
	CONSTRAINT unmatched_skills_top_candidate_skill_id_fkey FOREIGN KEY (top_candidate_skill_id) REFERENCES public.skills(skill_id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE INDEX idx_unmatched_skills_analysis_type ON public.unmatched_skills USING btree (analysis_type);
CREATE INDEX idx_unmatched_skills_raw_name ON public.unmatched_skills USING btree (raw_skill_name);
CREATE UNIQUE INDEX unmatched_skills_raw_skill_name_key ON public.unmatched_skills USING btree (raw_skill_name);


-- public.job_benefits definition

-- Drop table

-- DROP TABLE public.job_benefits;

CREATE TABLE public.job_benefits (
	job_id int8 NOT NULL,
	benefit_id int4 NOT NULL,
	is_inferred bool DEFAULT false NULL,
	CONSTRAINT job_benefits_pkey PRIMARY KEY (job_id, benefit_id),
	CONSTRAINT job_benefits_benefit_id_fkey FOREIGN KEY (benefit_id) REFERENCES public.benefits(benefit_id) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.job_skills definition

-- Drop table

-- DROP TABLE public.job_skills;

CREATE TABLE public.job_skills (
	job_id int8 NOT NULL,
	skill_id int4 NOT NULL,
	is_inferred bool DEFAULT false NULL,
	reason varchar(50) NULL,
	model_name varchar(100) NULL,
	similarity_score numeric(4, 3) NULL,
	lib_version varchar(20) NULL,
	raw_skill_name varchar(255) NULL,
	CONSTRAINT job_skills_pkey PRIMARY KEY (job_id, skill_id),
	CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT job_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.unmatched_skill_sources definition

-- Drop table

-- DROP TABLE public.unmatched_skill_sources;

CREATE TABLE public.unmatched_skill_sources (
	source_id int8 NOT NULL,
	unmatched_id int4 NOT NULL,
	source_type varchar(50) NOT NULL,
	occurrence_count int4 DEFAULT 1 NULL,
	max_similarity_score numeric(4, 3) NULL,
	first_seen timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	last_seen timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT unmatched_skill_sources_pkey PRIMARY KEY (source_id, unmatched_id, source_type),
	CONSTRAINT unmatched_skill_sources_unmatched_id_fkey FOREIGN KEY (unmatched_id) REFERENCES public.unmatched_skills(unmatched_id) ON DELETE CASCADE ON UPDATE CASCADE
);


-- public.cv_job_matches definition

-- Drop table

-- DROP TABLE public.cv_job_matches;

CREATE TABLE public.cv_job_matches (
	match_id uuid NOT NULL,
	cv_id uuid NOT NULL,
	match_type varchar(50) NOT NULL,
	search_group varchar(100) NULL,
	job_id int8 NULL,
	match_score numeric(5, 2) NULL,
	radar_data jsonb NULL,
	gap_report jsonb NULL,
	model_version varchar(100) NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT cv_job_matches_pkey PRIMARY KEY (match_id)
);
CREATE INDEX idx_cv_job_matches_created_at ON public.cv_job_matches USING btree (created_at);
CREATE INDEX idx_cv_job_matches_cv_id ON public.cv_job_matches USING btree (cv_id);
CREATE INDEX idx_cv_job_matches_job_id ON public.cv_job_matches USING btree (job_id);
CREATE INDEX idx_cv_job_matches_match_type ON public.cv_job_matches USING btree (match_type);
CREATE INDEX idx_cv_job_matches_search_group ON public.cv_job_matches USING btree (search_group);


-- public.notifications definition

-- Drop table

-- DROP TABLE public.notifications;

CREATE TABLE public.notifications (
	notification_id uuid NOT NULL,
	user_id uuid NOT NULL,
	"type" varchar(50) DEFAULT 'system'::character varying NOT NULL,
	title varchar(255) NOT NULL,
	message text NOT NULL,
	action_url text NULL,
	entity_type varchar(50) NULL,
	entity_id text NULL,
	status varchar(20) DEFAULT 'unread'::character varying NOT NULL,
	priority varchar(20) DEFAULT 'normal'::character varying NOT NULL,
	is_read bool DEFAULT false NOT NULL,
	read_at timestamp(6) NULL,
	metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT notifications_pkey PRIMARY KEY (notification_id)
);
CREATE INDEX idx_notifications_entity ON public.notifications USING btree (entity_type, entity_id);
CREATE INDEX idx_notifications_user_created_at ON public.notifications USING btree (user_id, created_at DESC);
CREATE INDEX idx_notifications_user_is_read ON public.notifications USING btree (user_id, is_read);
CREATE INDEX idx_notifications_user_status ON public.notifications USING btree (user_id, status);


-- public.saved_courses definition

-- Drop table

-- DROP TABLE public.saved_courses;

CREATE TABLE public.saved_courses (
	user_id uuid NOT NULL,
	course_id uuid NOT NULL,
	status text DEFAULT 'saved'::text NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT saved_courses_pkey PRIMARY KEY (user_id, course_id)
);


-- public.saved_jobs definition

-- Drop table

-- DROP TABLE public.saved_jobs;

CREATE TABLE public.saved_jobs (
	saved_job_id uuid NOT NULL,
	user_id uuid NOT NULL,
	job_id int8 NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT saved_jobs_pkey PRIMARY KEY (saved_job_id)
);
CREATE INDEX idx_saved_jobs_user_id ON public.saved_jobs USING btree (user_id);
CREATE UNIQUE INDEX saved_jobs_user_id_job_id_key ON public.saved_jobs USING btree (user_id, job_id);


-- public.user_auth_providers definition

-- Drop table

-- DROP TABLE public.user_auth_providers;

CREATE TABLE public.user_auth_providers (
	auth_provider_id uuid NOT NULL,
	user_id uuid NOT NULL,
	provider varchar(50) NOT NULL,
	provider_user_id varchar(255) NOT NULL,
	provider_email varchar(255) NULL,
	provider_name varchar(255) NULL,
	provider_avatar_url text NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	last_login_at timestamp(6) NULL,
	CONSTRAINT user_auth_providers_pkey PRIMARY KEY (auth_provider_id)
);
CREATE INDEX idx_user_auth_providers_user_id ON public.user_auth_providers USING btree (user_id);
CREATE UNIQUE INDEX user_auth_providers_provider_provider_user_id_key ON public.user_auth_providers USING btree (provider, provider_user_id);


-- public.user_cv_skills definition

-- Drop table

-- DROP TABLE public.user_cv_skills;

CREATE TABLE public.user_cv_skills (
	cv_id uuid NOT NULL,
	skill_id int4 NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	raw_skill varchar(255) NULL,
	CONSTRAINT user_cv_skills_pkey PRIMARY KEY (cv_id, skill_id)
);
CREATE INDEX idx_user_cv_skills_skill_id ON public.user_cv_skills USING btree (skill_id);


-- public.user_cvs definition

-- Drop table

-- DROP TABLE public.user_cvs;

CREATE TABLE public.user_cvs (
	cv_id uuid NOT NULL,
	user_id uuid NOT NULL,
	file_name varchar(255) NULL,
	file_url text NULL,
	extracted_text text NULL,
	uploaded_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT user_cvs_pkey PRIMARY KEY (cv_id)
);
CREATE INDEX idx_user_cvs_user_id ON public.user_cvs USING btree (user_id);


-- public.users definition

-- Drop table

-- DROP TABLE public.users;

CREATE TABLE public.users (
	user_id uuid NOT NULL,
	full_name varchar(255) NULL,
	email varchar(255) NULL,
	password_hash text NULL,
	avatar_url text NULL,
	"role" varchar(50) DEFAULT 'student'::character varying NOT NULL,
	created_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp(6) DEFAULT CURRENT_TIMESTAMP NULL,
	is_active bool DEFAULT false NOT NULL,
	verify_token varchar(255) NULL,
	verify_token_expires timestamp(6) NULL,
	school varchar(255) NULL,
	major varchar(255) NULL,
	current_year int4 NULL,
	orientation varchar(255) NULL,
	objective varchar(255) NULL,
	target_salary int4 NULL,
	prefer_remote bool NULL,
	current_step int4 DEFAULT 1 NOT NULL,
	onboarding_completed bool DEFAULT false NOT NULL,
	default_cv_id uuid NULL,
	default_match_id uuid NULL,
	allow_default_cv_matching bool DEFAULT false NOT NULL,
	CONSTRAINT users_pkey PRIMARY KEY (user_id)
);
CREATE UNIQUE INDEX users_default_cv_id_key ON public.users USING btree (default_cv_id);
CREATE UNIQUE INDEX users_default_match_id_key ON public.users USING btree (default_match_id);
CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email);


-- public.cv_job_matches foreign keys

ALTER TABLE public.cv_job_matches ADD CONSTRAINT cv_job_matches_cv_id_fkey FOREIGN KEY (cv_id) REFERENCES public.user_cvs(cv_id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE public.cv_job_matches ADD CONSTRAINT cv_job_matches_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE SET NULL ON UPDATE CASCADE;


-- public.notifications foreign keys

ALTER TABLE public.notifications ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.saved_courses foreign keys

ALTER TABLE public.saved_courses ADD CONSTRAINT saved_courses_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.courses(course_id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE public.saved_courses ADD CONSTRAINT saved_courses_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.saved_jobs foreign keys

ALTER TABLE public.saved_jobs ADD CONSTRAINT saved_jobs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE public.saved_jobs ADD CONSTRAINT saved_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.user_auth_providers foreign keys

ALTER TABLE public.user_auth_providers ADD CONSTRAINT user_auth_providers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.user_cv_skills foreign keys

ALTER TABLE public.user_cv_skills ADD CONSTRAINT user_cv_skills_cv_id_fkey FOREIGN KEY (cv_id) REFERENCES public.user_cvs(cv_id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE public.user_cv_skills ADD CONSTRAINT user_cv_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.user_cvs foreign keys

ALTER TABLE public.user_cvs ADD CONSTRAINT user_cvs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;


-- public.users foreign keys

ALTER TABLE public.users ADD CONSTRAINT users_default_cv_id_fkey FOREIGN KEY (default_cv_id) REFERENCES public.user_cvs(cv_id) ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE public.users ADD CONSTRAINT users_default_match_id_fkey FOREIGN KEY (default_match_id) REFERENCES public.cv_job_matches(match_id) ON DELETE SET NULL ON UPDATE CASCADE;