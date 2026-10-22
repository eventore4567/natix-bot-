"""Generate NATIX original graphic assets; no copied logo or trademark art."""
import io
import random
import re
from PIL import Image,ImageDraw
import discord

CATEGORIES=[
    ("nitro","💎 Nitro Boost","Abonnements et services Nitro"),
    ("decor","✨ Discord Decoration","Décorations et profils Discord"),
    ("boost","🚀 Server Boost","Boosts pour serveurs Discord"),
    ("bots","⚙️ Custom Bots","Création de bots personnalisés"),
    ("food","🛍️ Fastfood","Services rapides"),
    ("other","📁 Autres","Autres offres et services"),
]
PANELS={
    "home":"Accueil","shop":"Boutique","support":"Support","giveaways":"Giveaways",
    "stats":"Statistiques","social":"Réseaux","terms":"Règlement",
    "trade":"Échanges","promo":"Promotions",
}
TICKET_TYPES={
    "support":"Support","seller":"Candidature vendeur","staff":"Candidature staff",
    "report":"Signalement","trade":"Échange","promo":"Promotion","order":"Commande",
    "partner":"Partenariat",
}
PLANS=[("basic","Basic","10€ · 7 jours"),("standard","Standard","20€ · 14 jours"),
       ("premium","Premium","30€ · 21 jours"),("lifetime","Lifetime","45€ · À vie")]

def safe(text,limit=120):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(text)))[:limit]

def banner(title="NATIX",subtitle="PREMIUM DISCORD SHOP"):
    """High contrast 1400×420 banner, vector-drawn to work without system fonts.

    The previous banner relied on external fonts. Railway's default fallback
    reduced NATIX to 10-pixel letters. This logo uses fixed geometry instead.
    """
    W,H=1400,420
    im=Image.new("RGB",(W,H),"#08090D")
    d=ImageDraw.Draw(im)
    rng=random.Random(2032)

    # Subtle ink/manga composition restricted to the left and right edges.
    for mirror in (False,True):
        def pt(x,y):
            return ((W-x) if mirror else x,y)
        # Sharp illustration-inspired layers and abstract character silhouette.
        for i in range(9):
            y=i*54-60
            xend=180+rng.randrange(20,85)
            shade=rng.choice(["#17191F","#242630","#363943","#5D606A","#A5A8B3","#DFE1E8"])
            d.polygon([pt(0,y),pt(xend,y+30),pt(60,y+80)],fill=shade)
        # Rounded hood/head profile silhouette, no copied character assets.
        d.ellipse((70,83,235,250) if not mirror else (W-235,83,W-70,250),fill="#22252D")
        d.polygon([pt(56,250),pt(190,204),pt(280,420),pt(0,420)],fill="#30343C")
        d.polygon([pt(90,155),pt(145,117),pt(235,183),pt(155,170)],fill="#A3A6AE")
        d.polygon([pt(130,194),pt(214,176),pt(181,201)],fill="#F0F1F4")
        for j in range(8):
            y=20+j*52
            d.line((pt(12,y),pt(240+(j%3)*35,y-36)),
                   fill="#5C606A",width=2)

    # Center: clean, dark reading zone and modest silver ornamental frame.
    d.rounded_rectangle((260,64,1140,350),radius=22,fill="#090B10",
                        outline="#4D505C",width=2)
    d.line((300,92,1100,92),fill="#717582",width=2)
    d.line((300,310,1100,310),fill="#717582",width=2)
    d.polygon([(700,66),(716,84),(700,99),(684,84)],fill="#E7E8EE")
    d.polygon([(700,322),(712,335),(700,348),(688,335)],fill="#7C8190")

    # Guaranteed LARGE logo: 5 vector glyphs, independent of installed fonts.
    glyphs={
        "N":[[(4,172),(4,4),(123,172),(123,4)]],
        "A":[[(4,172),(64,4),(124,172)],[(28,116),(101,116)]],
        "T":[[(3,4),(125,4)],[(64,4),(64,172)]],
        "I":[[(18,4),(108,4)],[(64,4),(64,172)],[(18,172),(108,172)]],
        "X":[[(5,4),(123,172)],[(123,4),(5,172)]],
    }
    x0=345
    y0=113
    for ix,letter in enumerate("NATIX"):
        x=x0+ix*148
        for part in glyphs[letter]:
            coords=[(x+px,y0+py) for px,py in part]
            shadow=[(px+5,py+7) for px,py in coords]
            d.line(shadow,fill="#0A0B10",width=43,joint="curve")
            d.line(coords,fill="#676D79",width=32,joint="curve")
            d.line(coords,fill="#F5F6FB",width=25,joint="curve")
    # Mark deliberately centered below, no font dependency for the wordmark.
    # Tiny secondary decorations are not used to carry the brand name.
    d.line((440,362,960,362),fill="#BFC3CC",width=2)
    d.polygon([(700,355),(709,362),(700,369),(691,362)],fill="#EDEEF5")

    out=io.BytesIO()
    im.save(out,format="PNG",optimize=True)
    out.seek(0)
    return out

