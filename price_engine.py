from response_formatter import esc
from context_engine import is_contextual_hv_price
from ev_engine import hv_battery_price
from vehicle_engine import vehicle_label


def price_answer(text: str, ctx: dict) -> str:
    t = (text or "").lower()

    if is_contextual_hv_price(text, ctx):
        return hv_battery_price(ctx)

    car = vehicle_label(ctx.get("vehicle") or {})

    if any(x in t for x in ["program", "software", "atnauj"]):
        return f"""💰 <b>Programinės įrangos atnaujinimas</b>

Automobilis:
{esc(car)}

Orientacinė kaina:
• Nepriklausomas servisas: apie 100–300 €
• Oficialus atstovas: apie 200–500 €+

Kaina priklauso nuo to, ar atnaujinamas vienas valdymo blokas, ar visas automobilio modulių paketas.

Prieš atnaujinimą rekomenduojama:
1. Patikrinti 12 V akumuliatoriaus būklę.
2. Užtikrinti stabilų maitinimą programavimo metu.
3. Nuskaityti esamus klaidų kodus."""

    return f"""💰 <b>Apytikslė kaina</b>

Automobilis:
{esc(car)}

Kainai patikslinti reikia žinoti:
1. Kuri detalė ar sistema.
2. Nauja, naudota ar restauruota dalis.
3. Ar reikės programavimo / adaptacijos.
4. Automobilio VIN arba tiksli komplektacija."""
