"""
Independent checks for the routed boards (CI gate before fabrication outputs).

    python3 hardware/tools/check_pcb.py

1. Netlist: every pad's net on the board == the net of that pin in the reviewed schematic data
   (gen_schematics.py), and every schematic part is on the board with the same footprint.
2. KiCad DRC (pcbnew engine): 0 errors and 0 unconnected items. Warnings are reported; library-path
   warnings (no global fp-lib-table in headless CI) are ignored.
3. Board-specific rules: outline size, antenna clearance (no copper/vias/footprints of other parts under
   or beside the antenna), USB-C at the board edge, ESP32 antenna at the board edge.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import gen_schematics as gs  # noqa: E402
from route_pcb import summarize, tracks  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
IGNORED_WARNINGS = {"lib_footprint_issues", "lib_footprint_mismatch"}


def mm(v: int) -> float:
    return pcbnew.ToMM(v)


def check_netlist(board: pcbnew.BOARD, parts: list) -> list[str]:
    errs = []
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for p in parts:
        fp = fps.get(p.ref)
        if fp is None:
            errs.append(f"{p.ref}: missing on board")
            continue
        fpid = f"{fp.GetFPID().GetLibNickname()}:{fp.GetFPID().GetLibItemName()}"
        if fpid != p.footprint:
            errs.append(f"{p.ref}: footprint {fpid} != schematic {p.footprint}")
        for pad in fp.Pads():
            num = pad.GetNumber()
            if num == "":
                continue  # NPTH / mechanical
            want = p.nets.get(num)
            got = pad.GetNetname() or None
            if want != got:
                errs.append(f"{p.ref}.{num}: board net {got!r} != schematic {want!r}")
    extra = set(fps) - {p.ref for p in parts}
    for ref in sorted(extra):
        if not fps[ref].IsBoardOnly():
            errs.append(f"{ref}: on board but not in schematic (and not board-only)")
    return errs


def check_drc(board_path: str) -> tuple[list[str], dict[str, int]]:
    b = pcbnew.LoadBoard(board_path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    with tempfile.TemporaryDirectory() as tmp:
        rpt = os.path.join(tmp, "drc.rpt")
        pcbnew.WriteDRCReport(b, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
        counts = summarize(rpt)
    errs = [f"DRC {k}: {v}" for k, v in counts.items() if k.endswith(":error") and v]
    if counts.get("unconnected", -1) != 0:
        errs.append(f"DRC unconnected items: {counts.get('unconnected')}")
    warns = {k: v for k, v in counts.items() if k.endswith(":warning") and k.split(":")[0] not in IGNORED_WARNINGS}
    return errs, warns


def outline_size(board: pcbnew.BOARD) -> tuple[float, float]:
    bb = board.GetBoardEdgesBoundingBox()
    return round(mm(bb.GetWidth()), 2), round(mm(bb.GetHeight()), 2)


def check_main(board: pcbnew.BOARD) -> list[str]:
    errs = []
    w, h = outline_size(board)
    if (w, h) != (100.0, 100.0):
        errs.append(f"main outline {w}×{h} mm, expected 100×100")
    edges = board.GetBoardEdgesBoundingBox()
    u1 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U1")
    # Antenna end of the module (footprint y = -15.75 mm) must be at the top board edge, not inside
    ant_y = u1.GetPosition().y - pcbnew.FromMM(15.75)
    if abs(mm(ant_y - edges.GetTop())) > 0.5:
        errs.append(f"U1 antenna end is {mm(ant_y - edges.GetTop()):.2f} mm from the top edge (want ≤ 0.5)")
    # Nothing conductive in the antenna clearance box (module width + 11 mm each side, 6.5 mm deep)
    x0, x1 = u1.GetPosition().x - pcbnew.FromMM(20), u1.GetPosition().x + pcbnew.FromMM(20)
    y0, y1 = edges.GetTop(), edges.GetTop() + pcbnew.FromMM(6.5)

    def inside(pt) -> bool:
        return x0 <= pt.x <= x1 and y0 <= pt.y <= y1

    for t in tracks(board):
        pts = [t.GetPosition()] if isinstance(t, pcbnew.PCB_VIA) else [t.GetStart(), t.GetEnd()]
        if any(inside(p) for p in pts):
            errs.append(f"track/via of {t.GetNetname()} in the antenna clearance at {[mm(p.x) for p in pts]}")
    for fp in board.GetFootprints():
        if fp.GetReference() == "U1":
            continue
        for pad in fp.Pads():
            if inside(pad.GetPosition()):
                errs.append(f"{fp.GetReference()}.{pad.GetNumber()} in the antenna clearance")
    # USB-C: receptacle mouth at the left edge
    j1 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "J1")
    if abs(mm(j1.GetPosition().x - edges.GetLeft()) - 3.1) > 0.3:
        errs.append("J1 (USB-C) is not at the board edge")
    return errs


def run() -> int:
    failures = 0
    _, main_parts = gs.main_board()
    btn_parts = gs.button_board().parts
    for name, path, parts, extra in [
        ("main", os.path.join(HW, "routine-quest.kicad_pcb"), main_parts, check_main),
        ("button", os.path.join(HW, "button-board", "button-board.kicad_pcb"), btn_parts, None),
    ]:
        board = pcbnew.LoadBoard(path)
        errs = check_netlist(board, parts)
        if extra:
            errs += extra(board)
        drc_errs, warns = check_drc(path)
        errs += drc_errs
        w, h = outline_size(board)
        status = "OK" if not errs else f"{len(errs)} problem(s)"
        nvias = sum(isinstance(t, pcbnew.PCB_VIA) for t in tracks(board))
        print(f"{name}: {w}×{h} mm, {len(board.GetFootprints())} footprints, {nvias} vias → {status}")
        if warns:
            print(f"   warnings: {warns}")
        for e in errs:
            print("   ✗", e)
        failures += len(errs)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
