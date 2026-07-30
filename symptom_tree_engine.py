import json
import re
from pathlib import Path

from decision_tree_engine import render_node, keyboard_for_node
from decision_session import save_decision_session
from vehicle_profile_engine import get_vehicle_profile
from vehicle_logic_engine import symptom_redirect
from manufacturer_diagnostic_engine import select_manufacturer_tree


def normalize_text(text: str) -> str:
    value = (text or "").lower()
    for source, target in {
        "ą": "a", "č": "c", "ę": "e", "ė": "e", "į": "i",
        "š": "s", "ų": "u", "ū": "u", "ž": "z",
    }.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9\s/+-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


ALIASES = {
    "no_start_cranks.json": [
        "starteris suka bet neuzsiveda",
        "starteris suka bet nesikuria",
        "suka bet neuzsiveda",
        "suka bet nesikuria",
    ],
    "no_crank.json": [
        "starteris nesuka",
        "starteris visai nesuka",
        "paspaudus start nieko",
        "neprasuka variklio",
    ],
    "starts_then_stalls.json": [
        "uzsiveda ir uzgesta",
        "uzsiveda ir iskart uzgesta",
        "pasileidzia ir uzgesta",
    ],
    "alternator_not_charging.json": [
        "nekrauna generatorius",
        "generatorius nekrauna",
        "akumuliatoriaus lempute",
        "nera krovimo",
    ],
    "abs_warning.json": [
        "dega abs",
        "abs lempute",
        "dega esp",
        "esp lempute",
        "abs neveikia",
    ],
    "hv_not_ready.json": [
        "neisijungia ready",
        "neijungia ready",
        "ready rezimas neisijungia",
        "elektromobilis neisijungia",
        "hibridas neisijungia",
    ],
}


def _load_tree(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["_source_file"] = str(path)
            return data
    except Exception:
        return None
    return None


def _best_generic_filename(text: str):
    normalized = normalize_text(text)
    words = set(normalized.split())
    best_filename = None
    best_score = 0

    for filename, aliases in ALIASES.items():
        score = 0
        for alias in aliases:
            alias_n = normalize_text(alias)
            if alias_n in normalized:
                score += 100
            else:
                overlap = len(set(alias_n.split()) & words)
                if overlap >= 2:
                    score += overlap * 5

        if score > best_score:
            best_filename = filename
            best_score = score

    return best_filename if best_score >= 10 else None


def find_symptom_tree(base_dir: Path, text: str, ctx: dict):
    # 1. Gamintojo diagnostika turi aukščiausią prioritetą.
    tree, path = select_manufacturer_tree(base_dir, text, ctx)
    if tree and path:
        return tree, path

    # 2. Modelio specifinis medis.
    root = Path(base_dir) / "symptom_trees"
    model_tree = symptom_redirect(base_dir, text, ctx)

    if model_tree:
        model_path = root / model_tree
        if model_path.exists():
            tree = _load_tree(model_path)
            if tree:
                return tree, model_path

    # 3. Bendras platformos medis.
    profile = get_vehicle_profile(base_dir, ctx)
    generic = _best_generic_filename(text)

    if profile.get("platform") == "EV" and generic in {
        "no_start_cranks.json",
        "no_crank.json",
        "starts_then_stalls.json",
        "alternator_not_charging.json",
    }:
        generic = "hv_not_ready.json"

    if not generic:
        return None, None

    generic_path = root / generic
    if not generic_path.exists():
        return None, None

    tree = _load_tree(generic_path)
    return (tree, generic_path) if tree else (None, None)


def should_offer_symptom_tree(base_dir: Path, text: str, ctx: dict) -> bool:
    tree, _ = find_symptom_tree(base_dir, text, ctx)
    return tree is not None


def start_symptom_tree(base_dir: Path, chat_id: str, text: str, ctx: dict):
    tree, path = find_symptom_tree(base_dir, text, ctx)
    if not tree or not path:
        return None, None

    profile = get_vehicle_profile(base_dir, ctx)
    start_node = tree.get("start", "start")

    session = {
        "tree_id": tree.get("id"),
        "tree_title": tree.get("title"),
        "source_file": str(path),
        "current_node": start_node,
        "answers": [],
        "ctx_vehicle": ctx.get("vehicle", {}),
        "vehicle_profile": profile,
        "tree_type": "manufacturer_or_symptom",
    }

    save_decision_session(base_dir, chat_id, session)

    return render_node(tree, start_node, session), keyboard_for_node(tree, start_node)
