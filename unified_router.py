from pathlib import Path
from intent_engine import detect_intent
from decision_tree_router import should_offer_decision_tree
from decision_tree_engine import start_tree
from symptom_tree_engine import should_offer_symptom_tree, start_symptom_tree
from vehicle_profile_engine import get_vehicle_profile, incompatible_reason

def resolve_route(base_dir: Path, chat_id: str, text: str, ctx: dict) -> dict:
    intent = detect_intent(text, ctx)
    profile = get_vehicle_profile(base_dir, ctx)
    incompatibility = incompatible_reason(profile, text)

    if intent == "OBD":
        upper = (text or "").upper()
        if profile.get("platform") == "EV" and any(code in upper for code in ["P030","P035","P020"]):
            return {"route":"PROFILE_WARNING","profile":profile,"message":f"{profile.get('vehicle_label')} yra elektromobilis. Šiam automobiliui uždegimo, ritės ar purkštuko kodai netaikomi. Patikrinkite, ar kodas nuskaitytas iš teisingo automobilio ir modulio."}
        if should_offer_decision_tree(base_dir, text, ctx):
            answer, markup = start_tree(base_dir, chat_id, text, ctx)
            return {"route":"DECISION_TREE","answer":answer,"markup":markup}
        return {"route":"OBD"}

    if intent == "PRICE":
        return {"route":"PRICE"}

    if intent in ["PROCEDURE","PROCEDURE_12V_BATTERY"]:
        if incompatibility:
            return {"route":"PROFILE_WARNING","profile":profile,"message":incompatibility}
        return {"route":"PROCEDURE"}

    if should_offer_symptom_tree(base_dir, text, ctx):
        answer, markup = start_symptom_tree(base_dir, chat_id, text, ctx)
        return {"route":"SYMPTOM_TREE","answer":answer,"markup":markup,"profile_note":incompatibility}

    if incompatibility:
        return {"route":"PROFILE_WARNING","profile":profile,"message":incompatibility}

    if intent == "EV_BATTERY" or ctx.get("topic") == "HV_BATTERY":
        return {"route":"EV"}

    if should_offer_decision_tree(base_dir, text, ctx):
        answer, markup = start_tree(base_dir, chat_id, text, ctx)
        return {"route":"DECISION_TREE","answer":answer,"markup":markup}

    return {"route":"QUESTION","profile":profile}
