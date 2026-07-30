from pathlib import Path

from decision_tree_loader import find_tree, load_tree
from decision_session import load_decision_session, save_decision_session, clear_decision_session
from context_engine import save_completed_diagnostic


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _button(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def yes_no_keyboard():
    return {
        "inline_keyboard": [
            [_button("✅ Taip", "dt:yes"), _button("❌ Ne", "dt:no")]
        ]
    }


def next_keyboard():
    return {
        "inline_keyboard": [
            [_button("➡️ Tęsti", "dt:next")]
        ]
    }


def finish_keyboard():
    return {
        "inline_keyboard": [
            [_button("🆕 Nauja diagnostika", "new_diagnostic")],
            [_button("📂 Ankstesnės diagnostikos", "diagnostic_history")],
        ]
    }


def node_has_yes_no(node: dict) -> bool:
    return bool(node.get("yes") or node.get("no"))


def keyboard_for_node(tree: dict, node_id: str):
    node = (tree.get("nodes") or {}).get(node_id, {})
    node_type = node.get("type", "question")

    # V20.1 pataisymas:
    # jei ACTION mazgas turi klausimą ir yes/no šakas,
    # jis turi rodyti Taip / Ne, o ne tik Tęsti.
    if node_has_yes_no(node):
        return yes_no_keyboard()

    if node_type == "question":
        return yes_no_keyboard()

    if node_type == "action":
        return next_keyboard()

    if node_type == "result":
        return finish_keyboard()

    return None


def render_header(tree: dict) -> str:
    title = tree.get("title", "Diagnostikos medis")
    code = tree.get("code")
    difficulty = tree.get("difficulty")
    tools = tree.get("tools") or []
    priority = tree.get("priority")

    lines = [f"🧭 <b>{esc(title)}</b>"]

    if code:
        lines.append(f"\nOBD / simptomas: {esc(code)}")

    if priority:
        lines.append(f"Prioritetas: {esc(priority)}")

    if difficulty:
        lines.append(f"Sudėtingumas: {esc(difficulty)}")

    if tools:
        lines.append("\nReikalinga:")
        lines += [f"• {esc(x)}" for x in tools[:6]]

    return "\n".join(lines)


def render_steps(steps):
    if not steps:
        return ""
    return "\n".join([f"{i+1}. {esc(x)}" for i, x in enumerate(steps)])


def render_node(tree: dict, node_id: str, session: dict | None = None) -> str:
    nodes = tree.get("nodes") or {}
    node = nodes.get(node_id)

    if not node:
        return "Diagnostikos žingsnis nerastas."

    node_type = node.get("type", "question")
    # Pilna antraštė rodoma tik pirmame diagnostikos žingsnyje.
    is_first_node = not (session or {}).get("answers")
    header = render_header(tree) if is_first_node else ""
    prefix = f"{header}\n\n" if header else ""

    if node_type == "question":
        return f"{prefix}❓ <b>Klausimas</b>\n{esc(node.get('text', ''))}"

    if node_type == "action":
        steps = node.get("steps") or []
        steps_txt = render_steps(steps) if steps else esc(node.get("text", ""))
        question = node.get("question")
        if question:
            return f"{prefix}🔧 <b>Veiksmas</b>\n{steps_txt}\n\n❓ <b>Po veiksmo</b>\n{esc(question)}"
        return f"{prefix}🔧 <b>Veiksmas</b>\n{steps_txt}"

    if node_type == "result":
        probability = node.get("probability")
        probability_txt = f"\n\n🎯 <b>Tikimybė:</b> ~{esc(probability)} %" if probability is not None else ""
        fix = node.get("recommended_fix")
        fix_txt = f"\n\n🔧 <b>Rekomenduojami veiksmai:</b>\n{esc(fix)}" if fix else ""
        notes = node.get("notes") or []
        notes_txt = "\n".join([f"• {esc(x)}" for x in notes]) if notes else ""
        notes_block = f"\n\n<b>Kiti patikrinimai:</b>\n{notes_txt}" if notes_txt else ""
        return f"✅ <b>Rezultatas</b>\n{esc(node.get('text', ''))}{probability_txt}{fix_txt}{notes_block}"

    return f"{prefix}{esc(node.get('text', ''))}"


def start_tree(base_dir: Path, chat_id: str, text: str, ctx: dict):
    tree = find_tree(base_dir, text, ctx)

    if not tree:
        return None, None

    start_node = tree.get("start", "start")

    session = {
        "tree_id": tree.get("id"),
        "tree_title": tree.get("title"),
        "source_file": tree.get("_source_file"),
        "current_node": start_node,
        "answers": [],
        "ctx_vehicle": ctx.get("vehicle", {}),
    }

    save_decision_session(base_dir, chat_id, session)

    return render_node(tree, start_node, session), keyboard_for_node(tree, start_node)


def handle_decision_callback(base_dir: Path, chat_id: str, callback_data: str):
    session = load_decision_session(base_dir, chat_id)

    if not session:
        return "Diagnostikos sesija nerasta arba baigta.", None

    if callback_data == "dt:stop":
        clear_decision_session(base_dir, chat_id)
        return "Diagnostika užbaigta.", finish_keyboard()

    source_file = session.get("source_file")
    if not source_file:
        clear_decision_session(base_dir, chat_id)
        return "Diagnostikos medis neberastas.", None

    tree = load_tree(Path(source_file))
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
        return "Diagnostika užbaigta.", finish_keyboard()

    session["current_node"] = next_node
    save_decision_session(base_dir, chat_id, session)

    next_text = render_node(tree, next_node, session)
    next_kb = keyboard_for_node(tree, next_node)

    result_node = (tree.get("nodes") or {}).get(next_node, {})
    if result_node.get("type") == "result":
        completed_at = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        result_data = {
            "tree_id": tree.get("id"),
            "tree_title": tree.get("title"),
            "node_id": next_node,
            "text": result_node.get("text"),
            "probability": result_node.get("probability"),
            "recommended_fix": result_node.get("recommended_fix"),
            "notes": result_node.get("notes") or [],
            "answers": session.get("answers") or [],
            "vehicle": session.get("ctx_vehicle") or {},
            "completed_at": completed_at,
        }
        save_completed_diagnostic(base_dir, chat_id, result_data)
        clear_decision_session(base_dir, chat_id)

    return next_text, next_kb
