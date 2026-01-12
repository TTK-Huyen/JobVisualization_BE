#!/usr/bin/env python3
"""Create database schema matching DatabaseStructure.md"""
import os
from dotenv import load_dotenv
import psycopg2


load_dotenv()

def get_conn():
    return psycopg2.connect(
        host=os.environ.get('PG_HOST','localhost'),
        port=int(os.environ.get('PG_PORT',5432)),
        dbname=os.environ.get('PG_DB','jobsdb'),
        user=os.environ.get('PG_USER','postgres'),
        password=os.environ.get('PG_PASSWORD','')
    )


def run():
    ddl = [
        # jobs
        '''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            company_id TEXT,
            title TEXT,
            description TEXT,
            max_salary NUMERIC,
            med_salary NUMERIC,
            min_salary NUMERIC,
            pay_period TEXT,
            formatted_work_type TEXT,
            location TEXT,
            applies INTEGER,
            original_listed_time TIMESTAMP,
            remote_allowed BOOLEAN,
            views INTEGER,
            job_posting_url TEXT,
            application_url TEXT,
            application_type TEXT,
            expiry TIMESTAMP,
            closed_time TIMESTAMP,
            formatted_experience_level TEXT,
            skills_desc TEXT,
            listed_time TIMESTAMP,
            posting_domain TEXT,
            sponsored BOOLEAN,
            work_type TEXT,
            currency TEXT,
            compensation_type TEXT,
            scraped BOOLEAN DEFAULT FALSE,
            inferred_benefits TEXT,
            years_experience TEXT,
            job_region TEXT,
            degree TEXT
        );
        ''',

        # salaries
        '''
        CREATE TABLE IF NOT EXISTS salaries (
            salary_id SERIAL PRIMARY KEY,
            job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
            max_salary NUMERIC,
            med_salary NUMERIC,
            min_salary NUMERIC,
            pay_period TEXT,
            currency TEXT,
            compensation_type TEXT
        );
        ''',

        # benefits
        '''
        CREATE TABLE IF NOT EXISTS benefits (
            id SERIAL PRIMARY KEY,
            job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
            type TEXT,
            inferred BOOLEAN DEFAULT FALSE
        );
        ''',

        # companies
        '''
        CREATE TABLE IF NOT EXISTS companies (
            company_id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            company_size TEXT,
            country TEXT,
            state TEXT,
            city TEXT,
            zip_code TEXT,
            address TEXT,
            url TEXT
        );
        ''',

        # employee_counts
        '''
        CREATE TABLE IF NOT EXISTS employee_counts (
            id SERIAL PRIMARY KEY,
            company_id TEXT REFERENCES companies(company_id) ON DELETE CASCADE,
            employee_count INTEGER,
            follower_count INTEGER,
            time_recorded TIMESTAMP
        );
        ''',

        # skills
        '''
        CREATE TABLE IF NOT EXISTS skills (
            skill_abr TEXT PRIMARY KEY,
            skill_name TEXT
        );
        ''',

        # job_skills
        '''
        CREATE TABLE IF NOT EXISTS job_skills (
            job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
            skill_abr TEXT REFERENCES skills(skill_abr),
            PRIMARY KEY (job_id, skill_abr)
        );
        ''',

        # industries
        '''
        CREATE TABLE IF NOT EXISTS industries (
            industry_id SERIAL PRIMARY KEY,
            industry_name TEXT
        );
        ''',

        # job_industries
        '''
        CREATE TABLE IF NOT EXISTS job_industries (
            job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
            industry_id INTEGER REFERENCES industries(industry_id),
            PRIMARY KEY (job_id, industry_id)
        );
        ''',

        # company_specialities
        '''
        CREATE TABLE IF NOT EXISTS company_specialities (
            company_id TEXT REFERENCES companies(company_id) ON DELETE CASCADE,
            speciality TEXT,
            PRIMARY KEY (company_id, speciality)
        );
        ''',

        # company_industries
        '''
        CREATE TABLE IF NOT EXISTS company_industries (
            company_id TEXT REFERENCES companies(company_id) ON DELETE CASCADE,
            industry INTEGER REFERENCES industries(industry_id),
            PRIMARY KEY (company_id, industry)
        );
        ''',
    ]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for s in ddl:
                cur.execute(s)
        conn.commit()
        print("✅ Schema created/ensured successfully.")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
