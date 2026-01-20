@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
REM Change to script directory so relative paths resolve correctly
cd /d "%~dp0"

REM Thư mục log & output (absolute based on script dir)
set BASE=%~dp0
set LOGDIR=%BASE%logs
set OUTDIR=%BASE%output

echo Creating directories...
mkdir "%LOGDIR%" 2>nul
mkdir "%OUTDIR%" 2>nul

if not exist "%LOGDIR%" (
	echo Error: Cannot create log directory: %LOGDIR%
	exit /b 1
)
if not exist "%OUTDIR%" (
	echo Error: Cannot create output directory: %OUTDIR%
	exit /b 1
)

for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')"') do set TIMESTAMP=%%i
set LOGFILE=%LOGDIR%\all_daily_%TIMESTAMP%.log
type nul > "%LOGFILE%"

echo LOGFILE=%LOGFILE%

echo ================================================== >> "%LOGFILE%"
echo [START] All daily crawl at %date% %time% >> "%LOGFILE%"

REM Python executable from venv (located in parent Db directory)
set PYTHON=%BASE%..\\.venv\Scripts\python.exe

if not exist "%PYTHON%" (
	echo [ERROR] Python venv not found at: %PYTHON% >> "%LOGFILE%"
	exit /b 1
)

REM ============================================
REM CHỈ CHẠY LINKEDIN - Các nguồn khác đã comment
REM ============================================
echo [INFO] Running LinkedIn scraper (multiple titles) >> %LOGFILE%
for %%A in ("Software Engineer|software_engineer","Backend Developer|backend_developer","Data Analyst|data_analyst","DevOps Engineer|devops_engineer","QA Engineer|qa_engineer") do (
	for /f "tokens=1,2 delims=|" %%T in ("%%~A") do (
		echo [INFO] LinkedIn: %%T >> "%LOGFILE%"
		"%PYTHON%" "%BASE%crawl_data\crawl-linkedin-jobs\scripts\scrape_linkedin.py" --title "%%T" --location "Vietnam" --out_prefix "%OUTDIR%\linkedin_%%U" >> "%LOGFILE%" 2>&1
		if errorlevel 1 (
			echo [ERROR] Failed to scrape LinkedIn for %%T >> "%LOGFILE%"
		)
	)
)

REM echo [INFO] Running CareerViet scraper (3 lists) >> %LOGFILE%
REM "%PYTHON%" "%BASE%crawl_data\crawl-careerviet-jobs\scripts\scrape_careerviet.py" --out-prefix "%OUTDIR%\careerviet_ai" --list-urls "https://careerviet.vn/viec-lam/ai-k-vi.html" >> "%LOGFILE%" 2>&1
REM "%PYTHON%" "%BASE%crawl_data\crawl-careerviet-jobs\scripts\scrape_careerviet.py" --out-prefix "%OUTDIR%\careerviet_backend" --list-urls "https://careerviet.vn/viec-lam/backend-k-vi.html" >> "%LOGFILE%" 2>&1
REM "%PYTHON%" "%BASE%crawl_data\crawl-careerviet-jobs\scripts\scrape_careerviet.py" --out-prefix "%OUTDIR%\careerviet_cntt" --list-urls "https://careerviet.vn/viec-lam/cntt-phan-mem-c1-vi.html" >> "%LOGFILE%" 2>&1

REM echo [INFO] Running VietnamWorks scraper (multiple queries) >> %LOGFILE%
REM "%PYTHON%" "%BASE%crawl_data\crawl-vietnamwork-jobs\scripts\scrape_vietnamwork.py" --list-urls "https://www.vietnamworks.com/viec-lam?q=python" --start-page 1 --end-page 1 --out-prefix "%OUTDIR%\vnw_python" >> "%LOGFILE%" 2>&1
REM "%PYTHON%" "%BASE%crawl_data\crawl-vietnamwork-jobs\scripts\scrape_vietnamwork.py" --list-urls "https://www.vietnamworks.com/viec-lam?q=java" --start-page 1 --end-page 1 --out-prefix "%OUTDIR%\vnw_java" >> "%LOGFILE%" 2>&1
REM "%PYTHON%" "%BASE%crawl_data\crawl-vietnamwork-jobs\scripts\scrape_vietnamwork.py" --list-urls "https://www.vietnamworks.com/viec-lam?q=devops" --start-page 1 --end-page 1 --out-prefix "%OUTDIR%\vnw_devops" >> "%LOGFILE%" 2>&1

REM echo [INFO] Running ITviec scraper (multiple combos) >> %LOGFILE%
REM pushd "%BASE%crawl_data\crawl-itviec-jobs\scripts"
REM for %%K in ("software engineer","python developer","data engineer") do (
REM 	for %%L in ("Ho Chi Minh","Ha Noi") do (
REM 		echo [INFO] ITviec: %%K | %%L >> "%LOGFILE%"
REM 		"%PYTHON%" scrape_itviec.py --keyword "%%K" --location "%%L" --out_prefix "%OUTDIR%\itviec_%%K_%%L" >> "%LOGFILE%" 2>&1
REM 	)
REM )
REM popd

echo [INFO] Merging daily outputs >> %LOGFILE%
"%PYTHON%" "%BASE%merge_daily_outputs.py" >> "%LOGFILE%" 2>&1

REM Tính toán ngày để xác định folder crawl_DD_MM_YY
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('dd_MM_yy')"') do set TODAY=%%i

echo [END] All daily crawl at %date% %time% >> %LOGFILE%
echo ================================================== >> %LOGFILE%
echo Done. Merged file: %OUTDIR%\crawl_%TODAY%\jobs_combined.json

REM Optional: dọn các file tạm (csv, xlsx) để chỉ giữ folder crawl_DD_MM_YY với 1 file json
for %%F in ("%OUTDIR%\linkedin_*.csv" "%OUTDIR%\linkedin_*.json" "%OUTDIR%\linkedin_*.xlsx" ^
						"%OUTDIR%\careerviet_*.csv" "%OUTDIR%\careerviet_*.json" "%OUTDIR%\careerviet_*.xlsx" ^
						"%OUTDIR%\vnw_*.csv" "%OUTDIR%\vnw_*.json" "%OUTDIR%\vnw_*.xlsx" ^
						"%OUTDIR%\itviec_*.csv" "%OUTDIR%\itviec_*.json" "%OUTDIR%\itviec_*.xlsx") do (
	if exist %%~F del /q %%~F
)

goto :EOF

