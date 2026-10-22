import io
import json
import logging
import os
import random
import re
import sqlite3
import time
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import tasks
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["DISCORD_TOKEN"]
PATH = os.getenv("NATIX_DB_PATH", "/data/natix.sqlite" if Path("/data").is_dir() else "natix.sqlite")
Path(PATH).parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(PATH, isolation_level=None)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS config (guild INTEGER PRIMARY KEY, json TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, category TEXT, name TEXT, details TEXT, price TEXT, stock INTEGER DEFAULT -1, active INTEGER DEFAULT 1)")
db.execute("CREATE TABLE IF NOT EXISTS tickets (channel INTEGER PRIMARY KEY, guild INTEGER, owner INTEGER, kind TEXT, state TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS giveaways (message INTEGER PRIMARY KEY, channel INTEGER, prize TEXT, ends INTEGER, closed INTEGER DEFAULT 0)")
db.execute("CREATE TABLE IF NOT EXISTS entries (message INTEGER, member INTEGER, PRIMARY KEY(message,member))")
db.execute("CREATE TABLE IF NOT EXISTS votes (message INTEGER, member INTEGER, yes INTEGER, PRIMARY KEY(message,member))")

DEFAULT={"staff":0,"category":0,"banner":"","name":"NATIX","color":"E6E4F0",
         "rules":"Payez uniquement par les moyens officiels convenus avec le staff. Ne partagez jamais de mot de passe. Les commandes sont validées dans un ticket.",
         "supporter_role":0,"status":".gg/natix"}
CATS=[("nitro","💎 Nitro Boost"),("decor","✨ Discord Decoration"),("boost","🚀 Server Boost"),("bots","⚙️ Custom Bots"),("food","🛍️ Fastfood"),("other","📁 Autres")]
TICKETS={"support":"Assistance","seller":"Candidature vendeur","staff":"Candidature staff","report":"Signalement","trade":"Échange","promo":"Promotion","order":"Commande"}
PANELS={"shop":"Boutique","support":"Support","trade":"Échanges","promo":"Promotions","terms":"Conditions","supporter":"Supporters","reviews":"Avis"}
PLANS=[("basic","Basic","10€ · 7 jours"),("standard","Standard","20€ · 14 jours"),("premium","Premium","30€ · 21 jours"),("lifetime","Lifetime","45€ · À vie")]

def config(gid):
    r=db.execute("SELECT json FROM config WHERE guild=?",(gid,)).fetchone()
    return {**DEFAULT,**(json.loads(r["json"]) if r else {})}

def save(gid,**kwargs):
    c=config(gid); c.update(kwargs)
    db.execute("INSERT OR REPLACE INTO config VALUES (?,?)",(gid,json.dumps(c,ensure_ascii=False)))

def safe(s,n=120):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(s)))[:n]

def staff(i):
    if not isinstance(i.user,discord.Member): return False
    return i.user.guild_permissions.manage_guild or any(r.id==config(i.guild_id)["staff"] for r in i.user.roles)

async def reply(i,text):
    if i.response.is_done(): await i.followup.send(text,ephemeral=True)
    else: await i.response.send_message(text,ephemeral=True)

def natix_banner(title):
    im=Image.new("RGB",(1200,340),"#060609");d=ImageDraw.Draw(im)
    rng=random.Random(42)
    for k in range(28):
        x=rng.randint(0,1200);y=rng.randint(0,340)
        d.line((x,y,x+rng.randint(100,330),y-rng.randint(0,130)),fill="#2D2D34",width=2)
    for k in range(9):
        d.polygon([(0,k*34),(270+k*9,k*14),(170+k*12,k*33+58)],fill="#ECECF0" if k%2 else "#8D8D99")
        d.polygon([(1200,k*34),(930-k*9,k*14),(1030-k*12,k*33+58)],fill="#ECECF0" if k%2 else "#8D8D99")
    try: font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",150)
    except OSError: font=ImageFont.load_default()
    title=re.sub(r"[^A-Za-z0-9 -]","",title)[:14].upper() or "NATIX"
    w=d.textbbox((0,0),title,font=font)[2]
    d.text(((1200-w)//2,80),title,font=font,fill="#FFFFFF",stroke_width=3,stroke_fill="#101013")
    d.text((398,286),"PREMIUM DISCORD MARKETPLACE",fill="#E7E3EC")
    buf=io.BytesIO();im.save(buf,format="PNG");buf.seek(0);return buf

def emoji_image(kind):
    im=Image.new("RGBA",(128,128));d=ImageDraw.Draw(im); white=(255,255,255,255)
    d.ellipse((8,8,120,120),fill=(8,8,12,255),outline=white,width=5)
    if kind=="gift":
        d.rectangle((30,55,98,101),outline=white,width=7);d.rectangle((23,43,105,57),fill=white)
        d.line((64,43,64,101),fill=white,width=7)
    elif kind=="shop":
        d.rounded_rectangle((30,49,98,99),radius=8,outline=white,width=7)
        d.arc((44,23,84,75),180,360,fill=white,width=7)
    elif kind=="support":
        d.arc((25,23,103,102),185,355,fill=white,width=8)
        d.rounded_rectangle((22,61,39,92),radius=4,fill=white)
        d.rounded_rectangle((89,61,106,92),radius=4,fill=white)
    else:
        d.regular_polygon((64,64,40),5,rotation=270,outline=white)
        d.ellipse((53,53,75,75),fill=white)
    buf=io.BytesIO();im.save(buf,format="PNG");return buf.getvalue()

def icon(guild,kind,default):
    return discord.utils.get(guild.emojis,name="nx_"+kind) or default if guild else default

def line(content):
    return ui.TextDisplay(content)

class Act(ui.Button):
    def __init__(self,label,key,emoji=None,style=discord.ButtonStyle.secondary):
        super().__init__(label=label,custom_id="natix:"+key,emoji=emoji,style=style)
        self.key=key
    async def callback(self,i):
        await interact(i,self.key)

class ShopSelect(ui.Select):
    def __init__(self):
        super().__init__(custom_id="natix:shopselect",placeholder="Choisir une catégorie",
                         options=[discord.SelectOption(label=name,value=key) for key,name in CATS])
    async def callback(self,i):
        await show_catalog(i,self.values[0])

class AddUser(ui.UserSelect):
    def __init__(self):
        super().__init__(custom_id="natix:adduser",placeholder="Ajouter un membre",min_values=1,max_values=1)
    async def callback(self,i):
        if not staff(i): return await reply(i,"Réservé au staff.")
        if not db.execute("SELECT 1 FROM tickets WHERE channel=? AND state='open'",(i.channel_id,)).fetchone():
            return await reply(i,"Ticket introuvable ou fermé.")
        member=self.values[0]
        await i.channel.set_permissions(member,view_channel=True,send_messages=True,read_message_history=True)
        await reply(i,"Accès accordé.")

class Panel(ui.LayoutView):
    def __init__(self,kind,guild=None):
        super().__init__(timeout=None)
        c=config(guild.id) if guild else DEFAULT
        accent=int(c["color"].strip("#"),16)
        frame=ui.Container(accent_colour=discord.Colour(accent))
        if kind!="reviews":
            frame.add_item(ui.MediaGallery(discord.MediaGalleryItem(media=c["banner"] or "attachment://natix_banner.png")))
        if kind=="shop":
            frame.add_item(line("## 🛒 NATIX · Boutique\nChoisis une catégorie puis un produit pour ouvrir un ticket de commande."))
            for key,name in CATS[:4]:
                frame.add_item(ui.Separator())
                frame.add_item(ui.Section(line("**"+name+"**\nDécouvrir les produits"),accessory=Act("Voir","cat:"+key,icon(guild,"shop","🛍️"))))
            frame.add_item(ui.ActionRow(ShopSelect()))
        elif kind=="support":
            frame.add_item(line("## 🎧 Support NATIX\nChoisis une catégorie pour ouvrir un ticket privé."))
            for key,name in list(TICKETS.items())[:4]:
                frame.add_item(ui.Separator())
                frame.add_item(ui.Section(line("**"+name+"**\nDemande privée au staff"),accessory=Act("Ouvrir","ticket:"+key,icon(guild,"support","🎟️"))))
            frame.add_item(line("-# Tout ticket est privé et soumis aux règles du serveur."))
        elif kind=="trade":
            frame.add_item(line("## ⇄ Welcome To NATIX Exchange\nNos échanges se déroulent dans des tickets privés."))
            frame.add_item(ui.ActionRow(Act("Start A Trade","ticket:trade","🔄",discord.ButtonStyle.primary),Act("Previous Trades","history","🕒")))
        elif kind=="promo":
            frame.add_item(line("## 📦 Promotion Slots\n> Salon dédié à ton nom\n> Diffusion validée par le staff\n> Choisis un plan pour ouvrir ton ticket"))
            for key,name,detail in PLANS:
                frame.add_item(ui.Separator())
                frame.add_item(ui.Section(line("**"+name+"**\n"+detail),accessory=Act("Choisir","plan:"+key,icon(guild,"shop","💰"))))
            frame.add_item(line("-# Les pings ne sont jamais envoyés automatiquement."))
        elif kind=="terms":
            frame.add_item(line("## 📜 NATIX · Terms of Service"))
            frame.add_item(ui.Separator())
            frame.add_item(line(c["rules"][:3000]))
            frame.add_item(ui.ActionRow(Act("Ouvrir le support","ticket:support","🎧")))
        elif kind=="supporter":
            frame.add_item(line("## 🎁 NATIX Supporters\n**Conditions**\n> Statut Discord commençant par "+safe(c["status"],60)+"\n> Activité visible aux bots"))
            frame.add_item(ui.ActionRow(Act("Verify","verify","✅",discord.ButtonStyle.success),Act("Check Time","checktime","🕒")))
        elif kind=="reviews":
            frame.add_item(line("## ✦ NATIX · Vos avis\nLes votes reflètent les vraies réponses des membres."))
            frame.add_item(ui.ActionRow(Act("Oui","vote:1","✅",discord.ButtonStyle.success),Act("Non","vote:0","❌",discord.ButtonStyle.danger),Act("Résultats","results","📊")))
        self.add_item(frame)

class TicketControls(ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        f=ui.Container(accent_colour=discord.Colour(0xD4C2FF))
        f.add_item(line("## 🎟️ NATIX · Gestion de ticket\nActions disponibles ci-dessous."))
        f.add_item(ui.ActionRow(Act("Fermer","close","🔒",discord.ButtonStyle.danger),Act("Rouvrir","reopen","🔓"),Act("Transcript","transcript","📄"),Act("Ajouter","add","➕")))
        self.add_item(f)

class GiveView(ui.LayoutView):
    def __init__(self,prize="Concours",ended=False):
        super().__init__(timeout=None)
        c=ui.Container(accent_colour=discord.Colour(0x7779EF))
        c.add_item(line("## 🎁 "+safe(prize)+"\n"+("Concours terminé" if ended else "Participe au giveaway NATIX !")))
        c.add_item(ui.ActionRow(Act("Participer","givejoin","🎁",discord.ButtonStyle.primary),Act("Participants","givelist","🔎")))
        self.add_item(c)

class BuyModal(ui.Modal,title="Commander sur NATIX"):
    amount=ui.TextInput(label="Quantité",default="1",max_length=3)
    note=ui.TextInput(label="Précisions",style=discord.TextStyle.paragraph,required=False,max_length=400)
    def __init__(self,product):
        super().__init__();self.product=product
    async def on_submit(self,i):
        try:
            n=int(self.amount.value)
            if not 1<=n<=100: raise ValueError
        except ValueError: return await reply(i,"Quantité invalide.")
        if self.product["stock"]>=0 and n>self.product["stock"]:
            return await reply(i,"Stock insuffisant.")
        await ticket(i,"order","Produit : "+safe(self.product["name"])+"\nQuantité : "+str(n)+"\n"+safe(self.note.value,400))

async def show_catalog(i,category):
    p=db.execute("SELECT * FROM products WHERE guild=? AND category=? AND active=1 ORDER BY id DESC LIMIT 8",(i.guild_id,category)).fetchall()
    if not p: return await reply(i,"Aucun produit disponible dans cette catégorie.")
    frame=ui.Container(accent_colour=discord.Colour(0xC7B4FF));frame.add_item(line("## 🛒 Produits NATIX"))
    for item in p:
        frame.add_item(ui.Separator())
        b=Act("Commander","buy:"+str(item["id"]),"🛒",discord.ButtonStyle.primary)
        b.disabled=item["stock"]==0
        frame.add_item(ui.Section(line("**"+safe(item["name"],60)+"**\n"+
                                       safe(item["price"],50)+" · "+safe(item["details"],95)),
                                  accessory=b))
    view=ui.LayoutView(timeout=180);view.add_item(frame)
    await i.response.send_message(view=view,ephemeral=True)

async def ticket(i,kind,details=""):
    if not i.guild: return await reply(i,"Disponible uniquement dans un serveur.")
    current=db.execute("SELECT channel FROM tickets WHERE guild=? AND owner=? AND kind=? AND state='open'",(i.guild_id,i.user.id,kind)).fetchone()
    if current and i.guild.get_channel(current["channel"]):
        return await reply(i,"Ticket déjà ouvert : <#"+str(current["channel"])+">")
    await i.response.defer(ephemeral=True,thinking=True)
    c=config(i.guild_id)
    overwrites={i.guild.default_role:discord.PermissionOverwrite(view_channel=False),
                i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
    if i.guild.me: overwrites[i.guild.me]=discord.PermissionOverwrite(view_channel=True,manage_channels=True,send_messages=True,read_message_history=True)
    role=i.guild.get_role(c["staff"])
    if role: overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
    parent=i.guild.get_channel(c["category"])
    if not isinstance(parent,discord.CategoryChannel): parent=None
    who=re.sub("[^a-z0-9]","",i.user.name.lower())[:10] or "membre"
    chan=await i.guild.create_text_channel("ticket-"+kind+"-"+who,category=parent,overwrites=overwrites,reason="Ticket NATIX")
    db.execute("INSERT OR REPLACE INTO tickets VALUES (?,?,?,?,?)",(chan.id,i.guild_id,i.user.id,kind,"open"))
    await chan.send(view=TicketControls())
    await chan.send("**"+TICKETS.get(kind,kind)+"** · <@"+str(i.user.id)+">"+("\n"+details if details else ""),allowed_mentions=discord.AllowedMentions.none())
    await i.followup.send("✅ Ticket créé : "+chan.mention,ephemeral=True)

async def transcript(i):
    if not staff(i): return await reply(i,"Action réservée au staff.")
    lines=["NATIX · Transcript "+i.channel.name]
    async for m in i.channel.history(limit=1500,oldest_first=True):
        lines.append(m.created_at.isoformat()+" | "+str(m.author.id)+" | "+(m.content or "[composants]")[:8000]+
                     " | "+", ".join(a.url for a in m.attachments))
    data="\n".join(lines).encode("utf-8")[:7_000_000]
    await i.response.send_message(file=discord.File(io.BytesIO(data),filename="natix-transcript.txt"),ephemeral=True)

async def interact(i,key):
    try:
        if key.startswith("cat:"): return await show_catalog(i,key[4:])
        if key.startswith("ticket:"): return await ticket(i,key[7:])
        if key.startswith("plan:"):
            p=next((x for x in PLANS if x[0]==key[5:]),None)
            if p: return await ticket(i,"promo","Plan : "+p[1]+" · "+p[2])
        if key.startswith("buy:"):
            item=db.execute("SELECT * FROM products WHERE guild=? AND id=? AND active=1",(i.guild_id,int(key[4:]))).fetchone()
            if not item or item["stock"]==0: return await reply(i,"Produit indisponible.")
            return await i.response.send_modal(BuyModal(item))
        if key=="history":
            rows=db.execute("SELECT channel,state FROM tickets WHERE owner=? AND guild=? AND kind='trade' LIMIT 10",(i.user.id,i.guild_id)).fetchall()
            return await reply(i,"\n".join("<#"+str(r["channel"])+"> · "+r["state"] for r in rows) if rows else "Aucun échange enregistré.")
        if key in ("close","reopen","transcript","add"):
            r=db.execute("SELECT * FROM tickets WHERE channel=?",(i.channel_id,)).fetchone()
            if not r: return await reply(i,"Ce salon n'est pas un ticket NATIX.")
            if key=="transcript": return await transcript(i)
            if key=="add":
                if not staff(i): return await reply(i,"Réservé au staff.")
                v=ui.View(timeout=180);v.add_item(AddUser())
                return await i.response.send_message("Choisis le membre :",view=v,ephemeral=True)
            if key=="close":
                if not staff(i) and i.user.id!=r["owner"]: return await reply(i,"Accès refusé.")
                db.execute("UPDATE tickets SET state='closed' WHERE channel=?",(i.channel_id,))
                owner=i.guild.get_member(r["owner"])
                if owner: await i.channel.set_permissions(owner,view_channel=False)
                return await i.response.send_message("🔒 Ticket fermé.")
            if not staff(i): return await reply(i,"Réservé au staff.")
            owner=i.guild.get_member(r["owner"])
            if owner: await i.channel.set_permissions(owner,view_channel=True,send_messages=True,read_message_history=True)
            db.execute("UPDATE tickets SET state='open' WHERE channel=?",(i.channel_id,))
            return await i.response.send_message("🔓 Ticket rouvert.")
        if key in ("givejoin","givelist"):
            g=db.execute("SELECT * FROM giveaways WHERE message=?",(i.message.id,)).fetchone()
            if not g: return await reply(i,"Concours introuvable.")
            if key=="givejoin":
                if g["closed"] or time.time()>g["ends"]: return await reply(i,"Concours terminé.")
                old=db.execute("SELECT 1 FROM entries WHERE message=? AND member=?",(i.message.id,i.user.id)).fetchone()
                if old:
                    db.execute("DELETE FROM entries WHERE message=? AND member=?",(i.message.id,i.user.id))
                    return await reply(i,"Participation retirée.")
                db.execute("INSERT INTO entries VALUES (?,?)",(i.message.id,i.user.id))
                return await reply(i,"🎁 Participation enregistrée.")
            count=db.execute("SELECT COUNT(*) AS n FROM entries WHERE message=?",(i.message.id,)).fetchone()["n"]
            return await reply(i,str(count)+" participant(s).")
        if key.startswith("vote:"):
            db.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?)",(i.message.id,i.user.id,int(key[-1])))
            return await reply(i,"Vote enregistré.")
        if key=="results":
            r=db.execute("SELECT yes,COUNT(*) n FROM votes WHERE message=? GROUP BY yes",(i.message.id,)).fetchall()
            counts={x["yes"]:x["n"] for x in r}
            return await reply(i,"✅ "+str(counts.get(1,0))+" · ❌ "+str(counts.get(0,0)))
        if key=="verify":
            status=config(i.guild_id)["status"].lower()
            acts=getattr(i.user,"activities",[]) or []
            ok=any(isinstance(a,discord.CustomActivity) and (a.state or a.name or "").lower().startswith(status) for a in acts)
            if not ok: return await reply(i,"Statut non détecté. Vérifie ton statut et sa visibilité.")
            role=i.guild.get_role(config(i.guild_id)["supporter_role"])
            if role: await i.user.add_roles(role,reason="Supporter NATIX")
            return await reply(i,"✅ Statut vérifié !")
        if key=="checktime":
            return await reply(i,"Le suivi horaire et les vouchers ne sont pas activés. Aucun crédit fictif n'est accordé.")
        return await reply(i,"Action inconnue.")
    except discord.Forbidden:
        await reply(i,"Permissions Discord insuffisantes.")
    except Exception:
        logging.exception("Interaction NATIX")
        await reply(i,"Erreur de traitement. Vérifie les logs.")

intents=discord.Intents.default()
intents.members=os.getenv('NATIX_MEMBERS_INTENT','0')=='1'
intents.presences=os.getenv('NATIX_PRESENCES_INTENT','0')=='1'
bot=discord.Client(intents=intents,allowed_mentions=discord.AllowedMentions.none())
tree=app_commands.CommandTree(bot)

async def publish(i,kind,private=False):
    c=config(i.guild_id)
    file=None if c["banner"] or kind=="reviews" else discord.File(natix_banner(c["name"]),filename="natix_banner.png")
    await i.response.send_message(view=Panel(kind,i.guild),file=file,ephemeral=private)

@tree.command(name="shop",description="Publier la boutique NATIX")
@app_commands.checks.has_permissions(manage_guild=True)
async def shop(i:discord.Interaction): await publish(i,"shop")

@tree.command(name="support",description="Publier les tickets NATIX")
@app_commands.checks.has_permissions(manage_guild=True)
async def support(i:discord.Interaction): await publish(i,"support")

@tree.command(name="trade",description="Publier le panneau d'échanges")
@app_commands.checks.has_permissions(manage_guild=True)
async def trade(i:discord.Interaction): await publish(i,"trade")

@tree.command(name="promo",description="Publier les abonnements promotionnels")
@app_commands.checks.has_permissions(manage_guild=True)
async def promo(i:discord.Interaction): await publish(i,"promo")

@tree.command(name="rules",description="Publier les conditions de vente")
@app_commands.checks.has_permissions(manage_guild=True)
async def rules(i:discord.Interaction): await publish(i,"terms")

@tree.command(name="supporter",description="Publier le panneau supporters")
@app_commands.checks.has_permissions(manage_guild=True)
async def supporter(i:discord.Interaction): await publish(i,"supporter")

@tree.command(name="reviews",description="Publier les votes d'avis")
@app_commands.checks.has_permissions(manage_guild=True)
async def reviews(i:discord.Interaction): await publish(i,"reviews")

@tree.command(name="preview",description="Prévisualiser un panneau en privé")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(panel=[app_commands.Choice(name=n,value=k) for k,n in PANELS.items()])
async def preview(i:discord.Interaction,panel:app_commands.Choice[str]): await publish(i,panel.value,True)

@tree.command(name="setup",description="Régler le rôle staff et la catégorie tickets")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(i:discord.Interaction,staff_role:discord.Role,category:discord.CategoryChannel):
    save(i.guild_id,staff=staff_role.id,category=category.id)
    await reply(i,"✅ Staff et catégorie des tickets configurés.")

@tree.command(name="brand",description="Personnaliser la bannière NATIX")
@app_commands.checks.has_permissions(manage_guild=True)
async def brand(i:discord.Interaction,title:str="NATIX",color:str="E6E4F0",banner_url:str=""):
    if not re.fullmatch("#?[0-9A-Fa-f]{6}",color): return await reply(i,"Couleur hex invalide.")
    if banner_url and not banner_url.startswith("https://"): return await reply(i,"Bannière : URL HTTPS obligatoire.")
    save(i.guild_id,name=title[:14],color=color.strip("#"),banner=banner_url[:1000])
    await reply(i,"✅ Bannière et thème enregistrés pour les prochains panneaux.")

@tree.command(name="terms",description="Modifier le texte des conditions")
@app_commands.checks.has_permissions(manage_guild=True)
async def terms(i:discord.Interaction,text:str):
    save(i.guild_id,rules=text[:3000]);await reply(i,"Conditions modifiées.")

@tree.command(name="supporter_config",description="Définir le rôle et le statut supporter")
@app_commands.checks.has_permissions(manage_guild=True)
async def supporter_config(i:discord.Interaction,role:discord.Role,status_prefix:str=".gg/natix"):
    save(i.guild_id,supporter_role=role.id,status=status_prefix[:80])
    await reply(i,"Supporter configuré.")

products=app_commands.Group(name="product",description="Gérer les produits de la boutique")

@products.command(name="add",description="Ajouter un produit")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(category=[app_commands.Choice(name=n,value=k) for k,n in CATS])
async def add_product(i:discord.Interaction,category:app_commands.Choice[str],name:str,price:str,details:str,stock:int=-1):
    if stock< -1: return await reply(i,"Stock : -1 ou un entier positif.")
    cur=db.execute("INSERT INTO products (guild,category,name,details,price,stock) VALUES (?,?,?,?,?,?)",
                   (i.guild_id,category.value,name[:80],details[:400],price[:40],stock))
    await reply(i,"✅ Produit ajouté : #"+str(cur.lastrowid))

@products.command(name="remove",description="Retirer un produit")
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_product(i:discord.Interaction,id:int):
    r=db.execute("UPDATE products SET active=0 WHERE guild=? AND id=?",(i.guild_id,id))
    await reply(i,"Produit retiré." if r.rowcount else "Produit introuvable.")

@products.command(name="list",description="Lister les produits")
@app_commands.checks.has_permissions(manage_guild=True)
async def list_products(i:discord.Interaction):
    rows=db.execute("SELECT * FROM products WHERE guild=? AND active=1 LIMIT 30",(i.guild_id,)).fetchall()
    await reply(i,"\n".join("#"+str(x["id"])+" "+safe(x["name"],50)+" · "+safe(x["price"],30)+" · stock "+str(x["stock"]) for x in rows)[:1900] or "Aucun produit.")
tree.add_command(products)

@tree.command(name="restock",description="Modifier un stock et publier un réassort")
@app_commands.checks.has_permissions(manage_guild=True)
async def restock(i:discord.Interaction,id:int,stock:int,announce:bool=False):
    if stock< -1: return await reply(i,"Stock invalide.")
    r=db.execute("SELECT name FROM products WHERE guild=? AND id=? AND active=1",(i.guild_id,id)).fetchone()
    if not r: return await reply(i,"Produit introuvable.")
    db.execute("UPDATE products SET stock=? WHERE id=?",(stock,id))
    await reply(i,"Stock mis à jour.")
    if announce: await i.channel.send("📦 **NATIX Restock !**\n"+safe(r["name"])+" : "+str(stock)+" en stock.",allowed_mentions=discord.AllowedMentions.none())

@tree.command(name="giveaway",description="Lancer un giveaway avec tirage")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(i:discord.Interaction,prize:str,duration_minutes:app_commands.Range[int,1,10080]):
    await i.response.send_message(view=GiveView(prize))
    m=await i.original_response()
    db.execute("INSERT INTO giveaways VALUES (?,?,?,?,0)",(m.id,i.channel_id,prize[:120],int(time.time())+duration_minutes*60))

@tree.command(name="ticket_delete",description="Supprimer un ticket fermé")
async def ticket_delete(i:discord.Interaction):
    if not staff(i): return await reply(i,"Réservé au staff.")
    r=db.execute("SELECT state FROM tickets WHERE channel=?",(i.channel_id,)).fetchone()
    if not r or r["state"]!="closed": return await reply(i,"Ferme ce ticket avant de le supprimer.")
    await i.response.send_message("Suppression du ticket…",ephemeral=True)
    db.execute("DELETE FROM tickets WHERE channel=?",(i.channel_id,))
    await i.channel.delete(reason="Suppression ticket NATIX")

@tree.command(name="emojis",description="Créer les emojis NATIX personnalisés")
@app_commands.checks.has_permissions(manage_guild=True)
async def emojis(i:discord.Interaction):
    await i.response.defer(ephemeral=True,thinking=True)
    done=[]
    for kind in ("gift","shop","support","star"):
        if discord.utils.get(i.guild.emojis,name="nx_"+kind): continue
        try:
            await i.guild.create_custom_emoji(name="nx_"+kind,image=emoji_image(kind),reason="Natix icons")
            done.append(kind)
        except (discord.Forbidden,discord.HTTPException): pass
    await i.followup.send("Emojis créés : "+(", ".join(done) if done else "aucun (permissions ou places disponibles à vérifier)"),ephemeral=True)

@tree.command(name="help",description="Afficher les commandes Natix")
async def help_cmd(i:discord.Interaction):
    await reply(i,"**NATIX SHOP**\n/shop · /support · /trade · /promo · /rules · /supporter · /reviews\n"
                "/setup · /brand · /terms · /preview · /product add|remove|list · /restock · /giveaway · /emojis · /ticket_delete")

@tree.error
async def on_cmd_error(i,error):
    logging.warning("Command error: %s",error)
    await reply(i,"Permission insuffisante ou commande indisponible.")

@tasks.loop(seconds=45)
async def end_giveaways():
    games=db.execute("SELECT * FROM giveaways WHERE closed=0 AND ends<=?",(int(time.time()),)).fetchall()
    for g in games:
        db.execute("UPDATE giveaways SET closed=1 WHERE message=?",(g["message"],))
        all_ids=[r["member"] for r in db.execute("SELECT member FROM entries WHERE message=?",(g["message"],))]
        winner=random.SystemRandom().choice(all_ids) if all_ids else None
        channel=bot.get_channel(g["channel"])
        if not channel:
            try: channel=await bot.fetch_channel(g["channel"])
            except discord.HTTPException: continue
        try:
            m=await channel.fetch_message(g["message"])
            await m.edit(view=GiveView(g["prize"],True))
            await channel.send("🏆 **NATIX Giveaway** · "+safe(g["prize"])+
                               "\n"+("<@"+str(winner)+">" if winner else "Aucun participant."),
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException: logging.exception("Giveaway finalization")

@end_giveaways.before_loop
async def before_loop(): await bot.wait_until_ready()

@bot.event
async def on_ready():
    if getattr(bot,"initialized",False): return
    bot.initialized=True
    for panel in PANELS: bot.add_view(Panel(panel))
    bot.add_view(TicketControls());bot.add_view(GiveView())
    try:
        guild_id=os.getenv("DISCORD_GUILD_ID","")
        if guild_id:
            obj=discord.Object(id=int(guild_id));tree.copy_global_to(guild=obj)
            await tree.sync(guild=obj)
        else: await tree.sync()
        logging.info("NATIX ready: %s",bot.user)
    except Exception: logging.exception("Command sync")
    end_giveaways.start()

bot.run(TOKEN)
