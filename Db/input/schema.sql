--
-- PostgreSQL database dump
--

\restrict QRAWAeGxwmuVIiLl0L8uIFqHs4uJc3JiEAzB52MezdU73Fga0Hkr8WS3t92FKer

-- Dumped from database version 17.7
-- Dumped by pg_dump version 17.7

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: benefits; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.benefits (
    benefit_id integer NOT NULL,
    benefit_name character varying(255) NOT NULL,
    category character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.benefits OWNER TO postgres;

--
-- Name: benefits_benefit_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.benefits_benefit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.benefits_benefit_id_seq OWNER TO postgres;

--
-- Name: benefits_benefit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.benefits_benefit_id_seq OWNED BY public.benefits.benefit_id;


--
-- Name: companies; Type: TABLE; Schema: public; Owner: postgres
--

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


ALTER TABLE public.companies OWNER TO postgres;

--
-- Name: company_industries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.company_industries (
    company_id bigint NOT NULL,
    industry_id integer NOT NULL
);


ALTER TABLE public.company_industries OWNER TO postgres;

--
-- Name: industries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.industries (
    industry_id integer NOT NULL,
    industry_name character varying(255) NOT NULL
);


ALTER TABLE public.industries OWNER TO postgres;

--
-- Name: industries_industry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.industries_industry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.industries_industry_id_seq OWNER TO postgres;

--
-- Name: industries_industry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.industries_industry_id_seq OWNED BY public.industries.industry_id;


--
-- Name: job_benefits; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.job_benefits (
    job_id bigint NOT NULL,
    benefit_id integer NOT NULL,
    is_inferred boolean DEFAULT false
);


ALTER TABLE public.job_benefits OWNER TO postgres;

--
-- Name: job_group_skill_weights; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.job_group_skill_weights (
    search_group character varying(100) NOT NULL,
    skill_id integer NOT NULL,
    weight_wi numeric(8,4) NOT NULL
);


ALTER TABLE public.job_group_skill_weights OWNER TO postgres;

--
-- Name: job_skills; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.job_skills (
    job_id bigint NOT NULL,
    skill_id integer NOT NULL,
    is_inferred boolean DEFAULT false
);


ALTER TABLE public.job_skills OWNER TO postgres;

--
-- Name: jobs_job_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.jobs_job_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.jobs_job_id_seq OWNER TO postgres;

--
-- Name: jobs; Type: TABLE; Schema: public; Owner: postgres
--

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


ALTER TABLE public.jobs OWNER TO postgres;

--
-- Name: salaries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.salaries (
    salary_id integer NOT NULL,
    job_id bigint,
    min_salary numeric(18,2),
    max_salary numeric(18,2),
    med_salary numeric(18,2),
    currency character varying(10) DEFAULT 'VND'::character varying,
    pay_period character varying(20)
);


ALTER TABLE public.salaries OWNER TO postgres;

--
-- Name: salaries_salary_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.salaries_salary_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.salaries_salary_id_seq OWNER TO postgres;

--
-- Name: salaries_salary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.salaries_salary_id_seq OWNED BY public.salaries.salary_id;


--
-- Name: skills; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.skills (
    skill_id integer NOT NULL,
    skill_name character varying(255) NOT NULL,
    category character varying(255),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    type character varying(100)
);


ALTER TABLE public.skills OWNER TO postgres;

--
-- Name: skills_skill_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.skills_skill_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.skills_skill_id_seq OWNER TO postgres;

--
-- Name: skills_skill_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.skills_skill_id_seq OWNED BY public.skills.skill_id;


--
-- Name: benefits benefit_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.benefits ALTER COLUMN benefit_id SET DEFAULT nextval('public.benefits_benefit_id_seq'::regclass);


--
-- Name: industries industry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.industries ALTER COLUMN industry_id SET DEFAULT nextval('public.industries_industry_id_seq'::regclass);


--
-- Name: salaries salary_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.salaries ALTER COLUMN salary_id SET DEFAULT nextval('public.salaries_salary_id_seq'::regclass);


--
-- Name: skills skill_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.skills ALTER COLUMN skill_id SET DEFAULT nextval('public.skills_skill_id_seq'::regclass);


--
-- Name: benefits benefits_benefit_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT benefits_benefit_name_key UNIQUE (benefit_name);


--
-- Name: benefits benefits_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT benefits_pkey PRIMARY KEY (benefit_id);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (company_id);


--
-- Name: company_industries company_industries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_pkey PRIMARY KEY (company_id, industry_id);


--
-- Name: industries industries_industry_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.industries
    ADD CONSTRAINT industries_industry_name_key UNIQUE (industry_name);


--
-- Name: industries industries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.industries
    ADD CONSTRAINT industries_pkey PRIMARY KEY (industry_id);


--
-- Name: job_benefits job_benefits_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_pkey PRIMARY KEY (job_id, benefit_id);


--
-- Name: job_group_skill_weights job_group_skill_weights_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_group_skill_weights
    ADD CONSTRAINT job_group_skill_weights_pkey PRIMARY KEY (search_group, skill_id);


--
-- Name: job_skills job_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_pkey PRIMARY KEY (job_id, skill_id);


--
-- Name: jobs jobs_fingerprint_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_fingerprint_key UNIQUE (fingerprint);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (job_id);


--
-- Name: salaries salaries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_pkey PRIMARY KEY (salary_id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (skill_id);


--
-- Name: benefits unique_benefit_name; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT unique_benefit_name UNIQUE (benefit_name);


--
-- Name: skills unique_skill_name; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT unique_skill_name UNIQUE (skill_name);


--
-- Name: idx_jobs_experience; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_jobs_experience ON public.jobs USING btree (formatted_experience_level);


--
-- Name: idx_jobs_skills_search; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_jobs_skills_search ON public.jobs USING gin (to_tsvector('english'::regconfig, skills_desc));


--
-- Name: idx_jobs_title; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_jobs_title ON public.jobs USING btree (title);


--
-- Name: company_industries company_industries_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE CASCADE;


--
-- Name: company_industries company_industries_industry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.company_industries
    ADD CONSTRAINT company_industries_industry_id_fkey FOREIGN KEY (industry_id) REFERENCES public.industries(industry_id) ON DELETE CASCADE;


--
-- Name: job_benefits job_benefits_benefit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_benefit_id_fkey FOREIGN KEY (benefit_id) REFERENCES public.benefits(benefit_id) ON DELETE CASCADE;


--
-- Name: job_benefits job_benefits_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;


--
-- Name: job_group_skill_weights job_group_skill_weights_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_group_skill_weights
    ADD CONSTRAINT job_group_skill_weights_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE;


--
-- Name: job_skills job_skills_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;


--
-- Name: job_skills job_skills_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(skill_id) ON DELETE CASCADE;


--
-- Name: jobs jobs_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(company_id) ON DELETE SET NULL;


--
-- Name: salaries salaries_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict QRAWAeGxwmuVIiLl0L8uIFqHs4uJc3JiEAzB52MezdU73Fga0Hkr8WS3t92FKer

