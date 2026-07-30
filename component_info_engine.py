import re
from pathlib import Path

from technical_library_engine import list_documents
from vehicle_database_engine import available_topics, get_verified_topic


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().strip())


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


def component_keyboard(base_dir: Path, ctx: dict) -> dict:
    available = available_topics(base_dir, ctx)
    has_diagram = bool(list_documents(base_dir, ctx, "fuse_diagram"))
    has_library = bool(list_documents(base_dir, ctx))

    buttons = []
    row = []

    candidates = [
        ("battery_12v", "🔋 12 V akumuliatorius", "comp:battery_12v"),
        ("fuses", "📍 Saugiklių vietos", "comp:fuses"),
        ("bdc", "🔧 BDC modulis", "comp:bdc"),
        ("check_procedure", "📄 Patikros procedūra", "comp:check_procedure"),
        ("hv_safety", "⚠️ HV sauga", "comp:hv_safety"),
    ]

    for topic, label, callback in candidates:
        if topic not in available:
            continue
        row.append({"text": label, "callback_data": callback})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if has_diagram:
        buttons.append([{"text": "🧩 Saugiklių schema", "callback_data": "comp:diagram"}])
    if has_library:
        buttons.append([{"text": "📚 Techninė biblioteka", "callback_data": "comp:library"}])

    buttons.append([
        {"text": "🆕 Nauja diagnostika", "callback_data": "new_diagnostic"},
        {"text": "📂 Ankstesnės diagnostikos", "callback_data": "diagnostic_history"},
    ])
    return {"inline_keyboard": buttons}


def _vehicle_label(ctx: dict) -> str:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    return " ".join(str(v) for v in parts if v) or "Automobilis"


def unavailable_component_answer(ctx: dict, topic: str) -> str:
    label = _vehicle_label(ctx)
    names = {
        "fuses": "tikslių saugiklių vietų",
        "battery_12v": "tikslios 12 V akumuliatoriaus informacijos",
        "bdc": "patvirtintos BDC modulio informacijos",
        "hv_safety": "modeliui skirtos HV saugos procedūros",
        "check_procedure": "patvirtintos patikros procedūros",
        "diagram": "patvirtintos saugiklių schemos",
    }
    subject = names.get(topic, "patvirtintos techninės informacijos")
    return (
        f"ℹ️ <b>{esc(label)}</b>\n\n"
        f"Šiuo metu duomenų bazėje nėra {esc(subject)}.\n\n"
        "Kad nebūtų pateikta netiksli informacija, bendras arba nepatvirtintas atsakymas nerodomas."
    )


def answer_component(base_dir: Path, text: str, ctx: dict, forced_topic: str | None = None):
    topic = forced_topic or detect_component_topic(text)
    if not topic:
        return None, None

    if topic == "diagram":
        return None, None

    entry = get_verified_topic(base_dir, ctx, topic)
    if not entry:
        return unavailable_component_answer(ctx, topic), component_keyboard(base_dir, ctx)

    label = _vehicle_label(ctx)
    title = entry.get("title") or topic
    lines = [f"<b>{esc(label)} – {esc(title)}</b>"]

    intro = entry.get("intro")
    if intro:
        lines.append(f"\n{esc(intro)}")

    for section in entry.get("sections") or []:
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

    source = entry.get("source")
    if source:
        lines.append(f"\n📚 Šaltinis: {esc(source)}")

    return "\n".join(lines), component_keyboard(base_dir, ctx)
