# Routine Quest — Firmware (ESP32-S3)

ESP-IDF **v5.3.x**, target **esp32s3** (ESP32-S3-WROOM-1-N8). Prototype board: ESP32-S3-DevKitC-1.

## Αρχιτεκτονική

```
                ┌────────────────────────── app_main (owner του quest engine) ──────────────────────────┐
 GPIO 4-7 ──► buttons ──btn_evt──►│ qe_press / qe_long_press / qe_tick (1 Hz)  ──► feedback (LEDs+ήχος) │
 (5 ms poll,   (debounce 30 ms,   │                     │                                              │
  active-low)   long 2 s, reset)  │                     └──► storage: event ring (NVS, 512) + progress │
                                  │ ◄──cloud_config_t── cloud ◄── GET /v1/device/config (60 s, ETag)    │
                                  └──────────────────────┘    └──► POST /v1/device/events (on event/15 s)
 net: Wi-Fi STA · BLE provisioning (Security 1 + PoP) · "rq-claim" endpoint · SNTP
 ota: HTTPS OTA, A/B slots, rollback μέχρι το πρώτο επιτυχές backend round-trip
```

| Module | Αρχείο | Ευθύνη |
|---|---|---|
| Quest engine | `quest_engine.{h,c}` | Pure C state machine (docs/02 §3). Χωρίς εξαρτήσεις ESP-IDF, με host tests |
| Buttons | `buttons.{h,c}` | Polling 5 ms, debounce, press-down event (<100 ms feedback), long-press undo, combo reset 1+4 |
| Feedback | `feedback.{h,c}` | WS2812 chain (12 ring + 4 κουμπιά) στα 30 fps, LEDC buzzer, scenes D1–D7 του Figma |
| Storage | `storage.{h,c}` | NVS: token, schedule, progress, settings, offline event ring με UUIDv4 idempotency keys |
| Net | `net.{h,c}` | Wi-Fi, BLE provisioning, claim endpoint, SNTP, timezone, reconnect με backoff |
| Cloud | `cloud.{h,c}` | Claim → device token, batch upload events, config polling, χειρισμός 401 (revoke) |
| OTA | `ota.{h,c}` | `esp_https_ota`, μόνο HTTPS, mark-valid μετά από επιτυχές round-trip |

Η πηγή αλήθειας για XP, streak και αστέρια είναι το **backend**. Η συσκευή τρέχει το ίδιο state machine για άμεσο feedback και κάνει reconcile από το config.

### Pin map (προσωρινό, οριστικοποιείται στη Φάση 6)

| Λειτουργία | GPIO |
|---|---|
| Κουμπιά 1–4 (κόκκινο, μπλε, πράσινο, κίτρινο) | 4, 5, 6, 7 (pull-up, active-low) |
| WS2812 data | 38 |
| Buzzer (PWM) | 15 |

Αποφεύγονται τα strapping pins (0, 3, 45, 46), τα USB pins (19, 20), τα pins flash/PSRAM (26–37) και το 48 (on-board LED του DevKitC).

## Build

```bash
. $IDF_PATH/export.sh
idf.py set-target esp32s3
idf.py build                       # production config
idf.py -p /dev/ttyACM0 flash monitor
```

Ρυθμίσεις: `idf.py menuconfig` → **Routine Quest** (`RQ_API_BASE_URL`, `RQ_DEV_POP`, `RQ_SIM_MODE`).

### Host tests (χωρίς hardware)

```bash
make -C test/host     # ASan + UBSan, -Wall -Wextra -Wconversion -Werror
```

## Προσομοίωση στο Wokwi (χωρίς ESP32)

Η build παραλλαγή **simulation** (`sdkconfig.wokwi`, `CONFIG_RQ_SIM_MODE=y`):
- Παρακάμπτει το BLE provisioning, γιατί η Wokwi δεν προσομοιώνει BLE.
- Συνδέεται στο ανοιχτό δίκτυο `Wokwi-GUEST`.
- Φορτώνει demo πρόγραμμα: 00:00–12:00 quest με τα κουμπιά 1–4, 12:00–24:00 quest με τα 4, 2, 1. Έτσι υπάρχει πάντα ενεργό quest.
- Δεν μιλά με backend. Τα events γράφονται στο serial log ως `quest: ...`.

```bash
idf.py -B build-wokwi -D SDKCONFIG=build-wokwi/sdkconfig \
       -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.wokwi" build
```

**VS Code:**
1. Εγκατάσταση extension «Wokwi Simulator» και ενεργοποίηση license (δωρεάν για προσωπική χρήση).
2. Άνοιγμα του φακέλου `firmware/`.
3. `F1` → **Wokwi: Start Simulator**.

Τα κουμπιά πατιούνται με το ποντίκι ή με τα πλήκτρα `1`–`4`. Κράτημα 2 s κάνει undo.

**CLI / CI:**

```bash
wokwi-cli --timeout 120000 --scenario test/wokwi/quest_smoke.test.yaml .
```

Στο GitHub Actions το job `wokwi` τρέχει μόνο αν οριστεί το repo variable `WOKWI_ENABLED=true` και το secret `WOKWI_CLI_TOKEN`.

> ⚠️ Το simulation build **δεν** φλασάρεται ποτέ σε συσκευή που δίνεται σε οικογένεια.

## Γνωστοί περιορισμοί του MVP firmware

- **PoP provisioning:** στα dev boards είναι σταθερό (`RQ_DEV_POP`). Στην παραγωγή γίνεται μοναδικό ανά συσκευή, γραμμένο σε factory NVS partition και τυπωμένο στην ετικέτα (Φάσεις 6/7).
- **Client provisioning στην PWA:** το `wifi_provisioning` χρησιμοποιεί το protocomm (protobuf + Security 1). Η PWA χρειάζεται συμβατό client μέσω Web Bluetooth. Για δοκιμές χρησιμοποιείται η εφαρμογή «ESP BLE Provisioning» της Espressif (Φάση 5).
- **Revoke:** μετά από 401 (token ανακλήθηκε), η επανασύνδεση γίνεται με factory reset (κουμπιά 1+4, 10 s).
- **Config polling:** κάθε 60 s, οπότε οι αλλαγές από τον γονέα φτάνουν στη συσκευή με καθυστέρηση έως 1 λεπτό. Push κανάλι (MQTT/SSE) εξετάζεται στη v2.

## Production security (Φάση 9)

Secure Boot v2 (signed images), flash encryption σε release mode, NVS encryption, απενεργοποιημένο JTAG. Θα μπουν σε ξεχωριστό `sdkconfig.defaults.prod`. Στο dev δεν ενεργοποιούνται, γιατί καίνε eFuses μη αναστρέψιμα.
