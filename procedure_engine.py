import json
from pathlib import Path
from vehicle_engine import brand_slug, vehicle_label

def esc(v): return str(v or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def norm(t): return (t or "").lower()

def load_proc(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def score_proc(proc: dict, text: str) -> int:
    t = norm(text)
    score = 0
    for k in proc.get("keywords", []):
        if norm(k) in t:
            score += 5
    title = norm(proc.get("title", ""))
    for word in t.split():
        if len(word) > 3 and word in title:
            score += 1
    return score

def find_local_procedure(base_dir: Path, text: str, ctx: dict):
    brand = brand_slug(ctx.get("vehicle") or {}) or "bmw"
    proc_dir = Path(base_dir) / "procedures" / brand
    if not proc_dir.exists():
        return None
    best, best_score = None, 0
    for path in proc_dir.glob("*.json"):
        proc = load_proc(path)
        if not isinstance(proc, dict):
            continue
        s = score_proc(proc, text)
        if s > best_score:
            best_score, best = s, proc
    return best if best_score >= 3 else None

def format_procedure(proc: dict, ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback=proc.get("vehicle", "Automobilis"))
    title = proc.get("title", "Procedūra")
    when = proc.get("when_to_use") or proc.get("when") or ""
    tools = proc.get("tools") or []
    steps = proc.get("steps") or []
    expected = proc.get("expected_result") or proc.get("result") or ""
    failed = proc.get("if_failed") or proc.get("notes") or []
    tools_txt = "\n".join([f"• {esc(x)}" for x in tools]) if tools else ""
    steps_txt = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(steps)]) if steps else "1. Procedūros žingsniai nenurodyti."
    failed_txt = "\n".join([f"• {esc(x)}" for x in failed]) if failed else ""
    parts = [f"📘 <b>{esc(title)}</b>", "", "🚗 Automobilis:", esc(car)]
    if when: parts += ["", "Kada naudoti:", esc(when)]
    if tools_txt: parts += ["", "Reikalinga:", tools_txt]
    parts += ["", "🔧 Žingsniai:", steps_txt]
    if expected: parts += ["", "✅ Tikėtinas rezultatas:", esc(expected)]
    if failed_txt: parts += ["", "❗ Jei nepavyksta:", failed_txt]
    return "\n".join(parts)

def answer_12v(ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback="Automobilis")
    return f"""📘 <b>12 V akumuliatoriaus keitimas</b>

🚗 Automobilis:
{esc(car)}

Keitimo eiga:
1. Išjunkite automobilį ir palaukite kelias minutes.
2. Atjunkite įkrovimo laidą, jei jis prijungtas.
3. Pasiekite 12 V akumuliatorių pagal konkretaus modelio vietą.
4. Pirmiausia atjunkite neigiamą (-) gnybtą.
5. Tada atjunkite teigiamą (+) gnybtą.
6. Įdėkite naują tinkamos talpos ir tipo akumuliatorių.
7. Prijunkite teigiamą (+), po to neigiamą (-) gnybtą.
8. Jei reikia, atlikite akumuliatoriaus registraciją / BMS adaptaciją.

Svarbu:
EV automobiliuose po 12 V akumuliatoriaus keitimo rekomenduojama patikrinti DC/DC krovimą ir ištrinti senas klaidas."""

def answer_procedure(base_dir: Path, text: str, ctx: dict) -> str | None:
    t = norm(text)
    if any(x in t for x in ["start bater", "starto bater", "12v", "12 v", "starto akumuliator"]):
        return answer_12v(ctx)
    proc = find_local_procedure(base_dir, text, ctx)
    if proc:
        return format_procedure(proc, ctx)
    return None
