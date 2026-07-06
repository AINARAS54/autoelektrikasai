import json, re
from pathlib import Path

def esc(v): return str(v or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def detect_obd(text: str):
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None

def answer_obd(base_dir: Path, text: str, ctx: dict | None = None) -> str:
    code = detect_obd(text)
    if not code:
        return "OBD kodas neatpažintas."
    data_dir = Path(base_dir) / "data"
    db = load_json(data_dir / "obd_codes_starter_lt.json", {})
    full = load_json(data_dir / "obd_codes_full_lt.json", {})
    if isinstance(full, dict):
        db.update(full)
    item = db.get(code)
    if not item:
        return f"⚡ <b>OBD kodas: {esc(code)}</b>\n\nŠio kodo vietinėje bazėje neradau.\n\nParašykite automobilio markę, modelį, metus ir simptomus."
    meaning = item.get("meaning_lt") or item.get("meaning") or item.get("title_lt") or "Aprašymas nerastas."
    causes = item.get("causes_lt") or []
    checks = item.get("checks_lt") or item.get("first_checks") or []
    severity = item.get("severity", "medium")
    priority = {"low":"🟢 Žemas", "medium":"🟠 Vidutinis", "high":"🔴 Aukštas"}.get(severity, "🟠 Vidutinis")
    causes_txt = "\n".join([f"• {esc(x)}" for x in causes[:6]]) or "• Reikalinga papildoma diagnostika."
    checks_txt = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(checks[:7])]) or "1. Nuskaityti freeze-frame duomenis."
    return f"""⚡ <b>OBD kodas: {esc(code)}</b>

Reikšmė:
{esc(meaning)}

Galimos priežastys:
{causes_txt}

Rekomenduojama diagnostikos eiga:
{checks_txt}

Prioritetas:
{priority}

Svarbu:
Klaidos kodas nėra galutinė diagnozė."""
