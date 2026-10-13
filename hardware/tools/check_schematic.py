"""
Independent schematic check — does NOT reuse the generator's data structures.

1. Parses each .kicad_sch with kiutils (catches syntax errors KiCad would reject).
2. Rebuilds connectivity purely from geometry: pin positions (from embedded lib_symbols),
   wire endpoints, labels (same name = same net), power symbols (same value = same net).
3. Compares the result with the reviewed netlist (build/*.netlist.json).
4. ERC-style rules (subset of KiCad's):
   - every pin is connected or explicitly no-connect, never both
   - each net has ≥ 2 connections
   - power_in nets need a power_out or PWR_FLAG driver
   - no output↔output / power_out↔power_out / power_out↔output conflicts
   - nets with only inputs have no driver

Exit code 1 on any error. Run KiCad's own ERC as well during review (docs/06 §7).
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

from kiutils.schematic import Schematic

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARDS = [
    ("routine-quest.kicad_sch", "build/main.netlist.json"),
    ("button-board/button-board.kicad_sch", "build/button-board.netlist.json"),
]


def key(x: float, y: float) -> tuple[int, int]:
    return (round(x * 1000), round(y * 1000))


class DSU:
    def __init__(self):
        self.p: dict = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def pin_world(sx: float, sy: float, rot: float, px: float, py: float) -> tuple[float, float]:
    r = math.radians(rot or 0)
    rx = px * math.cos(r) - py * math.sin(r)
    ry = px * math.sin(r) + py * math.cos(r)
    return sx + rx, sy - ry


def check(sch_path: str, netlist_path: str) -> list[str]:
    errors: list[str] = []
    sch = Schematic.from_file(sch_path)
    libs = {}
    for s in sch.libSymbols:
        lib_id = f"{s.libraryNickname}:{s.entryName}" if s.libraryNickname else s.entryName
        pins = []
        for u in s.units:
            for p in u.pins:
                pins.append((p.number, p.electricalType, p.position.X, p.position.Y))
        libs[lib_id] = {"pins": pins, "power": bool(s.isPower)}

    dsu = DSU()
    point_pins: dict = defaultdict(list)  # point -> [(ref, pin, etype)]
    power_points: dict = defaultdict(list)  # point -> [net]
    flag_points: list = []
    refs_pins = {}

    for inst in sch.schematicSymbols:
        lib = libs[inst.libId]
        ref = next(p.value for p in inst.properties if p.key == "Reference")
        value = next(p.value for p in inst.properties if p.key == "Value")
        for num, etype, px, py in lib["pins"]:
            pt = key(*pin_world(inst.position.X, inst.position.Y, inst.position.angle, px, py))
            dsu.find(pt)
            if lib["power"]:
                if value == "PWR_FLAG":
                    flag_points.append(pt)
                else:
                    power_points[pt].append(value)
            else:
                point_pins[pt].append((ref, num, etype))
                refs_pins[(ref, num)] = (pt, etype)

    for item in sch.graphicalItems:
        if getattr(item, "type", None) == "wire":
            a, b = item.points[0], item.points[-1]
            dsu.union(key(a.X, a.Y), key(b.X, b.Y))

    label_points: dict = defaultdict(list)
    for lab in sch.labels:
        label_points[lab.text].append(key(lab.position.X, lab.position.Y))
    for name, pts in label_points.items():
        for p in pts:
            dsu.find(p)
        for p in pts[1:]:
            dsu.union(pts[0], p)
        if len(pts) == 1:
            errors.append(f"label '{name}' appears once (dangling net)")
    power_by_name: dict = defaultdict(list)
    for pt, names in power_points.items():
        for n in names:
            power_by_name[n].append(pt)
    for _name, pts in power_by_name.items():
        for p in pts[1:]:
            dsu.union(pts[0], p)

    nc_points = {key(nc.position.X, nc.position.Y) for nc in sch.noConnects}

    # group into nets
    groups: dict = defaultdict(lambda: {"pins": [], "names": set(), "flag": False})
    for pt, pins in point_pins.items():
        groups[dsu.find(pt)]["pins"].extend(pins)
    for name, pts in label_points.items():
        groups[dsu.find(pts[0])]["names"].add(name)
    for name, pts in power_by_name.items():
        groups[dsu.find(pts[0])]["names"].add(name)
    for pt in flag_points:
        groups[dsu.find(pt)]["flag"] = True

    derived: dict[str, list[str]] = {}
    for _root, g in groups.items():
        if len(g["names"]) > 1:
            errors.append(f"net has several names: {sorted(g['names'])}")
        if not g["pins"]:
            continue
        name = sorted(g["names"])[0] if g["names"] else None
        pins = sorted(f"{r}.{n}" for r, n, _ in g["pins"])
        if name is None:
            # unnamed group: must be a single NC pin
            for r, n, _ in g["pins"]:
                if refs_pins[(r, n)][0] not in nc_points:
                    errors.append(f"pin {r}.{n} is unconnected and not marked no-connect")
            continue
        for r, n, _ in g["pins"]:
            if refs_pins[(r, n)][0] in nc_points:
                errors.append(f"pin {r}.{n} is marked no-connect but connected to {name}")
        derived[name] = pins
        types = [t for _, _, t in g["pins"]]
        if len(pins) < 2:
            errors.append(f"net {name} has a single connection ({pins[0]})")
        n_out, n_pout = types.count("output"), types.count("power_out")
        if n_out > 1:
            errors.append(f"net {name}: {n_out} outputs driving each other")
        if n_pout > 1:
            errors.append(f"net {name}: {n_pout} power outputs in parallel")
        if n_pout and n_out:
            errors.append(f"net {name}: power output and signal output conflict")
        if "power_in" in types and not (n_pout or g["flag"]):
            errors.append(f"net {name}: power input(s) without a driver (power_out or PWR_FLAG)")
        if types and all(t == "input" for t in types):
            errors.append(f"net {name}: only inputs, nothing drives it")

    with open(netlist_path, encoding="utf-8") as f:
        expected = json.load(f)
    if derived != expected:
        for n in sorted(set(expected) | set(derived)):
            if expected.get(n) != derived.get(n):
                errors.append(f"netlist mismatch on {n}: expected {expected.get(n)}, schematic {derived.get(n)}")
    n_pins = sum(len(v) for v in derived.values())
    print(f"{os.path.relpath(sch_path, HW)}: {len(sch.schematicSymbols)} symbols, {len(derived)} nets, "
          f"{n_pins} connected pins, {len(nc_points)} no-connects, {len(flag_points)} PWR_FLAGs → "
          f"{'OK' if not errors else f'{len(errors)} ERROR(S)'}")
    return errors


def main() -> int:
    bad = 0
    for sch, net in BOARDS:
        errs = check(os.path.join(HW, sch), os.path.join(HW, net))
        for e in errs:
            print("  ERROR:", e)
        bad += len(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
