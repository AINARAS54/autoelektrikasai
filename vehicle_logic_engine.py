import json
from pathlib import Path

from vehicle_engine import brand_slug


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _model_slug(value: str) -> str:
    return (
        _norm(value)
        .replace(".", "")
        .replace("-", "_")
        .replace(" ", "_")
    )


def _load_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_vehicle_logic(base_dir: Path, ctx: dict) -> dict | None:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    brand = brand_slug(vehicle)
    model = _model_slug(vehicle.get("model", ""))

    if not brand or not model:
        return None

    path = Path(base_dir) / "vehicle_logic" / brand / f"{model}.json"
    if not path.exists():
        return None

    data = _load_json(path)
    if not data:
        return None

    data["_source_file"] = str(path)
    return data


def symptom_redirect(base_dir: Path, text: str, ctx: dict) -> str | None:
    logic = get_vehicle_logic(base_dir, ctx)
    if not logic:
        return None

    t = _norm(text)

    for rule in logic.get("symptom_redirects", []):
        keywords = [_norm(x) for x in rule.get("keywords", [])]
        if any(keyword and keyword in t for keyword in keywords):
            return rule.get("tree")

    return None


def incompatible_component_message(base_dir: Path, text: str, ctx: dict) -> str | None:
    logic = get_vehicle_logic(base_dir, ctx)
    if not logic:
        return None

    t = _norm(text)

    for item in logic.get("not_present_components", []):
        keywords = [_norm(x) for x in item.get("keywords", [])]
        if any(keyword and keyword in t for keyword in keywords):
            return item.get("message")

    return None


def model_context(base_dir: Path, ctx: dict) -> dict:
    logic = get_vehicle_logic(base_dir, ctx)
    if not logic:
        return {}

    return {
        "vehicle_name": logic.get("vehicle_name"),
        "platform": logic.get("platform"),
        "modules": logic.get("modules", []),
        "charging_system": logic.get("charging_system"),
        "ready_sequence": logic.get("ready_sequence", []),
        "common_checks": logic.get("common_checks", []),
        "safety_notes": logic.get("safety_notes", []),
    }
