from __future__ import annotations

import os
import base64
from pathlib import Path
from typing import Optional


def find_db_env() -> Optional[Path]:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        candidate = Path(parent) / "Db" / ".env"
        if candidate.exists():
            return candidate
    return None


def load_db_env() -> bool:
    env = find_db_env()
    if not env:
        return False
    try:
        from dotenv import load_dotenv

        load_dotenv(env)
        return True
    except Exception:
        # attempt fallback using os.environ already set
        return False


def extract_cv_text(file_path: str, ocr_threshold: int = 200) -> str:
    """Extract text from CV file.

    Strategy:
    1. Try to extract text from PDF using pdfplumber or PyPDF2.
    2. If extracted text length is below `ocr_threshold`, fallback to OCR using pytesseract.

    Raises RuntimeError with clear instructions if required libs are missing.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"CV file not found: {file_path}")

    text = ""

    # Try pdf text extraction
    if p.suffix.lower() == ".pdf":
        try:
            try:
                import pdfplumber

                with pdfplumber.open(str(p)) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                    text = "\n".join(pages).strip()
            except Exception:
                # fallback to PyPDF2
                from PyPDF2 import PdfReader

                reader = PdfReader(str(p))
                pages = []
                for pg in reader.pages:
                    try:
                        pages.append(pg.extract_text() or "")
                    except Exception:
                        pages.append("")
                text = "\n".join(pages).strip()
        except Exception:
            text = ""

    # For non-pdf or pdf fallback, if text short then OCR
    if len(text) < ocr_threshold:
        text = _extract_text_pytesseract(p)

    return text or ""


def _extract_text_pytesseract(p: Path) -> str:
    """Fallback OCR using pytesseract (requires Tesseract binary installed)."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "Cannot extract text from image CV. Either:\n"
            "  1. Set GEMINI_API_KEY in environment, or\n"
            "  2. Install: pip install pytesseract pillow  (and install Tesseract binary)"
        )
    if p.suffix.lower() == ".pdf":
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(p))
        except Exception:
            images = [Image.open(str(p))]
    else:
        images = [Image.open(str(p))]

    parts = []
    for img in images:
        try:
            parts.append(pytesseract.image_to_string(img))
        except Exception as e:
            raise RuntimeError(f"pytesseract failed: {e}")
    return "\n".join(parts).strip()
