from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import yaml


def load_job_extraction_prompt(config_path) -> str:
    p = Path(config_path)
    if not p.exists():
        # try relative to 2_clean_data
        alt = Path(__file__).parent / "2_clean_data" / "clean_config.yaml"
        p = alt if alt.exists() else p
    try:
        cfg = yaml.safe_load(p.read_text(encoding='utf-8'))
        return cfg.get('prompt_extraction', '') if isinstance(cfg, dict) else ''
    except Exception:
        return ''


def build_job_extraction_generation_config_kwargs() -> Dict[str, Any]:
    # Minimal generation config suitable for genai.types.GenerationConfig(**kwargs)
    return {
        'max_output_tokens': 4096,
        'temperature': 0.0,
        'top_p': 0.95,
    }


def normalize_job_extraction_output(response_text: str, job_text: str | None = None) -> Dict[str, Any]:
    """Try to parse model response into a dict. If JSON parse fails, return
    a conservative structure the pipeline can work with.
    """
    if not response_text:
        return {'extracted_skills': [], 'benefits': [], 'job': {}, 'raw': {}, 'is_it_job': False}

    # Attempt direct JSON parse
    try:
        obj = json.loads(response_text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Try to extract first JSON object from text
    txt = response_text.strip()
    first = txt.find('{')
    last = txt.rfind('}')
    if first != -1 and last != -1 and last > first:
        try:
            candidate = txt[first:last+1]
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # Fallback: return minimal structure with raw text preserved
    return {
        'extracted_skills': [],
        'benefits': [],
        'job': {'skills_desc': {'value': job_text or None, 'confidence': 0}},
        'raw': {'requirements_text': job_text},
        'is_it_job': False,
    }
