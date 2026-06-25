AutoElektrikas AI moduliai V1

Failai:
- vehicle_parser.py
- diagnostic_context.py
- openai_diagnostic.py
- app_patch.txt

Ką daro:
1. vehicle_parser.py
   Atpažįsta markę, modelį, metus, EV/hibridą, OBD kodą.

2. diagnostic_context.py
   Surenka kontekstą OpenAI analizei:
   automobilis, gedimas, matavimai, sesijos istorija, vietinės bazės atsakymas.

3. openai_diagnostic.py
   OpenAI sluoksnis:
   vietinė bazė + vartotojo tekstas + sesijos istorija → profesionali diagnostinė analizė.

4. app_patch.txt
   Parodo, ką įdėti į app.py.

Render Environment:
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini

requirements.txt:
openai
