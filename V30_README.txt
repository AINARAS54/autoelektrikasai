AUTOELEKTRIKAS AI V30 – TECHNINĖ BIBLIOTEKA

PAKEISTI / PRIDĖTI FAILAI
- app.py
- component_info_engine.py
- vision_engine.py
- technical_library_engine.py
- data/technical_library_index_template.json

KAS NAUJO
1. Įkelti PDF ir paveikslėliai automatiškai išsaugomi pagal automobilio markę, modelį ir metus.
2. Failai indeksuojami SHA-256 kontroliniu kodu, todėl dublikatai nekaupiami.
3. VIN, registracijos dokumentai, OBD ataskaitos, skydelio ir matavimų nuotraukos susiejamos su aktyvia diagnostikos sesija.
4. Aktyvios diagnostikos metu nebeklausiama gedimo iš naujo.
5. Rastos saugiklių schemos automatiškai įtraukiamos į techninę biblioteką.
6. Pridėtas mygtukas „📚 Techninė biblioteka“.

KATALOGŲ STRUKTŪRA KURIAMA AUTOMATIŠKAI
technical_library/<markė>/<modelis>/<metai>/<dokumento_tipas>/

SVARBU RENDER
Render laikina failų sistema po naujo deploy gali būti išvalyta. Ilgalaikiam bibliotekos saugojimui prijunkite persistent disk arba išorinę saugyklą (pvz., Supabase Storage / S3). Ši V30 versija veikia lokaliai ir paruošta vėlesniam saugyklos adapteriui.

DIEGIMAS
1. Nukopijuokite visus failus į projekto šaknį, išlaikydami katalogų struktūrą.
2. Patvirtinkite Replace tik esamiems failams.
3. Įkelkite pakeitimus į GitHub.
4. Render atlikite Clear build cache & deploy.
