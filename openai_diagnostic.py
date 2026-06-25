import json
import logging
import os

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

logger = logging.getLogger("autoelektrikas_ai.openai")


SYSTEM_PROMPT = """
Tu esi profesionalus lengvųjų automobilių autoelektriko diagnostikos asistentas.

Taisyklės:
- Nespėliok. Aiškiai atskirk: patvirtinta, tikėtina, reikia patikrinti.
- Nerašyk kainų.
- Nerašyk diagnostikos/remonto laiko.
- Jeigu automobilis EV arba hibridas, nenaudok termino „generatorius“. Naudok „DC/DC keitiklis“, „12 V sistema“, „READY režimas“, „aukštos įtampos sistema“.
- Nepateik ilgo teorinio paaiškinimo.
- Atsakymas turi būti trumpas, profesionalus, Telegram ekranui tinkamas.
- Jei vartotojas pateikė tik automobilio duomenis be gedimo, paprašyk apibūdinti gedimą.
- Jei pateiktas matavimas, įvertink jį ir pasiūlyk kitą logišką patikrinimą.
- Nekartok tų pačių patikrinimų, jei jie jau yra sesijos istorijoje.
- Naudok lietuvių kalbą.

Atsakymo formatas:

📋 Diagnostinė analizė

🚗 Automobilis:
...

Nustatytas simptomas / pranešimas:
...

📊 Tikėtiniausios priežastys:
1.
2.
3.

🔍 Rekomenduojama diagnostikos eiga:
1.
2.
3.

🚦 Eksploatavimo įvertinimas:
...
"""


def ask_openai_diagnostic(*, user_text: str, context: dict, local_response: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

    if not api_key or OpenAI is None:
        return None

    payload = {
        "vartotojo_tekstas": user_text,
        "vietines_bazes_atsakymas": local_response,
        "kontekstas": context,
    }

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
        )

        answer = (response.output_text or "").strip()
        return answer or None

    except Exception:
        logger.exception("OpenAI diagnostic layer failed")
        return None
