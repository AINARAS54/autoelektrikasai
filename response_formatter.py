import re


def remove_urls(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"\([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^)]*\)", "", text)
    return text


def remove_markdown(text: str) -> str:
    text = text or ""

    # Headings
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)

    # Bold / italic markdown
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
    text = text.replace("`", "")

    # Markdown bullets normalized
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    return text


def compact_paragraphs(text: str) -> str:
    text = text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove trailing spaces
    lines = [line.strip() for line in text.split("\n")]

    cleaned = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False

    text = "\n".join(cleaned).strip()

    # Max two newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def clean_telegram_text(text: str) -> str:
    """
    Bendras atsakymo valymas Telegram'ui:
    - pašalina URL;
    - pašalina markdown likučius;
    - sutvarko tarpus;
    - pakeičia blogą terminiją.
    """
    text = text or ""

    text = remove_urls(text)
    text = remove_markdown(text)

    replacements = {
        "nulaužimui": "atstatymui",
        "nulaužimas": "atstatymas",
        "nulaužimą": "atstatymą",
        "nulaužti": "atstatyti",
        "nulažti": "atstatyti",
        "nulažimas": "atstatymas",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    text = compact_paragraphs(text)

    return text


def format_bms_adaptation_answer(vehicle_label: str | None = None) -> str:
    vehicle = vehicle_label or "Automobilis"

    return f"""📘 <b>BMS talpos adaptacija</b>

Automobilis:
{vehicle}

BMS talpos adaptacija reikalinga tada, kai keičiamas 12 V akumuliatorius arba jo tipas / talpa. Sistema turi žinoti naujo akumuliatoriaus parametrus, kad tinkamai valdytų įkrovimą.

🔧 Atlikimo tvarka:
1. Įdėkite tinkamos talpos ir tipo akumuliatorių.
2. Patikrinkite, ar gnybtai ir masės jungtys prijungtos teisingai.
3. Prijunkite diagnostikos įrangą.
4. Pasirinkite akumuliatoriaus registravimo / BMS adaptacijos funkciją.
5. Įveskite naujo akumuliatoriaus parametrus, jei to prašo įranga.
6. Užbaikite procedūrą ir patikrinkite, ar nėra aktyvių klaidų.

⚠️ Pastaba:
BMW automobiliuose ši procedūra dažniausiai atliekama naudojant ISTA arba kitą suderinamą diagnostikos įrangą.

Jei kalbate apie aukštos įtampos bateriją, o ne 12 V akumuliatorių, procedūra yra kitokia ir reikia BMS/SOH diagnostikos."""
