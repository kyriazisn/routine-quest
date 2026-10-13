# Routine Quest

Παιδικό device (4 φυσικά κουμπιά, ESP32-S3, Wi-Fi) που μετατρέπει τις καθημερινές ρουτίνες σε quests και ειδοποιεί τον γονέα.

## Δομή

| Φάκελος | Περιεχόμενο |
|---|---|
| `docs/` | Product brief, game design, test plan, risks |
| `firmware/` | ESP32-S3 firmware (ESP-IDF) |
| `backend/` | FastAPI + Postgres, device & parent API, Web Push |
| `app/` | Parent PWA |
| `hardware/` | KiCad schematic, BOM, PCB |

## Ροή εργασίας

- Κάθε αλλαγή σε ξεχωριστό branch → PR → review → merge στο `main`.
- Κανένα direct commit στο `main` μετά το initial scaffold.
- Το PCB layout ξεκινά **μόνο** μετά από έγκριση του schematic.

## Φάσεις

1. Product brief & user stories — `docs/01-product-brief.md`
2. Game loop, XP, streaks, rewards — `docs/02-game-design.md`
3. Wireframes (Figma)
4. Firmware
5. Backend & notifications
6. Schematic → (έγκριση) → PCB
7. Test plan
8. Landing page & launch
9. Risks, safety, privacy, parental controls
