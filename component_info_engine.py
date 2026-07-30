import json
import re
from pathlib import Path


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().strip())


def _vehicle_key(ctx: dict) -> str | None:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    brand = _norm(str(vehicle.get("brand", "")))
    model = _norm(str(vehicle.get("model", "")))
    if brand == "bmw" and model in {"i3", "i 3"}:
        return "bmw_i3"
    return None


def _load_vehicle_data(base_dir: Path, key: str) -> dict:
    path = Path(base_dir) / "component_info" / f"{key}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def detect_component_topic(text: str) -> str | None:
    t = _norm(text)
    rules = {
        "fuses": ["saugikl", "fuse", "pagrindiniai saugikliai", "saugikliu deze", "saugiklių dėžė"],
        "battery_12v": ["12 v akumuliator", "12v akumuliator", "pagalbinis akumuliator", "12 v bater", "12v bater"],
        "bdc": ["bdc", "body domain controller"],
        "hv_safety": ["hv saug", "aukštos įtampos saug", "aukstos itampos saug", "aukštos įtampos", "aukstos itampos"],
        "check_procedure": ["patikros proced", "kaip patikrinti", "tikrinimo eiga", "patikrinimo eiga"],
        "diagram": ["schema", "schemą", "schemos", "išdėstymas", "isdestymas"],
    }
    for topic, needles in rules.items():
        if any(needle in t for needle in needles):
            return topic
    return None


def _has_library_documents(base_dir: Path, ctx: dict, document_type: str | None = None) -> bool:
    try:
        from technical_library_engine import list_documents
        return bool(list_documents(base_dir, ctx, document_type=document_type))
    except Exception:
        return False


def available_component_topics(base_dir: Path, ctx: dict) -> set[str]:
    """Return only actions that can provide useful information now.

    Static component topics are available when the active vehicle data file has
    real content for them. File-backed actions are available only when a local
    document exists, so the user never sees a button that leads to an empty
    result.
    """
    key = _vehicle_key(ctx)
    if not key:
        return set()
    data = _load_vehicle_data(base_dir, key)
    topics = data.get("topics") if isinstance(data.get("topics"), dict) else {}
    available = {
        topic for topic in ("battery_12v", "fuses", "bdc", "check_procedure", "hv_safety")
        if isinstance(topics.get(topic), dict) and topics.get(topic)
    }
    if _has_library_documents(base_dir, ctx, "fuse_diagram"):
        available.add("diagram")
    if _has_library_documents(base_dir, ctx):
        available.add("library")
    return available


def component_keyboard(base_dir: Path, ctx: dict) -> dict:
    available = available_component_topics(base_dir, ctx)
    buttons = {
        "battery_12v": {"text": "🔋 12 V akumuliatorius", "callback_data": "comp:battery_12v"},
        "fuses": {"text": "📍 Saugiklių vietos", "callback_data": "comp:fuses"},
        "bdc": {"text": "🔧 BDC modulis", "callback_data": "comp:bdc"},
        "diagram": {"text": "🧩 Saugiklių schema", "callback_data": "comp:diagram"},
        "check_procedure": {"text": "📄 Patikros procedūra", "callback_data": "comp:check_procedure"},
        "hv_safety": {"text": "⚠️ HV sauga", "callback_data": "comp:hv_safety"},
        "library": {"text": "📚 Techninė biblioteka", "callback_data": "comp:library"},
    }
    rows = []
    for pair in (("battery_12v", "fuses"), ("bdc", "diagram"), ("check_procedure", "hv_safety")):
        row = [buttons[name] for name in pair if name in available]
        if row:
            rows.append(row)
    if "library" in available:
        rows.append([buttons["library"]])
    rows.append([
        {"text": "🆕 Nauja diagnostika", "callback_data": "new_diagnostic"},
        {"text": "📂 Ankstesnės diagnostikos", "callback_data": "diagnostic_history"},
    ])
    return {"inline_keyboard": rows}


def _vehicle_label(ctx: dict, data: dict) -> str:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    label = " ".join(str(v) for v in parts if v)
    return label or data.get("vehicle_label") or "Automobilis"


def answer_component(base_dir: Path, text: str, ctx: dict, forced_topic: str | None = None):
    key = _vehicle_key(ctx)
    topic = forced_topic or detect_component_topic(text)
    if not key or not topic:
        return None, None

    data = _load_vehicle_data(base_dir, key)
    entry = (data.get("topics") or {}).get(topic)
    if not entry:
        return None, None

    label = _vehicle_label(ctx, data)
    title = entry.get("title") or topic
    lines = [f"<b>{esc(label)} – {esc(title)}</b>"]

    intro = entry.get("intro")
    if intro:
        lines.append(f"\n{esc(intro)}")

    sections = entry.get("sections") or []
    for section in sections:
        heading = section.get("heading")
        body = section.get("body")
        items = section.get("items") or []
        if heading:
            lines.append(f"\n<b>{esc(heading)}</b>")
        if body:
            lines.append(esc(body))
        for item in items:
            lines.append(f"• {esc(item)}")

    warning = entry.get("warning")
    if warning:
        lines.append(f"\n⚠️ <b>Svarbu:</b> {esc(warning)}")

    note = entry.get("note")
    if note:
        lines.append(f"\nℹ️ {esc(note)}")

    return "\n".join(lines), component_keyboard(base_dir, ctx)
