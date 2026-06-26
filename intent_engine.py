import re


def normalize(text: str) -> str:
    return (text or "").lower().strip()


def detect_obd(text: str) -> str | None:
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None


def is_price_query(text: str) -> bool:
    t = normalize(text)
    return any(term in t for term in [
        "kiek kainuoja", "kokia kaina", "kiek atsieina", "kiek kainuos",
        "remonto kaina", "dalies kaina", "modulio kaina", "modulių kaina",
        "baterijos kaina", "programinės įrangos", "programines irangos",
        "software update", "update kaina", "atnaujinti", "atnaujinimas", "remontas"
    ])


def is_procedure_query(text: str) -> bool:
    t = normalize(text)
    return any(term in t for term in [
        "kaip", "reset", "nuresetinti", "nunulinti", "atstatyti",
        "serviso interval", "brake fluid", "stabdžių skys", "stabdziu skys",
        "procedūra", "procedura", "adaptuoti", "kalibruoti", "registruoti"
    ])


def detect_intent(text: str, ctx: dict | None = None) -> str:
    t = normalize(text)
    ctx = ctx or {}

    if text.strip().lower() in ["/start", "start"]:
        return "START"

    if t in ["/newcase", "/new", "nauja byla", "pradėti naują bylą", "pradeti nauja byla", "nauja diagnostika", "pradėti iš naujo", "pradeti is naujo"]:
        return "NEW_CASE"

    if t in ["/clear", "išvalyti bylą", "isvalyti byla"]:
        return "CLEAR"

    if is_price_query(text):
        return "PRICE"

    if detect_obd(text):
        return "OBD"

    if is_procedure_query(text):
        return "PROCEDURE"

    if any(x in t for x in ["bater", "talpa", "soh", "nuvažiuoja", "nuvaziuoja", "rida"]):
        return "EV_BATTERY"

    if "?" in text or any(x in t for x in ["kodėl", "kodel", "kur", "ką reiškia", "ka reiskia"]):
        return "QUESTION"

    return "DIAGNOSTIC"
