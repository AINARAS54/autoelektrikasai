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


def _archive_dir(base_dir: Path) -> Path:
    d = Path(base_dir) / "cases_archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_completed_diagnostic(base_dir: Path, chat_id: str, result: dict) -> str:
    """Persist a completed diagnostic immediately, without clearing active context.

    This makes the result visible in history as soon as the decision tree reaches
    a result node. The same completed session is not archived twice when the user
    later presses "Nauja diagnostika".
    """
    ctx = load_context(base_dir, chat_id)
    now = datetime.datetime.now(datetime.UTC)
    case_id = ctx.get("last_completed_case_id")

    # Reuse the id only when this exact completed result was already saved.
    result_key = f"{result.get('tree_id')}:{result.get('node_id')}:{result.get('completed_at', '')}"
    if case_id and ctx.get("last_completed_result_key") == result_key:
        return case_id

    case_id = f"AE-{now.strftime('%Y%m%d-%H%M%S-%f')}-{_safe_chat_id(chat_id)}"
    snapshot = json.loads(json.dumps(ctx, ensure_ascii=False))
    snapshot["case_id"] = case_id
    snapshot["archived_at"] = now.isoformat()
    snapshot["completed_at"] = result.get("completed_at") or now.isoformat()
    snapshot["status"] = "completed"
    snapshot["diagnostic_result"] = result

    _archive_dir(base_dir).joinpath(f"{case_id}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ctx["diagnostic_completed"] = True
    ctx["last_completed_case_id"] = case_id
    ctx["last_completed_result_key"] = result_key
    ctx["diagnostic_result"] = result
    save_context(base_dir, chat_id, ctx)
    return case_id

def archive_context(base_dir: Path, chat_id: str):
    ctx = load_context(base_dir, chat_id)
    if not ctx.get("vehicle") and not ctx.get("history") and not ctx.get("topic"):
        clear_context(base_dir, chat_id)
        return None

    # A completed decision-tree result is already saved immediately. Do not
    # create a duplicate when the user starts a new diagnostic.
    if ctx.get("diagnostic_completed") and ctx.get("last_completed_case_id"):
        case_id = ctx.get("last_completed_case_id")
        clear_context(base_dir, chat_id)
        return case_id

    d = _archive_dir(base_dir)
    now = datetime.datetime.now(datetime.UTC)
    case_id = ctx.get("case_id") or f"AE-{now.strftime('%Y%m%d-%H%M%S-%f')}-{_safe_chat_id(chat_id)}"
    ctx["case_id"] = case_id
    ctx["archived_at"] = now.isoformat()
    ctx.setdefault("status", "incomplete")
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



def has_active_diagnostic(ctx: dict) -> bool:
    """True when context already contains a fault/diagnostic conversation.

    Vehicle-only and VIN-only messages do not count as a diagnosed fault.
    """
    if ctx.get("active_diagnostic") or ctx.get("fault_id") or ctx.get("problem"):
        return True
    if ctx.get("topic") or ctx.get("subtopic"):
        return True
    vin_re = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)
    ignored = {"/start", "start", "nauja diagnostika", "nauja sesija"}
    for item in ctx.get("history") or []:
        text = str((item or {}).get("user") or "").strip()
        compact = text.replace(" ", "").upper()
        if not text or text.lower() in ignored or vin_re.fullmatch(compact):
            continue
        # A message containing only make/model/year is vehicle setup, not a fault.
        detected = detect_vehicle(text)
        words = text.split()
        if detected and len(words) <= 5 and not any(x in text.lower() for x in [
            "ne", "klaida", "ged", "ready", "užsived", "uzsived", "neveik", "dega", "meta", "krauna", "suka"
        ]):
            continue
        return True
    return False

def get_range_summary(ctx: dict) -> str:
    m = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    old, cur = m.get("range_new_km"), m.get("range_current_km")
    if not old or not cur:
        return ""
    lines = [f"Pradinė rida: {old} km", f"Dabartinė rida: {cur} km"]
    if m.get("range_loss_percent") is not None:
        lines.append(f"Sumažėjimas: apie {m.get('range_loss_percent')} %")
    return "\n".join(lines)


def archived_diagnostics_summary(base_dir: Path, chat_id: str, limit: int = 10) -> str:
    """Return completed and manually archived diagnostics for this chat."""
    archive_dir = Path(base_dir) / "cases_archive"
    safe_id = _safe_chat_id(chat_id)
    if not archive_dir.exists():
        return "📂 <b>Ankstesnės diagnostikos</b>\n\nIšsaugotų diagnostikų dar nėra."

    items = []
    for path in archive_dir.glob(f"*-{safe_id}.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        vehicle = data.get("vehicle") if isinstance(data.get("vehicle"), dict) else {}
        label_parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
        label = " ".join(str(x) for x in label_parts if x) or "Automobilis nenurodytas"

        result = data.get("diagnostic_result") if isinstance(data.get("diagnostic_result"), dict) else {}
        saved_at = data.get("completed_at") or data.get("archived_at") or ""
        date = saved_at[:16].replace("T", " ") if saved_at else "Data nenurodyta"
        title = result.get("tree_title") or data.get("subtopic") or data.get("topic") or "Diagnostika"
        conclusion = result.get("text") or ""
        probability = result.get("probability")

        line = f"• <b>{esc_history(date)}</b> — {esc_history(label)}\n  {esc_history(title)}"
        if conclusion:
            line += f"\n  Rezultatas: {esc_history(conclusion[:140])}"
        if probability is not None:
            line += f"\n  Tikimybė: ~{esc_history(probability)} %"
        items.append((saved_at, line))

    if not items:
        return "📂 <b>Ankstesnės diagnostikos</b>\n\nIšsaugotų diagnostikų dar nėra."

    items.sort(key=lambda item: item[0], reverse=True)
    return "📂 <b>Ankstesnės diagnostikos</b>\n\n" + "\n\n".join(line for _, line in items[:limit])


def esc_history(value) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

