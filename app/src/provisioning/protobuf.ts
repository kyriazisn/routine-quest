/**
 * Minimal protobuf (proto3) codec — just what ESP-IDF provisioning needs:
 * varint (uint32/int32/bool/enum) and length-delimited (bytes/string/sub-message) fields.
 * Field numbers come from ESP-IDF v5.3 .proto files (see messages.ts).
 */

export class Writer {
  private buf: number[] = [];

  private varint(v: bigint): void {
    let x = BigInt.asUintN(64, v);
    while (x > 0x7fn) {
      this.buf.push(Number((x & 0x7fn) | 0x80n));
      x >>= 7n;
    }
    this.buf.push(Number(x));
  }

  private tag(field: number, wire: 0 | 2): void {
    this.varint(BigInt((field << 3) | wire));
  }

  /** Scalar varint field. proto3 omits default (0/false) values. */
  uint(field: number, v: number | boolean): this {
    const n = typeof v === "boolean" ? (v ? 1 : 0) : v;
    if (n !== 0) {
      this.tag(field, 0);
      this.varint(BigInt(n));
    }
    return this;
  }

  /** bytes/string field. proto3 omits empty values. */
  bytes(field: number, v: Uint8Array | string): this {
    const b = typeof v === "string" ? new TextEncoder().encode(v) : v;
    if (b.length > 0) {
      this.tag(field, 2);
      this.varint(BigInt(b.length));
      for (const x of b) this.buf.push(x);
    }
    return this;
  }

  /** Sub-message field. Always emitted: a set oneof member must be present even when empty. */
  message(field: number, sub: Uint8Array): this {
    this.tag(field, 2);
    this.varint(BigInt(sub.length));
    for (const x of sub) this.buf.push(x);
    return this;
  }

  finish(): Uint8Array {
    return Uint8Array.from(this.buf);
  }
}

export type FieldValue = bigint | Uint8Array;
export type Fields = Map<number, FieldValue[]>;

export function decode(buf: Uint8Array): Fields {
  const out: Fields = new Map();
  let i = 0;
  const readVarint = (): bigint => {
    let shift = 0n;
    let result = 0n;
    for (;;) {
      if (i >= buf.length) throw new Error("protobuf: truncated varint");
      const b = buf[i++];
      result |= BigInt(b & 0x7f) << shift;
      if ((b & 0x80) === 0) return result;
      shift += 7n;
      if (shift > 70n) throw new Error("protobuf: varint too long");
    }
  };
  while (i < buf.length) {
    const key = Number(readVarint());
    const field = key >>> 3;
    const wire = key & 7;
    let value: FieldValue;
    if (wire === 0) {
      value = readVarint();
    } else if (wire === 2) {
      const len = Number(readVarint());
      if (i + len > buf.length) throw new Error("protobuf: truncated bytes");
      value = buf.slice(i, i + len);
      i += len;
    } else if (wire === 1) {
      i += 8;
      continue;
    } else if (wire === 5) {
      i += 4;
      continue;
    } else {
      throw new Error(`protobuf: unsupported wire type ${wire}`);
    }
    const list = out.get(field) ?? [];
    list.push(value);
    out.set(field, list);
  }
  return out;
}

export const get = {
  uint(f: Fields, field: number): number {
    const v = f.get(field)?.at(-1);
    return typeof v === "bigint" ? Number(BigInt.asUintN(32, v)) : 0;
  },
  int32(f: Fields, field: number): number {
    const v = f.get(field)?.at(-1);
    return typeof v === "bigint" ? Number(BigInt.asIntN(32, v)) : 0;
  },
  bool(f: Fields, field: number): boolean {
    return get.uint(f, field) !== 0;
  },
  bytes(f: Fields, field: number): Uint8Array {
    const v = f.get(field)?.at(-1);
    return v instanceof Uint8Array ? v : new Uint8Array();
  },
  string(f: Fields, field: number): string {
    return new TextDecoder().decode(get.bytes(f, field));
  },
  message(f: Fields, field: number): Fields | undefined {
    const v = f.get(field)?.at(-1);
    return v instanceof Uint8Array ? decode(v) : undefined;
  },
  repeated(f: Fields, field: number): Fields[] {
    return (f.get(field) ?? []).filter((v): v is Uint8Array => v instanceof Uint8Array).map(decode);
  },
  has(f: Fields, field: number): boolean {
    return f.has(field);
  },
};

/** Copy into a fresh ArrayBuffer-backed view (WebCrypto/fetch/BLE typings reject SharedArrayBuffer-able views). */
export function ab(u: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(u.length));
  out.set(u);
  return out;
}
