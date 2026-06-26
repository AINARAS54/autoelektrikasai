AutoElektrikas AI online_sources V1

Veikiantys moduliai:
- source_manager.py
- nhtsa_vpic.py
- nhtsa_recalls.py
- obd_database.py
- procedure_library.py
- openai_web_search.py
- cache.py

Pirma patvirtinta procedūra:
- BMW i3 Brake Fluid service interval reset

Naudojimas app.py:
from online_sources.source_manager import answer_from_sources

result = answer_from_sources(text, vehicle)
if result.get("ok") or result.get("answer"):
    send_message(chat_id, result["answer"], clean_menu())
