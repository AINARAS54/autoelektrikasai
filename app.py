import os
import logging
import datetime
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from response_formatter import clean_telegram_text, esc
from vehicle_engine import detect_vehicle, vehicle_label
from context_engine import (
    load_context,
    update_context,
    clear_context,
    archive_context,
)
from intent_engine import detect_intent
from ev_engine import battery_analysis
from procedure_engine import answer_procedure
from price_engine import price_answer

try:
    from telegram_photo_handler import handle_photo_or_document
except Exception:
    handle_photo_or_document = None

try:
    from online_sources.nhtsa_vpic import decode_vin, format_vin_result
except Exception:
    decode_vin = None
    format_vin_result = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# ==========================================================
# AutoElektrikas AI - V15 Modular
# ==========================================================

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
    text = clean_telegram_text(text)

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


def handle_new_case(chat_id: str):
    archived_id = archive_context(BASE_DIR, chat_id)
    if archived_id:
        send_message(chat_id, "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())
    else:
        send_message(chat_id, "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.", start_menu())


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
                {"role": "user", "content": {"question": text, "context": ctx}},
            ],
            temperature=0.2,
        )
        return response.output_text or "Nepavyko paruošti atsakymo."
    except Exception:
        logger.exception("OpenAI fallback failed")
        return "Nepavyko paruošti atsakymo. Parašykite daugiau automobilio duomenų arba gedimo požymių."


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

    ctx = update_context(BASE_DIR, chat_id, "Įkelta nuotrauka", {"vehicle": vehicle})

    brand = vehicle.get("brand")
    model = vehicle.get("model")
    year = vehicle.get("year")
    vin = vehicle.get("vin")
    reg = vehicle.get("registration_number")

    if vision.get("document_type") == "registration_document":
        car = " ".join([str(x) for x in [brand, model, year] if x]).strip()
        lines = ["🚗 <b>Automobilio duomenys nuskaityti</b>"]
        if car:
            lines.append(f"\n🚘 {esc(car)}")
        if vin:
            lines.append(f"🔑 VIN: {esc(vin)}")
        if reg:
            lines.append(f"🔖 Nr.: {esc(reg)}")
        lines.append("\n✅ Byla atnaujinta.")
        lines.append("✍️ Apibūdinkite gedimą.")
        send_message(chat_id, "\n".join(lines), clean_menu())
        return

    send_message(chat_id, result.get("text", "Failas gautas."), clean_menu())


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V15 Modular",
        "modules": {
            "context_engine": True,
            "vehicle_engine": True,
            "intent_engine": True,
            "ev_engine": True,
            "procedure_engine": True,
            "price_engine": True,
            "response_formatter": True,
            "photo_handler": handle_photo_or_document is not None,
            "vin_decoder": decode_vin is not None,
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
            }
            ctx = update_context(BASE_DIR, chat_id, text, {"vehicle": vehicle})
            send_message(chat_id, format_vin_result(vin_result), clean_menu())
            return jsonify({"ok": True})

    if intent == "PRICE":
        send_message(chat_id, price_answer(text, ctx), clean_menu())
        return jsonify({"ok": True})

    if intent == "PROCEDURE":
        proc = answer_procedure(text, ctx)
        if proc:
            send_message(chat_id, proc, clean_menu())
            return jsonify({"ok": True})

    if intent == "EV_BATTERY" or ctx.get("topic") == "HV_BATTERY":
        send_message(chat_id, battery_analysis(ctx), clean_menu())
        return jsonify({"ok": True})

    # If only vehicle data was sent
    vehicle = detect_vehicle(text)
    if vehicle and len(text.split()) <= 5:
        label = vehicle_label(ctx.get("vehicle") or vehicle)
        send_message(chat_id, f"🚗 <b>Automobilio duomenys gauti</b>\n\nAutomobilis:\n{esc(label)}\n\nDabar apibūdinkite gedimą.", clean_menu())
        return jsonify({"ok": True})

    send_message(chat_id, fallback_question_answer(text, ctx), clean_menu())
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
