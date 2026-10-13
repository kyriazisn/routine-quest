/**
 * Provisioning flow for the Routine Quest device (firmware/main/net.c):
 *   proto-ver → Security 1 session (PoP) → [scan] → rq-claim (one-time code from the backend)
 *   → Wi-Fi credentials → apply → poll status.
 * The claim code goes first: once Wi-Fi connects the device ends provisioning and BLE drops.
 * Wi-Fi credentials go only to the device (encrypted), never to our backend.
 */
import {
  type FailReason,
  ProvError,
  type WifiNetwork,
  cfgApply,
  cfgGetStatus,
  cfgSetConfig,
  parseCfgSimple,
  parseCfgStatus,
  parseScanResult,
  parseScanStatus,
  scanResult,
  scanStart,
  scanStatus,
} from "./messages";
import { Sec1Session } from "./sec1";
import type { Transport } from "./transport";

export type ProvStep = "version" | "session" | "scan" | "claim" | "wifi" | "connecting" | "done";

export class ProvisioningClient {
  private constructor(
    private readonly t: Transport,
    private readonly sec: Sec1Session,
    readonly version: Record<string, unknown>,
  ) {}

  static async connect(t: Transport, pop: string): Promise<ProvisioningClient> {
    let version: Record<string, unknown> = {};
    try {
      const raw = await t.send("proto-ver", new TextEncoder().encode("ESP"));
      version = JSON.parse(new TextDecoder().decode(raw));
    } catch {
      /* optional: older firmware may not answer */
    }
    const sec = await Sec1Session.create(pop);
    const r0 = await t.send("prov-session", sec.command0());
    const cmd1 = await sec.handleResponse0(r0);
    const r1 = await t.send("prov-session", cmd1);
    await sec.handleResponse1(r1);
    return new ProvisioningClient(t, sec, version);
  }

  private async call(endpoint: string, msg: Uint8Array): Promise<Uint8Array> {
    const enc = await this.sec.crypt(msg);
    const resp = await this.t.send(endpoint, enc);
    return this.sec.crypt(resp);
  }

  async scan(): Promise<WifiNetwork[]> {
    await this.call("prov-scan", scanStart());
    let status = parseScanStatus(await this.call("prov-scan", scanStatus()));
    for (let i = 0; !status.finished && i < 20; i++) {
      await new Promise((r) => setTimeout(r, 500));
      status = parseScanStatus(await this.call("prov-scan", scanStatus()));
    }
    const nets: WifiNetwork[] = [];
    for (let start = 0; start < status.count; start += 4) {
      nets.push(...parseScanResult(await this.call("prov-scan", scanResult(start, Math.min(4, status.count - start)))));
    }
    // strongest first, one entry per SSID, hidden networks dropped
    const best = new Map<string, WifiNetwork>();
    for (const n of nets) {
      if (n.ssid && (!best.has(n.ssid) || best.get(n.ssid)!.rssi < n.rssi)) best.set(n.ssid, n);
    }
    return [...best.values()].sort((a, b) => b.rssi - a.rssi);
  }

  async sendClaimCode(code: string): Promise<void> {
    const reply = new TextDecoder().decode(await this.call("rq-claim", new TextEncoder().encode(code)));
    if (reply !== "ok") throw new ProvError(`device rejected claim code (${reply})`, "claim");
  }

  async setWifi(ssid: string, passphrase: string): Promise<void> {
    parseCfgSimple(await this.call("prov-config", cfgSetConfig(ssid, passphrase)), "resp_set_config");
    parseCfgSimple(await this.call("prov-config", cfgApply()), "resp_apply_config");
  }

  async waitConnected(timeoutMs = 30000, pollMs = 1000): Promise<{ ok: true } | { ok: false; reason: FailReason }> {
    const until = Date.now() + timeoutMs;
    while (Date.now() < until) {
      const s = parseCfgStatus(await this.call("prov-config", cfgGetStatus()));
      if (s.state === "connected") return { ok: true };
      if (s.state === "failed") return { ok: false, reason: s.failReason };
      await new Promise((r) => setTimeout(r, pollMs));
    }
    return { ok: false, reason: undefined };
  }

  async close(): Promise<void> {
    await this.t.close();
  }
}
