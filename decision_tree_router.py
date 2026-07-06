from pathlib import Path
from decision_tree_loader import find_tree

def should_offer_decision_tree(base_dir: Path, text: str, ctx: dict) -> bool:
    return find_tree(base_dir, text, ctx) is not None

def decision_tree_available_title(base_dir: Path, text: str, ctx: dict) -> str | None:
    tree = find_tree(base_dir, text, ctx)
    if not tree:
        return None
    return tree.get("title", "Diagnostikos medis")
