import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException

app = FastAPI(
    title="JobVisualization Algo API Wrapper",
    description="API Gateway bọc các module thuật toán, ETL, và Matching CV",
    version="1.0.0"
)

# Thư mục lưu tạm CV khi Web upload lên
UPLOAD_DIR = Path(".tmp_cv_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

if os.name == 'nt':  # Windows
    PYTHON_EXEC = str(Path(".venv/Scripts/python.exe").resolve())
else:  # Linux / MacOS / Docker
    PYTHON_EXEC = str(Path(".venv/bin/python").resolve())


def run_cli_command(command: list[str]) -> dict:
    """Helper chạy lệnh CLI hệ thống và bắt kết quả trả về"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=env
        )
        if result.returncode != 0:
            print("\n" + "="*50 + " SCRIPT CRASH LOG " + "="*50)
            print(f"STDERR FROM PYTHON:\n{result.stderr}")
            print("="*118 + "\n")
            
            return {"status": "error", "exit_code": result.returncode, "stderr": result.stderr}
        return {"status": "success", "stdout": result.stdout}
    except Exception as e:
        print(f"--- SUBPROCESS EXCEPTION: {str(e)} ---")
        return {"status": "error", "message": str(e)}


# =====================================================================
# MATCHING CV (REALTIME ENDPOINTS)
# =====================================================================

@app.post("/api/v1/matching/search-group")
async def match_by_search_group(
    search_group: str = Form(...),
    source_id: str = Form("0"),
    file: UploadFile = File(...)
):
    """Kiểu 1: Match CV dựa trên nhóm ngành tổng quan (Dữ liệu từ DB)"""
    temp_file_path = UPLOAD_DIR / file.filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        # python -m matching_cv.match_cv --cv <path> --search-group <group> --source-id <id>
        cmd = [
            PYTHON_EXEC, "-m", "matching_cv.match_cv",
            "--cv", str(temp_file_path),
            "--search-group", search_group,
            "--source-id", source_id
        ]
        
        res = run_cli_command(cmd)
        if res["status"] == "error":
            raise HTTPException(status_code=500, detail=res)
        return {"message": "Match thành công", "output": res["stdout"]}
        
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()


@app.post("/api/v1/matching/job-url")
async def match_by_job_url(
    url: str = Form(...),
    source_id: str = Form("0"),
    file: UploadFile = File(...)
):
    """Kiểu 2: Match CV trực tiếp với link URL tuyển dụng cụ thể"""
    temp_file_path = UPLOAD_DIR / file.filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        # python -m matching_cv.match_cv_with_url --cv <path> --url <url> --source-id <source_id>
        cmd = [
            PYTHON_EXEC, "-m", "matching_cv.match_cv_with_url",
            "--cv", str(temp_file_path),
            "--url", url,
            "--source-id", source_id
        ]
        res = run_cli_command(cmd)
        if res["status"] == "error":
            raise HTTPException(status_code=500, detail=res)
        return {"message": "Match URL thành công", "output": res["stdout"]}
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()


# =====================================================================
# ETL PIPELINE (BACKGROUND TASKS)
# =====================================================================

def background_etl_worker(step: str):
    """Worker chạy ngầm cho tác vụ ETL vì luồng này tốn rất nhiều thời gian"""
    # Di chuyển vào folder Db để chạy
    current_dir = os.getcwd()
    try:
        os.chdir("Db")
        if step == "all":
            cmd = [PYTHON_EXEC, "run_etl_pipeline.py"]
        else:
            cmd = [PYTHON_EXEC, "run_etl_pipeline.py", "--step", step]
        
        # Ghi log ra file hệ thống
        run_cli_command(cmd)
    finally:
        os.chdir(current_dir)


@app.post("/api/v1/pipeline/trigger")
def trigger_pipeline(background_tasks: BackgroundTasks, step: str = "all"):
    """
    Trigger chạy ETL Pipeline (Crawl / Clean / Import).
    """
    valid_steps = ["all", "crawl", "clean", "import"]
    if step not in valid_steps:
        raise HTTPException(status_code=400, detail=f"Step không hợp lệ. Phải thuộc {valid_steps}")
        
    background_tasks.add_task(background_etl_worker, step)
    return {"status": "accepted", "message": f"Pipeline step '{step}' đang chạy ngầm hệ thống."}


# =====================================================================
# WEIGHT UPDATE
# =====================================================================

@app.post("/api/v1/weights/update-tfidf")
def update_tfidf():
    """Cập nhật nhanh trọng số TF-IDF trực tiếp từ database"""
    cmd = [PYTHON_EXEC, "SkillWeighting/tf_idf.py"]
    res = run_cli_command(cmd)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res)
    return {"status": "success", "output": res["stdout"]}