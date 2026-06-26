LOCAL_OBD = {
    "P0300": {
        "meaning": "Atsitiktinis / kelių cilindrų uždegimo praleidimas.",
        "first_checks": [
            "Patikrinkite uždegimo žvakes.",
            "Patikrinkite uždegimo rites.",
            "Patikrinkite vakuumo nuotėkius ir kuro slėgį.",
        ],
    },
    "P0301": {
        "meaning": "1 cilindro uždegimo praleidimas.",
        "first_checks": [
            "Sukeiskite 1 cilindro uždegimo ritę su kitu cilindru ir stebėkite, ar klaida persikelia.",
            "Patikrinkite žvakę.",
            "Patikrinkite purkštuko darbą ir kompresiją.",
        ],
    },
    "P0420": {
        "meaning": "Katalizatoriaus efektyvumas žemiau ribos.",
        "first_checks": [
            "Patikrinkite išmetimo nuotėkius.",
            "Patikrinkite lambda zondų signalus.",
            "Įvertinkite katalizatoriaus būklę.",
        ],
    },
    "P0A80": {
        "meaning": "Hibridinės / EV baterijos paketo keitimo indikacija.",
        "first_checks": [
            "Nuskaitykite baterijos modulių įtampas.",
            "Patikrinkite elementų balansą.",
            "Patikrinkite BMS klaidas ir izoliacijos būseną.",
        ],
    },
}


def lookup_obd(code: str) -> dict:
    code = (code or "").strip().upper()
    if code in LOCAL_OBD:
        data = dict(LOCAL_OBD[code])
        data["ok"] = True
        data["code"] = code
        data["source"] = "Local OBD database"
        return data
    return {"ok": False, "code": code, "error": "Kodas vietinėje OBD bazėje nerastas."}


def format_obd_lookup(result: dict) -> str:
    if not result.get("ok"):
        return f"OBD kodas {result.get('code')} vietinėje bazėje nerastas."

    checks = result.get("first_checks") or []
    lines = [
        f"⚡ <b>OBD kodas: {result.get('code')}</b>",
        f"\nReikšmė:\n{result.get('meaning')}",
        "\n🔎 Rekomenduojama patikra:",
    ]
    for i, step in enumerate(checks, 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)
