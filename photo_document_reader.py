import base64
import json
import logging
import os
from pathlib import Path

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

logger = logging.getLogger("autoelektrikas_ai.vision")


VISION_PROMPT = """
Tu analizuoji automobilio registracijos dokumento, techninio paso, prietaisų skydelio, OBD skaitytuvo arba multimetro nuotrauką.

Ištrauk tik aiškiai matomą informaciją. Nespėliok.

Grąžink tik JSON, be papildomo teksto.

JSON formatas:
{
  "document_type": "registration_document | dashboard | obd_scanner | multimeter | unknown",
  "vehicle": {
    "brand": null,
    "model": null,
    "year": null,
    "vin": null,
    "registration_number": null,
    "fuel_type": null,
    "vehicle_type": null
  },
  "dashboard": {
    "messages": [],
    "warning_lights": [],
    "ready_status": null,
    "mileage": null
  },
  "obd": {
    "codes": [],
    "tool_name": null
  },
  "measurement": {
    "type": null,
    "value": null,
    "unit": null
  },
  "confidence": "low | medium | high",
  "notes": []
}

Taisyklės:
- Jei nematai duomens, rašyk null.
- VIN turi būti 17 simbolių, jei matomas.
- Jei dokumente matosi BMW i3, modelis turi būti "i3".
- Jei automobilis elektrinis, fuel_type gali būti "electric".
"""


def _encode_image(image_path: str) -> str:
    path = Path(image_path)
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def analyze_vehicle_image(image_path: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")).strip()

    if not api_key or OpenAI is None:
        return {"ok": False, "error": "OPENAI_API_KEY arba OpenAI biblioteka nenustatyta"}

    try:
        image_b64 = _encode_image(image_path)
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": VISION_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Išanalizuok šią automobilio nuotrauką ir grąžink JSON."},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_b64}"},
                    ],
                },
            ],
            temperature=0.0,
        )

        raw = (response.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()

        data = json.loads(raw)
        data["ok"] = True
        return data

    except Exception as exc:
        logger.exception("Vision image analysis failed")
        return {"ok": False, "error": str(exc)}


def format_vehicle_image_result(result: dict) -> str:
    if not result.get("ok"):
        return "Nuotraukos nepavyko apdoroti. Įveskite automobilio duomenis tekstu."

    vehicle = result.get("vehicle") or {}
    doc_type = result.get("document_type") or "unknown"

    brand = vehicle.get("brand")
    model = vehicle.get("model")
    year = vehicle.get("year")
    vin = vehicle.get("vin")
    reg = vehicle.get("registration_number")
    fuel = vehicle.get("fuel_type")

    car_line = " ".join([x for x in [brand, model, str(year) if year else None] if x]).strip()

    if doc_type == "registration_document":
        lines = ["🚗 <b>Automobilio duomenys nuskaityti</b>"]
        if car_line:
            lines.append(f"\nAutomobilis:\n{car_line}")
        if vin:
            lines.append(f"\nVIN:\n{vin}")
        if reg:
            lines.append(f"\nValstybinis nr.:\n{reg}")
        if fuel:
            lines.append(f"\nKuro tipas:\n{fuel}")
        lines.append("\nByla atnaujinta.")
        lines.append("\nDabar apibūdinkite gedimą.")
        return "\n".join(lines)

    if doc_type == "dashboard":
        dashboard = result.get("dashboard") or {}
        messages = dashboard.get("messages") or []
        warnings = dashboard.get("warning_lights") or []
        lines = ["📸 <b>Prietaisų skydelio informacija nuskaityta</b>"]
        if messages:
            lines.append("\nPranešimai:")
            for item in messages[:5]:
                lines.append(f"• {item}")
        if warnings:
            lines.append("\nĮspėjimai:")
            for item in warnings[:5]:
                lines.append(f"• {item}")
        lines.append("\nAprašykite, kada šis pranešimas atsiranda.")
        return "\n".join(lines)

    if doc_type == "obd_scanner":
        obd = result.get("obd") or {}
        codes = obd.get("codes") or []
        lines = ["⚡ <b>OBD informacija nuskaityta</b>"]
        if codes:
            lines.append("\nKlaidos kodai:")
            for code in codes[:10]:
                lines.append(f"• {code}")
        lines.append("\nAprašykite simptomą arba parašykite, kada klaida atsiranda.")
        return "\n".join(lines)

    if doc_type == "multimeter":
        measurement = result.get("measurement") or {}
        value = measurement.get("value")
        unit = measurement.get("unit")
        mtype = measurement.get("type")
        lines = ["📏 <b>Matavimas nuskaitytas</b>"]
        if value is not None:
            lines.append(f"\nRezultatas:\n{value} {unit or ''}".strip())
        if mtype:
            lines.append(f"\nMatavimo tipas:\n{mtype}")
        lines.append("\nMatavimas įrašytas į bylą.")
        return "\n".join(lines)

    return "Nuotrauka gauta, tačiau jos tipas neatpažintas. Įveskite automobilio duomenis arba gedimo aprašymą."
