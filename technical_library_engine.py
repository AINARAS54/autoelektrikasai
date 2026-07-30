import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIBRARY_VERSION = 1
ALLOWED_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}


def _norm(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _slug(value: Any, fallback: str) -> str:
    text = _norm(value).lower()
    text = re.sub(r'[^a-z0-9]+', '_', text).strip('_')
    return text or fallback


def _vehicle(ctx: dict) -> dict:
    value = ctx.get('vehicle')
    return value if isinstance(value, dict) else {}


def vehicle_library_dir(base_dir: Path, ctx: dict) -> Path:
    vehicle = _vehicle(ctx)
    brand = _slug(vehicle.get('brand'), 'unknown_brand')
    model = _slug(vehicle.get('model'), 'unknown_model')
    year = _slug(vehicle.get('year'), 'unknown_year')
    path = Path(base_dir) / 'technical_library' / brand / model / year
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(base_dir: Path, ctx: dict) -> Path:
    return vehicle_library_dir(base_dir, ctx) / 'index.json'


def _empty_index(ctx: dict) -> dict:
    vehicle = _vehicle(ctx)
    return {
        'version': LIBRARY_VERSION,
        'vehicle': {
            'brand': vehicle.get('brand'),
            'model': vehicle.get('model'),
            'year': vehicle.get('year'),
            'vin': vehicle.get('vin') or ctx.get('vin'),
        },
        'documents': [],
    }


def load_library_index(base_dir: Path, ctx: dict) -> dict:
    path = _index_path(base_dir, ctx)
    if not path.exists():
        return _empty_index(ctx)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else _empty_index(ctx)
    except Exception:
        return _empty_index(ctx)


def save_library_index(base_dir: Path, ctx: dict, data: dict) -> None:
    path = _index_path(base_dir, ctx)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def classify_document(filename: str, vision_result: dict | None = None, forced_type: str | None = None) -> str:
    if forced_type:
        return forced_type
    name = _norm(filename).lower()
    vision_result = vision_result or {}
    document_type = str(vision_result.get('document_type') or '').lower()
    if 'fuse' in name or 'saugikl' in name:
        return 'fuse_diagram'
    if 'wiring' in name or 'electrical' in name or 'elektros' in name:
        return 'wiring_diagram'
    if 'manual' in name or 'vadov' in name:
        return 'manual'
    if document_type == 'registration_document':
        return 'registration_document'
    if document_type == 'obd_scanner':
        return 'obd_report'
    if document_type == 'dashboard':
        return 'dashboard_photo'
    if document_type == 'multimeter':
        return 'measurement_photo'
    return 'technical_document'


def register_file(
    base_dir: Path,
    ctx: dict,
    source_path: str | Path,
    *,
    source_name: str = 'Telegram įkėlimas',
    source_url: str | None = None,
    document_type: str | None = None,
    confidence: str = 'unverified',
    vision_result: dict | None = None,
) -> dict:
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        return {'ok': False, 'error': 'Failas nerastas'}
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return {'ok': False, 'error': 'Nepalaikomas failo formatas'}

    digest = _sha256(source)
    index = load_library_index(base_dir, ctx)
    for item in index.get('documents', []):
        if item.get('sha256') == digest:
            existing = Path(base_dir) / item.get('relative_path', '')
            return {'ok': True, 'duplicate': True, 'item': item, 'path': str(existing)}

    doc_type = classify_document(source.name, vision_result, document_type)
    folder = vehicle_library_dir(base_dir, ctx) / doc_type
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{digest[:12]}_{_slug(source.stem, "document")}{suffix}'
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)

    vehicle = _vehicle(ctx)
    relative_path = str(target.relative_to(Path(base_dir))).replace('\\', '/')
    item = {
        'id': digest[:16],
        'document_type': doc_type,
        'file_name': target.name,
        'relative_path': relative_path,
        'mime_type': mimetypes.guess_type(target.name)[0] or 'application/octet-stream',
        'sha256': digest,
        'source_name': source_name,
        'source_url': source_url,
        'verification': confidence,
        'brand': vehicle.get('brand'),
        'model': vehicle.get('model'),
        'year': vehicle.get('year'),
        'vin': vehicle.get('vin') or ctx.get('vin'),
        'added_at': datetime.now(timezone.utc).isoformat(),
    }
    index.setdefault('documents', []).append(item)
    save_library_index(base_dir, ctx, index)
    return {'ok': True, 'duplicate': False, 'item': item, 'path': str(target)}


def register_resolved_items(base_dir: Path, ctx: dict, items: list[dict]) -> list[dict]:
    stored = []
    for item in items or []:
        path = item.get('path')
        if not path:
            continue
        result = register_file(
            base_dir,
            ctx,
            path,
            source_name=item.get('source_name') or 'Techninis šaltinis',
            source_url=item.get('source_url') or item.get('url'),
            document_type='fuse_diagram',
            confidence=item.get('verification') or 'model_match',
        )
        if result.get('ok'):
            stored.append(result)
    return stored


def list_documents(base_dir: Path, ctx: dict, document_type: str | None = None) -> list[dict]:
    index = load_library_index(base_dir, ctx)
    items = []
    for item in index.get('documents', []):
        if document_type and item.get('document_type') != document_type:
            continue
        path = Path(base_dir) / item.get('relative_path', '')
        if path.exists():
            items.append({**item, 'path': str(path)})
    return sorted(items, key=lambda x: x.get('added_at', ''), reverse=True)


def library_summary(base_dir: Path, ctx: dict) -> str:
    items = list_documents(base_dir, ctx)
    vehicle = _vehicle(ctx)
    label = ' '.join(str(vehicle.get(k) or '') for k in ('brand', 'model', 'year')).strip() or 'Automobilis'
    if not items:
        return (
            f'📚 <b>{label} – techninė biblioteka</b>\n\n'
            'Biblioteka dar tuščia. Įkelti PDF, schemos ir techninės nuotraukos bus automatiškai susietos su aktyvia diagnostikos sesija.'
        )
    names = {
        'fuse_diagram': 'Saugiklių schemos',
        'wiring_diagram': 'Elektros schemos',
        'manual': 'Vadovai',
        'registration_document': 'Automobilio dokumentai',
        'obd_report': 'OBD ataskaitos',
        'dashboard_photo': 'Prietaisų skydelio nuotraukos',
        'measurement_photo': 'Matavimų nuotraukos',
        'technical_document': 'Kiti techniniai dokumentai',
    }
    counts: dict[str, int] = {}
    for item in items:
        key = item.get('document_type') or 'technical_document'
        counts[key] = counts.get(key, 0) + 1
    lines = [f'📚 <b>{label} – techninė biblioteka</b>', f'\nIš viso dokumentų: <b>{len(items)}</b>']
    for key, count in counts.items():
        lines.append(f'• {names.get(key, key)}: {count}')
    lines.append('\nNauji įkelti dokumentai automatiškai papildys šią biblioteką.')
    return '\n'.join(lines)
