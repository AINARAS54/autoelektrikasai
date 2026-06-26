import json
from pathlib import Path


PROCEDURES_DIR = Path(__file__).resolve().parent / "procedures"


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def load_procedures() -> list[dict]:
    procedures = []
    if not PROCEDURES_DIR.exists():
        return procedures

    for path in PROCEDURES_DIR.rglob("*.json"):
        try:
            procedures.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return procedures


def find_procedure(text: str, vehicle: dict | None = None) -> dict | None:
    text_norm = _normalize(text)
    vehicle = vehicle or {}
    brand = _normalize(vehicle.get("brand") or vehicle.get("make") or "")
    model = _normalize(vehicle.get("model") or "")

    best = None
    best_score = 0

    for proc in load_procedures():
        score = 0
        proc_brand = _normalize(proc.get("brand"))
        proc_model = _normalize(proc.get("model"))

        if brand and proc_brand and brand == proc_brand:
            score += 5
        if model and proc_model and model == proc_model:
            score += 5

        for kw in proc.get("keywords", []):
            if _normalize(kw) in text_norm:
                score += 3

        if score > best_score:
            best = proc
            best_score = score

    if best and best_score >= 6:
        return best
    return None


def format_procedure(proc: dict) -> str:
    title = proc.get("title") or "Procedūra"
    vehicle = " ".join([str(x) for x in [proc.get("brand"), proc.get("model")] if x])
    steps = proc.get("steps") or []
    notes = proc.get("notes") or []

    lines = [f"📘 <b>{title}</b>"]
    if vehicle:
        lines.append(f"\nAutomobilis: {vehicle}")

    lines.append("\nŽingsniai:")
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")

    if notes:
        lines.append("\nPastabos:")
        for note in notes:
            lines.append(f"• {note}")

    return "\n".join(lines)
