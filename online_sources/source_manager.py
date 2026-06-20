import json
from pathlib import Path

from online_sources.nhtsa_vpic import decode_vin
from online_sources.obd_online import lookup_external_obd_local, lookup_carapi_obd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_config() -> dict:
    path = DATA_DIR / "online_sources_config.json"
    if not path.exists():
        return {"enabled": False}
    return json.loads(path.read_text(encoding="utf-8"))


def get_vehicle_from_vin(vin: str, model_year: str | None = None) -> dict:
    cfg = load_config()
    src = cfg.get("sources", {}).get("nhtsa_vpic", {})
    if not cfg.get("enabled") or not src.get("enabled"):
        return {"ok": False, "error": "NHTSA vPIC išjungtas"}
    return decode_vin(vin, model_year)


def enrich_obd_code(code: str) -> dict:
    cfg = load_config()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "Online šaltiniai išjungti"}

    local_result = lookup_external_obd_local(code)
    if local_result.get("ok"):
        return local_result

    carapi_cfg = cfg.get("sources", {}).get("carapi_obd", {})
    if carapi_cfg.get("enabled"):
        carapi_result = lookup_carapi_obd(code)
        if carapi_result.get("ok"):
            return carapi_result

    return {"ok": False, "error": "Papildomų duomenų nerasta"}
