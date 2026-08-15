#!/usr/bin/env python3
"""
Stage 0 topology diagram.

Reflects the lab as actually deployed: bridge names, subnets, the eth->Junos
interface mapping, and where the two ground-truth files come from.

Regenerate after an architecture change:
    python3 docs/topology/gen_topo.py
    python3 -c "import cairosvg; cairosvg.svg2png(url='topology.svg', \
        write_to='topology.png', output_width=1360, output_height=920)"
"""

W, H = 1360, 920

BG      = "#0b1020"
PANEL   = "#111a30"
GRID    = "#18213c"
EDGE    = "#243154"
INK     = "#e8eefc"
MUTED   = "#8492b8"
DIM     = "#5a6790"

TRUST   = "#38bdf8"
AMBER   = "#f5a524"
GREEN   = "#34d399"
VIOLET  = "#a78bfa"
RED     = "#f2555a"

out = []
def add(s): out.append(s)


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, stroke, fill=PANEL, dash=None, rx=10, width=1.5, op=1.0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{width}" opacity="{op}"{d}/>')


def text(x, y, t, fill=INK, size=13, weight="400", anchor="start", ls=0, mono=True):
    fam = ("ui-monospace,SFMono-Regular,Menlo,monospace" if mono
           else "ui-sans-serif,system-ui,sans-serif")
    add(f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}" letter-spacing="{ls}" font-family="{fam}">{esc(t)}</text>')


def arrow(x1, y1, x2, y2, color, label=None, dash=None, lx=None, ly=None, width=2.2):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{width}" marker-end="url(#a-{color[1:]})"{d}/>')
    if label:
        text(lx if lx is not None else (x1 + x2) / 2,
             ly if ly is not None else min(y1, y2) - 8,
             label, color, 10.5, anchor="middle")


def header():
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    defs = ['<defs>']
    for c in (TRUST, AMBER, GREEN, VIOLET, RED, MUTED, DIM):
        defs.append(
            f'<marker id="a-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>')
    defs.append(f'''<linearGradient id="fwg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2a2038"/><stop offset="1" stop-color="#1c1830"/></linearGradient>''')
    defs.append('</defs>')
    add("".join(defs))
    add(f'<rect width="{W}" height="{H}" rx="14" fill="{BG}"/>')
    add('<g opacity=".45">')
    for gx in range(0, W, 34):
        add(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}" stroke="{GRID}"/>')
    for gy in range(0, H, 34):
        add(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}" stroke="{GRID}"/>')
    add('</g>')
    add(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="none" stroke="{EDGE}"/>')


# ---------------------------------------------------------------- title
header()
text(42, 52, "STAGE 0 — TOPOLOGY", INK, 25, "700", ls=2.2)
text(43, 78, "netsim-stage0  ·  cSRX 26.2R1.7  ·  all bridges internal (no route to the real internet)",
     MUTED, 12.5)

# ---------------------------------------------------------------- host boundary
box(30, 96, W - 60, 706, EDGE, "none", dash="7 6", rx=12, width=1.4)
text(48, 120, "Ubuntu x86_64 host — docker", DIM, 11, ls=1.4)

# ---------------------------------------------------------------- management band
MX, MY, MW, MH = 430, 140, 500, 108
box(MX, MY, MW, MH, VIOLET, "#141a33", rx=10, width=1.4)
text(MX + 16, MY + 24, "MANAGEMENT", VIOLET, 11, "700", ls=1.8)
text(MX + 16, MY + 42, "br-ns-mgmt   172.30.0.0/24   internal", DIM, 10.5)

box(MX + 250, MY + 54, 232, 40, VIOLET, PANEL, rx=8, width=1.2)
text(MX + 366, MY + 72, "netsim-syslog-sink", INK, 11.5, "600", anchor="middle")
text(MX + 366, MY + 86, "172.30.0.20  ·  UDP/514", DIM, 10, anchor="middle")

text(MX + 16, MY + 78, "bridge gw .254", DIM, 9.5)
text(MX + 16, MY + 92, "(unused — internal)", DIM, 9.5)

# ---------------------------------------------------------------- cSRX
FX, FY, FW, FH = 566, 320, 250, 268
box(FX, FY, FW, FH, AMBER, "url(#fwg)", rx=12, width=2)
text(FX + FW / 2, FY + 28, "netsim-csrx", AMBER, 14.5, "700", anchor="middle", ls=1)
text(FX + FW / 2, FY + 46, "cSRX 26.2R1.7 · AppSecure · IDP", MUTED, 10, anchor="middle")

rows = [
    ("eth0  →  fxp0",      "172.30.0.10",  VIOLET),
    ("eth1  →  ge-0/0/0",  "10.20.0.1/16",  TRUST),
    ("eth2  →  ge-0/0/1",  "203.0.113.1/24", GREEN),
]
ry = FY + 74
for name, addr, col in rows:
    box(FX + 14, ry, FW - 28, 34, col, "#0e1428", rx=6, width=1)
    text(FX + 24, ry + 15, name, col, 10.5, "600")
    text(FX + 24, ry + 28, addr, MUTED, 10)
    ry += 40

box(FX + 14, ry + 4, FW - 28, 70, DIM, "#0e1428", rx=6, width=1)
text(FX + 24, ry + 21, "tap0 ← ge-0/0/0   tap1 ← ge-0/0/1", DIM, 9)
text(FX + 24, ry + 35, "zones: trust / untrust", DIM, 9)
text(FX + 24, ry + 49, "policy permit-all · log init+close", AMBER, 9)
text(FX + 24, ry + 63, "NO NAT — keeps the join key intact", AMBER, 9)

# ---------------------------------------------------------------- trust zone
TX, TY, TW, TH = 66, 320, 386, 268
box(TX, TY, TW, TH, TRUST, "#101a2e", rx=10, width=1.4)
text(TX + 16, TY + 24, "TRUST ZONE", TRUST, 11, "700", ls=1.8)
text(TX + 16, TY + 42, "br-ns-trust   10.20.0.0/16   internal", DIM, 10.5)
text(TX + 16, TY + 58, "bridge gw 10.20.255.254 (unused)", DIM, 9.5)

box(TX + 16, TY + 72, TW - 32, 178, TRUST, PANEL, rx=8, width=1.2)
text(TX + 30, TY + 94, "netsim-workstation", INK, 12, "600")
text(TX + 30, TY + 110, "10.20.0.100  ·  python asyncio engine", DIM, 10)
text(TX + 30, TY + 130, "a worker is a coroutine + a source IP,", MUTED, 9.5)
text(TX + 30, TY + 143, "not a container", MUTED, 9.5)

wy = TY + 158
for i in range(3):
    box(TX + 30, wy, 150, 26, TRUST, "#0e1428", rx=5, width=1)
    text(TX + 40, wy + 17, f"worker-{i:04d}", INK, 10)
    text(TX + 172, wy + 17, f"10.20.1.{i+1}", TRUST, 10, anchor="end")
    wy += 30

text(TX + 196, TY + 176, "seeded state machines", DIM, 9)
text(TX + 196, TY + 190, "same seed → same traffic", DIM, 9)
text(TX + 196, TY + 212, "one request per TCP session", DIM, 9)
text(TX + 196, TY + 226, "keep-alive off → 1 flow = 1 intent", DIM, 9)

# ---------------------------------------------------------------- untrust zone
UX, UY, UW, UH = 908, 320, 386, 268
box(UX, UY, UW, UH, GREEN, "#0f1c2a", rx=10, width=1.4)
text(UX + 16, UY + 24, "UNTRUST ZONE — FAKE INTERNET", GREEN, 11, "700", ls=1.4)
text(UX + 16, UY + 42, "br-ns-untrust   203.0.113.0/24   internal", DIM, 10.5)
text(UX + 16, UY + 58, "TEST-NET-3, unroutable · gw .254 (unused)", DIM, 9.5)

box(UX + 16, UY + 72, UW - 32, 106, GREEN, PANEL, rx=8, width=1.2)
text(UX + 30, UY + 94, "netsim-web", INK, 12, "600")
text(UX + 30, UY + 110, "203.0.113.10  ·  nginx 1.27 + TLS", DIM, 10)
text(UX + 30, UY + 130, "www.example-corp.internal", GREEN, 10)
text(UX + 30, UY + 148, "/ /small /medium /large /upload", DIM, 9.5)
text(UX + 30, UY + 164, "cert signed by the lab CA (private)", DIM, 9.5)

box(UX + 16, UY + 190, UW - 32, 60, DIM, "#0e1428", rx=8, width=1)
text(UX + 30, UY + 210, "Stage 2 adds:", MUTED, 10, "600")
text(UX + 30, UY + 226, "MinIO (S3) · Nextcloud · HLS · SMB · CoreDNS", DIM, 9.5)
text(UX + 30, UY + 240, "return route 10.20.0.0/16 via 203.0.113.1", DIM, 9.5)

OY = 620

# ---------------------------------------------------------------- arrows
arrow(TX + TW, 430, FX, 430, TRUST, width=2.2)
text(TX + TW + 8, 420, "HTTPS / TLS", TRUST, 9.5)
text(TX + TW + 8, 446, "src 10.20.1.x", DIM, 9)

arrow(FX + FW, 430, UX, 430, GREEN, width=2.2)
text(FX + FW + 8, 420, "inspected", GREEN, 9.5)
text(FX + FW + 8, 446, "AppID", DIM, 9)

# syslog: cSRX -> management band
arrow(FX + FW / 2, FY, FX + FW / 2, MY + MH + 4, VIOLET, dash="5 4", width=1.8)
text(FX + FW / 2 + 10, (MY + MH + FY) / 2 - 2, "RT_FLOW syslog", VIOLET, 10)
text(FX + FW / 2 + 10, (MY + MH + FY) / 2 + 12, "structured-data", DIM, 9)

# ---------------------------------------------------------------- outputs
box(66, OY, W - 132, 168, EDGE, PANEL, rx=10, width=1.4)
text(86, OY + 26, "GROUND TRUTH", INK, 11.5, "700", ls=1.8)
text(86, OY + 44, "what makes this a labelled dataset rather than a traffic generator", DIM, 10)

box(86, OY + 58, 380, 94, TRUST, "#0e1428", rx=8, width=1.2)
text(102, OY + 80, "out/intents.jsonl", TRUST, 11.5, "600")
text(102, OY + 98, "written by the engine — what each worker", MUTED, 9.5)
text(102, OY + 112, "meant to do", MUTED, 9.5)
text(102, OY + 132, "worker · persona · activity · label · src_port", DIM, 9.5)

box(894, OY + 58, 380, 94, VIOLET, "#0e1428", rx=8, width=1.2)
text(910, OY + 80, "out/flows.csv", VIOLET, 11.5, "600")
text(910, OY + 98, "parsed from cSRX RT_FLOW — what the", MUTED, 9.5)
text(910, OY + 112, "firewall actually saw", MUTED, 9.5)
text(910, OY + 132, "5-tuple · bytes · packets · application · policy", DIM, 9.5)

box(500, OY + 58, 360, 94, AMBER, "#0e1428", rx=8, width=1.2)
text(680, OY + 80, "JOIN", AMBER, 11.5, "700", anchor="middle", ls=1.4)
text(680, OY + 100, "(src_ip, src_port) within 5s", INK, 10.5, anchor="middle")
text(680, OY + 118, "no NAT + no keep-alive keep this", DIM, 9.5, anchor="middle")
text(680, OY + 132, "1:1 and unambiguous", DIM, 9.5, anchor="middle")

# drawn here, after the ground-truth panel, so the panel does not cover it
add(f'<path d="M 890 {MY + MH} L 890 646 L 1084 646 L 1084 {OY + 58}" fill="none" '
    f'stroke="{VIOLET}" stroke-width="1.8" stroke-dasharray="5 4" '
    f'marker-end="url(#a-{VIOLET[1:]})"/>')

arrow(466, OY + 105, 500, OY + 105, TRUST, width=2)
arrow(894, OY + 105, 860, OY + 105, VIOLET, width=2)

arrow(TX + 100, TY + TH, 180, OY, TRUST, dash="5 4", width=1.8)

# ---------------------------------------------------------------- footer
text(42, 836, "VERIFIED BY  make verify", INK, 10.5, "700", ls=1.4)
checks = [
    "flow events received",
    "session_close received",
    "≥3 distinct source IPs",
    "AppSecure classified",
    "join rate ≥ 98%",
]
cx = 250
for c in checks:
    text(cx, 836, "✓ " + c, GREEN, 10)
    cx += 200

text(42, 866, "Interfaces are attached one at a time by csrx/launch.sh — docker does not guarantee "
              "attach order, and cSRX maps eth0/1/2 positionally.", DIM, 9.5)
text(42, 884, "Addressing comes from TRUST_PREFIX / MGMT_PREFIX / UNTRUST_PREFIX in .env; the values "
              "shown are the defaults.", DIM, 9.5)

add('</svg>')
open("topology.svg", "w").write("\n".join(out))
print(f"topology.svg written: {sum(len(o) for o in out)} bytes")
