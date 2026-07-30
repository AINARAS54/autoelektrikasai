AUTOELEKTRIKAS AI V33 – VIN MODULIS

Pakeisti / pridėti failai:
- app.py
- vin_decoder_engine.py

Kas pataisyta:
1. 17 simbolių VIN dabar dekoduojamas per NHTSA vPIC, kai paslauga pasiekiama.
2. Jei internetinis dekoderis nepasiekiamas, naudojamas saugus WMI / modelio metų / patvirtintų platformų fallback.
3. WBY7Z... atpažįstamas kaip BMW i3, todėl neberodoma „Nenurodytas automobilis“.
4. VIN pridedamas prie aktyvios diagnostikos ir neištrina gedimo aprašymo.
5. Jei aktyvios diagnostikos nėra, tik tada prašoma apibūdinti gedimą.
6. Nežinomi komplektacijos, variklio ar įrangos duomenys nėra išgalvojami.
7. Jei naudotojo įvesti metai skiriasi nuo VIN modelio metų, skirtumas parodomas aiškiai.

Diegimas:
- Nukopijuokite abu .py failus į pagrindinį projekto katalogą.
- GitHub patvirtinkite Replace.
- Render atlikite Clear build cache & deploy.
