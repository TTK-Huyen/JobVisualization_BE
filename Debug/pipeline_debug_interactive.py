#!/usr/bin/env python3
"""
PIPELINE DEBUG SCRIPT - Interactive Debug Tool
Hỗ trợ debug từng bước pipeline: Crawl → Merge → Clean → Extract → Normalize
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
import subprocess

BASE_DIR = Path(__file__).parent
DB_DIR = BASE_DIR / "Db"
DATA_DIR = DB_DIR / "data"


class PipelineDebugger:
    """Interactive debugger for pipeline stages"""
    
    def __init__(self, crawl_folder: str):
        self.crawl_folder = crawl_folder
        self.crawl_path = DATA_DIR / crawl_folder
        self.raw_path = self.crawl_path / "raw"
        self.clean_path = self.crawl_path / "clean"
        self.fallback_path = self.crawl_path / "fallback"
        
        if not self.crawl_path.exists():
            raise FileNotFoundError(f"Folder not found: {self.crawl_path}")
    
    def show_menu(self):
        """Display interactive menu"""
        print("""
╔════════════════════════════════════════════════════════════════════╗
║           PIPELINE DEBUG TOOL - JobVisualization_BE                ║
╚════════════════════════════════════════════════════════════════════╝

Select a step to debug:
  1. Check folder structure
  2. Check raw data (jobs_combined.json)
  3. Check clean data (pending_llm.json)
  4. Analyze job loss (raw → clean)
  5. Run clean step (Step 1)
  6. Check extract data (extracted.json)
  7. Run extraction
  8. Check normalized data
  9. Validate full pipeline flow
  10. Show common issues & fixes
  0. Exit

Current crawl folder: {crawl_folder}
""".format(crawl_folder=self.crawl_folder))
    
    def check_structure(self):
        """Step 1: Show folder structure"""
        print("\n" + "="*70)
        print("FOLDER STRUCTURE")
        print("="*70)
        
        for subdir in ["raw", "clean", "fallback", "logs"]:
            dir_path = self.crawl_path / subdir
            if dir_path.exists():
                files = list(dir_path.glob("*.json"))
                print(f"\n✓ {subdir}/ ({len(files)} files)")
                for f in sorted(files)[:5]:
                    size_kb = f.stat().st_size / 1024
                    print(f"    - {f.name} ({size_kb:.1f} KB)")
            else:
                print(f"\n✗ {subdir}/ (missing)")
    
    def check_raw(self):
        """Step 2: Analyze raw data"""
        print("\n" + "="*70)
        print("RAW DATA ANALYSIS")
        print("="*70)
        
        raw_file = self.raw_path / "jobs_combined.json"
        if not raw_file.exists():
            print(f"✗ {raw_file} not found")
            return
        
        try:
            data = json.load(open(raw_file, encoding='utf-8'))
            print(f"\n✓ Total jobs: {len(data)}")
            
            # Analyze structure
            has_req = sum(1 for j in data if j.get('requirements_text'))
            has_desc = sum(1 for j in data if j.get('description_html'))
            has_url = sum(1 for j in data if j.get('job_url'))
            
            print(f"\n  Field analysis:")
            print(f"    - With requirements_text: {has_req}/{len(data)}")
            print(f"    - With description_html: {has_desc}/{len(data)}")
            print(f"    - With job_url: {has_url}/{len(data)}")
            
            # Show samples
            print(f"\n  Sample jobs:")
            for i, job in enumerate(data[:3], 1):
                print(f"\n    {i}. {job.get('title', 'N/A')[:50]}")
                print(f"       Source: {job.get('source_name', 'N/A')}")
                print(f"       has_req: {bool(job.get('requirements_text'))}")
                
        except Exception as e:
            print(f"✗ Error reading file: {e}")
    
    def check_clean(self):
        """Step 3: Analyze clean data"""
        print("\n" + "="*70)
        print("CLEAN DATA ANALYSIS")
        print("="*70)
        
        clean_file = self.clean_path / "pending_llm.json"
        if not clean_file.exists():
            print(f"✗ {clean_file} not found")
            return
        
        try:
            data = json.load(open(clean_file, encoding='utf-8'))
            print(f"\n✓ Total jobs: {len(data)}")
            
            if data:
                print(f"\n  Sample job structure:")
                first = data[0]
                print(f"    - Fields: {list(first.keys())[:5]}...")
                print(f"    - Title: {first.get('title', 'N/A')[:60]}")
                print(f"    - Requirements text length: {len(first.get('requirements_text', ''))}")
                
        except Exception as e:
            print(f"✗ Error reading file: {e}")
    
    def analyze_loss(self):
        """Step 4: Compare raw vs clean"""
        print("\n" + "="*70)
        print("JOB LOSS ANALYSIS (Raw → Clean)")
        print("="*70)
        
        raw_file = self.raw_path / "jobs_combined.json"
        clean_file = self.clean_path / "pending_llm.json"
        
        if not raw_file.exists() or not clean_file.exists():
            print("✗ Missing files for comparison")
            return
        
        try:
            raw_data = json.load(open(raw_file, encoding='utf-8'))
            clean_data = json.load(open(clean_file, encoding='utf-8'))
            
            print(f"\n  Raw: {len(raw_data)} jobs")
            print(f"  Clean: {len(clean_data)} jobs")
            print(f"  Lost: {len(raw_data) - len(clean_data)} jobs")
            
            if len(raw_data) > len(clean_data):
                print(f"\n  Reasons for loss (analyzing first 5 lost jobs):")
                
                raw_urls = {j.get('job_url'): j for j in raw_data}
                clean_urls = {j.get('job_url'): j for j in clean_data}
                lost_urls = set(raw_urls.keys()) - set(clean_urls.keys())
                
                for url in list(lost_urls)[:5]:
                    if url:
                        job = raw_urls[url]
                        reason = "Unknown"
                        if not job.get('requirements_text'):
                            reason = "No requirements_text"
                        elif not job.get('job_url'):
                            reason = "No job_url"
                        elif not job.get('title'):
                            reason = "No title"
                        
                        print(f"\n    ✗ {job.get('title', 'N/A')[:40]}")
                        print(f"      Reason: {reason}")
                        
        except Exception as e:
            print(f"✗ Error: {e}")
    
    def run_clean_step1(self):
        """Step 5: Run clean step 1"""
        print("\n" + "="*70)
        print("RUNNING CLEAN STEP 1")
        print("="*70)
        
        raw_file = self.raw_path / "jobs_combined.json"
        output_file = self.clean_path / "pending_llm.json"
        
        cmd = [
            str((DB_DIR / ".venv/Scripts/python.exe")),
            str(DB_DIR / "pipeline/clean/clean_process.py"),
            str(raw_file),
            "--step", "1",
            "--output", str(output_file)
        ]
        
        print(f"Command: {' '.join(cmd)}")
        print("\nExecuting...")
        
        try:
            result = subprocess.run(cmd, cwd=str(DB_DIR), capture_output=True, text=True)
            if result.returncode == 0:
                print("✓ Clean step completed successfully")
                if output_file.exists():
                    data = json.load(open(output_file, encoding='utf-8'))
                    print(f"  Output: {len(data)} jobs in {output_file.name}")
            else:
                print(f"✗ Error: {result.stderr}")
        except Exception as e:
            print(f"✗ Failed to run: {e}")
    
    def check_extract(self):
        """Step 6: Analyze extracted data"""
        print("\n" + "="*70)
        print("EXTRACTED DATA ANALYSIS")
        print("="*70)
        
        extract_file = self.clean_path / "extracted.json"
        if not extract_file.exists():
            print(f"✗ {extract_file} not found")
            return
        
        try:
            data = json.load(open(extract_file, encoding='utf-8'))
            print(f"\n✓ Total jobs extracted: {len(data)}")
            
            # Check fallback
            fallback_file = self.fallback_path / "extract_fallback.json"
            if fallback_file.exists():
                fallback = json.load(open(fallback_file, encoding='utf-8'))
                print(f"  Fallback jobs: {len(fallback)}")
            
            if data:
                print(f"\n  Sample extracted job:")
                first = data[0]
                print(f"    - Title: {first.get('title', {}).get('value', 'N/A')[:50]}")
                print(f"    - Skills extracted: {len(first.get('skills_desc', []))}")
                print(f"    - Salaries: {first.get('salaries', [])}")
                
        except Exception as e:
            print(f"✗ Error: {e}")
    
    def validate_flow(self):
        """Step 9: Full pipeline validation"""
        print("\n" + "="*70)
        print("FULL PIPELINE VALIDATION")
        print("="*70)
        
        stages = {
            "Raw": self.raw_path / "jobs_combined.json",
            "Clean": self.clean_path / "pending_llm.json",
            "Extracted": self.clean_path / "extracted.json",
            "Normalized": self.clean_path / "normalized.json",
        }
        
        print(f"\n{'Stage':<12} {'Jobs':<10} {'Status':<15}")
        print("-" * 40)
        
        counts = {}
        for stage, path in stages.items():
            try:
                data = json.load(open(path, encoding='utf-8'))
                count = len(data)
                counts[stage] = count
                status = "✓ OK" if count > 0 else "✗ Empty"
                print(f"{stage:<12} {count:<10} {status:<15}")
            except FileNotFoundError:
                print(f"{stage:<12} {'N/A':<10} {'✗ Missing':<15}")
            except Exception as e:
                print(f"{stage:<12} {'N/A':<10} {'✗ Error':<15}")
        
        # Analyze flow
        print("\n" + "="*40)
        print("FLOW ANALYSIS")
        print("="*40)
        
        if "Raw" in counts and "Clean" in counts:
            loss = counts["Raw"] - counts["Clean"]
            loss_pct = (loss / counts["Raw"] * 100) if counts["Raw"] > 0 else 0
            print(f"Raw → Clean: {loss} lost ({loss_pct:.1f}%)")
        
        if "Clean" in counts and "Extracted" in counts:
            success = counts["Extracted"] / counts["Clean"] * 100 if counts["Clean"] > 0 else 0
            print(f"Extraction success: {success:.1f}%")
    
    def show_common_issues(self):
        """Step 10: Common issues & fixes"""
        print("""
╔════════════════════════════════════════════════════════════════════╗
║                   COMMON ISSUES & FIXES                           ║
╚════════════════════════════════════════════════════════════════════╝

ISSUE 1: Large job loss (Raw → Clean)
  Symptom: 9 → 1 jobs
  Cause: Jobs missing required fields (requirements_text, job_url, etc)
  Check:
    - python debug_job_loss.py
    - View Db/pipeline/crawl/crawl_schema.json for required fields
  Fix:
    - Verify raw data has all required fields
    - Check if crawl step completed successfully

ISSUE 2: No extracted jobs
  Symptom: pending_llm.json has jobs but extracted.json is empty
  Cause: LLM errors, API failures, or retry queue issues
  Check:
    - tail -f Db/data/{folder}/logs/*.log
    - Check extract_fallback.json for error details
    - Run: python -c "import json; print(json.load(open('Db/data/{folder}/fallback/extract_fallback.json')))"
  Fix:
    - Ensure API keys are active (check .env)
    - Disable retry_queue if needed
    - Run extraction again

ISSUE 3: Extraction takes too long
  Symptom: Processing (1/71) instead of (1/1)
  Cause: Retry queue loading cached jobs
  Fix:
    - Comment out line 949 in process_pending_llm.py
    - Or run: python process_pending_llm.py --ignore-retry-queue

ISSUE 4: Output files in wrong folder
  Symptom: Files created in Db/data/{different_folder}/
  Cause: BASE_PATH not resolved correctly
  Fix:
    - Use absolute paths when calling scripts
    - Verify working directory is correct (cwd=Db/)
    - Use run_etl_pipeline.py which handles paths automatically

ISSUE 5: Can't find jobs in normalized data
  Symptom: Normalized jobs don't match extracted jobs
  Cause: Normalization filters, skill mapping issues
  Check:
    - Compare job URLs between extracted and normalized
    - Check normalizer logs (Db/logs/*)
  Fix:
    - Review normalization rules
    - Check skill mapping database

QUICK FIX COMMANDS:

# Count jobs at each stage
python << 'EOF'
import json, os
for stage in ['raw/jobs_combined.json', 'clean/pending_llm.json', 'clean/extracted.json', 'clean/normalized.json']:
    try:
        path = 'Db/data/crawl_20260506_114403/' + stage
        data = json.load(open(path, encoding='utf-8'))
        print(f'{stage}: {len(data)} jobs')
    except: pass
EOF

# Find which jobs are missing between stages
python debug_job_loss.py

# Run full pipeline on single folder
cd Db
python run_etl_pipeline.py --input "F:\\...\\crawl_YYYYMMDD_HHMMSS\\raw\\jobs_combined.json"

# Test extraction with ignore retry queue
cd Db
python pipeline/extract/process_pending_llm.py \\
  --input-path "data/crawl_YYYYMMDD_HHMMSS/clean/pending_llm.json" \\
  --ignore-retry-queue
""")
    
    def interactive_menu(self):
        """Main interactive loop"""
        while True:
            self.show_menu()
            choice = input("Enter choice (0-10): ").strip()
            
            if choice == "0":
                print("Exiting...")
                break
            elif choice == "1":
                self.check_structure()
            elif choice == "2":
                self.check_raw()
            elif choice == "3":
                self.check_clean()
            elif choice == "4":
                self.analyze_loss()
            elif choice == "5":
                self.run_clean_step1()
            elif choice == "6":
                self.check_extract()
            elif choice == "9":
                self.validate_flow()
            elif choice == "10":
                self.show_common_issues()
            else:
                print("Invalid choice")
            
            input("\nPress Enter to continue...")


def main():
    """Main entry point"""
    print("Pipeline Debug Tool - JobVisualization_BE\n")
    
    if len(sys.argv) > 1:
        crawl_folder = sys.argv[1]
    else:
        print("Available crawl folders:")
        folders = sorted([f.name for f in DATA_DIR.iterdir() if f.is_dir() and f.name.startswith("crawl_")])
        for i, folder in enumerate(folders[-10:], 1):  # Show last 10
            print(f"  {i}. {folder}")
        
        folder_input = input(f"\nEnter folder name or number (1-{len(folders[-10:])}): ").strip()
        try:
            idx = int(folder_input) - 1
            crawl_folder = folders[-10:][idx]
        except:
            crawl_folder = folder_input
    
    try:
        debugger = PipelineDebugger(crawl_folder)
        debugger.interactive_menu()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
