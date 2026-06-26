import re


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_telegram_text(text: str) -> str:
    text = text or ""

    # Remove markdown links and raw URLs
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^)]*\)", "", text)

    # Remove markdown artifacts
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # Terminology fixes
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

    # Clean spaces and paragraphs
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
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
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
