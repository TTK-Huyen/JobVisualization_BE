@echo off
set LINKEDIN_HOURS_OLD=72
set LINKEDIN_HEADLESS=false
set LINKEDIN_MAX_JOBS=2
\.venv\Scripts\python.exe run_etl_pipeline.py --crawl-only
