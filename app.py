import os
import re
import json
import logging
import datetime
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

try:
    from session_store import create_or_update_session, get_session_summary, clear_session
except Exception:
    create_or_update_session = None
    get_session_summary = None
    clear_session = None

try:
    from telegram_photo_handler import handle_photo_or_document
except Exception:
    handle_photo_or_document = None

try:
    from response_formatter import clean_telegram_text
except Exception:
    clean_telegram_text = None

try:
    from vehicle_engine import detect_vehicle, vehicle_label
except Exception:
    detect_vehicle = None
    vehicle_label = None

try:
    from vehicle_parser import parse_vehicle
except Exception:
    parse_vehicle = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from online_sources.nhtsa_vpic import decode_vin, format_vin_result
except Exception:
    decode_vin = None
    format_vin_result = None

try:
    from online_sources.source_manager import answer_from_sources
except Exception:
    answer_from_sources = None


# ==========================================================
# AutoElektrikas AI - Telegram Webhook
# V15 app.py - integrated context / EV / procedure / price fixes
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


START_TEXT = """🚗 <b>AutoElektrikas AI</b>

Automobilių elektros ir elektronikos diagnostikos asistentas.

📋 Įveskite automobilio duomenis ir apibūdinkite gedimą.

📎 Galite pateikti papildomą informaciją: kėbulo numerį (VIN), techninio paso duomenis, prietaisų skydelio pranešimus ar diagnostikos rezultatus – tai padės tiksliau nustatyti gedimą."""


# -----------------------------
# Basic utilities
# -----------------------------
def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def normalize(text: str) -> str:
    return (text or "").lower().strip()


def clean_text_for_telegram(text: str) -> str:
    if clean_telegram_text:
        try:
            return clean_telegram_text(text)
        except Exception:
            pass

    text = text or ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^)]*\)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("nulaužimui", "atstatymui")
    text = text.replace("nulaužimas", "atstatymas")
    text = text.replace("nulaužimą", "atstatymą")
    text = text.replace("nulaužti", "atstatyti")
    return text.strip()


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
FAULT_BY_ID = {f.get("id"): f for f in FAULTS if isinstance(f, dict) and f.get("id")}


# -----------------------------
# Telegram
# -----------------------------
def telegram_api(method: str, payload: dict):
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is missing")
        return None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=25)
        if not r.ok:
            logger.error("Telegram API error: %s %s", r.status_code, r.text)
        return r.json()
    except Exception as e:
        logger.exception("Telegram API request failed: %s", e)
        return None


def send_message(chat_id, text, reply_markup=None):
    text = clean_text_for_telegram(text)
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


# -----------------------------
# Context engine in app.py
# -----------------------------
def safe_chat_id(chat_id: str) -> str:
    return "".join(ch for ch in str(chat_id) if ch.isalnum() or ch in ("_", "-"))


def context_dir() -> Path:
    path = BASE_DIR / "case_contexts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_dir() -> Path:
    path = BASE_DIR / "cases_archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_path(chat_id: str) -> Path:
    return context_dir() / f"{safe_chat_id(chat_id)}.json"


def load_context(chat_id: str) -> dict:
    path = context_path(chat_id)
    if not path.exists():
        return {"vehicle": {}, "measurements": {}, "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"vehicle": {}, "measurements": {}, "history": []}
        data.setdefault("vehicle", {})
        data.setdefault("measurements", {})
        data.setdefault("history", [])
        return data
    except Exception:
        return {"vehicle": {}, "measurements": {}, "history": []}


def save_context(chat_id: str, ctx: dict) -> dict:
    context_path(chat_id).write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx


def clear_context(chat_id: str):
    path = context_path(chat_id)
    if path.exists():
        path.unlink()
    if clear_session:
        try:
            clear_session(chat_id)
        except Exception:
            pass


def archive_current_case(chat_id: str) -> str | None:
    ctx = load_context(chat_id)
    if not ctx.get("vehicle") and not ctx.get("topic") and not ctx.get("history"):
        clear_context(chat_id)
        return None

    now = datetime.datetime.now(datetime.UTC)
    case_id = ctx.get("case_id") or f"AE-{now.strftime('%Y%m%d-%H%M%S')}-{safe_chat_id(chat_id)}"
    ctx["case_id"] = case_id
    ctx["archived_at"] = now.isoformat()
    ctx["status"] = ctx.get("status") or "Sustabdyta"
    (archive_dir() / f"{case_id}.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_context(chat_id)
    return case_id


def detect_vehicle_local(text: str) -> dict:
    if detect_vehicle:
        try:
            v = detect_vehicle(text)
            if isinstance(v, dict):
                return v
        except Exception:
            pass

    if parse_vehicle:
        try:
            v = parse_vehicle(text, BRANDS)
            if isinstance(v, dict):
                # normalize key names
                out = {}
                if v.get("brand"):
                    out["brand"] = v.get("brand")
                if v.get("model"):
                    out["model"] = v.get("model")
                if v.get("year"):
                    out["year"] = v.get("year")
                return out
        except Exception:
            pass

    t = normalize(text)
    vehicle = {}

    brands = {
        "bmw": "BMW", "audi": "Audi", "vw": "Volkswagen", "volkswagen": "Volkswagen",
        "mercedes": "Mercedes-Benz", "toyota": "Toyota", "volvo": "Volvo", "tesla": "Tesla",
        "nissan": "Nissan", "hyundai": "Hyundai", "kia": "Kia", "ford": "Ford",
        "opel": "Opel", "peugeot": "Peugeot", "renault": "Renault",
    }
    for key, value in brands.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            vehicle["brand"] = value
            break

    models = [
        "i3", "i4", "i5", "i7", "ix", "id.3", "id3", "id.4", "id4",
        "golf", "passat", "tiguan", "touran", "a3", "a4", "a6", "q5", "q7",
        "model 3", "model y", "leaf", "kona", "niro", "f30", "f10", "e90", "e60", "g30",
    ]
    for model in models:
        if re.search(rf"\b{re.escape(model)}\b", t):
            vehicle["model"] = {"id3": "ID.3", "id4": "ID.4"}.get(model, model.upper() if model in ["q5","q7","f30","f10","e90","e60","g30"] else model)
            break

    year = re.search(r"\b(19[8-9]\d|20[0-3]\d)\s*m?\.?\b", t)
    if year:
        vehicle["year"] = year.group(1)

    vin_text = (text or "").upper().replace(" ", "")
    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", vin_text)
    if vin:
        vehicle["vin"] = vin.group(0)

    return vehicle


def vehicle_label_local(vehicle: dict, fallback: str = "Nenurodytas automobilis") -> str:
    if vehicle_label:
        try:
            return vehicle_label(vehicle, fallback=fallback)
        except TypeError:
            try:
                return vehicle_label(vehicle)
            except Exception:
                pass
        except Exception:
            pass

    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    return " ".join([str(x) for x in parts if x]).strip() or fallback


def extract_range_context(text: str) -> dict:
    """
    Recognizes:
    - naujas nuvažiuodavo 270 km, dabar 170 km
    - nuo 270 km iki 170 km
    - 270 km -> 170 km
    Ignores years and age.
    """
    t = normalize(text)
    result = {}

    patterns = [
        r"nuva\w+\s*(\d{2,4})\s*km?.{0,100}?nuva\w+\s*(\d{2,4})\s*km?",
        r"nuo\s*(\d{2,4})\s*km?.{0,60}?iki\s*(\d{2,4})\s*km?",
        r"(\d{2,4})\s*km\s*(?:->|→|-)\s*(\d{2,4})\s*km?",
    ]
    pair = None
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            pair = (int(m.group(1)), int(m.group(2)))
            break

    if not pair:
        nums = []
        for m in re.finditer(r"\b(\d{2,4})\b", t):
            n = int(m.group(1))
            if 50 <= n <= 800:
                nums.append(n)
        if len(nums) >= 2:
            pair = (nums[0], nums[-1])

    if pair:
        old, current = pair
        if old > current and old > 0:
            result["range_new_km"] = old
            result["range_current_km"] = current
            result["range_loss_percent"] = round((1 - current / old) * 100)
            result["range_remaining_percent"] = round((current / old) * 100)

    return result


def detect_topic(text: str) -> dict:
    t = normalize(text)
    data = {}

    if any(x in t for x in ["bater", "akumuliator", "hv", "aukštos įtampos", "aukstos itampos", "soh", "nuvažiuoja", "nuvaziuoja", "talpa"]):
        data["topic"] = "HV_BATTERY"

    if any(x in t for x in ["stabdžių skys", "stabdziu skys", "brake fluid"]):
        data["topic"] = "BRAKE_FLUID"

    if any(x in t for x in ["kain", "remont", "kiek kainuos", "kiek kainuoja"]):
        data["last_intent"] = "PRICE"

    if any(x in t for x in ["kaip", "reset", "nureset", "nunul", "atstat"]):
        data["last_intent"] = data.get("last_intent") or "PROCEDURE"

    return data


def update_context(chat_id: str, text: str, extra: dict | None = None) -> dict:
    ctx = load_context(chat_id)
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}

    detected_vehicle = detect_vehicle_local(text)
    vehicle.update({k: v for k, v in detected_vehicle.items() if v})
    ctx["vehicle"] = vehicle

    topic = detect_topic(text)
    ctx.update({k: v for k, v in topic.items() if v})

    range_ctx = extract_range_context(text)
    if range_ctx:
        ctx.setdefault("measurements", {})
        ctx["measurements"].update(range_ctx)
        ctx["topic"] = "HV_BATTERY"
        ctx["subtopic"] = "RANGE_DECREASE"

    if extra:
        for k, v in extra.items():
            if k == "vehicle" and isinstance(v, dict):
                ctx.setdefault("vehicle", {})
                ctx["vehicle"].update({kk: vv for kk, vv in v.items() if vv})
            elif k == "measurements" and isinstance(v, dict):
                ctx.setdefault("measurements", {})
                ctx["measurements"].update(v)
            else:
                ctx[k] = v

    ctx.setdefault("history", [])
    ctx["history"].append({"user": text, "time": datetime.datetime.now(datetime.UTC).isoformat()})
    ctx["history"] = ctx["history"][-20:]

    if create_or_update_session:
        try:
            create_or_update_session(
                chat_id,
                text,
                {
                    "status": "Aktyvi byla",
                    "brand": vehicle.get("brand"),
                    "fault": None,
                    "vehicle": vehicle,
                    "case_context": ctx,
                    "case_title": generate_case_title(vehicle, text),
                },
            )
        except Exception:
            pass

    return save_context(chat_id, ctx)


def generate_case_title(vehicle: dict | None, fault_text: str | None = None) -> str:
    vehicle = vehicle or {}
    car = vehicle_label_local(vehicle, fallback="")
    fault = (fault_text or "").strip()
    if len(fault) > 55:
        fault = fault[:55].rstrip() + "..."
    if car:
        return f"{car} – {fault or 'nauja diagnostika'}"
    return fault or "Nauja diagnostikos byla"


def get_range_summary(ctx: dict) -> str:
    m = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    old = m.get("range_new_km")
    current = m.get("range_current_km")
    loss = m.get("range_loss_percent")
    remaining = m.get("range_remaining_percent")

    if not old or not current:
        return ""

    lines = [
        f"Pradinė rida: {old} km",
        f"Dabartinė rida: {current} km",
    ]
    if loss is not None:
        lines.append(f"Sumažėjimas: apie {loss} %")
    if remaining is not None:
        lines.append(f"Likusi santykinė talpa: apie {remaining} %")
    return "\n".join(lines)


# -----------------------------
# Intent
# -----------------------------
def detect_obd(text: str):
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None


def is_price_query(text: str) -> bool:
    t = normalize(text)
    return any(term in t for term in [
        "kiek kainuoja", "kokia kaina", "kiek atsieina", "kiek kainuos",
        "remonto kaina", "dalies kaina", "modulio kaina", "modulių kaina",
        "baterijos kaina", "programinės įrangos", "programines irangos",
        "software update", "update kaina", "atnaujinti", "atnaujinimas", "remontas",
    ])


def is_procedure_query(text: str) -> bool:
    t = normalize(text)
    return any(term in t for term in [
        "kaip", "reset", "nuresetinti", "nunulinti", "atstatyti",
        "serviso interval", "brake fluid", "stabdžių skys", "stabdziu skys",
        "procedūra", "procedura", "adaptuoti", "kalibruoti", "registruoti",
    ])


def is_hv_battery_text(text: str) -> bool:
    t = normalize(text)
    return any(x in t for x in [
        "bater", "akumuliator", "aukštos įtampos", "aukstos itampos",
        "talpa", "soh", "nuvažiuoja", "nuvaziuoja", "nuvažiuodavo",
        "nuvaziuodavo", "rida", "atstatyti bater"
    ])


def detect_intent(text: str, ctx: dict | None = None) -> str:
    t = normalize(text)
    if t in ["/start", "start"]:
        return "START"
    if t in ["/newcase", "/new", "nauja byla", "pradėti naują bylą", "pradeti nauja byla", "nauja diagnostika", "pradėti iš naujo", "pradeti is naujo"]:
        return "NEW_CASE"
    if t in ["/clear", "išvalyti bylą", "isvalyti byla"]:
        return "CLEAR"
    if is_price_query(text):
        return "PRICE"
    if detect_obd(text):
        return "OBD"
    # EV / HV baterijos klausimai turi prioritetą prieš bendras procedūras.
    if is_hv_battery_text(text):
        return "EV_BATTERY"
    if is_procedure_query(text):
        return "PROCEDURE"
    if "?" in text or any(x in t for x in ["kodėl", "kodel", "kur", "ką reiškia", "ka reiskia"]):
        return "QUESTION"
    return "DIAGNOSTIC"


# -----------------------------
# Answers
# -----------------------------
def bmw_i3_brake_fluid_reset_answer(ctx: dict | None = None) -> str:
    ctx = ctx or {}
    car = vehicle_label_local(ctx.get("vehicle") or {}, fallback="BMW i3")
    if "BMW" not in car or "i3" not in car:
        car = "BMW i3"

    return f"""📘 <b>BMW i3 stabdžių skysčio serviso intervalo atstatymas</b>

Automobilis:
{esc(car)}

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
• Jei meniu šios funkcijos nerodo, atlikite atstatymą diagnostikos įranga, pvz. ISTA, Autel, Launch ar Bosch."""


def bms_adaptation_answer(ctx: dict) -> str:
    car = vehicle_label_local(ctx.get("vehicle") or {}, fallback="Automobilis")

    return f"""📘 <b>BMS talpos adaptacija</b>

Automobilis:
{esc(car)}

BMS talpos adaptacija reikalinga tada, kai keičiamas 12 V akumuliatorius arba jo tipas / talpa. Sistema turi žinoti naujo akumuliatoriaus parametrus, kad tinkamai valdytų įkrovimą.

Atlikimo tvarka:
1. Įdėkite tinkamos talpos ir tipo akumuliatorių.
2. Patikrinkite, ar gnybtai ir masės jungtys prijungtos teisingai.
3. Prijunkite diagnostikos įrangą.
4. Pasirinkite akumuliatoriaus registravimo / BMS adaptacijos funkciją.
5. Įveskite naujo akumuliatoriaus parametrus, jei to prašo įranga.
6. Užbaikite procedūrą ir patikrinkite, ar nėra aktyvių klaidų.

Pastaba:
BMW automobiliuose ši procedūra dažniausiai atliekama naudojant ISTA arba kitą suderinamą diagnostikos įrangą.

Jei kalbate apie aukštos įtampos bateriją, o ne 12 V akumuliatorių, procedūra yra kitokia ir reikia BMS/SOH diagnostikos."""


def answer_procedure(text: str, ctx: dict) -> str | None:
    t = normalize(text)
    vehicle = ctx.get("vehicle") or {}
    brand = normalize(str(vehicle.get("brand") or ""))
    model = normalize(str(vehicle.get("model") or ""))

    has_bmw = "bmw" in t or brand == "bmw"
    has_i3 = "i3" in t or model == "i3"
    has_brake = "stabdziu skys" in t or "stabdžių skys" in t or "brake fluid" in t or ("stabd" in t and "skys" in t)
    has_reset = any(x in t for x in ["reset", "nureset", "nunul", "atstat", "panaikinti", "isjungti", "išjungti"])

    if has_bmw and has_i3 and has_brake and has_reset:
        return bmw_i3_brake_fluid_reset_answer(ctx)

    if "bms" in t and any(x in t for x in ["adapt", "kaip", "atlikti", "registr", "reset"]):
        return bms_adaptation_answer(ctx)

    # Use online_sources as a fallback for procedures, but sanitize output.
    if answer_from_sources:
        try:
            result = answer_from_sources(text, {"brand": vehicle.get("brand"), "model": vehicle.get("model"), "year": vehicle.get("year")})
            if result and result.get("answer"):
                return result.get("answer")
        except Exception:
            logger.exception("answer_from_sources failed")

    return None


def hv_battery_analysis(ctx: dict) -> str:
    car = vehicle_label_local(ctx.get("vehicle") or {}, fallback="Elektromobilis")
    summary = get_range_summary(ctx)
    block = f"\n\n{summary}" if summary else ""

    measurements = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    loss = measurements.get("range_loss_percent")

    conclusion = ""
    if loss is not None:
        if loss >= 30:
            conclusion = f"\n\nVertinimas:\n🔴 Apie {loss} % sumažėjimas yra didelis. Reikalinga BMS/SOH ir modulių balansavimo patikra."
        elif loss >= 20:
            conclusion = f"\n\nVertinimas:\n🟡 Apie {loss} % sumažėjimas yra pastebimas. Reikalinga baterijos būklės patikra."
        else:
            conclusion = f"\n\nVertinimas:\n🟢 Apie {loss} % sumažėjimas gali būti artimas natūraliai degradacijai, bet SOH patikra vis tiek naudinga."

    return f"""🔋 <b>Aukštos įtampos baterijos analizė</b>

Automobilis:
{esc(car)}{esc(block)}{esc(conclusion)}

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
5. Įvertinti baterijos vidinę varžą."""


def hv_battery_price(ctx: dict) -> str:
    car = vehicle_label_local(ctx.get("vehicle") or {}, fallback="Elektromobilis")
    summary = get_range_summary(ctx)
    block = f"\n\nKontekstas:\n{summary}" if summary else ""

    return f"""💰 <b>HV baterijos remonto kaina</b>

Automobilis:
{esc(car)}{esc(block)}

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


def price_answer(text: str, ctx: dict) -> str:
    t = normalize(text)
    topic = ctx.get("topic")
    direct_battery = any(x in t for x in ["bater", "modul", "soh", "akumuliator"])
    if topic == "HV_BATTERY" or ctx.get("subtopic") == "RANGE_DECREASE" or direct_battery:
        return hv_battery_price(ctx)

    car = vehicle_label_local(ctx.get("vehicle") or {}, fallback="Nenurodytas automobilis")
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


def local_obd_answer(code: str) -> str | None:
    code = (code or "").upper()
    if code in OBD:
        obd = OBD[code]
        checks = obd.get("first_checks") or []
        checks_text = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(checks[:5])])
        return f"""⚡ <b>OBD kodas: {esc(code)}</b>

Reikšmė:
{esc(obd.get('meaning', 'Kodo aprašymas nerastas.'))}

Svarbu:
Klaidos kodas nėra galutinė diagnozė.

Rekomenduojama patikra:
{checks_text or 'Reikalinga papildoma diagnostika.'}"""

    if answer_from_sources:
        try:
            result = answer_from_sources(code, {})
            if result and result.get("answer"):
                return result.get("answer")
        except Exception:
            pass

    return f"""⚡ <b>OBD kodas: {esc(code)}</b>

Šio kodo vietinėje bazėje neradau.

Parašykite automobilio markę, modelį, metus ir simptomus."""


def fallback_question_answer(text: str, ctx: dict) -> str:
    if not OPENAI_API_KEY or OpenAI is None:
        return "Parašykite daugiau informacijos apie automobilį, gedimą arba patikros rezultatą."

    system = """
Tu esi profesionalus lengvųjų automobilių autoelektrikas.
Atsakyk lietuviškai, trumpai ir praktiškai.
Nerodyk interneto nuorodų.
Nenaudok markdown žymėjimo su žvaigždutėmis.
Nevartok žodžių nulaužti, nulaužimas, nulaužimui serviso atstatymo kontekste.
Jei klausimas yra apie procedūrą ir neturi patikimos konkrečios procedūros, aiškiai pasakyk, kokių duomenų trūksta.
"""

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"question": text, "context": ctx}, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        return response.output_text or "Nepavyko paruošti atsakymo."
    except Exception:
        logger.exception("OpenAI fallback failed")
        return "Nepavyko paruošti atsakymo. Parašykite daugiau automobilio duomenų arba gedimo požymių."


def handle_new_case(chat_id: str):
    archived_id = archive_current_case(chat_id)
    if archived_id:
        send_message(chat_id, "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
    else:
        send_message(chat_id, "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())


def handle_photo(chat_id: str, message: dict):
    if not handle_photo_or_document:
        send_message(chat_id, "Nuotraukų nuskaitymo modulis neprijungtas.", clean_menu())
        return

    result = handle_photo_or_document(
        bot_token=BOT_TOKEN,
        message=message,
        chat_id=chat_id,
        base_dir=BASE_DIR,
    )

    if not result.get("handled"):
        send_message(chat_id, "Failas gautas, bet jo nepavyko apdoroti.", clean_menu())
        return

    vision = result.get("vision_result") or {}
    vehicle = (vision.get("vehicle") or {}) if isinstance(vision, dict) else {}

    # Normalize vehicle keys from vision
    clean_vehicle = {
        "brand": vehicle.get("brand"),
        "model": vehicle.get("model"),
        "year": vehicle.get("year"),
        "vin": vehicle.get("vin"),
        "registration_number": vehicle.get("registration_number"),
        "fuel_type": vehicle.get("fuel_type"),
    }
    clean_vehicle = {k: v for k, v in clean_vehicle.items() if v}

    update_context(chat_id, "Įkelta nuotrauka", {"vehicle": clean_vehicle})

    if vision.get("document_type") == "registration_document":
        car = vehicle_label_local(clean_vehicle, fallback="")
        lines = ["🚗 <b>Automobilio duomenys nuskaityti</b>"]
        if car:
            lines.append(f"\n🚘 {esc(car)}")
        if clean_vehicle.get("vin"):
            lines.append(f"🔑 VIN: {esc(clean_vehicle.get('vin'))}")
        if clean_vehicle.get("registration_number"):
            lines.append(f"🔖 Nr.: {esc(clean_vehicle.get('registration_number'))}")
        lines.append("\n✅ Byla atnaujinta.")
        lines.append("✍️ Apibūdinkite gedimą.")
        send_message(chat_id, "\n".join(lines), clean_menu())
        return

    send_message(chat_id, result.get("text", "Failas gautas."), clean_menu())


# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V15.1 integrated",
        "modules": {
            "photo_handler": handle_photo_or_document is not None,
            "vin_decoder": decode_vin is not None,
            "online_sources": answer_from_sources is not None,
            "openai": bool(OPENAI_API_KEY and OpenAI is not None),
        },
        "time": datetime.datetime.now(datetime.UTC).isoformat(),
    })


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        data = cq.get("data", "")

        if data == "new_case":
            handle_new_case(chat_id)
        else:
            send_message(chat_id, "Pasirinkimas neatpažintas.", start_menu())

        return jsonify({"ok": True})

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if not chat_id:
        return jsonify({"ok": True})

    if message.get("photo") or message.get("document"):
        handle_photo(chat_id, message)
        return jsonify({"ok": True})

    text = (message.get("text") or "").strip()

    if not text:
        send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        return jsonify({"ok": True})

    ctx = update_context(chat_id, text)
    intent = detect_intent(text, ctx)

    if intent == "START":
        send_message(chat_id, START_TEXT, start_menu())
        return jsonify({"ok": True})

    if intent == "NEW_CASE":
        handle_new_case(chat_id)
        return jsonify({"ok": True})

    if intent == "CLEAR":
        clear_context(chat_id)
        send_message(chat_id, "Byla išvalyta. Galite pradėti iš naujo.", start_menu())
        return jsonify({"ok": True})

    clean_text = text.replace(" ", "").strip().upper()
    if len(clean_text) == 17 and clean_text.isalnum() and decode_vin:
        vin_result = decode_vin(clean_text)
        if vin_result.get("ok"):
            vehicle = {
                "brand": vin_result.get("make"),
                "model": vin_result.get("model"),
                "year": vin_result.get("model_year"),
                "vin": clean_text,
                "fuel_type": vin_result.get("fuel_type"),
                "vehicle_type": vin_result.get("vehicle_type"),
            }
            ctx = update_context(chat_id, text, {"vehicle": vehicle})
            if format_vin_result:
                send_message(chat_id, format_vin_result(vin_result), clean_menu())
            else:
                send_message(chat_id, f"🚗 <b>VIN duomenys</b>\n\nAutomobilis:\n{esc(vehicle_label_local(vehicle))}\nVIN: {esc(clean_text)}\n\nDabar apibūdinkite gedimą.", clean_menu())
            return jsonify({"ok": True})

    # Griežtas EV baterijos maršrutizavimas:
    # jei tekste yra baterija / rida / SOH arba kontekste jau HV_BATTERY,
    # atsakome per HV baterijos modulį, ne per bendrą OpenAI.
    if intent == "EV_BATTERY" or ctx.get("topic") == "HV_BATTERY":
        send_message(chat_id, hv_battery_analysis(ctx), clean_menu())
        return jsonify({"ok": True})

    if intent == "PRICE":
        send_message(chat_id, price_answer(text, ctx), clean_menu())
        return jsonify({"ok": True})

    if intent == "PROCEDURE":
        proc = answer_procedure(text, ctx)
        if proc:
            send_message(chat_id, proc, clean_menu())
            return jsonify({"ok": True})

    if intent == "OBD":
        send_message(chat_id, local_obd_answer(detect_obd(text)), clean_menu())
        return jsonify({"ok": True})

    # Vehicle-only message
    vehicle = detect_vehicle_local(text)
    if vehicle and len(text.split()) <= 5:
        label = vehicle_label_local(ctx.get("vehicle") or vehicle)
        send_message(chat_id, f"🚗 <b>Automobilio duomenys gauti</b>\n\nAutomobilis:\n{esc(label)}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok": True})

    send_message(chat_id, fallback_question_answer(text, ctx), clean_menu())
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
