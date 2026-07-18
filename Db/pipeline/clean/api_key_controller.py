from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class APIKeyController:
    """Quota-aware API key pool manager compatible with legacy interface.

    Enhances the previous controller with per-key RPM windows, backoff, and
    counters. Keeps old methods (`get_next_available_key`, `get_next_key`,
    `record_request_attempt`, `mark_exhausted`, `mark_temporary_error`,
    `has_active_keys`) for backward compatibility and adds new helpers used by
    the pipeline: `acquire_key`, `mark_success`, `mark_429`,
    `mark_5xx_or_timeout`, `mark_daily_exhausted`, `has_any_future_available_key`,
    and `stats`.
    """

    def __init__(self, provider: str = "gemini", state_file: Path | str = None, max_requests_per_day: int = 20):
        from Db.llm.llm_config import LLM_RPM_PER_KEY

        self.provider = provider
        self.state_file = Path(state_file) if state_file is not None else Path(__file__).parent.parent / "2_clean_data" / "cache" / "api_key_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.max_requests_per_day = int(max_requests_per_day)
        self.rpm_per_key = int(LLM_RPM_PER_KEY)
        self._lock = threading.Lock()
        self._state: Dict = {"keys": [], "cursor": 0}
        self._discover_env_keys()
        self._load_or_init_state()

    # --------- State shape helpers ---------
    def _discover_env_keys(self) -> None:
        """Find available environment API key names for this provider.

        We do not store values in the state file; we only store the env var names
        (e.g., GEMINI_API_KEY_1) as `key_id`.
        """
        prefix = os.getenv("GEMINI_KEY_PREFIX", "GEMINI_API_KEY_")
        keys = []
        for name, val in os.environ.items():
            if name.startswith(prefix) and val:
                keys.append(name)
        # sort by numeric suffix when possible
        def _key_sort(k: str):
            try:
                return int(k.rsplit("_", 1)[1])
            except Exception:
                return k

        keys.sort(key=_key_sort)
        self._env_key_ids = keys

    def _load_or_init_state(self) -> None:
        today = date.today().isoformat()
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self._state = json.load(f) or {"keys": [], "cursor": 0}
            except Exception:
                self._state = {"keys": [], "cursor": 0}

        # Migrate env_name to key_id for backward compatibility
        for k in self._state.get('keys', []):
            if 'key_id' not in k and 'env_name' in k:
                k['key_id'] = k['env_name']

        # Ensure all discovered env keys exist in state (add missing)
        existing = {k['key_id']: k for k in self._state.get('keys', []) if k.get('key_id')}
        for idx, kid in enumerate(self._env_key_ids):
            if kid not in existing:
                entry = {
                    "index": idx,
                    "key_id": kid,
                    "provider": self.provider,
                    "is_active": True,
                    "last_activated_date": today,
                    "request_count_today": 0,
                    "max_requests_per_day": self.max_requests_per_day,
                    "last_error": None,
                    "last_error_at": None,
                    "exhausted_today": False,
                    # RPM/window tracking
                    "window_started_at": None,
                    "used_in_window": 0,
                    "rpm_limit": int(self.rpm_per_key),
                    # scheduling
                    "next_available_at": None,
                    "disabled_until": None,
                    # error counters
                    "consecutive_errors": 0,
                    "total_success": 0,
                    "total_failed": 0,
                    "total_429": 0,
                    "total_5xx": 0,
                }
                self._state.setdefault('keys', []).append(entry)
            else:
                # Ensure existing keys have all required default fields
                k = existing[kid]
                k.setdefault("provider", self.provider)
                k.setdefault("is_active", True)
                k.setdefault("last_activated_date", today)
                k.setdefault("request_count_today", 0)
                k.setdefault("max_requests_per_day", self.max_requests_per_day)
                k.setdefault("last_error", None)
                k.setdefault("last_error_at", None)
                k.setdefault("exhausted_today", False)
                k.setdefault("window_started_at", None)
                k.setdefault("used_in_window", 0)
                k.setdefault("rpm_limit", int(self.rpm_per_key))
                k.setdefault("next_available_at", None)
                k.setdefault("disabled_until", None)
                k.setdefault("consecutive_errors", 0)
                k.setdefault("total_success", 0)
                k.setdefault("total_failed", 0)
                k.setdefault("total_429", 0)
                k.setdefault("total_5xx", 0)

        # Remove keys that no longer exist in env
        self._state['keys'] = [k for k in self._state.get('keys', []) if k.get('key_id') in self._env_key_ids]

        # Ensure every key entry has a stable numeric `index` (enumerate by list position).
        # This avoids legacy state files missing `index` which would cause acquire_key()
        # to return the fallback 0 for many keys.
        for idx, k in enumerate(self._state.get('keys', [])):
            try:
                k['index'] = int(idx)
            except Exception:
                k['index'] = idx

        # Ensure cursor sane
        if 'cursor' not in self._state:
            self._state['cursor'] = 0

        # Daily reset if needed
        self.reset_daily_if_needed()
        # Persist normalized state (including assigned indexes)
        self._save_state()

    def _save_state(self) -> None:
        try:
            with self._lock:
                with open(self.state_file, 'w', encoding='utf-8') as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --------- Public API ---------
    def reset_daily_if_needed(self) -> None:
        today = date.today().isoformat()
        changed = False
        for k in self._state.get('keys', []):
            if k.get('last_activated_date') != today:
                k.update({
                    'is_active': True,
                    'request_count_today': 0,
                    'last_activated_date': today,
                    'exhausted_today': False,
                    'last_error': None,
                    'last_error_at': None,
                    'last_request_at': None,
                    'request_timestamps': [],
                })
                changed = True
        if changed:
            self._save_state()

    # RPM helpers
    def _prune_old_timestamps(self, k: Dict, window_seconds: int = 60) -> None:
        # legacy helper kept for compatibility (not used in new acquire flow)
        now = datetime.utcnow()
        kept = []
        for ts in k.get('request_timestamps', []) or []:
            try:
                t = datetime.fromisoformat(ts)
            except Exception:
                continue
            if (now - t).total_seconds() <= window_seconds:
                kept.append(ts)
        k['request_timestamps'] = kept

    def _ensure_window(self, k: Dict, window_seconds: int = 60) -> None:
        """Ensure the per-key window is initialized and reset when expired."""
        now = datetime.utcnow()
        started = None
        if k.get('window_started_at'):
            try:
                started = datetime.fromisoformat(k.get('window_started_at'))
            except Exception:
                started = None

        if not started or (now - started).total_seconds() >= window_seconds:
            k['window_started_at'] = now.isoformat()
            k['used_in_window'] = 0

    def can_request_now(self, k: Dict, max_per_minute: int = 4, window_seconds: int = 60) -> bool:
        # Check per-key used_in_window count
        try:
            self._ensure_window(k, window_seconds=window_seconds)
            return int(k.get('used_in_window', 0)) < int(k.get('rpm_limit', max_per_minute))
        except Exception:
            return False

    def seconds_until_available(self, k: Dict, max_per_minute: int = 4, window_seconds: int = 60) -> float:
        try:
            self._ensure_window(k, window_seconds=window_seconds)
            used = int(k.get('used_in_window', 0))
            limit = int(k.get('rpm_limit', max_per_minute))
            if used < limit:
                return 0.0
            # wait until window expires
            try:
                started = datetime.fromisoformat(k.get('window_started_at'))
                elapsed = (datetime.utcnow() - started).total_seconds()
                return max(0.0, window_seconds - elapsed)
            except Exception:
                return 0.0
        except Exception:
            return 0.0

    # --------- New quota-aware methods ---------
    def acquire_key(self, wait: bool = True, max_wait: int = 300, exclude_key_indexes: Optional[List[int]] = None) -> Optional[Tuple[int, str, str]]:
        """Return tuple (index, key_id, api_key_value) for a key that can be used now.

        Applies per-key rpm, next_available_at, disabled_until, and daily_exhausted.
        """
        now = datetime.utcnow()
        keys = self._state.get('keys', [])
        if not keys:
            return None

        exclude_set = set(exclude_key_indexes or [])
        candidates = []
        waits = []
        for k in keys:
            # skip removed keys
            if not k.get('key_id'):
                continue
            if int(k.get('index', -1)) in exclude_set:
                continue
            if k.get('exhausted_today'):
                continue
            # disabled_until
            if k.get('disabled_until'):
                try:
                    if datetime.fromisoformat(k.get('disabled_until')) > now:
                        # skip
                        continue
                    else:
                        k['disabled_until'] = None
                except Exception:
                    k['disabled_until'] = None

            # next_available_at
            if k.get('next_available_at'):
                try:
                    if datetime.fromisoformat(k.get('next_available_at')) > now:
                        # compute wait
                        waits.append((k, (datetime.fromisoformat(k.get('next_available_at')) - now).total_seconds()))
                        continue
                    else:
                        k['next_available_at'] = None
                except Exception:
                    k['next_available_at'] = None

            # per-window rpm check
            if self.can_request_now(k, max_per_minute=self.rpm_per_key, window_seconds=60):
                candidates.append(k)
            else:
                waits.append((k, self.seconds_until_available(k, max_per_minute=self.rpm_per_key, window_seconds=60)))

        if candidates:
            # simple round-robin using cursor but prefer lower used counts
            candidates.sort(key=lambda x: int(x.get('used_in_window', 0)))
            chosen = candidates[0]
            # update cursor for compatibility
            try:
                idx = int(chosen.get('index', 0))
                self._state['cursor'] = (idx + 1) % max(1, len(self._state.get('keys', [])))
            except Exception:
                pass
            # === FIX: Optimistic increment used_in_window IMMEDIATELY ===
            # This prevents multiple concurrent workers from all acquiring the
            # same key (race condition: all see used_in_window=0 simultaneously).
            # mark_success() will also increment it later, which is acceptable
            # since _ensure_window() resets the window every 60s anyway.
            try:
                chosen['used_in_window'] = int(chosen.get('used_in_window', 0)) + 1
            except Exception:
                pass
            self._save_state()
            api_val = os.getenv(chosen.get('key_id'))
            return (int(chosen.get('index', 0)), chosen.get('key_id'), api_val)

        # no immediate candidate
        if wait and waits:
            shortest = min(w[1] for w in waits)
            if shortest > max_wait:
                return None
            import time
            time.sleep(shortest)
            # try once more
            return self.acquire_key(wait=False)

        return None

    def has_any_future_available_key(self) -> bool:
        now = datetime.utcnow()
        for k in self._state.get('keys', []):
            if k.get('exhausted_today'):
                continue
            if k.get('disabled_until'):
                try:
                    if datetime.fromisoformat(k.get('disabled_until')) > now:
                        continue
                except Exception:
                    pass
            # next_available_at may be in future
            return True
        return False

    def has_available_key_now(self) -> bool:
        """Return True if any key can be used immediately (respecting rpm and scheduling)."""
        now = datetime.utcnow()
        for k in self._state.get('keys', []):
            if k.get('exhausted_today'):
                continue
            if k.get('disabled_until'):
                try:
                    if datetime.fromisoformat(k.get('disabled_until')) > now:
                        continue
                except Exception:
                    pass
            if k.get('next_available_at'):
                try:
                    if datetime.fromisoformat(k.get('next_available_at')) > now:
                        continue
                except Exception:
                    pass
            if self.can_request_now(k, max_per_minute=self.rpm_per_key, window_seconds=60):
                return True
        return False

    def mark_success(self, key_index_or_id: int | str) -> None:
        """Record a successful request for the key and reset consecutive errors."""
        now = datetime.utcnow().isoformat()
        
        target_idx = None
        if isinstance(key_index_or_id, int):
            target_idx = key_index_or_id
        elif isinstance(key_index_or_id, str):
            try:
                target_idx = int(key_index_or_id)
            except ValueError:
                pass

        for k in self._state.get('keys', []):
            is_match = False
            if target_idx is not None and int(k.get('index', -1)) == target_idx:
                is_match = True
            elif k.get('key_id') == key_index_or_id:
                is_match = True

            if is_match:
                k['consecutive_errors'] = 0
                k['total_success'] = int(k.get('total_success', 0)) + 1
                k['last_error'] = None
                k['last_error_at'] = None
                k['last_request_at'] = now
                # increment daily counter
                k['request_count_today'] = int(k.get('request_count_today', 0)) + 1
                # increment used_in_window
                try:
                    k['used_in_window'] = int(k.get('used_in_window', 0)) + 1
                except Exception:
                    k['used_in_window'] = 1
                # mark exhausted if daily reached
                if int(k.get('request_count_today', 0)) >= int(k.get('max_requests_per_day', self.max_requests_per_day)):
                    k['is_active'] = False
                    k['exhausted_today'] = True
                self._save_state()
                return

    def mark_daily_exhausted(self, key_id: str) -> None:
        return self.mark_exhausted(key_id)

    def stats(self) -> Dict:
        s = { 'keys': [], 'total_keys': 0 }
        for k in self._state.get('keys', []):
            s['keys'].append({
                'index': int(k.get('index', 0)),
                'key_id': k.get('key_id'),
                'request_count_today': int(k.get('request_count_today', 0)),
                'used_in_window': int(k.get('used_in_window', 0)),
                'rpm_limit': int(k.get('rpm_limit', 0)),
                'exhausted_today': bool(k.get('exhausted_today', False)),
                'disabled_until': k.get('disabled_until'),
                'next_available_at': k.get('next_available_at'),
            })
        s['total_keys'] = len(self._state.get('keys', []))
        return s

    def record_request_attempt(self, key_id: str, now_iso: Optional[str] = None, max_per_minute: int = 4, window_seconds: int = 60) -> None:
        now = datetime.utcnow()
        now_s = now_iso or now.isoformat()
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                # increment daily counter
                k['request_count_today'] = int(k.get('request_count_today', 0)) + 1
                k['last_request_at'] = now_s
                # append timestamp and prune
                arr = k.get('request_timestamps') or []
                arr.append(now_s)
                k['request_timestamps'] = arr
                self._prune_old_timestamps(k, window_seconds=window_seconds)
                # if daily exceeded, mark exhausted
                if int(k.get('request_count_today', 0)) >= int(k.get('max_requests_per_day', self.max_requests_per_day)):
                    k['is_active'] = False
                    k['exhausted_today'] = True
                self._save_state()
                return

    def get_next_available_key(self, max_per_minute: int = 4, window_seconds: int = 60, wait: bool = True, max_wait: int = 300) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """Return (api_val, key_id) for an available key.

        If all keys are RPM-limited and wait=True, sleep until the earliest becomes available (up to max_wait seconds).
        If no active keys remain, return None.
        """
        keys = self._state.get('keys', [])
        if not keys:
            return None

        # First, filter out daily-exhausted/inactive keys
        candidates = []
        for k in keys:
            if not k.get('is_active'):
                continue
            if k.get('exhausted_today'):
                continue
            if int(k.get('request_count_today', 0)) >= int(k.get('max_requests_per_day', self.max_requests_per_day)):
                # mark exhausted
                k['is_active'] = False
                k['exhausted_today'] = True
                continue
            candidates.append(k)

        if not candidates:
            return None

        # Check immediate availability
        avail = []
        waits = []
        for k in candidates:
            if self.can_request_now(k, max_per_minute=max_per_minute, window_seconds=window_seconds):
                avail.append(k)
            else:
                waits.append(self.seconds_until_available(k, max_per_minute=max_per_minute, window_seconds=window_seconds))

        if avail:
            # simple round-robin among avail based on cursor
            n = len(keys)
            start = int(self._state.get('cursor', 0) or 0) % n
            for offset in range(n):
                idx = (start + offset) % n
                k = keys[idx]
                if k in avail:
                    self._state['cursor'] = (idx + 1) % n
                    self._save_state()
                    api_val = os.getenv(k.get('key_id'))
                    print(f"[APIKEY] Selected key {k.get('key_id')} (daily={k.get('request_count_today')}, rpm_window={len(k.get('request_timestamps') or [])})")
                    return (api_val, k.get('key_id'))

        # No immediate avail. If wait requested, compute shortest wait and sleep
        if wait and waits:
            shortest = min(waits)
            if shortest > max_wait:
                return None
            print(f"[APIKEY] All keys RPM-limited. Waiting {shortest:.1f}s for availability...")
            import time
            time.sleep(shortest)
            # after wait, retry once (no infinite loop)
            return self.get_next_available_key(max_per_minute=max_per_minute, window_seconds=window_seconds, wait=False)

        return None

    def get_next_key(self) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """Return tuple (api_key_value, key_id) for next active key, or None if none available."""
        keys = self._state.get('keys', [])
        if not keys:
            return None

        n = len(keys)
        start = int(self._state.get('cursor', 0) or 0) % n
        for offset in range(n):
            idx = (start + offset) % n
            k = keys[idx]
            if not k.get('is_active'):
                continue
            if k.get('exhausted_today'):
                continue
            if int(k.get('request_count_today', 0)) >= int(k.get('max_requests_per_day', self.max_requests_per_day)):
                # mark exhausted
                k['is_active'] = False
                k['exhausted_today'] = True
                continue

            # candidate found
            self._state['cursor'] = (idx + 1) % n
            self._save_state()
            api_val = os.getenv(k.get('key_id'))
            return (api_val, k.get('key_id'))

        return None

    def increment_request_count(self, key_id: str) -> None:
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                k['request_count_today'] = int(k.get('request_count_today', 0)) + 1
                # if exceeded, mark inactive & exhausted
                if int(k.get('request_count_today')) >= int(k.get('max_requests_per_day', self.max_requests_per_day)):
                    k['is_active'] = False
                    k['exhausted_today'] = True
                self._save_state()
                return

    def mark_exhausted(self, key_id: str, error: str | None = None) -> None:
        now = datetime.utcnow().isoformat()
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                k['is_active'] = False
                k['exhausted_today'] = True
                k['last_error'] = str(error) if error else None
                k['last_error_at'] = now
                self._save_state()
                return

    def mark_temporary_error(self, key_id: str, error: str | None = None) -> None:
        # Keep key active but record last_error metadata
        now = datetime.utcnow().isoformat()
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                k['last_error'] = str(error) if error else None
                k['last_error_at'] = now
                self._save_state()
                return

    def mark_429(self, key_id: str) -> None:
        """Handle a 429 on the given key: record and push key to next minute window.

        - increment `total_429`
        - reset `consecutive_errors` to 0
        - set `next_available_at` to the start of the next minute
        - reset per-window counters (`used_in_window`)
        - persist state
        """
        now = datetime.utcnow()
        next_minute = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))
        next_iso = next_minute.isoformat()
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                k['total_429'] = int(k.get('total_429', 0)) + 1
                k['consecutive_errors'] = 0
                k['next_available_at'] = next_iso
                # reset rpm window so next minute starts fresh
                k['window_started_at'] = next_iso
                k['used_in_window'] = 0
                k['last_error'] = '429'
                k['last_error_at'] = now.isoformat()
                self._save_state()
                return

    def mark_5xx_or_timeout(self, key_id: str, backoff_seconds: int = 60) -> None:
        """Record a 5xx/timeout for the given key and apply exponential backoff.

        - increment `consecutive_errors`
        - increment `total_5xx`
        - set `next_available_at` = now + backoff_seconds
        - if `consecutive_errors >= 5` then set `disabled_until` to a longer window
        - persist state
        """
        now = datetime.utcnow()
        now_iso = now.isoformat()
        for k in self._state.get('keys', []):
            if k.get('key_id') == key_id:
                # increment counters
                k['consecutive_errors'] = int(k.get('consecutive_errors', 0)) + 1
                k['total_5xx'] = int(k.get('total_5xx', 0)) + 1
                k['last_error'] = '5xx_or_timeout'
                k['last_error_at'] = now_iso

                # schedule next available time
                try:
                    next_iso = (now + timedelta(seconds=int(backoff_seconds))).isoformat()
                    k['next_available_at'] = next_iso
                except Exception:
                    next_iso = None
                    k['next_available_at'] = None

                # if too many consecutive errors, disable key for a longer cooldown
                try:
                    if int(k.get('consecutive_errors', 0)) >= 5:
                        # disabled for min(1 hour, backoff_seconds * 10)
                        cool = min(3600, int(backoff_seconds) * 10)
                        k['disabled_until'] = (now + timedelta(seconds=cool)).isoformat()
                except Exception:
                    pass

                # persist and return diagnostic info
                self._save_state()
                return {"next_available_at": next_iso, "consecutive_errors": int(k.get('consecutive_errors', 0))}

    def has_active_keys(self) -> bool:
        for k in self._state.get('keys', []):
            if k.get('is_active') and not k.get('exhausted_today') and int(k.get('request_count_today', 0)) < int(k.get('max_requests_per_day', self.max_requests_per_day)):
                return True
        return False
