AutoElektrikas AI V28.1 pataisymas

Pakeisti failai:
1. fuse_schematic_engine.py
2. data/fuse_schematics_index.json

Kas pataisyta:
- BMW i3 schemų paieška nebepriklauso vien nuo AI/Bing paieškos.
- Įtraukti konkretūs BMW i3 techniniai puslapiai.
- Atpažįstami lazy-load paveikslėliai: data-src, data-lazy-src, srcset, data-srcset ir JSON-LD.
- Prioritetas teikiamas failams, kurių pavadinime yra fuse, diagram, box, location ar layout.
- Botas siunčia rastus schemos / saugiklių dėžės vietos paveikslėlius tiesiai į Telegram.

Diegimas:
Nukopijuokite abu failus į projektą, išlaikydami aplankų struktūrą, ir Render atlikite Manual Deploy / Clear build cache & deploy.

Pastaba:
BMW nuo 2019 m. individualią saugiklių paskirstymo kortelę pateikia pagal VIN. Bendro modelio schema gali skirtis pagal komplektaciją, todėl botas ir toliau nerodys išgalvotų saugiklių numerių.
