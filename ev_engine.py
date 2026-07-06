from vehicle_engine import vehicle_label
from context_engine import get_range_summary

def esc(v): return str(v or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def battery_analysis(ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback="Elektromobilis")
    summary = get_range_summary(ctx)
    m = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    loss = m.get("range_loss_percent")
    verdict = ""
    if loss is not None:
        if loss >= 30:
            verdict = f"\n\nVertinimas:\n🔴 Apie {loss} % nuvažiuojamos ridos sumažėjimas yra didelis. Reikalinga BMS/SOH ir modulių balansavimo patikra."
        elif loss >= 20:
            verdict = f"\n\nVertinimas:\n🟡 Apie {loss} % sumažėjimas yra pastebimas. Reikalinga baterijos būklės patikra."
    block = f"\n\n{summary}" if summary else ""
    return f"""🔋 <b>Aukštos įtampos baterijos analizė</b>

Automobilis:
{esc(car)}{esc(block)}{esc(verdict)}

Pastaba:
Tai nėra tikras baterijos SOH. Tikrą SOH galima nustatyti tik BMS diagnostika.

Galimos priežastys:
1. Natūrali baterijos elementų degradacija.
2. Netiksli BMS talpos adaptacija.
3. Vieno ar kelių modulių disbalansas.
4. Padidėjusi elementų vidinė varža.
5. Temperatūros daviklių arba BMS klaidos.

Rekomenduojama patikra:
1. Nuskaityti BMS klaidas.
2. Patikrinti SOH.
3. Patikrinti modulių įtampas ir balansą.
4. Patikrinti elementų temperatūrų skirtumus.
5. Įvertinti baterijos vidinę varžą."""
