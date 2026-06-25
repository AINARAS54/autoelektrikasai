import json
from pathlib import Path


def load_session_context(base_dir: Path, chat_id: str) -> dict:
    try:
        safe = "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))
        path = base_dir / "sessions" / f"{safe}.json"

        if not path.exists():
            return {}

        data = json.loads(path.read_text(encoding="utf-8"))

        return {
            "problem": data.get("problem"),
            "fault_title": data.get("fault_title"),
            "brand": data.get("brand"),
            "status": data.get("status"),
            "last_actions": data.get("actions", [])[-8:],
        }
    except Exception:
        return {}


def build_context(
    *,
    text: str,
    vehicle: dict,
    obd_code,
    voltage,
    voltage_context,
    brake_fluid_service: bool,
    local_fault,
    local_response: str,
    session_context: dict,
) -> dict:
    return {
        "vehicle": {
            "brand": vehicle.get("brand"),
            "model": vehicle.get("model"),
            "year": vehicle.get("year"),
            "is_ev_or_hybrid": vehicle.get("is_ev_or_hybrid"),
            "ev_rule": (
                "Jei EV/hibridas, nenaudoti termino generatorius. "
                "Naudoti DC/DC keitiklis, 12 V sistema, READY režimas, aukštos įtampos sistema."
            ),
        },
        "input": {
            "text": text,
            "obd_code": obd_code,
            "voltage": voltage,
            "voltage_context": voltage_context,
            "brake_fluid_service": brake_fluid_service,
        },
        "local_fault": local_fault,
        "local_response": local_response,
        "session": session_context,
        "rules": [
            "Nespėlioti ir nerašyti, kad detalė sugedusi, kol nėra patvirtinančio patikrinimo.",
            "Nerodyti kainų.",
            "Nerodyti diagnostikos ar remonto laiko.",
            "Atsakyti profesionaliai, bet suprantamai automobilio savininkui.",
            "Pateikti kitą logišką diagnostikos žingsnį.",
            "Nekartoti patikrinimų, kurie jau yra atlikti sesijos istorijoje.",
            "Naudoti terminą: Eksploatavimo įvertinimas.",
        ],
    }
