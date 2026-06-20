import os
import json
from pathlib import Path
import requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def lookup_external_obd_local(code: str) -> dict:
    code = (code or "").upper().strip()
    path = DATA_DIR / "external_obd_codes.json"

    if not path.exists():
        return {"ok": False, "source": "external_obd_json", "error": "Failas nerastas"}

    try:
        db = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "source": "external_obd_json", "error": str(exc)}

    item = db.get(code)
    if not item:
        return {"ok": False, "source": "external_obd_json", "error": "Kodas nerastas"}

    return {"ok": True, "source": "external_obd_json", "code": code, "data": item}


def lookup_carapi_obd(code: str) -> dict:
    token = os.getenv("CARAPI_TOKEN", "").strip()
    code = (code or "").upper().strip()

    if not token:
        return {"ok": False, "source": "carapi", "error": "CARAPI_TOKEN nenustatytas"}

    url = f"https://carapi.app/api/obd-codes/{code}"

    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if response.status_code == 404:
            return {"ok": False, "source": "carapi", "error": "Kodas nerastas"}
        response.raise_for_status()
        return {"ok": True, "source": "carapi", "code": code, "data": response.json()}
    except Exception as exc:
        return {"ok": False, "source": "carapi", "error": str(exc)}
