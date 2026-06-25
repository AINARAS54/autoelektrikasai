from telegram_photo_handler import handle_photo_or_document
import os
import json
import re
import logging
import datetime
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from session_store import (
    create_or_update_session,
    add_user_action,
    get_session_summary,
    clear_session,
)

try:
    from online_sources.source_manager import get_vehicle_from_vin
except Exception:
    get_vehicle_from_vin = None

try:
    from vehicle_parser import parse_vehicle
    from diagnostic_context import load_session_context, build_context
    from openai_diagnostic import ask_openai_diagnostic
except Exception:
    parse_vehicle = None
    load_session_context = None
    build_context = None
    ask_openai_diagnostic = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ==========================================================
# AutoElektrikas AI - Telegram Webhook
# V8 FINAL app.py
# ==========================================================

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autoelektrikas_ai")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
app = Flask(__name__)


def load_json(name: str, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


FAULTS = load_json("top_100_faults_lt.json", [])
ALIASES = load_json("symptom_aliases_lt.json", {})
OBD = load_json("obd_codes_starter_lt.json", {})
BRANDS = load_json("brand_specific_lt.json", {})
FAULT_BY_ID = {f.get("id"): f for f in FAULTS if f.get("id")}


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram_api(method: str, payload: dict):
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is missing")
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=20)
        if not r.ok:
            logger.error("Telegram API error: %s %s", r.status_code, r.text)
        return r.json()
    except Exception as e:
        logger.exception("Telegram API request failed: %s", e)
        return None


def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)


def clean_menu():
    return {
        "inline_keyboard": [
            [{"text": "🧹 Išvalyti bylą", "callback_data": "clear"}],
        ]
    }


def start_menu():
    return None


def diagnostic_menu():
    return clean_menu()


def main_menu():
    return start_menu()


START_TEXT = """🚗 <b>AutoElektrikas AI</b>

Profesionali automobilių elektros ir elektronikos diagnostika.

📋 Įveskite automobilio duomenis ir apibūdinkite gedimą.

🔎 Taip pat galite įvesti VIN numerį."""


def normalize(text: str) -> str:
    return (text or "").lower().strip()


def detect_brand(text: str):
    t = normalize(text)
    for brand in BRANDS:
        if brand.lower() in t:
            return brand
    aliases = {
        "vw": "Volkswagen", "mb": "Mercedes-Benz", "mersedes": "Mercedes-Benz", "mersas": "Mercedes-Benz",
        "bmw": "BMW", "audi": "Audi", "volvo": "Volvo", "toyota": "Toyota", "ford": "Ford",
        "opel": "Opel", "peugeot": "Peugeot", "renault": "Renault",
    }
    for key, brand in aliases.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            return brand
    return None


def detect_model(text: str):
    t = normalize(text)
    models = ["i3", "i4", "i5", "i7", "ix", "f30", "f10", "e90", "e60", "g30", "golf", "passat", "tiguan", "touran", "a3", "a4", "a6", "q5", "q7", "corolla", "avensis", "yaris"]
    for model in models:
        if re.search(rf"\b{re.escape(model)}\b", t):
            return model.upper() if model.startswith(("f", "e", "g", "q")) else model
    return None


def detect_year(text: str):
    m = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", text)
    return m.group(1) if m else None


def detect_obd(text: str):
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", text.upper())
    return m.group(1) if m else None


def is_ev_vehicle(text: str, brand=None, model=None):
    t = normalize(text)
    ev_terms = ["elektromobil", "electric", "ev", "bev", "hybrid", "hibrid", "bmw i3", "bmw i4", "bmw i5", "bmw i7", "bmw ix"]
    if any(x in t for x in ev_terms):
        return True
    return brand == "BMW" and model and model.lower() in ["i3", "i4", "i5", "i7", "ix"]


def has_voltage_context(text: str) -> bool:
    """
    Įtampa laikoma matavimu tik tada, kai tekste yra aiškus matavimo kontekstas.
    Apsauga nuo klaidų:
    BMW i3 -> ne 3.0 V
    Audi A4 -> ne 4.0 V
    Q5 -> ne 5.0 V
    F30 -> ne 30.0 V
    """
    t = normalize(text)

    patterns = [
        r"\b\d{1,2}(?:[.,]\d{1,2})\s*v\b",
        r"\b\d{1,2}(?:[.,]\d{1,2})\s*volt",
        r"\bakum",
        r"\bbattery\b",
        r"\bbater",
        r"\b12v\b",
        r"\bdc\s*/?\s*dc\b",
        r"\bdcdc\b",
        r"\bkeitikl",
        r"\bkrov",
        r"\bkrauna",
        r"\bįkrov",
        r"\bikrov",
        r"\bgenerator",
    ]

    return any(re.search(pattern, t) for pattern in patterns)


def extract_voltage(text: str):
    """
    Leidžiami pavyzdžiai:
    - 12.7 V
    - 12,7 V
    - akumuliatorius 12.7
    - akumas 11,5
    - battery 12.5 V
    - DC/DC 13.9 V
    - generatorius 14.2 V

    Neleidžiami kaip matavimai:
    - BMW i3 2019
    - BMW i4
    - Audi A4
    - Q5
    - F30
    - E90
    """
    if not has_voltage_context(text):
        return None

    t = normalize(text)

    # 1) Aiškus formatas su V/volt
    m = re.search(r"\b(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:v|volt|voltų)\b", t)

    # 2) Kontekstas prieš skaičių, bet be V
    if not m:
        m = re.search(
            r"\b(?:akumuliatorius|akumas|battery|baterija|12v|dc\s*/?\s*dc|dcdc|keitiklis|krovimas|krauna|generatorius)"
            r"\D{0,25}(\d{1,2}[.,]\d{1,2})\b",
            t,
        )

    if not m:
        return None

    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None

    # 12 V automobilių sistemos ir krovimo ribos.
    # Nepriimame 3.0, 4.0, 5.0 ir pan., nes tai dažnai modeliai: i3, A4, Q5.
    if value < 5.0 or value > 18.0:
        return None

    return value


def voltage_context(text: str):
    t = normalize(text)
    if any(x in t for x in ["dc/dc", "dcdc", "dc dc", "keitiklis"]):
        return "dcdc"
    if any(x in t for x in ["generator", "krov", "krauna", "įkrov", "ikrov"]):
        return "charging"
    if any(x in t for x in ["akum", "bater", "12v"]):
        return "battery"
    return "battery"


def evaluate_battery_voltage(value: float):
    if value >= 12.6:
        return ("🟢", "Akumuliatoriaus įtampa normali", "Pagal pateiktą matavimą 12 V akumuliatorius nėra pagrindinė įtariama priežastis.", "🟢 Aukštas atitikimas", "🟢 Galima eksploatuoti, jei nėra kitų įspėjimų skydelyje.")
    if 12.4 <= value < 12.6:
        return ("🟡", "Akumuliatorius dalinai išsikrovęs", "Įtampa nėra kritinė, bet rekomenduojama patikrinti įkrovimą ir kontaktus.", "🟡 Vidutinis atitikimas", "🟡 Galima eksploatuoti ribotai.")
    if 12.2 <= value < 12.4:
        return ("🟠", "Akumuliatorius silpnas", "Įtampa žema. Gali būti sunkus užvedimas arba elektronikos klaidos.", "🟢 Aukštas atitikimas", "🟡 Galima eksploatuoti ribotai, bet gali neužsivesti po stovėjimo.")
    if 11.8 < value < 12.2:
        return ("🔴", "Akumuliatorius labai išsikrovęs", "Įtampa per maža. Reikalingas įkrovimas ir papildomas patikrinimas.", "🟢 Aukštas atitikimas", "🔴 Nerekomenduojama eksploatuoti, kol nepatikrinta 12 V sistema.")
    return ("🔴", "Kritinė akumuliatoriaus būklė", "Įtampa kritiškai maža. Gali neveikti automobilio elektronika.", "🟢 Aukštas atitikimas", "🔴 Nerekomenduojama eksploatuoti.")


def evaluate_charging_voltage(value: float, ev: bool):
    name = "DC/DC keitiklio krovimas" if ev else "Įkrovimo sistemos įtampa"
    if 13.8 <= value <= 14.8:
        return name, "🟢", "Krovimas leistinose ribose", "Pagal pateiktą matavimą krovimas yra normaliose ribose.", "🟢 Galima eksploatuoti, jei nėra kitų gedimo požymių."
    if 13.2 <= value < 13.8:
        return name, "🟠", "Krovimas per mažas", "Įtampa žemesnė nei įprasta. Reikalingas papildomas patikrinimas su apkrova.", "🟡 Galima eksploatuoti ribotai."
    if value < 13.2:
        return name, "🔴", "Krovimas per mažas", "Įtampa per maža. 12 V akumuliatorius gali būti nepakankamai kraunamas.", "🔴 Nerekomenduojama eksploatuoti, kol nepatikrinta 12 V sistema."
    return name, "🔴", "Krovimas per didelis", "Per didelė įtampa gali pažeisti 12 V elektroniką.", "🔴 Nerekomenduojama eksploatuoti."


def format_measurement_response(text, brand, model, year, ev):
    value = extract_voltage(text)
    if value is None:
        return None
    ctx = voltage_context(text)
    car_line = " ".join([x for x in [brand, model, year] if x]) or "Nenurodyta"

    if ctx == "battery":
        icon, title, detail, match, drive = evaluate_battery_voltage(value)
        checks = [
            "Patikrinti, ar įsijungia READY režimas" if ev else "Patikrinti įkrovimo sistemos veikimą",
            "Patikrinti DC/DC keitiklio 12 V krovimą" if ev else "Patikrinti akumuliatoriaus gnybtus ir masę",
            "Patikrinti 12 V akumuliatoriaus gnybtus ir masę" if ev else "Patikrinti, ar problema atsiranda po ilgesnio stovėjimo",
            "Patikrinti, ar skydelyje nėra EV sistemos įspėjimų" if ev else "Patikrinti srovės nuotėkį stovint",
        ]
        checks_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(checks)])
        return f"""📌 <b>Patikrinimo rezultatas</b>

🚗 Automobilis:
{esc(car_line)}

Patikrinta:
12 V akumuliatorius

Rezultatas:
<b>{value:.1f} V</b>

Vertinimas:
{icon} {esc(title)}

Išvada:
{esc(detail)}

Atitikimas:
{esc(match)}

🔍 Rekomenduojama diagnostikos eiga:
{checks_text}

🚦 Eksploatavimo įvertinimas:
{esc(drive)}"""

    name, icon, title, detail, drive = evaluate_charging_voltage(value, ev)
    checks = [
        "Patikrinti READY režimą" if ev else "Patikrinti generatoriaus diržą",
        "Pamatuoti 12 V įtampą READY režime" if ev else "Pamatuoti įtampą su elektros apkrova",
        "Patikrinti 12 V akumuliatoriaus gnybtus ir masę" if ev else "Patikrinti gnybtus ir masės jungtis",
    ]
    checks_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(checks)])
    return f"""📌 <b>Patikrinimo rezultatas</b>

🚗 Automobilis:
{esc(car_line)}

Patikrinta:
{esc(name)}

Rezultatas:
<b>{value:.1f} V</b>

Vertinimas:
{icon} {esc(title)}

Išvada:
{esc(detail)}

Atitikimas:
🟡 Vidutinis atitikimas

🔍 Rekomenduojama diagnostikos eiga:
{checks_text}

🚦 Eksploatavimo įvertinimas:
{esc(drive)}"""



def detect_brake_fluid_service(text: str) -> bool:
    t = normalize(text)
    terms = [
        "stabdžių skys",
        "stabdziu skys",
        "stabdžiu skys",
        "stabdzių skys",
        "stabdžių serviso",
        "stabdziu serviso",
        "brake fluid",
        "brake service",
    ]
    return any(term in t for term in terms)


def format_brake_fluid_response(brand, model, year):
    car_line = " ".join([x for x in [brand, model, year] if x]) or "Nenurodyta"
    return f"""📌 <b>Nustatyta problema</b>

🚗 Automobilis:
{esc(car_line)}

Nustatytas pranešimas:
Stabdžių skysčio aptarnavimo priminimas

Dažniausia priežastis:
Pasibaigęs stabdžių skysčio keitimo intervalas automobilio serviso sistemoje.

🎯 Galimos priežastys:
1. Stabdžių skysčio aptarnavimo intervalo priminimas
2. Žemas stabdžių skysčio lygis
3. Stabdžių skysčio lygio daviklio sutrikimas
4. Stabdžių sistemos nuotėkis

Atitikimas:
🟢 Aukštas atitikimas

🔍 Rekomenduojama diagnostikos eiga:
1. Patikrinti stabdžių skysčio lygį
2. Patikrinti, ar nėra skysčio nuotėkio
3. Patikrinti serviso pranešimą automobilio meniu
4. Jei skysčio lygis normalus – tikėtina, kad reikalingas serviso intervalo atstatymas

🚦 Eksploatavimo įvertinimas:
🟡 Galima eksploatuoti ribotai, jei stabdžiai veikia normaliai ir skysčio lygis nėra žemas."""


def score_fault(text, fault):
    t = normalize(text)
    score = 0
    for w in normalize(fault.get("title", "")).replace("/", " ").split():
        if len(w) > 3 and w in t:
            score += 3
    for cause in fault.get("common_causes", []):
        for w in normalize(cause).split():
            if len(w) > 5 and w in t:
                score += 1
    return score


def find_fault_from_text(text):
    t = normalize(text)
    for alias, ids in ALIASES.items():
        if alias in t and ids:
            return FAULT_BY_ID.get(ids[0])
    scored = sorted([(score_fault(text, f), f) for f in FAULTS], key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return None


def format_obd_response(code, brand, model, year):
    car_line = " ".join([x for x in [brand, model, year] if x]) or "Nenurodyta"
    if code in OBD:
        obd = OBD[code]
        checks_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(obd.get("first_checks", [])[:3])])
        return f"""⚡ <b>OBD kodas: {esc(code)}</b>

🚗 Automobilis:
{esc(car_line)}

Ką rodo kodas:
{esc(obd.get('meaning', 'Kodo aprašymas nerastas.'))}

Svarbu:
Klaidos kodas nėra galutinė diagnozė.

Atitikimas:
🟡 Vidutinis atitikimas

🔍 Rekomenduojama diagnostikos eiga:
{checks_text}

🚦 Eksploatavimo įvertinimas:
{esc(obd.get('operation_assessment', '🟡 Reikalingas papildomas patikrinimas'))}"""
    return f"""⚡ <b>OBD kodas: {esc(code)}</b>

Šio kodo dar nėra vietinėje bazėje.

Ką daryti dabar:
1. Parašykite automobilio markę, modelį ir metus.
2. Parašykite pagrindinį simptomą.
3. Jei yra daugiau klaidų kodų, įrašykite juos kartu.

Būsena:
🟡 Reikalingi papildomi duomenys."""


def format_fault_response(text, brand, model, year, ev):
    fault = find_fault_from_text(text)
    car_line = " ".join([x for x in [brand, model, year] if x]) or "Nenurodyta"
    if not fault:
        return f"""📌 <b>Problema užregistruota</b>

🚗 Automobilis:
{esc(car_line)}

Ką daryti dabar:
1. Parašykite, kas tiksliai neveikia.
2. Jei yra klaidos kodas, įrašykite jį.
3. Jei atlikote matavimą, parašykite rezultatą, pvz. 12.4 V.

Atitikimas:
⚪ Žemas atitikimas

Būsena:
🟡 Reikalinga papildoma informacija."""

    checks = fault.get("first_checks", [])[:3]
    causes = fault.get("common_causes", [])[:4]
    if ev:
        def ev_replace(s):
            return (s.replace("generatoriaus", "DC/DC keitiklio")
                     .replace("Generatoriaus", "DC/DC keitiklio")
                     .replace("generatorių", "DC/DC keitiklį")
                     .replace("generatorius", "DC/DC keitiklis")
                     .replace("įkrovimo sistemos", "12 V sistemos"))
        checks = [ev_replace(x) for x in checks]
        causes = [ev_replace(x) for x in causes]

    checks_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(checks)])
    causes_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(causes)])

    return f"""📌 <b>Nustatyta problema</b>

🚗 Automobilis:
{esc(car_line)}

Problema:
{esc(fault.get('title', 'Problema'))}

🎯 Galimos priežastys:
{causes_text}

Atitikimas:
🟡 Vidutinis atitikimas

🔍 Rekomenduojama diagnostikos eiga:
{checks_text}

🚦 Eksploatavimo įvertinimas:
{esc(fault.get('operation_assessment', '🟡 Reikalingas papildomas patikrinimas'))}"""


def diagnose_text(text):
    brand = detect_brand(text)
    model = detect_model(text)
    year = detect_year(text)
    ev = is_ev_vehicle(text, brand, model)

    # Specialus prioritetas: stabdžių skysčio / brake fluid pranešimai nėra įtampos matavimas.
    if detect_brake_fluid_service(text):
        return format_brake_fluid_response(brand, model, year)

    obd = detect_obd(text)
    if obd:
        return format_obd_response(obd, brand, model, year)

    measurement = format_measurement_response(text, brand, model, year, ev)
    if measurement:
        return measurement

    return format_fault_response(text, brand, model, year, ev)


def detect_intent(text: str, chat_id: str | None = None) -> str:
    t = normalize(text)
    question_words = [
        "kaip", "kur", "kodėl", "kodel", "ką reiškia", "ka reiskia",
        "kaip atlikti", "kaip padaryti", "kaip patikrinti", "kaip nuresetinti",
        "kaip resetinti", "reset", "nuresetinti", "atstatyti",
        "kur rasti", "kaip tai atlikti", "ką daryti", "ka daryti",
    ]
    if any(q in t for q in question_words) or "?" in text:
        return "question"
    if detect_obd(text):
        return "obd"
    if extract_voltage(text) is not None:
        return "measurement"
    brand = detect_brand(text)
    model = detect_model(text)
    year = detect_year(text)
    symptom_terms = [
        "neveikia", "neužsiveda", "neuzsiveda", "dega", "klaida", "pranešimas", "pranesimas",
        "dingsta", "mirksi", "nesikrauna", "nekrauna", "suka", "nesuka", "užgęsta", "uzgesta",
        "serviso", "service", "brake", "stabd", "abs", "airbag", "ready", "drive train",
    ]
    if (brand or model or year) and not any(s in t for s in symptom_terms):
        return "vehicle_only"
    return "diagnostic"


def get_session_context_safe(chat_id: str) -> dict:
    if load_session_context:
        try:
            return load_session_context(BASE_DIR, chat_id)
        except Exception:
            return {}
    return {}


def ask_openai_question(text: str, chat_id: str) -> str | None:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    brand = detect_brand(text)
    model = detect_model(text)
    year = detect_year(text)
    ev = is_ev_vehicle(text, brand, model)
    context = {
        "vehicle": {"brand": brand, "model": model, "year": year, "is_ev_or_hybrid": ev},
        "session": get_session_context_safe(chat_id),
        "user_question": text,
    }
    system_prompt = """
Tu esi profesionalus lengvųjų automobilių autoelektrikas.
Vartotojas uždavė klausimą, todėl nepradėk naujos diagnostikos.
Atsakyk į konkretų klausimą trumpai ir praktiškai.
Nerašyk kainų. Nerašyk remonto ar diagnostikos laiko.
EV / hibridui nenaudok termino „generatorius“.
Atsakyk lietuviškai.

Formatas:
📘 Atsakymas

...
"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        answer = (response.output_text or "").strip()
        return answer or None
    except Exception:
        logger.exception("OpenAI question answer failed")
        return None


def local_question_answer(text: str) -> str:
    t = normalize(text)
    if "brake fluid" in t or "stabd" in t or "idrive" in t:
        return """📘 <b>Atsakymas</b>

BMW i3 stabdžių skysčio aptarnavimo priminimo atstatymas dažniausiai atliekamas per serviso meniu.

Bendra eiga:
1. Įjunkite automobilį į READY arba diagnostikos režimą.
2. Atidarykite iDrive meniu.
3. Eikite į Service / Vehicle status / Service requirements.
4. Pasirinkite Brake Fluid.
5. Pasirinkite Reset arba Confirm reset.
6. Patvirtinkite veiksmą.

Jei meniu neleidžia atstatyti:
1. Patikrinkite, ar tikrai atliktas stabdžių skysčio aptarnavimas.
2. Patikrinkite, ar nėra aktyvių stabdžių sistemos klaidų.
3. Atstatymą atlikite diagnostikos įranga.

Pastaba: meniu pavadinimai gali skirtis pagal iDrive versiją."""
    return """📘 <b>Atsakymas</b>

Parašykite, kokį veiksmą norite atlikti arba kokią sistemą tikrinate.
Atsakysiu į konkretų techninį klausimą nepradėdamas naujos diagnostikos."""


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V8 FINAL",
        "modules": {
            "vehicle_parser": parse_vehicle is not None,
            "diagnostic_context": build_context is not None,
            "openai_diagnostic": ask_openai_diagnostic is not None,
        },
        "openai_env": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "time": datetime.datetime.now(datetime.UTC).isoformat()
    })


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        data = cq.get("data", "")

        if data == "clear":
            clear_session(chat_id)
            send_message(chat_id, "Diagnostikos byla išvalyta. Galite pradėti iš naujo.", start_menu())
        elif data in ["new_diag", "add_action", "continue_diag", "summary"]:
            send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą arba patikros rezultatą.", start_menu())
        else:
            send_message(chat_id, "Pasirinkimas neatpažintas.", start_menu())
        return jsonify({"ok": True})

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = (message.get("text") or "").strip()

    if not chat_id:
        return jsonify({"ok": True})

    if text.lower() in ["/start", "start"]:
        send_message(chat_id, START_TEXT, start_menu())
        return jsonify({"ok": True})

    if not text:
        send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        return jsonify({"ok": True})

    clean_text = text.replace(" ", "").strip()
    if len(clean_text) == 17 and clean_text.isalnum() and get_vehicle_from_vin:
        vin_result = get_vehicle_from_vin(clean_text)
        if vin_result.get("ok"):
            vin_msg = f"""🚗 <b>VIN dekodavimas</b>

Šaltinis:
{esc(vin_result.get('source'))}

Markė:
{esc(vin_result.get('make'))}

Modelis:
{esc(vin_result.get('model'))}

Metai:
{esc(vin_result.get('model_year'))}

Kėbulas:
{esc(vin_result.get('body_class') or 'Nenurodyta')}

Variklis:
{esc(vin_result.get('engine_model') or 'Nenurodyta')}

Kuro tipas:
{esc(vin_result.get('fuel_type') or 'Nenurodyta')}

Toliau parašykite gedimą."""
            send_message(chat_id, vin_msg, diagnostic_menu())
            return jsonify({"ok": True})

    intent = detect_intent(text, chat_id)

    if intent == "question":
        send_message(chat_id, "📥 <b>Klausimas gautas</b>\n\n🔍 Ruošiamas atsakymas...")
        answer = ask_openai_question(text, chat_id) or local_question_answer(text)
        send_message(chat_id, answer, clean_menu())
        return jsonify({"ok": True})

    if intent == "vehicle_only":
        try:
            create_or_update_session(chat_id, text, {"status": "Laukiamas gedimo aprašymas", "brand": detect_brand(text), "fault": None})
        except Exception:
            logger.exception("Session update failed")
        send_message(chat_id, "🚗 <b>Automobilio duomenys gauti</b>\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok": True})

    send_message(chat_id, "📥 <b>Informacija gauta</b>\n\n🔍 Atliekama diagnostinė analizė...")

    local_response = diagnose_text(text)
    response = local_response

    try:
        if parse_vehicle and load_session_context and build_context and ask_openai_diagnostic:
            vehicle = parse_vehicle(text, BRANDS)
            voltage_value = extract_voltage(text)
            context = build_context(
                text=text,
                vehicle=vehicle,
                obd_code=detect_obd(text),
                voltage=voltage_value,
                voltage_context=voltage_context(text) if voltage_value is not None else None,
                brake_fluid_service=detect_brake_fluid_service(text),
                local_fault=find_fault_from_text(text),
                local_response=local_response,
                session_context=load_session_context(BASE_DIR, chat_id),
            )
            ai_response = ask_openai_diagnostic(
                user_text=text,
                context=context,
                local_response=local_response,
            )
            if ai_response:
                response = ai_response
    except Exception:
        logger.exception("OpenAI module integration failed")
        response = local_response

    try:
        create_or_update_session(chat_id, text, {"status": "🟡 Reikalingas papildomas patikrinimas", "brand": detect_brand(text), "fault": None})
    except Exception:
        logger.exception("Session update failed")

    send_message(chat_id, response, clean_menu())
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
