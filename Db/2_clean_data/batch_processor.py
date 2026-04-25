#!/usr/bin/env python3
"""
BATCH PROCESSOR - Xử lý file lớn (~100 jobs) theo lô (batch size: 10 jobs)
- Split input file thành nhiều lô
- Chạy clean_process.py từng lô  
- Merge kết quả thành 1 file
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

def split_into_batches(jobs, batch_size=10):
    """Chia jobs thành các lô"""
    batches = []
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i+batch_size]
        batches.append(batch)
    return batches

def save_batch(batch, batch_num, output_dir="input"):
    """Lưu 1 lô vào file JSON"""
    Path(output_dir).mkdir(exist_ok=True)
    filename = f"{output_dir}/batch_{batch_num:03d}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)
    return filename

def load_jobs(input_file):
    """Load jobs từ file"""
    with open(input_file, encoding='utf-8') as f:
        jobs = json.load(f)
    if not isinstance(jobs, list):
        jobs = [jobs]
    return jobs

def merge_results(batch_results, output_file="output/merged_output.json"):
    """Merge kết quả từ tất cả các lô"""
    Path(output_file).parent.mkdir(exist_ok=True)
    
    merged = []
    for result_file in batch_results:
        if os.path.exists(result_file):
            with open(result_file, encoding='utf-8') as f:
                batch_data = json.load(f)
                if isinstance(batch_data, list):
                    merged.extend(batch_data)
                else:
                    merged.append(batch_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    
    return output_file

def main():
    parser = argparse.ArgumentParser(
        description='Batch processor for large job files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
EXAMPLES:
  # Split file into batches
  python batch_processor.py input/jobs_combined.json --split --batch-size 10
  
  # Process all batches (run this after split)
  python batch_processor.py --process-all
  
  # Merge results
  python batch_processor.py --merge
  
  # Full workflow (split + process + merge)
  python batch_processor.py input/jobs_combined.json --full --batch-size 10
        '''
    )
    
    parser.add_argument('input_file', nargs='?', help='Input job file')
    parser.add_argument('--split', action='store_true', help='Split into batches only')
    parser.add_argument('--process-all', action='store_true', help='Process all batches')
    parser.add_argument('--merge', action='store_true', help='Merge results')
    parser.add_argument('--full', action='store_true', help='Full workflow')
    parser.add_argument('--batch-size', type=int, default=10, help='Batch size (default: 10)')
    parser.add_argument('--batch-dir', default='input', help='Directory for batch files')
    
    args = parser.parse_args()
    
    # ===== SPLIT MODE =====
    if args.split and args.input_file:
        print(f"📦 Loading jobs từ {args.input_file}...")
        jobs = load_jobs(args.input_file)
        total_jobs = len(jobs)
        print(f"✓ Loaded {total_jobs} jobs")
        
        batches = split_into_batches(jobs, args.batch_size)
        print(f"\n📂 Splitting thành {len(batches)} lô (batch size: {args.batch_size})...\n")
        
        batch_files = []
        for i, batch in enumerate(batches, 1):
            batch_file = save_batch(batch, i, args.batch_dir)
            batch_files.append(batch_file)
            print(f"   Batch {i:3d}: {batch_file} ({len(batch)} jobs)")
        
        print(f"\n✓ Split complete! {len(batch_files)} batch files created")
        print("\n📝 Next steps:")
        print("   1. Run each batch: python clean_process.py input/batch_001.json --output output/batch_001_output.json")
        print("   2. Or use --process-all to run all batches")
        
    # ===== PROCESS ALL MODE =====
    elif args.process_all:
        import subprocess
        import glob
        
        batch_files = sorted(glob.glob(f"{args.batch_dir}/batch_*.json"))
        if not batch_files:
            print(f"❌ No batch files found in {args.batch_dir}")
            sys.exit(1)
        
        print(f"🔄 Processing {len(batch_files)} batches...\n")
        
        output_files = []
        for i, batch_file in enumerate(batch_files, 1):
            output_file = f"output/{Path(batch_file).stem}_output.json"
            print(f"[{i}/{len(batch_files)}] Processing {batch_file} -> {output_file}")
            
            cmd = f"python clean_process.py {batch_file} --output {output_file}"
            result = subprocess.run(cmd, shell=True)
            
            if result.returncode == 0:
                output_files.append(output_file)
                print(f"✓ Done\n")
            else:
                print(f"❌ Error processing {batch_file}\n")
        
        print(f"✓ All batches processed! {len(output_files)} files created")
        
    # ===== MERGE MODE =====
    elif args.merge:
        import glob
        
        output_files = sorted(glob.glob("output/batch_*_output.json"))
        if not output_files:
            print("❌ No batch output files found")
            sys.exit(1)
        
        print(f"🔀 Merging {len(output_files)} batch outputs...\n")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_file = f"output/merged_clean_data_{timestamp}.json"
        
        result = merge_results(output_files, merged_file)
        print(f"✓ Merged to: {merged_file}")
        
        # Count total jobs
        with open(merged_file) as f:
            merged_data = json.load(f)
        total = len(merged_data) if isinstance(merged_data, list) else 1
        print(f"  Total jobs: {total}")
    
    # ===== FULL WORKFLOW =====
    elif args.full and args.input_file:
        import subprocess
        import glob
        
        # Step 1: Split
        print("=" * 70)
        print("STEP 1: SPLIT INTO BATCHES")
        print("=" * 70)
        jobs = load_jobs(args.input_file)
        total_jobs = len(jobs)
        print(f"✓ Loaded {total_jobs} jobs")
        
        batches = split_into_batches(jobs, args.batch_size)
        print(f"✓ Split thành {len(batches)} lô\n")
        
        for i, batch in enumerate(batches, 1):
            save_batch(batch, i, args.batch_dir)
        
        # Step 2: Process all
        print("=" * 70)
        print("STEP 2: PROCESS ALL BATCHES")
        print("=" * 70)
        batch_files = sorted(glob.glob(f"{args.batch_dir}/batch_*.json"))
        
        for i, batch_file in enumerate(batch_files, 1):
            output_file = f"output/{Path(batch_file).stem}_output.json"
            print(f"\n[{i}/{len(batch_files)}] {batch_file}")
            cmd = f"python clean_process.py {batch_file} --output {output_file}"
            subprocess.run(cmd, shell=True)
        
        # Step 3: Merge
        print("\n" + "=" * 70)
        print("STEP 3: MERGE RESULTS")
        print("=" * 70)
        output_files = sorted(glob.glob("output/batch_*_output.json"))
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_file = f"output/merged_clean_data_{timestamp}.json"
        
        result = merge_results(output_files, merged_file)
        print(f"✓ Final merged file: {merged_file}")
        
        with open(merged_file) as f:
            data = json.load(f)
        total = len(data) if isinstance(data, list) else 1
        print(f"✓ Total jobs: {total}")
        
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
