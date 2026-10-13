"""
Generate the Routine Quest schematics from a reviewed netlist.

    python hardware/tools/gen_schematics.py           # writes *.kicad_sch, BOM CSV, netlist JSON
    python hardware/tools/check_schematic.py          # independent connectivity + ERC-style checks

Design rationale and calculations: docs/06-hardware.md.
Part numbers marked "verify" must be checked for availability before ordering (Phase 6b).
"""

from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from kisch import STUB, Part, Pin, Schematic, SymbolDef, circle, ic, poly, rect, snap, two_pin

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
ESP_LIB = os.environ.get("ESP_KICAD_LIB", "/root/esplib/symbols/Espressif.kicad_sym")
PROJECT = "routine-quest"

POWER_NETS = {"VBUS", "VBUS_F", "+5V", "+3V3", "GND"}

# --------------------------------------------------------------------------- symbol library (RQ:)

R = two_pin("RQ:R", "R", [rect(-2.54, 0.889, 2.54, -0.889, fill="none")])
C = two_pin("RQ:C", "C", [
    poly((-0.762, -1.524), (-0.762, 1.524), w=0.508), poly((0.762, -1.524), (0.762, 1.524), w=0.508),
    poly((-3.81, 0), (-0.762, 0)), poly((0.762, 0), (3.81, 0))])
FUSE = two_pin("RQ:Polyfuse", "F", [rect(-2.54, 0.762, 2.54, -0.762, fill="none"), poly((-3.81, 0), (3.81, 0)),
                                    poly((-2.54, -1.27), (-1.27, -1.27), (1.27, 1.27))])
_tri_left = poly((1.27, 1.27), (1.27, -1.27), (-1.27, 0), (1.27, 1.27), fill="none")
D = two_pin("RQ:D", "D", [_tri_left, poly((-1.27, 1.27), (-1.27, -1.27)), poly((-3.81, 0), (3.81, 0))],
            names=("K", "A"))
D_TVS = two_pin("RQ:D_TVS", "D", [_tri_left, poly((-1.778, 1.27), (-1.27, 1.27), (-1.27, -1.27), (-0.762, -1.27)),
                                  poly((-3.81, 0), (3.81, 0))], names=("K", "A"))
D_TVS_BI = two_pin("RQ:D_TVS_Bidir", "D", [
    poly((0, 0), (-2.54, 1.27), (-2.54, -1.27), (0, 0)), poly((0, 0), (2.54, 1.27), (2.54, -1.27), (0, 0)),
    poly((-0.508, 1.27), (0, 1.27), (0, -1.27), (0.508, -1.27)), poly((-3.81, 0), (3.81, 0))],
    names=("A1", "A2"))
SW = two_pin("RQ:SW_Push", "SW", [circle(-2.032, 0, 0.508), circle(2.032, 0, 0.508),
                                  poly((-2.54, 1.524), (2.54, 1.524)), poly((0, 1.524), (0, 3.048)),
                                  poly((-3.81, 0), (-2.54, 0)), poly((2.54, 0), (3.81, 0))])
BUZ = two_pin("RQ:Buzzer", "BZ", [circle(0, 0, 2.286), poly((-3.81, 0), (-2.286, 0)), poly((2.286, 0), (3.81, 0))],
              names=("+", "-"))
TP = SymbolDef("RQ:TestPoint", "TP", [Pin("1", "1", "passive", -3.81, 0, 0, 2.54)],
               [circle(0, 0, 1.016)], pin_names_hidden=True, pin_numbers_hidden=True,
               ref_at=(0, 2.54), value_at=(0, -2.54))

WS2812B = ic("RQ:WS2812B", "LED", left=[("4", "DIN", "input")], right=[("2", "DOUT", "output")],
             top=[("1", "VDD", "power_in")], bottom=[("3", "VSS", "power_in")], width=10.16)
USBC = ic("RQ:USB_C_Receptacle_USB2.0_16P", "J",
          left=[("A4", "VBUS", "passive"), ("A9", "VBUS", "passive"), ("B4", "VBUS", "passive"),
                ("B9", "VBUS", "passive"), None, ("A5", "CC1", "passive"), ("B5", "CC2", "passive"), None,
                ("A8", "SBU1", "passive"), ("B8", "SBU2", "passive")],
          right=[("A6", "D+", "passive"), ("B6", "D+", "passive"), ("A7", "D-", "passive"), ("B7", "D-", "passive"),
                 None, ("A1", "GND", "passive"), ("A12", "GND", "passive"), ("B1", "GND", "passive"),
                 ("B12", "GND", "passive"), ("S1", "SHIELD", "passive")], width=15.24)
USBLC6 = ic("RQ:USBLC6-2SC6", "U",
            left=[("1", "I/O1", "passive"), ("3", "I/O2", "passive"), ("2", "GND", "passive")],
            right=[("6", "I/O1", "passive"), ("4", "I/O2", "passive"), ("5", "VBUS", "passive")], width=10.16)
TPS22918 = ic("RQ:TPS22918", "U",
              left=[("1", "VIN", "power_in"), ("3", "ON", "input"), ("4", "CT", "passive")],
              right=[("6", "VOUT", "power_out"), ("5", "QOD", "passive")],
              bottom=[("2", "GND", "power_in")], width=12.7)
LDO = ic("RQ:AP7361C-33E", "U", left=[("1", "IN", "power_in")], right=[("3", "OUT", "power_out")],
         bottom=[("2", "GND", "power_in")], width=12.7)
BUF = ic("RQ:74AHCT1G125", "U", left=[("2", "A", "input"), ("1", "~{OE}", "input")], right=[("4", "Y", "output")],
         top=[("5", "VCC", "power_in")], bottom=[("3", "GND", "power_in")], width=10.16)
NMOS = ic("RQ:2N7002", "Q", left=[("1", "G", "input")], top=[("3", "D", "passive")],
          bottom=[("2", "S", "passive")], width=7.62)
JST6 = ic("RQ:Conn_ButtonBoard_6P", "J",
          left=[("1", "+5V", "passive"), ("2", "DIN", "passive"), ("3", "DOUT", "passive"), ("4", "GND", "passive"),
                ("5", "SW", "passive"), ("6", "GND", "passive")], width=7.62)
JST2 = ic("RQ:Conn_Microswitch_2P", "J", left=[("1", "SW", "passive"), ("2", "GND", "passive")], width=7.62)


def esp32_s3_wroom_1() -> SymbolDef:
    """
    Pin data (number, name, electrical type, position) taken verbatim from the official Espressif
    symbol (espressif/kicad-libraries, CC-BY-SA 4.0), re-serialised by our own writer: the upstream
    file uses KiCad 10 syntax that kiutils mis-parses (`show_name`, lost `hide`), which made KiCad 9
    reject the schematic.
    """
    from kiutils.symbol import SymbolLib

    lib = SymbolLib.from_file(ESP_LIB)
    s = next(x for x in lib.symbols if x.entryName == "ESP32-S3-WROOM-1")
    pins = []
    for u in s.units:
        for p in u.pins:
            name = p.name.split("/")[0] if p.name.startswith("GPIO") else p.name
            pins.append(Pin(p.number, name, p.electricalType, p.position.X, p.position.Y,
                            int(p.position.angle or 0), p.length))
    hw = max(abs(p.x) for p in pins if p.angle in (0, 180)) - 2.54
    hh = max(abs(p.y) for p in pins if p.angle in (90, 270)) - 2.54
    return SymbolDef("Espressif:ESP32-S3-WROOM-1", "U", pins, [rect(-hw, hh, hw, -hh)],
                     ref_at=(0, hh + 5.08), value_at=(0, -hh - 5.08), pin_name_offset=1.016)


# --------------------------------------------------------------------------- footprints & BOM data

FP = {
    "R0603": "Resistor_SMD:R_0603_1608Metric",
    "R1206": "Resistor_SMD:R_1206_3216Metric",
    "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric",
    "C1210": "Capacitor_SMD:C_1210_3225Metric",
    "USBC": "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    "F1812": "Fuse:Fuse_1812_4532Metric",
    "SMA": "Diode_SMD:D_SMA",
    "SOD323": "Diode_SMD:D_SOD-323",
    "SOD123": "Diode_SMD:D_SOD-123",
    "SOT23": "Package_TO_SOT_SMD:SOT-23",
    "SOT235": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT236": "Package_TO_SOT_SMD:SOT-23-6",
    "SOT223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "ESP": "Espressif:ESP32-S3-WROOM-1",
    "WS2812B": "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
    "TACT": "Button_Switch_SMD:SW_SPST_TL3342",
    "JST6": "Connector_JST:JST_PH_B6B-PH-K_1x06_P2.00mm_Vertical",
    "JST2": "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
    "TP": "TestPoint:TestPoint_Pad_D1.5mm",
    "BUZ": "RQ:Buzzer_MLT-8530 (create in Phase 6b)",
}


def res(ref, value, at, a, b, fp="R0603", note="", mpn="") -> Part:
    f = {"Description": f"Resistor {value} 1% {fp[1:]}" + (f" — {note}" if note else "")}
    if mpn:
        f["MPN"] = mpn
    return Part(ref, R, value, at, {"1": a, "2": b}, FP[fp], f)


def cap(ref, value, at, a, b, fp="C0603", spec="X7R 16V", note="") -> Part:
    return Part(ref, C, value, at, {"1": a, "2": b}, FP[fp],
                {"Description": f"Capacitor {value} {spec} {fp[1:]}" + (f" — {note}" if note else "")})


# --------------------------------------------------------------------------- placement


class Section:
    """Shelf packing of parts inside a rectangle, with room for net labels."""

    def __init__(self, sch: Schematic, title: str, x0: float, y0: float, width: float):
        self.sch, self.x0, self.y0, self.w = sch, x0, y0, width
        self.cx, self.cy, self.row_h = x0, y0 + 8.0, 0.0
        sch.text(x0, y0, title, 2.54)

    @staticmethod
    def _bbox(p: Part) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for pin in p.sym.pins:
            net = p.nets[pin.number]
            lab = 0.0 if net is None else (6.0 if net in POWER_NETS else 1.6 + 1.05 * len(net))
            px, py = pin.x, -pin.y
            ox, oy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[pin.angle]
            ex, ey = px + ox * (STUB + lab), py + oy * (STUB + lab)
            xs += [px, ex]
            ys += [py, ey]
        body = [abs(pin.x) - (pin.length if pin.angle in (0, 180) else 0) for pin in p.sym.pins]
        hw = max(body + [2.54])
        xs += [-hw, hw]
        ys += [-p.sym.ref_at[1] - 1.5, -p.sym.value_at[1] + 1.5]
        return min(xs), min(ys), max(xs), max(ys)

    def place(self, *parts: Part, newline: bool = False) -> None:
        if newline:
            self.newline()
        for p in parts:
            x1, y1, x2, y2 = self._bbox(p)
            w, h = x2 - x1, y2 - y1
            if self.cx + w > self.x0 + self.w and self.cx > self.x0:
                self.newline()
            p.at = (snap(self.cx - x1), snap(self.cy - y1))
            self.cx += w + 5.08
            self.row_h = max(self.row_h, h)
            self.sch.add(p)

    def newline(self) -> None:
        self.cx = self.x0
        self.cy += self.row_h + 5.08
        self.row_h = 0.0

    @property
    def bottom(self) -> float:
        return self.cy + self.row_h


# --------------------------------------------------------------------------- main board


def main_board() -> tuple[Schematic, list[Part]]:
    sch = Schematic("Routine Quest — Main board", "0.1", PROJECT, POWER_NETS, paper="A2")
    esp = esp32_s3_wroom_1()
    O = (0, 0)

    # ---------------- power: USB-C → PTC → TVS → load switch (soft start) → +5V → LDO → +3V3
    pw = Section(sch, "1. Τροφοδοσία: USB-C 5V → προστασία → soft-start → +5V → LDO → +3V3", 15, 15, 270)
    pw.place(
        Part("J1", USBC, "USB4105-GF-A", O,
             {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A5": "CC1", "B5": "CC2", "A8": None,
              "B8": None, "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN", "A1": "GND",
              "A12": "GND", "B1": "GND", "B12": "GND", "S1": "SHIELD"},
             FP["USBC"], {"MPN": "USB4105-GF-A", "Manufacturer": "GCT",
                          "Description": "USB-C receptacle USB 2.0, 16P, top mount (verify pad names in 6b)"}),
        Part("U2", USBLC6, "USBLC6-2SC6", O,
             {"1": "USB_DP", "6": "USB_DP", "3": "USB_DN", "4": "USB_DN", "2": "GND", "5": "VBUS_F"},
             FP["SOT236"], {"MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics",
                            "Description": "USB 2.0 ESD protection D+/D-"}),
        Part("U3", TPS22918, "TPS22918DBVR", O,
             {"1": "VBUS_F", "3": "LS_ON", "4": "LS_CT", "6": "+5V", "5": "+5V", "2": "GND"},
             FP["SOT236"], {"MPN": "TPS22918DBVR", "Manufacturer": "Texas Instruments",
                            "Description": "Load switch 5.5V 2A, slew control (inrush limit for USB)"}),
        Part("U4", LDO, "AP7361C-33E-13", O, {"1": "+5V", "3": "+3V3", "2": "GND"}, FP["SOT223"],
             {"MPN": "AP7361C-33E-13", "Manufacturer": "Diodes Inc.",
              "Description": "LDO 3.3V 1A SOT-223, pinout IN-GND(tab)-OUT. NOT the -33ER variant (reversed)"}),
    )
    pw.place(
        Part("F1", FUSE, "0.75A hold", O, {"1": "VBUS", "2": "VBUS_F"}, FP["F1812"],
             {"MPN": "MF-MSMF075-2", "Manufacturer": "Bourns",
              "Description": "PTC resettable fuse 0.75A hold / 1.5A trip, 1812 (verify)"}),
        Part("D1", D_TVS, "SMAJ5.0A", O, {"1": "VBUS_F", "2": "GND"}, FP["SMA"],
             {"MPN": "SMAJ5.0A", "Description": "TVS unidirectional 5V standoff, SMA (K = band → VBUS_F)"}),
        res("R1", "5.1k", O, "CC1", "GND", note="USB-C sink Rd"),
        res("R2", "5.1k", O, "CC2", "GND", note="USB-C sink Rd"),
        res("R3", "1M", O, "SHIELD", "GND", note="shield bleed"),
        cap("C1", "4.7nF", O, "SHIELD", "GND", spec="X7R 50V", note="shield EMI"),
        res("R4", "10k", O, "VBUS_F", "LS_ON", note="ON tied high, never floating"),
        cap("C2", "1nF", O, "LS_CT", "GND", spec="X7R 25V", note="load-switch slew (inrush)"),
        cap("C3", "1uF", O, "VBUS_F", "GND", spec="X7R 16V", note="U3 VIN"),
        cap("C4", "22uF", O, "+5V", "GND", fp="C0805", spec="X5R 10V", note="U3 VOUT / U4 IN"),
        cap("C5", "100uF", O, "+5V", "GND", fp="C1210", spec="X5R 6.3V", note="LED bulk"),
        cap("C6", "10uF", O, "+5V", "GND", fp="C0805", spec="X5R 10V", note="U4 IN"),
        cap("C7", "22uF", O, "+3V3", "GND", fp="C0805", spec="X5R 10V", note="U4 OUT"),
        cap("C8", "100nF", O, "+3V3", "GND", note="U4 OUT HF"),
        newline=True,
    )

    # ---------------- MCU
    mc = Section(sch, "2. MCU: ESP32-S3-WROOM-1-N8 (pin map = firmware/main/board.h)", 300, 15, 270)
    used = {"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN", "27": "IO0",
            "4": "BTN1", "5": "BTN2", "6": "BTN3", "7": "BTN4", "8": "BUZ_PWM", "31": "LED_DATA_3V3",
            "13": "USB_DN", "14": "USB_DP", "37": "U0TXD", "36": "U0RXD"}
    mc.place(Part("U1", esp, "ESP32-S3-WROOM-1-N8", O,
                  {p.number: used.get(p.number) for p in esp.pins}, FP["ESP"],
                  {"MPN": "ESP32-S3-WROOM-1-N8", "Manufacturer": "Espressif",
                   "Description": "Wi-Fi/BLE module, 8MB flash, no PSRAM, PCB antenna (keep-out!)"}))
    mc.place(
        cap("C9", "10uF", O, "+3V3", "GND", fp="C0805", spec="X5R 10V", note="U1 3V3 bulk"),
        cap("C10", "100nF", O, "+3V3", "GND", note="U1 3V3 HF"),
        res("R5", "10k", O, "+3V3", "EN", note="EN pull-up"),
        cap("C11", "1uF", O, "EN", "GND", note="EN RC delay (Espressif HW guide)"),
        Part("SW1", SW, "RESET", O, {"1": "EN", "2": "GND"}, FP["TACT"],
             {"MPN": "TL3342F160QG", "Manufacturer": "E-Switch", "Description": "Tactile, inside enclosure only"}),
        res("R6", "10k", O, "+3V3", "IO0", note="BOOT strap pull-up"),
        Part("SW2", SW, "BOOT", O, {"1": "IO0", "2": "GND"}, FP["TACT"],
             {"MPN": "TL3342F160QG", "Manufacturer": "E-Switch", "Description": "Tactile, inside enclosure only"}),
        newline=True,
    )
    tps = [("TP1", "U0TXD"), ("TP2", "U0RXD"), ("TP3", "EN"), ("TP4", "IO0"), ("TP5", "+3V3"), ("TP6", "+5V"),
           ("TP7", "GND"), ("TP8", "LED_CHAIN_END"), ("TP9", "USB_DP"), ("TP10", "USB_DN")]
    mc.place(*[Part(r, TP, n, O, {"1": n}, FP["TP"], {"Description": f"Test pad {n} (factory pogo)"})
               for r, n in tps], newline=True)

    # ---------------- buttons
    sch.flag_at = (snap(25), snap(pw.bottom + 6))
    bt = Section(sch, "3. Κουμπιά → button boards (JST-PH 6P): series R + pull-up + RC + TVS ανά είσοδο",
                 15, pw.bottom + 22, 270)
    led_in = {1: "LED_RING_OUT", 2: "LED_B1_RET", 3: "LED_B2_RET", 4: "LED_B3_RET"}
    led_out = {1: "LED_B1_RET", 2: "LED_B2_RET", 3: "LED_B3_RET", 4: "LED_CHAIN_END"}
    for n in range(1, 5):
        j = f"J{n + 1}"
        bt.place(
            Part(j, JST6, f"BTN{n}", O,
                 {"1": "+5V", "2": led_in[n], "3": led_out[n], "4": "GND", "5": f"BTN{n}_SW", "6": "GND"},
                 FP["JST6"], {"MPN": "B6B-PH-K-S(LF)(SN)", "Manufacturer": "JST",
                              "Description": f"Button board {n} (+5V, LED data in/out, switch)"}),
            Part(f"D{n + 1}", D_TVS_BI, "PESD5V0S1BA", O, {"1": f"BTN{n}_SW", "2": "GND"}, FP["SOD323"],
                 {"MPN": "PESD5V0S1BA,115", "Manufacturer": "Nexperia",
                  "Description": "ESD bidirectional 5V, on external switch wire"}),
            res(f"R{6 + n}", "1k", O, f"BTN{n}_SW", f"BTN{n}", note="series, limits ESD/injection current"),
            res(f"R{10 + n}", "10k", O, "+3V3", f"BTN{n}", note="pull-up (stronger than internal)"),
            cap(f"C{11 + n}", "10nF", O, f"BTN{n}", "GND", note="RC filter τ≈10µs, debounce in firmware"),
            newline=(n > 1),
        )

    # ---------------- buzzer
    sch.text(300, mc.bottom + 6, NOTES_MAIN, 1.27)
    bz = Section(sch, "4. Buzzer: magnetic transducer, low-side MOSFET, flyback", 300, mc.bottom + 40, 280)
    bz.place(
        Part("Q1", NMOS, "2N7002", O, {"1": "BUZ_G", "3": "BUZ_N", "2": "GND"}, FP["SOT23"],
             {"MPN": "2N7002", "Description": "N-MOSFET 60V 0.3A, logic level"}),
        Part("BZ1", BUZ, "MLT-8530", O, {"1": "BUZ_P", "2": "BUZ_N"}, FP["BUZ"],
             {"MPN": "MLT-8530", "Manufacturer": "Jiangsu Huaneng",
              "Description": "Magnetic buzzer, external drive, 2.7kHz 80dB, 8.5mm SMD (pin1 +)"}),
        Part("D6", D, "1N4148W", O, {"1": "BUZ_P", "2": "BUZ_N"}, FP["SOD123"],
             {"MPN": "1N4148W", "Description": "Flyback across coil (K → BUZ_P)"}),
        res("R15", "47R", O, "+5V", "BUZ_P", fp="R1206", note="coil current limit / volume; tune in Phase 7"),
        res("R16", "100R", O, "BUZ_PWM", "BUZ_G", note="gate series"),
        res("R17", "100k", O, "BUZ_G", "GND", note="gate pull-down: silent during boot"),
        newline=True,
    )

    # ---------------- LEDs
    ld = Section(sch, "5. LEDs: 3.3V→5V level shift, 12× WS2812B ring → button boards (data chain)",
                 300, bz.bottom + 12, 285)
    ld.place(
        Part("U5", BUF, "74AHCT1G125", O, {"2": "LED_DATA_3V3", "1": "GND", "4": "LED_DATA_5V", "5": "+5V",
                                           "3": "GND"}, FP["SOT235"],
             {"MPN": "SN74AHCT1G125DBVR", "Manufacturer": "Texas Instruments",
              "Description": "Buffer, TTL-level input at 5V: 3.3V → 5V for WS2812B (VIH 0.7·VDD)"}),
        cap("C16", "100nF", O, "+5V", "GND", note="U5 VCC"),
        res("R18", "100k", O, "LED_DATA_3V3", "GND", note="data low while GPIO38 floats at boot"),
        res("R19", "330R", O, "LED_DATA_5V", "LED_D0", note="series, damps ringing"),
    )
    for i in range(1, 13):
        din = "LED_D0" if i == 1 else f"LED_D{i - 1}"
        dout = "LED_RING_OUT" if i == 12 else f"LED_D{i}"
        ld.place(
            Part(f"LED{i}", WS2812B, "WS2812B", O, {"4": din, "2": dout, "1": "+5V", "3": "GND"}, FP["WS2812B"],
                 {"MPN": "WS2812B-B/W", "Manufacturer": "Worldsemi", "Description": f"Ring LED {i}/12"}),
            cap(f"C{16 + i}", "100nF", O, "+5V", "GND", note=f"LED{i} decoupling"),
            newline=(i == 1),
        )

    return sch, sch.parts


NOTES_MAIN = "\n".join([
    "Σημειώσεις σχεδίασης (docs/06-hardware.md):",
    "• Τροφοδοσία μόνο USB-C 5V. ΚΑΜΙΑ μπαταρία (ασφάλεια παιδιού).",
    "• Ρεύμα: ESP32-S3 Wi-Fi TX ≈ 350 mA peak + LEDs. Το firmware περιορίζει το συνολικό ρεύμα LED",
    "  ώστε όλη η συσκευή να μένει ≤ 500 mA (USB 2.0 default). F1 0.75 A hold.",
    "• U3 soft-start: περιορίζει το inrush των C4+C5 (USB: ≤ 10 µF στο attach χωρίς έλεγχο).",
    "• Antenna keep-out του U1: χωρίς χαλκό/εξαρτήματα κάτω από την κεραία (Φάση 6b).",
    "• Strapping: IO0 pull-up (R6), IO3/IO45/IO46 ασύνδετα (default). IO19/20 = native USB (flash + console).",
])


# --------------------------------------------------------------------------- button board


def button_board() -> Schematic:
    sch = Schematic("Routine Quest — Button board (×4)", "0.1", PROJECT, {"+5V", "GND"}, paper="A4")
    s = Section(sch, "Button board: WS2812B κάτω από το arcade κουμπί + καλώδια microswitch", 15, 15, 260)
    s.place(
        Part("J1", JST6, "TO_MAIN", (0, 0),
             {"1": "+5V", "2": "DIN", "3": "DOUT", "4": "GND", "5": "SW", "6": "GND"}, FP["JST6"],
             {"MPN": "B6B-PH-K-S(LF)(SN)", "Manufacturer": "JST",
              "Description": "To main board (6-wire harness, same pinout both ends)"}),
        res("R1", "330R", (0, 0), "DIN", "DIN_R", note="series at input (cable)"),
        Part("LED1", WS2812B, "WS2812B", (0, 0), {"4": "DIN_R", "2": "DOUT", "1": "+5V", "3": "GND"},
             FP["WS2812B"], {"MPN": "WS2812B-B/W", "Manufacturer": "Worldsemi",
                             "Description": "Button LED, under translucent arcade button"}),
        cap("C1", "100nF", (0, 0), "+5V", "GND", note="LED1 decoupling"),
        cap("C2", "10uF", (0, 0), "+5V", "GND", fp="C0805", spec="X5R 10V", note="local bulk (cable inductance)"),
        Part("J2", JST2, "MICROSWITCH", (0, 0), {"1": "SW", "2": "GND"}, FP["JST2"],
             {"MPN": "B2B-PH-K-S(LF)(SN)", "Manufacturer": "JST",
              "Description": "To arcade microswitch (spade harness), NO contact"}),
    )
    return sch


# --------------------------------------------------------------------------- outputs


def write_bom(parts: list[Part], path: str, board: str) -> None:
    groups: dict[tuple, list[str]] = {}
    descs: dict[tuple, str] = {}
    for p in parts:
        if not p.sym.in_bom:
            continue
        # group identical parts; per-instance notes ("LED3/12", "BTN2") don't split a BOM line
        value = p.value if p.sym.lib_id not in ("RQ:Conn_ButtonBoard_6P",) else "B6B-PH-K-S"
        key = (value, p.footprint, p.fields.get("MPN", ""), p.fields.get("Manufacturer", ""))
        groups.setdefault(key, []).append(p.ref)
        descs.setdefault(key, p.fields.get("Description", "").split(" — ")[0])

    def refkey(r: str):
        import re

        m = re.match(r"([A-Z]+)(\d+)", r)
        return (m.group(1), int(m.group(2))) if m else (r, 0)

    rows = sorted(groups.items(), key=lambda kv: refkey(sorted(kv[1], key=refkey)[0]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Board", "Qty", "References", "Value", "Description", "Manufacturer", "MPN", "Footprint"])
        for k, refs in rows:
            value, fp, mpn, mfr = k
            desc = descs[k].replace("Ring LED 1/12", "RGB LED, ring").replace("Button board 1", "Button board connector")
            refs = sorted(refs, key=refkey)
            w.writerow([board, len(refs), " ".join(refs), value, desc, mfr, mpn, fp])


def write_netlist(sch: Schematic, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: sorted(v) for k, v in sorted(sch.netlist().items())}, f, indent=1, ensure_ascii=False)


def main() -> None:
    out = HW
    main_sch, parts = main_board()
    main_sch.write(os.path.join(out, "routine-quest.kicad_sch"))
    write_netlist(main_sch, os.path.join(out, "build", "main.netlist.json"))
    write_bom(parts, os.path.join(out, "bom", "main-board.csv"), "main")

    bb = button_board()
    bb.write(os.path.join(out, "button-board", "button-board.kicad_sch"))
    write_netlist(bb, os.path.join(out, "build", "button-board.netlist.json"))
    write_bom(bb.parts, os.path.join(out, "bom", "button-board.csv"), "button (x4)")
    print(f"main: {len(parts)} parts, {len(main_sch.netlist())} nets | button board: {len(bb.parts)} parts")


if __name__ == "__main__":
    os.makedirs(os.path.join(HW, "build"), exist_ok=True)
    os.makedirs(os.path.join(HW, "bom"), exist_ok=True)
    main()
