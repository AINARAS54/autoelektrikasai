import json
import re
from pathlib import Path

from vehicle_engine import detect_vehicle, vehicle_label


def _safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))


def context_dir(base_dir: Path) -> Path:
    path = Path(base_dir) / "case_contexts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_dir(base_dir: Path) -> Path:
    path = Path(base_dir) / "cases_archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_path(base_dir: Path, chat_id: str) -> Path:
    return context_dir(base_dir) / f"{_safe_chat_id(chat_id)}.json"


def load_context(base_dir: Path, chat_id: str) -> dict:
    path = context_path(base_dir, chat_id)
    if not path.exists():
        return default_context()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_context()
        data.setdefault("vehicle", {})
        data.setdefault("measurements", {})
        data.setdefault("history", [])
        return data
    except Exception:
        return default_context()


def default_context() -> dict:
    return {
        "vehicle": {},
        "topic": None,
        "subtopic": None,
        "measurements": {},
        "last_intent": None,
        "history": [],
    }


def save_context(base_dir: Path, chat_id: str, ctx: dict) -> dict:
    context_path(base_dir, chat_id).write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx


def clear_context(base_dir: Path, chat_id: str):
    path = context_path(base_dir, chat_id)
    if path.exists():
        path.unlink()


def archive_context(base_dir: Path, chat_id: str) -> str | None:
    path = context_path(base_dir, chat_id)
    if not path.exists():
        return None
    ctx = load_context(base_dir, chat_id)
    if not ctx.get("history") and not ctx.get("vehicle") and not ctx.get("topic"):
        clear_context(base_dir, chat_id)
        return None

    import datetime
    now = datetime.datetime.now(datetime.UTC)
    case_id = ctx.get("case_id") or f"AE-{now.strftime('%Y%m%d-%H%M%S')}-{_safe_chat_id(chat_id)}"
    ctx["case_id"] = case_id
    ctx["archived_at"] = now.isoformat()
    archive_file = archive_dir(base_dir) / f"{case_id}.json"
    archive_file.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_context(base_dir, chat_id)
    return case_id


def extract_range_data(text: str) -> dict:
    t = (text or "").lower()
    result = {}

    patterns = [
        r"nuva\w+\s*(\d{2,4})\s*km?.{0,100}?nuva\w+\s*(\d{2,4})\s*km?",
        r"nuo\s*(\d{2,4})\s*km?.{0,60}?iki\s*(\d{2,4})\s*km?",
        r"(\d{2,4})\s*km\s*(?:->|→|-)\s*(\d{2,4})\s*km?",
    ]

    pair = None
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            pair = (int(m.group(1)), int(m.group(2)))
            break

    if not pair:
        nums = []
        for m in re.finditer(r"\b(\d{2,4})\b", t):
            n = int(m.group(1))
            if 50 <= n <= 800:
                nums.append(n)
        if len(nums) >= 2:
            pair = (nums[0], nums[-1])

    if pair:
        old, current = pair
        if old > current and old > 0:
            result["range_new_km"] = old
            result["range_current_km"] = current
            result["range_loss_percent"] = round((1 - current / old) * 100)
            result["range_remaining_percent"] = round((current / old) * 100)

    return result


def detect_topic(text: str) -> dict:
    t = (text or "").lower()
    data = {}

    if any(x in t for x in ["bater", "akumuliator", "hv", "aukštos įtampos", "aukstos itampos", "soh", "nuvažiuoja", "nuvaziuoja", "talpa"]):
        data["topic"] = "HV_BATTERY"

    if any(x in t for x in ["stabdžių skys", "stabdziu skys", "brake fluid"]):
        data["topic"] = "BRAKE_FLUID"

    if any(x in t for x in ["kain", "remont", "kiek kainuos", "kiek kainuoja"]):
        data["last_intent"] = "PRICE"

    if any(x in t for x in ["kaip", "reset", "nureset", "nunul", "atstat"]):
        data["last_intent"] = data.get("last_intent") or "PROCEDURE"

    return data


def update_context(base_dir: Path, chat_id: str, text: str, extra: dict | None = None) -> dict:
    ctx = load_context(base_dir, chat_id)

    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    detected = detect_vehicle(text)
    vehicle.update({k: v for k, v in detected.items() if v})
    ctx["vehicle"] = vehicle

    topic = detect_topic(text)
    ctx.update({k: v for k, v in topic.items() if v})

    range_data = extract_range_data(text)
    if range_data:
        ctx.setdefault("measurements", {})
        ctx["measurements"].update(range_data)
        ctx["topic"] = "HV_BATTERY"
        ctx["subtopic"] = "RANGE_DECREASE"

    if extra:
        for k, v in extra.items():
            if k == "vehicle" and isinstance(v, dict):
                ctx.setdefault("vehicle", {})
                ctx["vehicle"].update({kk: vv for kk, vv in v.items() if vv})
            elif k == "measurements" and isinstance(v, dict):
                ctx.setdefault("measurements", {})
                ctx["measurements"].update(v)
            else:
                ctx[k] = v

    history = ctx.setdefault("history", [])
    history.append({"user": text})
    ctx["history"] = history[-20:]

    return save_context(base_dir, chat_id, ctx)


def get_vehicle_label(ctx: dict) -> str:
    return vehicle_label(ctx.get("vehicle") or {})


def get_hv_range_summary(ctx: dict) -> str:
    m = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    old = m.get("range_new_km")
    current = m.get("range_current_km")
    loss = m.get("range_loss_percent")
    remaining = m.get("range_remaining_percent")

    if not old or not current:
        return ""

    lines = [
        f"Pradinė rida: {old} km",
        f"Dabartinė rida: {current} km",
    ]
    if loss is not None:
        lines.append(f"Sumažėjimas: apie {loss} %")
    if remaining is not None:
        lines.append(f"Likusi santykinė talpa: apie {remaining} %")
    return "\n".join(lines)


def is_contextual_hv_price(text: str, ctx: dict) -> bool:
    t = (text or "").lower()
    price = any(x in t for x in ["kain", "kiek kainuos", "kiek kainuoja", "remont"])
    hv_topic = ctx.get("topic") == "HV_BATTERY" or ctx.get("subtopic") == "RANGE_DECREASE"
    direct_battery = any(x in t for x in ["bater", "modul", "soh", "akumuliator"])
    return price and (hv_topic or direct_battery)


def is_hv_battery_consultation(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in ["bater", "talpa", "soh", "nuvažiuoja", "nuvaziuoja", "rida", "atstatyti bater"])
