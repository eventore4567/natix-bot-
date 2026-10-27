"""Génère les visuels NATIX (bannières, logo, emojis) dans assets/.

Outil de développement uniquement : le bot utilise les PNG déjà générés.
Dépendances : Pillow, cairosvg (pip install cairosvg).
Usage : python tools/build_assets.py
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_TITLE = str(ASSETS / "fonts" / "DelaGothicOne.woff")
FONT_SUB = str(ASSETS / "fonts" / "BebasNeue.woff")
CJK_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]

S = 2                     # supersampling
W, H = 1500, 500          # taille finale de la bannière

SECTIONS = {
    "home": "PREMIUM DISCORD SHOP",
    "shop": "SHOP",
    "exchange": "EXCHANGE",
    "promo": "PROMOTION SLOTS",
    "support": "SUPPORT",
    "reviews": "CUSTOMER REVIEWS",
    "rules": "TERMS OF SERVICE",
    "social": "OFFICIAL LINKS",
    "giveaway": "GIVEAWAYS",
}


# --------------------------------------------------------------------------- formes
def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0],
            u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1])


def leaf(draw, p0, p1, p2, p3, width, fill=255, steps=90):
    """Feuille / flamme au pinceau : épine en Bézier, extrémités effilées."""
    pts = [bezier(p0, p1, p2, p3, i/steps) for i in range(steps+1)]
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        t = i/steps
        a = pts[max(i-1, 0)]
        b = pts[min(i+1, steps)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy/n, dx/n
        # profil asymétrique : ventre vers 40 %, pointe fine
        w = width * (math.sin(math.pi * t) ** 0.85) * (1.15 - 0.55*t)
        left.append((x + nx*w, y + ny*w*0.95))
        right.append((x - nx*w*0.55, y - ny*w*0.55))
    draw.polygon(left + right[::-1], fill=fill)


def branch(draw, start, end, bend, leaves, rng, scale=1.0, flip=False):
    """Gerbe de feuilles : toutes suivent le sens du vent, comme un coup de pinceau."""
    p0, p3 = start, end
    p1 = (start[0] + bend[0], start[1] + bend[1])
    p2 = (end[0] - bend[0]*0.4, end[1] + bend[1]*0.6)
    for k in range(leaves):
        t = 0.04 + 0.92 * k / max(leaves-1, 1)
        x, y = bezier(p0, p1, p2, p3, t)
        ax, ay = bezier(p0, p1, p2, p3, min(t+0.02, 1))
        ang = math.atan2(ay-y, ax-x)
        side = 1 if k % 2 else -1
        if flip:
            side = -side
        a = ang + math.radians(rng.uniform(14, 34)) * side
        L = rng.uniform(250, 380) * scale * (1.0 - 0.25*t)
        tip = (x + math.cos(a)*L, y + math.sin(a)*L)
        curl = math.radians(rng.uniform(24, 40)) * side
        c1 = (x + math.cos(a-curl*0.5)*L*0.38, y + math.sin(a-curl*0.5)*L*0.38)
        c2 = (x + math.cos(a+curl*0.6)*L*0.78, y + math.sin(a+curl*0.6)*L*0.78)
        leaf(draw, (x, y), c1, c2, tip, rng.uniform(32, 48)*scale)


def speed_lines(draw, cx, cy, rng, inner, count=220):
    for _ in range(count):
        a = rng.uniform(0, 2*math.pi)
        r0 = inner + rng.uniform(0, 160*S)
        r1 = r0 + rng.uniform(260, 900)*S
        g = rng.randint(28, 62)
        draw.line((cx + math.cos(a)*r0, cy + math.sin(a)*r0,
                   cx + math.cos(a)*r1, cy + math.sin(a)*r1),
                  fill=(g, g, g), width=rng.choice((1, 1, 2, 3)))


def halftone(img, side):
    """Trame manga en dégradé sur un bord."""
    d = ImageDraw.Draw(img)
    step = 15*S
    for gx in range(0, 380*S, step):
        for gy in range(0, H*S + step, step):
            off = step/2 if (gy//step) % 2 else 0
            x = gx + off
            f = max(0.0, 1 - x/(380*S))
            r = f * step * 0.42
            if r < 0.6:
                continue
            px = x if side == "left" else W*S - x
            d.ellipse((px-r, gy-r, px+r, gy+r), fill=(34, 34, 38))


# --------------------------------------------------------------------------- bannière
def base_art(seed=7):
    rng = random.Random(seed)
    img = Image.new("RGB", (W*S, H*S), (0, 0, 0))
    halftone(img, "left")
    halftone(img, "right")
    d = ImageDraw.Draw(img)
    speed_lines(d, W*S/2, H*S/2, rng, inner=330*S)

    # Halo sombre central pour garantir la lisibilité du logo.
    glow = Image.new("L", (W*S, H*S), 0)
    ImageDraw.Draw(glow).ellipse((W*S*0.24, H*S*0.12, W*S*0.76, H*S*0.88), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(70*S))
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, glow)

    # Feuillages blancs (style pinceau) : masque séparé puis composé.
    mask = Image.new("L", (W*S, H*S), 0)
    m = ImageDraw.Draw(mask)
    # droite : grande branche qui monte vers le coin supérieur droit
    branch(m, (1150*S, 560*S), (1520*S, 60*S), (120*S, -140*S), 8, rng, scale=S)
    branch(m, (1300*S, 560*S), (1560*S, 300*S), (90*S, -40*S), 4, rng, scale=S*0.75)
    # gauche : gerbe qui descend vers le coin inférieur gauche
    branch(m, (350*S, -60*S), (-20*S, 440*S), (-120*S, 140*S), 8, rng, scale=S, flip=True)
    branch(m, (200*S, -60*S), (-60*S, 200*S), (-90*S, 40*S), 4, rng, scale=S*0.75, flip=True)
    # Protection du centre : les feuilles s'effacent avant le logo.
    clear = Image.new("L", (W*S, H*S), 255)
    ImageDraw.Draw(clear).rounded_rectangle(
        (W*S*0.235, H*S*0.13, W*S*0.765, H*S*0.87), radius=110*S, fill=0)
    clear = clear.filter(ImageFilter.GaussianBlur(16*S))
    mask = Image.composite(mask, Image.new("L", mask.size, 0), clear)

    # Ombre portée grise sous les feuilles pour la profondeur.
    shadow = mask.filter(ImageFilter.GaussianBlur(6*S)).point(lambda v: int(v*0.55))
    img.paste((70, 70, 76), (8*S, 10*S), shadow)
    img.paste((246, 246, 248), (0, 0), mask)

    # Katakana verticaux discrets (ambiance manga).
    cjk = next((f for f in CJK_CANDIDATES if Path(f).exists()), None)
    if cjk:
        font = ImageFont.truetype(cjk, 30*S)
        for text, x in (("ナティックス", 26*S), ("限定ショップ", W*S - 58*S)):
            y = 70*S
            for ch in text:
                d2 = ImageDraw.Draw(img)
                d2.text((x, y), ch, font=font, fill=(150, 150, 156))
                y += 38*S
    return img


def wordmark(img, subtitle):
    d = ImageDraw.Draw(img)
    cx, cy = W*S/2, H*S/2 - 22*S
    title = ImageFont.truetype(FONT_TITLE, 168*S)
    text = "NATIX"
    spacing = 10*S
    widths = [d.textlength(c, font=title) for c in text]
    total = sum(widths) + spacing*(len(text)-1)
    x = cx - total/2
    bbox = d.textbbox((0, 0), text, font=title)
    top = cy - (bbox[3]-bbox[1])/2 - bbox[1]

    layer = Image.new("L", img.size, 0)
    ld = ImageDraw.Draw(layer)
    xx = x
    for c, w_ in zip(text, widths):
        ld.text((xx, top), c, font=title, fill=255)
        xx += w_ + spacing
    # ombre dure décalée (effet encre)
    img.paste((88, 88, 96), (9*S, 9*S), layer)
    # contour noir épais
    outline = layer.filter(ImageFilter.MaxFilter(9))
    img.paste((0, 0, 0), (0, 0), outline)
    img.paste((255, 255, 255), (0, 0), layer)
    # reflet gris sur la moitié basse des lettres (rendu métal / encre)
    grad = Image.new("L", img.size, 0)
    gd = ImageDraw.Draw(grad)
    y0 = int(top + bbox[1] + (bbox[3]-bbox[1])*0.58)
    for y in range(y0, int(top + bbox[3]) + 2):
        gd.line((0, y, img.size[0], y), fill=min(255, int((y-y0)*1.4)))
    shade = Image.composite(grad, Image.new("L", img.size, 0), layer)
    img.paste((178, 178, 186), (0, 0), shade)

    # Sous-titre espacé entre deux filets avec losanges.
    sub = ImageFont.truetype(FONT_SUB, 44*S)
    letters = list(subtitle)
    track = 9*S
    sw = sum(d.textlength(c, font=sub) for c in letters) + track*(len(letters)-1)
    sy = top + bbox[3] + 26*S
    sx = cx - sw/2
    for c in letters:
        d.text((sx, sy), c, font=sub, fill=(214, 214, 220))
        sx += d.textlength(c, font=sub) + track
    ly = sy + 24*S
    gap = 26*S
    line_len = 120*S
    for sgn in (-1, 1):
        x1 = cx + sgn*(sw/2 + gap)
        x2 = x1 + sgn*line_len
        d.line((x1, ly, x2, ly), fill=(150, 150, 158), width=3*S)
        r = 7*S
        d.polygon([(x2, ly-r), (x2+sgn*r, ly), (x2, ly+r), (x2-sgn*r, ly)], fill=(240, 240, 244))


def build_banners():
    art = base_art()
    out = ASSETS / "banners"
    for key, subtitle in SECTIONS.items():
        img = art.copy()
        wordmark(img, subtitle)
        img = img.resize((W, H), Image.LANCZOS)
        img.save(out / f"{key}.png", optimize=True)
        print("banner", key)


# --------------------------------------------------------------------------- logo
def build_logo():
    N = 512*S
    img = Image.new("RGB", (N, N), (0, 0, 0))
    mask = Image.new("L", (N, N), 0)
    m = ImageDraw.Draw(mask)
    c = N/2
    petals = 14
    for k in range(petals):
        a = 2*math.pi*k/petals
        r0, r1 = 92*S, 196*S
        p0 = (c + math.cos(a)*r0, c + math.sin(a)*r0)
        tip_a = a + 0.42
        p3 = (c + math.cos(tip_a)*r1, c + math.sin(tip_a)*r1)
        p1 = (c + math.cos(a+0.05)*(r0+50*S), c + math.sin(a+0.05)*(r0+50*S))
        p2 = (c + math.cos(a+0.30)*(r1-30*S), c + math.sin(a+0.30)*(r1-30*S))
        leaf(m, p0, p1, p2, p3, 22*S)
    img.paste((255, 255, 255), (0, 0), mask)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_TITLE, 120*S)
    bb = d.textbbox((0, 0), "N", font=font)
    d.text((c - (bb[2]+bb[0])/2, c - (bb[3]+bb[1])/2), "N", font=font, fill=(255, 255, 255))
    img = img.resize((512, 512), Image.LANCZOS)
    img.save(ASSETS / "banners" / "logo.png", optimize=True)
    print("logo")


# --------------------------------------------------------------------------- emojis
EMOJIS = {
    "nx_nitro": "gem", "nx_decor": "sparkles", "nx_boost": "rocket", "nx_bots": "cpu",
    "nx_food": "shopping-bag", "nx_other": "folder", "nx_clock": "clock", "nx_gift": "gift",
    "nx_dollar": "circle-dollar-sign", "nx_book": "book-open", "nx_trade": "arrow-left-right",
    "nx_search": "search", "nx_ticket": "ticket", "nx_check": "circle-check", "nx_cross": "circle-x",
    "nx_star": "star", "nx_lock": "lock", "nx_unlock": "lock-open", "nx_userplus": "user-plus",
    "nx_shield": "shield-check", "nx_link": "link", "nx_megaphone": "megaphone", "nx_trash": "trash-2",
    "nx_archive": "archive", "nx_claim": "user-check", "nx_cart": "shopping-cart", "nx_box": "package",
    "nx_info": "info", "nx_home": "house", "nx_file": "file-text", "nx_crown": "crown",
    "nx_heart": "heart", "nx_message": "message-circle", "nx_tag": "tag", "nx_settings": "settings-2",
    "nx_list": "list", "nx_reset": "rotate-ccw",
}


def build_emojis():
    import cairosvg
    import io
    out = ASSETS / "emojis"
    for name, icon in EMOJIS.items():
        svg = (ASSETS / "icons" / f"{icon}.svg").read_text()
        svg = svg.replace('stroke="currentColor"', 'stroke="#FFFFFF"')
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=128, output_height=128)
        Image.open(io.BytesIO(png)).save(out / f"{name}.png", optimize=True)
    print("emojis", len(EMOJIS))


if __name__ == "__main__":
    build_banners()
    build_logo()
    build_emojis()
