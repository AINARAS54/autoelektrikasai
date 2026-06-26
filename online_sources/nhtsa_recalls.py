import requests
from .cache import get_cache, set_cache


RECALL_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"


def get_recalls(make: str, model: str, year: str | int, timeout: int = 15) -> dict:
    make = (make or "").strip()
    model = (model or "").strip()
    year = str(year or "").strip()

    if not make or not model or not year:
        return {"ok": False, "error": "Reikia make, model ir year."}

    cache_key = f"recalls_{make}_{model}_{year}".lower()
    cached = get_cache(cache_key, max_age_seconds=60 * 60 * 24 * 7)
    if cached:
        return cached

    try:
        url = RECALL_URL.format(make=make, model=model, year=year)
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        result = {
            "ok": True,
            "source": "NHTSA Recalls",
            "make": make,
            "model": model,
            "year": year,
            "count": int(data.get("Count") or 0),
            "results": data.get("results") or [],
        }
        set_cache(cache_key, result)
        return result

    except Exception as exc:
        return {"ok": False, "source": "NHTSA Recalls", "error": str(exc)}


def format_recalls(result: dict) -> str:
    if not result.get("ok"):
        return f"Atšaukimų patikros atlikti nepavyko: {result.get('error', 'nežinoma klaida')}"

    if result.get("count", 0) == 0:
        return "✅ Pagal nurodytus duomenis NHTSA atšaukimų nerasta."

    lines = [f"⚠️ <b>Rasti atšaukimai: {result.get('count')}</b>"]
    for item in result.get("results", [])[:5]:
        title = item.get("Component") or "Atšaukimas"
        summary = (item.get("Summary") or "").strip()
        lines.append(f"\n• {title}")
        if summary:
            lines.append(summary[:500])
    return "\n".join(lines)
