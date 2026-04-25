#!/usr/bin/env python3
"""
Check API Quota Usage:
- Show requests already used
- Show estimate remaining
- Show which keys are exhausted
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gemini_request_options import build_request_options

# Load .env
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ Loaded .env from: {env_path}\n")

# Load quota audit
QUOTA_LOG = Path(__file__).parent / "quota_audit.json"
DAILY_LIMIT = 1500  # Gemini RPD limit per key

def load_quota_audit():
    """Load quota tracking data"""
    if QUOTA_LOG.exists():
        try:
            with open(QUOTA_LOG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    return None

def test_api_key(key_value, key_name):
    """Test single API key by making a tiny API call"""
    try:
        genai.configure(api_key=key_value)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Minimal request to test quota
        response = model.generate_content(
            "Say 'OK'",
            generation_config=genai.types.GenerationConfig(
                temperature=1.0,
                max_output_tokens=10,
            ),
            request_options=build_request_options(),
        )
        
        # If we get here, key is working
        return True, "✅ WORKING", None
    
    except Exception as e:
        error_msg = str(e).lower()
        
        if '429' in error_msg or 'quota' in error_msg or 'exceeded' in error_msg:
            return False, "❌ QUOTA EXHAUSTED (429)", str(e)
        elif '403' in error_msg or 'permission' in error_msg:
            return False, "❌ INVALID/FORBIDDEN", str(e)
        else:
            return False, f"⚠️  ERROR", str(e)

def main():
    print("\n" + "="*80)
    print("📊 API QUOTA USAGE REPORT")
    print("="*80)
    
    # Load tracked quota
    quota_data = load_quota_audit()
    
    if not quota_data:
        print("\n⏳ No quota tracking data yet (run some tests first)")
        print("\nUsage instructions:")
        print("  1. Run tests or processing")
        print("  2. Re-run this command to see quota used")
        return
    
    keys_data = quota_data.get("keys", {})
    
    # Calculate stats
    total_requests = sum(k.get("requests", 0) for k in keys_data.values())
    total_errors = sum(k.get("errors", 0) for k in keys_data.values())
    active_keys = sum(1 for k in keys_data.values() if k.get("status") == "ACTIVE")
    exhausted_keys = sum(1 for k in keys_data.values() if k.get("status") == "EXHAUSTED")
    
    # Estimate remaining
    avg_per_key = total_requests / max(len(keys_data), 1)
    remaining_per_key = DAILY_LIMIT - avg_per_key
    total_remaining = remaining_per_key * active_keys
    
    # Print summary
    print(f"\n📈 SUMMARY")
    print(f"{'─'*80}")
    print(f"  Total requests: {total_requests}")
    print(f"  Total errors: {total_errors}")
    print(f"  Active keys: {active_keys}")
    print(f"  Exhausted keys: {exhausted_keys}")
    print()
    print(f"  Avg per key: {avg_per_key:.0f} requests")
    print(f"  Est. remaining per key: {remaining_per_key:.0f} / {DAILY_LIMIT}")
    print(f"  Est. total remaining: {total_remaining:.0f} calls")
    
    # Show key details
    print(f"\n🔑 KEY STATUS")
    print(f"{'─'*80}")
    
    # Group by status
    active_list = []
    exhausted_list = []
    
    for key_name in sorted(keys_data.keys()):
        info = keys_data[key_name]
        reqs = info.get("requests", 0)
        status = info.get("status", "ACTIVE")
        
        if status == "ACTIVE":
            active_list.append((key_name, reqs))
        else:
            exhausted_list.append((key_name, reqs))
    
    # Show active keys
    if active_list:
        print(f"\n✅ ACTIVE ({len(active_list)} keys)")
        for key_name, reqs in active_list[:5]:  # Show first 5
            print(f"  {key_name}: {reqs} requests used")
        if len(active_list) > 5:
            print(f"  ... and {len(active_list) - 5} more")
    
    # Show exhausted keys
    if exhausted_list:
        print(f"\n❌ EXHAUSTED ({len(exhausted_list)} keys - don't use)")
        for key_name, reqs in exhausted_list:
            print(f"  {key_name}: {reqs} requests (LIMIT REACHED)")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS")
    print(f"{'─'*80}")
    if exhausted_list:
        print(f"⚠️  {len(exhausted_list)} keys exhausted!")
        print(f"  → Use active keys instead (system auto-rotates on error)")
    else:
        print(f"✅ All keys still have quota available")
    
    if total_requests > 0:
        print(f"  → Estimated capacity remaining: {total_remaining:.0f} API calls")
    
    print()
    print("="*80)
    print()

if __name__ == "__main__":
    main()
