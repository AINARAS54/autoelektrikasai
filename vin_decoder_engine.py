"""VIN decoding for AutoElektrikas AI V33.

Uses NHTSA vPIC when available and falls back to deterministic VIN data
(WMI, model-year code, and a small verified platform map). The fallback never
invents trim, engine, or equipment data.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from online_sources.nhtsa_vpic import decode_vin as decode_vpic
except Exception:  # pragma: no cover
    decode_vpic = None

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

WMI_MAP: dict[str, dict[str, str]] = {
    "WBA": {"brand": "BMW", "manufacturer": "BMW AG", "country": "Germany"},
    "WBS": {"brand": "BMW", "manufacturer": "BMW M GmbH", "country": "Germany"},
    "WBY": {"brand": "BMW", "manufacturer": "BMW AG", "country": "Germany", "platform": "BMW i"},
    "WAU": {"brand": "Audi", "manufacturer": "Audi AG", "country": "Germany"},
    "WVW": {"brand": "Volkswagen", "manufacturer": "Volkswagen AG", "country": "Germany"},
    "WDD": {"brand": "Mercedes-Benz", "manufacturer": "Mercedes-Benz", "country": "Germany"},
    "WDB": {"brand": "Mercedes-Benz", "manufacturer": "Mercedes-Benz", "country": "Germany"},
    "JTD": {"brand": "Toyota", "manufacturer": "Toyota", "country": "Japan"},
    "JTJ": {"brand": "Lexus", "manufacturer": "Toyota", "country": "Japan"},
    "JN1": {"brand": "Nissan", "manufacturer": "Nissan", "country": "Japan"},
    "KMH": {"brand": "Hyundai", "manufacturer": "Hyundai", "country": "South Korea"},
    "KNA": {"brand": "Kia", "manufacturer": "Kia", "country": "South Korea"},
    "YV1": {"brand": "Volvo", "manufacturer": "Volvo Cars", "country": "Sweden"},
    "5YJ": {"brand": "Tesla", "manufacturer": "Tesla", "country": "United States"},
}

# VIN model-year code repeats every 30 years. Modern vehicles are resolved to
# 2010-2039; older code values fall back to 1980-2009 only when necessary.
YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"


def normalize_vin(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def is_valid_vin_format(vin: str) -> bool:
    return bool(VIN_RE.fullmatch(normalize_vin(vin)))


def decode_model_year(vin: str) -> int | None:
    vin = normalize_vin(vin)
    if len(vin) != 17:
        return None
    code = vin[9]
    if code not in YEAR_CODES:
        return None
    index = YEAR_CODES.index(code)
    modern_year = 2010 + index
    if modern_year <= 2039:
        return modern_year
    return 1980 + index


def _fallback_model(vin: str, brand: str | None) -> str | None:
    """Return only model mappings that are safe enough for local fallback."""
    if brand == "BMW" and vin.startswith("WBY"):
        # WBY was used for BMW i vehicles. The 7Z family is BMW i3.
        if vin[3:5] == "7Z" or vin[3:8].startswith("7Z"):
            return "i3"
    return None


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def decode_vin(vin: str) -> dict[str, Any]:
    vin = normalize_vin(vin)
    if not is_valid_vin_format(vin):
        return {"ok": False, "vin": vin, "error": "VIN turi būti 17 simbolių ir negali turėti I, O arba Q."}

    wmi = WMI_MAP.get(vin[:3], {})
    fallback_year = decode_model_year(vin)
    fallback_model = _fallback_model(vin, wmi.get("brand"))

    online: dict[str, Any] = {}
    if decode_vpic is not None:
        try:
            result = decode_vpic(vin)
            if result.get("ok"):
                online = result
        except Exception:
            online = {}

    brand = _clean(online.get("make")) or wmi.get("brand")
    model = _clean(online.get("model")) or fallback_model
    year_raw = _clean(online.get("model_year"))
    try:
        model_year = int(year_raw) if year_raw else fallback_year
    except (TypeError, ValueError):
        model_year = fallback_year

    return {
        "ok": bool(brand or model or model_year),
        "vin": vin,
        "brand": brand,
        "model": model,
        "model_year": model_year,
        "manufacturer": _clean(online.get("raw", {}).get("Manufacturer")) or wmi.get("manufacturer"),
        "body_class": _clean(online.get("body_class")),
        "vehicle_type": _clean(online.get("vehicle_type")),
        "fuel_type": _clean(online.get("fuel_type")),
        "engine_model": _clean(online.get("engine_model")),
        "plant_country": _clean(online.get("plant_country")) or wmi.get("country"),
        "platform": wmi.get("platform"),
        "source": online.get("source") if online else "VIN WMI/VDS fallback",
        "confidence": "official_decoder" if online else ("verified_local_map" if model else "wmi_only"),
    }


def merge_decoded_vehicle(existing: dict | None, decoded: dict) -> dict:
    """Merge VIN data without erasing user-provided vehicle/session details."""
    vehicle = dict(existing or {})
    vehicle["vin"] = decoded.get("vin") or vehicle.get("vin")

    if decoded.get("brand"):
        vehicle["brand"] = decoded["brand"]
    if decoded.get("model"):
        vehicle["model"] = decoded["model"]

    decoded_year = decoded.get("model_year")
    existing_year = vehicle.get("year")
    if not existing_year and decoded_year:
        vehicle["year"] = str(decoded_year)
    if decoded_year:
        vehicle["vin_model_year"] = str(decoded_year)

    for source_key, target_key in [
        ("manufacturer", "manufacturer"),
        ("body_class", "body_class"),
        ("vehicle_type", "vehicle_type"),
        ("fuel_type", "fuel_type"),
        ("engine_model", "engine_model"),
        ("plant_country", "plant_country"),
        ("platform", "platform"),
        ("source", "vin_source"),
        ("confidence", "vin_confidence"),
    ]:
        if decoded.get(source_key):
            vehicle[target_key] = decoded[source_key]
    return vehicle


def vin_message(vehicle: dict, active_diagnostic: bool) -> str:
    label = " ".join(str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x).strip()
    if not label:
        label = vehicle.get("brand") or "Modelio tiksliai nustatyti nepavyko"

    lines = ["🚗 <b>VIN gautas</b>", "", "Automobilis:", label, "", "VIN:", str(vehicle.get("vin") or "")]

    vin_year = str(vehicle.get("vin_model_year") or "")
    stated_year = str(vehicle.get("year") or "")
    if vin_year and stated_year and vin_year != stated_year:
        lines.extend(["", f"ℹ️ VIN modelio metai: {vin_year}; sesijoje nurodyti metai: {stated_year}."])

    if active_diagnostic:
        lines.extend(["", "✅ VIN susietas su aktyvia diagnostikos sesija. Ankstesnis gedimo aprašymas išsaugotas."])
    else:
        lines.extend(["", "Dabar apibūdinkite gedimą."])
    return "\n".join(lines)
