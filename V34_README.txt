AutoElektrikas AI V34 – diagnostikų istorija

Pakeisti failai:
- app.py
- context_engine.py
- decision_tree_engine.py

Kas sutvarkyta:
1. Diagnostikos rezultatas išsaugomas automatiškai vos pasiekus galutinį sprendimų medžio rezultatą.
2. Išsaugomi automobilio duomenys, VIN (jei kontekste yra), diagnozė, tikimybė, rekomenduojami veiksmai, papildomi patikrinimai ir visa Taip/Ne eiga.
3. Paspaudus „Ankstesnės diagnostikos“ rezultatas matomas iš karto – nereikia prieš tai spausti „Nauja diagnostika“.
4. Paspaudus „Nauja diagnostika“ jau išsaugotas rezultatas nebedubliuojamas.
5. Neužbaigta diagnostika vis dar archyvuojama pradėjus naują sesiją.

Svarbu dėl Render:
Failai šiuo metu saugomi projekto failų sistemoje (cases_archive). Įprastas Render deploy gali juos ištrinti. Ilgalaikiam saugojimui prijunkite Persistent Disk, Supabase arba kitą nuolatinę saugyklą.
