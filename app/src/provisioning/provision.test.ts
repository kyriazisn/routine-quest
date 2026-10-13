/**
 * The PWA's provisioning client against the device simulator (app/e2e/sim/prov_sim.py),
 * which is itself validated against Espressif's official esp_prov client.
 */
import { type ChildProcess, spawn } from "node:child_process";
import { resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ProvError } from "./messages";
import { ProvisioningClient } from "./provision";
import { HttpTransport } from "./transport";

const PORT = 8190 + Math.floor(Math.random() * 500);
const BASE = `http://127.0.0.1:${PORT}`;
const POP = "rq-dev-pop";
let sim: ChildProcess;

async function state(): Promise<Record<string, unknown>> {
  return (await fetch(`${BASE}/_state`)).json();
}

beforeAll(async () => {
  const py = process.env.RQ_PYTHON ?? "python3";
  sim = spawn(py, [resolve(__dirname, "../../e2e/sim/prov_sim.py"), "--port", String(PORT), "--pop", POP,
    "--networks", "HomeNet:secret123,Guest:"], { stdio: ["ignore", "pipe", "inherit"] });
  for (let i = 0; i < 100; i++) {
    try {
      await fetch(`${BASE}/_state`);
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 100));
    }
  }
  throw new Error("simulator did not start");
}, 30_000);

afterAll(() => {
  sim?.kill();
});

describe("ESP-IDF provisioning client (Security 1)", () => {
  it("performs the full pairing flow: session, scan, claim, Wi-Fi, connect", async () => {
    const c = await ProvisioningClient.connect(new HttpTransport(BASE), POP);
    expect((c.version.prov as { sec_ver: number }).sec_ver).toBe(1);

    const nets = await c.scan();
    expect(nets.map((n) => n.ssid)).toEqual(["HomeNet", "Guest"]);
    expect(nets[0].rssi).toBeLessThan(0); // negative int32 decoded correctly
    expect(nets[1].auth).toBe(0); // open network

    await c.sendClaimCode("ABCD2345XY");
    await c.setWifi("HomeNet", "secret123");
    expect(await c.waitConnected(10_000, 50)).toEqual({ ok: true });

    const s = await state();
    expect(s.claim_code).toBe("ABCD2345XY");
    expect(s.ssid).toBe("HomeNet");
    expect(s.passphrase_set).toBe(true);
  });

  it("rejects a wrong proof-of-possession", async () => {
    await expect(ProvisioningClient.connect(new HttpTransport(BASE), "wrong-pop")).rejects.toMatchObject({
      code: expect.stringMatching(/pop|device_status/),
    });
  });

  it("reports a wrong Wi-Fi password", async () => {
    const c = await ProvisioningClient.connect(new HttpTransport(BASE), POP);
    await c.setWifi("HomeNet", "nope");
    expect(await c.waitConnected(10_000, 50)).toEqual({ ok: false, reason: "auth_error" });
  });

  it("reports an unknown network", async () => {
    const c = await ProvisioningClient.connect(new HttpTransport(BASE), POP);
    await c.setWifi("Elsewhere", "x");
    expect(await c.waitConnected(10_000, 50)).toEqual({ ok: false, reason: "network_not_found" });
  });

  it("keeps the keystream in sync over many messages", async () => {
    const c = await ProvisioningClient.connect(new HttpTransport(BASE), POP);
    for (let i = 0; i < 25; i++) await c.sendClaimCode(`CODE${i}`.padEnd(10, "X")); // odd lengths cross 16-byte blocks
    expect((await state()).claim_code).toBe("CODE24XXXX");
  });

  it("is a ProvError for protocol failures", () => {
    expect(new ProvError("x", "pop")).toBeInstanceOf(Error);
  });
});
