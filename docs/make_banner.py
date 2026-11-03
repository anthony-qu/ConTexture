"""GitHub banner (docs/banner.png): the page's dark honeycomb background, the logo, and the one-line
description. Rebuild with the cluster miniconda python (needs cairosvg): python docs/make_banner.py"""
import math, re, sys, cairosvg
LOGO = __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "contexture", "webui", "static", "logo_dark.svg")
BG, LINE, PATCH = "#14152a", "#262857", "#7a5cd0"
TEXT1, TEXT2 = "#eeedf6", "#b6a8ee"

def hexes(W, H, R, patches):
    out = []
    w = math.sqrt(3) * R; h = 1.5 * R
    rows = int(H / h) + 3; cols = int(W / w) + 3
    pts = lambda cx, cy: " ".join(f"{cx + R*math.cos(math.radians(a)):.1f},{cy + R*math.sin(math.radians(a)):.1f}" for a in range(30, 390, 60))
    for r in range(-1, rows):
        for c in range(-1, cols):
            cx = c * w + (w / 2 if r % 2 else 0); cy = r * h
            fill = "none"; op = ""
            for (pc, pr, alpha) in patches:
                if (c, r) == (pc, pr): fill = PATCH; op = f' fill-opacity="{alpha}"'
            out.append(f'<polygon points="{pts(cx, cy)}" fill="{fill}"{op} stroke="{LINE}" stroke-width="1.2"/>')
    return "\n".join(out)

def logo_inner():
    s = open(LOGO).read()
    s = s[s.index("</title>") + 8:]; s = s[:s.rindex("</svg>")]
    return s  # viewBox 0 0 615.4 108

def patch(cells, alphas):
    return [(c, r, a) for (c, r), a in zip(cells, alphas)]

def banner(layout, out, W=1800, H=380, R=26):
    # a soft "breathing" domain of cells top-right and bottom-left, like the page
    P = patch([(35,1),(36,1),(37,1),(35,2),(36,2),(37,2),(36,3),(37,3),(38,2)], [.22,.3,.2,.28,.35,.26,.18,.22,.16]) + \
        patch([(2,8),(3,8),(2,9),(3,9),(4,9),(3,10)], [.18,.24,.22,.3,.18,.16])
    grid = hexes(W, H, R, P)
    text = ("A self-evolving agentic AI system for spatial multi-omics analysis",
            "that adapts to new, unseen assay technologies")
    if layout == "side":
        lh = 112; sc = lh / 108; lw = 615.4 * sc
        x0 = 100; y0 = (H - lh) / 2
        body = f'<g transform="translate({x0},{y0}) scale({sc})">{logo_inner()}</g>'
        tx = x0 + lw + 70
        body += f'<line x1="{tx-35}" y1="{H/2-60}" x2="{tx-35}" y2="{H/2+60}" stroke="{LINE}" stroke-width="2"/>'
        body += f'<text x="{tx}" y="{H/2-8}" font-family="Arial" font-size="28" fill="{TEXT1}">{text[0]}</text>'
        body += f'<text x="{tx}" y="{H/2+34}" font-family="Arial" font-size="28" fill="{TEXT2}">{text[1]}</text>'
    else:  # stacked, centred
        lh = 130; sc = lh / 108; lw = 615.4 * sc
        body = f'<g transform="translate({(W-lw)/2},{70}) scale({sc})">{logo_inner()}</g>'
        body += f'<text x="{W/2}" y="{H-110}" text-anchor="middle" font-family="Arial" font-size="31" fill="{TEXT1}">{text[0]}</text>'
        body += f'<text x="{W/2}" y="{H-66}" text-anchor="middle" font-family="Arial" font-size="31" fill="{TEXT2}">{text[1]}</text>'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="{W}" height="{H}" fill="{BG}"/>
<g opacity="0.9">{grid}</g>
<rect width="{W}" height="{H}" fill="url(#fade)"/>
<defs><radialGradient id="fade" cx="0.5" cy="0.5" r="0.75"><stop offset="0" stop-color="{BG}" stop-opacity="0.55"/><stop offset="1" stop-color="{BG}" stop-opacity="0"/></radialGradient></defs>
{body}
</svg>'''
    open(out + ".svg", "w").write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=out + ".png", output_width=W)
    print("wrote", out + ".png")


banner("side", __import__("os").path.join(__import__("os").path.dirname(__file__), "banner"))
