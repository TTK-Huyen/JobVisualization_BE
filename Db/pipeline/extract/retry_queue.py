import json
import os
from pathlib import Path
import hashlib
from datetime import datetime
from Db.llm.llm_config import LLM_RETRY_QUEUE_PATH, LLM_DEAD_LETTER_PATH


def _job_fingerprint(job: dict) -> str:
    title = job.get('title', '')
    company = job.get('company_name', '')
    req = job.get('requirements_text', '')
    combined = f"{title}|{company}|{req}"
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


def _atomic_write(path: Path, data) -> bool:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(str(tmp), str(path))
        return True
    except Exception:
        return False


def load_retry_queue():
    path = Path(LLM_RETRY_QUEUE_PATH)
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or []
        if not isinstance(data, list):
            data = [data]
        # Return only entries (do not filter by next_retry_at here)
        return data
    except Exception:
        return []


def save_retry_queue(jobs):
    try:
        path = Path(LLM_RETRY_QUEUE_PATH)
        # Load existing queue and merge instead of blindly overwriting
        existing = {}
        now = datetime.utcnow().isoformat()
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or []
                for e in data:
                    if not isinstance(e, dict):
                        continue
                    fp = e.get('_fingerprint') or _job_fingerprint(e)
                    e['_fingerprint'] = fp
                    existing[fp] = e
            except Exception:
                existing = {}

        def merge_entry(old: dict, new: dict) -> dict:
            # Preserve original fields unless new provides them.
            out = dict(old or {})
            # Core identity fields (keep from old if missing in new)
            for k in new:
                if k in ("title", "company_name", "job_url", "job_source_id", "description_html", "source_name"):
                    out.setdefault(k, new.get(k))

            # Ensure fingerprint present
            fp = new.get('_fingerprint') or _job_fingerprint(new)
            out['_fingerprint'] = fp
            # runtime fields to update/merge per rules.
            # retry_count: take max (if provided in new or old)
            old_retry = int(old.get('retry_count', 0)) if old else 0
            new_retry = int(new.get('retry_count', 0)) if ('retry_count' in new) else old_retry
            out['retry_count'] = max(old_retry, new_retry)

            # keys_tried: merge unique (old + new)
            old_keys = old.get('keys_tried') or []
            if 'keys_tried' in new:
                new_keys = new.get('keys_tried') or []
                # preserve order: old keys first then new, dedup
                merged_keys = []
                for k in (old_keys + new_keys):
                    if k not in merged_keys:
                        merged_keys.append(k)
                out['keys_tried'] = merged_keys
            else:
                out['keys_tried'] = old_keys

            # Overwrite runtime fields if the key exists in new (even if None)
            if 'last_error' in new:
                out['last_error'] = new.get('last_error')
            else:
                out['last_error'] = old.get('last_error')

            if 'last_error_code' in new:
                out['last_error_code'] = new.get('last_error_code')
            else:
                out['last_error_code'] = old.get('last_error_code')

            if 'next_retry_at' in new:
                out['next_retry_at'] = new.get('next_retry_at')
            else:
                out['next_retry_at'] = old.get('next_retry_at')

            if 'reason' in new:
                out['reason'] = new.get('reason')
            else:
                out['reason'] = old.get('reason')

            if 'last_attempt_at' in new:
                out['last_attempt_at'] = new.get('last_attempt_at')
            else:
                out['last_attempt_at'] = old.get('last_attempt_at')

            # priority: prefer new if provided, else old or 0
            out['priority'] = int(new.get('priority', old.get('priority', 0)))

            # updated_at: always set to now
            out['updated_at'] = now

            # keep other fields from old unless new provides them (non-runtime fields)
            runtime_fields = {'retry_count', 'keys_tried', 'last_error', 'last_error_code', 'next_retry_at', 'reason', 'last_attempt_at', 'updated_at'}
            for k, v in new.items():
                if k in runtime_fields:
                    # already handled above
                    continue
                if k not in out or v is not None:
                    out[k] = v if v is not None else out.get(k)

            return out

        unique = dict(existing)
        for j in jobs or []:
            if not isinstance(j, dict):
                continue
            fp = j.get('_fingerprint') or _job_fingerprint(j)
            j['_fingerprint'] = fp
            if fp in unique:
                merged = merge_entry(unique[fp], j)
                unique[fp] = merged
            else:
                # ensure runtime defaults
                j.setdefault('retry_count', int(j.get('retry_count', 0)))
                j.setdefault('keys_tried', j.get('keys_tried') or [])
                j.setdefault('priority', int(j.get('priority', 0)))
                j['updated_at'] = now
                unique[fp] = j

        return _atomic_write(path, list(unique.values()))
    except Exception:
        return False


def remove_retry_queue_entries(fingerprints):
    """Remove successfully processed entries from the retry queue."""
    try:
        remove_set = {str(fp) for fp in (fingerprints or []) if fp}
        if not remove_set:
            return True

        path = Path(LLM_RETRY_QUEUE_PATH)
        if not path.exists():
            return True

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f) or []
        except Exception:
            data = []

        if not isinstance(data, list):
            data = [data]

        kept = []
        for entry in data:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            fp = entry.get('_fingerprint') or _job_fingerprint(entry)
            url = entry.get('job_url')
            source_key = None
            if entry.get('source_name') and entry.get('job_source_id'):
                source_key = f"{entry.get('source_name')}|{entry.get('job_source_id')}"
            if fp in remove_set or url in remove_set or source_key in remove_set:
                continue
            kept.append(entry)

        return _atomic_write(path, kept)
    except Exception:
        return False


def append_retry_history(entry: dict):
    try:
        path = Path(LLM_RETRY_QUEUE_PATH)
        history = path.parent / 'retry_history.jsonl'
        history.parent.mkdir(parents=True, exist_ok=True)
        with open(history, 'a', encoding='utf-8') as f:
            rec = dict(entry)
            rec.setdefault('history_at', datetime.utcnow().isoformat())
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass


def save_dead_letter(job: dict):
    try:
        path = Path(LLM_DEAD_LETTER_PATH)
        existing = []
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f) or []
            except Exception:
                existing = []
        existing.append(job)
        return _atomic_write(path, existing)
    except Exception:
        return False
