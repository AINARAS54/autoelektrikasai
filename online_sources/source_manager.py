import re

from .nhtsa_vpic import decode_vin, format_vin_result
from .nhtsa_recalls import get_recalls, format_recalls
from .obd_database import lookup_obd, format_obd_lookup
from .procedure_library import find_procedure, format_procedure
from .openai_web_search import web_search_answer


def _detect_vin(text: str) -> str | None:
    clean = (text or "").replace(" ", "").upper()
    m = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", clean)
    return m.group(0) if m else None


def _detect_obd(text: str) -> str | None:
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None


def is_procedure_query(text: str) -> bool:
    t = (text or "").lower()
    terms = [
        "kaip", "reset", "nuresetinti", "atstatyti", "nustatyti iš naujo",
        "serviso interval", "adaptuoti", "kalibruoti", "programuoti",
        "pakeisti", "procedūra", "procedura"
    ]
    return any(x in t for x in terms)


def answer_from_sources(text: str, vehicle: dict | None = None) -> dict:
    """
    Pagrindinis išorinių šaltinių maršrutizatorius.
    Grąžina:
    {
      ok: bool,
      type: vin | obd | procedure | recall | web | none,
      answer: str,
      raw: dict
    }
    """
    vehicle = vehicle or {}

    vin = _detect_vin(text)
    if vin:
        result = decode_vin(vin)
        return {"ok": result.get("ok", False), "type": "vin", "answer": format_vin_result(result), "raw": result}

    obd = _detect_obd(text)
    if obd:
        result = lookup_obd(obd)
        return {"ok": result.get("ok", False), "type": "obd", "answer": format_obd_lookup(result), "raw": result}

    if is_procedure_query(text):
        proc = find_procedure(text, vehicle)
        if proc:
            return {"ok": True, "type": "procedure", "answer": format_procedure(proc), "raw": proc}

        search = web_search_answer(text, vehicle)
        if search.get("ok"):
            return {"ok": True, "type": "web", "answer": search.get("answer"), "raw": search}

        return {
            "ok": False,
            "type": "procedure",
            "answer": (
                "Tikslios patvirtintos procedūros vietinėje bazėje neradau. "
                "Kad išvengtume klaidų, nerekomenduoju remtis bendru atsakymu be patikimo šaltinio."
            ),
            "raw": search,
        }

    make = vehicle.get("brand") or vehicle.get("make")
    model = vehicle.get("model")
    year = vehicle.get("year") or vehicle.get("model_year")
    if make and model and year and "recall" in (text or "").lower():
        result = get_recalls(make, model, year)
        return {"ok": result.get("ok", False), "type": "recall", "answer": format_recalls(result), "raw": result}

    return {"ok": False, "type": "none", "answer": "", "raw": {}}
