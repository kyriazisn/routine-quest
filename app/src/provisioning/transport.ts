/**
 * Transports for ESP-IDF protocomm endpoints.
 *  - BleTransport: Web Bluetooth (Chrome/Edge on Android, Windows, macOS, ChromeOS, Linux).
 *    Safari/iOS has no Web Bluetooth.
 *  - HttpTransport: protocomm over HTTP (POST /<endpoint>), as used by SoftAP provisioning and
 *    by our device simulator in tests.
 */
import { ab } from "./protobuf";

export interface Transport {
  send(endpoint: string, data: Uint8Array): Promise<Uint8Array>;
  close(): Promise<void>;
}

// ESP-IDF wifi_provisioning scheme_ble default service (scheme_ble.c, LSB-first bytes reversed)
export const PROV_SERVICE_UUID = "1775244d-6b43-439b-877c-060f2d9bed07";
// Endpoint UUIDs replace bytes 12..13 of the service UUID (manager.c: 0xFF50.., custom endpoints next)
export const ENDPOINT_UUID16: Record<string, number> = {
  "prov-scan": 0xff50,
  "prov-session": 0xff51,
  "prov-config": 0xff52,
  "proto-ver": 0xff53,
  "rq-claim": 0xff54, // firmware/main/net.c: first custom endpoint
};

export function endpointUuid(uuid16: number): string {
  return `1775${uuid16.toString(16).padStart(4, "0")}-6b43-439b-877c-060f2d9bed07`;
}

export function bleSupported(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator;
}

/* Minimal Web Bluetooth typings (not in lib.dom yet). */
interface BtCharacteristic {
  uuid: string;
  writeValueWithResponse(v: BufferSource): Promise<void>;
  readValue(): Promise<DataView>;
  getDescriptor(name: string | number): Promise<{ readValue(): Promise<DataView> }>;
}
interface BtDevice {
  name?: string;
  gatt?: {
    connect(): Promise<{
      getPrimaryService(uuid: string): Promise<{ getCharacteristics(): Promise<BtCharacteristic[]> }>;
      disconnect(): void;
      connected: boolean;
    }>;
  };
}

export class BleTransport implements Transport {
  private chars = new Map<string, BtCharacteristic>();
  private disconnect?: () => void;
  deviceName = "";

  /** Must be called from a user gesture (button click). */
  static async request(namePrefix = "RQ-"): Promise<BleTransport> {
    const nav = navigator as unknown as { bluetooth: { requestDevice(o: unknown): Promise<BtDevice> } };
    const device = await nav.bluetooth.requestDevice({
      filters: [{ namePrefix }],
      optionalServices: [PROV_SERVICE_UUID],
    });
    const t = new BleTransport();
    t.deviceName = device.name ?? "";
    const server = await device.gatt!.connect();
    t.disconnect = () => server.disconnect();
    const service = await server.getPrimaryService(PROV_SERVICE_UUID);
    const chars = await service.getCharacteristics();
    const byUuid = new Map(chars.map((c) => [c.uuid.toLowerCase(), c]));
    // Preferred: endpoint names from Characteristic User Description (0x2901), as esp_prov does
    for (const c of chars) {
      try {
        const d = await c.getDescriptor("gatt.characteristic_user_description");
        const name = new TextDecoder().decode((await d.readValue()).buffer).replace(/\0+$/, "");
        if (name) t.chars.set(name, c);
      } catch {
        /* descriptor missing: fall back to computed UUIDs */
      }
    }
    for (const [name, u16] of Object.entries(ENDPOINT_UUID16)) {
      const c = byUuid.get(endpointUuid(u16));
      if (c && !t.chars.has(name)) t.chars.set(name, c);
    }
    return t;
  }

  async send(endpoint: string, data: Uint8Array): Promise<Uint8Array> {
    const c = this.chars.get(endpoint);
    if (!c) throw new Error(`device has no '${endpoint}' endpoint`);
    await c.writeValueWithResponse(ab(data));
    const v = await c.readValue();
    return new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));
  }

  async close(): Promise<void> {
    this.disconnect?.();
  }
}

export class HttpTransport implements Transport {
  constructor(private readonly baseUrl: string) {}

  async send(endpoint: string, data: Uint8Array): Promise<Uint8Array> {
    const r = await fetch(`${this.baseUrl}/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "text/plain" },
      body: ab(data),
    });
    if (!r.ok) throw new Error(`${endpoint}: HTTP ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
  }

  async close(): Promise<void> {}
}
