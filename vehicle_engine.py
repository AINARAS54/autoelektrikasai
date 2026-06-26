import re


def normalize(text: str) -> str:
    return (text or "").lower().strip()


BRANDS = {
    "bmw": "BMW",
    "audi": "Audi",
    "vw": "Volkswagen",
    "volkswagen": "Volkswagen",
    "mercedes": "Mercedes-Benz",
    "toyota": "Toyota",
    "volvo": "Volvo",
    "tesla": "Tesla",
    "nissan": "Nissan",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "ford": "Ford",
    "opel": "Opel",
    "peugeot": "Peugeot",
    "renault": "Renault",
}


MODELS = [
    "i3", "i4", "i5", "i7", "ix",
    "id.3", "id3", "id.4", "id4",
    "golf", "passat", "tiguan", "touran",
    "a3", "a4", "a6", "q5", "q7",
    "model 3", "model y", "leaf", "kona", "niro",
    "f30", "f10", "e90", "e60", "g30",
]


def detect_vehicle(text: str) -> dict:
    t = normalize(text)
    vehicle = {}

    for key, value in BRANDS.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            vehicle["brand"] = value
            break

    for model in MODELS:
        if re.search(rf"\b{re.escape(model)}\b", t):
            if model == "id3":
                model = "ID.3"
            elif model == "id4":
                model = "ID.4"
            elif model in ["f30", "f10", "e90", "e60", "g30", "q5", "q7"]:
                model = model.upper()
            vehicle["model"] = model
            break

    year = re.search(r"\b(19[8-9]\d|20[0-3]\d)\s*m?\.?\b", t)
    if year:
        vehicle["year"] = year.group(1)

    vin_text = (text or "").upper().replace(" ", "")
    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", vin_text)
    if vin:
        vehicle["vin"] = vin.group(0)

    return vehicle


def is_ev(vehicle: dict, text: str = "") -> bool:
    t = normalize(text)
    brand = vehicle.get("brand")
    model = str(vehicle.get("model") or "").lower()
    if any(x in t for x in ["elektromobil", "electric", "ev", "bev", "aukštos įtampos", "aukstos itampos"]):
        return True
    if brand == "BMW" and model in ["i3", "i4", "i5", "i7", "ix"]:
        return True
    if brand == "Tesla":
        return True
    if model in ["id.3", "id.4", "id3", "id4", "leaf", "kona", "niro"]:
        return True
    return False


def vehicle_label(vehicle: dict, fallback: str = "Nenurodytas automobilis") -> str:
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    label = " ".join([str(x) for x in parts if x]).strip()
    return label or fallback
