import re

def clean_telegram_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^)]*\)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    for bad, good in {
        "nulaužimui": "atstatymui",
        "nulaužimas": "atstatymas",
        "nulaužimą": "atstatymą",
        "nulaužti": "atstatyti",
    }.items():
        text = text.replace(bad, good)
    lines = [x.strip() for x in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out, blank = [], False
    for line in lines:
        if not line:
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(line)
            blank = False
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
