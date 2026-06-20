import requests

NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"


def decode_vin(vin: str, model_year: str | None = None) -> dict:
    vin = (vin or "").strip()
    if not vin:
        return {"ok": False, "error": "VIN nenurodytas"}

    url = f"{NHTSA_BASE}/DecodeVinValuesExtended/{vin}"
    params = {"format": "json"}
    if model_year:
        params["modelyear"] = model_year

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    results = data.get("Results") or []
    if not results:
        return {"ok": False, "error": "VIN duomenų nerasta"}

    row = results[0]
    return {
        "ok": True,
        "source": "NHTSA vPIC",
        "vin": vin,
        "make": row.get("Make") or "",
        "model": row.get("Model") or "",
        "model_year": row.get("ModelYear") or "",
        "vehicle_type": row.get("VehicleType") or "",
        "body_class": row.get("BodyClass") or "",
        "engine_model": row.get("EngineModel") or "",
        "fuel_type": row.get("FuelTypePrimary") or "",
        "plant_country": row.get("PlantCountry") or ""
    }
