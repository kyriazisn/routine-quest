/**
 * ESP-IDF v5.3 provisioning messages (components/protocomm/proto/{session,sec1,constants}.proto,
 * components/wifi_provisioning/proto/{wifi_config,wifi_scan,wifi_constants}.proto).
 * Field numbers below are copied from those files; tests check them against the official
 * Python bindings via the device simulator (app/e2e/sim).
 */
import { type Fields, Writer, decode, get } from "./protobuf";

export const Status = [
  "Success", "InvalidSecScheme", "InvalidProto", "TooManySessions",
  "InvalidArgument", "InternalError", "CryptoError", "InvalidSession",
] as const;

export class ProvError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

function checkStatus(status: number, what: string): void {
  if (status !== 0) throw new ProvError(`${what}: ${Status[status] ?? status}`, "device_status");
}

// ------------------------------------------------------------------ session (Security 1)

const SEC_SCHEME_1 = 1;
const SessionData = { sec_ver: 2, sec1: 11 };
const Sec1Payload = { msg: 1, sc0: 20, sr0: 21, sc1: 22, sr1: 23 };
const Sec1Msg = { Command0: 0, Response0: 1, Command1: 2, Response1: 3 };

export function sessionCmd0(clientPubkey: Uint8Array): Uint8Array {
  const sc0 = new Writer().bytes(1, clientPubkey).finish();
  const sec1 = new Writer().uint(Sec1Payload.msg, Sec1Msg.Command0).message(Sec1Payload.sc0, sc0).finish();
  return new Writer().uint(SessionData.sec_ver, SEC_SCHEME_1).message(SessionData.sec1, sec1).finish();
}

function sec1Of(buf: Uint8Array): Fields {
  const sd = decode(buf);
  if (get.uint(sd, SessionData.sec_ver) !== SEC_SCHEME_1) {
    throw new ProvError("device does not use Security 1", "sec_scheme");
  }
  const sec1 = get.message(sd, SessionData.sec1);
  if (!sec1) throw new ProvError("missing sec1 payload", "protocol");
  return sec1;
}

export function parseSessionResp0(buf: Uint8Array): { devicePubkey: Uint8Array; deviceRandom: Uint8Array } {
  const sr0 = get.message(sec1Of(buf), Sec1Payload.sr0);
  if (!sr0) throw new ProvError("missing SessionResp0", "protocol");
  checkStatus(get.uint(sr0, 1), "session setup");
  const devicePubkey = get.bytes(sr0, 2);
  const deviceRandom = get.bytes(sr0, 3);
  if (devicePubkey.length !== 32 || deviceRandom.length !== 16) {
    throw new ProvError("bad key material from device", "protocol");
  }
  return { devicePubkey, deviceRandom };
}

export function sessionCmd1(clientVerify: Uint8Array): Uint8Array {
  const sc1 = new Writer().bytes(2, clientVerify).finish();
  const sec1 = new Writer().uint(Sec1Payload.msg, Sec1Msg.Command1).message(Sec1Payload.sc1, sc1).finish();
  return new Writer().uint(SessionData.sec_ver, SEC_SCHEME_1).message(SessionData.sec1, sec1).finish();
}

export function parseSessionResp1(buf: Uint8Array): Uint8Array {
  const sr1 = get.message(sec1Of(buf), Sec1Payload.sr1);
  if (!sr1) throw new ProvError("missing SessionResp1 (wrong proof-of-possession?)", "pop");
  checkStatus(get.uint(sr1, 1), "session verify");
  return get.bytes(sr1, 3);
}

// ------------------------------------------------------------------ Wi-Fi config

const CfgMsg = { GetStatus: 0, RespGetStatus: 1, SetConfig: 2, RespSetConfig: 3, ApplyConfig: 4, RespApplyConfig: 5 };
const CfgField = { msg: 1, cmd_get_status: 10, resp_get_status: 11, cmd_set_config: 12, resp_set_config: 13,
  cmd_apply_config: 14, resp_apply_config: 15 };

export function cfgSetConfig(ssid: string, passphrase: string): Uint8Array {
  const body = new Writer().bytes(1, ssid).bytes(2, passphrase).finish();
  return new Writer().uint(CfgField.msg, CfgMsg.SetConfig).message(CfgField.cmd_set_config, body).finish();
}

export function cfgApply(): Uint8Array {
  return new Writer().uint(CfgField.msg, CfgMsg.ApplyConfig).message(CfgField.cmd_apply_config, new Uint8Array()).finish();
}

export function cfgGetStatus(): Uint8Array {
  return new Writer().uint(CfgField.msg, CfgMsg.GetStatus).message(CfgField.cmd_get_status, new Uint8Array()).finish();
}

export function parseCfgSimple(buf: Uint8Array, field: "resp_set_config" | "resp_apply_config"): void {
  const resp = get.message(decode(buf), CfgField[field]);
  if (!resp) throw new ProvError(`missing ${field}`, "protocol");
  checkStatus(get.uint(resp, 1), field);
}

export type StaState = "connected" | "connecting" | "disconnected" | "failed";
export type FailReason = "auth_error" | "network_not_found" | undefined;

export function parseCfgStatus(buf: Uint8Array): { state: StaState; failReason: FailReason; ip?: string } {
  const resp = get.message(decode(buf), CfgField.resp_get_status);
  if (!resp) throw new ProvError("missing RespGetStatus", "protocol");
  checkStatus(get.uint(resp, 1), "get status");
  const state = (["connected", "connecting", "disconnected", "failed"] as const)[get.uint(resp, 2)] ?? "failed";
  let failReason: FailReason;
  if (state === "failed" && get.has(resp, 10)) {
    failReason = get.uint(resp, 10) === 0 ? "auth_error" : "network_not_found";
  }
  const connected = get.message(resp, 11);
  return { state, failReason, ip: connected ? get.string(connected, 1) : undefined };
}

// ------------------------------------------------------------------ Wi-Fi scan

const ScanMsg = { Start: 0, Status: 2, Result: 4 };
const ScanField = { msg: 1, status: 2, cmd_scan_start: 10, cmd_scan_status: 12, resp_scan_status: 13,
  cmd_scan_result: 14, resp_scan_result: 15 };

export function scanStart(): Uint8Array {
  const body = new Writer().uint(1, true).uint(4, 120).finish(); // blocking, 120 ms per channel
  return new Writer().uint(ScanField.msg, ScanMsg.Start).message(ScanField.cmd_scan_start, body).finish();
}

export function scanStatus(): Uint8Array {
  return new Writer().uint(ScanField.msg, ScanMsg.Status).message(ScanField.cmd_scan_status, new Uint8Array()).finish();
}

export function scanResult(start: number, count: number): Uint8Array {
  const body = new Writer().uint(1, start).uint(2, count).finish();
  return new Writer().uint(ScanField.msg, ScanMsg.Result).message(ScanField.cmd_scan_result, body).finish();
}

export function parseScanStatus(buf: Uint8Array): { finished: boolean; count: number } {
  const p = decode(buf);
  checkStatus(get.uint(p, ScanField.status), "scan status");
  const r = get.message(p, ScanField.resp_scan_status);
  return { finished: r ? get.bool(r, 1) : false, count: r ? get.uint(r, 2) : 0 };
}

export interface WifiNetwork {
  ssid: string;
  channel: number;
  rssi: number;
  auth: number; // 0 = open
}

export function parseScanResult(buf: Uint8Array): WifiNetwork[] {
  const p = decode(buf);
  checkStatus(get.uint(p, ScanField.status), "scan result");
  const r = get.message(p, ScanField.resp_scan_result);
  return (r ? get.repeated(r, 1) : []).map((e) => ({
    ssid: get.string(e, 1),
    channel: get.uint(e, 2),
    rssi: get.int32(e, 3),
    auth: get.uint(e, 5),
  }));
}
