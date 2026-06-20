import json
import re
from pathlib import Path
try:
    from online_sources.source_manager import enrich_obd_code
except Exception:
    enrich_obd_code = None

DATA_DIR = Path(__file__).parent / "data"

def load_json(name, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

FAULTS = load_json("top_100_faults_lt.json", [])
ALIASES = load_json("symptom_aliases_lt.json", {})
OBD = load_json("obd_codes_starter_lt.json", {})
BRANDS = load_json("brand_specific_lt.json", {})

FAULT_BY_ID = {f["id"]: f for f in FAULTS}


def normalize(text: str) -> str:
    return text.lower().strip()


def detect_brand(text: str):
    t = normalize(text)
    for brand in BRANDS:
        if brand.lower() in t:
            return brand
    # Common aliases
    aliases = {
        "vw": "Volkswagen",
        "mb": "Mercedes-Benz",
        "mersedes": "Mercedes-Benz",
        "mersas": "Mercedes-Benz",
    }
    for key, brand in aliases.items():
        if key in t:
            return brand
    return None


def detect_obd(text: str):
    match = re.search(r"\b([PBUC][0-9A-F]{4})\b", text.upper())
    if match:
        return match.group(1)
    return None


def score_fault(text: str, fault: dict) -> int:
    t = normalize(text)
    score = 0

    title_words = [w for w in normalize(fault["title"]).replace("/", " ").split() if len(w) > 3]
    for w in title_words:
        if w in t:
            score += 3

    system_words = [w for w in normalize(fault.get("system", "")).replace("/", " ").split() if len(w) > 4]
    for w in system_words:
        if w in t:
            score += 1

    for cause in fault.get("common_causes", []):
        for w in normalize(cause).split():
            if len(w) > 5 and w in t:
                score += 1

    return score


def diagnose_user_text(text: str):
    obd_code = detect_obd(text)
    brand = detect_brand(text)
    t = normalize(text)

    if obd_code and obd_code in OBD:
        obd = OBD[obd_code]
        linked = [FAULT_BY_ID[x] for x in obd.get("linked_faults", []) if x in FAULT_BY_ID]
        fault = linked[0] if linked else None
        return {
            "type": "obd",
            "input": text,
            "obd_code": obd_code,
            "obd": obd,
            "fault": fault,
            "brand": brand,
            "brand_data": BRANDS.get(brand) if brand else None,
            "confidence": "Vidutinis atitikimas",
            "status": "🟡 Reikalingas papildomas patikrinimas"
        }

    if obd_code and enrich_obd_code:
        ext = enrich_obd_code(obd_code)
        if ext.get("ok"):
            return {
                "type": "obd_external",
                "input": text,
                "obd_code": obd_code,
                "external": ext,
                "brand": brand,
                "brand_data": BRANDS.get(brand) if brand else None,
                "confidence": "Žemas atitikimas",
                "status": "🟡 Reikalingas papildomas patikrinimas"
            }

    alias_matches = []
    for alias, ids in ALIASES.items():
        if alias in t:
            alias_matches.extend(ids)

    if alias_matches:
        first_id = alias_matches[0]
        fault = FAULT_BY_ID.get(first_id)
    else:
        scored = sorted(
            [(score_fault(text, f), f) for f in FAULTS],
            key=lambda x: x[0],
            reverse=True
        )
        fault = scored[0][1] if scored and scored[0][0] > 0 else None

    if not fault:
        return {
            "type": "unknown",
            "input": text,
            "brand": brand,
            "brand_data": BRANDS.get(brand) if brand else None,
            "confidence": "Žemas",
            "status": "🟡 Reikalinga papildoma informacija"
        }

    brand_note = None
    if brand and brand in BRANDS and fault["id"] in BRANDS[brand].get("priority_fault_ids", []):
        brand_note = f"{brand}: ši problema patenka į dažnesnių tikrinimo sričių sąrašą."

    return {
        "type": "fault",
        "input": text,
        "fault": fault,
        "brand": brand,
        "brand_data": BRANDS.get(brand) if brand else None,
        "brand_note": brand_note,
        "confidence": "Vidutinis",
        "status": fault.get("status_default", "🟡 Reikalingas papildomas patikrinimas")
    }


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_user_response(result: dict) -> str:
    if result["type"] == "unknown":
        brand_line = f"\n🚗 Automobilis: <b>{esc(result['brand'])}</b>" if result.get("brand") else ""
        return f"""📌 <b>Problema užregistruota</b>{brand_line}

Ką nustatė sistema:
Turimų duomenų nepakanka priežasčiai patvirtinti.

Ką daryti dabar:
1. Parašykite markę, modelį ir metus, jei žinote.
2. Parašykite, kas tiksliai neveikia.
3. Jei yra klaida skydelyje, įkelkite tekstą arba OBD kodą.

Būsena:
{result['status']}"""

    if result["type"] == "obd_external":
        ext = result.get("external", {})
        data = ext.get("data", {})
        desc = data.get("description") or data.get("meaning") or str(data)
        return f"""⚡ <b>{esc(result['obd_code'])}</b>

Šaltinis:
{esc(ext.get('source', 'išorinis šaltinis'))}

Ką nustatė sistema:
{esc(desc)}

Atitikimas:
⚪ Žemas atitikimas

Būsena:
🟡 Išorinis šaltinis naudojamas tik papildymui. Kodo reikšmė nėra galutinė diagnozė.

Ką daryti dabar:
1. Patikrinkite, ar yra papildomų klaidų kodų.
2. Parašykite automobilio markę, modelį ir metus.
3. Parašykite pagrindinį simptomą."""

    if result["type"] == "obd":
        obd = result["obd"]
        fault = result.get("fault")
        first_checks = obd.get("first_checks", [])[:3]
        checks = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(first_checks)])
        related = f"\nSusijusi sritis: <b>{esc(fault['title'])}</b>" if fault else ""
        return f"""⚡ <b>{esc(result['obd_code'])}</b>{related}

Ką nustatė sistema:
{esc(obd.get('meaning', 'Kodo aprašymas nerastas.'))}

Ką daryti dabar:
{checks}

Būsena:
🟡 Kodo reikšmė nėra galutinė diagnozė.

Eksploatavimo įvertinimas:
{esc(obd.get('operation_assessment', '🟡 Reikalingas papildomas patikrinimas'))}

⏱️ Diagnostikos laikas:
{esc(obd.get('diagnostic_time', '30–90 min.'))}"""

    fault = result["fault"]
    checks = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(fault.get("first_checks", [])[:3])])
    brand_note = f"\n\nPastaba pagal markę:\n{esc(result['brand_note'])}" if result.get("brand_note") else ""

    return f"""📌 <b>Problema</b>
{esc(fault['title'])}

Ką nustatė sistema:
{esc(fault['what_system_detects'])}

Ką daryti dabar:
{checks}

Būsena:
{esc(fault.get('status_default'))}

Eksploatavimo įvertinimas:
{esc(fault.get('operation_assessment'))}

⏱️ Diagnostikos laikas:
{esc(fault.get('diagnostic_time'))}

⏱️ Remonto laikas:
{esc(fault.get('repair_time'))}{brand_note}"""
