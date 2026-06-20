import os
import json
import logging
import datetime
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

from diagnostics_engine import diagnose_user_text, format_user_response
from online_sources.source_manager import get_vehicle_from_vin
from session_store import (
    create_or_update_session,
    add_user_action,
    get_session_summary,
    clear_session
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autoelektrikas_ai")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

app = Flask(__name__)


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


def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "🚗 Nauja diagnostika", "callback_data": "new_diag"}],
            [{"text": "✅ Atlikau patikrinimą", "callback_data": "add_action"}],
            [{"text": "⏭️ Praleisti žingsnį", "callback_data": "skip_step"}],
            [{"text": "📋 Diagnostikos santrauka", "callback_data": "summary"}],
            [{"text": "🧹 Išvalyti bylą", "callback_data": "clear"}],
        ]
    }


START_TEXT = """🚗 <b>AutoElektrikas AI V2</b>

Parašykite automobilio problemą paprastai.

Pavyzdžiai:
• BMW F30 po nakties neužsiveda
• VW Golf dega ABS
• Audi A4 neveikia centrinis
• P0301

Sistema nerodo kainų. Rodomas tik apytikslis diagnostikos ir remonto laikas.
"""


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V2",
        "time": datetime.datetime.utcnow().isoformat()
    })


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        data = cq.get("data", "")

        if data == "new_diag":
            clear_session(chat_id)
            send_message(chat_id, "🚗 Nauja diagnostika pradėta.\n\nParašykite problemą vienu sakiniu.")
        elif data == "add_action":
            send_message(chat_id, "Parašykite, ką patikrinote ir rezultatą.\n\nPvz.: Patikrinau akumuliatorių – 12.4 V")
        elif data == "skip_step":
            add_user_action(chat_id, "Vartotojas praleido siūlytą žingsnį.")
            send_message(chat_id, "Žingsnis praleistas. Galite parašyti, kurią kryptį norite tikrinti toliau.")
        elif data == "summary":
            send_message(chat_id, get_session_summary(chat_id), main_menu())
        elif data == "clear":
            clear_session(chat_id)
            send_message(chat_id, "Diagnostikos byla išvalyta. Galite pradėti iš naujo.", main_menu())
        else:
            send_message(chat_id, "Pasirinkimas neatpažintas.")
        return jsonify({"ok": True})

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = (message.get("text") or "").strip()

    if not chat_id:
        return jsonify({"ok": True})

    if text in ["/start", "start", "Start"]:
        send_message(chat_id, START_TEXT, main_menu())
        return jsonify({"ok": True})

    if not text:
        send_message(chat_id, "Parašykite problemą tekstu arba įveskite OBD kodą.", main_menu())
        return jsonify({"ok": True})

    clean_text = text.replace(" ", "").strip()
    if len(clean_text) == 17 and clean_text.isalnum():
        vin_result = get_vehicle_from_vin(clean_text)
        if vin_result.get("ok"):
            vin_msg = f"""🚗 <b>VIN dekodavimas</b>

Šaltinis:
{vin_result.get('source')}

Markė:
{vin_result.get('make')}

Modelis:
{vin_result.get('model')}

Metai:
{vin_result.get('model_year')}

Kėbulas:
{vin_result.get('body_class') or 'Nenurodyta'}

Variklis:
{vin_result.get('engine_model') or 'Nenurodyta'}

Kuro tipas:
{vin_result.get('fuel_type') or 'Nenurodyta'}

Toliau parašykite problemą."""
            send_message(chat_id, vin_msg, main_menu())
            return jsonify({"ok": True})

    result = diagnose_user_text(text)
    create_or_update_session(chat_id, text, result)
    response = format_user_response(result)
    send_message(chat_id, response, main_menu())

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
