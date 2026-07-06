from pathlib import Path
from decision_tree_loader import find_tree, load_tree
from decision_session import load_decision_session, save_decision_session, clear_decision_session

def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _button(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}

def yes_no_keyboard():
    return {"inline_keyboard": [[_button("✅ Taip", "dt:yes"), _button("❌ Ne", "dt:no")], [_button("⏹ Baigti diagnostiką", "dt:stop")]]}

def next_keyboard():
    return {"inline_keyboard": [[_button("➡️ Tęsti", "dt:next")], [_button("⏹ Baigti diagnostiką", "dt:stop")]]}

def keyboard_for_node(tree: dict, node_id: str):
    node = (tree.get("nodes") or {}).get(node_id, {})
    node_type = node.get("type", "question")
    if node_type == "question":
        return yes_no_keyboard()
    if node_type == "action":
        return next_keyboard()
    if node_type == "result":
        return {"inline_keyboard": [[_button("✅ Baigti", "dt:stop")]]}
    return None

def render_header(tree: dict) -> str:
    lines = [f"🧭 <b>{esc(tree.get('title', 'Diagnostikos medis'))}</b>"]
    if tree.get("code"):
        lines.append(f"\nOBD / simptomas: {esc(tree.get('code'))}")
    if tree.get("priority"):
        lines.append(f"Prioritetas: {esc(tree.get('priority'))}")
    if tree.get("difficulty"):
        lines.append(f"Sudėtingumas: {esc(tree.get('difficulty'))}")
    tools = tree.get("tools") or []
    if tools:
        lines.append("\nReikalinga:")
        lines += [f"• {esc(x)}" for x in tools[:6]]
    return "\n".join(lines)

def render_node(tree: dict, node_id: str, session: dict | None = None) -> str:
    node = (tree.get("nodes") or {}).get(node_id)
    if not node:
        return "Diagnostikos žingsnis nerastas."
    header = render_header(tree)
    node_type = node.get("type", "question")
    if node_type == "question":
        return f"{header}\n\n❓ <b>Klausimas</b>\n{esc(node.get('text', ''))}"
    if node_type == "action":
        steps = node.get("steps") or []
        steps_txt = "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(steps)]) if steps else esc(node.get("text", ""))
        question = node.get("question")
        if question:
            return f"{header}\n\n🔧 <b>Veiksmas</b>\n{steps_txt}\n\n❓ <b>Po veiksmo</b>\n{esc(question)}"
        return f"{header}\n\n🔧 <b>Veiksmas</b>\n{steps_txt}"
    if node_type == "result":
        probability = node.get("probability")
        prob = f"\nTikimybė: apie {probability} %" if probability is not None else ""
        fix = node.get("recommended_fix")
        fix_txt = f"\n\nRekomenduojamas remontas:\n{esc(fix)}" if fix else ""
        notes = node.get("notes") or []
        notes_txt = "\n".join([f"• {esc(x)}" for x in notes])
        notes_block = f"\n\nPastabos:\n{notes_txt}" if notes_txt else ""
        return f"{header}\n\n✅ <b>Išvada</b>\n{esc(node.get('text', ''))}{prob}{fix_txt}{notes_block}"
    return f"{header}\n\n{esc(node.get('text', ''))}"

def start_tree(base_dir: Path, chat_id: str, text: str, ctx: dict):
    tree = find_tree(base_dir, text, ctx)
    if not tree:
        return None, None
    node_id = tree.get("start", "start")
    session = {"tree_id": tree.get("id"), "tree_title": tree.get("title"), "source_file": tree.get("_source_file"), "current_node": node_id, "answers": [], "ctx_vehicle": ctx.get("vehicle", {})}
    save_decision_session(base_dir, chat_id, session)
    return render_node(tree, node_id, session), keyboard_for_node(tree, node_id)

def handle_decision_callback(base_dir: Path, chat_id: str, callback_data: str):
    session = load_decision_session(base_dir, chat_id)
    if not session:
        return "Diagnostikos sesija nerasta arba baigta.", None
    if callback_data == "dt:stop":
        clear_decision_session(base_dir, chat_id)
        return "Diagnostika baigta.", None
    source_file = session.get("source_file")
    tree = load_tree(Path(source_file)) if source_file else None
    if not tree:
        clear_decision_session(base_dir, chat_id)
        return "Diagnostikos medis neberastas.", None
    node_id = session.get("current_node")
    node = (tree.get("nodes") or {}).get(node_id)
    if not node:
        clear_decision_session(base_dir, chat_id)
        return "Diagnostikos žingsnis neberastas.", None
    if callback_data == "dt:yes":
        next_node = node.get("yes")
        session.setdefault("answers", []).append({"node": node_id, "answer": "yes"})
    elif callback_data == "dt:no":
        next_node = node.get("no")
        session.setdefault("answers", []).append({"node": node_id, "answer": "no"})
    elif callback_data == "dt:next":
        next_node = node.get("next")
        session.setdefault("answers", []).append({"node": node_id, "answer": "next"})
    else:
        return "Pasirinkimas neatpažintas.", keyboard_for_node(tree, node_id)
    if not next_node:
        clear_decision_session(base_dir, chat_id)
        return "Diagnostikos medis baigtas.", None
    session["current_node"] = next_node
    save_decision_session(base_dir, chat_id, session)
    text = render_node(tree, next_node, session)
    kb = keyboard_for_node(tree, next_node)
    if (tree.get("nodes") or {}).get(next_node, {}).get("type") == "result":
        clear_decision_session(base_dir, chat_id)
    return text, kb
