from response_formatter import esc
from vehicle_engine import vehicle_label


def normalize(text: str) -> str:
    return (text or "").lower().strip()


def bmw_i3_brake_fluid_reset() -> str:
    return """📘 <b>BMW i3 stabdžių skysčio serviso intervalo atstatymas</b>

Automobilis:
BMW i3

Žingsniai:
1. Įjunkite degimą nepaspausdami stabdžio pedalo, kad automobilis būtų Accessory / diagnostikos režime.
2. Palaukite, kol prietaisų skydelyje išnyks pradiniai pranešimai.
3. Paspauskite ir laikykite kairėje prietaisų skydelio pusėje esantį odometro / kelionės atstumo mygtuką apie 10 sekundžių, kol atsivers techninės priežiūros meniu.
4. Trumpais paspaudimais pereikite iki punkto Brake Fluid.
5. Kai rodoma Reset possible, paspauskite ir palaikykite mygtuką apie 3 sekundes, kol pasirodys Reset?.
6. Dar kartą paspauskite ir palaikykite mygtuką, kol prasidės atstatymas.
7. Baigus procedūrą, prietaisų skydelyje turi būti rodoma nauja stabdžių skysčio aptarnavimo data arba intervalas.

Pastabos:
• Jei atstatymas nepavyksta arba pranešimas sugrįžta, patikrinkite stabdžių skysčio lygį, lygio daviklį ir DSC/ABS klaidas.
• Jei meniu šios funkcijos nerodo, atlikite atstatymą diagnostikos įranga, pvz. ISTA, Autel, Launch ar Bosch."""


def bms_adaptation(ctx: dict) -> str:
    car = vehicle_label(ctx.get("vehicle") or {}, fallback="Automobilis")
    return f"""📘 <b>BMS talpos adaptacija</b>

Automobilis:
{esc(car)}

BMS talpos adaptacija reikalinga tada, kai keičiamas 12 V akumuliatorius arba jo tipas / talpa. Sistema turi žinoti naujo akumuliatoriaus parametrus, kad tinkamai valdytų įkrovimą.

Atlikimo tvarka:
1. Įdėkite tinkamos talpos ir tipo akumuliatorių.
2. Patikrinkite, ar gnybtai ir masės jungtys prijungtos teisingai.
3. Prijunkite diagnostikos įrangą.
4. Pasirinkite akumuliatoriaus registravimo / BMS adaptacijos funkciją.
5. Įveskite naujo akumuliatoriaus parametrus, jei to prašo įranga.
6. Užbaikite procedūrą ir patikrinkite, ar nėra aktyvių klaidų.

Pastaba:
BMW automobiliuose ši procedūra dažniausiai atliekama naudojant ISTA arba kitą suderinamą diagnostikos įrangą.

Jei kalbate apie aukštos įtampos bateriją, o ne 12 V akumuliatorių, procedūra yra kitokia ir reikia BMS/SOH diagnostikos."""


def answer_procedure(text: str, ctx: dict) -> str | None:
    t = normalize(text)
    vehicle = ctx.get("vehicle") or {}
    brand = normalize(str(vehicle.get("brand") or ""))
    model = normalize(str(vehicle.get("model") or ""))

    has_bmw = "bmw" in t or brand == "bmw"
    has_i3 = "i3" in t or model == "i3"
    has_brake = "stabdziu skys" in t or "stabdžių skys" in t or "brake fluid" in t or ("stabd" in t and "skys" in t)
    has_reset = any(x in t for x in ["reset", "nureset", "nunul", "atstat", "panaikinti", "isjungti", "išjungti"])

    if has_bmw and has_i3 and has_brake and has_reset:
        return bmw_i3_brake_fluid_reset()

    if "bms" in t and any(x in t for x in ["adapt", "kaip", "atlikti", "registr", "reset"]):
        return bms_adaptation(ctx)

    return None
