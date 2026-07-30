import json
import re
from pathlib import Path
from typing import Any

TRUSTED_STATUSES = {"verified", "vin_specific", "manufacturer"}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _slug(value: Any, fallback: str) -> str:
    text = _norm(value)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or fallback


def vehicle_record_path(base_dir: Path, ctx: dict) -> Path:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    brand = _slug(vehicle.get("brand"), "unknown_brand")
    model = _slug(vehicle.get("model"), "unknown_model")
    year = _slug(vehicle.get("year"), "unknown_year")
    return Path(base_dir) / "vehicle_database" / brand / model / year / "component_locations.json"


def load_vehicle_record(base_dir: Path, ctx: dict) -> dict:
    path = vehicle_record_path(base_dir, ctx)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_verified_topic(base_dir: Path, ctx: dict, topic: str) -> dict | None:
    record = load_vehicle_record(base_dir, ctx)
    entry = (record.get("topics") or {}).get(topic)
    if not isinstance(entry, dict):
        return None

    status = _norm(entry.get("verification"))
    if status not in TRUSTED_STATUSES:
        return None

    required_vin = _norm(entry.get("vin"))
    if required_vin:
        vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
        actual_vin = _norm(vehicle.get("vin") or ctx.get("vin"))
        if actual_vin != required_vin:
            return None

    return entry


def available_topics(base_dir: Path, ctx: dict) -> set[str]:
    record = load_vehicle_record(base_dir, ctx)
    topics = record.get("topics") or {}
    available: set[str] = set()
    for topic in topics:
        if get_verified_topic(base_dir, ctx, topic):
            available.add(topic)
    return available
