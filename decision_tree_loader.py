import json
import re
from pathlib import Path

try:
    from vehicle_engine import brand_slug
except Exception:
    def brand_slug(vehicle):
        return ""

def _norm(text: str) -> str:
    text = (text or "").lower()
    for a, b in {"ą":"a","č":"c","ę":"e","ė":"e","į":"i","š":"s","ų":"u","ū":"u","ž":"z"}.items():
        text = text.replace(a, b)
    return text

def detect_obd_code(text: str) -> str | None:
    m = re.search(r"\b([PBUC][0-9A-F]{4})\b", (text or "").upper())
    return m.group(1) if m else None

def load_tree(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["_source_file"] = str(path)
            return data
    except Exception:
        pass
    return None

def candidate_tree_paths(base_dir: Path, text: str, ctx: dict) -> list[Path]:
    root = Path(base_dir) / "decision_trees"
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    brand = brand_slug(vehicle)
    code = detect_obd_code(text)
    paths = []
    if code:
        if brand:
            paths.append(root / brand / f"{code}.json")
        paths.append(root / "generic" / f"{code}.json")
    t = _norm(text)
    symptom_map = {
        "battery_drain.json": ["iskrauna akumuliator", "issikrauna", "parazitine srove", "iškrauna akumuliator"],
        "no_communication.json": ["nera rysio", "nėra ryšio", "no communication", "can klaida"],
        "starter_not_cranking.json": ["nesuka starter", "starteris nesuka", "neuzsiveda", "neužsiveda", "nesikuria"],
        "wheel_speed_sensor.json": ["rato greicio", "rato greičio", "abs daviklis"],
    }
    for filename, phrases in symptom_map.items():
        if any(_norm(p) in t for p in phrases):
            if brand:
                paths.append(root / brand / filename)
            paths.append(root / "generic" / filename)
    return paths

def find_tree(base_dir: Path, text: str, ctx: dict) -> dict | None:
    seen = set()
    for path in candidate_tree_paths(base_dir, text, ctx):
        if str(path) in seen:
            continue
        seen.add(str(path))
        if path.exists():
            tree = load_tree(path)
            if tree:
                return tree
    return None
