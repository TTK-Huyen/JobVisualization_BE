"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                          UTILITIES MODULE                                     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║ PURPOSE:                                                                      ║
║   Các hàm helper cho text processing và debugging:                           ║
║   - Clean HTML/CSS/JavaScript từ job descriptions                            ║
║   - Extract sections (requirements, benefits, salary, etc.)                  ║
║   - Logging errors to JSON                                                   ║
║   - Slug conversion cho URLs                                                 ║
║   - Display functions cho debugging                                          ║
║                                                                               ║
║ ORGANIZATION:                                                                 ║
║   1. Text Cleaning        - Remove HTML, CSS, JS                             ║
║   2. Text Validation      - Check for remaining artifacts                    ║
║   3. Section Extraction   - Extract requirements, benefits, etc.             ║
║   4. Display Functions    - Show stats, sections, results                    ║
║   5. Error Logging        - Log errors to JSON file                          ║
║   6. Text Formatting      - Slug conversion, normalization                   ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import re
import json
import unicodedata
from datetime import datetime
from pathlib import Path


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                   1. TEXT CLEANING (Remove HTML/CSS/JS)                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def clean_text_regex(text):
    """Remove HTML/CSS/JavaScript and normalize whitespace from text."""
    if not text:
        return ""
    
    clean = str(text)
    
    # Step 1: Remove <script> blocks (highest priority - often contain junk)
    clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL | re.IGNORECASE)
    
    # Step 2: Remove <style> blocks (contains CSS, not useful)
    clean = re.sub(r'<style[^>]*>.*?</style>', ' ', clean, flags=re.DOTALL | re.IGNORECASE)
    
    # Step 3: Remove @keyframes blocks (all vendor prefixes: -webkit, -moz, -ms, etc.)
    clean = re.sub(r'@[-a-z]*keyframes[^{]*\{[^}]*\}', ' ', clean, flags=re.IGNORECASE)
    
    # Step 4: Remove inline style attributes (style="...")
    clean = re.sub(r'style\s*=\s*["\'][^"\']*["\']', ' ', clean)
    
    # Step 5: Remove all HTML tags (<tag attributes>)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    
    # Step 6: Normalize line breaks (multiple \n → single \n)
    clean = re.sub(r'[\r\n]+', '\n', clean)
    
    # Step 7: Normalize whitespace (multiple spaces → single space, preserve newlines)
    clean = re.sub(r'[ \t]+', ' ', clean)  # Only spaces/tabs, NOT newlines
    
    # Step 8: Remove spaces before newlines
    clean = re.sub(r' +\n', '\n', clean)
    
    return clean.strip()


def repair_mojibake_text(text):
    """Best-effort repair for UTF-8 text that was decoded as Latin-1/CP1252.

    Many scraped job pages contain section headers like 'MÃ´ táº£' instead of
    'Mô tả'. This helper tries to restore those strings before regex extraction.
    """

    if not text:
        return ""

    if not any(marker in text for marker in ("Ã", "Â", "áº", "á»", "Æ", "Ä")):
        return text

    try:
        repaired = text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

    return repaired if repaired else text


def strip_css_artifacts(text):
    """Remove stray CSS-like lines that sometimes leak into cleaned job text."""

    if not text:
        return ""

    keep_lines = []
    css_hint_terms = ("text-decoration", "background-color", "border:", "color:", "display:", "margin:", "padding:")

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "{" or stripped == "}":
            continue
        if stripped.endswith("{"):
            continue
        lowered = stripped.lower()
        if any(term in lowered for term in css_hint_terms):
            continue
        keep_lines.append(line)

    return "\n".join(keep_lines).strip()


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                2. TEXT VALIDATION (Check for artifacts)                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def validate_cleaned_text(cleaned_text):
    """Check if cleaned text still has HTML/CSS/JS artifacts (quality control)."""
    issues = []
    
    if '@keyframes' in cleaned_text or '@webkit' in cleaned_text or '@moz' in cleaned_text:
        issues.append("❌ Keyframes CSS still present")
    
    if '<script' in cleaned_text:
        issues.append("❌ Script tags still present")
    
    if '<style' in cleaned_text:
        issues.append("❌ Style tags still present")
    
    if '<' in cleaned_text and '>' in cleaned_text:
        issues.append("⚠️  Possible remaining HTML tags")
    
    if issues:
        print("\n🔍 VALIDATION ISSUES:")
        for issue in issues:
            print(f"   {issue}")
        return False
    else:
        print("\n✅ VALIDATION: Clean! No HTML artifacts detected")
        return True


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║             3. SECTION EXTRACTION (Extract requirements, benefits)         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def extract_job_sections(cleaned_text):
    """Extract job sections (requirements, benefits, salary, experience) from cleaned text."""
    sections = {}
    
    # Guard against None
    if not cleaned_text:
        return sections

    cleaned_text = repair_mojibake_text(cleaned_text)
    
    # Define section patterns (Vietnamese + English) - include extra anchors so
    # the requirements section stops before company/UI boilerplate.
    section_patterns = {
        'job_description': [r'mô tả công việc', r'mÃ´ táº£ cÃ´ng viá»‡c', r'job description', r'job purpose'],
        'requirements': [r'yêu cầu công việc', r'yêu cầu ứng viên', r'yÃªu cáº§u cÃ´ng viá»‡c', r'requirements', r'điều kiện'],
        'benefits': [r'quyền lợi', r'phÃºc lá»£i', r'benefits', r'phúc lợi'],
        'location': [r'địa điểm làm việc', r'Äá»‹a Ä‘iá»ƒm lÃ m viá»‡c', r'work location', r'location'],
        'other_info': [r'thông tin khác', r'thÃ´ng tin khÃ¡c', r'other information', r'additional information'],
        'company_info': [r'thông tin công ty', r'thÃ´ng tin cÃ´ng ty', r'about the company', r'giới thiệu về công ty', r'giá»›i thiá»‡u vá» cÃ´ng ty'],
        'jobs_opening': [r'việc làm đang tuyển', r'viá»‡c lÃ m Ä‘ang tuyá»ƒn', r'jobs opening', r'opening jobs'],
    }
    
    text_lower = cleaned_text.lower()
    
    # Find section start positions (only main sections)
    section_positions = {}
    for section_name, patterns in section_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                section_positions[section_name] = match.start()
                break
    
    # Extract content between sections (sorted by position)
    sorted_sections = sorted(section_positions.items(), key=lambda x: x[1])
    
    for i, (section_name, start_pos) in enumerate(sorted_sections):
        # Find end position (start of next section or end of text)
        if i < len(sorted_sections) - 1:
            end_pos = sorted_sections[i + 1][1]
        else:
            end_pos = len(cleaned_text)
        
        section_text = cleaned_text[start_pos:end_pos].strip()
        
        # Remove section header (first line: the header keyword line)
        lines = section_text.split('\n')
        content_lines = lines[1:] if len(lines) > 1 else []
        sections[section_name] = strip_css_artifacts('\n'.join(content_lines).strip())
    
    # Add empty placeholders for common output sections for consistency
    for section_name in ['salary', 'experience', 'benefits']:
        if section_name not in sections:
            sections[section_name] = ''
    
    return sections


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║               4. DISPLAY FUNCTIONS (Show stats & results)                   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def display_cleaning_stats(raw_size, cleaned_size):
    """Display text cleaning statistics (size reduction percentage)."""
    if raw_size == 0:
        reduction_pct = 0
    else:
        reduction_pct = round((1 - cleaned_size/raw_size) * 100)
    
    print(f"\n📊 CLEANING STATS:")
    print(f"   Raw size: {raw_size:,} characters")
    print(f"   Cleaned size: {cleaned_size:,} characters")
    print(f"   Reduction: {reduction_pct}%")
    print(f"   Efficiency: {'✅ Good' if reduction_pct >= 70 else '⚠️  Fair' if reduction_pct >= 50 else '❌ Poor'}\n")


def display_section_extraction(cleaned_text, title="Job Description"):
    """Display extracted sections in formatted table."""
    sections = extract_job_sections(cleaned_text)
    
    print(f"\n{'='*80}")
    print(f"EXTRACTED SECTIONS: {title}")
    print(f"{'='*80}")
    
    for section_name, content in sections.items():
        print(f"\n[{section_name.upper()}]")
        print(f"{'-'*80}")
        if content:
            preview = content[:500]
            print(preview)
            if len(content) > 500:
                print(f"... ({len(content)} total characters)")
        else:
            print("(empty)")
    
    print(f"\n{'='*80}\n")


def display_regex_cleaning_results(input_file):
    """Display detailed regex cleaning results for first job in file."""
    try:
        # Load first job
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data:
            print("❌ No data found in file")
            return
        
        first_job = data[0]
        raw_desc = first_job.get('description_html', '')
        job_title = first_job.get('job_title', 'N/A')
        
        # Clean text
        cleaned_desc = clean_text_regex(raw_desc)
        
        # Check for remaining issues
        has_keyframes = '@keyframes' in cleaned_desc or '@webkit' in cleaned_desc or '@moz' in cleaned_desc
        has_script = '<script' in cleaned_desc
        has_style = '<style' in cleaned_desc
        
        # Display results
        print("\n" + "="*80)
        print("REGEX CLEANING TEST RESULTS")
        print("="*80)
        print(f"Job: {job_title}")
        print(f"Raw description size: {len(raw_desc):,} characters")
        print(f"Cleaned description size: {len(cleaned_desc):,} characters")
        reduction_pct = round((1 - len(cleaned_desc)/len(raw_desc)) * 100) if raw_desc else 0
        print(f"Data reduction: {reduction_pct}%")
        print(f"\nQuality check:")
        print(f"  - Keyframes remaining: {has_keyframes}")
        print(f"  - Script tags remaining: {has_script}")
        print(f"  - Style tags remaining: {has_style}")
        print(f"\nCleaned text (FULL):")
        print("-" * 80)
        print(cleaned_desc)
        print("-" * 80 + "\n")
        
        # Extract and display sections
        print(f"EXTRACTED SECTIONS:")
        print("=" * 80)
        sections = extract_job_sections(cleaned_desc)
        for section_name, content in sections.items():
            print(f"\n[{section_name.upper()}]")
            print("-" * 80)
            print(content[:1000] if len(content) > 1000 else content)
            if len(content) > 1000:
                print(f"... (total: {len(content)} chars)")
            print()
        
        # Save results to JSON
        result = {
            "job_title": job_title,
            "timestamp": datetime.now().isoformat(),
            "raw_size": len(raw_desc),
            "cleaned_size": len(cleaned_desc),
            "reduction_percent": reduction_pct,
            "cleaned_text": cleaned_desc,
            "sections": sections
        }
        
        results_file = Path(input_file).parent / "cleaning_results.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ Results saved to: {results_file.name}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        log_error(f"Error in display_regex_cleaning_results: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║              5. ERROR LOGGING (Log errors to JSON file)                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def log_error(message):
    """Log error message to JSON file with timestamp."""
    log_file = Path(__file__).parent.parent / 'data' / 'cleaning_error_log.json'
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "error": message
    }
    
    try:
        existing_logs = []
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                existing_logs = json.load(f)
        
        existing_logs.append(log_entry)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(existing_logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Could not log error: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║           6. TEXT FORMATTING (Slug conversion, normalization)               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def slugify(text):
    """Convert text to URL-friendly slug format."""
    if not text:
        return ""
    
    # Step 1: Handle special cases
    text = text.lower().replace("c++", "cpp").replace("c#", "c-sharp").replace(".net", "dot-net")
    
    # Step 2: Normalize Unicode (remove accents)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    
    # Step 3: Remove non-alphanumeric except spaces and hyphens
    text = re.sub(r'[^\w\s-]', '', text)
    
    # Step 4: Replace spaces and multiple hyphens with single hyphen
    return re.sub(r'[-\s]+', '-', text).strip('-')
