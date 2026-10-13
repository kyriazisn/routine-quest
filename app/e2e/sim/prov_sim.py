"""
Routine Quest device provisioning simulator (ESP-IDF v5.3 protocomm over HTTP, Security 1).

    python prov_sim.py --port 8090 --pop rq-dev-pop --networks "HomeNet:secret123,Guest:"

Endpoints mirror ESP-IDF: proto-ver, prov-session, prov-config, prov-scan and the firmware's
custom rq-claim (also aliased as custom-data for esp_prov). GET /_state returns what the
"device" received (claim code, credentials) for tests.

Security 1 mirrors components/protocomm/src/security/security1.c: X25519, key = shared XOR
SHA-256(PoP), AES-256-CTR with IV = device_random and ONE keystream for all messages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HERE = os.path.dirname(os.path.abspath(__file__))


def load_protos():
    out = tempfile.mkdtemp(prefix="rqpb_")
    proto_dir = os.path.join(HERE, "proto")
    files = [f for f in os.listdir(proto_dir) if f.endswith(".proto")]
    subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{proto_dir}", f"--python_out={out}", *files],
                   check=True)
    sys.path.insert(0, out)
    import session_pb2  # noqa: E402
    import wifi_config_pb2  # noqa: E402
    import wifi_constants_pb2  # noqa: E402
    import wifi_scan_pb2  # noqa: E402

    return session_pb2, wifi_config_pb2, wifi_constants_pb2, wifi_scan_pb2


session_pb2, wifi_config_pb2, wifi_constants_pb2, wifi_scan_pb2 = load_protos()
import sec1_pb2  # noqa: E402  (generated next to session_pb2)


class Device:
    def __init__(self, pop: str, networks: dict[str, str]):
        self.pop = pop.encode()
        self.networks = networks
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.cipher = None
        self.client_pub = b""
        self.device_pub = b""
        self.claim_code: str | None = None
        self.creds: tuple[str, str] | None = None
        self.applied = False
        self.status_polls = 0
        self.session_ok = False

    # ---------------------------------------------------------------- session
    def session(self, data: bytes) -> bytes:
        req = session_pb2.SessionData()
        req.ParseFromString(data)
        resp = session_pb2.SessionData()
        resp.sec_ver = session_pb2.SecScheme1
        if req.sec_ver != session_pb2.SecScheme1:
            raise ValueError("only Security 1 supported")
        if req.sec1.msg == sec1_pb2.Session_Command0:
            self.reset()
            priv = X25519PrivateKey.generate()
            self.device_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.client_pub = req.sec1.sc0.client_pubkey
            shared = priv.exchange(X25519PublicKey.from_public_bytes(self.client_pub))
            if self.pop:
                digest = hashlib.sha256(self.pop).digest()
                shared = bytes(a ^ b for a, b in zip(shared, digest, strict=True))
            self.rand = os.urandom(16)
            self.key = shared
            resp.sec1.msg = sec1_pb2.Session_Response0
            resp.sec1.sr0.status = 0
            resp.sec1.sr0.device_pubkey = self.device_pub
            resp.sec1.sr0.device_random = self.rand
        elif req.sec1.msg == sec1_pb2.Session_Command1:
            self.cipher = Cipher(algorithms.AES(self.key), modes.CTR(self.rand)).encryptor()
            check = self.cipher.update(req.sec1.sc1.client_verify_data)
            resp.sec1.msg = sec1_pb2.Session_Response1
            if check != self.device_pub:  # wrong PoP: the device closes the session
                self.cipher = None
                resp.sec1.sr1.status = 6  # CryptoError
            else:
                resp.sec1.sr1.status = 0
                resp.sec1.sr1.device_verify_data = self.cipher.update(self.client_pub)
                self.session_ok = True
        return resp.SerializeToString()

    def crypt(self, data: bytes) -> bytes:
        if self.cipher is None or not self.session_ok:
            raise PermissionError("no secure session")
        return self.cipher.update(data)

    # ---------------------------------------------------------------- endpoints
    def config(self, data: bytes) -> bytes:
        req = wifi_config_pb2.WiFiConfigPayload()
        req.ParseFromString(data)
        resp = wifi_config_pb2.WiFiConfigPayload()
        T = wifi_config_pb2
        if req.msg == T.TypeCmdSetConfig:
            self.creds = (req.cmd_set_config.ssid.decode(), req.cmd_set_config.passphrase.decode())
            resp.msg = T.TypeRespSetConfig
            resp.resp_set_config.status = 0
        elif req.msg == T.TypeCmdApplyConfig:
            self.applied = True
            self.status_polls = 0
            resp.msg = T.TypeRespApplyConfig
            resp.resp_apply_config.status = 0
        elif req.msg == T.TypeCmdGetStatus:
            resp.msg = T.TypeRespGetStatus
            resp.resp_get_status.status = 0
            self.status_polls += 1
            C = wifi_constants_pb2
            if not self.applied or not self.creds:
                resp.resp_get_status.sta_state = C.Disconnected
            elif self.status_polls < 2:
                resp.resp_get_status.sta_state = C.Connecting
            elif self.creds[0] not in self.networks:
                resp.resp_get_status.sta_state = C.ConnectionFailed
                resp.resp_get_status.fail_reason = C.NetworkNotFound
            elif self.networks[self.creds[0]] != self.creds[1]:
                resp.resp_get_status.sta_state = C.ConnectionFailed
                resp.resp_get_status.fail_reason = C.AuthError
            else:
                resp.resp_get_status.sta_state = C.Connected
                resp.resp_get_status.connected.ip4_addr = "192.168.1.42"
                resp.resp_get_status.connected.ssid = self.creds[0].encode()
                resp.resp_get_status.connected.channel = 6
        return resp.SerializeToString()

    def scan(self, data: bytes) -> bytes:
        req = wifi_scan_pb2.WiFiScanPayload()
        req.ParseFromString(data)
        resp = wifi_scan_pb2.WiFiScanPayload()
        resp.status = 0
        T = wifi_scan_pb2
        nets = [(s, -40 - 7 * i, 6 + i) for i, s in enumerate(self.networks)]
        if req.msg == T.TypeCmdScanStart:
            resp.msg = T.TypeRespScanStart
            resp.resp_scan_start.SetInParent()
        elif req.msg == T.TypeCmdScanStatus:
            resp.msg = T.TypeRespScanStatus
            resp.resp_scan_status.scan_finished = True
            resp.resp_scan_status.result_count = len(nets)
        elif req.msg == T.TypeCmdScanResult:
            resp.msg = T.TypeRespScanResult
            start, count = req.cmd_scan_result.start_index, req.cmd_scan_result.count
            for ssid, rssi, ch in nets[start:start + count]:
                e = resp.resp_scan_result.entries.add()
                e.ssid = ssid.encode()
                e.rssi = rssi
                e.channel = ch
                e.auth = 3 if self.networks[ssid] else 0  # WPA2_PSK / Open
        return resp.SerializeToString()

    def claim(self, data: bytes) -> bytes:
        code = data.decode(errors="replace")
        if not 0 < len(code) <= 64:
            return b"err:len"
        self.claim_code = code
        return b"ok"


def make_handler(dev: Device):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # noqa: N802 — CORS preflight from the browser e2e
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if self.path == "/_state":
                body = {"claim_code": dev.claim_code, "ssid": dev.creds[0] if dev.creds else None,
                        "passphrase_set": bool(dev.creds and dev.creds[1]), "applied": dev.applied,
                        "session_ok": dev.session_ok}
                self._send(200, json.dumps(body).encode(), "application/json")
            else:
                self._send(404, b"")

        def do_POST(self):  # noqa: N802
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            ep = self.path.strip("/")
            with dev.lock:
                try:
                    if ep == "proto-ver":
                        v = {"prov": {"ver": "v1.1", "sec_ver": 1, "cap": ["wifi_scan"]},
                             "rq": {"fw": "0.1.0-sim"}}
                        return self._send(200, json.dumps(v).encode())
                    if ep == "prov-session":
                        return self._send(200, dev.session(data))
                    handlers = {"prov-config": dev.config, "prov-scan": dev.scan, "rq-claim": dev.claim,
                                "custom-data": dev.claim}
                    if ep not in handlers:
                        return self._send(404, b"")
                    plain = dev.crypt(data)
                    out = handlers[ep](plain)
                    return self._send(200, dev.crypt(out))
                except PermissionError as e:
                    return self._send(403, str(e).encode())
                except Exception as e:  # noqa: BLE001 — report to the test, keep serving
                    return self._send(500, f"{type(e).__name__}: {e}".encode())

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--pop", default="rq-dev-pop")
    ap.add_argument("--networks", default="HomeNet:secret123,Guest:")
    a = ap.parse_args()
    nets = dict(n.split(":", 1) for n in a.networks.split(",") if n)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Device(a.pop, nets)))
    print(f"prov-sim listening on http://127.0.0.1:{a.port} (pop={'*' * len(a.pop)}, networks={list(nets)})",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
