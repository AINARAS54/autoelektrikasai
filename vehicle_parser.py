import re


def normalize(text: str) -> str:
    return (text or "").lower().strip()


def detect_brand(text: str, brands: dict | None = None):
    t = normalize(text)

    if brands:
        for brand in brands:
            if brand.lower() in t:
                return brand

    aliases = {
        "vw": "Volkswagen",
        "mb": "Mercedes-Benz",
        "mersedes": "Mercedes-Benz",
        "mersas": "Mercedes-Benz",
        "bmw": "BMW",
        "audi": "Audi",
        "volvo": "Volvo",
        "toyota": "Toyota",
        "ford": "Ford",
        "opel": "Opel",
        "peugeot": "Peugeot",
        "renault": "Renault",
    }

    for key, brand in aliases.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            return brand

    return None


def detect_model(text: str):
    t = normalize(text)

    models = [
        "i3", "i4", "i5", "i7", "ix",
        "f30", "f10", "e90", "e60", "g30",
        "golf", "passat", "tiguan", "touran",
        "a3", "a4", "a6", "q5", "q7",
        "corolla", "avensis", "yaris",
    ]

    for model in models:
        if re.search(rf"\b{re.escape(model)}\b", t):
            return model.upper() if model.startswith(("f", "e", "g", "q")) else model

    return None


def detect_year(text: str):
    m = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", text)
    return m.group(1) if m else None


def detect_obd(text: str):
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None


def is_ev_vehicle(text: str, brand=None, model=None):
    t = normalize(text)
    ev_terms = [
        "elektromobil",
        "electric",
        "ev",
        "bev",
        "hybrid",
        "hibrid",
        "bmw i3",
        "bmw i4",
        "bmw i5",
        "bmw i7",
        "bmw ix",
    ]

    if any(x in t for x in ev_terms):
        return True

    return brand == "BMW" and model and model.lower() in ["i3", "i4", "i5", "i7", "ix"]


def parse_vehicle(text: str, brands: dict | None = None) -> dict:
    brand = detect_brand(text, brands)
    model = detect_model(text)
    year = detect_year(text)
    return {
        "brand": brand,
        "model": model,
        "year": year,
        "is_ev_or_hybrid": is_ev_vehicle(text, brand, model),
    }
