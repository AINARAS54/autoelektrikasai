AutoElektrikas AI V18 Architecture

Įkelti į GitHub projekto šaknį:
app.py
context_engine.py
vehicle_engine.py
intent_engine.py
obd_engine.py
procedure_engine.py
response_formatter.py
ev_engine.py
price_engine.py
service_engine.py
vision_engine.py

V18 principas:
app.py yra tik routeris.
Visa logika perkelta į atskirus modulius.

Prioritetų tvarka:
1. Nuotrauka
2. Start / New case / Clear
3. VIN
4. OBD
5. Kaina
6. Procedūra
7. Service
8. EV
9. Vehicle-only
10. AI fallback
