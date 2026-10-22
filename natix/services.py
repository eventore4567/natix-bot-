"""Business workflows. Every button leads to a real, permission-checked action."""
import io
import logging
import re
import secrets
import time
import discord
from discord import ui

from .assets import CATEGORIES,PLANS,TICKET_TYPES,safe
from .panels import CatalogView,GiveawayPanel,MemberSelect,TicketControls,Panel

LOG=logging.getLogger("natix.services")
ORDER_STATES=("pending","accepted","processing","delivered","cancelled")
HANDLERS={}

def store(i):
    return i.client.store

def is_staff(i):
    user=i.user
    if not isinstance(user,discord.Member):return False
    if user.guild_permissions.manage_guild or user.guild_permissions.administrator:
        return True
    staff_id=store(i).settings(i.guild_id)["staff"]
    return bool(staff_id and any(role.id==staff_id for role in user.roles))

async def respond(i,message,**kwargs):
    if i.response.is_done():
        return await i.followup.send(message,ephemeral=True,**kwargs)
    return await i.response.send_message(message,ephemeral=True,**kwargs)

async def audit(i,what,details=""):
    db=store(i)
    db.audit(i.guild_id or 0,i.user.id,what,details)
    conf=db.settings(i.guild_id or 0)
    channel=i.guild.get_channel(conf["logs"]) if i.guild and conf["logs"] else None
    if channel:
        try:
            await channel.send("✦ **NATIX Audit** · "+safe(what,60)+"\n"
                               "Auteur : <@"+str(i.user.id)+"> · "+safe(details,500),
                               allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden,discord.HTTPException):
            LOG.exception("Audit delivery failed")

async def create_ticket(i,kind,details=""):
    if not i.guild or kind not in TICKET_TYPES:
        return await respond(i,"Ticket invalide ou serveur introuvable.")
    db=store(i)
    conf=db.settings(i.guild_id)
    role=i.guild.get_role(conf["staff"]) if conf["staff"] else None
    if role is None:
        return await respond(i,"La boutique n'est pas encore configurée. Un administrateur doit utiliser /setup.")
    existing=db.active_ticket(i.guild_id,i.user.id,kind)
    if existing and (channel:=i.guild.get_channel(existing["channel"])):
        if details:
            await channel.send("**Nouvelle demande** · "+safe(details,800),
                               allowed_mentions=discord.AllowedMentions.none())
        await respond(i,"Tu possèdes déjà un ticket : "+channel.mention)
        return channel
    if not i.response.is_done():
        await i.response.defer(thinking=True,ephemeral=True)
    allow={
        i.guild.default_role:discord.PermissionOverwrite(view_channel=False),
        i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True),
        role:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True),
    }
    me=i.guild.me
    if me:
        allow[me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,
                read_message_history=True,manage_channels=True,manage_permissions=True)
    parent=i.guild.get_channel(conf["category"])
    if not isinstance(parent,discord.CategoryChannel):parent=None
    nick=re.sub("[^a-z0-9-]","",i.user.name.lower().replace("_","-"))[:14] or "member"
    try:
        chan=await i.guild.create_text_channel("nx-"+kind+"-"+nick,category=parent,
            overwrites=allow,topic="NATIX "+kind+" | owner:"+str(i.user.id),
            reason="NATIX "+kind+" ticket")
        db.create_ticket(chan.id,i.guild_id,i.user.id,kind)
        await chan.send(view=TicketControls())
        await chan.send("**"+TICKET_TYPES[kind]+"**\nCréateur : <@"+str(i.user.id)+">"
             +("\n\n"+safe(details,1800) if details else ""),
            allowed_mentions=discord.AllowedMentions.none())
        await audit(i,"ticket:open",str(chan.id)+" / "+kind)
        await respond(i,"✅ Ticket ouvert : "+chan.mention)
        return chan
    except discord.Forbidden:
        return await respond(i,"Je n'ai pas la permission de créer les salons de tickets.")
    except discord.HTTPException:
        LOG.exception("Create ticket error")
        return await respond(i,"Discord n'a pas pu créer ton ticket.")

async def add_ticket_member(i,member):
    if not is_staff(i):return await respond(i,"Réservé au staff.")
    row=store(i).ticket(i.channel_id)
    if not row or row["state"]!="open":
        return await respond(i,"Ce ticket n'est pas ouvert.")
    if not isinstance(i.channel,discord.TextChannel):
        return await respond(i,"Salon incompatible.")
    if not isinstance(member,discord.Member):
        member=await i.guild.fetch_member(member.id)
    await i.channel.set_permissions(member,view_channel=True,send_messages=True,
                                    read_message_history=True,reason="NATIX ticket guest")
    await audit(i,"ticket:add",str(member.id)+" in "+str(i.channel_id))
    await respond(i,"Membre ajouté aux permissions du ticket.")

async def transcript_parts(channel):
    """Export the complete accessible channel history in <=7 MB UTF-8 parts.

    Content, embeds and attachment URLs are included. Discord does not provide
    deleted messages or past versions of edited messages through history.
    """
    parts=[]
    current=[]
    size=0
    limit=7_000_000
    async for message in channel.history(limit=None,oldest_first=True):
        attachments="\n".join(
            "Attachment: "+str(a.filename)+" | "+str(a.url)
            for a in message.attachments
        )
        embeds="\n".join(
            "Embed: "+str(e.title or "")+" | "+str(e.description or "")
            for e in message.embeds
        )
        content=message.content or "[no plaintext]"
        entry=(message.created_at.isoformat()+" | "
               +str(message.author.id)+" @"+str(message.author)
               +"\n"+content+"\n"+embeds+"\n"+attachments+"\n\n").encode(
                    "utf-8",errors="replace")
        for i in range(0,len(entry),limit):
            chunk=entry[i:i+limit]
            if current and size+len(chunk)>limit:
                parts.append(b"".join(current))
                current=[];size=0
            current.append(chunk);size+=len(chunk)
    if current:
        parts.append(b"".join(current))
    if not parts:
        parts=[b"No accessible messages in this channel."]
    return parts


async def archive_ticket(i):
    """Archive to a configured staff-only log channel before ticket deletion.

    Refuse deletion if the archive cannot be safely delivered in full.
    """
    db=store(i)
    settings=db.settings(i.guild_id)
    logs=i.guild.get_channel(settings["logs"]) if settings["logs"] else None
    if not isinstance(logs,discord.TextChannel):
        return False,"Configure d'abord un salon de logs avec /setup pour archiver avant suppression."
    if logs.id==i.channel_id:
        return False,"Le salon des logs doit être différent du salon ticket."
    guild_me=i.guild.me
    if not guild_me:
        return False,"Le bot n'est pas accessible dans ce serveur."
    permissions=logs.permissions_for(guild_me)
    if not (permissions.view_channel and permissions.send_messages and permissions.attach_files):
        return False,"Permissions insuffisantes pour envoyer les transcripts dans le salon de logs."
    parts=await transcript_parts(i.channel)
    try:
        for number,part in enumerate(parts,1):
            info=("📜 **Archive NATIX** — ticket : "+str(i.channel_id)
                  +" · "+str(number)+"/"+str(len(parts))
                  +" · staff : <@"+str(i.user.id)+">")
            await logs.send(
                info,file=discord.File(io.BytesIO(part),
                filename=f"natix-ticket-{i.channel_id}-{number}.txt"),
                allowed_mentions=discord.AllowedMentions.none()
            )
    except (discord.Forbidden,discord.HTTPException):
        LOG.exception("Could not archive ticket %s",i.channel_id)
        return False,"L'export a échoué. Le ticket est conservé pour éviter toute perte."
    return True,str(len(parts))+" fichier(s) enregistré(s) dans "+logs.mention


async def export_transcript(i):
    if not is_staff(i):
        return await respond(i,"Le téléchargement du transcript est réservé au staff.")
    if not store(i).ticket(i.channel_id):
        return await respond(i,"Ticket NATIX introuvable.")
    await i.response.defer(thinking=True,ephemeral=True)
    parts=await transcript_parts(i.channel)
    for number,data in enumerate(parts,1):
        await i.followup.send(
            "📜 Transcript "+str(number)+"/"+str(len(parts))+" — historique accessible sur Discord",
            file=discord.File(io.BytesIO(data),
                filename=f"natix-{i.channel_id}-part-{number}.txt"),
            ephemeral=True
        )
    await audit(i,"ticket:transcript",str(i.channel_id)+" parts="+str(len(parts)))


class BuyModal(ui.Modal,title="✦ Commander sur NATIX"):
    quantity=ui.TextInput(label="Quantité",placeholder="1",default="1",max_length=4)
    notes=ui.TextInput(label="Précisions",placeholder="Couleur, option ou autre demande…",
                       style=discord.TextStyle.paragraph,required=False,max_length=500)
    def __init__(self,product):
        super().__init__(timeout=300)
        self.product=product

    async def on_submit(self,i):
        try:
            number=int(self.quantity.value)
            if not 1<=number<=100:raise ValueError()
        except ValueError:
            return await respond(i,"Quantité invalide (entre 1 et 100).")
        db=store(i)
        product=db.product(i.guild_id,self.product["id"])
        if not product or product["stock"]==0 or (product["stock"]>0 and number>product["stock"]):
            return await respond(i,"Produit indisponible ou stock insuffisant.")
        if not db.settings(i.guild_id)["staff"]:
            return await respond(i,"Le service n'a pas encore été configuré avec /setup.")
        details=("**Commande NATIX**\nProduit : "+safe(product["name"],100)
                 +"\nQuantité : "+str(number)+"\nPrix affiché : "+safe(product["price"],50)
                 +"\nDétails : "+safe(self.notes.value,400))
        # Create or find the private ticket before recording the order. Failed
        # channel permissions must not generate a phantom unpaid order.
        channel=await create_ticket(i,"order",details)
        if not isinstance(channel,discord.TextChannel):
            return
        order_id=db.create_order(i.guild_id,i.user.id,product,number,self.notes.value)
        db.attach_order_ticket(i.guild_id,order_id,channel.id)
        await channel.send("📦 **Commande NATIX #"+str(order_id)+" enregistrée**\n"
                           "Le staff doit accepter la commande avant la préparation.",
                           allowed_mentions=discord.AllowedMentions.none())
        await audit(i,"order:created",str(order_id))

class TradeModal(ui.Modal,title="✦ Commencer un échange"):
    offering=ui.TextInput(label="Tu proposes quoi ?",max_length=350)
    requested=ui.TextInput(label="Tu cherches quoi ?",max_length=350)
    details=ui.TextInput(label="Informations complémentaires",style=discord.TextStyle.paragraph,
                         required=False,max_length=350)
    async def on_submit(self,i):
        await create_ticket(i,"trade","**Proposition :** "+safe(self.offering.value,350)
             +"\n**Recherche :** "+safe(self.requested.value,350)
             +"\n**Détails :** "+safe(self.details.value,350))

class VouchModal(ui.Modal,title="✦ Témoignage NATIX"):
    stars=ui.TextInput(label="Note sur 5",placeholder="5",max_length=1)
    review=ui.TextInput(label="Ton avis authentique",style=discord.TextStyle.paragraph,max_length=800)
    async def on_submit(self,i):
        try:
            n=int(self.stars.value)
            if n not in (1,2,3,4,5):raise ValueError()
        except ValueError:
            return await respond(i,"La note doit être comprise entre 1 et 5.")
        db=store(i)
        last=db.one("SELECT created FROM reviews WHERE guild=? AND author=? ORDER BY id DESC LIMIT 1",
                    (i.guild_id,i.user.id))
        if last and int(time.time())-last["created"]<86400:
            return await respond(i,"Un avis maximum par jour.")
        db.execute("INSERT INTO reviews(guild,author,rating,comment,created,approved) VALUES (?,?,?,?,?,0)",
                  (i.guild_id,i.user.id,n,self.review.value,int(time.time())))
        await respond(i,"Ton témoignage est enregistré, en attente de validation du staff.")

async def show_category(i,cat,page=0,edit=False):
    db=store(i)
    if cat not in [x[0] for x in CATEGORIES]:
        return await respond(i,"Catégorie inconnue.")
    page=max(0,min(int(page),10000))
    products,total=db.products_page(i.guild_id,cat,page,page_size=6)
    if not total:
        return await respond(i,"Aucun produit disponible dans cette catégorie.")
    if not products:
        return await respond(i,"Cette page du catalogue n'existe plus.")
    view=CatalogView(products,cat,page,total)
    if edit:
        return await i.response.edit_message(view=view)
    return await i.response.send_message(view=view,ephemeral=True)

async def ticket_action(i,key):
    db=store(i)
    row=db.ticket(i.channel_id)
    if not row:return await respond(i,"Ceci n'est pas un salon ticket NATIX.")
    if key=="transcript":return await export_transcript(i)
    if key=="add":
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        view=ui.View(timeout=180);view.add_item(MemberSelect())
        return await i.response.send_message("Ajoute un membre :",view=view,ephemeral=True)
    if key=="status":
        claimer=("<@"+str(row["claimed_by"])+">" if row["claimed_by"] else "Non attribué")
        return await respond(i,"Ticket **"+row["state"]+"** · Type : "+row["kind"]+
                             " · Propriétaire : <@"+str(row["owner"])+"> · Responsable : "+claimer)
    if key=="claim":
        if not is_staff(i):
            return await respond(i,"Réservé au staff.")
        if row["state"]!="open":
            return await respond(i,"Ce ticket est fermé.")
        if not db.claim_ticket(i.channel_id,i.user.id):
            return await respond(i,"Ce ticket est déjà pris en charge par <@"+
                                 str(row["claimed_by"])+">.")
        await audit(i,"ticket:claimed",str(i.channel_id)+" by "+str(i.user.id))
        return await i.response.send_message(
            "🛡️ Ticket pris en charge par <@"+str(i.user.id)+">.",
            allowed_mentions=discord.AllowedMentions.none())
    if key=="unclaim":
        if not is_staff(i):
            return await respond(i,"Réservé au staff.")
        can_override=i.user.guild_permissions.manage_guild
        if not db.release_ticket(i.channel_id,i.user.id,override=can_override):
            return await respond(i,"Ce ticket n'est pas attribué à toi, ou est déjà libéré.")
        await audit(i,"ticket:unclaimed",str(i.channel_id))
        return await i.response.send_message("🛡️ Ticket libéré.")
    if key=="close":
        if not is_staff(i) and row["owner"]!=i.user.id:
            return await respond(i,"Tu ne peux pas fermer ce ticket.")
        if row["state"]!="open":return await respond(i,"Ticket déjà fermé.")
        db.state_ticket(i.channel_id,"closed")
        owner=i.guild.get_member(row["owner"])
        if owner:await i.channel.set_permissions(owner,view_channel=False,reason="NATIX ticket closed")
        await audit(i,"ticket:close",str(i.channel_id))
        return await i.response.send_message("🔒 Ticket fermé.")
    if key=="reopen":
        if not is_staff(i):return await respond(i,"Réouverture réservée au staff.")
        if row["state"]=="open":return await respond(i,"Ticket déjà ouvert.")
        owner=i.guild.get_member(row["owner"])
        if owner:
            await i.channel.set_permissions(owner,view_channel=True,send_messages=True,
                                            read_message_history=True,reason="NATIX ticket reopened")
        db.state_ticket(i.channel_id,"open")
        await audit(i,"ticket:reopen",str(i.channel_id))
        return await i.response.send_message("🔓 Ticket rouvert.")

async def supporter(i,key):
    db=store(i);cfg=db.settings(i.guild_id)
    if key=="time":
        return await respond(i,"Le suivi horaire et les récompenses automatiques ne sont pas activés.")
    if not i.guild or not isinstance(i.user,discord.Member):
        return await respond(i,"Vérification réservée aux membres du serveur.")
    if not i.client.intents.presences:
        return await respond(i,"La vérification du statut nécessite Presence Intent sur le bot.")
    prefix=cfg["status"].lower()
    present=any(isinstance(a,discord.CustomActivity) and
         (a.state or a.name or "").lower().startswith(prefix) for a in (i.user.activities or []))
    if not present:
        return await respond(i,"Le statut n'a pas été détecté. Vérifie ton statut personnalisé et sa visibilité.")
    rid=cfg["supporter_role"]
    role=i.guild.get_role(rid) if rid else None
    if not role:return await respond(i,"Statut vérifié, mais aucun rôle supporter n'est configuré.")
    await i.user.add_roles(role,reason="NATIX supporter verified")
    await respond(i,"✅ Statut vérifié et rôle attribué.")
    await audit(i,"supporter:verified",str(i.user.id))

async def give_action(i,key):
    db=store(i);g=db.giveaway(i.message.id)
    if not g:return await respond(i,"Giveaway introuvable.")
    if key=="participants":
        return await respond(i,str(len(db.giveaway_entries(i.message.id)))+" participant(s).")
    if g["closed"] or int(time.time())>=g["ends"]:
        return await respond(i,"Ce concours est terminé.")
    joined=db.toggle_entry(i.message.id,i.user.id)
    await respond(i,"🎁 Participation "+("enregistrée !" if joined else "retirée."))
    try:
        await i.message.edit(view=GiveawayPanel(g["prize"],False,len(db.giveaway_entries(i.message.id))))
    except discord.HTTPException:
        LOG.warning("Could not refresh giveaway card")

async def review_action(i,key):
    db=store(i)
    if key=="results":
        rows=db.many("SELECT yes,COUNT(*) n FROM votes WHERE message=? GROUP BY yes",(i.message.id,))
        votes={r["yes"]:r["n"] for r in rows}
        return await respond(i,"✅ **"+str(votes.get(1,0))+"** satisfaits · ❌ **"+
                             str(votes.get(0,0))+"** insatisfaits")
    db.execute("INSERT OR REPLACE INTO votes(message,member,yes) VALUES (?,?,?)",
               (i.message.id,i.user.id,int(key)))
    await respond(i,"Merci, ton vote est enregistré.")

async def dispatch(i,key):
    try:
        if not i.guild:return await respond(i,"Commande disponible dans un serveur uniquement.")
        if key.startswith("custom:"):
            try: item_id=int(key[7:])
            except ValueError:return await respond(i,"Bouton invalide.")
            r=store(i).one("""SELECT ci.*,cp.guild,cp.active FROM custom_items ci
                JOIN custom_panels cp ON cp.id=ci.panel_id WHERE ci.id=?""",(item_id,))
            if not r or not r["active"] or r["guild"]!=i.guild_id:
                return await respond(i,"Ce panneau a été désactivé.")
            if r["action_kind"]=="ticket":
                return await create_ticket(i,r["action_value"])
            if r["action_kind"]=="category":
                return await show_category(i,r["action_value"])
            return await respond(i,"Action non configurée.")
        if key.startswith("catalog:"):
            parts=key.split(":")
            if len(parts)!=3 or not parts[2].isdigit():
                return await respond(i,"Page du catalogue invalide.")
            return await show_category(i,parts[1],int(parts[2]),edit=True)
        if key.startswith("category:"):return await show_category(i,key.split(":",1)[1])
        if key.startswith("product:"):
            p=store(i).product(i.guild_id,int(key.split(":")[1]))
            if not p or p["stock"]==0:return await respond(i,"Ce produit n'est plus disponible.")
            return await i.response.send_modal(BuyModal(p))
        if key.startswith("ticket:"):
            action=key[7:]
            if action in TICKET_TYPES:
                return await create_ticket(i,action)
            return await ticket_action(i,action)
        if key.startswith("plan:"):
            plan=next((p for p in store(i).promo_plans(i.guild_id) if p[0]==key[5:]),None)
            if plan:return await create_ticket(i,"promo","Formule : "+plan[1]+" · "+plan[2])
        if key=="trade:history":
            rows=store(i).many("SELECT channel,state FROM tickets WHERE guild=? AND owner=? AND kind='trade' LIMIT 10",
                               (i.guild_id,i.user.id))
            return await respond(i,"\n".join("<#"+str(r["channel"])+"> — "+r["state"] for r in rows)
                                 if rows else "Aucun échange enregistré.")
        if key=="trade:start":return await i.response.send_modal(TradeModal())
        if key.startswith("supporter:"):return await supporter(i,key[10:])
        if key.startswith("review:"):return await review_action(i,key[7:])
        if key.startswith("give:"):return await give_action(i,key[5:])
        if key=="stats:refresh":
            cfg=store(i).metrics(i.guild_id)
            return await respond(i,"📊 **NATIX** · Produits : "+str(cfg["products"])+
                       " · Commandes : "+str(cfg["orders"])+" · Tickets : "+str(cfg["open_tickets"]))
        if key=="vouch:create":return await i.response.send_modal(VouchModal())
        if key=="vouch:list":
            rows=store(i).many("SELECT author,rating,comment FROM reviews WHERE guild=? AND approved=1 ORDER BY id DESC LIMIT 5",
                                (i.guild_id,))
            return await respond(i,"\n\n".join("⭐ "+str(r["rating"])+"/5 · <@"+str(r["author"])+"> : "+
                  safe(r["comment"],300) for r in rows) if rows else "Aucun avis publié.")
        return await respond(i,"Action inconnue.")
    except discord.Forbidden:
        return await respond(i,"Permissions Discord insuffisantes.")
    except discord.HTTPException:
        LOG.exception("Discord API error")
        return await respond(i,"Une erreur Discord empêche cette action.")
    except Exception:
        LOG.exception("NATIX interaction failed: %s",key)
        return await respond(i,"Erreur temporaire. Réessaie et préviens le staff.")
