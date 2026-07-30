AutoElektrikas AI V23 – Vehicle Profile First

Į GitHub šaknį įkelkite ir pakeiskite:
- app.py
- unified_router.py
- symptom_tree_engine.py
- vehicle_profile_engine.py
- vehicle_profiles/ aplanką

Palikite jau esančius:
- symptom_trees/
- decision_trees/
- decision_tree_engine.py
- decision_session.py
- decision_tree_loader.py
- decision_tree_router.py
- procedures/
- data/

Testavimo seka:

1. Paspauskite „Nauja byla“.
2. Parašykite:
BMW i3 2019
3. Parašykite:
starteris suka, bet neužsiveda

Tikėtina:
- botas atpažįsta BMW i3 kaip EV;
- paaiškina, kad įprasto starterio nėra;
- paleidžia EV / READY diagnostikos medį;
- nerodo kuro slėgio, kibirkšties ar purkštukų.

Papildomi testai:
- BMW i3 2019, generatorius nekrauna
- BMW i3 2019, P0301
- BMW 320d 2015, starteris suka, bet neužsiveda
