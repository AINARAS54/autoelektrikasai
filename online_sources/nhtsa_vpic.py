import requests
from .cache import get_cache, set_cache


VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"


def decode_vin(vin: str, timeout: int = 15) -> dict:
    vin = (vin or "").strip().upper().replace(" ", "")
    if len(vin) != 17:
        return {"ok": False, "error": "VIN turi būti 17 simbolių.", "vin": vin}

    cache_key = f"vpic_{vin}"
    cached = get_cache(cache_key, max_age_seconds=60 * 60 * 24 * 30)
    if cached:
        return cached

    try:
        url = VPIC_URL.format(vin=vin)
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        row = (data.get("Results") or [{}])[0]

        result = {
            "ok": True,
            "source": "NHTSA vPIC",
            "vin": vin,
            "make": row.get("Make") or None,
            "model": row.get("Model") or None,
            "model_year": row.get("ModelYear") or None,
            "body_class": row.get("BodyClass") or None,
            "vehicle_type": row.get("VehicleType") or None,
            "fuel_type": row.get("FuelTypePrimary") or None,
            "fuel_type_secondary": row.get("FuelTypeSecondary") or None,
            "engine_model": row.get("EngineModel") or None,
            "plant_country": row.get("PlantCountry") or None,
            "raw": row,
        }
        set_cache(cache_key, result)
        return result

    except Exception as exc:
        return {"ok": False, "source": "NHTSA vPIC", "vin": vin, "error": str(exc)}


def format_vin_result(result: dict) -> str:
    if not result.get("ok"):
        return f"VIN nepavyko dekoduoti: {result.get('error', 'nežinoma klaida')}"

    lines = ["🚗 <b>VIN duomenys</b>"]
    if result.get("make") or result.get("model") or result.get("model_year"):
        lines.append(f"\nAutomobilis: {result.get('make') or ''} {result.get('model') or ''} {result.get('model_year') or ''}".strip())
    lines.append(f"VIN: {result.get('vin')}")
    if result.get("fuel_type"):
        lines.append(f"Kuro tipas: {result.get('fuel_type')}")
    if result.get("body_class"):
        lines.append(f"Kėbulas: {result.get('body_class')}")
    lines.append("\nDabar apibūdinkite gedimą.")
    return "\n".join(lines)
