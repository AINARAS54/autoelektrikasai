AutoElektrikas AI V24 – Model Logic

Į GitHub šaknį įkelkite / pakeiskite:
- vehicle_logic_engine.py
- symptom_tree_engine.py
- unified_router.py
- vehicle_logic/ aplanką
- symptom_trees/ aplanke esančius naujus modelio medžius

app.py keisti nereikia, jei naudojate V23 app.py.

Modeliai:
- BMW i3
- Tesla Model 3
- Nissan Leaf
- Volkswagen ID.3
- Hyundai Kona Electric
- Toyota Prius

Svarbiausi testai:
1. Nauja byla → BMW i3 2019
2. starteris suka, bet neužsiveda
   Turi paleisti bmw_i3_ready.json.
3. BMW i3 2019 nekrauna
   Turi paleisti bmw_i3_charging.json.
4. Nauja byla → Toyota Prius 2018
5. neįsijungia READY
   Turi paleisti toyota_prius_ready.json.
