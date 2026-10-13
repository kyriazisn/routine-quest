"""
Autoroute the placed boards with Freerouting, then pour GND and run KiCad's DRC.

    python3 hardware/tools/route_pcb.py [main|button|all]

Flow per board:
  1. export Specctra DSN *without* copper zones (Freerouting would treat a GND pour on a signal layer as an
     obstacle), keeping rule areas (antenna keep-out) and net-class widths/clearances;
  2. Freerouting (headless, single thread → reproducible for a given version and input);
  3. read the SES back with our own parser (KiCad 7's ImportSpecctraSES only works inside the GUI editor);
  4. fill the GND zones on both layers, save, write the DRC report next to the board (build/).

Needs: KiCad ≥ 7 Python (pcbnew), Java ≥ 17, xvfb-run (1.9.0 needs a display even in CLI mode), FREEROUTING_JAR (Freerouting 1.9.0,
sha256 9084a4888937a7f31f857ecc12aa7a37407f51160e4d2892dff9c9bb47ae3102).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
JAR = os.environ.get("FREEROUTING_JAR", "/root/tools/freerouting-1.9.0.jar")
BOARDS = {
    "main": os.path.join(HW, "routine-quest.kicad_pcb"),
    "button": os.path.join(HW, "button-board", "button-board.kicad_pcb"),
}

# ------------------------------------------------------------------ minimal s-expression reader


def sexp(text: str):
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tokens:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def tracks(b) -> list:
    """BOARD.GetTracks() raises on an empty track list with KiCad 7 SWIG + Python 3.13."""
    try:
        return list(b.Tracks())
    except TypeError:
        return []


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


# ------------------------------------------------------------------ steps


def strip_blocks(text: str, head: str) -> str:
    """Remove every balanced s-expression that starts with `head` (e.g. "(plane ")."""
    out, i = [], 0
    while (j := text.find(head, i)) >= 0:
        out.append(text[i:j])
        depth, k = 0, j
        while True:
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 1
    out.append(text[i:])
    return "".join(out)


def require_unrouted(pcb: str) -> None:
    b = pcbnew.LoadBoard(pcb)
    routed = [t for t in tracks(b) if not (isinstance(t, pcbnew.PCB_VIA) and t.IsLocked())]
    if routed:
        sys.exit(f"{os.path.relpath(pcb, HW)} already has {len(routed)} routed items: run gen_pcb.py first")


def export_dsn(pcb: str, dsn: str) -> None:
    # Board is exported unmodified (removing zones via SWIG corrupts memory on KiCad 7 + Python 3.13);
    # copper pours are stripped from the DSN text instead. Rule areas stay (exported as keepouts).
    b = pcbnew.LoadBoard(pcb)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        raise RuntimeError("DSN export failed")
    text = strip_blocks(open(dsn, encoding="utf-8").read(), "(plane ")
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(text)


def freeroute(dsn: str, ses: str, passes: int) -> None:
    # Freerouting 1.9.0: its CLI honours -mp / -inc / -mt (2.1 ignores them).
    cmd = ["xvfb-run", "-a", "java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "1", "-inc", "GND", "-da"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    log = r.stdout + r.stderr
    if r.returncode != 0 or not os.path.exists(ses):
        print(log[-3000:])
        raise RuntimeError("Freerouting failed")
    for line in log.splitlines():
        if "unrouted" in line.lower() or "completed" in line.lower():
            print("   ", line.split("  ", 1)[-1].strip())


def import_ses(pcb: str, ses: str) -> tuple[int, int]:
    b = pcbnew.LoadBoard(pcb)
    tree = sexp(open(ses, encoding="utf-8").read())
    routes = find(tree, "routes")[0]
    res_unit, res_val = find(routes, "resolution")[0][1:3]
    assert res_unit == "um", res_unit
    scale = 1000.0 / float(res_val)  # SES units → nm
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}

    padstacks = {}
    for ps in find(find(routes, "library_out")[0], "padstack") if find(routes, "library_out") else []:
        m = re.search(r"_(\d+):(\d+)_um", ps[1])
        if not m:
            raise ValueError(f"unexpected via padstack {ps[1]}")
        padstacks[ps[1]] = (int(m.group(1)) * 1000, int(m.group(2)) * 1000)

    def pt(x, y):
        return pcbnew.VECTOR2I(int(round(float(x) * scale)), int(round(-float(y) * scale)))

    fixed = {(v.GetPosition().x, v.GetPosition().y) for v in tracks(b) if isinstance(v, pcbnew.PCB_VIA)}
    ntracks = nvias = 0
    for net in find(find(routes, "network_out")[0], "net"):
        ni = b.FindNet(net[1])
        if ni is None:
            raise ValueError(f"SES net {net[1]} not on board")
        for wire in find(net, "wire"):
            path = find(wire, "path")[0]
            layer, width, coords = path[1], int(float(path[2]) * scale), path[3:]
            pts = [pt(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]
            for a, c in zip(pts, pts[1:]):
                if a == c:
                    continue
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(a)
                t.SetEnd(c)
                t.SetWidth(width)
                t.SetLayer(layers[layer])
                t.SetNet(ni)
                b.Add(t)
                ntracks += 1
        for via in find(net, "via"):
            dia, drill = padstacks[via[1]]
            pos = pt(via[2], via[3])
            if any(abs(pos.x - fx) < 2000 and abs(pos.y - fy) < 2000 for fx, fy in fixed):
                continue  # our locked via, echoed back by the router
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pos)
            v.SetWidth(dia)
            v.SetDrill(drill)
            v.SetNet(ni)
            b.Add(v)
            nvias += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(pcb, b)
    return ntracks, nvias


def drc(pcb: str, report: str) -> dict[str, int]:
    b = pcbnew.LoadBoard(pcb)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.WriteDRCReport(b, report, pcbnew.EDA_UNITS_MILLIMETRES, True)
    return summarize(report)


def summarize(report: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    sev = None
    for line in open(report, encoding="utf-8"):
        m = re.match(r"\[(\w+)\]", line)
        if m:
            sev = m.group(1)
        elif "Severity:" in line and sev:
            level = line.rsplit("Severity:", 1)[1].strip()
            counts[f"{sev}:{level}"] = counts.get(f"{sev}:{level}", 0) + 1
            sev = None
    m = re.search(r"Found (\d+) unconnected", open(report, encoding="utf-8").read())
    counts["unconnected"] = int(m.group(1)) if m else -1
    return counts


def route(name: str, passes: int = int(os.environ.get("RQ_ROUTE_PASSES", "100"))) -> None:
    pcb = BOARDS[name]
    os.makedirs(os.path.join(HW, "build"), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        dsn, ses = os.path.join(tmp, f"{name}.dsn"), os.path.join(tmp, f"{name}.ses")
        require_unrouted(pcb)
        export_dsn(pcb, dsn)
        print(f"{name}: Freerouting…")
        freeroute(dsn, ses, passes)
        n, v = import_ses(pcb, ses)
    report = os.path.join(HW, "build", f"{name}-drc.rpt")
    counts = drc(pcb, report)
    print(f"{name}: {n} track segments, {v} vias → DRC {counts}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for nm in (BOARDS if which == "all" else [which]):
        route(nm)
