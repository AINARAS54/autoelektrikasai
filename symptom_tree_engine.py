import json
import re
from pathlib import Path
from decision_tree_engine import render_node, keyboard_for_node
from decision_session import save_decision_session
from vehicle_profile_engine import get_vehicle_profile

def normalize_text(text: str) -> str:
    value = (text or "").lower()
    for source, target in {"ą":"a","č":"c","ę":"e","ė":"e","į":"i","š":"s","ų":"u","ū":"u","ž":"z"}.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9\s/+-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()

ALIASES = {
    "no_start_cranks.json": ["starteris suka bet neuzsiveda","starteris suka bet nesikuria","suka bet neuzsiveda","suka bet nesikuria"],
    "no_crank.json": ["starteris nesuka","starteris visai nesuka","paspaudus start nieko","neprasuka variklio"],
    "starts_then_stalls.json": ["uzsiveda ir uzgesta","uzsiveda ir iskart uzgesta","pasileidzia ir uzgesta"],
    "alternator_not_charging.json": ["nekrauna generatorius","generatorius nekrauna","akumuliatoriaus lempute","nera krovimo"],
    "abs_warning.json": ["dega abs","abs lempute","dega esp","esp lempute","abs neveikia"],
    "hv_not_ready.json": ["neisijungia ready","neijungia ready","ready rezimas neisijungia","elektromobilis neisijungia","hibridas neisijungia"],
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
    best, best_score = None, 0
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
            best, best_score = filename, score
    return best if best_score >= 10 else None

def select_symptom_filename(base_dir: Path, text: str, ctx: dict):
    profile = get_vehicle_profile(base_dir, ctx)
    generic = _best_generic_filename(text)
    if profile.get("platform") == "EV" and generic in {
        "no_start_cranks.json","no_crank.json","starts_then_stalls.json","alternator_not_charging.json"
    }:
        return "hv_not_ready.json"
    return generic

def find_symptom_tree(base_dir: Path, text: str, ctx: dict):
    root = Path(base_dir) / "symptom_trees"
    filename = select_symptom_filename(base_dir, text, ctx)
    if not root.exists() or not filename:
        return None, None
    path = root / filename
    if not path.exists():
        return None, None
    tree = _load_tree(path)
    return (tree, path) if tree else (None, None)

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
        "tree_type": "symptom",
    }
    save_decision_session(base_dir, chat_id, session)
    return render_node(tree, start_node, session), keyboard_for_node(tree, start_node)
