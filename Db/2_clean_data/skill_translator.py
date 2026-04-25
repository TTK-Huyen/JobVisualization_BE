"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                      SKILL TRANSLATOR: VIE → ENG                             ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ ⚠️  DEPRECATED - This module is no longer used                               ║
║                                                                               ║
║ Skill translation is now integrated into the extraction step (STEP 2).       ║
║ The LLM extraction prompt now includes skill_name_eng field directly.        ║
║                                                                               ║
║ PURPOSE (LEGACY): Translate Vietnamese skills to English for embedding       ║
║ METHOD: Gemini LLM-based translation                                        ║
║ OUTPUT: skill_name_eng field for each skill                                 ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import time
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

try:
    import google.generativeai as genai
except ImportError:
    print("[!] google-generativeai not installed, install with: pip install google-generativeai")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gemini_request_options import build_request_options

load_dotenv()

class SkillTranslator:
    """Translate Vietnamese skills to English using Gemini LLM."""
    
    def __init__(self):
        """Initialize translator with Gemini API keys."""
        self.api_keys = [
            os.getenv(f'GEMINI_API_KEY_{i}') 
            for i in range(1, 8) 
            if os.getenv(f'GEMINI_API_KEY_{i}')
        ]
        
        self.current_key_idx = 0
        self.model = "gemini-2.5-flash"
        
        if not self.api_keys:
            raise ValueError("❌ No GEMINI_API_KEY_* found in .env")
        
        print(f"[✓] Initialized with {len(self.api_keys)} API keys")
        self._set_api_key()
    
    def _set_api_key(self):
        """Set current API key."""
        key = self.api_keys[self.current_key_idx % len(self.api_keys)]
        genai.configure(api_key=key)
        print(f"🔑 [TRANSLATOR] Using GEMINI_API_KEY_{self.current_key_idx % len(self.api_keys) + 1}")
    
    def _rotate_key(self):
        """Rotate to next API key on quota error."""
        self.current_key_idx += 1
        self._set_api_key()
    
    def translate_skill(self, skill_name):
        """
        Translate single skill from Vietnamese to English.
        
        Args:
            skill_name: Vietnamese skill name (string)
            
        Returns:
            English translation (string), or original if translation fails
        """
        if not skill_name or not isinstance(skill_name, str):
            return skill_name
        
        # Skip if already English (mostly uppercased, numbers, or known English skills)
        if self._is_english(skill_name):
            return skill_name
        
        try:
            prompt = f"""Translate this Vietnamese skill/technology name to English.
ONLY return the English translation, nothing else. Just the translated word/phrase.

Vietnamese: {skill_name}
English:"""
            
            client = genai.Client()
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=50,
                    temperature=0.3,
                ),
                request_options=build_request_options(),
            )
            
            if response and response.text:
                translation = response.text.strip()
                # Clean up: remove extra quotes/punctuation
                translation = translation.strip('"\'.,')
                return translation if translation else skill_name
        
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print(f"⚠️  [QUOTA] Key quota exhausted, rotating...")
                self._rotate_key()
            else:
                print(f"⚠️  Translation error for '{skill_name}': {str(e)}")
        
        return skill_name
    
    def translate_batch(self, skills):
        """
        Translate multiple skills.
        
        Args:
            skills: List of skill names (strings)
            
        Returns:
            List of tuples: [(original, translated), ...]
        """
        results = []
        for skill in skills:
            translated = self.translate_skill(skill)
            results.append((skill, translated))
            time.sleep(0.1)  # Rate limiting
        
        return results
    
    @staticmethod
    def _is_english(text):
        """Check if text is already English (heuristic)."""
        # Known English patterns: Java, SQL, HTML, CSS, etc.
        english_keywords = [
            'java', 'python', 'sql', 'html', 'css', 'api', 'http', 'json',
            'rest', 'xml', 'git', 'aws', 'gcp', 'azure', 'docker', 'kubernetes',
            'spring', 'react', 'angular', 'node', 'express', 'django', 'flask',
            'mysql', 'postgresql', 'oracle', 'mongodb', 'redis', 'elasticsearch',
            'kafka', 'rabbitmq', 'mq', 'linux', 'windows', 'oauth', 'jwt',
            'testing', 'junit', 'pytest', 'selenium', 'postman', 'jira', 'confluence'
        ]
        
        text_lower = text.lower().strip()
        
        # Check if it's in English keywords
        if any(text_lower.startswith(kw) or text_lower.endswith(kw) for kw in english_keywords):
            return True
        
        # Check if mostly uppercase/numbers (acronyms like OOP, MQ, EE)
        if len(text) <= 5 and (text.isupper() or text.replace('/', '').isupper()):
            return True
        
        # Check if contains mostly ASCII
        ascii_ratio = sum(1 for c in text if ord(c) < 128) / len(text) if text else 0
        if ascii_ratio > 0.8:
            return True
        
        return False


def translate_skills(input_file, output_file=None):
    """
    Translate extracted skills in JSON file from Vietnamese to English.
    
    Input: output_2_sections.json (from STEP 2)
    Output: Same file with added 'skill_translated' field
    """
    if output_file is None:
        output_file = input_file.replace('.json', '_translated.json')
    
    print(f"\n{'='*80}")
    print("SKILL TRANSLATION: VIETNAMESE → ENGLISH")
    print(f"{'='*80}")
    
    # Read input
    print(f"[*] Reading: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    if not isinstance(jobs, list):
        jobs = [jobs]
    
    print(f"[*] Processing {len(jobs)} jobs...")
    
    # Initialize translator
    translator = SkillTranslator()
    
    # Translate skills for each job
    translated_count = 0
    for idx, job in enumerate(jobs, 1):
        # Extract skills from nested structure
        extracted_skills = job.get('extracted_skills', [])
        
        if not extracted_skills:
            continue
        
        # For each skill item
        for skill_item in extracted_skills:
            if isinstance(skill_item, dict):
                # Check nested structure
                if 'extracted_skills' in skill_item:
                    for skill in skill_item['extracted_skills']:
                        if isinstance(skill, dict) and 'skill_name' in skill:
                            original = skill['skill_name']
                            translated = translator.translate_skill(original)
                            if translated != original:
                                skill['skill_name_eng'] = translated
                                translated_count += 1
                                print(f"  ✓ '{original}' → '{translated}'")
        
        if idx % 5 == 0:
            print(f"[*] Processed {idx}/{len(jobs)} jobs...")
    
    # Save output
    print(f"\n[*] Saving to: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    
    print(f"\n[+] Translation Complete!")
    print(f"   Total translated: {translated_count} skills")
    print(f"   Output: {output_file}")
    
    return jobs


if __name__ == "__main__":
    # Test: Translate a list of skills
    test_skills = [
        'Java',
        'framework Java',
        'EE',
        'Spring',
        'Hibernate',
        'SQL',
        'PL/SQL',
        'Oracle',
        'MySQL',
        'tối ưu CSDL',
        'OOP',
        'đa luồng',
        'HTTP',
        'Redis',
        'MQ',
        'MES',
        'QMS',
        'WMS',
        'sản xuất thông minh',
        'công nghiệp 4.0'
    ]
    
    print("\n" + "="*80)
    print("SKILL TRANSLATOR - TEST")
    print("="*80)
    
    translator = SkillTranslator()
    results = translator.translate_batch(test_skills)
    
    print(f"\n{'Original':<25} → {'Translated':<35}")
    print("-" * 65)
    for original, translated in results:
        print(f"{original:<25} → {translated:<35}")
