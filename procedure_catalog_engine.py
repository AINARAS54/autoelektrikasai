from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _norm(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("ą", "a").replace("č", "c").replace("ę", "e")
    value = value.replace("ė", "e").replace("į", "i").replace("š", "s")
    value = value.replace("ų", "u").replace("ū", "u").replace("ž", "z")
    return re.sub(r"\s+", " ", value).strip()


def _esc(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _score(item: dict, query: str) -> int:
    text = _norm(query)
    score = 0
    for phrase in item.get("keywords", []):
        p = _norm(str(phrase))
        if p and p in text:
            score += 10 + len(p.split())
    for word in _norm(str(item.get("title", ""))).split():
        if len(word) >= 4 and word in text:
            score += 2
    return score


def find_generic_procedure(base_dir: Path, query: str) -> dict | None:
    directory = Path(base_dir) / "procedures" / "generic"
    if not directory.exists():
        return None

    best: dict | None = None
    best_score = 0
    for path in directory.glob("*.json"):
        item = _load_json(path)
        if not item:
            continue
        score = _score(item, query)
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= 10 else None


def format_generic_procedure(item: dict, vehicle_label: str = "") -> str:
    parts = [f"🔧 <b>{_esc(item.get('title') or 'Patikros procedūra')}</b>"]
    if vehicle_label:
        parts += ["", f"🚗 {_esc(vehicle_label)}"]

    safety = item.get("safety") or []
    if safety:
        parts += ["", "⚠️ <b>Sauga</b>"]
        parts.extend(f"• {_esc(line)}" for line in safety)

    tools = item.get("tools") or []
    if tools:
        parts += ["", "🧰 <b>Reikės</b>"]
        parts.extend(f"• {_esc(line)}" for line in tools)

    steps = item.get("steps") or []
    if steps:
        parts += ["", "📋 <b>Patikra</b>"]
        for index, step in enumerate(steps, 1):
            if isinstance(step, dict):
                text = step.get("text", "")
                expected = step.get("expected")
                parts.append(f"{index}. {_esc(text)}")
                if expected:
                    parts.append(f"   ✅ {_esc(expected)}")
            else:
                parts.append(f"{index}. {_esc(step)}")

    interpretation = item.get("interpretation") or []
    if interpretation:
        parts += ["", "📊 <b>Rezultatų vertinimas</b>"]
        parts.extend(f"• {_esc(line)}" for line in interpretation)

    note = item.get("note")
    if note:
        parts += ["", f"ℹ️ {_esc(note)}"]
    return "\n".join(parts)
