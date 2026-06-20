import json
import datetime
from pathlib import Path

STORE_DIR = Path(__file__).parent / "sessions"
STORE_DIR.mkdir(exist_ok=True)


def _path(chat_id: str) -> Path:
    safe = "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))
    return STORE_DIR / f"{safe}.json"


def _load(chat_id: str) -> dict:
    path = _path(chat_id)
    if not path.exists():
        return {
            "chat_id": str(chat_id),
            "created_at": datetime.datetime.utcnow().isoformat(),
            "updated_at": None,
            "problem": None,
            "fault_id": None,
            "fault_title": None,
            "brand": None,
            "status": "🟡 Reikalinga papildoma informacija",
            "actions": [],
            "skipped_steps": 0
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _save(chat_id: str, data: dict):
    data["updated_at"] = datetime.datetime.utcnow().isoformat()
    _path(chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_or_update_session(chat_id: str, user_text: str, diagnosis: dict):
    data = _load(chat_id)
    data["problem"] = user_text

    fault = diagnosis.get("fault")
    if fault:
        data["fault_id"] = fault.get("id")
        data["fault_title"] = fault.get("title")

    if diagnosis.get("brand"):
        data["brand"] = diagnosis.get("brand")

    data["status"] = diagnosis.get("status", data.get("status"))

    data["actions"].append({
        "time": datetime.datetime.utcnow().isoformat(),
        "type": "user_message",
        "text": user_text
    })
    _save(chat_id, data)


def add_user_action(chat_id: str, action_text: str):
    data = _load(chat_id)

    if "praleido" in action_text.lower():
        data["skipped_steps"] = int(data.get("skipped_steps", 0)) + 1

    data["actions"].append({
        "time": datetime.datetime.utcnow().isoformat(),
        "type": "action",
        "text": action_text
    })
    _save(chat_id, data)


def clear_session(chat_id: str):
    path = _path(chat_id)
    if path.exists():
        path.unlink()


def get_session_summary(chat_id: str) -> str:
    data = _load(chat_id)

    if not data.get("problem") and not data.get("actions"):
        return "📋 Diagnostikos santrauka tuščia.\n\nPradėkite nuo problemos aprašymo."

    actions = data.get("actions", [])[-8:]
    action_lines = []
    for item in actions:
        txt = item.get("text", "")
        if len(txt) > 80:
            txt = txt[:77] + "..."
        action_lines.append(f"• {txt}")

    actions_text = "\n".join(action_lines) if action_lines else "Dar nėra atliktų veiksmų."

    return f"""📋 <b>Diagnostikos santrauka</b>

Automobilis:
{data.get('brand') or 'Nenurodyta'}

Problema:
{data.get('problem') or 'Nenurodyta'}

Sritis:
{data.get('fault_title') or 'Dar nenustatyta'}

Būsena:
{data.get('status')}

Praleisti žingsniai:
{data.get('skipped_steps', 0)}

Paskutiniai veiksmai:
{actions_text}
"""
