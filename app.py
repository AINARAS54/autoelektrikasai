import os, json, logging, datetime
from pathlib import Path
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from response_formatter import clean_telegram_text
from vehicle_engine import detect_vehicle, vehicle_label
from intent_engine import detect_intent
from context_engine import load_context, update_context, clear_context, archive_context
from obd_engine import answer_obd
from procedure_engine import answer_procedure
from price_engine import price_answer
from ev_engine import battery_analysis
from service_engine import answer_service
from vision_engine import handle_vehicle_photo

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
    except Exception as e:
        logger.exception("Telegram failed: %s", e)
        return None

def send_message(chat_id, text, reply_markup=None):
    text = clean_telegram_text(text)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)

def clean_menu():
    return {"inline_keyboard": [[{"text": "📂 Nauja byla", "callback_data": "new_case"}]]}

def start_menu():
    return None

def fallback_ai_answer(text: str, ctx: dict) -> str:
    if not OPENAI_API_KEY or OpenAI is None:
        return "Parašykite daugiau informacijos apie automobilį, gedimą arba patikros rezultatą."
    system = "Tu esi profesionalus lengvųjų automobilių autoelektrikas. Atsakyk lietuviškai, praktiškai, be URL ir be markdown žvaigždučių."
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"question": text, "context": ctx}, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        return res.output_text or "Nepavyko paruošti atsakymo."
    except Exception:
        logger.exception("fallback AI failed")
        return "Nepavyko paruošti atsakymo. Parašykite daugiau automobilio duomenų arba gedimo požymių."

def handle_new_case(chat_id: str):
    case_id = archive_context(BASE_DIR, chat_id)
    if case_id:
        send_message(chat_id, "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
    else:
        send_message(chat_id, "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "AutoElektrikas AI V18 Architecture", "time": datetime.datetime.now(datetime.UTC).isoformat()})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        if cq.get("data") == "new_case":
            handle_new_case(chat_id)
        else:
            send_message(chat_id, "Pasirinkimas neatpažintas.", start_menu())
        return jsonify({"ok": True})

    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return jsonify({"ok": True})

    if message.get("photo") or message.get("document"):
        answer, ctx_extra = handle_vehicle_photo(BASE_DIR, BOT_TOKEN, chat_id, message)
        if ctx_extra:
            update_context(BASE_DIR, chat_id, "Įkelta nuotrauka", ctx_extra)
        send_message(chat_id, answer, clean_menu())
        return jsonify({"ok": True})

    text = (message.get("text") or "").strip()
    if not text:
        send_message(chat_id, "Įveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
        return jsonify({"ok": True})

    ctx = update_context(BASE_DIR, chat_id, text)
    intent = detect_intent(text, ctx)

    if intent == "START":
        send_message(chat_id, START_TEXT, start_menu())
        return jsonify({"ok": True})
    if intent == "NEW_CASE":
        handle_new_case(chat_id)
        return jsonify({"ok": True})
    if intent == "CLEAR":
        clear_context(BASE_DIR, chat_id)
        send_message(chat_id, "Byla išvalyta. Galite pradėti iš naujo.", start_menu())
        return jsonify({"ok": True})

    vehicle = detect_vehicle(text)
    if intent == "VIN" and vehicle.get("vin"):
        ctx = update_context(BASE_DIR, chat_id, text, {"vehicle": vehicle})
        send_message(chat_id, f"🚗 <b>VIN gautas</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\nVIN: {esc(vehicle.get('vin'))}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok": True})

    if intent == "OBD":
        send_message(chat_id, answer_obd(BASE_DIR, text, ctx), clean_menu())
        return jsonify({"ok": True})
    if intent == "PRICE":
        send_message(chat_id, price_answer(text, ctx), clean_menu())
        return jsonify({"ok": True})
    if intent in ["PROCEDURE", "PROCEDURE_12V_BATTERY"]:
        answer = answer_procedure(BASE_DIR, text, ctx)
        if answer:
            send_message(chat_id, answer, clean_menu())
            return jsonify({"ok": True})
    service_answer = answer_service(BASE_DIR, text, ctx)
    if service_answer:
        send_message(chat_id, service_answer, clean_menu())
        return jsonify({"ok": True})
    if intent == "EV_BATTERY" or ctx.get("topic") == "HV_BATTERY":
        send_message(chat_id, battery_analysis(ctx), clean_menu())
        return jsonify({"ok": True})
    if vehicle and len(text.split()) <= 5:
        send_message(chat_id, f"🚗 <b>Automobilio duomenys gauti</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok": True})
    send_message(chat_id, fallback_ai_answer(text, ctx), clean_menu())
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
