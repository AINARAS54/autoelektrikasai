import json
import re
from pathlib import Path


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def _safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))


def context_dir(base_dir: Path) -> Path:
    path = Path(base_dir) / "case_contexts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_path(base_dir: Path, chat_id: str) -> Path:
    return context_dir(base_dir) / f"{_safe_chat_id(chat_id)}.json"


def load_context(base_dir: Path, chat_id: str) -> dict:
    path = context_path(base_dir, chat_id)
    if not path.exists():
        return {
            "vehicle": {},
            "topic": None,
            "subtopic": None,
            "measurements": {},
            "last_intent": None,
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"vehicle": {}, "measurements": {}}
        data.setdefault("vehicle", {})
        data.setdefault("measurements", {})
        return data
    except Exception:
        return {"vehicle": {}, "measurements": {}}


def save_context(base_dir: Path, chat_id: str, ctx: dict) -> dict:
    path = context_path(base_dir, chat_id)
    path.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx


def clear_context(base_dir: Path, chat_id: str):
    path = context_path(base_dir, chat_id)
    if path.exists():
        path.unlink()


def detect_vehicle_entities(text: str) -> dict:
    t = _normalize(text)
    vehicle = {}

    brand_aliases = {
        "bmw": "BMW",
        "audi": "Audi",
        "vw": "Volkswagen",
        "volkswagen": "Volkswagen",
        "mercedes": "Mercedes-Benz",
        "toyota": "Toyota",
        "volvo": "Volvo",
        "tesla": "Tesla",
        "nissan": "Nissan",
        "hyundai": "Hyundai",
        "kia": "Kia",
    }

    for key, value in brand_aliases.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            vehicle["brand"] = value
            break

    models = [
        "i3", "i4", "i5", "i7", "ix",
        "id.3", "id3", "id.4", "id4",
        "golf", "passat", "a3", "a4", "a6", "q5", "q7",
        "model 3", "model y", "leaf", "kona", "niro",
    ]
    for model in models:
        if re.search(rf"\b{re.escape(model)}\b", t):
            if model == "id3":
                model = "ID.3"
            elif model == "id4":
                model = "ID.4"
            vehicle["model"] = model
            break

    year = re.search(r"\b(19[8-9]\d|20[0-3]\d)\s*m?\.?\b", t)
    if year:
        vehicle["year"] = year.group(1)

    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", (text or "").upper().replace(" ", ""))
    if vin:
        vehicle["vin"] = vin.group(0)

    return vehicle


def detect_topic(text: str) -> dict:
    t = _normalize(text)
    result = {}

    if any(x in t for x in ["bater", "akumuliator", "hv", "aukštos įtampos", "aukstos itampos", "soh", "nuvažiuoja", "nuvaziuoja", "talpa"]):
        result["topic"] = "HV_BATTERY"

    if any(x in t for x in ["stabdžių skys", "stabdziu skys", "brake fluid"]):
        result["topic"] = "BRAKE_FLUID"

    if any(x in t for x in ["kain", "remont", "kiek kainuos", "kiek kainuoja"]):
        result["last_intent"] = "PRICE"

    if any(x in t for x in ["kaip", "reset", "nureset", "nunul", "atstat"]):
        result["last_intent"] = result.get("last_intent") or "PROCEDURE"

    return result


def extract_range_data(text: str) -> dict:
    """
    Atpažįsta EV ridos sumažėjimą:
    - naujas nuvažiuodavo 270 km, dabar 170
    - nuo 270 km iki 170 km
    - 270 -> 170 km
    Ignoruoja metus, pvz. 2019, ir amžių, pvz. 7 metai.
    """
    t = _normalize(text)
    result = {}

    patterns = [
        r"nuva\w+\s*(\d{2,4})\s*km?.{0,80}?nuva\w+\s*(\d{2,4})\s*km?",
        r"nuo\s*(\d{2,4})\s*km?.{0,40}?iki\s*(\d{2,4})\s*km?",
        r"(\d{2,4})\s*km\s*(?:->|→|-)\s*(\d{2,4})\s*km?",
    ]

    pair = None
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            pair = (int(m.group(1)), int(m.group(2)))
            break

    if not pair:
        # Fallback: imame tik realistiškas EV ridos reikšmes, ignoruojame metus ir "7 metų".
        nums = []
        for m in re.finditer(r"\b(\d{2,4})\b", t):
            n = int(m.group(1))
            if 50 <= n <= 800:
                nums.append(n)
        if len(nums) >= 2:
            # Dažniausiai pirmas yra pradinė rida, paskutinis - dabartinė.
            pair = (nums[0], nums[-1])

    if pair:
        old, current = pair
        if old > current and old > 0:
            result["range_new_km"] = old
            result["range_current_km"] = current
            result["range_loss_percent"] = round((1 - current / old) * 100)
            result["range_remaining_percent"] = round((current / old) * 100)
            result["subtopic"] = "RANGE_DECREASE"

    return result


def update_context(base_dir: Path, chat_id: str, text: str, extra: dict | None = None) -> dict:
    ctx = load_context(base_dir, chat_id)

    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    new_vehicle = detect_vehicle_entities(text)
    for k, v in new_vehicle.items():
        if v:
            vehicle[k] = v
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

    return save_context(base_dir, chat_id, ctx)


def get_vehicle_label(ctx: dict) -> str:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    label = " ".join([str(x) for x in parts if x]).strip()
    return label or "Nenurodytas automobilis"


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
    t = _normalize(text)
    price = any(x in t for x in ["kain", "kiek kainuos", "kiek kainuoja", "remont"])
    hv_topic = ctx.get("topic") == "HV_BATTERY" or ctx.get("subtopic") == "RANGE_DECREASE"
    direct_battery = any(x in t for x in ["bater", "modul", "soh", "akumuliator"])
    return price and (hv_topic or direct_battery)


def is_hv_battery_consultation(text: str) -> bool:
    t = _normalize(text)
    return any(x in t for x in ["bater", "talpa", "soh", "nuvažiuoja", "nuvaziuoja", "rida", "atstatyti bater"])
