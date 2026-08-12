#!/usr/bin/env python3
"""
Generate the project banner: a pixel-art rendering of the lab architecture.

Doubles as a diagram — workers on the left, cSRX in the middle, the fake
internet on the right, telemetry dropping out the bottom.

Regenerate after changing the architecture:

    python3 docs/banner/make_banner.py
    python3 -c "import cairosvg; cairosvg.svg2png(url='banner.svg', \
        write_to='banner.png', output_width=1280, output_height=452)"

Requires cairosvg only for the PNG; the SVG needs nothing.
"""

W, H = 1280, 452

# Palette. The image carries its own dark panel so it reads correctly on both
# GitHub light and dark themes without needing two variants.
BG        = "#0b1020"
PANEL     = "#111a30"
GRID      = "#18213c"
EDGE      = "#1e2a4a"

INK       = "#e8eefc"
MUTED     = "#7f8db3"
DIM       = "#55618a"

TRUST     = "#38bdf8"   # trust zone / benign traffic
AMBER     = "#f5a524"   # the firewall
GREEN     = "#34d399"   # services / healthy
RED       = "#f2555a"   # the injected attack
VIOLET    = "#a78bfa"   # telemetry

SKIN  = ["#f2c8a0", "#d9a273", "#b87f52", "#f7d9b8"]
HAIR  = ["#3b2b25", "#6b4423", "#1f1a17", "#8a5a2b"]
SHIRT = ["#4f7fd4", "#3fae8f", "#c8613f", "#8b6fc4"]

out = []
def add(s): out.append(s)


def px(grid, x, y, s, colors):
    """Emit a pixel-art sprite from a string grid."""
    for r, row in enumerate(grid):
        run_ch, run_start = None, 0
        for c in range(len(row) + 1):
            ch = row[c] if c < len(row) else None
            if ch != run_ch:
                if run_ch and run_ch != ".":
                    add(f'<rect x="{x+run_start*s}" y="{y+r*s}" '
                        f'width="{(c-run_start)*s}" height="{s}" fill="{colors[run_ch]}"/>')
                run_ch, run_start = ch, c


WORKER = [
    "..HHHHH..",
    ".HHHHHHH.",
    ".HSSSSSH.",
    ".SSKSKSS.",
    ".SSSSSSS.",
    "..SSSSS..",
    "...NNN...",
    ".BBBBBBB.",
    "BBBBBBBBB",
    "ABBBBBBBA",
    "ABBBBBBBA",
    ".BBBBBBB.",
]

MONITOR = [
    "MMMMMMMMM",
    "MGGtGGGGM",
    "MGttttGGM",
    "MGGGGttGM",
    "MGtGGGGGM",
    "MMMMMMMMM",
    "...MMM...",
    "..MMMMM..",
]

CHAIR = [
    "..CCCCC..",
    ".CCCCCCC.",
    ".CCCCCCC.",
    ".CCCCCCC.",
    ".CCCCCCC.",
    "..CCCCC..",
]

RACK = [
    "RRRRRRRRRR",
    "RLLLLLLLDR",
    "RRRRRRRRRR",
    "RLLLLLLLDR",
    "RRRRRRRRRR",
    "RLLLLLLLDR",
    "RRRRRRRRRR",
    "RLLLLLLLDR",
    "RRRRRRRRRR",
]


def header():
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">')
    add(f'''<defs>
  <linearGradient id="bgg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{BG}"/><stop offset="1" stop-color="#0a0f1e"/>
  </linearGradient>
  <linearGradient id="fw" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f7b955"/><stop offset="1" stop-color="#d4881a"/>
  </linearGradient>
  <radialGradient id="glow">
    <stop offset="0" stop-color="{AMBER}" stop-opacity=".45"/>
    <stop offset="1" stop-color="{AMBER}" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="scr">
    <stop offset="0" stop-color="#8fd6ff" stop-opacity=".55"/>
    <stop offset="1" stop-color="#8fd6ff" stop-opacity="0"/>
  </radialGradient>
</defs>''')
    add(f'<rect width="{W}" height="{H}" rx="14" fill="url(#bgg)"/>')
    # faint grid
    add('<g opacity=".5">')
    for gx in range(0, W, 32):
        add(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}" stroke="{GRID}" stroke-width="1"/>')
    for gy in range(0, H, 32):
        add(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}" stroke="{GRID}" stroke-width="1"/>')
    add('</g>')
    add(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="none" stroke="{EDGE}"/>')


def title():
    add(f'<text x="44" y="62" fill="{INK}" font-size="30" font-weight="700" '
        f'letter-spacing="2.5">ENTERPRISE NETWORK SIMULATION LAB</text>')
    add(f'<text x="46" y="90" fill="{MUTED}" font-size="14.5" letter-spacing="1.2">'
        f'synthetic workers &#183; cSRX &#183; labelled traffic &#183; anomaly detection</text>')


def zone_label(x, y, text, color, sub=None):
    add(f'<text x="{x}" y="{y}" fill="{color}" font-size="12" font-weight="700" '
        f'letter-spacing="2.2">{text}</text>')
    if sub:
        add(f'<text x="{x}" y="{y+17}" fill="{DIM}" font-size="11" letter-spacing=".6">{sub}</text>')


def office():
    """Four workstations in the trust zone."""
    zone_label(46, 138, "TRUST ZONE", TRUST, "10.10.0.0/16")
    desk_y = 268
    for i in range(4):
        x = 46 + i * 78
        c = {"H": HAIR[i % 4], "S": SKIN[i % 4], "K": "#241a14",
             "N": SKIN[i % 4], "B": SHIRT[i % 4], "A": SKIN[i % 4]}
        # chair back behind the worker
        px(CHAIR, x + 11, desk_y - 54, 4, {"C": "#1d2745"})
        # worker: head and torso clear above the desk line
        px(WORKER, x + 12, desk_y - 62, 4, c)
        # desk surface + legs
        add(f'<rect x="{x-4}" y="{desk_y}" width="72" height="8" rx="2.5" fill="#2c3a60"/>')
        add(f'<rect x="{x-4}" y="{desk_y}" width="72" height="3" rx="1.5" fill="#3d4f7d"/>')
        add(f'<rect x="{x+2}" y="{desk_y+8}" width="5" height="20" fill="#1e2947"/>')
        add(f'<rect x="{x+57}" y="{desk_y+8}" width="5" height="20" fill="#1e2947"/>')
        # monitor sits ON the desk, offset so it never covers the face
        add(f'<ellipse cx="{x+30}" cy="{desk_y-12}" rx="34" ry="20" fill="url(#scr)"/>')
        px(MONITOR, x + 16, desk_y - 32, 3.5, {"M": "#33436e", "G": "#5aa9d8", "t": "#a8e0ff"})
        add(f'<text x="{x+30}" y="{desk_y+44}" fill="{DIM}" font-size="9.5" '
            f'text-anchor="middle">10.10.1.{i+1}</text>')


def firewall():
    cx = 470
    add(f'<ellipse cx="{cx+34}" cy="246" rx="124" ry="118" fill="url(#glow)"/>')
    zone_label(cx - 12, 138, "cSRX 26.2R1", AMBER, "AppSecure &#183; IDP")
    # brick wall
    bx, by, bw, bh = cx, 172, 68, 148
    add(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="4" fill="url(#fw)"/>')
    brick_h = 15
    for r in range(bh // brick_h):
        y = by + r * brick_h
        add(f'<line x1="{bx}" y1="{y}" x2="{bx+bw}" y2="{y}" stroke="#00000038" stroke-width="2"/>')
        off = 0 if r % 2 == 0 else bw // 4
        for k in range(3):
            xx = bx + off + k * (bw // 2)
            if bx < xx < bx + bw:
                add(f'<line x1="{xx}" y1="{y}" x2="{xx}" y2="{y+brick_h}" '
                    f'stroke="#00000038" stroke-width="2"/>')
    add(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="4" fill="none" stroke="#ffca6a" stroke-width="1.5"/>')
    # shield
    sx, sy = bx + bw // 2, by + bh // 2
    add(f'<path d="M {sx} {sy-30} L {sx+22} {sy-20} L {sx+22} {sy+6} '
        f'Q {sx+22} {sy+26} {sx} {sy+34} Q {sx-22} {sy+26} {sx-22} {sy+6} '
        f'L {sx-22} {sy-20} Z" fill="#0b1020" opacity=".82"/>')
    add(f'<path d="M {sx-9} {sy+2} l 7 8 l 14 -16" fill="none" stroke="{GREEN}" '
        f'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>')
    add(f'<text x="{sx}" y="{by+bh+17}" fill="{MUTED}" font-size="10" '
        f'text-anchor="middle" letter-spacing="1">RT_FLOW</text>')


SERVICES = [
    ("web", "nginx / TLS", GREEN),
    ("cloud", "MinIO / S3", TRUST),
    ("files", "SMB / SFTP", VIOLET),
    ("stream", "HLS", GREEN),
]


def internet():
    zone_label(646, 138, "UNTRUST &#183; FAKE INTERNET", GREEN, "203.0.113.0/24 &#183; TEST-NET-3")
    for i, (name, sub, col) in enumerate(SERVICES):
        x = 646 + i * 116
        y = 182
        px(RACK, x, y, 5, {"R": "#28355a", "L": col, "D": "#f5a524"})
        add(f'<rect x="{x-3}" y="{y-3}" width="{56}" height="{51}" rx="4" fill="none" '
            f'stroke="{col}" stroke-opacity=".45"/>')
        add(f'<text x="{x+25}" y="{y+68}" fill="{INK}" font-size="12" font-weight="600" '
            f'text-anchor="middle">{name}</text>')
        add(f'<text x="{x+25}" y="{y+84}" fill="{DIM}" font-size="10" '
            f'text-anchor="middle">{sub}</text>')


def flow_dot(x1, y, x2, color, dur, begin, r=4):
    add(f'<circle r="{r}" fill="{color}">'
        f'<animate attributeName="cx" values="{x1};{x2}" dur="{dur}s" '
        f'begin="{begin}s" repeatCount="indefinite"/>'
        f'<animate attributeName="cy" values="{y};{y}" dur="{dur}s" '
        f'begin="{begin}s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values="0;1;1;0" dur="{dur}s" '
        f'begin="{begin}s" repeatCount="indefinite"/></circle>')


def traffic():
    """Flow lanes. Static dots keep it legible if animation is stripped."""
    lanes = [(206, TRUST, 0.0, "HTTPS"), (232, GREEN, 1.1, "S3"), (258, VIOLET, 2.2, "SMB"), (284, RED, 3.1, "C2 beacon")]
    for y, col, delay, tag in lanes:
        add(f'<line x1="378" y1="{y}" x2="466" y2="{y}" stroke="{col}" '
            f'stroke-opacity=".22" stroke-width="2" stroke-dasharray="4 5"/>')
        add(f'<line x1="542" y1="{y}" x2="640" y2="{y}" stroke="{col}" '
            f'stroke-opacity=".22" stroke-width="2" stroke-dasharray="4 5"/>')
        for i, sx in enumerate((392, 416, 440)):
            add(f'<circle cx="{sx}" cy="{y}" r="3" fill="{col}" opacity="{0.75 - i*0.16:.2f}"/>')
        for i, sx in enumerate((558, 586, 614)):
            add(f'<circle cx="{sx}" cy="{y}" r="3" fill="{col}" opacity="{0.7 - i*0.16:.2f}"/>')
        flow_dot(380, y, 464, col, 2.6, delay)
        flow_dot(544, y, 638, col, 2.6, delay + 1.3)
        add(f'<text x="549" y="{y-6}" fill="{col}" font-size="9" opacity=".85">{tag}</text>')

    add(f'<circle cx="52" cy="333" r="3.5" fill="{RED}"/>')
    add(f'<text x="64" y="337" fill="{RED}" font-size="10" font-weight="700">'
        f'injected anomaly</text>')
    add(f'<text x="170" y="337" fill="{DIM}" font-size="10">'
        f'&#8212; same code path, labelled in ground truth</text>')


def telemetry():
    """Firewall logs dropping into the labelled dataset."""
    y = 348
    add(f'<path d="M 504 330 L 504 {y-8}" stroke="{VIOLET}" stroke-opacity=".5" '
        f'stroke-width="2" stroke-dasharray="3 4"/>')
    add(f'<rect x="46" y="{y}" width="1188" height="72" rx="8" fill="{PANEL}" '
        f'stroke="{EDGE}"/>')

    add(f'<text x="66" y="{y+27}" fill="{VIOLET}" font-size="11" font-weight="700" '
        f'letter-spacing="1.8">GROUND TRUTH</text>')
    add(f'<text x="66" y="{y+48}" fill="{MUTED}" font-size="11">'
        f'every flow labelled: worker &#183; persona &#183; activity &#183; benign/malicious</text>')

    # session bars, one per worker colour
    bx = 470
    import math
    for i in range(46):
        h = 6 + int(20 * abs(math.sin(i * 0.55) * math.cos(i * 0.21)))
        col = RED if i in (29, 30, 31) else (TRUST if i % 3 else GREEN)
        add(f'<rect x="{bx + i*9}" y="{y+50-h}" width="5" height="{h}" rx="1.5" '
            f'fill="{col}" opacity=".85"/>')
    add(f'<text x="{bx}" y="{y+64}" fill="{DIM}" font-size="9.5">sessions/min &#8594;</text>')

    add(f'<text x="1214" y="{y+27}" fill="{INK}" font-size="11" font-weight="700" '
        f'text-anchor="end" letter-spacing="1.2">REPRODUCIBLE</text>')
    add(f'<text x="1214" y="{y+48}" fill="{DIM}" font-size="10" text-anchor="end">'
        f'same seed &#8594; same traffic</text>')


header(); title(); office(); firewall(); internet(); traffic(); telemetry()
add('</svg>')

svg = "\n".join(out)
open("banner.svg", "w").write(svg)
print(f"banner.svg written: {len(svg)} bytes")
