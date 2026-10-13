# 06 — Hardware: Schematic & BOM

Status: **Schematic προς έγκριση.** Σύμφωνα με τον κανόνα του έργου, το **PCB layout (Φάση 6b) δεν ξεκινά** πριν εγκριθεί το schematic.

| Αρχείο | Περιεχόμενο |
|---|---|
| `hardware/routine-quest.kicad_sch` | Main board (KiCad 8 format, ανοίγει σε KiCad 8/9) |
| `hardware/button-board/button-board.kicad_sch` | Button board (×4) |
| `hardware/build/main-board.pdf`, `button-board.pdf` | Render για review χωρίς KiCad |
| `hardware/bom/main-board.csv`, `button-board.csv` | BOM (42 + 6 γραμμές) |
| `hardware/build/*.netlist.json` | Netlist: η πηγή αλήθειας που ελέγχεται |
| `hardware/tools/` | Generator, ανεξάρτητος checker, renderer |

## 1. Αρχιτεκτονική

```
                      ┌──────────────────────────── MAIN BOARD ────────────────────────────┐
 USB-C ─VBUS─► F1 PTC ─► D1 TVS ─► U3 TPS22918 (soft-start) ─► +5V ─┬─► U4 AP7361C ─► +3V3 ─► U1 ESP32-S3
   │ CC1/CC2: 5.1k Rd (sink)                                         ├─► 12× WS2812B ring
   └─ D+/D- ─► U2 USBLC6 (ESD) ─► U1 IO20/IO19 (native USB: flash + console)
                                                                     └─► buzzer driver
 U1 IO38 ─► U5 74AHCT1G125 (3.3→5V) ─► R19 ─► LED1…LED12 ─► J2 ─► J3 ─► J4 ─► J5 ─► TP8
 U1 IO4…IO7 ◄── R(1k) ◄── TVS ◄── J2…J5 SW   (10k pull-up, 10nF)
 U1 IO15 ─► Q1 2N7002 ─► BZ1 MLT-8530 (47Ω από +5V, flyback D6)
                      └──────────────────────────────────────────────────────────────────────┘
 J2…J5 ═ 6-wire JST-PH ═► BUTTON BOARD (×4): WS2812B κάτω από το διάφανο arcade κουμπί + microswitch
```

### Pin map (ίδιο με το `firmware/main/board.h`, χωρίς αλλαγή στο firmware)

| Λειτουργία | GPIO | Pin module |
|---|---|---|
| Κουμπιά 1–4 | IO4, IO5, IO6, IO7 | 4, 5, 6, 7 |
| Buzzer PWM | IO15 | 8 |
| WS2812B data | IO38 | 31 |
| USB D− / D+ | IO19 / IO20 | 13 / 14 |
| UART0 TX / RX (test pads) | IO43 / IO44 | 37 / 36 |
| BOOT / EN | IO0 / EN | 27 / 3 |

Τα strapping pins IO3, IO45 και IO46 μένουν ασύνδετα (default). Τα IO35–37 είναι ελεύθερα στο N8 (χωρίς PSRAM), αλλά δεν χρησιμοποιούνται. Τα 27 αχρησιμοποίητα pins έχουν σήμανση no-connect.

## 2. Αποφάσεις & υπολογισμοί

### Τροφοδοσία

| Θέμα | Επιλογή | Αιτιολόγηση |
|---|---|---|
| Πηγή | USB-C 5V, sink με Rd 5.1k στα CC | Δουλεύει με κάθε USB-C φορτιστή. **Καμία μπαταρία** (ασφάλεια παιδιού, πιστοποίηση) |
| Υπερένταση | F1 PTC 0.75A hold / 1.5A trip | Προστασία σε βραχυκύκλωμα του harness προς τα κουμπιά |
| Υπέρταση / ESD | D1 SMAJ5.0A στο VBUS, U2 USBLC6 στα D+/D− | Hot-plug spikes και ESD από το καλώδιο |
| Inrush | U3 TPS22918 με C2 = 1nF στο CT (slew control) | Το C4+C5 (≈ 70 µF πραγματικά υπό DC bias) υπερβαίνει τα 10 µF που επιτρέπει το USB στη σύνδεση χωρίς έλεγχο. Ο χρόνος ανόδου επαληθεύεται με μέτρηση στη Φάση 7 |
| 3.3V | U4 AP7361C-33E, 1A, SOT-223 | Ceramic-stable, ανοχή στα peaks Wi-Fi |

**Θερμικά του U4:** στη χειρότερη περίπτωση (Wi-Fi TX) η κατανάλωση είναι (5 − 3.3) V × 0.35 A ≈ 0.6 W για λίγα ms. Ο μέσος όρος με modem sleep είναι ≈ 0.08 A → 0.14 W. Με SOT-223 και ≥ 2 cm² χαλκό (θJA ≈ 60–80 °C/W), η μέση άνοδος θερμοκρασίας είναι ≈ 10 °C. Το layout της Φάσης 6b θα δώσει την αναγκαία επιφάνεια χαλκού.

### Ενεργειακός προϋπολογισμός (+5V)

| Κατανάλωση | Τυπικό | Χειρότερο |
|---|---|---|
| ESP32-S3 (μέσω LDO) | 40–80 mA | **≈ 350 mA** (TX peak, ms) |
| 16× WS2812B quiescent | 16 mA | 16 mA |
| 16× WS2812B φως (firmware cap 64/255) | 20–60 mA | 240 mA (όλα λευκά) |
| Buzzer (47 Ω + πηνίο) | 0 | ≈ 80 mA |
| **Σύνολο** | **≈ 100–150 mA** | **≈ 690 mA** |

> ⚠️ **Απαιτείται αλλαγή στο firmware (ξεχωριστό PR, Φάση 7):** ένας περιοριστής ρεύματος LED στο `feedback.c`, που να κρατά το άθροισμα των καναλιών ≤ 100 mA. Μαζί του, η συσκευή μένει ≤ 500 mA (USB 2.0 default) εκτός από στιγμιαία peaks Wi-Fi. Με φορτιστή USB-C (≥ 1.5 A) δεν υπάρχει πρόβλημα. Με θύρα USB 2.0 υπολογιστή, ο περιοριστής είναι απαραίτητος.

### LEDs

- Το WS2812B στα 5V θέλει V<sub>IH</sub> ≥ 0.7·V<sub>DD</sub> = 3.5V. Το ESP32 δίνει 3.3V, οπότε μπαίνει ο U5 **74AHCT1G125** (TTL input, V<sub>IH</sub> = 2V) ως level shifter.
- Το R18 (100k) κρατά το data low όσο το IO38 είναι floating στο boot, ώστε να μην ανάβουν τυχαία LEDs.
- Αντιστάσεις 330 Ω σε σειρά στην αρχή της αλυσίδας και στην είσοδο κάθε button board, για ringing και προστασία καλωδίου.
- 100 nF ανά LED και 10 µF τοπικά σε κάθε button board.
- Αλυσίδα: ring 1→12 → κουμπί 1 → 2 → 3 → 4 → TP8. Ίδια σειρά με το `RQ_BUTTON_LED_BASE` του firmware (LEDs 12–15).

### Κουμπιά

- Το καλώδιο του κουμπιού είναι εξωτερικό και το αγγίζει παιδί, άρα έχει υψηλό κίνδυνο ESD.
- Αλυσίδα προστασίας ανά είσοδο: **TVS (PESD5V0S1BA) στον connector → 1k σε σειρά → 10k pull-up + 10nF**.
- Σταθερά χρόνου RC = 10 µs. Το debounce μένει στο firmware (30 ms).

### Buzzer

- MLT-8530: ηλεκτρομαγνητικός, εξωτερικής οδήγησης, 2.7 kHz, 80 dB.
- Οδήγηση: low-side 2N7002, με 100 Ω στο gate και 100k pull-down (σιωπηλός στο boot), και flyback 1N4148W.
- Το R15 (47 Ω, 1206) περιορίζει το ρεύμα πηνίου σε ≈ 80 mA. Η τιμή του ρυθμίζεται με μέτρηση dB στη Φάση 7. Η αντίσταση πηνίου δεν δίνεται στις πηγές που βρήκα.

### Διάφορα

- **Reset/Boot:** RESET (EN) και BOOT (IO0) είναι μόνο **μέσα** στο κουτί. Το flashing γίνεται μέσω native USB, οπότε τα κουμπιά χρειάζονται μόνο για recovery.
- **EN:** 10k pull-up και 1µF προς GND, σύμφωνα με το Espressif HW design guide.
- **Test pads (pogo, για το factory test της Φάσης 7):** TP1–TP10 για UART, EN, IO0, ράγες τροφοδοσίας, τέλος αλυσίδας LED και USB.

## 3. BOM (σύνοψη)

| Ομάδα | Βασικά εξαρτήματα | MPN |
|---|---|---|
| MCU | ESP32-S3-WROOM-1-N8 | Espressif |
| Τροφοδοσία | USB4105-GF-A · MF-MSMF075-2 · SMAJ5.0A · USBLC6-2SC6 · TPS22918DBVR · AP7361C-33E-13 | GCT · Bourns · — · ST · TI · Diodes |
| LEDs | 74AHCT1G125 · 12+4 × WS2812B | TI · Worldsemi |
| Κουμπιά | 4 × B6B-PH-K-S · 4 × PESD5V0S1BA | JST · Nexperia |
| Ήχος | MLT-8530 · 2N7002 · 1N4148W | Huaneng |
| Main board | 90 εξαρτήματα / 42 γραμμές BOM | `hardware/bom/main-board.csv` |
| Button board ×4 | 6 εξαρτήματα | `hardware/bom/button-board.csv` |

**Πριν την παραγγελία (Φάση 6b):**
- Έλεγχος διαθεσιμότητας και κόστους όλων των MPN (LCSC/Mouser).
- Επιλογή συγκεκριμένων MPN για τα παθητικά.
- Επιλογή arcade κουμπιών 30 mm με διάφανο καπάκι και χώρο για LED.

## 4. Επαλήθευση που έγινε

| Έλεγχος | Αποτέλεσμα |
|---|---|
| Pinout ESP32-S3-WROOM-1 | Από το **επίσημο** σύμβολο Espressif (pinned commit `dd76561`). Pads footprint 1–41 = pins συμβόλου, με antenna keep-out zone |
| Pinout TPS22918 (DBV) | TI datasheet: 1 VIN, 2 GND, 3 ON, 4 CT, 5 QOD, 6 VOUT |
| Pinout AP7361C-33**E** (SOT-223) | Δύο ανεξάρτητες πηγές: 1 IN, 2 GND (tab), 3 OUT. Η παραλλαγή **-33ER** έχει άλλο pinout και σημειώνεται στο BOM |
| MLT-8530 | Electromagnetic, external drive, 2.7 kHz, pin 1 (+) |
| Footprints | 17/18 υπάρχουν στις βιβλιοθήκες KiCad. Το USB4105 είναι νεότερο από το mirror που είχα διαθέσιμο, οπότε ελέγχεται στη Φάση 6b |
| Συνδεσιμότητα | Ανεξάρτητος checker: ξαναχτίζει τα nets από τη γεωμετρία του `.kicad_sch` και τα συγκρίνει με το netlist. **OK** και στα δύο boards (47 + 6 nets) |
| ERC-style κανόνες | Ασύνδετα pins, nets με μία σύνδεση, power χωρίς driver, συγκρούσεις outputs: **0 σφάλματα** |
| Mutation test του checker | Πιάνει λάθος καλωδίωση, κομμένο σήμα, power net χωρίς driver, και pin χωρίς σήμανση no-connect |
| Ντετερμινισμός | Πανομοιότυπη έξοδος σε 3 διαφορετικά hash seeds. Το CI ελέγχει ότι τα committed αρχεία = έξοδος του generator |

## 5. Γνωστοί περιορισμοί

- Το **ERC του ίδιου του KiCad** δεν έχει τρέξει. Δεν ήταν διαθέσιμο στο περιβάλλον όπου παράχθηκε το schematic. Είναι το πρώτο βήμα του review (§7).
- Το schematic είναι «label-style»: κάθε pin έχει net label αντί για σχεδιασμένα καλώδια. Είναι εύκολο να ελεγχθεί αυτόματα, αλλά διαβάζεται λιγότερο φυσικά από ένα χειροποίητο σχέδιο.
- Δεν υπάρχουν ακόμα footprint για τον buzzer και 3D models. Αυτά ανήκουν στη Φάση 6b.

## 6. Αποφάσεις (2026-10-13)

| # | Θέμα | Απόφαση | Επίπτωση |
|---|---|---|---|
| 1 | Ring LEDs | **Πάνω στη main board** (λιγότερα καλώδια) | Η main board είναι περίπου 130 × 130 mm και το ring τοποθετείται γύρω από το κέντρο της στη Φάση 6b. Το schematic δεν αλλάζει |
| 2 | Button boards | **4 μικρά PCB με harness 6 καλωδίων** | Όπως στο schematic (J2–J5 ↔ button-board J1) |
| 3 | Power budget | **Περιοριστής LED ≤ 100 mA στο firmware και σύσταση «φορτιστής USB-C»** | Firmware PR στη Φάση 7. Κείμενο στο εγχειρίδιο / landing page (Φάση 8) |
| 4 | Buzzer | **MLT-8530 με ρύθμιση έντασης μετά από μέτρηση** | Η R15 (47 Ω, 1206) ορίζεται με μέτρηση dB στη Φάση 7. Στο layout μπαίνει footprint 1206 ώστε να αλλάζει εύκολα |

Το schematic **δεν άλλαξε** από αυτές τις αποφάσεις. Μένει η τελική έγκριση μετά το ERC του KiCad (§7).

## 7. Πώς γίνεται το review (Fedora)

```bash
sudo dnf install kicad                     # KiCad 9 στο Fedora 42+
git fetch && git checkout hardware/schematic
kicad hardware/routine-quest.kicad_pro     # άνοιγμα και οπτικός έλεγχος
kicad-cli sch erc --severity-all -o /tmp/erc.rpt hardware/routine-quest.kicad_sch && cat /tmp/erc.rpt
kicad-cli sch erc --severity-all -o /tmp/erc-btn.rpt hardware/button-board/button-board.kicad_sch
```

Αναμενόμενα warnings στο ERC του KiCad: «symbol not in library» για τα `RQ:` και `Espressif:` σύμβολα, που είναι ενσωματωμένα στο αρχείο. Αυτό είναι φυσιολογικό και δεν αποτελεί σφάλμα. Οποιοδήποτε **error** σταματά την έγκριση.
