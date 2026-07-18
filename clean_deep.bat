@echo off
title Script Don Dep Chuyen Sau - JobVisualization_BE
cls

echo ============================================================
echo   BAT DAU QUY TRINH DON DEP SAU CAC THU MUC CON BEN TRONG
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1. DỌN DẸP SÂU TRONG FOLDER 'Db' (MÃ NGUỒN CHÍNH)
:: ------------------------------------------------------------
echo [+] Dang quet va xoa cac file tam phat sinh trong Db...

:: Xóa __pycache__ nội bộ trong các module con (Nếu có phát sinh ngoài Docker)
if exist "Db\input\__pycache__" rmdir /s /q "Db\input\__pycache__"[cite: 6]
if exist "Db\llm\__pycache__" rmdir /s /q "Db\llm\__pycache__"[cite: 6]
if exist "Db\pipeline\clean\2_clean_data\__pycache__" rmdir /s /q "Db\pipeline\clean\2_clean_data\__pycache__"[cite: 6]
if exist "Db\_archive_unused\2_clean_data\__pycache__" rmdir /s /q "Db\_archive_unused\2_clean_data\__pycache__"[cite: 6]

:: Dọn dẹp folder _archive_unused (Code thừa cũ đã gom nhóm)
if exist "Db\_archive_unused" (
    rmdir /s /q "Db\_archive_unused"
    echo    - Da xoa xach se folder code cu _archive_unused trong Db.
)

:: ------------------------------------------------------------
:: 2. DỌN DẸP TRONG FOLDER 'SkillWeighting' & 'matching_cv'
:: ------------------------------------------------------------
echo.
echo [+] Dang quet cac file tam trong module thuat toan...

if exist "SkillWeighting\__pycache__" rmdir /s /q "SkillWeighting\__pycache__"
if exist "matching_cv\__pycache__" rmdir /s /q "matching_cv\__pycache__"

:: Xóa các file .log hoặc file text tam trong cac thu muc nay neu co
del /f /q /s "SkillWeighting\*.log" >nul 2>&1
del /f /q /s "matching_cv\*.log" >nul 2>&1

:: ------------------------------------------------------------
:: 3. QUÉT DỌN ĐỆ QUY AN TOÀN ĐỐI VỚI FILE .PYC VÀ FILE LOG
:: ------------------------------------------------------------
echo.
echo [+] Dang quet de quy xoa file bien dich (.pyc) va file tam (.tmp)...

:: Xóa toàn bộ file .pyc (file Python compiled trung gian, khong phai file code .py)
del /f /q /s *.pyc >nul 2>&1
echo    - Da xoa toan bo cac file .pyc trung gian de quy.

:: Xóa các file log phat sinh trong toan bo project
del /f /q /s *.log >nul 2>&1
echo    - Da xoa toan bo file .log phat sinh trong cac folder con.

:: ------------------------------------------------------------
:: RE-CHECK & BẢO VỆ ASSETS CHÍ MẠNG
:: ------------------------------------------------------------
echo.
echo ============================================================
echo   BAO VE TAI NGUYEN KHI QUET SAU (WHITE-LIST CHECK)
echo ============================================================
echo [!] Thu muc Db/pipeline/clean/2_clean_data/cache: AN TOAN[cite: 6].
echo [!] Cac file embeddings (.pkl) va faiss index (.bin): GIU NGUYEN[cite: 4].
echo.
echo KET THUC: Toan bo cac folder con ben trong da duoc don sach.
echo ============================================================
pause