"""
Minimal KiCad 8 schematic writer (file format version 20231120; opens in KiCad 8 and 9).

Design approach: the netlist is the source of truth. Every pin gets a short wire stub and
a net label (or a power symbol / no-connect marker), so connectivity never depends on
hand-drawn wires. `check_schematic.py` re-derives connectivity from the written file
independently and runs ERC-style checks.

Coordinates: library symbols use Y-up; the schematic uses Y-down. A symbol placed at (X, Y)
with rotation 0 maps a library pin at (px, py) to (X + px, Y - py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

GRID = 1.27
STUB = 2.54
FONT = 1.27
NAMESPACE = uuid.UUID("6f1b3b0e-6f4b-4c55-9c84-5e1d7a0c2a11")  # deterministic UUIDs → stable diffs


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# --------------------------------------------------------------------------- symbols


@dataclass
class Pin:
    number: str
    name: str
    etype: str  # input output bidirectional tri_state passive power_in power_out open_collector no_connect
    x: float
    y: float
    angle: int  # direction from the connection point into the body (KiCad convention)
    length: float = 2.54
    hidden: bool = False


@dataclass
class SymbolDef:
    lib_id: str  # "RQ:R"
    ref_prefix: str
    pins: list[Pin]
    graphics: list[str] = field(default_factory=list)
    pin_names_hidden: bool = False
    pin_numbers_hidden: bool = False
    power: bool = False
    in_bom: bool = True
    raw_sexpr: str | None = None  # imported symbol (already serialised with lib_id)
    ref_at: tuple[float, float] = (0.0, 5.08)
    value_at: tuple[float, float] = (0.0, -5.08)
    pin_name_offset: float = 0.508

    @property
    def name(self) -> str:
        return self.lib_id.split(":", 1)[1]

    def pin(self, number: str) -> Pin:
        for p in self.pins:
            if p.number == number:
                return p
        raise KeyError(f"{self.lib_id} has no pin {number}")

    def sexpr(self) -> str:
        if self.raw_sexpr is not None:
            return self.raw_sexpr
        n = self.name
        opts = []
        if self.power:
            opts.append("(power)")
        opts.append("(pin_numbers hide)" if self.pin_numbers_hidden else "")
        pn = f"(pin_names (offset {fmt(self.pin_name_offset)}){' hide' if self.pin_names_hidden else ''})"
        hide_ref = " hide" if self.power else ""
        out = [
            f"(symbol {q(self.lib_id)} {' '.join(o for o in opts if o)} {pn} (exclude_from_sim no) "
            f"(in_bom {'yes' if self.in_bom else 'no'}) (on_board yes)",
            f'  (property "Reference" {q(self.ref_prefix)} (at {fmt(self.ref_at[0])} {fmt(self.ref_at[1])} 0) '
            f"(effects (font (size {FONT} {FONT})){hide_ref}))",
            f'  (property "Value" {q(n)} (at {fmt(self.value_at[0])} {fmt(self.value_at[1])} 0) '
            f"(effects (font (size {FONT} {FONT}))))",
            f'  (property "Footprint" "" (at 0 0 0) (effects (font (size {FONT} {FONT})) hide))',
            f'  (property "Datasheet" "~" (at 0 0 0) (effects (font (size {FONT} {FONT})) hide))',
            f"  (symbol {q(n + '_0_1')} {' '.join(self.graphics)})",
            f"  (symbol {q(n + '_1_1')}",
        ]
        for p in self.pins:
            hide = " hide" if p.hidden else ""
            out.append(
                f"    (pin {p.etype} line (at {fmt(p.x)} {fmt(p.y)} {p.angle}) (length {fmt(p.length)}){hide} "
                f"(name {q(p.name)} (effects (font (size {FONT} {FONT})))) "
                f"(number {q(p.number)} (effects (font (size {FONT} {FONT})))))"
            )
        out.append("  )")
        out.append(")")
        return "\n".join(out)


def stroke(w: float = 0.254) -> str:
    return f"(stroke (width {fmt(w)}) (type default))"


def rect(x1, y1, x2, y2, fill="background") -> str:
    return (
        f"(rectangle (start {fmt(x1)} {fmt(y1)}) (end {fmt(x2)} {fmt(y2)}) {stroke()} (fill (type {fill})))"
    )


def poly(*pts, fill="none", w=0.254) -> str:
    xy = " ".join(f"(xy {fmt(x)} {fmt(y)})" for x, y in pts)
    return f"(polyline (pts {xy}) {stroke(w)} (fill (type {fill})))"


def circle(cx, cy, r, fill="none") -> str:
    return f"(circle (center {fmt(cx)} {fmt(cy)}) (radius {fmt(r)}) {stroke()} (fill (type {fill})))"


def ic(lib_id: str, ref: str, left: list = (), right: list = (), top: list = (), bottom: list = (), width: float = 15.24,
       min_rows: int = 0) -> SymbolDef:
    """
    Box symbol. left/right/top/bottom: lists of (number, name, etype) or None for a gap.
    Left pins point right into the body (angle 0), right pins angle 180, top 270, bottom 90.
    """
    rows = max(len(left), len(right), min_rows, 1)
    h = (rows + 1) * 2.54
    half_w = snap(width / 2)
    top_y = snap(h / 2)
    pins = []
    for i, p in enumerate(left):
        if p:
            pins.append(Pin(p[0], p[1], p[2], -half_w - 2.54, top_y - 2.54 * (i + 1), 0))
    for i, p in enumerate(right):
        if p:
            pins.append(Pin(p[0], p[1], p[2], half_w + 2.54, top_y - 2.54 * (i + 1), 180))
    for i, p in enumerate(top):
        if p:
            x = snap(-2.54 * (len(top) - 1) / 2 + 2.54 * i)
            pins.append(Pin(p[0], p[1], p[2], x, top_y + 2.54, 270))
    for i, p in enumerate(bottom):
        if p:
            x = snap(-2.54 * (len(bottom) - 1) / 2 + 2.54 * i)
            pins.append(Pin(p[0], p[1], p[2], x, -top_y - 2.54, 90))
    ref_y = top_y + (5.08 if top else 2.54)
    val_y = -top_y - (5.08 if bottom else 2.54)
    return SymbolDef(lib_id, ref, pins, [rect(-half_w, top_y, half_w, -top_y)],
                     ref_at=(0, ref_y + 1.27), value_at=(0, val_y - 1.27))


def two_pin(lib_id: str, ref: str, graphics: list[str], names=("~", "~"), etype="passive",
            numbers=("1", "2")) -> SymbolDef:
    """Horizontal 2-pin part: pin 1 on the left, pin 2 on the right (connection points at ±5.08)."""
    return SymbolDef(
        lib_id, ref,
        [Pin(numbers[0], names[0], etype, -5.08, 0, 0, 1.27), Pin(numbers[1], names[1], etype, 5.08, 0, 180, 1.27)],
        graphics, pin_names_hidden=True, pin_numbers_hidden=True, ref_at=(0, 3.175), value_at=(0, -3.175),
    )


def power_symbol(name: str, down: bool = False, flag: bool = False) -> SymbolDef:
    if flag:
        g = [poly((0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54), (1.016, 1.905), (0, 1.27))]
        return SymbolDef(f"power:{name}", "#FLG", [Pin("1", "pwr", "power_out", 0, 0, 90, 0, hidden=True)], g,
                         power=True, in_bom=False, ref_at=(0, 1.905), value_at=(0, 3.81))
    if down:  # GND
        g = [poly((0, 0), (0, -1.27), (1.27, -1.27), (0, -2.54), (-1.27, -1.27), (0, -1.27))]
        return SymbolDef(f"power:{name}", "#PWR", [Pin("1", name, "power_in", 0, 0, 270, 0, hidden=True)], g,
                         power=True, in_bom=False, ref_at=(0, -6.35), value_at=(0, -3.81))
    g = [poly((-0.762, 1.27), (0, 2.54)), poly((0, 0), (0, 2.54)), poly((0, 2.54), (0.762, 1.27))]
    return SymbolDef(f"power:{name}", "#PWR", [Pin("1", name, "power_in", 0, 0, 90, 0, hidden=True)], g,
                     power=True, in_bom=False, ref_at=(0, -3.81), value_at=(0, 3.556))


# --------------------------------------------------------------------------- placed parts


@dataclass
class Part:
    ref: str
    sym: SymbolDef
    value: str
    at: tuple[float, float]
    nets: dict[str, str | None]  # pin number -> net name, None = no-connect
    footprint: str = ""
    fields: dict[str, str] = field(default_factory=dict)  # MPN, Manufacturer, Description, ...
    dnp: bool = False


@dataclass
class Schematic:
    title: str
    rev: str
    project: str
    power_nets: set[str]
    paper: str = "A3"
    parts: list[Part] = field(default_factory=list)
    texts: list[tuple[float, float, str, float]] = field(default_factory=list)
    flag_at: tuple[float, float] = (20.32, 20.32)

    def uid(self, key: str) -> str:
        return str(uuid.uuid5(NAMESPACE, f"{self.project}/{self.title}/{key}"))

    def add(self, *parts: Part) -> None:
        self.parts.extend(parts)

    def text(self, x: float, y: float, s: str, size: float = 1.524) -> None:
        self.texts.append((x, y, s, size))

    # ----------------------------------------------------------------- netlist

    def netlist(self) -> dict[str, list[str]]:
        nets: dict[str, list[str]] = {}
        for p in self.parts:
            for num, net in p.nets.items():
                if net is not None:
                    nets.setdefault(net, []).append(f"{p.ref}.{num}")
        return nets

    def validate(self) -> None:
        refs = [p.ref for p in self.parts]
        dup = {r for r in refs if refs.count(r) > 1}
        assert not dup, f"duplicate references {dup}"
        for p in self.parts:
            pins = {pin.number for pin in p.sym.pins}
            missing = pins - set(p.nets)
            extra = set(p.nets) - pins
            assert not missing, f"{p.ref}: pins without net/NC assignment: {sorted(missing)}"
            assert not extra, f"{p.ref}: unknown pins {sorted(extra)}"

    # ----------------------------------------------------------------- writer

    def write(self, path: str, root_uuid_key: str = "root") -> None:
        self.validate()
        root = self.uid(root_uuid_key)
        syms: dict[str, SymbolDef] = {}
        for p in self.parts:
            syms[p.sym.lib_id] = p.sym
        power_defs: dict[str, SymbolDef] = {}
        for net in sorted(self.power_nets):
            power_defs[net] = power_symbol(net, down=(net == "GND"))
        flag = power_symbol("PWR_FLAG", flag=True)

        out: list[str] = [
            "(kicad_sch (version 20231120) (generator \"rq-gen\") (generator_version \"8.0\")",
            f"  (uuid {q(root)})",
            f"  (paper {q(self.paper)})",
            f"  (title_block (title {q(self.title)}) (date \"2026-10-13\") (rev {q(self.rev)}) "
            f"(company \"Routine Quest\") (comment 1 \"Generated by hardware/tools/gen_schematics.py — edit the "
            f"generator, not this file\"))",
            "  (lib_symbols",
        ]
        for s in list(syms.values()) + list(power_defs.values()) + [flag]:
            out.append("    " + s.sexpr().replace("\n", "\n    "))
        out.append("  )")

        pwr_n = 0
        body: list[str] = []
        for p in self.parts:
            body.append(self._symbol_instance(p, root))
            for pin in p.sym.pins:
                net = p.nets[pin.number]
                cx, cy = p.at[0] + pin.x, p.at[1] - pin.y
                if net is None:
                    body.append(f"  (no_connect (at {fmt(cx)} {fmt(cy)}) (uuid {q(self.uid(f'nc/{p.ref}/{pin.number}'))}))")
                    continue
                dx, dy = _outward(pin.angle)
                ex, ey = cx + dx * STUB, cy + dy * STUB
                body.append(
                    f"  (wire (pts (xy {fmt(cx)} {fmt(cy)}) (xy {fmt(ex)} {fmt(ey)})) (stroke (width 0) (type default)) "
                    f"(uuid {q(self.uid(f'w/{p.ref}/{pin.number}'))}))"
                )
                if net in self.power_nets:
                    pwr_n += 1
                    body.append(self._power_instance(power_defs[net], f"#PWR{pwr_n:03d}", ex, ey, dx, dy, root))
                else:
                    body.append(self._label(net, ex, ey, dx, dy, f"l/{p.ref}/{pin.number}"))

        # PWR_FLAGs for power nets that have no power_out driver (connector-fed rails, GND)
        flags = self._needed_flags()
        fx, fy = self.flag_at
        for i, net in enumerate(flags):
            x, y = fx + i * 20.32, fy
            body.append(self._flag_instance(flag, f"#FLG{i + 1:02d}", x, y, root))
            body.append(
                f"  (wire (pts (xy {fmt(x)} {fmt(y)}) (xy {fmt(x)} {fmt(y + STUB)})) (stroke (width 0) (type default)) "
                f"(uuid {q(self.uid(f'fw/{net}'))}))"
            )
            pwr_n += 1
            body.append(self._power_instance(power_defs[net], f"#PWR{pwr_n:03d}", x, y + STUB, 0, 1, root))

        for i, (x, y, s, size) in enumerate(self.texts):
            body.append(
                f"  (text {q(s)} (exclude_from_sim no) (at {fmt(x)} {fmt(y)} 0) "
                f"(effects (font (size {fmt(size)} {fmt(size)})) (justify left top)) (uuid {q(self.uid(f't/{i}'))}))"
            )
        out.extend(body)
        out.append('  (sheet_instances (path "/" (page "1")))')
        out.append(")")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")

    def _needed_flags(self) -> list[str]:
        driven = set()
        for p in self.parts:
            for pin in p.sym.pins:
                if pin.etype == "power_out" and p.nets[pin.number]:
                    driven.add(p.nets[pin.number])
        used = {n for p in self.parts for n in p.nets.values() if n in self.power_nets}
        return sorted(used - driven)

    def _symbol_instance(self, p: Part, root: str) -> str:
        s = p.sym
        x, y = p.at
        rx, ry = x + s.ref_at[0], y - s.ref_at[1]
        vx, vy = x + s.value_at[0], y - s.value_at[1]
        props = [
            f'    (property "Reference" {q(p.ref)} (at {fmt(rx)} {fmt(ry)} 0) (effects (font (size {FONT} {FONT}))))',
            f'    (property "Value" {q(p.value)} (at {fmt(vx)} {fmt(vy)} 0) (effects (font (size {FONT} {FONT}))))',
            f'    (property "Footprint" {q(p.footprint)} (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f'    (property "Datasheet" {q(p.fields.get("Datasheet", "~"))} (at {fmt(x)} {fmt(y)} 0) '
            f"(effects (font (size {FONT} {FONT})) hide))",
        ]
        for k, v in p.fields.items():
            if k == "Datasheet":
                continue
            props.append(
                f"    (property {q(k)} {q(v)} (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))"
            )
        pins = " ".join(f"(pin {q(pin.number)} (uuid {q(self.uid(f'pu/{p.ref}/{pin.number}'))}))" for pin in s.pins)
        return "\n".join([
            f"  (symbol (lib_id {q(s.lib_id)}) (at {fmt(x)} {fmt(y)} 0) (unit 1) (exclude_from_sim no) "
            f"(in_bom {'yes' if s.in_bom else 'no'}) (on_board yes) (dnp {'yes' if p.dnp else 'no'}) "
            f"(uuid {q(self.uid(f's/{p.ref}'))})",
            *props,
            f"    {pins}",
            f"    (instances (project {q(self.project)} (path {q('/' + root)} (reference {q(p.ref)}) (unit 1))))",
            "  )",
        ])

    def _power_instance(self, sym: SymbolDef, ref: str, x: float, y: float, dx: float, dy: float, root: str) -> str:
        # rotate so the symbol body points away from the pin it is attached to
        if sym.name == "GND":
            rot = {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270}[(dx, dy)]
        else:
            rot = {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270}[(dx, dy)]
        vy = y - sym.value_at[1] if rot == 0 else y
        vx = x + (4.5 if (dx, dy) == (1, 0) else -4.5 if (dx, dy) == (-1, 0) else 0)
        if (dx, dy) == (0, 1) and sym.name != "GND":
            vy = y + 4.5
        if (dx, dy) == (0, -1) and sym.name == "GND":
            vy = y - 4.5
        return "\n".join([
            f"  (symbol (lib_id {q(sym.lib_id)}) (at {fmt(x)} {fmt(y)} {rot}) (unit 1) (exclude_from_sim no) "
            f"(in_bom no) (on_board yes) (dnp no) (uuid {q(self.uid(f'p/{ref}'))})",
            f'    (property "Reference" {q(ref)} (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f'    (property "Value" {q(sym.name)} (at {fmt(vx)} {fmt(vy)} 0) (effects (font (size {FONT} {FONT}))))',
            f'    (property "Footprint" "" (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f'    (property "Datasheet" "" (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f"    (pin \"1\" (uuid {q(self.uid(f'pp/{ref}'))}))",
            f"    (instances (project {q(self.project)} (path {q('/' + root)} (reference {q(ref)}) (unit 1))))",
            "  )",
        ])

    def _flag_instance(self, sym: SymbolDef, ref: str, x: float, y: float, root: str) -> str:
        return "\n".join([
            f"  (symbol (lib_id {q(sym.lib_id)}) (at {fmt(x)} {fmt(y)} 0) (unit 1) (exclude_from_sim no) "
            f"(in_bom no) (on_board yes) (dnp no) (uuid {q(self.uid(f'f/{ref}'))})",
            f'    (property "Reference" {q(ref)} (at {fmt(x)} {fmt(y - 1.905)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f'    (property "Value" "PWR_FLAG" (at {fmt(x)} {fmt(y - 3.81)} 0) (effects (font (size {FONT} {FONT}))))',
            f'    (property "Footprint" "" (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f'    (property "Datasheet" "~" (at {fmt(x)} {fmt(y)} 0) (effects (font (size {FONT} {FONT})) hide))',
            f"    (pin \"1\" (uuid {q(self.uid(f'fp/{ref}'))}))",
            f"    (instances (project {q(self.project)} (path {q('/' + root)} (reference {q(ref)}) (unit 1))))",
            "  )",
        ])

    def _label(self, net: str, x: float, y: float, dx: float, dy: float, key: str) -> str:
        angle, just = {(1, 0): (0, "left"), (-1, 0): (180, "right"), (0, -1): (90, "left"),
                       (0, 1): (270, "right")}[(dx, dy)]
        return (
            f"  (label {q(net)} (at {fmt(x)} {fmt(y)} {angle}) (fields_autoplaced yes) "
            f"(effects (font (size {FONT} {FONT})) (justify {just} bottom)) (uuid {q(self.uid(key))}))"
        )


def _outward(angle: int) -> tuple[int, int]:
    """Unit vector (schematic coords, Y down) pointing away from the body for a pin angle."""
    return {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[angle]
