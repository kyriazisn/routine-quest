#!/usr/bin/env bash
# Validate the simulator with Espressif's official provisioning client (esp_prov, ESP-IDF v5.3).
# Usage: IDF_PATH=~/esp-idf ./check_with_esp_prov.sh
set -euo pipefail
: "${IDF_PATH:?set IDF_PATH to an ESP-IDF v5.3 checkout}"
PY=${PYTHON:-python3}
PORT=${PORT:-8091}
HERE=$(cd "$(dirname "$0")" && pwd)

"$PY" "$HERE/prov_sim.py" --port "$PORT" --pop rq-dev-pop >/tmp/prov-sim-check.log 2>&1 &
SIM=$!
trap 'kill $SIM 2>/dev/null' EXIT
sleep 3

export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
cd "$IDF_PATH/tools/esp_prov"

echo "== 1. official client, correct PoP: must succeed"
"$PY" esp_prov.py --transport softap --service_name "127.0.0.1:$PORT" --sec_ver 1 --pop rq-dev-pop \
  --ssid HomeNet --passphrase secret123 --custom_data CLAIMCODE42 | grep -E "Provisioning was successful"
curl -fsS "http://127.0.0.1:$PORT/_state" | grep -q '"claim_code": "CLAIMCODE42"'

echo "== 2. official client, wrong PoP: must fail"
if "$PY" esp_prov.py --transport softap --service_name "127.0.0.1:$PORT" --sec_ver 1 --pop WRONG \
  --ssid HomeNet --passphrase secret123 >/dev/null 2>&1; then
  echo "FAIL: wrong PoP accepted"; exit 1
fi
echo "OK: simulator is protocol-compatible with esp_prov"
