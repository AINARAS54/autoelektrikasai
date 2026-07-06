def answer_service(base_dir, text: str, ctx: dict):
    t = (text or "").lower()
    if "serviso interval" in t or "aptarnavimo interval" in t:
        return """📘 <b>Serviso intervalo klausimas</b>

Parašykite automobilio markę, modelį, metus ir kokį intervalą norite atstatyti:
• alyvos;
• stabdžių skysčio;
• apžiūros;
• filtrų;
• techninės priežiūros."""
    return None
