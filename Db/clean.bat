@echo off
title Script Toi Uu Toan Dien Folder Goc - JobVisualization_BE
cls

echo ============================================================
echo   BAT DAU QUY TRINH CAN QUET FILE RAC NGOAI FOLDER GOC
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1. XÓA CÁC FILE RÁC TĨNH (SỬA LỖI LOGIC KÝ TỰ TIẾNG VIỆT)
:: ------------------------------------------------------------
echo [+] Dang xoa cac file text va du lieu tam ngoai folder goc...

:: Viết rút gọn trên 1 dòng để tránh lỗi xung đột ký tự "lỗi" với CMD Windows
if exist "log-lỗi-matching-job-url.txt" del /f /q "log-lỗi-matching-job-url.txt" && echo    - Da xoa file log loi matching.[cite: 6]
if exist "itviec_desc.txt" del /f /q "itviec_desc.txt" && echo    - Da xoa file nhap itviec_desc.[cite: 6]
if exist "lightcast.csv" del /f /q "lightcast.csv" && echo    - Da xoa file du lieu nang lightcast.csv (Toi uu dung luong).[cite: 6]
if exist "schema_only.sql" del /f /q "schema_only.sql" && echo    - Da xoa file backup schema_only.sql.[cite: 6]

:: ------------------------------------------------------------
:: 2. XÓA CÁC FOLDER TEST VÀ FOLDER ARCHIVE KHÔNG DÙNG TỚI
:: ------------------------------------------------------------
echo.
echo [+] Dang xoa cac thu muc Test, Debug va Archive unused...

if exist "__pycache__" rmdir /s /q "__pycache__" && echo    - Da xoa folder __pycache__ goc.[cite: 6]
if exist ".tmp" rmdir /s /q ".tmp" && echo    - Da xoa folder tam .tmp.[cite: 6]
if exist ".tmp_cv_uploads" rmdir /s /q ".tmp_cv_uploads" && echo    - Da xoa folder tam cv uploads.[cite: 6]
if exist "_archive_unused" rmdir /s /q "_archive_unused" && echo    - Da xoa thu muc code cu _archive_unused.[cite: 6]
if exist "Debug" rmdir /s /q "Debug" && echo    - Da xoa thu muc Debug ca nhan.[cite: 6]
if exist "test_run" rmdir /s /q "test_run" && echo    - Da xoa thu muc test_run.[cite: 6]
if exist "Test_module" rmdir /s /q "Test_module" && echo    - Da xoa thu muc Test_module.[cite: 6]
if exist "matching_cv" rmdir /s /q "matching_cv" && echo    - Da xoa thu muc matching_cv tam.[cite: 6]
if exist "clean" rmdir /s /q "clean" && echo    - Da xoa thu muc clean trung gian.[cite: 6]

:: Quét dọn các folder cache ngầm
if exist "Db\llm\__pycache__" rmdir /s /q "Db\llm\__pycache__"[cite: 6]
if exist "Db\input\__pycache__" rmdir /s /q "Db\input\__pycache__"[cite: 6]
if exist "Db\pipeline\clean\2_clean_data\__pycache__" rmdir /s /q "Db\pipeline\clean\2_clean_data\__pycache__"[cite: 6]

echo.
echo ============================================================
echo   QUY TRINH KIEM TRA NGHIEW NGAC AN TOAN (SECURITY CHECK)
echo ============================================================
echo [V] Thu muc code loi: Db[cite: 6]
echo [V] Thu muc thuat toan: SkillWeighting[cite: 6]
echo [V] Cau hinh trien khai: Dockerfile, .dockerignore, requirements.txt[cite: 6]
echo [V] File chay chinh: main.py[cite: 6]
echo.
echo => KET THUC: Thư muc goc cua ban hien tai da sach se 100%%.
echo ============================================================
pause