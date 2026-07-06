import re
from context_engine import is_12v_battery_text

def n(text): return (text or "").lower().strip()

def detect_obd(text: str):
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None

def is_price_query(text: str) -> bool:
    t = n(text)
    return any(x in t for x in ["kiek kainuoja","kokia kaina","kiek atsieina","kiek kainuos","kiek gali kainuoti","kainos","kaina","kainuoti","remontas"])

def is_hv_battery(text: str) -> bool:
    t = n(text)
    return any(x in t for x in ["bater", "hv", "aukštos įtampos", "aukstos itampos", "soh", "nuvažiuoja", "nuvaziuoja", "rida"]) and not is_12v_battery_text(text)

def is_procedure(text: str) -> bool:
    t = n(text)
    return any(x in t for x in ["kaip","reset","nureset","nunul","atstat","adapt","registr","pakeisti","keisti","proced"])

def detect_intent(text: str, ctx: dict | None = None) -> str:
    t = n(text)
    if t in ["/start","start"]:
        return "START"
    if t in ["/newcase","/new","nauja byla","pradėti naują bylą","pradeti nauja byla","nauja diagnostika"]:
        return "NEW_CASE"
    if t in ["/clear","išvalyti bylą","isvalyti byla"]:
        return "CLEAR"
    clean = text.replace(" ", "").strip().upper()
    if len(clean) == 17 and clean.isalnum():
        return "VIN"
    if detect_obd(text):
        return "OBD"
    if is_price_query(text):
        return "PRICE"
    if is_12v_battery_text(text) and is_procedure(text):
        return "PROCEDURE_12V_BATTERY"
    if is_procedure(text):
        return "PROCEDURE"
    if is_hv_battery(text):
        return "EV_BATTERY"
    return "QUESTION"
