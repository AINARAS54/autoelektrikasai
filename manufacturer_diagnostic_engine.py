import json
from pathlib import Path

from vehicle_logic_engine import get_vehicle_logic


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _load_tree(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["_source_file"] = str(path)
            return data
    except Exception:
        return None
    return None


def select_manufacturer_tree(base_dir: Path, text: str, ctx: dict) -> tuple[dict | None, Path | None]:
    logic = get_vehicle_logic(base_dir, ctx)
    if not logic:
        return None, None

    t = _norm(text)
    rules = logic.get("manufacturer_diagnostic_routes", [])

    best_tree = None
    best_score = 0

    for rule in rules:
        score = 0
        for keyword in rule.get("keywords", []):
            keyword_n = _norm(keyword)
            if keyword_n and keyword_n in t:
                score += 10
        if score > best_score:
            best_score = score
            best_tree = rule.get("tree")

    if not best_tree or best_score < 10:
        return None, None

    path = Path(base_dir) / "manufacturer_diagnostics" / best_tree
    if not path.exists():
        return None, None

    tree = _load_tree(path)
    return (tree, path) if tree else (None, None)


def has_manufacturer_tree(base_dir: Path, text: str, ctx: dict) -> bool:
    tree, _ = select_manufacturer_tree(base_dir, text, ctx)
    return tree is not None
