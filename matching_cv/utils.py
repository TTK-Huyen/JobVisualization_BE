from __future__ import annotations

import os
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
        # Use OCR
        try:
            from PIL import Image
        except Exception:
            raise RuntimeError("Pillow is required for OCR. Install with: pip install pillow pytesseract")
        try:
            import pytesseract
        except Exception:
            raise RuntimeError("pytesseract is required for OCR. Install with: pip install pytesseract and install tesseract executable")

        # Convert pages to images: try pdf2image for PDFs
        images = []
        if p.suffix.lower() == ".pdf":
            try:
                from pdf2image import convert_from_path

                images = convert_from_path(str(p))
            except Exception:
                # Last resort: try to open as image
                try:
                    images = [Image.open(str(p))]
                except Exception:
                    raise RuntimeError("Cannot convert PDF to images for OCR. Install pdf2image and poppler, or provide an image file.")
        else:
            images = [Image.open(str(p))]

        ocr_texts = []
        for img in images:
            try:
                ocr_texts.append(pytesseract.image_to_string(img))
            except Exception as e:
                raise RuntimeError(f"pytesseract failed: {e}")
        text = "\n".join(ocr_texts).strip()

    return text or ""
