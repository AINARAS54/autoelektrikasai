import re

def detect_vehicle(text: str) -> dict:
    t = (text or "").lower()
    vehicle = {}
    brands = {
        "bmw": "BMW", "audi": "Audi", "vw": "Volkswagen", "volkswagen": "Volkswagen",
        "mercedes": "Mercedes-Benz", "toyota": "Toyota", "volvo": "Volvo",
        "tesla": "Tesla", "nissan": "Nissan", "hyundai": "Hyundai", "kia": "Kia",
        "ford": "Ford", "opel": "Opel", "peugeot": "Peugeot", "renault": "Renault",
        "citroen": "Citroen", "skoda": "Skoda", "seat": "Seat", "lexus": "Lexus",
    }
    for k, v in brands.items():
        if re.search(rf"\b{re.escape(k)}\b", t):
            vehicle["brand"] = v
            break
    for m in ["i3","i4","i5","i7","ix","id.3","id3","id.4","id4","golf","passat","tiguan","a3","a4","a6","q5","q7","model 3","model y","leaf","kona","niro","f30","f10","e90","e60","g30"]:
        if re.search(rf"\b{re.escape(m)}\b", t):
            vehicle["model"] = {"id3": "ID.3", "id4": "ID.4"}.get(m, m.upper() if m in ["q5","q7","f30","f10","e90","e60","g30"] else m)
            break
    y = re.search(r"\b(19[8-9]\d|20[0-3]\d)\s*m?\.?\b", t)
    if y:
        vehicle["year"] = y.group(1)
    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", (text or "").upper().replace(" ", ""))
    if vin:
        vehicle["vin"] = vin.group(0)
    return vehicle

def vehicle_label(vehicle: dict, fallback="Nenurodytas automobilis") -> str:
    vehicle = vehicle or {}
    label = " ".join([str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x]).strip()
    return label or fallback

def brand_slug(vehicle: dict) -> str:
    b = (vehicle or {}).get("brand", "")
    return {
        "BMW": "bmw", "Audi": "audi", "Volkswagen": "vw", "Mercedes-Benz": "mercedes",
        "Toyota": "toyota", "Lexus": "lexus", "Hyundai": "hyundai", "Kia": "kia",
        "Ford": "ford", "Opel": "opel", "Peugeot": "peugeot", "Renault": "renault",
        "Citroen": "citroen", "Nissan": "nissan", "Tesla": "tesla", "Volvo": "volvo",
        "Skoda": "skoda", "Seat": "seat",
    }.get(b, b.lower())
