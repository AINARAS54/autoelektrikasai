from __future__ import annotations

import json
from pathlib import Path

from procedure_catalog_engine import find_generic_procedure, format_generic_procedure
from vehicle_engine import brand_slug, vehicle_label


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def norm(text):
    return (text or "").lower()


def load_proc(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def score_proc(proc: dict, text: str) -> int:
    query = norm(text)
    score = 0
    for keyword in proc.get("keywords", []):
        if norm(str(keyword)) in query:
            score += 5
    title = norm(proc.get("title", ""))
    for word in query.split():
        if len(word) > 3 and word in title:
            score += 1
    return score


def find_local_procedure(base_dir: Path, text: str, ctx: dict):
    brand = brand_slug(ctx.get("vehicle") or {})
    if not brand:
        return None
    proc_dir = Path(base_dir) / "procedures" / brand
    if not proc_dir.exists():
        return None

    best, best_score = None, 0
    for path in proc_dir.glob("*.json"):
        proc = load_proc(path)
        if not isinstance(proc, dict):
            continue
        score = score_proc(proc, text)
        if score > best_score:
            best_score, best = score, proc
    return best if best_score >= 3 else None


def format_procedure(proc: dict, ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback=proc.get("vehicle", "Automobilis"))
    title = proc.get("title", "Procedūra")
    when = proc.get("when_to_use") or proc.get("when") or ""
    tools = proc.get("tools") or []
    steps = proc.get("steps") or []
    expected = proc.get("expected_result") or proc.get("result") or ""
    failed = proc.get("if_failed") or proc.get("notes") or []
    if isinstance(failed, str):
        failed = [failed]

    tools_text = "\n".join(f"• {esc(item)}" for item in tools) if tools else ""
    step_lines = []
    for index, step in enumerate(steps, 1):
        if isinstance(step, dict):
            step_lines.append(f"{index}. {esc(step.get('text', ''))}")
            if step.get("expected"):
                step_lines.append(f"   ✅ {esc(step.get('expected'))}")
        else:
            step_lines.append(f"{index}. {esc(step)}")
    steps_text = "\n".join(step_lines) if step_lines else "1. Procedūros žingsniai nenurodyti."
    failed_text = "\n".join(f"• {esc(item)}" for item in failed) if failed else ""

    parts = [f"📘 <b>{esc(title)}</b>", "", f"🚗 {esc(car)}"]
    if when:
        parts += ["", "Kada naudoti:", esc(when)]
    if tools_text:
        parts += ["", "🧰 <b>Reikės</b>", tools_text]
    parts += ["", "🔧 <b>Žingsniai</b>", steps_text]
    if expected:
        parts += ["", "✅ <b>Tikėtinas rezultatas</b>", esc(expected)]
    if failed_text:
        parts += ["", "❗ <b>Jei nepavyksta</b>", failed_text]
    return "\n".join(parts)


def answer_procedure(base_dir: Path, text: str, ctx: dict) -> str | None:
    """Return a safe procedure answer before component-location routing.

    Routing order:
    1. Generic measurement/check procedure.
    2. Manufacturer-specific local procedure.
    3. None, allowing the remaining diagnostic router to continue.
    """
    generic = find_generic_procedure(base_dir, text)
    if generic:
        car = vehicle_label(ctx.get("vehicle") or {}, fallback="")
        return format_generic_procedure(generic, car)

    local = find_local_procedure(base_dir, text, ctx)
    if local:
        return format_procedure(local, ctx)
    return None
