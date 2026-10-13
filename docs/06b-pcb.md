# 06b — PCB layout (WIP)

Status: **σε εξέλιξη — ΟΧΙ για παραγγελία.** Ξεκίνησε μετά την έγκριση του schematic (2026-10-13).

## Τι υπάρχει

| Αρχείο | |
|---|---|
| `hardware/tools/gen_pcb.py` | Placement, outline, net classes, κανόνες, GND pours, stitching vias. Παίρνει parts/nets από το `gen_schematics.py` (μία πηγή αλήθειας) |
| `hardware/tools/route_pcb.py` | Autorouting με Freerouting 1.9.0 (μέσω DSN/SES), zone fill, DRC report |
| `hardware/tools/check_pcb.py` | Ανεξάρτητος έλεγχος: nets board == schematic, DRC 0 errors / 0 unconnected, antenna clearance, USB-C στην άκρη |
| `hardware/routine-quest.kicad_pcb` | Main board (placed + autorouted, **ημιτελές**) |
| `hardware/button-board/button-board.kicad_pcb` | Button board (placed + routed, DRC καθαρό) |
| `hardware/lib/` + `fp-lib-table` | Footprint MLT-8530 (νέο) και vendored ESP32-S3-WROOM-1 (Espressif) |
| `hardware/routine-quest.kicad_dru` | Custom DRC rule μόνο για το land pattern του USB-C |

Το schematic **δεν άλλαξε ηλεκτρικά**: μόνο το πεδίο Footprint του BZ1 έγινε `RQ:Buzzer_MLT-8530` (ήταν placeholder).

## Αποφάσεις layout

| Θέμα | Επιλογή | Γιατί |
|---|---|---|
| Main board | **100 × 100 mm**, 2 layers, 1.6 mm (αντί ~130 × 130) | Το ring Ø52 mm χωράει. Κατηγορία ≤100×100 = φθηνότερη στο JLCPCB. Τα 4 κουμπιά μπαίνουν γύρω από τη main board στο κουτί, χωρίς cut-outs |
| ESP32 | Κεραία στην πάνω άκρη, flush με το outline. Keep-out footprint + επιπλέον 40 × 6.5 mm rule area | Espressif HW design guide |
| USB-C | Αριστερή άκρη, στόμιο προς τα έξω. ESD (U2) αμέσως πίσω | Σύντομα D+/D−, προστασία πριν από οτιδήποτε |
| Ring | 12 LEDs, R = 26 mm, κέντρο (50, 62). LED1 πάνω-δεξιά, δεξιόστροφα, LED12 πάνω | Κοντά στον U5. Σειρά = firmware |
| Μέσα στο ring | U3 load switch, U4 LDO (tab → GND pour + 5 thermal vias) | Χαλκός για τη θερμότητα του U4 (docs/06 §2) |
| Κουμπιά | J2–J5 στις 4 γωνίες, προστασία (TVS → 1k → 10k/10nF) δίπλα σε κάθε connector | Κοντινό harness προς κάθε κουμπί |
| Test pads | TP1–TP10 στην κάτω πλευρά, στήλη δεξιά | Pogo fixture (Phase 7), όλα τα SMD πάνω (μονόπλευρη συναρμολόγηση) |
| GND | Pour και στα δύο layers, via δίπλα σε κάθε GND pad, 4 vias στο EPAD του ESP32 (στα κενά, όχι μέσα στα pads). Ο router δεν δρομολογεί GND | Συμπαγές GND, λιγότερος χώρος για traces |
| Net classes | Power 0.8 mm, +3V3 0.5, Buzzer 0.4, USB 0.3, default 0.25. Clearance 0.2 | Ρεύμα και περιθώριο κατασκευής |
| Button board | 24 × 24 mm, LED στο κέντρο πάνω, J1/J2 (THT) από την κάτω πλευρά, 2× M2 | Επίπεδη πάνω πλευρά για κουμπί/διαχυτή |

## Πού έμεινε (επόμενα βήματα)

Τελευταίο DRC της main board: **8 unconnected, 9 starved thermals** (τα υπόλοιπα είναι μόνο silk warnings και warnings βιβλιοθήκης headless).

1. **USB-C fan-out:** τα διπλά pads A6/B6 (D+), A7/B7 (D−), A4/B9 ↔ B4/A9 (VBUS) δεν ενώνονται από τον router (pitch 0.5 mm). Θα μπει προ-δρομολογημένο fan-out στο `gen_pcb.py` (D+/D− crossing με 2 vias πίσω από τα pads).
2. **GND islands:** μερικά GND pads (U1.1, U3.2, C12, C19, C21, C26, C27, J4, J5) έμειναν σε νησίδα pour. Θα μπει post-route βήμα που προσθέτει stitching via όπου χρειάζεται.
3. `min_resolved_spokes = 1` (το thermal με 1 spoke είναι πραγματική σύνδεση).
4. Καθάρισμα silkscreen (επικαλύψεις refs).
5. `export_fab.py`: Gerbers, drill, CPL, BOM (JLCPCB), renders για review. CI workflow.
6. Review στο KiCad 9 (DRC εκεί) **και έγκριση από τον χρήστη πριν από οποιαδήποτε παραγγελία**.

## Ανοιχτά πριν την παραγγελία

- **MLT-8530 footprint:** land pattern από LCSC C94599 (4 pads 2.4 mm σε ±3.6 mm, pad 1 = +). Το κείμενο του datasheet αναφέρει 3 τερματικά. **Επιβεβαίωση με το σχέδιο του κατασκευαστή.** Coil 16 Ω, rated 95 mA @ 5 Vp-p 50% → η R15 = 47 Ω δίνει ≈ 40 mA μέσο, πιο ήσυχα από το rated. Ρύθμιση στη Phase 7 όπως αποφασίστηκε.
- **Μηχανικά:** επιλογή κουμπιού (30 mm arcade ή μεγαλύτερο dome). Το outline του button board είναι παραμετρικό στο `gen_pcb.py`.
- Ύψος JST PH vertical + βύσμα ≈ 10 mm → standoffs/απόσταση από το καπάκι.

## Πώς τρέχει

```bash
sudo dnf install kicad                       # pcbnew Python (KiCad ≥ 7)
pip install kiutils==1.4.8                   # για το gen_schematics import
python3 hardware/tools/gen_pcb.py            # placement (ξαναγράφει τα .kicad_pcb χωρίς routing)
FREEROUTING_JAR=<path>/freerouting-1.9.0.jar python3 hardware/tools/route_pcb.py
python3 hardware/tools/check_pcb.py
```
