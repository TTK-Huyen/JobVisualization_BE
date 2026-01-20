@echo off
REM ETL Pipeline Runner - Windows Batch Script
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ============================================================
echo       ETL PIPELINE - CRAWL ^| CLEAN ^| IMPORT
echo ============================================================
echo.

REM Get Python executable from venv
set PYTHON=.venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo Error: Python venv not found at: %PYTHON%
    echo Please run: python -m venv .venv
    pause
    exit /b 1
)

echo Running ETL Pipeline...
echo.

"%PYTHON%" run_etl_pipeline.py

if errorlevel 1 (
    echo.
    echo ============================================================
    echo ETL Pipeline FAILED! Check logs for details.
    echo ============================================================
    pause
    exit /b 1
) else (
    echo.
    echo ============================================================
    echo ETL Pipeline COMPLETED SUCCESSFULLY!
    echo ============================================================
    echo.
    echo Check logs:
    echo   - Db\etl_pipeline.log
    echo   - Db\1_crawl_data\logs
    echo   - Db\2_clean_data\output
    echo   - Database: Check your PostgreSQL
    echo.
    pause
)
