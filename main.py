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

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "Db"

UPLOAD_DIR = Path(".tmp_cv_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

if Path("/.dockerenv").exists() or os.getenv("IS_DOCKER"):
    PYTHON_EXEC = "python3"
elif os.name == 'nt':
    PYTHON_EXEC = str(Path(".venv/Scripts/python.exe").resolve())
else:
    PYTHON_EXEC = str(Path(".venv/bin/python").resolve())


def run_cli_command(command: list[str], working_dir: str = None) -> dict:
    if working_dir is None:
        working_dir = str(BASE_DIR)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=env,
            cwd=working_dir
        )
        if result.returncode != 0:
            print("\n" + "="*50 + " SCRIPT CRASH LOG " + "="*50)
            print(f"Mã thoát (Exit Code): {result.returncode}")
            print(f"Thư mục thực thi (CWD): {working_dir}")
            print(f"STDERR FROM PYTHON:\n{result.stderr if result.stderr.strip() else '[Trống rỗng]'}")
            print("="*118 + "\n")
            
            return {"status": "error", "exit_code": result.returncode, "stderr": result.stderr}
        return {"status": "success", "stdout": result.stdout}
    except Exception as e:
        print(f"--- SUBPROCESS EXCEPTION: {str(e)} ---")
        return {"status": "error", "message": str(e)}


@app.post("/api/v1/matching/search-group")
async def match_by_search_group(
    search_group: str = Form(...),
    source_id: str = Form("0"),
    cv_id: str = Form(...),
    score_jobs: str = Form("false"),
    file: UploadFile = File(...)
):
    temp_file_path = UPLOAD_DIR / file.filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        cmd = [
            PYTHON_EXEC, "-m", "matching_cv.match_cv",
            "--cv", str(temp_file_path.resolve()),
            "--search-group", search_group,
            "--source-id", source_id,
            "--cv-id", cv_id
        ]
        # Chấm điểm từng job trong nhóm (chỉ bật cho CV/nhóm mặc định).
        if str(score_jobs).lower() in ("true", "1", "yes"):
            cmd.append("--score-jobs")

        res = run_cli_command(cmd, working_dir=str(BASE_DIR))
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
    cv_id: str = Form(...),
    file: UploadFile = File(...)
):
    temp_file_path = UPLOAD_DIR / file.filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        cmd = [
            PYTHON_EXEC, "-m", "matching_cv.match_cv_with_url",
            "--cv", str(temp_file_path.resolve()),
            "--url", url,
            "--source-id", source_id,
            "--cv-id", cv_id
        ]
        res = run_cli_command(cmd, working_dir=str(BASE_DIR))
        if res["status"] == "error":
            raise HTTPException(status_code=500, detail=res)
        return {"message": "Match URL thành công", "output": res["stdout"]}
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()


def background_etl_worker(step: str):
    if step == "all":
        cmd = [PYTHON_EXEC, "run_etl_pipeline.py"]
    else:
        cmd = [PYTHON_EXEC, "run_etl_pipeline.py", "--step", step]
    
    log_path = DB_DIR / "api_etl_debug.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.run(
                cmd,
                stdout=log_file,
                stderr=log_file,
                cwd=str(DB_DIR),
                env=os.environ.copy()
            )
    except Exception as e:
        print(f"--- KHÔNG THỂ GHI FILE LOG: {log_path} | Lỗi: {str(e)} ---")


@app.post("/api/v1/pipeline/trigger")
def trigger_pipeline(background_tasks: BackgroundTasks, step: str = "all"):
    valid_steps = ["all", "crawl", "clean", "import"]
    if step not in valid_steps:
        raise HTTPException(status_code=400, detail=f"Step không hợp lệ. Phải thuộc {valid_steps}")
        
    background_tasks.add_task(background_etl_worker, step)
    return {"status": "accepted", "message": f"Pipeline step '{step}' đang chạy ngầm hệ thống."}


@app.post("/api/v1/weights/update-tfidf")
def update_tfidf():
    cmd = [PYTHON_EXEC, "SkillWeighting/tf_idf.py"]
    res = run_cli_command(cmd, working_dir=str(BASE_DIR))
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res)
    return {"status": "success", "output": res["stdout"]}