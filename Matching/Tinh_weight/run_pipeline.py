"""
PIPELINE ORCHESTRATOR - TEST vs REAL MODE
==========================================

Usage:
    python run_pipeline.py --mode test      (Run with sample data, output to Test/)
    python run_pipeline.py --mode real      (Run with real data, output to root)
    python run_pipeline.py                  (Default: test mode)

Two Modes:
----------
TEST MODE (--mode test):
  • Input: test_sample_jobs.json (10 jobs, 6 categories)
  • Intermediate outputs: Test/
  • Final output: Test/job_group_skill_weights.json
  • Use for: Development, debugging, validation

REAL MODE (--mode real):
  • Input: External data source (from DB or another system)
  • Intermediate outputs: Root folder (kept for reference)
  • Final output: Output_weight/job_group_skill_weights_YYYY-MM-DD.json
  • Use for: Production, weekly updates, actual deployment
  • Note: Requires jobs_from_db.json in Matching_CV/ folder

Output Folder Structure:
  Tinh_weight/
  ├── Test/                       (Test mode outputs)
  │   ├── jobs_grouped_by_keyword.json
  │   ├── category_rankings_by_keyword.json
  │   └── job_group_skill_weights.json
  │
  └── Output_weight/              (Real mode timestamped outputs)
      ├── job_group_skill_weights_2026-04-08.json
      ├── job_group_skill_weights_2026-04-15.json
      └── ... (one file per week/update)
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
import io
import os

# Load environment variables from .env file
def load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=VALUE
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key:
                            os.environ[key] = value
            print(f"[*] Loaded environment from .env")
            return True
        except Exception as e:
            print(f"[!] Error loading .env: {e}")
            return False
    return False

# Fix Windows console encoding issues
if sys.platform == 'win32':
    # Force UTF-8 for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def parse_mode():
    """Parse command line arguments."""
    mode = "test"  # default
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--mode", "-m"]:
            if len(sys.argv) > 2:
                mode = sys.argv[2].lower()
        elif sys.argv[1].lower() in ["test", "real"]:
            mode = sys.argv[1].lower()
    
    if mode not in ["test", "real"]:
        print(f"Error: Invalid mode: {mode}")
        print("   Use: --mode test  OR  --mode real")
        sys.exit(1)
    
    return mode

def setup_mode(mode):
    """Setup paths and environment based on mode."""
    base_path = Path(__file__).parent
    
    if mode == "test":
        return {
            "mode": "test",
            "input_data": base_path / "Test" / "test_sample_jobs.json",
            "output_dir": base_path / "Test",
            "use_sample_data": True,
            "description": "TEST MODE - Sample data (10 jobs)"
        }
    else:  # real
        return {
            "mode": "real",
            "input_data": base_path.parent / "Matching_CV" / "jobs_from_db.json",
            "output_dir": base_path / "Output_weight",
            "use_sample_data": False,
            "description": "REAL MODE - Production data from database"
        }

def print_header(mode_config):
    """Print startup header."""
    print("\n" + "="*80)
    print("[*] LLM-BASED AHP PIPELINE")
    print("="*80)
    print(f"\n[>] Mode: {mode_config['description']}")
    print(f"[>] Input: {mode_config['input_data'].name}")
    print(f"[>] Output: {mode_config['output_dir'].name}/")
    
    if mode_config['mode'] == 'real':
        timestamp = datetime.now().strftime("%Y-%m-%d")
        print(f"[>] Timestamp: {timestamp}")
    
    print("\n" + "="*80 + "\n")

def verify_input(mode_config):
    """Verify input file exists."""
    if not mode_config['input_data'].exists():
        print(f"[!] Input file not found: {mode_config['input_data']}")
        if mode_config['mode'] == 'real':
            print("    For REAL mode, ensure jobs_from_db.json exists in Matching_CV/")
        return False
    return True

def create_output_dir(mode_config):
    """Create output directory if needed."""
    mode_config['output_dir'].mkdir(exist_ok=True)
    return True

def run_scripts(mode_config):
    """Run the pipeline scripts."""
    base_path = Path(__file__).parent
    
    # For REAL mode, add Script 10 (fetch from database)
    if mode_config['mode'] == 'real':
        scripts = [
            "10_fetch_jobs_from_db.py",      # NEW: Fetch jobs from PostgreSQL
            "11_generate_training_data.py",
            "12_apply_llm_rankings.py",
            "13_aggregate_calculate_weights.py"
        ]
    else:
        # TEST mode: Use sample data
        scripts = [
            "11_generate_training_data.py",
            "12_apply_llm_rankings.py",
            "13_aggregate_calculate_weights.py"
        ]
    
    # Set environment variable for scripts to know the mode
    os.environ['PIPELINE_MODE'] = mode_config['mode']
    os.environ['PIPELINE_OUTPUT_DIR'] = str(mode_config['output_dir'])
    
    # Set input directory for test data
    if mode_config['mode'] == 'test':
        os.environ['PIPELINE_INPUT_DIR'] = str(Path(__file__).parent / 'Test')
    else:
        os.environ['PIPELINE_INPUT_DIR'] = str(Path(__file__).parent)
    
    for i, script in enumerate(scripts, 1):
        script_path = base_path / script
        
        if not script_path.exists():
            print(f"[!] Script not found: {script}")
            return False
        
        print(f"\n[{i}] Running {script}...")
        print("-" * 80)
        
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=base_path,
            capture_output=False
        )
        
        if result.returncode != 0:
            print(f"\n[!] Script failed: {script}")
            return False
    
    return True

def finalize_output(mode_config):
    """Handle final output for real mode (with timestamp)."""
    if mode_config['mode'] != 'real':
        return True
    
    output_dir = mode_config['output_dir']
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # Find job_group_skill_weights.json in root and copy to Output_weight with timestamp
    root_output = Path(__file__).parent / "job_group_skill_weights.json"
    if root_output.exists():
        timestamped_output = output_dir / f"job_group_skill_weights_{timestamp}.json"
        import shutil
        shutil.copy(root_output, timestamped_output)
        print(f"\n[!] Final output saved: {timestamped_output.name}")
        return True
    
    return False

def update_database(mode_config):
    """Update database with calculated weights (Real mode only)."""
    if mode_config['mode'] != 'real':
        return True
    
    base_path = Path(__file__).parent
    db_script = base_path / "14_update_database.py"
    
    if not db_script.exists():
        print("[!] Database update script not found: 14_update_database.py")
        return False
    
    print("\n" + "="*80)
    print("[4] Running 14_update_database.py...")
    print("-" * 80)
    
    result = subprocess.run(
        [sys.executable, str(db_script)],
        cwd=base_path,
        capture_output=False
    )
    
    if result.returncode != 0:
        print("\n[!] Database update failed")
        return False
    
    return True

def print_summary(mode_config, success):
    """Print final summary."""
    if success:
        print("\n" + "="*80)
        print("[OK] PIPELINE COMPLETED SUCCESSFULLY")
        print("="*80)
        
        output_dir = mode_config['output_dir']
        if output_dir.exists():
            files = list(output_dir.glob("*.json"))
            if files:
                print(f"\n[>] Output files ({len(files)}):")
                for f in sorted(files):
                    size_kb = f.stat().st_size / 1024
                    print(f"    * {f.name:50} ({size_kb:.1f} KB)")
        
        print("\n" + "="*80 + "\n")
    else:
        print("\n[!] PIPELINE FAILED\n")

def main():
    """Main orchestrator."""
    # Load environment variables from .env file if exists
    load_env_file()
    
    mode = parse_mode()
    mode_config = setup_mode(mode)
    
    print_header(mode_config)
    
    if not verify_input(mode_config):
        return False
    
    if not create_output_dir(mode_config):
        return False
    
    if not run_scripts(mode_config):
        return False
    
    if not finalize_output(mode_config):
        print("[*] Warning: Could not finalize output")
    
    # For REAL mode, update database with the calculated weights
    if mode_config['mode'] == 'real':
        if not update_database(mode_config):
            print("[!] Warning: Database update failed (but weights were calculated)")
            return False
    
    print_summary(mode_config, True)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
