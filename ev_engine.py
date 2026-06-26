from response_formatter import esc
from context_engine import get_vehicle_label, get_hv_range_summary


def battery_analysis(ctx: dict) -> str:
    car = get_vehicle_label(ctx)
    if car == "Nenurodytas automobilis":
        car = "Elektromobilis"

    summary = get_hv_range_summary(ctx)
    block = f"\n\n{summary}" if summary else ""

    measurements = ctx.get("measurements") if isinstance(ctx.get("measurements"), dict) else {}
    loss = measurements.get("range_loss_percent")
    conclusion = ""
    if loss is not None:
        if loss >= 30:
            conclusion = f"\n\nVertinimas:\n🔴 Apie {loss} % sumažėjimas yra didelis. Reikalinga BMS/SOH ir modulių balansavimo patikra."
        elif loss >= 20:
            conclusion = f"\n\nVertinimas:\n🟡 Apie {loss} % sumažėjimas yra pastebimas. Reikalinga baterijos būklės patikra."
        else:
            conclusion = f"\n\nVertinimas:\n🟢 Apie {loss} % sumažėjimas gali būti artimas natūraliai degradacijai, bet SOH patikra vis tiek naudinga."

    return f"""🔋 <b>Aukštos įtampos baterijos analizė</b>

Automobilis:
{esc(car)}{esc(block)}{esc(conclusion)}

Galimos priežastys:
1. Natūrali baterijos elementų degradacija.
2. Netiksli BMS talpos adaptacija.
3. Vieno ar kelių modulių disbalansas.
4. Padidėjusi elementų vidinė varža.
5. Temperatūros daviklių arba BMS klaidos.

Ar galima „atstatyti“ bateriją?
Visiškai atkurti pradinės fizinės talpos negalima, jei elementai susidėvėję. Tačiau kai kuriais atvejais galima pagerinti veikimą:
• atlikti BMS adaptaciją;
• subalansuoti modulius;
• pakeisti silpnus modulius;
• atnaujinti BMS programinę įrangą, jei gamintojas tai numato.

Rekomenduojama patikra:
1. Nuskaityti BMS klaidas.
2. Patikrinti SOH.
3. Patikrinti modulių įtampas ir balansą.
4. Patikrinti elementų temperatūrų skirtumus.
5. Įvertinti baterijos vidinę varžą."""


def hv_battery_price(ctx: dict) -> str:
    car = get_vehicle_label(ctx)
    if car == "Nenurodytas automobilis":
        car = "Elektromobilis"

    summary = get_hv_range_summary(ctx)
    block = f"\n\nKontekstas:\n{summary}" if summary else ""

    return f"""💰 <b>HV baterijos remonto kaina</b>

Automobilis:
{esc(car)}{esc(block)}

Orientacinės kainos:
• BMS diagnostika / SOH patikra: apie 100–300 €
• Modulių įtampos ir balanso patikra: apie 100–300 €
• Vieno modulio keitimas: apie 500–1500 €+
• Naudotas baterijos paketas: apie 3000–8000 €+
• Baterijos paketo restauravimas: kaina priklauso nuo modulių būklės.

Prieš remontą būtina patikrinti:
1. SOH.
2. Modulių įtampas.
3. Modulių balansą.
4. BMS klaidas.
5. Temperatūros daviklius.
6. Izoliacijos klaidas.

Pastaba:
Tik pagal sumažėjusią ridą negalima nuspręsti, ar reikia keisti visą bateriją. Pirmiausia reikalinga BMS/SOH diagnostika."""
