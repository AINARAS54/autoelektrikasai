import os, json, logging, datetime, re
from pathlib import Path
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from response_formatter import clean_telegram_text
from vehicle_engine import detect_vehicle, vehicle_label
from intent_engine import detect_intent
from context_engine import update_context, clear_context, archive_context
from obd_engine import answer_obd
from procedure_engine import answer_procedure
from price_engine import price_answer
from ev_engine import battery_analysis
from service_engine import answer_service
from vision_engine import handle_vehicle_photo

from decision_tree_engine import start_tree, handle_decision_callback, render_node, keyboard_for_node
from decision_session import save_decision_session
from decision_tree_router import should_offer_decision_tree

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# ==========================================================
# AutoElektrikas AI V21.1
# app.py = router
# V20: Diagnostic Decision Trees + Telegram buttons
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


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram_api(method: str, payload: dict):
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN missing")
        return None

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=25
        )
        if not r.ok:
            logger.error("Telegram error: %s %s", r.status_code, r.text)
        return r.json()
    except Exception as e:
        logger.exception("Telegram request failed: %s", e)
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
            [{"text": "📂 Nauja byla", "callback_data": "new_case"}]
        ]
    }


def start_menu():
    return None


def fallback_ai_answer(text: str, ctx: dict) -> str:
    if not OPENAI_API_KEY or OpenAI is None:
        return "Parašykite daugiau informacijos apie automobilį, gedimą arba patikros rezultatą."

    system = """
Tu esi profesionalus lengvųjų automobilių autoelektrikas.
Atsakyk lietuviškai, praktiškai ir trumpai.
Nerodyk interneto nuorodų.
Nenaudok markdown žymėjimo su žvaigždutėmis.
Jei trūksta duomenų, prašyk konkretaus matavimo arba kodo.
"""

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": text, "context": ctx},
                        ensure_ascii=False
                    )
                },
            ],
            temperature=0.2,
        )
        return res.output_text or "Nepavyko paruošti atsakymo."
    except Exception:
        logger.exception("fallback AI failed")
        return "Nepavyko paruošti atsakymo. Parašykite daugiau automobilio duomenų arba gedimo požymių."



def normalize_symptom_text(text: str) -> str:
    value = (text or "").lower()
    for source, target in {
        "ą": "a", "č": "c", "ę": "e", "ė": "e", "į": "i",
        "š": "s", "ų": "u", "ū": "u", "ž": "z",
    }.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9\s/+-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


SYMPTOM_TREE_ALIASES = {
    "no_start_cranks.json": [
        "starteris suka bet neuzsiveda",
        "starteris suka bet nesikuria",
        "suka bet neuzsiveda",
        "suka bet nesikuria",
        "variklis suka bet neuzsiveda"
    ],
    "no_crank.json": [
        "starteris nesuka",
        "starteris visai nesuka",
        "paspaudus start nieko",
        "pasukus rakta nieko",
        "neprasuka variklio"
    ],
    "starts_then_stalls.json": [
        "uzsiveda ir uzgesta",
        "uzsiveda ir iskart uzgesta",
        "pasileidzia ir uzgesta",
        "variklis uzsiveda bet uzgesta"
    ],
    "alternator_not_charging.json": [
        "nekrauna generatorius",
        "generatorius nekrauna",
        "akumuliatoriaus lempute",
        "nera krovimo",
        "per maza krovimo itampa",
        "12 v nekrauna"
    ],
    "abs_warning.json": [
        "dega abs",
        "abs lempute",
        "dega esp",
        "esp lempute",
        "abs neveikia",
        "traction control lempute"
    ],
    "hv_not_ready.json": [
        "neisijungia ready",
        "neijungia ready",
        "ready rezimas neisijungia",
        "elektromobilis neisijungia",
        "hibridas neisijungia",
        "hv sistema nepasiruosia"
    ],
}


def find_symptom_tree(base_dir: Path, text: str):
    root = Path(base_dir) / "symptom_trees"
    if not root.exists():
        return None, None

    normalized = normalize_symptom_text(text)
    best_filename = None
    best_score = 0
    text_words = set(normalized.split())

    for filename, aliases in SYMPTOM_TREE_ALIASES.items():
        score = 0
        for alias in aliases:
            alias_n = normalize_symptom_text(alias)
            if alias_n in normalized:
                score += 10
            else:
                overlap = len(set(alias_n.split()) & text_words)
                if overlap >= 2:
                    score += overlap
        if score > best_score:
            best_filename = filename
            best_score = score

    if not best_filename or best_score < 4:
        return None, None

    path = root / best_filename
    if not path.exists():
        return None, None

    try:
        tree = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(tree, dict):
            return None, None
        tree["_source_file"] = str(path)
        return tree, path
    except Exception:
        logger.exception("Nepavyko įkelti simptomų medžio: %s", path)
        return None, None


def should_offer_symptom_tree(base_dir: Path, text: str) -> bool:
    tree, _ = find_symptom_tree(base_dir, text)
    return tree is not None


def start_symptom_tree(base_dir: Path, chat_id: str, text: str, ctx: dict):
    tree, path = find_symptom_tree(base_dir, text)
    if not tree or not path:
        return None, None

    start_node = tree.get("start", "start")
    session = {
        "tree_id": tree.get("id"),
        "tree_title": tree.get("title"),
        "source_file": str(path),
        "current_node": start_node,
        "answers": [],
        "ctx_vehicle": ctx.get("vehicle", {}),
        "tree_type": "symptom",
    }
    save_decision_session(base_dir, chat_id, session)
    return render_node(tree, start_node, session), keyboard_for_node(tree, start_node)

def handle_new_case(chat_id: str):
    case_id = archive_context(BASE_DIR, chat_id)
    if case_id:
        send_message(
            chat_id,
            "📂 Ankstesnė byla išsaugota.\n\n🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.",
            start_menu()
        )
    else:
        send_message(
            chat_id,
            "🆕 Nauja byla pradėta.\n\nĮveskite automobilio duomenis ir apibūdinkite gedimą.",
            start_menu()
        )


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AutoElektrikas AI V21.1",
        "features": [
            "router_app",
            "local_obd_database",
            "local_procedure_library",
            "decision_tree_diagnostics",
            "symptom_tree_diagnostics",
            "telegram_yes_no_buttons",
            "case_context",
            "case_archive"
        ],
        "time": datetime.datetime.now(datetime.UTC).isoformat()
    })


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    # ------------------------------------------------------
    # Callback buttons
    # ------------------------------------------------------
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        data = cq.get("data", "")

        if not chat_id:
            return jsonify({"ok": True})

        # V20 decision tree buttons
        if data.startswith("dt:"):
            answer, markup = handle_decision_callback(BASE_DIR, chat_id, data)
            send_message(chat_id, answer, markup)
            return jsonify({"ok": True})

        if data == "new_case":
            handle_new_case(chat_id)
            return jsonify({"ok": True})

        send_message(chat_id, "Pasirinkimas neatpažintas.", start_menu())
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # Normal message
    # ------------------------------------------------------
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))

    if not chat_id:
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # Photo / document
    # ------------------------------------------------------
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

    # ------------------------------------------------------
    # 1. System commands
    # ------------------------------------------------------
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

    # ------------------------------------------------------
    # 2. VIN / vehicle only
    # ------------------------------------------------------
    vehicle = detect_vehicle(text)

    if intent == "VIN" and vehicle.get("vin"):
        ctx = update_context(BASE_DIR, chat_id, text, {"vehicle": vehicle})
        send_message(
            chat_id,
            f"🚗 <b>VIN gautas</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\nVIN: {esc(vehicle.get('vin'))}\n\nDabar apibūdinkite gedimą.",
            clean_menu()
        )
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 3. OBD
    # V20: if decision tree exists, start interactive diagnostic tree.
    # If no tree exists, return normal OBD explanation.
    # ------------------------------------------------------
    if intent == "OBD":
        if should_offer_decision_tree(BASE_DIR, text, ctx):
            answer, markup = start_tree(BASE_DIR, chat_id, text, ctx)
            send_message(chat_id, answer, markup)
        else:
            send_message(chat_id, answer_obd(BASE_DIR, text, ctx), clean_menu())
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 4. Price has priority over diagnostics
    # ------------------------------------------------------
    if intent == "PRICE":
        send_message(chat_id, price_answer(text, ctx), clean_menu())
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 5. Procedures
    # ------------------------------------------------------
    if intent in ["PROCEDURE", "PROCEDURE_12V_BATTERY"]:
        answer = answer_procedure(BASE_DIR, text, ctx)
        if answer:
            send_message(chat_id, answer, clean_menu())
            return jsonify({"ok": True})

    # ------------------------------------------------------
    # 6. Service / maintenance
    # ------------------------------------------------------
    service_answer = answer_service(BASE_DIR, text, ctx)
    if service_answer:
        send_message(chat_id, service_answer, clean_menu())
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 7. V21.1 symptom trees
    # ------------------------------------------------------
    if should_offer_symptom_tree(BASE_DIR, text):
        answer, markup = start_symptom_tree(BASE_DIR, chat_id, text, ctx)
        if answer:
            send_message(chat_id, answer, markup)
            return jsonify({"ok": True})

    # ------------------------------------------------------
    # 8. EV / HV
    # ------------------------------------------------------
    if intent == "EV_BATTERY" or ctx.get("topic") == "HV_BATTERY":
        send_message(chat_id, battery_analysis(ctx), clean_menu())
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 9. Other decision trees
    # ------------------------------------------------------
    if should_offer_decision_tree(BASE_DIR, text, ctx):
        answer, markup = start_tree(BASE_DIR, chat_id, text, ctx)
        send_message(chat_id, answer, markup)
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 10. Vehicle-only
    # ------------------------------------------------------
    if vehicle and len(text.split()) <= 5:
        send_message(
            chat_id,
            f"🚗 <b>Automobilio duomenys gauti</b>\n\nAutomobilis:\n{esc(vehicle_label(ctx.get('vehicle') or vehicle))}\n\nDabar apibūdinkite gedimą.",
            clean_menu()
        )
        return jsonify({"ok": True})

    # ------------------------------------------------------
    # 11. AI fallback
    # ------------------------------------------------------
    send_message(chat_id, fallback_ai_answer(text, ctx), clean_menu())
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
