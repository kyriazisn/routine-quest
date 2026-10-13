"""
Generate the Routine Quest PCBs (placement, outline, net classes, zones) from the reviewed schematic data.

    python3 hardware/tools/gen_pcb.py        # → *.kicad_pcb (placed, unrouted) + project design rules
    python3 hardware/tools/route_pcb.py      # → Freerouting + zone fill + DRC
    python3 hardware/tools/check_pcb.py      # independent checks (nets == schematic, DRC, keep-outs)

Runs with KiCad's Python (pcbnew, KiCad ≥ 7). Parts and nets come from gen_schematics.py, the single
source of truth, so the board can never silently diverge from the approved schematic.
Layout rationale: docs/06b-pcb.md.
"""

from __future__ import annotations

import json
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import gen_schematics as gs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
STD_FP = os.environ.get("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
PROJECT_LIBS = {"RQ": os.path.join(HW, "lib", "RQ.pretty"), "Espressif": os.path.join(HW, "lib", "Espressif.pretty")}

# Board origin on the KiCad sheet (purely cosmetic: keeps the board inside an A4 frame)
OX, OY = 50.0, 40.0

# ------------------------------------------------------------------ design rules (JLCPCB 2-layer, with margin)

RULES = {
    "min_clearance": 0.2,
    "min_track_width": 0.2,
    "min_via_diameter": 0.6,
    "min_through_hole_diameter": 0.3,
    "min_via_annular_width": 0.15,
    "min_copper_edge_clearance": 0.3,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_silk_clearance": 0.0,
    "min_text_height": 0.8,
    "min_text_thickness": 0.12,
}
NETCLASSES = [
    # name, track, clearance, via dia, via drill, nets
    ("Default", 0.25, 0.2, 0.6, 0.3, []),
    ("Power", 0.8, 0.2, 0.8, 0.4, ["VBUS", "VBUS_F", "+5V"]),
    ("3V3", 0.5, 0.2, 0.6, 0.3, ["+3V3"]),
    ("GND", 0.5, 0.2, 0.6, 0.3, ["GND"]),
    ("Buzzer", 0.4, 0.2, 0.6, 0.3, ["BUZ_P", "BUZ_N"]),
    ("USB", 0.3, 0.2, 0.6, 0.3, ["USB_DP", "USB_DN"]),
]


def write_project(pro_path: str) -> None:
    """Merge net classes and design rules into the KiCad project file (keeps any other settings)."""
    data = json.load(open(pro_path)) if os.path.exists(pro_path) else {"meta": {"version": 1}}
    data.setdefault("meta", {})["filename"] = os.path.basename(pro_path)
    classes = []
    for name, track, clr, vdia, vdrill, _ in NETCLASSES:
        classes.append({
            "name": name, "track_width": track, "clearance": clr, "via_diameter": vdia, "via_drill": vdrill,
            "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "microvia_diameter": 0.3,
            "microvia_drill": 0.1, "bus_width": 12, "wire_width": 6, "line_style": 0,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
        })
    data["net_settings"] = {
        "classes": classes, "meta": {"version": 3}, "net_colors": None, "netclass_assignments": None,
        "netclass_patterns": [{"netclass": name, "pattern": net} for name, *_, nets in NETCLASSES for net in nets],
    }
    ds = data.setdefault("board", {}).setdefault("design_settings", {})
    ds.setdefault("rules", {}).update(RULES)
    ds["track_widths"] = [0.0, 0.25, 0.3, 0.4, 0.5, 0.8]
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.6, "drill": 0.3},
                            {"diameter": 0.8, "drill": 0.4}]
    with open(pro_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


# ------------------------------------------------------------------ helpers


def P(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(x + OX, y + OY)


def load_fp(fpid: str) -> pcbnew.FOOTPRINT:
    lib, name = fpid.split(":", 1)
    path = PROJECT_LIBS.get(lib, os.path.join(STD_FP, f"{lib}.pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise FileNotFoundError(f"footprint {fpid} not found in {path}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


class Board:
    def __init__(self, path: str, parts: list, w: float, h: float, corner_r: float = 2.0):
        self.path = path
        self.board = pcbnew.NewBoard(path)
        self.parts = {p.ref: p for p in parts}
        self.fps: dict[str, pcbnew.FOOTPRINT] = {}
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}
        self.w, self.h = w, h
        self.board.SetCopperLayerCount(2)
        self._outline(w, h, corner_r)
        for p in parts:
            for n in p.nets.values():
                if n and n not in self.nets:
                    ni = pcbnew.NETINFO_ITEM(self.board, n)
                    self.board.Add(ni)
                    self.nets[n] = ni

    # -- outline
    def _seg(self, a, b, layer=pcbnew.Edge_Cuts, width=0.1):
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a))
        s.SetEnd(P(*b))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width))
        self.board.Add(s)

    def _arc(self, center, start, end, layer=pcbnew.Edge_Cuts, width=0.1):
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetCenter(P(*center))
        s.SetStart(P(*start))
        s.SetEnd(P(*end))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width))
        self.board.Add(s)

    def _outline(self, w, h, r):
        self._seg((r, 0), (w - r, 0))
        self._seg((w, r), (w, h - r))
        self._seg((w - r, h), (r, h))
        self._seg((0, h - r), (0, r))
        # arcs: start → end clockwise on screen (y down)
        self._arc((w - r, r), (w - r, 0), (w, r))
        self._arc((w - r, h - r), (w, h - r), (w - r, h))
        self._arc((r, h - r), (r, h), (0, h - r))
        self._arc((r, r), (0, r), (r, 0))

    # -- parts
    def place(self, ref: str, x: float, y: float, rot: float = 0.0, back: bool = False, center_pads=False):
        part = self.parts[ref]
        fp = load_fp(part.footprint)
        fp.SetReference(ref)
        fp.SetValue(part.value)
        self.board.Add(fp)  # must be on a board before Flip()
        fp.SetPosition(P(0, 0))
        fp.SetOrientationDegrees(rot)
        if back:
            fp.Flip(fp.GetPosition(), False)
        if center_pads:  # place so that the pads' bounding-box centre lands on (x, y)
            bb = None
            for pad in fp.Pads():
                pb = pad.GetBoundingBox()
                if bb is None:
                    bb = pb
                else:
                    bb.Merge(pb)
            c = bb.GetCenter()
            fp.Move(pcbnew.VECTOR2I(P(x, y).x - c.x, P(x, y).y - c.y))
        else:
            fp.SetPosition(P(x, y))
        for k, v in part.fields.items():
            if k in ("MPN", "Manufacturer", "Description"):
                fp.SetField(k, v) if hasattr(fp, "SetField") else fp.SetProperty(k, v)
        pins = {k: v for k, v in part.nets.items()}
        pad_numbers = {pad.GetNumber() for pad in fp.Pads()}
        missing = set(pins) - pad_numbers
        if missing:
            raise ValueError(f"{ref}: schematic pins {sorted(missing)} have no pad in {part.footprint}")
        for pad in fp.Pads():
            net = pins.get(pad.GetNumber())
            if net:
                pad.SetNet(self.nets[net])
        self.fps[ref] = fp
        return fp

    def hole(self, ref: str, x: float, y: float, fpid="MountingHole:MountingHole_3.2mm_M3"):
        fp = load_fp(fpid)
        fp.SetReference(ref)
        fp.SetValue("MountingHole")
        fp.SetPosition(P(x, y))
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        self.board.Add(fp)
        return fp

    def via(self, x: float, y: float, net: str, dia=0.6, drill=0.3):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(P(x, y))
        v.SetWidth(pcbnew.FromMM(dia))
        v.SetDrill(pcbnew.FromMM(drill))
        v.SetNet(self.nets[net])
        v.SetIsFree(False)
        v.SetLocked(True)  # fixed (thermal/stitching): kept by the router
        self.board.Add(v)

    def text(self, s: str, x: float, y: float, size=1.0, layer=pcbnew.F_SilkS, rot=0.0):
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(s)
        t.SetPosition(P(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I_MM(size, size))
        t.SetTextThickness(pcbnew.FromMM(size * 0.15))
        t.SetTextAngleDegrees(rot)
        if layer in (pcbnew.B_SilkS, pcbnew.B_Cu):
            t.SetMirrored(True)
        self.board.Add(t)

    def zone(self, net: str | None, layer: int, pts, rule_area=False, name="", priority=0, clearance=0.3):
        z = pcbnew.ZONE(self.board)
        if rule_area:
            z.SetIsRuleArea(True)
            z.SetDoNotAllowCopperPour(True)
            z.SetDoNotAllowTracks(True)
            z.SetDoNotAllowVias(True)
            z.SetDoNotAllowPads(False)
            z.SetDoNotAllowFootprints(False)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            ls.AddLayer(pcbnew.B_Cu)
            z.SetLayerSet(ls)
        else:
            z.SetLayer(layer)
            z.SetNet(self.nets[net])
            z.SetLocalClearance(pcbnew.FromMM(clearance))
            z.SetMinThickness(pcbnew.FromMM(0.25))
            z.SetThermalReliefGap(pcbnew.FromMM(0.3))
            z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
            z.SetAssignedPriority(priority)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(P(x, y).x, P(x, y).y)
        self.board.Add(z)
        return z

    def gnd_pours(self, margin=0.5):
        pts = [(margin, margin), (self.w - margin, margin), (self.w - margin, self.h - margin),
               (margin, self.h - margin)]
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            self.zone("GND", layer, pts, name="GND")

    def stitch_gnd(self, skip: tuple[str, ...] = (), via_d: float = 0.6, clearance: float = 0.3) -> int:
        """
        Drop a GND via next to every GND pad on the top layer so the pads reach the bottom GND pour
        directly (GND is not autorouted). Candidate spots are tried around the pad; a spot is accepted only
        if it keeps `clearance` to every other-net pad, existing via and the board edge, and lies outside
        rule areas (antenna).
        """
        r = via_d / 2
        other_pads = []
        for fp in self.fps.values():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                other_pads.append((pad.GetNetname(), pcbnew.ToMM(bb.GetLeft()) - OX, pcbnew.ToMM(bb.GetTop()) - OY,
                                   pcbnew.ToMM(bb.GetRight()) - OX, pcbnew.ToMM(bb.GetBottom()) - OY))
        for fp in self.board.GetFootprints():
            if fp.GetReference().startswith("H"):
                c = fp.GetPosition()
                x, y = pcbnew.ToMM(c.x) - OX, pcbnew.ToMM(c.y) - OY
                other_pads.append(("<hole>", x - 3.6, y - 3.6, x + 3.6, y + 3.6))
        keepouts = []
        for z in self.board.Zones():
            if z.GetIsRuleArea():
                bb = z.GetBoundingBox()
                keepouts.append((pcbnew.ToMM(bb.GetLeft()) - OX, pcbnew.ToMM(bb.GetTop()) - OY,
                                 pcbnew.ToMM(bb.GetRight()) - OX, pcbnew.ToMM(bb.GetBottom()) - OY))
        vias = [(pcbnew.ToMM(v.GetPosition().x) - OX, pcbnew.ToMM(v.GetPosition().y) - OY)
                for v in self.board.Tracks() if isinstance(v, pcbnew.PCB_VIA)] if self.board.Tracks().size() else []

        def free(x, y, own_bb) -> bool:
            if not (r + 0.5 <= x <= self.w - r - 0.5 and r + 0.5 <= y <= self.h - r - 0.5):
                return False
            for k in keepouts:
                if k[0] - r - 0.2 <= x <= k[2] + r + 0.2 and k[1] - r - 0.2 <= y <= k[3] + r + 0.2:
                    return False
            for net, x0, y0, x1, y1 in other_pads:
                if (x0, y0, x1, y1) == own_bb:
                    continue
                gap = clearance if net != "GND" else 0.15
                dx = max(x0 - x, 0, x - x1)
                dy = max(y0 - y, 0, y - y1)
                if math.hypot(dx, dy) < r + gap:
                    return False
            return all(math.hypot(x - vx, y - vy) >= via_d + 0.3 for vx, vy in vias)

        added = 0
        for ref in sorted(self.fps):
            if ref in skip:
                continue
            for pad in self.fps[ref].Pads():
                if pad.GetNetname() != "GND" or not pad.IsOnLayer(pcbnew.F_Cu) or pad.HasHole():
                    continue
                bb = pad.GetBoundingBox()
                own = (pcbnew.ToMM(bb.GetLeft()) - OX, pcbnew.ToMM(bb.GetTop()) - OY,
                       pcbnew.ToMM(bb.GetRight()) - OX, pcbnew.ToMM(bb.GetBottom()) - OY)
                cx, cy = (own[0] + own[2]) / 2, (own[1] + own[3]) / 2
                hw, hh = (own[2] - own[0]) / 2, (own[3] - own[1]) / 2
                placed = False
                for dist in (0.35, 0.6, 1.0, 1.5):
                    for ang in range(0, 360, 30):
                        a = math.radians(ang)
                        x = cx + math.cos(a) * (hw + r + dist)
                        y = cy + math.sin(a) * (hh + r + dist)
                        if free(x, y, own):
                            self.via(x, y, "GND", via_d, 0.3)
                            vias.append((x, y))
                            added += 1
                            placed = True
                            break
                    if placed:
                        break
                if not placed:
                    print(f"   note: no stitching via spot next to {ref}.{pad.GetNumber()} (pour must connect it)")
        return added

    def save(self):
        unplaced = set(self.parts) - set(self.fps)
        if unplaced:
            raise ValueError(f"unplaced parts: {sorted(unplaced)}")
        pcbnew.SaveBoard(self.path, self.board)


# ------------------------------------------------------------------ main board (100 × 100 mm, 2 layers)

MAIN_W = MAIN_H = 100.0
RING_C = (50.0, 62.0)
RING_R = 26.0


def ring_pos(i: int, r: float = RING_R) -> tuple[float, float, float]:
    """LED i (1..12): starts at upper right (-60°) and runs clockwise, ending at the top (data chain order)."""
    th = -60.0 + (i - 1) * 30.0
    t = math.radians(th)
    return RING_C[0] + r * math.cos(t), RING_C[1] + r * math.sin(t), th


def main_board() -> Board:
    _, parts = gs.main_board()
    b = Board(os.path.join(HW, "routine-quest.kicad_pcb"), parts, MAIN_W, MAIN_H)

    # Mounting holes (M3) in the corners
    for i, (x, y) in enumerate([(4, 4), (96, 4), (96, 96), (4, 96)], 1):
        b.hole(f"H{i}", x, y)

    # MCU: antenna at the top edge, flush with the board edge (Espressif HW design guide, option 1)
    b.place("U1", 50, 15.75, 0)
    # Board-level antenna clearance (beyond the footprint keep-out): no copper/tracks/vias near the antenna
    b.zone(None, 0, [(30, 0), (70, 0), (70, 6.5), (30, 6.5)], rule_area=True, name="antenna clearance")
    b.place("C9", 35.5, 9.0, 90)        # 3V3 bulk at pin 2
    b.place("C10", 38.2, 9.0, 90)       # 3V3 HF at pin 2
    b.place("R5", 37.2, 12.6, 0)        # EN pull-up
    b.place("C11", 37.2, 14.6, 0)       # EN RC
    b.place("SW1", 33.0, 21.0, 0)       # RESET
    b.place("R6", 62.5, 24.0, 0)        # IO0 pull-up (pin 27)
    b.place("SW2", 70.5, 20.0, 0)       # BOOT

    # USB-C on the left edge, mouth facing out (footprint "PCB Edge" mark at +3.1 mm)
    j1 = b.place("J1", 3.1, 62.0, 270)
    for pad in j1.Pads():  # fine-pitch GND/shield pads: solid zone connection (no starved thermals)
        if pad.GetNetname() in ("GND", "SHIELD"):
            pad.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.place("U2", 11.8, 62.0, 90)       # ESD right behind the connector
    b.place("R1", 11.8, 57.5, 0)        # CC1 Rd
    b.place("R2", 11.8, 66.5, 0)        # CC2 Rd
    b.place("R3", 9.0, 72.5, 90)        # shield bleed
    b.place("C1", 11.0, 72.5, 90)       # shield EMI
    b.place("F1", 16.5, 52.0, 90)       # PTC
    b.place("D1", 16.5, 45.5, 0)        # TVS
    b.place("C3", 20.5, 56.0, 90)       # VBUS_F decoupling (also at U3 VIN side)

    # Inside the ring: load switch + LDO (copper area for U4's tab, docs/06 §2)
    b.place("U3", 35.0, 60.0, 0)
    b.place("C2", 35.0, 55.3, 0)        # CT slew
    b.place("R4", 35.0, 64.7, 0)        # ON pull-up
    b.place("C4", 40.0, 56.5, 90)       # +5V 22uF
    b.place("C5", 40.5, 67.5, 90)       # +5V 100uF (1210)
    b.place("U4", 50.0, 62.0, 0)        # LDO, tab (GND) to the right
    b.place("C6", 44.5, 56.0, 90)       # U4 IN
    b.place("C7", 44.5, 68.5, 90)       # U4 OUT 22uF
    b.place("C8", 47.0, 70.5, 0)        # U4 OUT 100nF
    for dx, dy in [(0, -2.5), (0, 0), (0, 2.5), (2.0, -1.25), (2.0, 1.25)]:  # thermal vias under the tab
        b.via(53.15 + 2.6 + dx, 62.0 + dy, "GND")

    # LED driver: level shifter next to IO38 (pin 31) and LED1
    b.place("R18", 62.5, 19.0, 0)       # IO38 pull-down
    b.place("U5", 64.5, 29.0, 0)
    b.place("C16", 68.5, 29.0, 90)
    b.place("R19", 64.5, 32.8, 0)       # series 330R to LED1

    # 12-LED ring, decoupling cap just inside each LED
    for i in range(1, 13):
        x, y, th = ring_pos(i)
        b.place(f"LED{i}", x, y, -th)
        cx, cy, _ = ring_pos(i, RING_R - 5.6)
        b.place(f"C{16 + i}", cx, cy, -th + 90)
        b.text(str(i), *ring_pos(i, RING_R + 4.2)[:2], size=0.8)

    # Button connectors in the corners (harness to the 4 button boards), each with its protection chain
    jst = {2: (20.0, 5.5, 12.0), 3: (80.0, 5.5, 12.0), 4: (80.0, 94.5, 88.0), 5: (20.0, 94.5, 88.0)}
    for n in range(1, 5):
        jx, jy, py = jst[n + 1]
        b.place(f"J{n + 1}", jx, jy, 0, center_pads=True)
        b.text(f"BTN{n}", jx + 9.0, jy, size=1.0, rot=90)
        x0 = jx - 5.5
        b.place(f"D{n + 1}", x0, py, 0)           # TVS at the connector side
        b.place(f"R{6 + n}", x0 + 3.6, py, 0)     # 1k series
        b.place(f"R{10 + n}", x0 + 7.2, py, 0)    # 10k pull-up
        b.place(f"C{11 + n}", x0 + 10.8, py, 0)   # 10nF

    # Buzzer (left, near IO15 / pin 8) with its driver
    b.place("BZ1", 13.0, 31.0, 0)
    b.place("Q1", 22.0, 30.0, 0)
    b.place("D6", 22.0, 35.0, 0)
    b.place("R15", 13.0, 39.5, 0)       # 1206: value set by dB measurement in Phase 7
    b.place("R16", 25.5, 25.5, 0)
    b.place("R17", 25.5, 27.5, 0)

    # Factory test pads on the bottom side (pogo fixture), 3 mm pitch column on the right
    for k, ref in enumerate([f"TP{i}" for i in range(1, 11)]):
        b.place(ref, 91.0, 32.0 + 3.6 * k, 0, back=True)
        b.text(ref, 87.0, 32.0 + 3.6 * k, size=0.8, layer=pcbnew.B_SilkS)

    b.text("ROUTINE QUEST main v0.1", 50, 97.0, size=1.2)
    b.text("USB-C 5V", 9.5, 78.0, size=0.8)
    b.gnd_pours()
    print(f"   {b.stitch_gnd(skip=('U1',))} GND stitching vias (U1 has its own via array below)")
    # ESP32 exposed pad (41, 3×3 segments at 1.4 mm pitch): vias in the 4 gaps between segments, not in the
    # pads (no solder wicking), to the bottom pour.
    for gx in (-2.2, -0.8):
        for gy in (-1.24, 0.16):
            b.via(50 + gx, 15.75 + gy, "GND", 0.6, 0.3)
    return b


# ------------------------------------------------------------------ button board (24 × 24 mm, ×4)

BTN_W = BTN_H = 24.0


def button_board() -> Board:
    bb = gs.button_board()
    b = Board(os.path.join(HW, "button-board", "button-board.kicad_pcb"), bb.parts, BTN_W, BTN_H)
    c = BTN_W / 2
    b.hole("H1", 3.0, c, "MountingHole:MountingHole_2.2mm_M2")
    b.hole("H2", BTN_W - 3.0, c, "MountingHole:MountingHole_2.2mm_M2")
    b.place("LED1", c, c, 0)                       # centred under the button
    b.place("C1", c, c + 4.6, 0)
    b.place("R1", c - 4.6, c - 4.2, 0)
    b.place("C2", c + 4.6, c - 4.2, 0)
    # THT connectors from the back so the top stays flat for the button / diffuser
    b.place("J1", c, BTN_H - 3.6, 0, back=True, center_pads=True)
    b.place("J2", c, 3.4, 0, back=True, center_pads=True)
    b.text("RQ BTN v0.1", c, 7.2, size=0.8, layer=pcbnew.B_SilkS)
    b.text("MAIN", c, BTN_H - 7.2, size=0.8, layer=pcbnew.B_SilkS)
    b.gnd_pours()
    b.stitch_gnd()
    return b


DRU_MAIN = """(version 1)
# GCT USB4105 land pattern (manufacturer datasheet): NPTH locating pegs sit 0.19 mm from the GND/VBUS pads.
(rule "USB-C land pattern"
  (condition "A.intersectsCourtyard('J1') && B.intersectsCourtyard('J1')")
  (constraint hole_clearance (min 0.15mm)))
"""


def main() -> None:
    with open(os.path.join(HW, "routine-quest.kicad_dru"), "w", encoding="utf-8") as f:
        f.write(DRU_MAIN)
    write_project(os.path.join(HW, "routine-quest.kicad_pro"))
    write_project(os.path.join(HW, "button-board", "button-board.kicad_pro"))
    for make in (main_board, button_board):
        b = make()
        b.save()
        print(f"{os.path.relpath(b.path, HW)}: {len(b.fps)} footprints, {len(b.nets)} nets (unrouted)")


if __name__ == "__main__":
    main()
