from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Db.debug_llm_adapter import call_llm as call_gemini_llm
from Db.job_extraction_rules import load_job_extraction_prompt


DEFAULT_INPUT_PATH = BASE_DIR / "data" / "pending_llm" / "jobs_YYYY-MM-DD.pending.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "extracted"
DEFAULT_CONFIG_PATH = BASE_DIR / "2_clean_data" / "clean_config.yaml"
DEFAULT_FALLBACK_DIR = BASE_DIR / "data" / "fallback"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("process_pending_llm")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process pending jobs through Gemini and write extracted output.")
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to the pending_llm JSON file.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Path to the extracted JSON file. If omitted, it is derived from the input file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the extracted JSON file will be written.",
    )
    parser.add_argument(
        "--fallback-path",
        type=Path,
        default=None,
        help="Optional path where failed records will be written. Only created when failures exist.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to clean_config.yaml that contains prompt_extraction.",
    )
    return parser.parse_args()


def load_jobs(input_path: Path) -> List[Dict[str, Any]]:
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    raw_text = input_path.read_text(encoding="utf-8-sig").strip()
    if not raw_text:
        return []

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        jobs: List[Dict[str, Any]] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                jobs.append(item)
        return jobs

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("jobs", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]

    raise ValueError(f"Unsupported input format: {type(payload).__name__}")


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _load_api_keys(prefix: str = "GEMINI_API_KEY_") -> List[str]:
    key_entries: List[Tuple[int, str]] = []
    for env_name, env_value in os.environ.items():
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", env_name)
        if not match or not env_value:
            continue
        key_entries.append((int(match.group(1)), env_value))

    key_entries.sort(key=lambda item: item[0])
    return [value for _, value in key_entries]


def _build_prompt(job: Dict[str, Any], config_path: Path) -> str:
    prompt_template = load_job_extraction_prompt(config_path)
    requirements_text = _normalize_text(job.get("requirements_text"))
    return prompt_template.format(requirements_text=requirements_text)


def _is_api_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    api_markers = (
        "resourceexhausted",
        "quota",
        "429",
        "503",
        "service unavailable",
        "deadlineexceeded",
        "googleapierror",
        "api error",
        "connection",
        "timeout",
        "temporarily unavailable",
    )
    return any(marker in error_text for marker in api_markers)


def _is_parse_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    parse_markers = (
        "jsondecodeerror",
        "parse",
        "structured response is not an object",
        "empty gemini response",
        "model output is not a json object",
        "normalize",
    )
    return any(marker in error_text for marker in parse_markers)


def call_llm(job: Dict[str, Any], api_key: str, config_path: Path) -> Dict[str, Any]:
    prompt = _build_prompt(job, config_path)
    return call_gemini_llm(prompt, api_key)


def process_job(job: Dict[str, Any], api_key: str, config_path: Path) -> Dict[str, Any]:
    base_record = dict(job)
    base_record["status"] = "pending_llm"

    try:
        extracted = call_llm(job, api_key, config_path)
        if not isinstance(extracted, dict):
            raise ValueError(f"Structured output is not an object: {type(extracted).__name__}")

        # Allow LLM to provide `requirements_text` (do not block overwriting)

        base_record.update(extracted)
        # Extraction succeeded; do not compute fingerprint at this stage.
        base_record["status"] = "success"
        base_record.pop("error", None)
        return base_record
    except Exception as exc:  # noqa: BLE001
        err_text = str(exc) or ""
        # Determine failure reason with some granularity
        if _is_parse_error(exc) or "empty gemini response" in err_text.lower():
            failure_reason = "invalid_json_response"
            base_record["status"] = "invalid_json_response"
        elif _is_api_error(exc):
            failure_reason = "llm_api_fail"
            base_record["status"] = "llm_api_fail"
        else:
            failure_reason = "llm_api_fail"
            base_record["status"] = "llm_api_fail"

        base_record["error"] = err_text
        base_record["failure_reason"] = failure_reason

        # Do not compute fingerprint for failed records at extract stage.
        return base_record


def save_jobs(output_path: Path, jobs: List[Dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def derive_output_path(input_path: Path, output_dir: Path) -> Path:
    # If the caller passed an `extracted` directory (legacy), write the file
    # next to it as `extracted.json` instead of creating an `extracted/` folder.
    if output_dir.name == "extracted":
        return output_dir.parent / "extracted.json"
    return output_dir / "extracted.json"


def main() -> int:
    args = parse_args()
    logger = setup_logging()

    load_dotenv(BASE_DIR / ".env")

    input_path = args.input_path
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    output_path = args.output_path
    if output_path is None:
        output_path = derive_output_path(input_path, output_dir)
    elif not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    fallback_path = args.fallback_path
    if fallback_path is not None and not fallback_path.is_absolute():
        fallback_path = BASE_DIR / fallback_path
    if fallback_path is None:
        # produce a fallback filename based on the output filename stem
        fallback_name = output_path.stem + "_fallback.json"
        fallback_path = DEFAULT_FALLBACK_DIR / fallback_name

    jobs = load_jobs(input_path)
    total_jobs = len(jobs)
    logger.info("Loaded %s pending job(s) from %s", total_jobs, input_path)

    api_keys = _load_api_keys()
    if not api_keys:
        raise RuntimeError("No GEMINI_API_KEY_X keys found in environment.")

    passed_jobs: List[Dict[str, Any]] = []
    failed_jobs: List[Dict[str, Any]] = []
    success_count = 0
    api_fail_count = 0
    parse_fail_count = 0

    def _has_benefits(rec: Dict[str, Any]) -> bool:
        # accept non-empty list or non-empty string in common benefit keys
        benefit_keys = ("benefits", "extracted_benefits", "benefit_list", "benefits_list")
        for k in benefit_keys:
            v = rec.get(k)
            if isinstance(v, list) and len(v) > 0:
                return True
            if isinstance(v, str) and v.strip():
                return True
        return False

    def _has_requirements(rec: Dict[str, Any]) -> bool:
        for k in ("requirements_text", "requirements", "requirements_raw"):
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                return True
        return False

    def _has_posted_or_expiry(rec: Dict[str, Any]) -> bool:
        for k in ("posted_date", "expiry_date", "listed_time", "posted_at", "expires_at", "expiry_time"):
            if rec.get(k):
                return True
        return False

    def _count_skills(rec: Dict[str, Any]) -> int:
        skills = rec.get("extracted_skills") or []
        if isinstance(skills, list):
            return len(skills)
        return 0

    for index, job in enumerate(jobs):
        api_key = api_keys[index % len(api_keys)]
        try:
            processed = process_job(job, api_key, args.config_path)
        except Exception as exc:  # pragma: no cover - defensive guard
            processed = dict(job)
            processed["status"] = "api_fail"
            processed["error"] = str(exc)

        status = processed.get("status")

        # If the LLM/API already failed, send to fallback with mapped reason
        if status in {"invalid_json_response", "llm_api_fail", "api_fail", "parse_fail"}:
            # Normalize previous codes into the concise failure_reason field
            fr = processed.get("failure_reason") or (
                "invalid_json_response" if status == "invalid_json_response" else "llm_api_fail"
            )
            processed["failure_reason"] = fr
            failed_jobs.append(processed)
            if status == "invalid_json_response":
                parse_fail_count += 1
            else:
                api_fail_count += 1
            continue

        # At this point LLM extraction returned success; apply extract-pass gate
        # Conditions required to pass to normalize:
        # - extracted_skills exists and count >= 10
        # - benefits present
        # - requirements_text present
        # - at least one of posted_date or expiry_date present

        # Check skills
        skill_count = _count_skills(processed)
        if skill_count < 10:
            processed["status"] = "extract_fail"
            processed["failure_reason"] = "not_enough_skills"
            failed_jobs.append(processed)
            continue

        # Check benefits
        if not _has_benefits(processed):
            processed["status"] = "extract_fail"
            processed["failure_reason"] = "missing_benefits"
            failed_jobs.append(processed)
            continue

        # Check requirements_text
        if not _has_requirements(processed):
            processed["status"] = "extract_fail"
            processed["failure_reason"] = "missing_requirements_text"
            failed_jobs.append(processed)
            continue

        # Check posted/expiry date presence
        if not _has_posted_or_expiry(processed):
            processed["status"] = "extract_fail"
            processed["failure_reason"] = "missing_posted_and_expiry_date"
            failed_jobs.append(processed)
            continue

        # Passed all gates
        processed["status"] = "success"
        processed.pop("error", None)
        passed_jobs.append(processed)
        success_count += 1

    # Save only passing records to the main extracted output
    save_jobs(output_path, passed_jobs)

    # Save failures to fallback for debugging/retention
    if failed_jobs:
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        save_jobs(fallback_path, failed_jobs)

    logger.info("Total jobs: %s", total_jobs)
    logger.info("Extract-pass (to normalize): %s", success_count)
    logger.info("LLM/API parse failures: %s", parse_fail_count)
    logger.info("LLM/API other failures: %s", api_fail_count)
    logger.info("Wrote extracted (pass) jobs to: %s", output_path)
    if failed_jobs:
        logger.info("Wrote extract fallback jobs to: %s", fallback_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())