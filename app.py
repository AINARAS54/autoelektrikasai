import os
import json
import logging
import datetime
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from response_formatter import clean_telegram_text
from vehicle_engine import detect_vehicle, vehicle_label
from intent_engine import detect_intent
from context_engine import update_context, clear_context, archive_context, archived_diagnostics_summary
from obd_engine import answer_obd
from procedure_engine import answer_procedure
from price_engine import price_answer
from ev_engine import battery_analysis
from service_engine import answer_service
from vision_engine import handle_vehicle_photo
from decision_tree_engine import handle_decision_callback
from decision_session import clear_decision_session
from unified_router import resolve_route
from vehicle_profile_engine import get_vehicle_profile, profile_summary

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autoelektrikas_ai")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
BASE_DIR = Path(__file__).parent
app = Flask(__name__)

START_TEXT = """🚗 <b>AutoElektrikas AI</b>

Automobilių elektros ir elektronikos diagnostikos asistentas.

📋 Įveskite automobilio duomenis ir apibūdinkite gedimą.

📎 Galite pateikti papildomą informaciją: kėbulo numerį (VIN), techninio paso duomenis, prietaisų skydelio pranešimus ar diagnostikos rezultatus – tai padės tiksliau nustatyti gedimą."""

def esc(value):
    return str(value or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def telegram_api(method: str, payload: dict):
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN missing")
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=25)
        if not r.ok:
            logger.error("Telegram error: %s %s", r.status_code, r.text)
        return r.json()
    except Exception as exc:
        logger.exception("Telegram request failed: %s", exc)
        return None

def send_message(chat_id, text, reply_markup=None):
    text = clean_telegram_text(text or "Atsakymo paruošti nepavyko.")
    payload = {"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)

def clean_menu():
    return {"inline_keyboard":[[{"text":"🆕 Nauja diagnostika","callback_data":"new_diagnostic"}], [{"text":"📂 Ankstesnės diagnostikos","callback_data":"diagnostic_history"}]]}

def fallback_ai_answer(text: str, ctx: dict) -> str:
    profile = get_vehicle_profile(BASE_DIR, ctx)
    if not OPENAI_API_KEY or OpenAI is None:
        return "Parašykite daugiau informacijos apie automobilį, gedimą arba patikros rezultatą."
    system = """Tu esi profesionalus autoelektrikas. Atsakyk lietuviškai, praktiškai ir aiškiai.
Nerodyk interneto nuorodų. Neišgalvok gamintojo meniu ar procedūrų.
Griežtai laikykis automobilio profilio. Nesiūlyk starterio, generatoriaus,
žvakių, ričių ar purkštukų, jei profilyje nurodyta, kad jų nėra."""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role":"system","content":system},
                {"role":"user","content":json.dumps({"question":text,"context":ctx,"vehicle_profile":profile_summary(profile)}, ensure_ascii=False)}
            ],
            temperature=0.2,
        )
        return res.output_text or "Nepavyko paruošti atsakymo."
    except Exception:
        logger.exception("AI fallback failed")
        return "Nepavyko paruošti atsakymo. Parašykite daugiau automobilio duomenų arba gedimo požymių."

def handle_new_diagnostic(chat_id: str):
    clear_decision_session(BASE_DIR, chat_id)
    case_id = archive_context(BASE_DIR, chat_id)
    text = (
        "📂 Ankstesnė diagnostika išsaugota.\n\n"
        "🆕 Nauja diagnostikos sesija pradėta.\n\n"
        "Įveskite automobilio duomenis ir apibūdinkite gedimą."
        if case_id
        else
        "🆕 Nauja diagnostikos sesija pradėta.\n\n"
        "Įveskite automobilio duomenis ir apibūdinkite gedimą."
    )
    send_message(chat_id, text, clean_menu())

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status":"ok","service":"AutoElektrikas AI V26","architecture":"vehicle_profile_first","time":datetime.datetime.now(datetime.UTC).isoformat()})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    callback = update.get("callback_query")
    if callback:
        if callback.get("id"):
            telegram_api("answerCallbackQuery", {"callback_query_id":callback.get("id")})
        chat_id = str(callback.get("message",{}).get("chat",{}).get("id",""))
        data = callback.get("data","")
        if not chat_id:
            return jsonify({"ok":True})
        if data.startswith("dt:"):
            answer, markup = handle_decision_callback(BASE_DIR, chat_id, data)
            send_message(chat_id, answer, markup)
            return jsonify({"ok":True})
        if data in {"new_case", "new_diagnostic"}:
            handle_new_diagnostic(chat_id)
            return jsonify({"ok":True})
        if data == "diagnostic_history":
            send_message(chat_id, archived_diagnostics_summary(BASE_DIR, chat_id), clean_menu())
            return jsonify({"ok":True})
        send_message(chat_id, "Pasirinkimas neatpažintas.")
        return jsonify({"ok":True})

    message = update.get("message",{})
    chat_id = str(message.get("chat",{}).get("id",""))
    if not chat_id:
        return jsonify({"ok":True})

    if message.get("photo") or message.get("document"):
        answer, ctx_extra = handle_vehicle_photo(BASE_DIR, BOT_TOKEN, chat_id, message)
        if ctx_extra:
            update_context(BASE_DIR, chat_id, "Įkelta nuotrauka", ctx_extra)
        send_message(chat_id, answer, clean_menu())
        return jsonify({"ok":True})

    text = (message.get("text") or "").strip()
    if not text:
        send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą.")
        return jsonify({"ok":True})

    ctx = update_context(BASE_DIR, chat_id, text)
    intent = detect_intent(text, ctx)

    if intent == "START":
        send_message(chat_id, START_TEXT)
        return jsonify({"ok":True})
    if intent == "NEW_CASE":
        handle_new_diagnostic(chat_id)
        return jsonify({"ok":True})
    if intent == "CLEAR":
        clear_context(BASE_DIR, chat_id)
        send_message(chat_id, "Diagnostikos sesija išvalyta. Galite pradėti iš naujo.", clean_menu())
        return jsonify({"ok":True})

    vehicle = detect_vehicle(text)
    if intent == "VIN" and vehicle.get("vin"):
        ctx = update_context(BASE_DIR, chat_id, text, {"vehicle":vehicle})
        send_message(chat_id, f"🚗 <b>VIN gautas</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\n\nVIN:\n{esc(vehicle.get('vin'))}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok":True})

    route = resolve_route(BASE_DIR, chat_id, text, ctx)
    route_name = route.get("route")

    if route_name == "PROFILE_WARNING":
        profile = route.get("profile",{})
        send_message(chat_id, f"🚗 <b>Automobilio profilio patikra</b>\n\nAutomobilis:\n{esc(profile.get('vehicle_label'))}\n\n{esc(route.get('message'))}", clean_menu())
        return jsonify({"ok":True})

    if route_name in ["DECISION_TREE","SYMPTOM_TREE"]:
        answer = route.get("answer")
        if route.get("profile_note"):
            answer = f"🚗 <b>Automobilio profilio patikra</b>\n\n{esc(route.get('profile_note'))}\n\nParinkta EV / READY diagnostikos eiga:\n\n{answer}"
        send_message(chat_id, answer, route.get("markup"))
        return jsonify({"ok":True})

    if route_name == "OBD":
        send_message(chat_id, answer_obd(BASE_DIR, text, ctx), clean_menu())
        return jsonify({"ok":True})
    if route_name == "PRICE":
        send_message(chat_id, price_answer(text, ctx), clean_menu())
        return jsonify({"ok":True})
    if route_name == "PROCEDURE":
        answer = answer_procedure(BASE_DIR, text, ctx)
        if answer:
            send_message(chat_id, answer, clean_menu())
            return jsonify({"ok":True})

    service_answer = answer_service(BASE_DIR, text, ctx)
    if service_answer:
        send_message(chat_id, service_answer, clean_menu())
        return jsonify({"ok":True})

    if route_name == "EV":
        send_message(chat_id, battery_analysis(ctx), clean_menu())
        return jsonify({"ok":True})

    if vehicle and len(text.split()) <= 5:
        profile = get_vehicle_profile(BASE_DIR, ctx)
        send_message(chat_id, f"🚗 <b>Automobilio duomenys gauti</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\n\nPavaros tipas:\n{esc(profile.get('platform'))}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok":True})

    send_message(chat_id, fallback_ai_answer(text, ctx), clean_menu())
    return jsonify({"ok":True})

if __name__ == "__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port)
