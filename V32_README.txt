AUTOELEKTRIKAS AI V32

Pagrindinis pakeitimas:
- bendri component_info/*.json atsakymai nebenaudojami kaip techninių faktų šaltinis;
- komponentų vietos ir procedūros rodomos tik iš vehicle_database katalogo;
- kiekvienas įrašas privalo turėti verification: verified, manufacturer arba vin_specific;
- jei patvirtintų duomenų nėra, botas aiškiai pasako, kad jų nėra, ir nieko neišgalvoja;
- mygtukai rodomi tik toms temoms, kurioms yra patvirtintų duomenų;
- saugiklių schemos mygtukas rodomas tik kai techninėje bibliotekoje jau yra realus fuse_diagram failas.

Duomenų struktūros pavyzdys:
vehicle_database/bmw/i3/2019/component_locations.json

Temos įrašo pavyzdys:
{
  "topics": {
    "fuses": {
      "verification": "manufacturer",
      "source": "BMW gamintojo dokumento pavadinimas",
      "title": "pagrindinių saugiklių vietos",
      "sections": [
        {"heading": "Vieta", "body": "Patvirtintas aprašymas"}
      ]
    }
  }
}
