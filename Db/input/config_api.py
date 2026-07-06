"""
🔑 API Key Configuration
========================
Quản lý API keys dễ dàng - thêm key mới vào .env là được, tự động load + rotate

Load từ .env file
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading

# Load .env
ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_FILE)

# ============================================================================
# 🔄 TỰ ĐỘNG LOAD KEYS TỪ .ENV
# ============================================================================
# Cách thêm key mới:
# 1. Mở file .env
# 2. Thêm dòng: GEMINI_API_KEY_4=key_value_mới
# 3. Done! Config tự động detect và load
#
# Không cần edit file config_api.py!

def _load_api_keys():
    """Tự động scan .env để tìm tất cả GEMINI_API_KEY_X, kể cả khi bị hổng số."""
    api_keys = {}
    matched_keys = []

    # Support unsuffixed GEMINI_API_KEY as the primary key
    unsuffixed = os.environ.get("GEMINI_API_KEY")
    if unsuffixed:
        matched_keys.append((0, "GEMINI_API_KEY", unsuffixed))

    for env_name, env_value in os.environ.items():
        match = re.fullmatch(r"GEMINI_API_KEY_(\d+)", env_name)
        if not match or not env_value:
            continue
        matched_keys.append((int(match.group(1)), env_name, env_value))

    matched_keys.sort(key=lambda item: item[0])

    if matched_keys:
        api_keys["gemini"] = []
        for index, (key_number, key_name, key_value) in enumerate(matched_keys):
            api_keys["gemini"].append({
                "value": key_value,
                "env_name": key_name,
                "index": index,
                "status": "active",      # active, cooldown
                "cooldown_until": None,  # datetime object
                "error_count": 0,        # Số lần lỗi
                "last_request": None,    # datetime of last request made with this key
            })
    
    return api_keys


API_KEYS = _load_api_keys()

# ============================================================================
# 🎯 ACTIVE KEY SELECTION + AUTO-ROTATION
# ============================================================================
class KeyRotationManager:
    """Quản lý rotation tự động khi key hết quota"""
    
    def __init__(self, api_keys):
        self.api_keys = api_keys
        self.current_index = int(os.getenv("CURRENT_API_KEY_INDEX", "0"))
        self.cooldown_duration = int(os.getenv("API_KEY_COOLDOWN_MINUTES", "15"))
        # Minimum interval in seconds between consecutive requests using the same key
        self.min_interval_seconds = int(os.getenv("API_KEY_MIN_INTERVAL_SECONDS", "15"))
        self._lock = threading.Lock()
    
    def get_active_key(self, provider="gemini"):
        """Lấy API key hiện tại - tự động skip key cooldown"""
        if provider not in self.api_keys or len(self.api_keys[provider]) == 0:
            return None
        keys = self.api_keys[provider]
        max_attempts = len(keys)
        attempts = 0

        now = datetime.now()
        # Use a lock to prevent race conditions when multiple threads request keys
        with self._lock:
            # Try each key in round-robin starting from current_index
            while attempts < max_attempts:
                index = self.current_index % len(keys)
                key_info = keys[index]

                # Skip keys explicitly in cooldown
                if key_info["status"] == "cooldown" and key_info["cooldown_until"]:
                    if now < key_info["cooldown_until"]:
                        self.current_index += 1
                        attempts += 1
                        continue
                    else:
                        # Cooldown expired
                        key_info["status"] = "active"
                        key_info["cooldown_until"] = None
                        key_info["error_count"] = 0

                # Enforce minimum interval between uses of the same key
                last_req = key_info.get("last_request")
                if last_req and (now - last_req).total_seconds() < self.min_interval_seconds:
                    # Too recent, try next key
                    self.current_index += 1
                    attempts += 1
                    continue

                # Mark this key as used now
                key_info["last_request"] = now
                # Return active key value
                return key_info["value"]

            # If no key satisfies the min-interval/cooldown, return None to signal no key available
            return None
    
    def on_quota_error(self, provider="gemini"):
        """Gọi khi API trả về error quota/rate-limit"""
        if provider not in self.api_keys or len(self.api_keys[provider]) == 0:
            return
        
        keys = self.api_keys[provider]
        current_key = keys[self.current_index % len(keys)]
        
        # Mark key as cooldown
        current_key["status"] = "cooldown"
        current_key["error_count"] += 1
        current_key["cooldown_until"] = datetime.now() + timedelta(minutes=self.cooldown_duration)
        # reset last_request so it won't be treated as recently used after cooldown
        current_key["last_request"] = None
        
        print(f"\n[WARNING] API Key quota exceeded!")
        print(f"   Key: {current_key['env_name']}")
        print(f"   Cooldown until: {current_key['cooldown_until'].strftime('%H:%M:%S')}")
        
        # Rotate to next key
        self.current_index += 1
        next_key = self.get_active_key(provider)
        
        if next_key:
            next_env = "unknown"
            for k in self.api_keys.get(provider, []):
                if k["value"] == next_key:
                    next_env = k["env_name"]
                    break
            print(f"[SUCCESS] Switched to next key: {next_env}")
        else:
            print(f"[ERROR] No active keys available!")
    
    def get_all_keys(self, provider="gemini"):
        """Lấy tất cả keys (không filter)"""
        return [k["value"] for k in self.api_keys.get(provider, [])]
    
    def get_status(self, provider="gemini"):
        """Get status của tất cả keys"""
        if provider not in self.api_keys:
            return {}
        
        status = {}
        for k in self.api_keys[provider]:
            cooldown_str = "cooldown" if k["status"] == "cooldown" else "active"
            if k["cooldown_until"]:
                cooldown_str += f" (until {k['cooldown_until'].strftime('%H:%M:%S')})"
            status[k["env_name"]] = {
                "status": cooldown_str,
                "error_count": k["error_count"],
            }
        return status


key_manager = KeyRotationManager(API_KEYS)

def get_api_key(provider="gemini"):
    """Lấy API key hiện tại cho provider - tự động skip cooldown"""
    return key_manager.get_active_key(provider)

def get_all_api_keys(provider="gemini"):
    """Lấy tất cả API keys cho provider"""
    return key_manager.get_all_keys(provider)

def on_api_quota_error(provider="gemini"):
    """Gọi function này khi API trả về quota/rate-limit error - tự động rotate key"""
    key_manager.on_quota_error(provider)

def get_api_key_info(provider="gemini"):
    key = key_manager.get_active_key(provider)
    if not key:
        return None, None

    for k in API_KEYS.get(provider, []):
        if k["value"] == key:
            masked = k["value"][:8] + "..." + k["value"][-4:]
            return key, f"{k['env_name']} ({masked})"

    return key, "unknown_key"

# ============================================================================
# 🔧 MODEL CONFIG
# ============================================================================
GEMINI_CONFIG = {
    "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "api_key": get_api_key("gemini"),
    "rpm": int(os.getenv("GEMINI_RPM", "5")),
    "rpd": int(os.getenv("GEMINI_RPD", "20")),
    "tpm": int(os.getenv("GEMINI_TPM", "250000")),
}


# ============================================================================
# 📊 STATUS & DEBUG
# ============================================================================
def print_api_status():
    """In trạng thái API keys"""
    print("\n" + "="*70)
    print("API KEY STATUS")
    print("="*70)
    
    print(f"\nAvailable Keys:")
    gemini_keys = API_KEYS.get("gemini", [])
    if gemini_keys:
        for i, key_info in enumerate(gemini_keys):
            key_display = key_info["value"][:20] + "..." if len(key_info["value"]) > 20 else key_info["value"]
            status = key_info["status"]
            
            # Add cooldown time if applicable
            status_display = status.upper()
            if key_info["cooldown_until"] and status == "cooldown":
                time_remaining = key_info["cooldown_until"] - datetime.now()
                minutes = int(time_remaining.total_seconds() / 60)
                status_display = f"COOLDOWN ({minutes}m remaining)"
            
            marker = " <- Current" if i == (key_manager.current_index % len(gemini_keys)) else ""
            print(f"  [{i}] {key_info['env_name']}: {key_display} [{status_display}]{marker}")
    else:
        print("  [ERROR] No GEMINI_API_KEY_X found in .env")
    
    print(f"\nStatus:")
    print(f"  Total keys: {len(gemini_keys)}")
    print(f"  Active key index: {key_manager.current_index % len(gemini_keys) if gemini_keys else 'N/A'}")
    print(f"  Model: {GEMINI_CONFIG['model']}")
    # Show current key env name without triggering key selection side-effects
    if gemini_keys:
        active_env = gemini_keys[key_manager.current_index % len(gemini_keys)]["env_name"]
        print(f"  Active key: {active_env}")
    else:
        print("  Active key: NOT SET")
    
    # Key stats
    status_dict = key_manager.get_status("gemini")
    if status_dict:
        print(f"\nKey Statistics:")
        for key_name, info in status_dict.items():
            print(f"  {key_name}: {info['status']} (errors: {info['error_count']})")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    print_api_status()
