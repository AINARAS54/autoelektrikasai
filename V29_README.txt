AUTOELEKTRIKAS AI V29 – SAUGIKLIŲ DOKUMENTŲ MODULIS

Pakeista:
1. Naujas fuse_document_engine.py.
2. Mygtukas „Saugiklių schema“ dabar pirmiausia ieško techninių PDF ir realių numeruotų schemų.
3. Iš PDF ištraukiami tik puslapiai su „fuse assignment / layout / diagram / chart“ požymiais.
4. Atmetamos salono, saugiklių dėžės vietos, logotipų, piktogramų ir pavienių saugiklių nuotraukos.
5. PDF puslapiai paverčiami PNG ir siunčiami tiesiai į Telegram.
6. Patvirtinti rezultatai išsaugomi fuse_schematics kataloge ir indekse.

Pakeisti failai:
- app.py
- requirements.txt
- data/fuse_schematics_index.json
- fuse_document_engine.py (naujas)

Po įkėlimo į GitHub Render pasirinkite „Clear build cache & deploy“, nes pridėtos PyMuPDF ir Pillow bibliotekos.
