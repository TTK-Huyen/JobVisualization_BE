@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM CRAWL ALL DAILY - Gọi các daily runner từ từng source
REM ============================================================

set PYTHON=.\..\\.venv\Scripts\python.exe

REM Get today's date in format YYYYMMDD
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)

REM Set output directory to data/raw/crawl_YYYYMMDD
set OUTDIR=..\..\data\raw\crawl_%mydate%

mkdir "%OUTDIR%" 2>nul

echo [START] Crawl all daily sources to %OUTDIR%
echo.

REM ============================================================
REM STEP 1: ITviec
REM ============================================================
if exist "crawl_data\crawl-itviec-jobs\scripts\daily_itviec_runner.py" (
    echo [INFO] Running ITviec daily runner...
    set OUTPUT_FOLDER=%OUTDIR%
    "%PYTHON%" "crawl_data\crawl-itviec-jobs\scripts\daily_itviec_runner.py"
    if errorlevel 1 echo [WARNING] ITviec failed
) else (
    echo [WARNING] ITviec runner not found
)
timeout /t 2 /nobreak

REM ============================================================
REM STEP 2: LinkedIn
REM ============================================================
if exist "crawl_data\crawl-linkedin-jobs\scripts\daily_linkedin_runner.py" (
    echo [INFO] Running LinkedIn daily runner...
    set OUTPUT_FOLDER=%OUTDIR%
    "%PYTHON%" "crawl_data\crawl-linkedin-jobs\scripts\daily_linkedin_runner.py"
    if errorlevel 1 echo [WARNING] LinkedIn failed
) else (
    echo [WARNING] LinkedIn runner not found
)
timeout /t 2 /nobreak

REM ============================================================
REM STEP 3: CareerViet
REM ============================================================
if exist "crawl_data\crawl-careerviet-jobs\scripts\daily_careerviet_runner.py" (
    echo [INFO] Running CareerViet daily runner...
    set OUTPUT_FOLDER=%OUTDIR%
    "%PYTHON%" "crawl_data\crawl-careerviet-jobs\scripts\daily_careerviet_runner.py"
    if errorlevel 1 echo [WARNING] CareerViet failed
) else (
    echo [WARNING] CareerViet runner not found
)
timeout /t 2 /nobreak

REM ============================================================
REM STEP 4: VietnamWorks
REM ============================================================
if exist "crawl_data\crawl-vietnamwork-jobs\scripts\daily_vietnamworks_runner.py" (
    echo [INFO] Running VietnamWorks daily runner...
    "%PYTHON%" "crawl_data\crawl-vietnamwork-jobs\scripts\daily_vietnamworks_runner.py"
    if errorlevel 1 echo [WARNING] VietnamWorks failed
) else (
    echo [WARNING] VietnamWorks runner not found
)
timeout /t 2 /nobreak

REM ============================================================
REM STEP 5: Merge outputs
REM ============================================================
echo [INFO] Merging daily outputs...
"%PYTHON%" merge_daily_outputs.py

echo.
echo [END] Crawl all daily sources completed
echo ============================================================

