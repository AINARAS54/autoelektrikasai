from vehicle_engine import vehicle_label
from context_engine import get_range_summary, is_12v_battery_text

def esc(v): return str(v or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def price_answer(text: str, ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback="Automobilis")
    topic = ctx.get("topic")
    if is_12v_battery_text(text) or topic == "12V_BATTERY":
        return f"""💰 <b>12 V akumuliatoriaus keitimo kaina</b>

Automobilis:
{esc(car)}

Orientacinės kainos:
• 12 V AGM akumuliatorius: apie 80–250 €
• Keitimo darbas: apie 50–150 €
• Akumuliatoriaus registracija / BMS adaptacija: apie 50–150 €
• Diagnostika po keitimo: apie 50–120 €

Bendra suma dažniausiai:
• nepriklausomame servise: apie 150–400 €
• oficialiame servise: apie 250–600 €+"""
    if topic == "HV_BATTERY" or ctx.get("subtopic") == "RANGE_DECREASE" or "bater" in (text or "").lower():
        summary = get_range_summary(ctx)
        block = f"\n\nAktyvios bylos kontekstas:\n{summary}" if summary else ""
        return f"""💰 <b>HV baterijos remonto kaina</b>

Automobilis:
{esc(car)}{esc(block)}

Orientacinės kainos:
• BMS diagnostika / SOH patikra: apie 100–300 €
• SOH matavimas: apie 50–150 €
• Modulių įtampos ir balanso patikra: apie 100–300 €
• BMS programinės įrangos atnaujinimas: apie 150–400 €
• Vieno baterijos modulio keitimas: apie 500–1500 €+
• Kelių modulių remontas: apie 1500–4000 €+
• Aukštos įtampos baterijos restauravimas: apie 2000–6000 €+
• Naudotas baterijos paketas: apie 3000–8000 €+
• Naujas baterijos paketas: apie 12000–20000 €+

Pastaba:
Pirmiausia reikalinga BMS/SOH diagnostika."""
    return f"""💰 <b>Apytikslė kaina</b>

Automobilis:
{esc(car)}

Kainai patikslinti reikia žinoti:
1. Kuri detalė ar sistema.
2. Nauja, naudota ar restauruota dalis.
3. Ar reikės programavimo / adaptacijos.
4. Automobilio VIN arba tiksli komplektacija."""
