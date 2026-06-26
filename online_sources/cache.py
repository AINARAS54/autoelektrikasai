import json
import time
from pathlib import Path


CACHE_DIR = Path(__file__).resolve().parent / "_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_key(key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in str(key))[:180]


def get_cache(key: str, max_age_seconds: int = 86400):
    path = CACHE_DIR / f"{_safe_key(key)}.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created = data.get("_created", 0)
        if time.time() - created > max_age_seconds:
            return None
        return data.get("value")
    except Exception:
        return None


def set_cache(key: str, value):
    path = CACHE_DIR / f"{_safe_key(key)}.json"
    data = {
        "_created": time.time(),
        "value": value,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
