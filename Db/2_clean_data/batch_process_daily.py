#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                  PRODUCTION BATCH PROCESSOR FOR STEP 2                        ║
║              Process daily job crawls in batches of 10 jobs                   ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ INPUT:  data/crawl_YYYYMMDD_HHMMSS/raw/jobs_combined.json                   ║
║ OUTPUT: data/crawl_YYYYMMDD_HHMMSS/clean/normalized.json                  ║
║                                                                               ║
║ FEATURES:                                                                     ║
║ - Auto-detects crawl date folder from input path                            ║
║ - Splits jobs into 10-job batches                                           ║
║ - Processes each batch through full 3-step pipeline                         ║
║ - Saves individual batch outputs + optional merged file                     ║
║ - Rate-limited LLM requests (prevents quota exceeded)                       ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import json
import os
import argparse
import re
from pathlib import Path
from datetime import datetime
import subprocess

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Import API counter
try:
    from skill_extraction_llm import get_api_call_count
except ImportError:
    def get_api_call_count():
        return 0

try:
    from cache_manager import (
        load_pending_failed_jobs,
        clear_pending_failed_jobs,
        save_pending_failed_jobs,
        get_job_fingerprint,
    )
except ImportError:
    def load_pending_failed_jobs():
        return []

    def clear_pending_failed_jobs():
        return None

    def save_pending_failed_jobs(jobs):
        return None

    def get_job_fingerprint(job):
        title = job.get('title', '')
        company = job.get('company_name', '')
        req = job.get('requirements_text', '')
        return f"{title}|{company}|{req}"


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                          BATCH ORCHESTRATOR                                 ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class DailyBatchProcessor:
    """Orchestrates batch processing of daily job crawls."""
    
    def __init__(self, input_file, batch_size=10, merge_output=True, max_jobs=None):
        """
        Args:
            input_file: Path to jobs_combined.json or full path with crawl folder
            batch_size: Jobs per batch (default: 10)
            merge_output: Whether to merge all batch outputs into single file
            max_jobs: If set, only process first N jobs (useful for testing)
        """
        self.input_file = Path(input_file)
        self.batch_size = batch_size
        self.merge_output = merge_output
        self.max_jobs = max_jobs
        self.total_api_calls = 0  # Track total API calls across all batches
        
        # Parse crawl folder from path
        self.crawl_folder = self._extract_crawl_folder()
        self.output_folder = self.crawl_folder / "clean"
        self.logs_folder = self.crawl_folder / "logs"
        self.fallback_folder = self.crawl_folder / "fallback"
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.logs_folder.mkdir(parents=True, exist_ok=True)
        self.fallback_folder.mkdir(parents=True, exist_ok=True)
        self.max_same_run_retry_rounds = int(os.getenv("ETL_MAX_SAME_RUN_RETRY_ROUNDS", "3"))
        
        init_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n{'='*80}")
        print("BATCH PROCESSOR INITIALIZED")
        print(f"{'='*80}")
        print(f"Start time:   {init_time}")
        print(f"Input file:   {self.input_file}")
        print(f"Crawl folder: {self.crawl_folder.name}")
        print(f"Output dir:   {self.output_folder}")
        print(f"Batch size:   {batch_size} jobs/batch")
        print(f"Retry rounds: {self.max_same_run_retry_rounds} same-run rounds max")
        print(f"{'='*80}")
        
    def _extract_crawl_folder(self):
        """Extract crawl folder from input path.
        
        Expected format: .../data/crawl_YYYYMMDD_HHMMSS/raw/jobs_combined.json
        Returns: Path to crawl_YYYYMMDD_HHMMSS folder
        """
        # Handle both relative and absolute paths
        parts = self.input_file.parts
        
        # Find "crawl_" pattern in path
        for i, part in enumerate(parts):
            if part.startswith("crawl_"):
                # Found it! Return the crawl_ folder
                crawl_path = Path(*parts[:i+1])
                
                # Make absolute if needed
                if not crawl_path.is_absolute():
                    crawl_path = Path.cwd() / crawl_path
                
                return crawl_path
        
        # Fallback: assume it's in data/ folder next to current dir
        current_dir = Path(self.input_file).parent.parent
        raise ValueError(f"Could not detect crawl folder from path: {self.input_file}\n"
                        f"Expected format: data/crawl_YYYYMMDD_HHMMSS/raw/jobs_combined.json")
    
    def split_into_batches(self):
        """Split jobs into batches of specified size.
        
        Returns: List of batch file paths
        """
        load_start = datetime.now()
        print(f"\n[LOAD] START → Loading jobs from {self.input_file.name} | {load_start.strftime('%H:%M:%S')}")
        
        with open(self.input_file, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        
        if not isinstance(jobs, list):
            jobs = [jobs]

        if self.max_jobs is not None:
            jobs = jobs[:self.max_jobs]

        ignore_pending = os.getenv("BATCH_IGNORE_PENDING", "false").lower() in ("true", "1", "yes")
        pending_jobs = [] if ignore_pending else load_pending_failed_jobs()
        if pending_jobs:
            print(f"   [✓] Loaded {len(pending_jobs)} pending failed jobs to retry")

            existing_fingerprints = {get_job_fingerprint(job) for job in jobs if isinstance(job, dict)}
            merged_pending = []
            for job in pending_jobs:
                if not isinstance(job, dict):
                    continue
                fingerprint = get_job_fingerprint(job)
                if fingerprint not in existing_fingerprints:
                    merged_pending.append(job)
                    existing_fingerprints.add(fingerprint)

            if merged_pending:
                jobs = merged_pending + jobs
                print(f"   [✓] Added {len(merged_pending)} unique pending jobs into current run")
            clear_pending_failed_jobs()
        
        total_jobs = len(jobs)
        self.all_jobs = jobs
        load_duration = datetime.now() - load_start
        print(f"   [✓] Loaded {total_jobs} jobs | {load_duration}")
        print(f"\n[SPLIT] START → Splitting into batches of {self.batch_size}")

        return self._create_batch_files_from_jobs(jobs, start_batch_id=1, batch_prefix="batch")

    def _create_batch_files_from_jobs(self, jobs, start_batch_id=1, batch_prefix="batch"):
        """Create batch files from an in-memory job list."""
        total_jobs = len(jobs)
        
        # Create batch folder
        batch_folder = self.logs_folder / "batches"
        batch_folder.mkdir(parents=True, exist_ok=True)
        
        batch_files = []
        for offset, batch_num in enumerate(range(0, total_jobs, self.batch_size), start=0):
            batch_jobs = jobs[batch_num:batch_num + self.batch_size]
            batch_id = start_batch_id + offset
            
            batch_file = batch_folder / f"{batch_prefix}_{batch_id:03d}.json"
            with open(batch_file, 'w', encoding='utf-8') as f:
                json.dump(batch_jobs, f, ensure_ascii=False, indent=2)
            
            batch_files.append((batch_id, batch_file, len(batch_jobs)))
            print(f"   Batch {batch_id:3d}: {len(batch_jobs):2d} jobs → {batch_file.name}")
        
        print(f"   [✓] Created {len(batch_files)} batches")
        return batch_files

    def _load_jobs_from_batch_file(self, batch_file):
        """Load jobs from a batch file."""
        try:
            with open(batch_file, 'r', encoding='utf-8') as f:
                jobs = json.load(f)
            if not isinstance(jobs, list):
                jobs = [jobs]
            return jobs
        except Exception as e:
            print(f"   ⚠️  Could not load jobs from {Path(batch_file).name}: {str(e)[:80]}")
            return []

    def _is_quota_failure(self, job):
        """Detect if a failed job stopped because all keys/quota were exhausted."""
        if not isinstance(job, dict):
            return False

        error_text = f"{job.get('_error', '')} {job.get('_message', '')}".lower()
        return any(marker in error_text for marker in [
            'quota exhausted',
            'all_keys_exhausted',
            '429',
            'quota',
            'daily limit exceeded',
        ])

    def _collect_failed_jobs_from_subprocess(self):
        """Read failed jobs produced by clean_process.py and clear the queue file."""
        failed_jobs = load_pending_failed_jobs()
        if failed_jobs:
            clear_pending_failed_jobs()
        quota_exhausted = any(self._is_quota_failure(job) for job in failed_jobs)
        return failed_jobs, quota_exhausted

    def _dedupe_jobs(self, jobs):
        """Deduplicate jobs by fingerprint while preserving order."""
        seen = set()
        unique_jobs = []

        for job in jobs or []:
            if not isinstance(job, dict):
                continue
            fingerprint = job.get('_fingerprint') or get_job_fingerprint(job)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique_jobs.append(job)

        return unique_jobs
    
    def process_batch(self, batch_id, batch_file, job_count):
        """Process a single batch through the full pipeline.
        
        Args:
            batch_id: Batch number
            batch_file: Path to batch JSON file
            job_count: Number of jobs in this batch
        
        Returns: (output_file, failed_jobs, quota_exhausted)
        """
        output_file = self.output_folder / f"batch_{batch_id:03d}.json"
        step1_output_file = self.logs_folder / f"clean_step1_debug_batch_{batch_id:03d}.json"
        batch_start = datetime.now()
        
        print(f"\n[Batch {batch_id:3d}] START → Processing {job_count:2d} jobs | {datetime.now().strftime('%H:%M:%S')}")
        
        # Call clean_process.py for this batch
        cmd = [
            sys.executable,
            "clean_process.py",
            str(batch_file),
            "--output", str(output_file)
        ]
        
        # Setup environment - explicitly inherit and extend with venv path
        env = os.environ.copy()
        venv_lib_path = Path(sys.executable).parent.parent / "Lib" / "site-packages"
        db_root_path = str(Path(__file__).parent.parent)
        if 'PYTHONPATH' in env:
            env['PYTHONPATH'] = f"{db_root_path}{os.pathsep}{venv_lib_path}{os.pathsep}{env['PYTHONPATH']}"
        else:
            env['PYTHONPATH'] = f"{db_root_path}{os.pathsep}{venv_lib_path}"
        
        try:
            # Use Popen to stream output in real-time
            process = subprocess.Popen(
                cmd,
                cwd=str(Path(__file__).parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                bufsize=1,  # Line buffered
                env=env  # Pass explicit environment
            )
            
            last_stage_time = batch_start
            current_stage = ""
            
            # Read and print output line by line
            try:
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    
                    line = line.rstrip('\n\r')
                    if not line.strip():
                        continue
                    
                    # Track stage changes
                    if "STEP 1:" in line:
                        current_stage = "STEP 1: Clean HTML"
                    elif "STEP 2:" in line:
                        current_stage = "STEP 2: Extract Skills"
                    elif "STEP 3:" in line:
                        current_stage = "STEP 3: Normalize Skills"
                    elif "Complete" in line or "COMPLETE" in line:
                        current_stage = "COMPLETE"
                    
                    # Capture API call count from subprocess
                    if "[📊] TOTAL API CALLS IN SUBPROCESS:" in line:
                        try:
                            api_calls = int(line.split(":")[1].strip())
                            self.total_api_calls += api_calls
                        except (ValueError, IndexError):
                            pass
                    
                    # Print important lines with batch prefix - include API key logs
                    if any(x in line for x in ["STEP", "Complete", "COMPLETE", "Skills extracted:", "Jobs:", "ERROR", "Failed", "[INIT]", "[API]", "[QUOTA", "[ROTATE]", "[SUCCESS]", "[EXHAUSTED]", "[INPUT]", "[CACHE]", "[RPM]", "[JSON]", "[📊]", "send:", "reply:", "header:", "HTTP", "urllib3", "google.generativeai", "google.api_core"]):
                        time_str = datetime.now().strftime('%H:%M:%S')
                        print(f"   [{batch_id:3d}] {line[:75]} | {time_str}")
                
                # Wait for process to complete
                return_code = process.wait(timeout=1800)
                batch_duration = datetime.now() - batch_start

                failed_jobs, quota_exhausted = self._collect_failed_jobs_from_subprocess()

                self._copy_step1_output_to_archive(step1_output_file)
                
                if return_code == 0:
                    print(f"   [✓] Batch {batch_id:3d} Success | Duration: {batch_duration}")
                    return output_file, failed_jobs, quota_exhausted
                else:
                    print(f"   [✗] Batch {batch_id:3d} Failed (code {return_code}) | Duration: {batch_duration}")
                    return None, failed_jobs, quota_exhausted
                    
            except subprocess.TimeoutExpired:
                process.kill()
                batch_duration = datetime.now() - batch_start
                print(f"   [✗] Batch {batch_id:3d} Timeout after {batch_duration}")
                failed_jobs, quota_exhausted = self._collect_failed_jobs_from_subprocess()
                self._copy_step1_output_to_archive(step1_output_file)
                return None, failed_jobs, quota_exhausted
                
        except Exception as e:
            batch_duration = datetime.now() - batch_start
            print(f"   [✗] Error: {str(e)[:50]} | Duration: {batch_duration}")
            failed_jobs, quota_exhausted = self._collect_failed_jobs_from_subprocess()
            self._copy_step1_output_to_archive(step1_output_file)
            return None, failed_jobs, quota_exhausted
    
    def merge_batches(self, output_files):
        """Merge all batch outputs into single file.
        
        Args:
            output_files: List of batch output file paths
        
        Returns: Path to merged file
        """
        if not output_files:
            print("⚠️  No batches to merge")
            return None
        
        merge_start = datetime.now()
        print(f"\n[MERGE] START → Merging {len(output_files)} batch outputs | {merge_start.strftime('%H:%M:%S')}")
        
        all_jobs = []
        for batch_file in output_files:
            try:
                with open(batch_file, 'r', encoding='utf-8') as f:
                    batch_jobs = json.load(f)
                if isinstance(batch_jobs, list):
                    all_jobs.extend(batch_jobs)
                else:
                    all_jobs.append(batch_jobs)
            except Exception as e:
                print(f"   ⚠️  Error reading {batch_file.name}: {str(e)[:50]}")
                continue
        
        # Save merged file
        merged_file = self.output_folder / "normalized.json"
        with open(merged_file, 'w', encoding='utf-8') as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)
        
        merge_duration = datetime.now() - merge_start
        print(f"   [✓] Merged {len(all_jobs)} jobs → {merged_file.name} | {merge_duration}")
        
        # Delete individual batch files after merging
        print(f"[CLEANUP] Deleting individual batch files...")
        for batch_file in output_files:
            try:
                batch_file.unlink()
            except Exception as e:
                print(f"   ⚠️  Could not delete {batch_file.name}: {str(e)[:50]}")
        
        print(f"   [✓] Cleanup complete")
        return merged_file
    
    def run(self):
        """Execute full batch processing workflow."""
        overall_start = datetime.now()
        
        print(f"\n{'='*80}")
        print(f"BATCH PROCESSING START → {overall_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        
        try:
            # STEP 1: Split into batches
            split_start = datetime.now()
            batch_files = self.split_into_batches()
            split_duration = datetime.now() - split_start
            print(f"[SPLIT] Complete in {split_duration}")
            
            # STEP 2: Process each batch
            print(f"\n{'='*80}")
            print(f"PROCESSING BATCHES [{len(batch_files)} total]")
            print(f"{'='*80}")
            
            process_start = datetime.now()
            successful_batches = []
            failed_batches = []
            pending_next_day_jobs = []
            retry_jobs = []
            quota_exhausted = False
            
            current_batches = batch_files
            next_batch_id = len(batch_files) + 1
            retry_round = 1

            while current_batches:
                print(f"\n{'='*80}")
                print(f"PROCESSING ROUND {retry_round} [{len(current_batches)} batches]")
                print(f"{'='*80}")

                next_retry_jobs = []

                for i, (batch_id, batch_file, job_count) in enumerate(current_batches):
                    print(f"\n[Progress] {i}/{len(current_batches)} batches processed")
                    output_file, failed_jobs, batch_quota_exhausted = self.process_batch(batch_id, batch_file, job_count)

                    if output_file and output_file.exists():
                        successful_batches.append(output_file)
                    elif batch_id not in failed_batches:
                        failed_batches.append(batch_id)

                    if failed_jobs:
                        if batch_quota_exhausted:
                            quota_exhausted = True
                            print(f"\n[STOP] Quota exhausted during batch {batch_id}; saving remaining jobs for next day")
                            pending_next_day_jobs.extend(next_retry_jobs)
                            pending_next_day_jobs.extend(failed_jobs)

                            # Save all jobs that were not processed yet in this round
                            for _, remaining_batch_file, _ in current_batches[i + 1:]:
                                pending_next_day_jobs.extend(self._load_jobs_from_batch_file(remaining_batch_file))
                            break

                        next_retry_jobs.extend(failed_jobs)

                if quota_exhausted:
                    break

                next_retry_jobs = self._dedupe_jobs(next_retry_jobs)
                if not next_retry_jobs:
                    break

                if retry_round >= self.max_same_run_retry_rounds:
                    print(f"\n[STOP] Reached same-run retry limit ({self.max_same_run_retry_rounds}); deferring {len(next_retry_jobs)} jobs to next day")
                    pending_next_day_jobs.extend(next_retry_jobs)
                    break

                retry_round += 1
                current_batches = self._create_batch_files_from_jobs(
                    next_retry_jobs,
                    start_batch_id=next_batch_id,
                    batch_prefix=f"retry_r{retry_round:02d}"
                )
                next_batch_id += len(current_batches)
            
            process_duration = datetime.now() - process_start
            print(f"\n[BATCH PROCESSING] Complete in {process_duration}")

            if pending_next_day_jobs:
                pending_next_day_jobs = self._dedupe_jobs(pending_next_day_jobs)
                print(f"\n[PENDING] Saving {len(pending_next_day_jobs)} jobs for next day's run")
                save_pending_failed_jobs(pending_next_day_jobs)
            
            # STEP 3: Merge (optional)
            merged_file = None
            if self.merge_output and successful_batches:
                merged_file = self.merge_batches(successful_batches)
            
            # STEP 4: Copy STEP 2 output to archive (for user to review before normalization)
            self._copy_step2_output_to_archive(0)
            
            # SUMMARY
            overall_duration = datetime.now() - overall_start
            self._print_summary(batch_files, successful_batches, failed_batches, merged_file, overall_duration, pending_next_day_jobs)
            
            return len(failed_batches) == 0 and not pending_next_day_jobs
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            return False
    
    
    def _copy_step2_output_to_archive(self, batch_id):
        """Copy STEP 2 output (sections extraction) to archive folder for user review."""
        try:
            import shutil
            step2_source = Path(__file__).parent / "logs" / "extract_debug.json"
            if step2_source.exists():
                suffix = f"_batch_{batch_id:03d}" if batch_id else ""
                step2_dest = self.logs_folder / f"extract_debug{suffix}.json"
                shutil.copy(step2_source, step2_dest)
                print(f"[COPY] STEP 2 debug → {step2_dest.name}")
            else:
                print(f"[WARN] STEP 2 output not found: {step2_source}")
        except Exception as e:
            print(f"[WARN] Failed to copy STEP 2 output: {str(e)[:50]}")

    def _copy_step1_output_to_archive(self, destination_file):
        """Copy STEP 1 output (regex-cleaned jobs) into the clean archive folder."""
        try:
            import shutil

            step1_source = Path(__file__).parent / "logs" / "clean_step1_debug.json"
            if not step1_source.exists():
                return

            shutil.copy(step1_source, destination_file)
            print(f"[COPY] STEP 1 output → {destination_file.name}")

            step1_fallback_source = Path(__file__).parent / "fallback" / "clean_fallback.json"
            if step1_fallback_source.exists():
                fallback_dest_dir = self.fallback_folder
                fallback_dest_dir.mkdir(parents=True, exist_ok=True)
                fallback_dest_file = fallback_dest_dir / "clean_fallback.json"
                shutil.copy(step1_fallback_source, fallback_dest_file)
                print(f"[COPY] STEP 1 fallback → {fallback_dest_file.name}")
        except Exception as e:
            print(f"[WARN] Failed to copy STEP 1 output: {str(e)[:50]}")
    
    def _print_summary(self, all_batches, successful, failed, merged_file, duration, pending_next_day_jobs=None):
        """Print execution summary."""
        print(f"\n{'='*80}")
        print("FINAL SUMMARY")
        print(f"{'='*80}")
        print(f"Total batches:      {len(all_batches)}")
        print(f"✓ Successful:       {len(successful)}")
        print(f"✗ Failed:           {len(failed)}")
        
        if failed:
            failed_ids = []
            for batch_id, _, _ in all_batches:
                if batch_id in failed:
                    failed_ids.append(str(batch_id))
            print(f"  Failed batch IDs:  {', '.join(failed_ids)}")
        
        total_jobs = sum(count for _, _, count in all_batches)
        print(f"\nTotal jobs:         {total_jobs}")
        
        if merged_file:
            print(f"Output file:        {merged_file.name}")
        
        print(f"Step 2 preview:     logs/extract_debug.json (debug only)")

        if pending_next_day_jobs:
            print(f"Pending next day:   {len(pending_next_day_jobs)} jobs")
        
        # Show total API requests captured from subprocesses
        if self.total_api_calls > 0:
            print(f"\n📡 API Requests:     {self.total_api_calls} total (STEP 2: CLEAN DATA)")
        
        print(f"\n⏱️  Total Duration:    {duration}")
        print(f"{'='*80}\n")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                            CLI INTERFACE                                    ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch processor for daily job crawls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process crawl with auto-detected output folder
  python batch_process_daily.py data/crawl_20260330_114403/raw/jobs_combined.json
  
  # Process with custom batch size
  python batch_process_daily.py data/crawl_20260330_114403/raw/jobs_combined.json --batch 5
  
  # Process without merging (keep individual batches)
  python batch_process_daily.py data/crawl_20260330_114403/raw/jobs_combined.json --no-merge
        """
    )
    
    parser.add_argument('input_file', 
                       help='Path to jobs_combined.json in crawl folder')
    parser.add_argument('--batch', type=int, default=10,
                       help='Batch size (default: 10)')
    parser.add_argument('--no-merge', action='store_true',
                       help='Do not merge batch outputs')
    parser.add_argument('--max-jobs', type=int, default=None,
                       help='Only process first N jobs (useful for testing). Default: None (all jobs)')
    
    args = parser.parse_args()
    
    # Validate input
    if not Path(args.input_file).exists():
        print(f"❌ Error: File not found: {args.input_file}")
        sys.exit(1)
    
    # Run processor
    processor = DailyBatchProcessor(
        args.input_file,
        batch_size=args.batch,
        merge_output=not args.no_merge,
        max_jobs=args.max_jobs
    )
    
    success = processor.run()
    sys.exit(0 if success else 1)
