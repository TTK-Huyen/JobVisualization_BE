@echo off
cd /d "f:\HCMUS_KH\LuanVan\JobVisualization_BE\Db"
call .venv\Scripts\activate.bat
python run_all_daily_batches.py --reset-keywords >> all_daily_batches.log 2>&1
