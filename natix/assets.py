"""Generate NATIX original graphic assets; no copied logo or trademark art."""
import io
import math
import random
import re
from PIL import Image,ImageDraw,ImageFont
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
    "shop":"Boutique","support":"Tickets","trade":"Échanges","promo":"Promotions",
    "terms":"Conditions","supporter":"Supporters","reviews":"Avis","faq":"FAQ",
    "partners":"Partenaires","stats":"Statistiques","vouch":"Témoignages",
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

def font(size):
    for file in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        try:return ImageFont.truetype(file,size)
        except OSError:pass
    return ImageFont.load_default()

def banner(title="NATIX",subtitle="PREMIUM DISCORD MARKETPLACE"):
    im=Image.new("RGB",(1400,420),"#06070B")
    d=ImageDraw.Draw(im)
    r=random.Random(20261022)
    # Asymmetric layered silver wings framing the central NATIX wordmark.
    for side in (0,1):
        for k in range(15):
            x=-90+k*25 if side==0 else 1490-k*25
            factor=1 if side==0 else -1
            y=55+k*22
            p=[(x,y),(x+factor*(190+r.randrange(70)),y-80),
               (x+factor*(280+r.randrange(130)),y+9),
               (x+factor*(130+r.randrange(110)),y+56)]
            value=r.choice([52,87,131,189,233,245])
            d.polygon(p,fill=(value,value,value+min(8,255-value)))
    for i in range(42):
        x=r.randint(0,1400); y=r.randint(0,420)
        d.line((x,y,x+r.randint(-160,160),y+r.randint(-45,45)),
               fill=r.choice(["#1D1D29","#333340","#555561"]),width=r.randint(1,3))
    label=re.sub(r"[^A-Za-z0-9 -]","",title).upper()[:15] or "NATIX"
    f=font(165 if len(label)<9 else 115)
    bounds=d.textbbox((0,0),label,font=f)
    width=bounds[2]-bounds[0]
    x=(1400-width)//2
    d.text((x+10,108+11),label,font=f,fill="#14141B",stroke_width=8,stroke_fill="#07070A")
    d.text((x,108),label,font=f,fill="#F6F6FA",stroke_width=3,stroke_fill="#90909B")
    sf=font(25);sub=subtitle.upper()[:42]
    w=d.textbbox((0,0),sub,font=sf)[2]
    d.text(((1400-w)//2,320),sub,font=sf,fill="#D9D7DF")
    out=io.BytesIO();im.save(out,format="PNG",optimize=True);out.seek(0)
    return out

def emoji(kind):
    im=Image.new("RGBA",(128,128),(0,0,0,0));d=ImageDraw.Draw(im)
    light=(244,244,251,255)
    d.ellipse((6,6,122,122),fill=(8,8,13,255),outline=light,width=4)
    if kind in ("shop","cart"):
        d.rounded_rectangle((30,51,99,99),radius=9,outline=light,width=7)
        d.arc((44,23,85,76),180,360,fill=light,width=7)
    elif kind=="gift":
        d.rectangle((32,55,97,101),outline=light,width=6)
        d.rectangle((26,44,104,59),fill=light)
        d.line((64,45,64,101),fill=light,width=7)
        d.ellipse((40,25,64,47),outline=light,width=5)
        d.ellipse((64,25,89,47),outline=light,width=5)
    elif kind=="ticket":
        d.rounded_rectangle((29,38,99,91),radius=8,outline=light,width=7)
        d.line((64,42,64,88),fill=light,width=5)
    elif kind=="support":
        d.arc((26,25,102,104),180,360,fill=light,width=8)
        d.rounded_rectangle((23,65,40,92),radius=5,fill=light)
        d.rounded_rectangle((88,65,105,92),radius=5,fill=light)
    elif kind=="trade":
        d.arc((24,24,103,103),215,35,fill=light,width=9)
        d.arc((24,24,103,103),35,215,fill=light,width=9)
        d.polygon([(100,25),(111,51),(82,46)],fill=light)
        d.polygon([(28,103),(17,77),(46,83)],fill=light)
    elif kind=="star":
        d.regular_polygon((64,63,42),5,rotation=270,fill=light)
    elif kind=="shield":
        d.polygon([(64,22),(101,38),(95,83),(64,106),(33,83),(27,38)],outline=light,width=7)
        d.line((46,64,59,77,84,50),fill=light,width=7)
    else:
        for k in range(12):
            a=k*math.pi/6
            d.line((64+26*math.cos(a),64+26*math.sin(a),
                    64+44*math.cos(a),64+44*math.sin(a)),fill=light,width=7)
        d.ellipse((51,51,77,77),fill=light)
    out=io.BytesIO();im.save(out,format="PNG");return out.getvalue()

def server_emoji(guild,name,fallback):
    if guild:
        found=discord.utils.get(guild.emojis,name="nx_"+name)
        if found:return found
    return fallback
