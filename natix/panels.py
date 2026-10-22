"""Native Discord Components V2 designs with right-side accessory buttons."""
import re
import discord
from discord import ui
from .assets import CATEGORIES, PANELS, PLANS, TICKET_TYPES, safe, server_emoji

def pack_containers(view, source, colour):
    """Split Discord V2 containers: Discord permits up to 10 direct children each."""
    items=list(source.children)
    for offset in range(0,len(items),10):
        box=ui.Container(accent_colour=colour)
        for child in items[offset:offset+10]:
            box.add_item(child)
        view.add_item(box)

def button_emoji(guild,value):
    """Use a generated NATIX emoji name or an ordinary Unicode emoji."""
    if not value:return "🔹"
    if value.startswith("nx_"):
        return server_emoji(guild,value[3:],"🔹")
    return value

def txt(text):
    return ui.TextDisplay(text)

def sep():
    return ui.Separator()

class ActionButton(ui.Button):
    def __init__(self,label,action,emoji=None,style=discord.ButtonStyle.secondary):
        super().__init__(label=label,custom_id="natix:"+action,emoji=emoji,style=style)
        self.action=action

    async def callback(self,i):
        from .services import dispatch
        await dispatch(i,self.action)

class CategorySelect(ui.Select):
    def __init__(self):
        super().__init__(custom_id="natix:category-select",placeholder="Choisir une catégorie de produits",
            min_values=1,max_values=1,options=[
                discord.SelectOption(label=name,value=key,description=desc[:100])
                for key,name,desc in CATEGORIES
            ])

    async def callback(self,i):
        from .services import show_category
        await show_category(i,self.values[0])

class MemberSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(custom_id="natix:member-select",placeholder="Sélectionner un membre",
                         min_values=1,max_values=1)
    async def callback(self,i):
        from .services import add_ticket_member
        await add_ticket_member(i,self.values[0])

class Panel(ui.LayoutView):
    def __init__(self,kind,store,guild=None):
        super().__init__(timeout=None)
        s=store.settings(guild.id) if guild else store.settings(0)
        try: accent=discord.Colour(int(s["color"].strip("#"),16))
        except (ValueError,TypeError): accent=discord.Colour(0xE6E4F0)
        frame=ui.Container(accent_colour=accent)
        if kind!="reviews":
            frame.add_item(ui.MediaGallery(discord.MediaGalleryItem(
                media=s.get("banner") or "attachment://natix_banner.png")))
        if kind=="home":
            frame.add_item(txt("## NATIX  •  ACCUEIL\n**Marketplace Discord premium**\n"
                 "Choisis un service ci-dessous. Chaque bouton ouvre un vrai menu."))
            frame.add_item(sep())
            for key,name,desc in CATEGORIES[:5]:
                frame.add_item(ui.Section(
                    txt("**"+name+"**\n"+desc),
                    accessory=ActionButton("Ouvrir","category:"+key)))
                frame.add_item(sep())
            frame.add_item(txt("**SERVICES & OUTILS**"))
            frame.add_item(ui.ActionRow(
                ActionButton("Boutique","nav:shop"),
                ActionButton("Support","nav:support"),
                ActionButton("Giveaways","nav:giveaways"),
                ActionButton("Échanges","nav:trade"),
                ActionButton("Promos","nav:promo")
            ))
            frame.add_item(ui.ActionRow(
                ActionButton("Statistiques","nav:stats"),
                ActionButton("Réseaux","nav:social"),
                ActionButton("Règlement","nav:terms"),
                ActionButton("Mes commandes","nav:orders")
            ))
        elif kind=="giveaways":
            frame.add_item(txt("## NATIX  •  GIVEAWAYS\nConcours actifs de ce serveur."))
            records=store.many(
                "SELECT message,channel,prize,ends FROM giveaways WHERE closed=0 AND ends>? ORDER BY ends LIMIT 12",
                (__import__("time").time(),)
            )
            shown=0
            for item in records:
                if not guild or not guild.get_channel(item["channel"]):
                    continue
                frame.add_item(sep())
                frame.add_item(ui.Section(
                    txt("**"+safe(item["prize"],100)+"**\nFin : <t:"+str(item["ends"])+":R>"),
                    accessory=ui.Button(label="Voir",style=discord.ButtonStyle.link,
                     url="https://discord.com/channels/"+str(guild.id)+"/"+str(item["channel"])+"/"+str(item["message"]))))
                shown+=1
                if shown>=5:break
            if not shown:
                frame.add_item(txt("Aucun giveaway en cours pour le moment."))
        elif kind=="social":
            frame.add_item(txt("## NATIX  •  RÉSEAUX\nRetrouve uniquement les liens officiels de la boutique."))
            links=[("Discord",s.get("social_discord","")),
                   ("TikTok",s.get("social_tiktok","")),
                   ("Site web",s.get("social_site",""))]
            available=[(name,url) for name,url in links if url]
            if available:
                for name,url in available:
                    frame.add_item(sep())
                    frame.add_item(txt("**"+name+"**\n"+safe(url,190)))
            else:
                frame.add_item(sep())
                frame.add_item(txt("Liens à venir. Le staff peut les configurer avec /manage social."))
        elif kind=="shop":
            frame.add_item(txt("## NATIX  •  BOUTIQUE\n"
                 "Bienvenue dans notre boutique ! Parcours les collections, sélectionne un article et crée une commande privée."))
            for key,name,desc in CATEGORIES[:5]:
                frame.add_item(sep())
                frame.add_item(ui.Section(txt("**"+name+"**\n"+desc),
                    accessory=ActionButton("Ouvrir","category:"+key)))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(CategorySelect()))
            frame.add_item(txt("-# Les tarifs et stocks apparaissent dans les fiches produits."))
        elif kind=="support":
            frame.add_item(txt("## ✦ NATIX • SUPPORT CENTER\n"
                               "Besoin d'aide ou envie de rejoindre l'équipe ? Choisis ton service."))
            for key,desc in [
                ("support","Questions et problèmes liés à la boutique"),
                ("seller","Devenir vendeur dans notre équipe"),
                ("staff","Postuler en tant que membre du staff"),
                ("report","Signaler un incident en toute confidentialité"),
                ("partner","Proposer un partenariat")
            ]:
                frame.add_item(sep())
                frame.add_item(ui.Section(txt("**"+TICKET_TYPES[key]+"**\n"+desc),
                    accessory=ActionButton("Ouvrir","ticket:"+key)))
            frame.add_item(txt("-# Tickets privés • aucun membre mentionné automatiquement."))
        elif kind=="trade":
            frame.add_item(txt("## ⇄ NATIX EXCHANGE\n"
                "**Une transaction encadrée commence ici.**\n"
                "Décris ce que tu proposes et ce que tu cherches dans ton ticket."))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(
                ActionButton("Start a Trade","trade:start",server_emoji(guild,"trade","🔄"),discord.ButtonStyle.primary),
                ActionButton("Previous Trades","trade:history","🕒"),
            ))
            frame.add_item(txt("-# Les échanges ne sont pas exécutés automatiquement."))
        elif kind=="promo":
            frame.add_item(txt("## ✦ NATIX • PROMOTION SLOTS\n"
                  "Promotions soumises à approbation du staff. Choisis une formule."))
            for key,name,price in (store.promo_plans(guild.id) if guild else PLANS):
                frame.add_item(sep())
                frame.add_item(ui.Section(txt("**"+name+"**\n"+price),
                    accessory=ActionButton("Choisir","plan:"+key,server_emoji(guild,"star","⭐"))))
            frame.add_item(sep())
            frame.add_item(txt("**Comment commander ?**\n"
                "1. Sélectionne ton offre\n2. Précise ton serveur dans le ticket\n3. Attends la validation du staff.\n"
                "-# Aucun ping massif ni paiement automatique. Tarifs d'exemple modifiables."))
        elif kind=="terms":
            frame.add_item(txt("## 📜 NATIX • CONDITIONS DE VENTE"))
            frame.add_item(sep())
            frame.add_item(txt(s["rules"][:3000]))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(ActionButton("Contacter le support","ticket:support","🎧")))
        elif kind=="supporter":
            frame.add_item(txt("## ✧ NATIX • SUPPORTERS\n"
                "Merci de soutenir notre boutique !\n"
                "**Statut requis :** commence par "+safe(s["status"],70)+"\n"
                "Active la visibilité de ton activité Discord avant vérification."))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(
                ActionButton("Vérifier","supporter:verify","✅",discord.ButtonStyle.success),
                ActionButton("Vérifier le temps","supporter:time","🕒"),
            ))
            frame.add_item(txt("-# Les crédits automatiques ne sont pas disponibles tant que leur suivi n'est pas activé."))
        elif kind=="reviews":
            frame.add_item(txt("## ✧ NATIX • YOUR OPINION\n"
                "Es-tu satisfait de ton expérience ? Un vote par membre, modifiable."))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(
                ActionButton("Satisfait","review:1","✅",discord.ButtonStyle.success),
                ActionButton("Insatisfait","review:0","❌",discord.ButtonStyle.danger),
                ActionButton("Résultats","review:results","📊")
            ))
        elif kind=="faq":
            frame.add_item(txt("## ❖ NATIX • QUESTIONS FRÉQUENTES"))
            frame.add_item(sep())
            frame.add_item(txt(s["faq"][:2800]))
            frame.add_item(ui.ActionRow(ActionButton("Besoin d'aide ?","ticket:support","🎧")))
        elif kind=="partners":
            frame.add_item(txt("## ✧ NATIX • NOS PARTENAIRES"))
            frame.add_item(sep())
            frame.add_item(txt(s["partners"][:2800]))
            frame.add_item(ui.ActionRow(ActionButton("Devenir partenaire","ticket:partner","🤝")))
        elif kind=="stats":
            metrics=store.metrics(guild.id) if guild else {"products":0,"orders":0,"open_tickets":0,"reviews":0}
            frame.add_item(txt("## ✦ NATIX • STATISTIQUES"))
            frame.add_item(sep())
            frame.add_item(txt(
                "**"+str(metrics["products"])+"** produits disponibles\n"
                "**"+str(metrics["orders"])+"** commandes enregistrées\n"
                "**"+str(metrics["open_tickets"])+"** tickets ouverts\n"
                "**"+str(metrics["reviews"])+"** avis publiés"
            ))
            frame.add_item(ui.ActionRow(ActionButton("Actualiser","stats:refresh","🔄")))
        elif kind=="vouch":
            frame.add_item(txt("## ✦ NATIX • TÉMOIGNAGES\n"
                  "Laisse un avis authentique après une commande. Les témoignages sont modérés avant publication."))
            frame.add_item(sep())
            frame.add_item(ui.ActionRow(ActionButton("Écrire un avis","vouch:create","✍️",discord.ButtonStyle.primary),
                                             ActionButton("Voir les avis","vouch:list","⭐")))
        else:
            frame.add_item(txt("## NATIX"))
        pack_containers(self,frame,accent)

class TicketControls(ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        box=ui.Container(accent_colour=discord.Colour(0xDAD4E7))
        box.add_item(txt("## 🎫 NATIX • VOTRE TICKET\n"
                         "Un membre du staff prendra en charge votre demande."))
        box.add_item(sep())
        box.add_item(ui.ActionRow(ActionButton("Fermer","ticket:close","🔒",discord.ButtonStyle.danger),
                                  ActionButton("Rouvrir","ticket:reopen","🔓"),
                                  ActionButton("Transcript","ticket:transcript","📜")))
        box.add_item(ui.ActionRow(ActionButton("Ajouter","ticket:add","➕"),
                                  ActionButton("Claim","ticket:claim","🛡️"),
                                  ActionButton("Libérer","ticket:unclaim","↩️"),
                                  ActionButton("Statut","ticket:status","ℹ️")))
        self.add_item(box)

class GiveawayPanel(ui.LayoutView):
    def __init__(self,prize="Concours NATIX",ended=False,count=0):
        super().__init__(timeout=None)
        box=ui.Container(accent_colour=discord.Colour(0x9087EF))
        box.add_item(txt("## 🎁 NATIX GIVEAWAY\n"
                 "**"+safe(prize,120)+"**\n"
                 +("🏁 Concours terminé" if ended else "✅ **"+str(count)+"** participant(s)")))
        box.add_item(sep())
        box.add_item(ui.ActionRow(ActionButton("Participer","give:toggle","🎁",discord.ButtonStyle.primary),
                                  ActionButton("Participants","give:participants","👥")))
        self.add_item(box)

class CatalogView(ui.LayoutView):
    def __init__(self,products,category,page=0,total=None):
        super().__init__(timeout=None)
        box=ui.Container(accent_colour=discord.Colour(0xDDD1F2))
        label=next((name for key,name,_ in CATEGORIES if key==category),"Produits")
        box.add_item(txt("## 🛍️ "+label+"\nSélectionne un produit pour préparer ta commande."))
        for prod in products[:8]:
            btn=ActionButton("Commander","product:"+str(prod["id"]),"🛒",discord.ButtonStyle.primary)
            btn.disabled=prod["stock"]==0
            price=safe(prod["price"],40)
            stock="Épuisé" if prod["stock"]==0 else ("Stock illimité" if prod["stock"]<0 else str(prod["stock"])+" en stock")
            box.add_item(sep())
            box.add_item(ui.Section(txt("**"+safe(prod["name"],70)+"**\n"+
                 safe(prod["details"],120)+"\n"+price+" · "+stock),accessory=btn))
        if total is not None:
            pages=max(1,(total+5)//6)
            box.add_item(sep())
            box.add_item(txt("Page **"+str(page+1)+"/"+str(pages)+"** · "+str(total)+" produits"))
            buttons=[]
            if page>0:
                buttons.append(ActionButton("Précédent","catalog:"+category+":"+str(page-1),"◀️"))
            if page+1<pages:
                buttons.append(ActionButton("Suivant","catalog:"+category+":"+str(page+1),"▶️"))
            if buttons:box.add_item(ui.ActionRow(*buttons))
        pack_containers(self,box,discord.Colour(0xDDD1F2))


class CustomPanel(ui.LayoutView):
    """Staff-composed standalone panel with persistent side accessory buttons."""
    def __init__(self,db,record,guild=None):
        super().__init__(timeout=None)
        cfg=db.settings(record["guild"])
        try: accent=discord.Colour(int(cfg["color"].strip("#"),16))
        except (TypeError,ValueError):accent=discord.Colour(0xE6E4F0)
        box=ui.Container(accent_colour=accent)
        box.add_item(ui.MediaGallery(discord.MediaGalleryItem(
            media=cfg["banner"] or "attachment://natix_banner.png")))
        box.add_item(txt("## ✦ "+safe(record["title"],100)+"\n"+safe(record["description"],1500)))
        for item in db.custom_items(record["id"])[:6]:
            box.add_item(sep())
            box.add_item(ui.Section(
                txt("**"+safe(item["label"],70)+"**\n"+safe(item["description"],160)),
                accessory=ActionButton("Ouvrir","custom:"+str(item["id"]),button_emoji(guild,item["emoji"]))))
        box.add_item(txt("-# NATIX · Panneau personnalisé"))
        pack_containers(self,box,accent)
