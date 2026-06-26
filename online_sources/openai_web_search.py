import json
import logging
import os

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

logger = logging.getLogger("autoelektrikas_ai.web_search")


def web_search_answer(query: str, vehicle: dict | None = None) -> dict:
    """
    Naudoja OpenAI web_search įrankį, jei paskyra/modelis tai palaiko.
    Jei nepalaiko, grąžina ok=False.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_SEARCH_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")).strip()

    if not api_key or OpenAI is None:
        return {"ok": False, "error": "OpenAI web search neprieinamas."}

    vehicle = vehicle or {}
    prompt = {
        "query": query,
        "vehicle": vehicle,
        "instruction": (
            "Ieškok patikimos automobilių techninės informacijos. "
            "Jei nerandi patikimo šaltinio, pasakyk, kad procedūra nepatvirtinta. "
            "Atsakyk lietuviškai. Nenaudok žodžio nulaužti/nulaužimas serviso atstatymui."
        ),
    }

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=[
                {
                    "role": "system",
                    "content": "Tu esi autoelektriko techninių šaltinių paieškos modulis. Nesugalvok procedūrų be šaltinio."
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0.1,
        )
        return {"ok": True, "source": "OpenAI web_search", "answer": response.output_text}

    except Exception as exc:
        logger.exception("OpenAI web search failed")
        return {"ok": False, "error": str(exc)}
