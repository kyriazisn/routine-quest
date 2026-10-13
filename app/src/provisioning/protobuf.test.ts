import { describe, expect, it } from "vitest";
import { Writer, decode, get } from "./protobuf";

describe("protobuf codec", () => {
  it("round-trips varints, bytes and nested messages", () => {
    const inner = new Writer().bytes(1, "HomeNet").uint(2, 300).finish();
    const buf = new Writer().uint(1, 4).message(14, inner).bytes(3, new Uint8Array([0, 255])).finish();
    const f = decode(buf);
    expect(get.uint(f, 1)).toBe(4);
    const m = get.message(f, 14)!;
    expect(get.string(m, 1)).toBe("HomeNet");
    expect(get.uint(m, 2)).toBe(300);
    expect([...get.bytes(f, 3)]).toEqual([0, 255]);
  });

  it("omits proto3 defaults but always emits a set (empty) oneof message", () => {
    const buf = new Writer().uint(1, 0).bytes(2, "").message(10, new Uint8Array()).finish();
    expect([...buf]).toEqual([0x52, 0x00]); // field 10, wire 2, length 0
  });

  it("decodes negative int32 (10-byte varint), e.g. Wi-Fi RSSI", () => {
    // int32 -47 as encoded by protobuf: 0xd1 0xff 0xff 0xff 0xff 0xff 0xff 0xff 0xff 0x01
    const buf = new Uint8Array([0x18, 0xd1, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01]);
    expect(get.int32(decode(buf), 3)).toBe(-47);
  });

  it("rejects truncated input", () => {
    expect(() => decode(new Uint8Array([0x0a, 0x05, 0x01]))).toThrow(/truncated/);
  });
});
