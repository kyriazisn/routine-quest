# Device provisioning simulator

`prov_sim.py` emulates the provisioning side of the Routine Quest firmware
(`firmware/main/net.c` → ESP-IDF v5.3 `wifi_provisioning`, Security 1, plus the custom
`rq-claim` endpoint) over HTTP, the way ESP-IDF's `protocomm_httpd` exposes endpoints
(`POST /<endpoint>`).

Used by:
- `src/provisioning/*.test.ts`: the PWA's TypeScript client against the simulator
- `e2e/`: the full pairing flow in a real browser (HTTP transport)
- `check_with_esp_prov.sh`: Espressif's **official** `esp_prov` client against the simulator
  (needs an ESP-IDF checkout). This proves the simulator speaks the real protocol, so a
  passing TypeScript test means the TypeScript client does too.

`proto/` holds the unmodified ESP-IDF v5.3.2 `.proto` files (Apache-2.0, © Espressif Systems),
compiled to Python at start-up with `grpcio-tools`.

Not covered here: the BLE transport itself (GATT UUIDs/descriptors). That needs a real
device (test plan, Phase 7).
