AutoElektrikas AI V25 – Manufacturer Diagnostics

Į GitHub šaknį įkelkite / pakeiskite:
- manufacturer_diagnostic_engine.py
- symptom_tree_engine.py
- vehicle_logic/bmw/i3.json
- manufacturer_diagnostics/ aplanką

app.py ir unified_router.py keisti nereikia, jei naudojate V24/V23 suderinamą versiją.

BMW i3 V25 medžiai:
- manufacturer_diagnostics/bmw/i3/ready_full.json
- manufacturer_diagnostics/bmw/i3/low_voltage_dcdc.json
- manufacturer_diagnostics/bmw/i3/hv_safety.json
- manufacturer_diagnostics/bmw/i3/charging_full.json

Testai:
1. Nauja byla
2. BMW i3 2019
3. READY neįsijungia
4. 12 V akumuliatorius silpnas
5. HVIL klaida
6. BMW i3 nekrauna

Svarbu:
Aukštos įtampos darbai turi būti atliekami tik kvalifikuotai ir pagal gamintojo saugos procedūras.
