"""
Render a .kicad_sch to PDF/PNG for review without KiCad (approximation of KiCad's look).
    python hardware/tools/render_schematic.py   → hardware/build/*.pdf, *.png
"""

from __future__ import annotations

import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from kiutils.items.syitems import SyCircle, SyPolyLine, SyRect
from kiutils.schematic import Schematic

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420)}
BODY, PIN, WIRE, LABEL, PWR, TXT = "#8B0000", "#8B0000", "#008000", "#00008B", "#8B0000", "#222222"


def tf(sx, sy, rot, px, py):
    r = math.radians(rot or 0)
    return sx + px * math.cos(r) - py * math.sin(r), sy - (px * math.sin(r) + py * math.cos(r))


def render(src: str, dst_base: str) -> None:
    sch = Schematic.from_file(src)
    w, h = PAPER.get(sch.paper.paperSize, (420, 297))
    fig = plt.figure(figsize=(w / 25.4, h / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(plt.Rectangle((2, 2), w - 4, h - 4, fill=False, lw=0.6, color="#888"))
    tb = sch.titleBlock
    ax.text(w - 6, h - 6, f"{tb.title}   rev {tb.revision}   {tb.date}", ha="right", va="bottom", fontsize=9,
            color=TXT, weight="bold")

    libs = {(f"{s.libraryNickname}:{s.entryName}" if s.libraryNickname else s.entryName): s for s in sch.libSymbols}
    for inst in sch.schematicSymbols:
        lib = libs[inst.libId]
        X, Y, rot = inst.position.X, inst.position.Y, inst.position.angle or 0
        power = bool(lib.isPower)
        for u in lib.units:
            for g in u.graphicItems:
                if isinstance(g, SyRect):
                    pts = [(g.start.X, g.start.Y), (g.end.X, g.start.Y), (g.end.X, g.end.Y), (g.start.X, g.end.Y),
                           (g.start.X, g.start.Y)]
                    xs, ys = zip(*[tf(X, Y, rot, *p) for p in pts], strict=True)
                    ax.fill(xs, ys, color="#FFFFC2", zorder=1)
                    ax.plot(xs, ys, color=BODY, lw=0.6, zorder=2)
                elif isinstance(g, SyPolyLine):
                    xs, ys = zip(*[tf(X, Y, rot, p.X, p.Y) for p in g.points], strict=True)
                    ax.plot(xs, ys, color=BODY, lw=0.6, zorder=2)
                elif isinstance(g, SyCircle):
                    cx, cy = tf(X, Y, rot, g.center.X, g.center.Y)
                    ax.add_patch(plt.Circle((cx, cy), g.radius, fill=False, color=BODY, lw=0.6, zorder=2))
            show_names = not (lib.pinNames and getattr(lib, "pinNamesHide", False)) and not power
            for p in u.pins:
                if p.hide or power:
                    continue
                a = math.radians(p.position.angle or 0)
                x1, y1 = p.position.X, p.position.Y
                x2, y2 = x1 + p.length * math.cos(a), y1 + p.length * math.sin(a)
                (wx1, wy1), (wx2, wy2) = tf(X, Y, rot, x1, y1), tf(X, Y, rot, x2, y2)
                ax.plot([wx1, wx2], [wy1, wy2], color=PIN, lw=0.6, zorder=2)
                if show_names and p.name not in ("~", ""):
                    ang = int(p.position.angle or 0)
                    ha = {0: "left", 180: "right"}.get(ang, "center")
                    off = {0: (0.6, 0), 180: (-0.6, 0), 90: (0, -0.8), 270: (0, 0.8)}[ang]
                    va = {90: "bottom", 270: "top"}.get(ang, "center")
                    name = p.name.split("/")[0].replace("~{OE}", "OE̅")
                    ax.text(wx2 + off[0], wy2 + off[1], name, fontsize=3.2, ha=ha, va=va, color=TXT, zorder=3)
                if not lib.hidePinNumbers and not power and len(lib.units) and show_names:
                    mx, my = (wx1 + wx2) / 2, (wy1 + wy2) / 2
                    ax.text(mx, my - 0.3, p.number, fontsize=2.6, ha="center", va="bottom", color="#A05050")
        for prop in inst.properties:
            if prop.key not in ("Reference", "Value") or (prop.effects and prop.effects.hide):
                continue
            col = PWR if power else ("#006464" if prop.key == "Reference" else TXT)
            ax.text(prop.position.X, prop.position.Y, prop.value, fontsize=4.2 if not power else 3.6, ha="center",
                    va="center", color=col, zorder=4, weight="bold" if prop.key == "Reference" else "normal")

    for it in sch.graphicalItems:
        if getattr(it, "type", None) == "wire":
            xs = [p.X for p in it.points]
            ys = [p.Y for p in it.points]
            ax.plot(xs, ys, color=WIRE, lw=0.7, zorder=2)
    for nc in sch.noConnects:
        x, y, d = nc.position.X, nc.position.Y, 0.8
        ax.plot([x - d, x + d], [y - d, y + d], color="#0000AA", lw=0.6)
        ax.plot([x - d, x + d], [y + d, y - d], color="#0000AA", lw=0.6)
    for lab in sch.labels:
        ang = lab.position.angle or 0
        ha = "right" if ang in (180, 270) else "left"
        ax.text(lab.position.X, lab.position.Y, lab.text, fontsize=3.8, color=LABEL, ha=ha, va="bottom",
                rotation=90 if ang in (90, 270) else 0, rotation_mode="anchor", zorder=4)
    for t in sch.texts:
        size = t.effects.font.height if t.effects and t.effects.font else 1.27
        ax.text(t.position.X, t.position.Y, t.text, fontsize=size * 2.6, color=TXT, ha="left", va="top",
                weight="bold" if size > 2 else "normal", zorder=4, linespacing=1.4)

    fig.savefig(dst_base + ".pdf")
    fig.savefig(dst_base + ".png", dpi=110)
    plt.close(fig)
    print("rendered", os.path.relpath(dst_base, HW) + ".{pdf,png}")


if __name__ == "__main__":
    os.makedirs(os.path.join(HW, "build"), exist_ok=True)
    render(os.path.join(HW, "routine-quest.kicad_sch"), os.path.join(HW, "build", "main-board"))
    render(os.path.join(HW, "button-board", "button-board.kicad_sch"), os.path.join(HW, "build", "button-board"))
    sys.exit(0)
