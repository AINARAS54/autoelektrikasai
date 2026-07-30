"""Fuse document resolver for AutoElektrikas AI.

The engine deliberately prefers technical PDF documents and real fuse-layout
images. It rejects cabin/location photos, icons, logos and generic decorative
media. PDF pages containing fuse assignment/layout tables are rendered to PNG
and returned to Telegram as individual schematics.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - handled at runtime
    fitz = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

logger = logging.getLogger("autoelektrikas_ai.fuse_document")

HTTP_TIMEOUT = 30
MAX_FILE_BYTES = 22 * 1024 * 1024
MAX_RESULTS = 4
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_DOMAINS = {
    "bmw.com", "bmwgroup.com", "bmwusa.com", "bmw.co.uk",
    "fuse-box.info", "fubox.net", "fusecheck.com", "car-box.info",
    "manualslib.com", "ownersmanuals2.com", "carmanualsonline.info",
}

# Terms that indicate an actual allocation/layout page.
SCHEMA_TERMS = (
    "fuse assignment", "fuse allocation", "fuse layout", "fuse diagram",
    "fuse chart", "fuse map", "fuse table", "fuse overview",
    "sicherung belegung", "sicherungsbelegung", "sicherungsplan",
    "saugiklių schema", "saugiklių planas", "saugiklių paskirstymas",
)
SCHEMA_WORDS = ("fuse", "fuses", "sicherung", "sicherungen", "saugikl")
LAYOUT_WORDS = ("assignment", "allocation", "layout", "diagram", "chart", "map", "table", "overview", "belegung", "plan", "schema", "paskirst")
REJECT_TERMS = (
    "location", "where is", "dashboard", "interior", "glove box", "passenger footwell",
    "salon", "cabin", "cover", "logo", "icon", "avatar", "banner", "thumbnail",
    "fuse puller", "single fuse", "stock photo",
)


def _esc(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _vehicle(ctx: dict) -> dict:
    return ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}


def _vehicle_label(ctx: dict) -> str:
    v = _vehicle(ctx)
    return " ".join(str(v.get(k) or "").strip() for k in ("brand", "model", "year") if v.get(k)).strip() or "Automobilis"


def _vehicle_key(ctx: dict) -> str:
    raw = _vehicle_label(ctx).lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_") or "unknown"


def _domain_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def _cache_dir(base_dir: Path, ctx: dict) -> Path:
    path = Path(base_dir) / "fuse_schematics" / _vehicle_key(ctx)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(base_dir: Path) -> Path:
    return Path(base_dir) / "data" / "fuse_schematics_index.json"


def _load_index(base_dir: Path) -> dict:
    path = _index_path(base_dir)
    if not path.exists():
        return {"version": 2, "vehicles": {}, "source_pages": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 2, "vehicles": {}, "source_pages": {}}
    except Exception:
        logger.exception("Could not load fuse index")
        return {"version": 2, "vehicles": {}, "source_pages": {}}


def _save_index(base_dir: Path, data: dict) -> None:
    path = _index_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached_items(base_dir: Path, ctx: dict) -> list[dict]:
    data = _load_index(base_dir)
    result: list[dict] = []
    for item in (data.get("vehicles") or {}).get(_vehicle_key(ctx), []):
        file_name = item.get("file")
        if not file_name:
            continue
        path = Path(base_dir) / file_name
        if path.exists() and path.stat().st_size > 1024 and item.get("kind") == "schema":
            result.append({**item, "path": str(path)})
    return result[:MAX_RESULTS]


def _source_pages(base_dir: Path, ctx: dict) -> list[dict]:
    data = _load_index(base_dir)
    configured = list((data.get("source_pages") or {}).get(_vehicle_key(ctx), []))
    v = _vehicle(ctx)
    brand = _norm(v.get("brand"))
    model = _norm(v.get("model")).replace(" ", "")
    if brand == "bmw" and model == "i3":
        configured.extend([
            {"url": "https://fusecard.bmw.com/", "source_name": "BMW Fuse Card", "requires_vin": True},
            {"url": "https://fuse-box.info/bmw/bmw-i3-2014-2019-fuses-and-relay", "source_name": "Fuse-box.info"},
            {"url": "https://fubox.net/bmw/i3-2013-2022/", "source_name": "FuBox"},
        ])
    seen, result = set(), []
    for item in configured:
        url = item.get("url") if isinstance(item, dict) else str(item)
        if url and url not in seen and _domain_allowed(url):
            seen.add(url)
            result.append(item if isinstance(item, dict) else {"url": url})
    return result


def _search_query(ctx: dict) -> str:
    vin = str(_vehicle(ctx).get("vin") or ctx.get("vin") or "").strip()
    return f'{_vehicle_label(ctx)} {vin} "fuse assignment" OR "fuse layout" filetype:pdf'.strip()


def _openai_candidates(ctx: dict) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return []
    model = os.getenv("OPENAI_SEARCH_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    prompt = (
        f"Find technical fuse assignment/layout documents for {_vehicle_label(ctx)}. "
        "Prioritize official manufacturer PDFs, owner's manuals, workshop documents, or pages containing a real numbered fuse layout/table. "
        "Reject cabin location photos, icons, logos, generic fuse photos and pages that only explain where the box is. "
        "Return only a JSON array of objects with url and source_name. Never invent URLs."
    )
    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=[{"role": "system", "content": "Return valid JSON only."}, {"role": "user", "content": prompt}],
            temperature=0.0,
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (response.output_text or "").strip(), flags=re.I | re.S)
        parsed = json.loads(raw)
        return [x for x in parsed if isinstance(x, dict) and x.get("url") and _domain_allowed(x["url"])][:10]
    except Exception as exc:
        logger.info("OpenAI document discovery unavailable: %s", exc)
        return []


def _bing_candidates(ctx: dict) -> list[dict]:
    key = os.getenv("BING_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    endpoint = os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")
    try:
        response = requests.get(
            endpoint,
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"q": _search_query(ctx), "count": 10, "responseFilter": "Webpages", "textFormat": "Raw"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        values = ((response.json().get("webPages") or {}).get("value") or [])
        return [{"url": x.get("url"), "source_name": x.get("name")} for x in values if x.get("url") and _domain_allowed(x["url"])]
    except Exception as exc:
        logger.warning("Bing document search failed: %s", exc)
        return []


def _context_score(text: str) -> int:
    value = _norm(text)
    score = 0
    if any(term in value for term in SCHEMA_TERMS):
        score += 12
    if any(word in value for word in SCHEMA_WORDS):
        score += 4
    if any(word in value for word in LAYOUT_WORDS):
        score += 5
    if re.search(r"\bf\s?\d{1,4}\b", value):
        score += 5
    if any(term in value for term in REJECT_TERMS):
        score -= 12
    return score


def _extract_links(page_url: str, html: str) -> list[dict]:
    """Extract PDFs and only high-confidence schematic images from HTML."""
    results: list[dict] = []
    # Capture a limited window around each href/src so alt text and nearby headings
    # contribute to the decision, unlike URL-only filtering.
    pattern = re.compile(r"(?:href|src|data-src|data-lazy-src|data-original)\s*=\s*['\"]([^'\"]+)['\"]", re.I)
    for match in pattern.finditer(html):
        raw = match.group(1).strip().replace("&amp;", "&")
        url = urljoin(page_url, raw)
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            continue
        around = html[max(0, match.start() - 500): min(len(html), match.end() + 500)]
        plain = re.sub(r"<[^>]+>", " ", around)
        score = _context_score(url + " " + plain)
        if suffix == ".pdf":
            score += 10
        # Images require strong evidence. This blocks cabin photos and icons.
        threshold = 3 if suffix == ".pdf" else 8
        if score >= threshold:
            results.append({"url": url, "score": score})
    results.sort(key=lambda x: x["score"], reverse=True)
    seen, unique = set(), []
    for item in results:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique[:20]


def _download(url: str, target: Path) -> tuple[str, str] | None:
    headers = {"User-Agent": "Mozilla/5.0 AutoElektrikasAI/29"}
    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, stream=True, allow_redirects=True)
        response.raise_for_status()
        if not _domain_allowed(response.url):
            return None
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        suffix = Path(urlparse(response.url).path).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            suffix = mimetypes.guess_extension(content_type) or ""
        if suffix == ".jpe":
            suffix = ".jpg"
        if suffix not in ALLOWED_SUFFIXES:
            return None
        target = target.with_suffix(suffix)
        size = 0
        with target.open("wb") as fh:
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    fh.close(); target.unlink(missing_ok=True)
                    return None
                fh.write(chunk)
        if size < 1500:
            target.unlink(missing_ok=True)
            return None
        return str(target), content_type
    except Exception as exc:
        logger.info("Download failed %s: %s", url, exc)
        return None


def _pdf_page_score(text: str) -> int:
    value = _norm(text)
    score = _context_score(value)
    # Allocation pages normally contain many fuse references and amp values.
    score += min(12, len(re.findall(r"\bf\s?\d{1,4}\b", value)))
    score += min(8, len(re.findall(r"\b(?:5|7\.5|10|15|20|25|30|40|50|60|80|100)a\b", value)))
    return score


def _render_pdf_pages(pdf_path: Path, output_dir: Path, source: dict) -> list[dict]:
    if fitz is None:
        logger.warning("PyMuPDF not installed; PDF page extraction skipped")
        return []
    items: list[dict] = []
    try:
        doc = fitz.open(pdf_path)
        scored: list[tuple[int, int]] = []
        for page_no in range(len(doc)):
            text = doc[page_no].get_text("text") or ""
            score = _pdf_page_score(text)
            if score >= 8:
                scored.append((score, page_no))
        scored.sort(reverse=True)
        for score, page_no in scored[:MAX_RESULTS]:
            page = doc[page_no]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            target = output_dir / f"pdf_{hashlib.sha256((str(pdf_path)+str(page_no)).encode()).hexdigest()[:14]}_p{page_no+1}.png"
            pix.save(target)
            items.append({
                "path": str(target), "type": "photo", "kind": "schema",
                "title": source.get("source_name") or "Techninis PDF",
                "source_url": source.get("page_url") or source.get("url"),
                "page": page_no + 1, "score": score, "match_level": "model_year",
            })
        doc.close()
    except Exception as exc:
        logger.info("PDF analysis failed %s: %s", pdf_path, exc)
    return items


def _image_is_schema(path: Path, context: str) -> bool:
    # URL/context must already be strong. Basic dimensions reject icons and tiny assets.
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
        if width < 650 or height < 450 or width * height < 450_000:
            return False
        ratio = width / max(height, 1)
        if ratio > 4.5 or ratio < 0.2:
            return False
    except Exception:
        return False
    return _context_score(context) >= 8


def _persist_items(base_dir: Path, ctx: dict, items: list[dict]) -> None:
    if not items:
        return
    index = _load_index(base_dir)
    bucket = (index.setdefault("vehicles", {})).setdefault(_vehicle_key(ctx), [])
    existing = {x.get("file") for x in bucket}
    for item in items:
        path = Path(item["path"])
        relative = str(path.relative_to(base_dir)).replace("\\", "/")
        record = {k: v for k, v in item.items() if k != "path"}
        record["file"] = relative
        if relative not in existing:
            bucket.append(record); existing.add(relative)
    _save_index(base_dir, index)


def _process_candidate(base_dir: Path, ctx: dict, source: dict) -> list[dict]:
    url = source.get("url")
    if not url or not _domain_allowed(url):
        return []
    headers = {"User-Agent": "Mozilla/5.0 AutoElektrikasAI/29"}
    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        final_url = response.url
        if not _domain_allowed(final_url):
            return []
        content_type = (response.headers.get("Content-Type") or "").lower()
        output_dir = _cache_dir(base_dir, ctx)

        if "text/html" in content_type:
            html = response.content[:3_000_000].decode(response.encoding or "utf-8", errors="ignore")
            all_items: list[dict] = []
            for link in _extract_links(final_url, html):
                nested_source = {**source, "url": link["url"], "page_url": final_url, "context_score": link["score"]}
                all_items.extend(_process_candidate(base_dir, ctx, nested_source))
                if len(all_items) >= MAX_RESULTS:
                    break
            return all_items[:MAX_RESULTS]

        digest = hashlib.sha256(final_url.encode()).hexdigest()[:16]
        downloaded = _download(final_url, output_dir / f"document_{digest}")
        if not downloaded:
            return []
        file_name, _ = downloaded
        path = Path(file_name)
        if path.suffix.lower() == ".pdf":
            return _render_pdf_pages(path, output_dir, source)

        context = f"{final_url} {source.get('source_name','')} {source.get('context_score','')}"
        if not _image_is_schema(path, context):
            path.unlink(missing_ok=True)
            return []
        return [{
            "path": str(path), "type": "photo", "kind": "schema",
            "title": source.get("source_name") or urlparse(final_url).hostname,
            "source_url": source.get("page_url") or final_url,
            "match_level": "model_year", "score": int(source.get("context_score") or 8),
        }]
    except Exception as exc:
        logger.info("Candidate processing failed %s: %s", url, exc)
        return []


def resolve_fuse_documents(base_dir: Path, ctx: dict) -> dict:
    cached = _cached_items(base_dir, ctx)
    if cached:
        return {"ok": True, "items": cached, "from_cache": True}

    candidates = _source_pages(base_dir, ctx) + _openai_candidates(ctx) + _bing_candidates(ctx)
    results: list[dict] = []
    seen = set()
    for source in candidates:
        url = source.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        for item in _process_candidate(base_dir, ctx, source):
            signature = (item.get("path"), item.get("page"))
            if signature not in {(x.get("path"), x.get("page")) for x in results}:
                results.append(item)
        if len(results) >= MAX_RESULTS:
            break

    results.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    results = results[:MAX_RESULTS]
    _persist_items(base_dir, ctx, results)
    if results:
        return {"ok": True, "items": results, "from_cache": False}

    return {
        "ok": False,
        "items": [],
        "message": (
            "🧩 Šio automobilio saugiklių schema šiuo metu neprieinama."
        ),
    }


def fuse_document_caption(ctx: dict, item: dict) -> str:
    page = f" · PDF psl. {item.get('page')}" if item.get("page") else ""
    return (
        f"🧩 <b>{_esc(_vehicle_label(ctx))} – saugiklių schema</b>\n\n"
        "⚠️ Schema parinkta pagal modelį ir metus; numeracija gali skirtis pagal komplektaciją.\n"
        f"Šaltinis: {_esc(item.get('title') or 'techninis dokumentas')}{page}"
    )
