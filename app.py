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
    from online_sources.source_manager import answer_from_sources
except Exception:
    answer_from_sources = None

try:
    from online_sources.nhtsa_vpic import decode_vin, format_vin_result
except Exception:
    decode_vin = None
    format_vin_result = None

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

try:
    from telegram_photo_handler import handle_photo_or_document
except Exception:
    handle_photo_or_document = None

# ==========================================================
# AutoElektrikas AI - Telegram Webhook
# V13 FINAL app.py
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
            [{"text": "📂 Nauja byla", "callback_data": "new_case"}],
        ]
    }


def start_menu():
    return None


def diagnostic_menu():
    return clean_menu()


def main_menu():
    return start_menu()


START_TEXT = """🚗 <b>AutoElektrikas AI</b>

Automobilių elektros ir elektronikos diagnostikos asistentas.

📋 Įveskite automobilio duomenis ir apibūdinkite gedimą.

📎 Galite pateikti papildomą informaciją: kėbulo numerį (VIN), techninio paso duomenis, prietaisų skydelio pranešimus ar diagnostikos rezultatus – tai padės tiksliau nustatyti gedimą."""


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
    if is_price_query(text):
        return "price"
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
Nerašyk kainų. Nerašyk remonto ar diagnostikos laiko. Serviso atstatymui nevartok žodžių „nulaužti“, „nulaužimas“, „nulaužimui“.
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



def generate_case_title(vehicle: dict | None, fault_text: str | None = None) -> str:
    vehicle = vehicle or {}
    parts = [
        vehicle.get("brand"),
        vehicle.get("model"),
        str(vehicle.get("year")) if vehicle.get("year") else None,
    ]
    car = " ".join([p for p in parts if p]).strip()

    fault = (fault_text or "").strip()
    if fault:
        short_fault = fault.lower()
        for remove in ["bmw", "audi", "vw", "volkswagen", "mercedes", "2019", "2018", "2020", "2021", "2022", "2023", "2024", "2025"]:
            short_fault = short_fault.replace(remove, "")
        short_fault = re.sub(r"\s+", " ", short_fault).strip(" .,-")
        if len(short_fault) > 55:
            short_fault = short_fault[:55].rstrip() + "..."
    else:
        short_fault = "nauja diagnostika"

    if car:
        return f"{car} – {short_fault or 'nauja diagnostika'}"
    return short_fault or "Nauja diagnostikos byla"


def vehicle_from_vision_result(vision_result: dict | None) -> dict:
    if not vision_result:
        return {}
    vehicle = vision_result.get("vehicle") or {}
    return {
        "brand": vehicle.get("brand"),
        "model": vehicle.get("model"),
        "year": vehicle.get("year"),
        "vin": vehicle.get("vin"),
        "registration_number": vehicle.get("registration_number"),
        "fuel_type": vehicle.get("fuel_type"),
        "vehicle_type": vehicle.get("vehicle_type"),
    }


def sessions_dir() -> Path:
    path = BASE_DIR / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_dir() -> Path:
    path = BASE_DIR / "cases_archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))


def active_session_path(chat_id: str) -> Path:
    return sessions_dir() / f"{safe_chat_id(chat_id)}.json"


def read_active_session(chat_id: str) -> dict:
    path = active_session_path(chat_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def archive_current_case(chat_id: str) -> str | None:
    src = active_session_path(chat_id)
    if not src.exists():
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    now = datetime.datetime.now(datetime.UTC)
    case_id = data.get("case_id") or f"AE-{now.strftime('%Y%m%d-%H%M%S')}-{safe_chat_id(chat_id)}"
    data["case_id"] = case_id
    data["status"] = data.get("status") or "Sustabdyta"
    data["archived_at"] = now.isoformat()
    dst = archive_dir() / f"{case_id}.json"
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        src.unlink()
    except Exception:
        try:
            clear_session(chat_id)
        except Exception:
            pass
    return case_id


def start_new_case(chat_id: str) -> str | None:
    return archive_current_case(chat_id)


def is_case_command(text: str) -> str | None:
    t = normalize(text)
    if t in ["/newcase", "/new", "nauja byla", "pradėti naują bylą", "pradeti nauja byla", "nauja diagnostika", "pradėti iš naujo", "pradeti is naujo"]:
        return "new_case"
    if t in ["/clear", "išvalyti bylą", "isvalyti byla", "trinti bylą", "trinti byla"]:
        return "clear"
    if t in ["/close", "uždaryti bylą", "uzdaryti byla", "baigti bylą", "baigti byla"]:
        return "close"
    return None


def is_price_query(text: str) -> bool:
    t = normalize(text)
    return any(term in t for term in [
        "kiek kainuoja", "kokia kaina", "kiek atsieina", "kiek kainuos",
        "remonto kaina", "dalies kaina", "modulio kaina", "modulių kaina",
        "baterijos kaina", "programinės įrangos", "programines irangos",
        "software update", "update kaina", "atnaujinti", "atnaujinimas"
    ])


def compact_vehicle_image_text(result: dict) -> str | None:
    if not result or not result.get("ok") or result.get("document_type") != "registration_document":
        return None
    vehicle = result.get("vehicle") or {}
    car = " ".join([str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x]).strip()
    lines = ["🚗 <b>Automobilio duomenys nuskaityti</b>"]
    if car:
        lines.append(f"\n🚘 {esc(car)}")
    if vehicle.get("vin"):
        lines.append(f"🔑 VIN: {esc(vehicle.get('vin'))}")
    if vehicle.get("registration_number"):
        lines.append(f"🔖 Nr.: {esc(vehicle.get('registration_number'))}")
    lines.append("\n✅ Byla atnaujinta.")
    lines.append("✍️ Apibūdinkite gedimą.")
    return "\n".join(lines)


def current_vehicle_from_text_or_session(text: str, chat_id: str) -> dict:
    vehicle = {}
    session = read_active_session(chat_id)
    if isinstance(session.get("vehicle"), dict):
        vehicle.update(session.get("vehicle"))
    brand = detect_brand(text)
    model = detect_model(text)
    year = detect_year(text)
    if brand:
        vehicle["brand"] = brand
    if model:
        vehicle["model"] = model
    if year:
        vehicle["year"] = year
    return vehicle


def normalize_vehicle_for_sources(vehicle: dict) -> dict:
    result = dict(vehicle or {})
    if "make" not in result and result.get("brand"):
        result["make"] = result.get("brand")
    if "model_year" not in result and result.get("year"):
        result["model_year"] = result.get("year")
    return result


def is_bmw_i3_brake_fluid_reset(text: str, vehicle: dict | None = None) -> bool:
    t = normalize(text)
    vehicle = vehicle or {}
    brand = normalize(str(vehicle.get("brand") or vehicle.get("make") or ""))
    model = normalize(str(vehicle.get("model") or ""))
    has_bmw = "bmw" in t or brand == "bmw"
    has_i3 = re.search(r"\bi3\b", t) is not None or model == "i3"
    has_brake_fluid = "stabdziu skys" in t or "stabdžių skys" in t or "brake fluid" in t or ("stabd" in t and "skys" in t)
    has_reset = any(x in t for x in ["reset", "nureset", "nunul", "atstat", "panaikinti", "isjungti", "išjungti"])
    return has_bmw and has_i3 and has_brake_fluid and has_reset


def bmw_i3_brake_fluid_reset_answer() -> str:
    return """📘 <b>BMW i3 stabdžių skysčio serviso intervalo atstatymas</b>

Automobilis:
BMW i3

Žingsniai:
1. Įjunkite degimą nepaspausdami stabdžio pedalo, kad automobilis būtų Accessory / diagnostikos režime.
2. Palaukite, kol prietaisų skydelyje išnyks pradiniai pranešimai.
3. Paspauskite ir laikykite kairėje prietaisų skydelio pusėje esantį odometro / kelionės atstumo mygtuką apie 10 sekundžių, kol atsivers techninės priežiūros meniu.
4. Trumpais paspaudimais pereikite iki punkto Brake Fluid.
5. Kai rodoma Reset possible, paspauskite ir palaikykite mygtuką apie 3 sekundes, kol pasirodys Reset?.
6. Dar kartą paspauskite ir palaikykite mygtuką, kol prasidės atstatymas.
7. Baigus procedūrą, prietaisų skydelyje turi būti rodoma nauja stabdžių skysčio aptarnavimo data arba intervalas.

Pastabos:
• Jei atstatymas nepavyksta arba pranešimas sugrįžta, patikrinkite stabdžių skysčio lygį, lygio daviklį ir DSC/ABS klaidas.
• Jei meniu šios funkcijos nerodo, atlikite atstatymą diagnostikos įranga, pvz. ISTA, Autel, Launch ar Bosch.
• Naudotina formuluotė: serviso intervalo atstatymas."""


def is_source_query(text: str) -> bool:
    t = normalize(text)
    if detect_obd(text):
        return True
    return any(term in t for term in [
        "kaip", "reset", "nuresetinti", "nunulinti", "atstatyti",
        "serviso interval", "brake fluid", "stabdžių skys", "stabdziu skys",
        "procedūra", "procedura", "adaptuoti", "kalibruoti"
    ])


def answer_from_online_sources(text: str, chat_id: str) -> str | None:
    vehicle = normalize_vehicle_for_sources(current_vehicle_from_text_or_session(text, chat_id))
    if is_bmw_i3_brake_fluid_reset(text, vehicle):
        return bmw_i3_brake_fluid_reset_answer()
    if not answer_from_sources:
        return None
    try:
        result = answer_from_sources(text, vehicle)
        if result and (result.get("ok") or result.get("answer")):
            answer = result.get("answer")
            if answer:
                answer = answer.replace("nulaužim", "atstatym").replace("nulaužti", "atstatyti")
                return answer
    except Exception:
        logger.exception("online_sources answer failed")
    return None


def format_price_response(text: str, chat_id: str) -> str:
    hv_price = format_hv_battery_price(text, chat_id)
    if hv_price:
        return hv_price

    t = normalize(text)
    vehicle = current_vehicle_from_text_or_session(text, chat_id)
    brand = vehicle.get("brand") or vehicle.get("make") or detect_brand(text)
    model = vehicle.get("model") or detect_model(text)
    year = vehicle.get("year") or vehicle.get("model_year") or detect_year(text)
    car = " ".join([str(x) for x in [brand, model, year] if x]).strip() or "Nenurodytas automobilis"

    if "bater" in t and "modul" in t:
        return f"""💰 <b>Apytikslė dalių kaina</b>

Automobilis:
{esc(car)}

Baterijos moduliai:
• Naudotas modulis: apie 300–800 €
• Restauruotas modulis: apie 600–1200 €
• Naujas modulis: apie 1500–3000 €+

Tiksli kaina priklauso nuo baterijos versijos, modulio numerio, būklės ir tiekėjo.

Pastaba:
Aukštos įtampos baterijos darbams reikalinga EV saugos kvalifikacija."""

    if any(x in t for x in ["program", "software", "atnauj"]):
        return f"""💰 <b>Programinės įrangos atnaujinimas</b>

Automobilis:
{esc(car)}

Orientacinė kaina:
• Nepriklausomas servisas: apie 100–300 €
• Oficialus atstovas: apie 200–500 €+

Kaina priklauso nuo to, ar atnaujinamas vienas valdymo blokas, ar visas automobilio modulių paketas.

Prieš atnaujinimą rekomenduojama:
1. Patikrinti 12 V akumuliatoriaus būklę.
2. Užtikrinti stabilų maitinimą programavimo metu.
3. Nuskaityti esamus klaidų kodus."""

    return f"""💰 <b>Apytikslė kaina</b>

Automobilis:
{esc(car)}

Kainai patikslinti reikia žinoti:
1. Kuri detalė ar sistema.
2. Nauja, naudota ar restauruota dalis.
3. Ar reikės programavimo / adaptacijos.
4. Automobilio VIN arba tiksli komplektacija."""


def extract_range_context(text: str) -> dict:
    t = normalize(text)
    nums = [int(x) for x in re.findall(r"\b(\d{2,4})\s*km\b", t)]
    ctx = {}
    if len(nums) >= 2:
        ctx["range_new_km"] = nums[0]
        ctx["range_current_km"] = nums[1]
        if nums[0] > 0:
            ctx["range_loss_percent"] = round((1 - nums[1] / nums[0]) * 100)
    if any(x in t for x in ["bater", "akumuliator", "hv", "aukštos įtampos", "aukstos itampos"]):
        ctx["topic"] = "HV baterija"
    if any(x in t for x in ["nuvažiuoja", "nuvaziuoja", "rida", "km", "talpa", "soh"]):
        ctx["subtopic"] = "sumažėjusi nuvažiuojama rida / baterijos talpa"
    return ctx


def update_case_context(chat_id: str, text: str, extra: dict | None = None):
    try:
        session = read_active_session(chat_id)
    except Exception:
        session = {}

    case_context = session.get("case_context") if isinstance(session.get("case_context"), dict) else {}
    vehicle = session.get("vehicle") if isinstance(session.get("vehicle"), dict) else {}

    brand = detect_brand(text)
    model = detect_model(text)
    year = detect_year(text)

    if brand:
        vehicle["brand"] = brand
    if model:
        vehicle["model"] = model
    if year:
        vehicle["year"] = year

    case_context.update(extract_range_context(text))

    if extra:
        case_context.update(extra)

    create_or_update_session(
        chat_id,
        text,
        {
            "status": "Aktyvi byla",
            "brand": vehicle.get("brand") or detect_brand(text),
            "fault": None,
            "vehicle": vehicle,
            "case_context": case_context,
            "case_title": generate_case_title(vehicle, text),
        },
    )


def get_case_context(chat_id: str) -> dict:
    try:
        session = read_active_session(chat_id)
        ctx = session.get("case_context")
        return ctx if isinstance(ctx, dict) else {}
    except Exception:
        return {}


def format_hv_battery_consultation(text: str, chat_id: str) -> str | None:
    t = normalize(text)
    if not any(x in t for x in ["bater", "talpa", "soh", "nuvažiuoja", "nuvaziuoja", "rida"]):
        return None

    ctx = get_case_context(chat_id)
    ctx.update(extract_range_context(text))

    vehicle = current_vehicle_from_text_or_session(text, chat_id)
    car = " ".join([str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x]).strip()
    car = car or "Elektromobilis"

    range_line = ""
    if ctx.get("range_new_km") and ctx.get("range_current_km"):
        range_line = f"\nNuvažiuojamas atstumas sumažėjo nuo {ctx.get('range_new_km')} km iki {ctx.get('range_current_km')} km."
        if ctx.get("range_loss_percent") is not None:
            range_line += f"\nApytikslis sumažėjimas: {ctx.get('range_loss_percent')} %."

    return f"""🔋 <b>Aukštos įtampos baterijos būklės įvertinimas</b>

Automobilis:
{esc(car)}{esc(range_line)}

Galimos priežastys:
1. Natūrali baterijos elementų degradacija.
2. Netiksli BMS talpos adaptacija.
3. Vieno ar kelių modulių disbalansas.
4. Padidėjusi elementų vidinė varža.
5. Temperatūros daviklių arba BMS klaidos.

Ar galima „atstatyti“ bateriją?
Visiškai atkurti pradinės fizinės talpos negalima, jei elementai susidėvėję. Tačiau kai kuriais atvejais galima pagerinti veikimą:
• atlikti BMS adaptaciją;
• subalansuoti modulius;
• pakeisti silpnus modulius;
• atnaujinti BMS programinę įrangą, jei gamintojas tai numato.

Rekomenduojama patikra:
1. Nuskaityti BMS klaidas.
2. Patikrinti SOH.
3. Patikrinti modulių įtampas ir balansą.
4. Patikrinti elementų temperatūrų skirtumus.
5. Įvertinti baterijos vidinę varžą.

Pastaba:
Jei rida sumažėjo staiga, pirmiausia tikrinami moduliai ir BMS klaidos. Jei mažėjo palaipsniui per kelis metus – labiau tikėtina natūrali degradacija."""


def format_hv_battery_price(text: str, chat_id: str) -> str | None:
    t = normalize(text)
    if not ("kain" in t or "remont" in t):
        return None
    if not any(x in t for x in ["bater", "modul", "soh", "akumuliator"]):
        return None

    ctx = get_case_context(chat_id)
    vehicle = current_vehicle_from_text_or_session(text, chat_id)
    car = " ".join([str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x]).strip()
    car = car or "Elektromobilis"

    range_line = ""
    if ctx.get("range_new_km") and ctx.get("range_current_km"):
        range_line = f"\nKontekstas: rida sumažėjo nuo {ctx.get('range_new_km')} km iki {ctx.get('range_current_km')} km."
        if ctx.get("range_loss_percent") is not None:
            range_line += f" Apytikslis sumažėjimas: {ctx.get('range_loss_percent')} %."

    return f"""💰 <b>HV baterijos remonto kaina</b>

Automobilis:
{esc(car)}{esc(range_line)}

Orientacinės kainos:
• BMS diagnostika / SOH patikra: apie 100–300 €
• Modulių įtampos ir balanso patikra: apie 100–300 €
• Vieno modulio keitimas: apie 500–1500 €+
• Naudotas baterijos paketas: apie 3000–8000 €+
• Baterijos paketo restauravimas: kaina priklauso nuo modulių būklės.

Prieš remontą būtina patikrinti:
1. SOH.
2. Modulių įtampas.
3. Modulių balansą.
4. BMS klaidas.
5. Temperatūros daviklius.
6. Izoliacijos klaidas.

Pastaba:
Tik pagal sumažėjusią ridą negalima nuspręsti, ar reikia keisti visą bateriją. Pirmiausia reikalinga BMS/SOH diagnostika."""


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V13 FINAL",
        "modules": {
            "vehicle_parser": parse_vehicle is not None,
            "diagnostic_context": build_context is not None,
            "openai_diagnostic": ask_openai_diagnostic is not None,
            "telegram_photo_handler": handle_photo_or_document is not None,
            "online_sources": answer_from_sources is not None,
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

        if data == "new_case":
            archived_id = start_new_case(chat_id)
            if archived_id:
                send_message(chat_id, "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
            else:
                send_message(chat_id, "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        elif data == "clear":
            clear_session(chat_id)
            send_message(chat_id, "Byla išvalyta. Galite pradėti iš naujo.", start_menu())
        elif data in ["new_diag", "add_action", "continue_diag", "summary"]:
            send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą arba patikros rezultatą.", start_menu())
        else:
            send_message(chat_id, "Pasirinkimas neatpažintas.", start_menu())
        return jsonify({"ok": True})

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if (message.get("photo") or message.get("document")) and handle_photo_or_document:
        result = handle_photo_or_document(
            bot_token=BOT_TOKEN,
            message=message,
            chat_id=chat_id,
            base_dir=BASE_DIR,
        )

        if result.get("handled"):
            vision_result = result.get("vision_result") or {}
            vehicle = vehicle_from_vision_result(vision_result)
            case_title = generate_case_title(vehicle, None)

            try:
                create_or_update_session(
                    chat_id,
                    case_title,
                    {
                        "status": "Automobilio duomenys nuskaityti iš nuotraukos",
                        "brand": vehicle.get("brand"),
                        "fault": None,
                        "vehicle": vehicle,
                        "case_title": case_title,
                    },
                )
            except Exception:
                logger.exception("Failed to update session from vehicle image")

            compact_text = compact_vehicle_image_text(vision_result)
            send_message(
                chat_id,
                compact_text or result.get("text", "Failas gautas."),
                clean_menu()
            )
            return jsonify({"ok": True})
    text = (message.get("text") or "").strip()

    if not chat_id:
        return jsonify({"ok": True})

    if text.lower() in ["/start", "start"]:
        send_message(chat_id, START_TEXT, start_menu())
        return jsonify({"ok": True})

    if not text:
        send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        return jsonify({"ok": True})

    case_command = is_case_command(text)
    if case_command == "new_case":
        archived_id = start_new_case(chat_id)
        if archived_id:
            send_message(chat_id, "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        else:
            send_message(chat_id, "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        return jsonify({"ok": True})
    if case_command == "clear":
        clear_session(chat_id)
        send_message(chat_id, "Byla išvalyta. Galite pradėti iš naujo.", start_menu())
        return jsonify({"ok": True})
    if case_command == "close":
        start_new_case(chat_id)
        send_message(chat_id, "📦 Byla išsaugota ir uždaryta.", start_menu())
        return jsonify({"ok": True})

    try:
        update_case_context(chat_id, text)
    except Exception:
        logger.exception("Case context update failed")

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

    if intent != "price":
        hv_answer = format_hv_battery_consultation(text, chat_id)
        if hv_answer:
            try:
                update_case_context(chat_id, text, {"topic": "HV baterija"})
            except Exception:
                pass
            send_message(chat_id, hv_answer, clean_menu())
            return jsonify({"ok": True})

    if intent == "price":
        try:
            update_case_context(chat_id, text, {"last_intent": "price"})
        except Exception:
            logger.exception("Session update failed")
        send_message(chat_id, format_price_response(text, chat_id), clean_menu())
        return jsonify({"ok": True})

    if is_source_query(text):
        source_answer = answer_from_online_sources(text, chat_id)
        if source_answer:
            send_message(chat_id, source_answer, clean_menu())
            return jsonify({"ok": True})

    if intent == "question":
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

    send_message(chat_id, "📥 <b>Informacija gauta</b>\n\n🔍 Analizuoju...")

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
