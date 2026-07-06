import json, re, datetime
from pathlib import Path
from vehicle_engine import detect_vehicle

def _safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))

def default_context():
    return {"vehicle": {}, "measurements": {}, "history": [], "topic": None, "subtopic": None, "last_intent": None}

def context_path(base_dir: Path, chat_id: str) -> Path:
    d = Path(base_dir) / "case_contexts"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_chat_id(chat_id)}.json"

def load_context(base_dir: Path, chat_id: str) -> dict:
    p = context_path(base_dir, chat_id)
    if not p.exists():
        return default_context()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("vehicle", {})
        data.setdefault("measurements", {})
        data.setdefault("history", [])
        return data
    except Exception:
        return default_context()

def save_context(base_dir: Path, chat_id: str, ctx: dict) -> dict:
    context_path(base_dir, chat_id).write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx

def clear_context(base_dir: Path, chat_id: str):
    p = context_path(base_dir, chat_id)
    if p.exists():
        p.unlink()

def archive_context(base_dir: Path, chat_id: str):
    ctx = load_context(base_dir, chat_id)
    if not ctx.get("vehicle") and not ctx.get("history") and not ctx.get("topic"):
        clear_context(base_dir, chat_id)
        return None
    d = Path(base_dir) / "cases_archive"
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.UTC)
    case_id = ctx.get("case_id") or f"AE-{now.strftime('%Y%m%d-%H%M%S')}-{_safe_chat_id(chat_id)}"
    ctx["case_id"] = case_id
    ctx["archived_at"] = now.isoformat()
    (d / f"{case_id}.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_context(base_dir, chat_id)
    return case_id

def is_12v_battery_text(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in ["start bater", "starto bater", "12v", "12 v", "pagalbinis akumuliator", "aux battery", "starto akumuliator"])

def extract_range(text: str) -> dict:
    t = (text or "").lower()
    pair = None
    for pat in [
        r"nuva\w+\s*(\d{2,4})\s*km?.{0,120}?nuva\w+\s*(\d{2,4})\s*km?",
        r"nuo\s*(\d{2,4})\s*km?.{0,60}?iki\s*(\d{2,4})\s*km?",
        r"(\d{2,4})\s*km\s*(?:->|→|-)\s*(\d{2,4})\s*km?",
    ]:
        m = re.search(pat, t)
        if m:
            pair = (int(m.group(1)), int(m.group(2)))
            break
    if not pair:
        nums = [int(m.group(1)) for m in re.finditer(r"\b(\d{2,4})\b", t) if 50 <= int(m.group(1)) <= 800]
        if len(nums) >= 2:
            pair = (nums[0], nums[-1])
    if not pair:
        return {}
    old, cur = pair
    if old <= cur or old <= 0:
        return {}
    return {"range_new_km": old, "range_current_km": cur, "range_loss_percent": round((1 - cur / old) * 100)}

def detect_topic(text: str) -> dict:
    t = (text or "").lower()
    data = {}
    if is_12v_battery_text(text):
        data["topic"] = "12V_BATTERY"
        data["subtopic"] = "12 V akumuliatorius"
    elif any(x in t for x in ["bater", "akumuliator", "hv", "aukštos įtampos", "aukstos itampos", "soh", "nuvažiuoja", "nuvaziuoja", "talpa"]):
        data["topic"] = "HV_BATTERY"
    if any(x in t for x in ["kaina", "kainuoja", "kainuos", "kainuoti", "atsieina"]):
        data["last_intent"] = "PRICE"
    return data

def update_context(base_dir: Path, chat_id: str, text: str, extra: dict | None = None) -> dict:
    ctx = load_context(base_dir, chat_id)
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    vehicle.update({k: v for k, v in detect_vehicle(text).items() if v})
    ctx["vehicle"] = vehicle
    ctx.update({k: v for k, v in detect_topic(text).items() if v})
    r = extract_range(text)
    if r:
        ctx.setdefault("measurements", {}).update(r)
        ctx["topic"] = "HV_BATTERY"
        ctx["subtopic"] = "RANGE_DECREASE"
    if extra:
        for k, v in extra.items():
            if k == "vehicle" and isinstance(v, dict):
                ctx.setdefault("vehicle", {}).update({kk: vv for kk, vv in v.items() if vv})
            else:
                ctx[k] = v
    ctx.setdefault("history", []).append({"user": text, "time": datetime.datetime.now(datetime.UTC).isoformat()})
    ctx["history"] = ctx["history"][-30:]
    return save_context(base_dir, chat_id, ctx)

def get_range_summary(ctx: dict) -> str:
    m = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    old, cur = m.get("range_new_km"), m.get("range_current_km")
    if not old or not cur:
        return ""
    lines = [f"Pradinė rida: {old} km", f"Dabartinė rida: {cur} km"]
    if m.get("range_loss_percent") is not None:
        lines.append(f"Sumažėjimas: apie {m.get('range_loss_percent')} %")
    return "\n".join(lines)
