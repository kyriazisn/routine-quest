/**
 * ESP-IDF protocomm Security 1 (components/protocomm/src/security/security1.c, v5.3):
 *   - X25519 key exchange
 *   - key = shared_secret XOR SHA-256(proof_of_possession)
 *   - AES-256-CTR with IV = device_random, ONE continuous keystream for every message in
 *     both directions (the device keeps nc_off/stream_block across calls).
 * WebCrypto AES-CTR is stateless, so we track the keystream offset ourselves.
 */
import { ab } from "./protobuf";
import { ProvError, parseSessionResp0, parseSessionResp1, sessionCmd0, sessionCmd1 } from "./messages";

const subtle = globalThis.crypto.subtle;

function addToCounter(iv: Uint8Array, blocks: number): Uint8Array {
  const out = new Uint8Array(iv);
  let carry = blocks;
  for (let i = 15; i >= 0 && carry > 0; i--) {
    const sum = out[i] + (carry & 0xff);
    out[i] = sum & 0xff;
    carry = Math.floor(carry / 256) + (sum >> 8);
  }
  return out;
}

export class Sec1Session {
  private aesKey?: CryptoKey;
  private iv?: Uint8Array;
  private offset = 0;
  private clientPubkey!: Uint8Array;
  private devicePubkey!: Uint8Array;
  private privateKey!: CryptoKey;

  private constructor(private readonly pop: string) {}

  static async create(pop: string): Promise<Sec1Session> {
    const s = new Sec1Session(pop);
    const pair = (await subtle.generateKey({ name: "X25519" }, true, ["deriveBits"])) as CryptoKeyPair;
    s.privateKey = pair.privateKey;
    s.clientPubkey = new Uint8Array(await subtle.exportKey("raw", pair.publicKey));
    return s;
  }

  /** Session_Command0: our public key. */
  command0(): Uint8Array {
    return sessionCmd0(this.clientPubkey);
  }

  /** Session_Response0 → derive the session key; returns Session_Command1. */
  async handleResponse0(resp: Uint8Array): Promise<Uint8Array> {
    const { devicePubkey, deviceRandom } = parseSessionResp0(resp);
    this.devicePubkey = devicePubkey;
    const devKey = await subtle.importKey("raw", ab(devicePubkey), { name: "X25519" }, false, []);
    const shared = new Uint8Array(
      await subtle.deriveBits({ name: "X25519", public: devKey } as EcdhKeyDeriveParams, this.privateKey, 256),
    );
    if (this.pop.length > 0) {
      const digest = new Uint8Array(await subtle.digest("SHA-256", new TextEncoder().encode(this.pop)));
      for (let i = 0; i < 32; i++) shared[i] ^= digest[i];
    }
    this.aesKey = await subtle.importKey("raw", shared, { name: "AES-CTR" }, false, ["encrypt"]);
    this.iv = deviceRandom;
    this.offset = 0;
    const clientVerify = await this.crypt(devicePubkey);
    return sessionCmd1(clientVerify);
  }

  /** Session_Response1: the device proves it derived the same key (i.e. we used the right PoP). */
  async handleResponse1(resp: Uint8Array): Promise<void> {
    const deviceVerify = parseSessionResp1(resp);
    const decrypted = await this.crypt(deviceVerify);
    if (decrypted.length !== 32 || !decrypted.every((b, i) => b === this.clientPubkey[i])) {
      throw new ProvError("device verification failed (wrong proof-of-possession?)", "pop");
    }
  }

  /** CTR is symmetric: the same operation encrypts and decrypts, advancing the shared keystream. */
  async crypt(data: Uint8Array): Promise<Uint8Array> {
    if (!this.aesKey || !this.iv) throw new ProvError("session not established", "state");
    const skip = this.offset % 16;
    const counter = addToCounter(this.iv, Math.floor(this.offset / 16));
    const padded = new Uint8Array(skip + data.length);
    padded.set(data, skip);
    const out = new Uint8Array(await subtle.encrypt({ name: "AES-CTR", counter: ab(counter), length: 128 }, this.aesKey, padded));
    this.offset += data.length;
    return out.slice(skip);
  }

  get devicePublicKey(): Uint8Array {
    return this.devicePubkey;
  }
}
