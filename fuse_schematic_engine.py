"""Fuse schematic resolver.

Resolution order:
1. local/cache index;
2. configured exact manufacturer/technical source URLs;
3. Bing Web Search API (when BING_SEARCH_API_KEY is configured).

Only PDF and image files are downloaded. Every cached item keeps its source URL.
The engine never invents fuse numbers or claims VIN-level compatibility unless the
source metadata explicitly says so.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger("autoelektrikas_ai.fuse_schematic")

MAX_FILE_BYTES = int(os.getenv("FUSE_MAX_FILE_BYTES", str(18 * 1024 * 1024)))
HTTP_TIMEOUT = int(os.getenv("FUSE_HTTP_TIMEOUT", "18"))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_TRUSTED_DOMAINS = [
    "bmw.com", "bmwgroup.com", "bmwtechinfo.bmwgroup.com",
    "fuse-box.info", "car-box.info", "manualslib.com",
]


def esc(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _vehicle(ctx: dict) -> dict:
    return ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}


def _vehicle_key(ctx: dict) -> str:
    vehicle = _vehicle(ctx)
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    raw = "_".join(_norm(x).replace(" ", "_") for x in parts if x)
    return re.sub(r"[^a-z0-9_-]+", "", raw) or "unknown_vehicle"


def _vehicle_label(ctx: dict) -> str:
    vehicle = _vehicle(ctx)
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")]
    return " ".join(str(x) for x in parts if x) or "Automobilis"


def _index_path(base_dir: Path) -> Path:
    path = Path(base_dir) / "data" / "fuse_schematics_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({"vehicles": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_index(base_dir: Path) -> dict:
    try:
        return json.loads(_index_path(base_dir).read_text(encoding="utf-8"))
    except Exception:
        return {"vehicles": {}}


def _save_index(base_dir: Path, data: dict) -> None:
    _index_path(base_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_dir(base_dir: Path, ctx: dict) -> Path:
    path = Path(base_dir) / "fuse_schematics" / _vehicle_key(ctx)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _trusted_domains() -> list[str]:
    configured = [x.strip().lower() for x in os.getenv("FUSE_TRUSTED_DOMAINS", "").split(",") if x.strip()]
    return configured or DEFAULT_TRUSTED_DOMAINS


def _domain_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in _trusted_domains())


def _media_type(path: Path, content_type: str = "") -> str | None:
    suffix = path.suffix.lower()
    ctype = content_type.lower()
    if suffix == ".pdf" or "application/pdf" in ctype:
        return "document"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"} or ctype.startswith("image/"):
        return "photo"
    return None


def _existing_items(base_dir: Path, ctx: dict) -> list[dict]:
    index = _load_index(base_dir)
    vehicle = _vehicle(ctx)
    key = _vehicle_key(ctx)
    candidates = list((index.get("vehicles") or {}).get(key, []))

    # Also allow model-level entry without year as a fallback.
    model_key = re.sub(
        r"[^a-z0-9_-]+", "",
        "_".join(_norm(x).replace(" ", "_") for x in [vehicle.get("brand"), vehicle.get("model")] if x),
    )
    if model_key and model_key != key:
        candidates += list((index.get("vehicles") or {}).get(model_key, []))

    valid = []
    for item in candidates:
        file_value = item.get("file")
        if not file_value:
            continue
        path = Path(base_dir) / file_value
        if path.exists() and _media_type(path):
            valid.append({**item, "path": str(path)})
    return valid


def _configured_urls(base_dir: Path, ctx: dict) -> list[dict]:
    index = _load_index(base_dir)
    key = _vehicle_key(ctx)
    vehicle = _vehicle(ctx)
    model_key = re.sub(
        r"[^a-z0-9_-]+", "",
        "_".join(_norm(x).replace(" ", "_") for x in [vehicle.get("brand"), vehicle.get("model")] if x),
    )
    result = []
    for current_key in [key, model_key]:
        for item in (index.get("remote_sources") or {}).get(current_key, []):
            if isinstance(item, str):
                result.append({"url": item, "source_name": urlparse(item).hostname or "šaltinis"})
            elif isinstance(item, dict) and item.get("url"):
                result.append(item)
    return result


def _query(ctx: dict) -> str:
    vehicle = _vehicle(ctx)
    vin = vehicle.get("vin")
    parts = [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year"), "fuse box diagram PDF"]
    if vin:
        parts.insert(3, vin)
    return " ".join(str(x) for x in parts if x)




def _openai_candidates(ctx: dict) -> list[dict]:
    """Use the existing OpenAI key as a discovery fallback.

    The model only proposes URLs; every URL is still restricted to the trusted
    domain allow-list and downloaded/validated by this module.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        from openai import OpenAI
    except Exception:
        return []
    model = os.getenv("OPENAI_SEARCH_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")).strip()
    prompt = (
        "Find a fuse box diagram, fuse allocation PDF, or clear fuse layout image for: "
        + _query(ctx)
        + ". Prefer official manufacturer technical documentation, then trusted technical manual sites. "
          "Return only a JSON array with at most 8 objects: "
          '[{"url":"https://...","source_name":"..."}]. ' 
          "Use direct PDF/image URLs when available; otherwise use the exact page that contains the file. "
          "Do not invent URLs."
    )
    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=[
                {"role": "system", "content": "You locate automotive technical documents. Return only valid JSON and never fabricate a URL."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        raw = (response.output_text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        result = []
        for item in parsed:
            if isinstance(item, dict) and item.get("url") and _domain_allowed(item["url"]):
                result.append({"url": item["url"], "source_name": item.get("source_name") or urlparse(item["url"]).hostname})
        return result[:8]
    except Exception as exc:
        logger.info("OpenAI fuse source discovery unavailable: %s", exc)
        return []


def _bing_candidates(ctx: dict) -> list[dict]:
    key = os.getenv("BING_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    endpoint = os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search").strip()
    params = {"q": _query(ctx), "count": 10, "responseFilter": "Webpages", "textDecorations": False, "textFormat": "Raw"}
    try:
        r = requests.get(endpoint, headers={"Ocp-Apim-Subscription-Key": key}, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        items = (r.json().get("webPages") or {}).get("value") or []
        return [
            {"url": item.get("url"), "source_name": item.get("name") or urlparse(item.get("url") or "").hostname}
            for item in items if item.get("url") and _domain_allowed(item.get("url"))
        ]
    except Exception as exc:
        logger.warning("Bing fuse search failed: %s", exc)
        return []


def _extract_media_links(page_url: str, html: str) -> list[str]:
    found: list[str] = []
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'(?:href|src)=["\']([^"\']+\.(?:pdf|png|jpe?g|webp)(?:\?[^"\']*)?)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, flags=re.I):
            url = urljoin(page_url, match)
            if _domain_allowed(url) and url not in found:
                found.append(url)
    return found[:12]


def _download_candidate(base_dir: Path, ctx: dict, candidate: dict) -> dict | None:
    url = candidate.get("url")
    if not url or not _domain_allowed(url):
        return None
    headers = {"User-Agent": "AutoElektrikasAI/1.0 (+technical-document-fetcher)"}
    try:
        r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, stream=True, allow_redirects=True)
        r.raise_for_status()
        final_url = r.url
        if not _domain_allowed(final_url):
            return None
        content_type = (r.headers.get("Content-Type") or "").split(";", 1)[0].lower()

        if content_type.startswith("text/html"):
            html = r.content[:2_000_000].decode(r.encoding or "utf-8", errors="ignore")
            for media_url in _extract_media_links(final_url, html):
                nested = _download_candidate(base_dir, ctx, {**candidate, "url": media_url, "page_url": final_url})
                if nested:
                    return nested
            return None

        suffix = Path(urlparse(final_url).path).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            suffix = mimetypes.guess_extension(content_type) or ""
        if suffix == ".jpe":
            suffix = ".jpg"
        if suffix not in ALLOWED_EXTENSIONS:
            return None

        name_hash = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:16]
        target = _cache_dir(base_dir, ctx) / f"schema_{name_hash}{suffix}"
        size = 0
        with target.open("wb") as fh:
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    return None
                fh.write(chunk)
        if size < 1024 or not _media_type(target, content_type):
            target.unlink(missing_ok=True)
            return None

        relative = str(target.relative_to(base_dir)).replace("\\", "/")
        item = {
            "file": relative,
            "type": _media_type(target, content_type),
            "title": candidate.get("source_name") or "Saugiklių schema",
            "source_url": candidate.get("page_url") or final_url,
            "download_url": final_url,
            "match_level": "VIN" if _vehicle(ctx).get("vin") and _vehicle(ctx).get("vin") in final_url.upper() else "model_year",
        }
        index = _load_index(base_dir)
        items = (index.setdefault("vehicles", {})).setdefault(_vehicle_key(ctx), [])
        if not any(x.get("file") == relative for x in items):
            items.append(item)
            _save_index(base_dir, index)
        return {**item, "path": str(target)}
    except Exception as exc:
        logger.info("Fuse candidate unavailable (%s): %s", url, exc)
        return None


def resolve_fuse_schematics(base_dir: Path, ctx: dict) -> dict:
    """Return {'ok': bool, 'items': [...], 'message': str}."""
    existing = _existing_items(base_dir, ctx)
    if existing:
        return {"ok": True, "items": existing, "from_cache": True}

    candidates = _configured_urls(base_dir, ctx) + _openai_candidates(ctx) + _bing_candidates(ctx)
    downloaded = []
    seen = set()
    for candidate in candidates:
        url = candidate.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        item = _download_candidate(base_dir, ctx, candidate)
        if item:
            downloaded.append(item)
        if len(downloaded) >= 3:
            break

    if downloaded:
        return {"ok": True, "items": downloaded, "from_cache": False}

    missing_search = not os.getenv("BING_SEARCH_API_KEY", "").strip() and not os.getenv("OPENAI_API_KEY", "").strip() and not _configured_urls(base_dir, ctx)
    if missing_search:
        message = (
            "🧩 <b>Saugiklių schema nerasta vietinėje bazėje.</b>\n\n"
            "Automatinei paieškai serveryje reikia nustatyti <code>OPENAI_API_KEY</code> arba <code>BING_SEARCH_API_KEY</code> "
            "arba įrašyti tikslius šaltinių URL faile <code>data/fuse_schematics_index.json</code>."
        )
    else:
        message = (
            "🧩 <b>Patvirtintos schemos rasti nepavyko.</b>\n\n"
            "Paieška patikrino leidžiamus techninius šaltinius, tačiau nerado tiesiogiai "
            "atsisiunčiamo PDF ar paveikslėlio šiam modeliui. Saugiklių numeriai nebuvo spėjami."
        )
    return {"ok": False, "items": [], "message": message}


def schematic_caption(ctx: dict, item: dict) -> str:
    match = item.get("match_level")
    if match == "VIN":
        compatibility = "✅ Atitikimas patikrintas pagal VIN šaltinio nuorodoje."
    else:
        compatibility = "⚠️ Schema parinkta pagal modelį ir metus; numeracija gali skirtis pagal komplektaciją."
    return (
        f"🧩 <b>{esc(_vehicle_label(ctx))} – saugiklių schema</b>\n\n"
        f"{compatibility}\n"
        f"Šaltinis: {esc(item.get('title') or urlparse(item.get('source_url') or '').hostname or 'techninis šaltinis')}"
    )
