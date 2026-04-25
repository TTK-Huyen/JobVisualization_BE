"""
CLEAN PIPELINE CONFIG
- Batch size
- Fingerprint structure
- Normalization rules
- Extraction rules
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# ============================================================================
# 🔧 BATCH SIZE CONFIG
# ============================================================================

# Jobs per batch for extraction
BATCH_SIZE_EXTRACT = int(os.getenv("CLEAN_BATCH_SIZE", "20"))

# Fingerprint cache batch check
BATCH_SIZE_FINGERPRINT_CHECK = int(os.getenv("CLEAN_BATCH_SIZE", "20"))


# ============================================================================
# 🔐 FINGERPRINT STRUCTURE
# ============================================================================

# Fingerprint formula: MD5(title|company_name|cleaned_text)
FINGERPRINT_STRUCTURE = {
    "fields": ["title", "company_name", "requirements_text"],  # requirements_text = cleaned_text
    "separator": "|",
    "algorithm": "md5",
    "description": "MD5 hash of: title|company_name|cleaned_requirements_text"
}

def build_fingerprint_input(job: dict) -> str:
    """Build fingerprint input string from job data."""
    title = job.get('title', '')
    company = job.get('company_name', '')
    cleaned_text = job.get('requirements_text', '')
    
    return f"{title}|{company}|{cleaned_text}"


# ============================================================================
# 📝 NORMALIZATION CONFIG
# ============================================================================

# Normalization rules (from step 3)
NORMALIZATION_CONFIG = {
    "skill_matching": {
        "method": "fuzzy",  # exact, fuzzy, semantic
        "threshold": 0.85,  # similarity threshold for fuzzy matching
        "use_embedding": False  # True = use sentence-transformers, False = fuzzy string match
    },
    "skill_translation": {
        "vietnamese_to_english": True,  # Translate VN skills to English
        "standardize_names": True,  # Standardize skill names (e.g., "c++" → "C++")
    },
    "benefit_mapping": {
        "standardize_benefits": True,
        "translate_benefits": True  # Translate VN benefits to English
    }
}


# ============================================================================
# 🤖 EXTRACTION CONFIG (LLM)
# ============================================================================

EXTRACTION_CONFIG = {
    "llm_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "temperature": 0.3,
    "max_output_tokens": 8000,
    "candidate_count": 1,
    
    # Cache settings
    "use_fingerprint_cache": True,  # Check cache before calling LLM
    "persistent_cache": True,  # Save cache to disk
    "cache_dir": Path(__file__).parent / "cache" / "skill_extraction_cache.json",
    
    # Batch extraction (not implemented yet)
    "batch_extraction": False,  # Multi-jobs per request (future)
    "batch_size": 5,  # Jobs per LLM request (future)
    
    # Rate limiting
    "rpm_limit": int(os.getenv("GEMINI_RPM", "4")),
    "rpd_limit": int(os.getenv("GEMINI_RPD", "20")),
    "tpm_limit": int(os.getenv("GEMINI_TPM", "250000")),
}


# ============================================================================
# 📊 STEP CONFIGURATION
# ============================================================================

STEP_1_CLEAN_HTML_CONFIG = {
    "name": "CLEAN_HTML",
    "description": "Remove HTML/CSS/JS from job descriptions",
    "enabled": True,
    "output_fields": ["requirements_text", "fingerprint"]
}

STEP_2_EXTRACT_CONFIG = {
    "name": "EXTRACT_SECTIONS_AND_SKILLS",
    "description": "Extract job sections + LLM skill extraction",
    "enabled": True,
    "use_cache": True,  # Check fingerprint cache first
    "sections_to_extract": [
        "requirements",
        "responsibilities", 
        "benefits",
        "qualifications",
        "nice_to_have"
    ],
    "output_fields": [
        "extracted_sections",
        "extracted_skills",
        "benefits",
        "is_it_job"
    ]
}

STEP_3_NORMALIZE_CONFIG = {
    "name": "NORMALIZE_SKILLS",
    "description": "Normalize skills + map to canonical skills",
    "enabled": True,
    "use_cache": True,
    "skill_normalization": {
        "fuzzy_matching": True,
        "threshold": 0.85
    },
    "output_fields": [
        "canonical_skills",
        "skill_categories",
        "is_it_job"
    ]
}


# ============================================================================
# 📋 CACHE CONFIG
# ============================================================================

CACHE_CONFIG = {
    "skill_extraction_cache": {
        "file": Path(__file__).parent / "cache" / "skill_extraction_fingerprint.json",
        "description": "Fingerprint → extracted skills mapping",
        "format": {
            "fingerprint_hash": {
                "is_it_job": bool,
                "extracted_skills": list,
                "benefits": list,
                "timestamp": str
            }
        }
    },
    
    "normalized_skill_cache": {
        "file": Path(__file__).parent / "cache" / "normalized_skill_canonical.json",
        "description": "Skill → canonical skill mapping",
        "format": {
            "skill_lower": {
                "canonical_name": str,
                "category": str,
                "confidence": float
            }
        }
    },
    
    "normalized_jobs_cache": {
        "file": Path(__file__).parent / "cache" / "normalized_jobs_fingerprint.json",
        "description": "Fingerprint → normalized job mapping",
        "format": {
            "fingerprint_hash": {
                "canonical_skills": list,
                "skill_categories": dict,
                "is_it_job": bool
            }
        }
    }
}


# ============================================================================
# 🎯 DISPLAY CONFIG
# ============================================================================

DISPLAY_CONFIG = {
    "verbose_mode": True,
    "show_stats": True,
    "show_cache_hits": True,
    "show_api_calls": True,
    "show_timing": True
}


# ============================================================================
# Exported config dict
# ============================================================================

CONFIG = {
    "batch_size": BATCH_SIZE_EXTRACT,
    "fingerprint": FINGERPRINT_STRUCTURE,
    "normalization": NORMALIZATION_CONFIG,
    "extraction": EXTRACTION_CONFIG,
    "step_1": STEP_1_CLEAN_HTML_CONFIG,
    "step_2": STEP_2_EXTRACT_CONFIG,
    "step_3": STEP_3_NORMALIZE_CONFIG,
    "cache": CACHE_CONFIG,
    "display": DISPLAY_CONFIG,
}

if __name__ == "__main__":
    import json
    print(json.dumps(CONFIG, indent=2, default=str))
