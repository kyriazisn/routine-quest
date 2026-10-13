# 05 — Backend: Schema, API, Notifications

Status: **Draft — προς έγκριση**

Stack: **FastAPI · PostgreSQL 16 · SQLAlchemy 2 · Alembic · Web Push (VAPID)**. Κώδικας στο `backend/`.

## 1. Αρχιτεκτονική

```
 ESP32 ──HTTPS (device token)──►  /v1/device/*  ─┐
                                                 ├─► FastAPI ──► PostgreSQL
 PWA ───HTTPS (session cookie)──► /v1/*         ─┘      │
                                                         └─► Web Push (VAPID) ──► browser push service ──► γονέας
 jobs (κάθε 60 s): κλείνει παράθυρα που έληξαν όταν η συσκευή είναι offline
```

- **Πηγή αλήθειας για XP, levels, αστέρια και streak είναι το backend** (`app/game.py`). Η συσκευή δίνει άμεσο feedback και κάνει reconcile από το `/v1/device/config`.
- Ένα stateless API container, ένα jobs container και Postgres. Τα migrations τρέχουν ως ξεχωριστό βήμα, όχι σε κάθε εκκίνηση.

## 2. Schema

| Πίνακας | Περιεχόμενο | Σημειώσεις |
|---|---|---|
| `family` | Ζώνη ώρας (IANA) | Όλοι οι υπολογισμοί ημέρας γίνονται σε αυτή τη ζώνη |
| `parent` | Email, quiet hours | Μόνο ενήλικες έχουν λογαριασμό |
| `magic_link`, `auth_session` | Passwordless login | Αποθηκεύονται **μόνο SHA-256 hashes** των tokens |
| `child` | Ψευδώνυμο, avatar, level, one-shot animation | **Χωρίς** ημερομηνία γέννησης, φωτογραφία ή επώνυμο |
| `device`, `claim_code` | Pairing, device token, ρυθμίσεις ήχου/φωτός | Hashes. Το revoke αλλάζει αμέσως το token |
| `routine`, `routine_step` | Παράθυρο, ημέρες, κουμπί→βήμα, ειδοποιήσεις | Integer id (= `routine_id` του firmware). Archive αντί για διαγραφή |
| `device_event` | Κάθε event του firmware | PK = `event_id` (UUIDv4) → **idempotent** |
| `quest_day` | Κατάσταση quest ανά (παιδί, quest, ημέρα) | `in_progress` / `complete` / `expired` |
| `xp_entry`, `star_entry` | **Append-only ledgers** | Το undo γράφει αντισταθμιστική εγγραφή. Το υπόλοιπο είναι άθροισμα |
| `reward`, `redemption` | Rewards και εξαργυρώσεις | Ενεργό είναι το πρώτο μη-archived reward |
| `pause_day` | «Ημέρα εκτός» | Δεν μετρά στο streak και δεν βγάζει ειδοποίηση λήξης |
| `push_subscription` | Web Push endpoints | Αυτόματη διαγραφή σε 404/410 από τον push service |

Migration: `migrations/versions/0001_initial_schema.py`, παραγμένο με autogenerate. Είναι επαληθευμένο ως αναστρέψιμο (downgrade → upgrade), και το `alembic check` στο CI πιάνει drift ανάμεσα σε models και migrations.

## 3. Device API (contract με το `firmware/main/cloud.c`)

| Endpoint | Auth | Περιγραφή |
|---|---|---|
| `POST /v1/device/claim` | Claim code (μίας χρήσης, 15′) | `{device_id, claim_code, fw_version}` → `{device_token}`. Σε άκυρο code επιστρέφει **410** και το firmware πετάει το code. Re-pair σε άλλη οικογένεια = νέο token |
| `POST /v1/device/events` | Bearer device token | Έως 50 events/batch, ταξινόμηση με `seq`, dedupe με `event_id`. Events με ρολόι > +1 ημέρα ή > 30 ημέρες πίσω αποθηκεύονται αλλά δεν βαθμολογούνται |
| `GET /v1/device/config` | Bearer device token | `version` = CRC32 του περιεχομένου, `ETag`/`If-None-Match` → **304**. Περιέχει POSIX `tz`, routines, level, `week_stars`, `paused_day`, `anim {seq,type}`, `ota` |

Το POSIX TZ string παράγεται από το tzdata (π.χ. `Europe/Athens` → `EET-2EEST,M3.5.0/3,M10.5.0/4`), οπότε οι αλλαγές ώρας είναι πάντα σωστές στη συσκευή.

## 4. Parent API (για την PWA)

| Περιοχή | Endpoints |
|---|---|
| Auth | `POST /v1/auth/magic-link` (πάντα 202, χωρίς account enumeration, rate limit) · `POST /v1/auth/verify` → HttpOnly cookie · `POST /v1/auth/logout` |
| Λογαριασμός | `GET/PATCH/DELETE /v1/me` (το delete θέλει `{"confirm":"ΔΙΑΓΡΑΦΗ"}`) · `GET /v1/me/export` (GDPR portability) · `POST /v1/family/invites` |
| Παιδί & quests | `POST /v1/children` · `PATCH /v1/children/{id}` · `GET/PUT /v1/children/{id}/routines` (ίδια validation με το `qe_schedule_valid` του firmware) · `PATCH /v1/routines/{id}/notifications` |
| Οθόνες C1/C4 | `GET /v1/children/{id}/today` · `GET /v1/children/{id}/history?days=7` |
| Ημέρα εκτός | `PUT/DELETE /v1/children/{id}/pause` |
| Rewards (C5) | `GET/POST /v1/children/{id}/rewards` · `PATCH/DELETE /v1/rewards/{id}` · `POST /v1/rewards/{id}/give` |
| Συσκευή (O3, C6) | `POST /v1/children/{id}/claim-codes` · `PATCH /v1/devices/{id}` · `DELETE /v1/devices/{id}` (revoke) |
| Web Push | `GET /v1/push/vapid-public-key` · `POST/DELETE /v1/push/subscriptions` |

Πλήρης περιγραφή: OpenAPI στο `/docs` (εκτός production).

## 5. Κανόνες παιχνιδιού στο server (docs/02)

| Event | XP | ⭐ | Άλλα |
|---|---|---|---|
| `step_done` | +10 | — | Ένα expired quest ξανανοίγει αν φτάσει καθυστερημένο πάτημα από offline συσκευή |
| `quest_complete` | +10 (τελευταίο βήμα) +20 | +1 | `fast` αποθηκεύεται για το «⚡» στο ιστορικό |
| Όλα τα quests της ημέρας | +20 (perfect day) | — | Αντιστρέφεται αν γίνει undo |
| `step_undone` | −10 (και −20 αν ήταν complete) | −1 αν ήταν complete | Το πορτοφόλι αστεριών δεν πάει ποτέ κάτω από 0 |
| `quest_expired` ή server job | — | — | Μία ειδοποίηση. Χωρίς ποινή |

- **Levels:** 0 / 150 / 400 / 800 / 1400, μετά +800. Μόνο η άνοδος ανακοινώνεται (animation `level_up` + push).
- **Treasure:** όταν τα ⭐ φτάσουν το κόστος του ενεργού reward, ενεργοποιείται animation `treasure` και push «reward έτοιμο». Το `give` αφαιρεί τα αστέρια και ενεργοποιεί το επόμενο reward.
- **Streak:** συνεχόμενες επιτυχημένες ημέρες. Οι ημέρες pause ή χωρίς πρόγραμμα παραλείπονται. 1 ασπίδα ανά εβδομάδα (Δευτέρα–Κυριακή).

## 6. Ειδοποιήσεις

| Τύπος | Πότε | Παράδειγμα |
|---|---|---|
| Βήμα | Μόνο σε mode `each_step` | 🪥 Λένα: Δόντια ✓ (1/4) |
| Ολοκλήρωση | `each_step` ή `complete_only` | 🎉 Λένα ολοκλήρωσε: Πρωινό quest! ⚡ |
| Λήξη | `notify_expired = true` | ⏰ Πρωινό quest: έκλεισε με 1/4 βήματα. |
| Reward | Πάντα | 🛝 Λένα μάζεψε 5 ⭐ — «Παιδική χαρά» είναι έτοιμο! |
| Level | Πάντα | 🌈 Λένα ανέβηκε στο Level 3! |

- **Δεν στέλνονται:** σε quiet hours (ανά γονέα, μπορεί να περνά τα μεσάνυχτα), σε mode `mute`, και για events παλαιότερα από 15′ (backlog μιας offline συσκευής).
- **Payload:** μόνο ψευδώνυμο και όνομα quest ή reward. Κρυπτογραφείται κατά RFC 8291 και υπογράφεται με VAPID (RFC 8292). Επαληθεύεται από το `tests/test_webpush.py`.
- Η αποστολή γίνεται **μετά** το commit (BackgroundTasks), ώστε ένα αργό push service να μην καθυστερεί τη συσκευή.

## 7. Ασφάλεια & ιδιωτικότητα

- **Secrets:** sessions, magic links, claim codes και device tokens υπάρχουν στη βάση μόνο ως SHA-256 hashes.
- **Cookie:** HttpOnly, Secure (production), SameSite=Lax. Το API δέχεται μόνο JSON. Με SameSite=Lax και same-origin PWA αυτό καλύπτει το CSRF για το MVP.
- **Isolation:** κάθε πρόσβαση σε παιδί περνά από `owned_child()`. Σε ξένη οικογένεια επιστρέφεται 404, όχι 403, ώστε να μην αποκαλύπτεται ότι το παιδί υπάρχει.
- **Rate limiting:** in-process (magic link: 5/ώρα ανά email και IP · claim: 20/10′ ανά IP). Με περισσότερα από ένα instances χρειάζεται rate limiting στον reverse proxy ή κοινό store.
- **GDPR:**
  - Export όλων των δεδομένων.
  - Hard delete: ο τελευταίος γονέας παίρνει μαζί του όλη την οικογένεια με cascade, μαζί και τα device tokens.
  - Data minimization για το παιδί (μόνο ψευδώνυμο και avatar).
- **Production:** στο `RQ_ENV=prod` κλείνουν τα `/docs` και `/openapi.json`, και απορρίπτεται ο console mailer.

## 8. Επαλήθευση

| Έλεγχος | Αποτέλεσμα |
|---|---|
| `pytest` (PostgreSQL 16, Alembic migrations) | **45 passed**: auth, isolation, validation, claim/revoke, idempotency, scoring, undo, perfect day, rewards, level-up, streak/shield/pause, server expiry, quiet hours, backlog, export/delete, re-pair |
| Πραγματικό Web Push (aes128gcm + VAPID) σε τοπικό push endpoint | ✓ |
| `alembic downgrade base → upgrade head`, `alembic check` | ✓ χωρίς drift |
| `ruff check` / `ruff format --check` | ✓ |
| Uvicorn smoke test (`/healthz`, `/docs`, 23 paths) | ✓ |
| Contract με το firmware | Τα tests στέλνουν events **ακριβώς** όπως τα σειριοποιεί το `cloud.c` (αριθμοί ως cJSON doubles) και ελέγχουν το config που διαβάζει το `parse_config()` |

## 9. Γνωστοί περιορισμοί & επόμενα βήματα

1. **PWA provisioning client:** η PWA χρειάζεται protocomm client (protobuf + Security 1) πάνω από Web Bluetooth για Wi-Fi και claim code. Μέχρι να γίνει, το pairing δοκιμάζεται με την εφαρμογή «ESP BLE Provisioning» και το endpoint `rq-claim`.
2. **Ιστορικό προγράμματος:** το streak χρησιμοποιεί το *τρέχον* πρόγραμμα και για παλιές ημέρες.
3. **Parent check (P6/C6):** δεν υλοποιείται στο MVP backend. Αφαιρέθηκε από το API ώστε να μην υπάρχει διακόπτης χωρίς λειτουργία.
4. **Real-time ενημέρωση της PWA (C1):** η PWA κάνει polling στο `/today`. SSE στη v1.1.
5. **Αλλαγές προς τη συσκευή:** φτάνουν μέσω config polling (≤ 60 s). MQTT εξετάζεται στη v2.
6. **i18n:** τα κείμενα των push είναι ελληνικά, hard-coded.
