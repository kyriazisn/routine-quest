# Routine Quest — Hardware

Design notes, calculations and the approval checklist: [`docs/06-hardware.md`](../docs/06-hardware.md).

> **Status:** schematic v0.1 approved (2026-10-13). PCB layout (Phase 6b) **in progress, not for ordering** — see [`docs/06b-pcb.md`](../docs/06b-pcb.md).

## Files

| Path | |
|---|---|
| `routine-quest.kicad_pro` / `routine-quest.kicad_sch` | Main board |
| `button-board/button-board.kicad_sch` | Button board (×4) |
| `bom/*.csv` | Bill of materials |
| `build/*.pdf` | Review renders (generated, not committed — see CI artifact) |
| `build/*.netlist.json` | Reviewed netlist, checked against the schematic |
| `tools/gen_schematics.py` | **Source of truth.** Edit this, not the `.kicad_sch` |
| `tools/check_schematic.py` | Independent connectivity + ERC-style checks |
| `tools/render_schematic.py` | PDF/PNG render without KiCad |

## Regenerate & check

```bash
git clone https://github.com/espressif/kicad-libraries.git /tmp/esplib   # pinned SHA in .github/workflows/hardware.yml
pip install kiutils==1.4.8 matplotlib
ESP_KICAD_LIB=/tmp/esplib/symbols/Espressif.kicad_sym python hardware/tools/gen_schematics.py
python hardware/tools/check_schematic.py
python hardware/tools/render_schematic.py
```

Then run KiCad's own ERC (`kicad-cli sch erc`) — see docs/06 §7.

## Licences

The ESP32-S3-WROOM-1 symbol embedded in the schematic comes from
[espressif/kicad-libraries](https://github.com/espressif/kicad-libraries) (CC-BY-SA 4.0 with the KiCad library
exception for designs).
