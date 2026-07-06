import json
import datetime
from pathlib import Path

def _safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))

def session_dir(base_dir: Path) -> Path:
    path = Path(base_dir) / "decision_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path

def session_path(base_dir: Path, chat_id: str) -> Path:
    return session_dir(base_dir) / f"{_safe_chat_id(chat_id)}.json"

def load_decision_session(base_dir: Path, chat_id: str) -> dict | None:
    path = session_path(base_dir, chat_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def save_decision_session(base_dir: Path, chat_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    session_path(base_dir, chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def clear_decision_session(base_dir: Path, chat_id: str):
    path = session_path(base_dir, chat_id)
    if path.exists():
        path.unlink()
