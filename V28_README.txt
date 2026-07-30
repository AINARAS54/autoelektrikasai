AutoElektrikas AI V28 – pakeitimai

1. VIN aktyvioje diagnostikoje nebepradeda naujo proceso ir nebeprašo iš naujo aprašyti gedimo.
2. VIN susiejamas su esama sesija, išsaugant gedimo bei diagnostikos kontekstą.
3. „Saugiklių schema“ pirmiausia tikrina vietinę talpyklą, tada automatiškai ieško internete.
4. Rastas PDF arba paveikslėlis siunčiamas tiesiai į Telegram ir išsaugomas fuse_schematics/ kataloge.
5. Šaltinio URL ir atitikimo lygis saugomi data/fuse_schematics_index.json.
6. Saugiklių numeriai nėra spėjami, o modelio/metų schema pažymima kaip galinti skirtis pagal komplektaciją.

Automatinė paieška pirmiausia gali naudoti projekte jau nustatytą OPENAI_API_KEY.
Papildomas paieškos variantas Render aplinkoje:
BING_SEARCH_API_KEY=<jūsų Microsoft Bing Search API raktas>

Pasirinktinai:
BING_SEARCH_ENDPOINT=https://api.bing.microsoft.com/v7.0/search
FUSE_TRUSTED_DOMAINS=bmw.com,bmwgroup.com,bmwtechinfo.bmwgroup.com,fuse-box.info,car-box.info,manualslib.com
FUSE_HTTP_TIMEOUT=18
FUSE_MAX_FILE_BYTES=18874368

Be Bing rakto galima į data/fuse_schematics_index.json -> remote_sources įrašyti tikslius patvirtintus PDF/paveikslėlių arba puslapių URL.
