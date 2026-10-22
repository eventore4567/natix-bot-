"""Slash command catalog: one command per Discord panel plus admin workflows."""
import io
import logging
import re
import secrets
import time

import discord
from discord import app_commands,ui

from .assets import CATEGORIES,PANELS,PLANS,safe,banner,emoji
from .panels import Panel,GiveawayPanel
from .services import create_ticket,export_transcript,is_staff,respond,audit

LOG=logging.getLogger("natix.commands")
CATEGORIES_CHOICES=[app_commands.Choice(name=name,value=key) for key,name,_ in CATEGORIES]
PANEL_CHOICES=[app_commands.Choice(name=name,value=key) for key,name in PANELS.items()]
STATES=[app_commands.Choice(name=name,value=name) for name in ("pending","accepted","processing","delivered","cancelled")]

def register(tree):
    async def publish(i,kind,channel=None,preview=False):
        if not i.guild:return await respond(i,"Serveur requis.")
        if not i.user.guild_permissions.manage_guild:
            return await respond(i,"Gérer le serveur est requis.")
        cfg=i.client.store.settings(i.guild_id)
        destination=channel or i.channel
        if not isinstance(destination,discord.TextChannel):
            return await respond(i,"Choisis un salon textuel.")
        image=None
        if kind!="reviews" and not cfg["banner"]:
            image=discord.File(banner(cfg["name"]),filename="natix_banner.png")
        view=Panel(kind,i.client.store,i.guild)
        if preview:
            return await i.response.send_message(view=view,file=image,ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            msg=await destination.send(view=view,file=image,allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            return await i.followup.send("Je n'ai pas l'autorisation de publier dans ce salon.",ephemeral=True)
        await i.followup.send("✅ Panneau **"+PANELS[kind]+"** publié : "+msg.jump_url,ephemeral=True)
        await audit(i,"panel:published",kind+" #"+str(destination.id))

    # Separate commands because each screenshot represents an independent panel.
    @tree.command(name="shop",description="Publier le panneau de boutique premium")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_shop(i:discord.Interaction):
        await publish(i,"shop")

    @tree.command(name="support",description="Publier le panneau d'assistance et de tickets")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_support(i:discord.Interaction):
        await publish(i,"support")

    @tree.command(name="trade",description="Publier les échanges NATIX")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_trade(i:discord.Interaction):
        await publish(i,"trade")

    @tree.command(name="promo",description="Publier les offres promotionnelles")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_promo(i:discord.Interaction):
        await publish(i,"promo")

    @tree.command(name="rules",description="Publier les conditions de vente")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_rules(i:discord.Interaction):
        await publish(i,"terms")

    @tree.command(name="supporter",description="Publier le panneau supporter")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_supporter(i:discord.Interaction):
        await publish(i,"supporter")

    @tree.command(name="reviews",description="Publier les boutons d'avis clients")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_reviews(i:discord.Interaction):
        await publish(i,"reviews")

    @tree.command(name="faq",description="Publier la FAQ")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_faq(i:discord.Interaction):
        await publish(i,"faq")

    @tree.command(name="partners",description="Publier les partenaires")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_partners(i:discord.Interaction):
        await publish(i,"partners")

    @tree.command(name="statistics",description="Publier les statistiques de la boutique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_stats(i:discord.Interaction):
        await publish(i,"stats")

    @tree.command(name="vouch",description="Publier le panneau de témoignages")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_vouch(i:discord.Interaction):
        await publish(i,"vouch")

    @tree.command(name="panel",description="Prévisualiser ou publier un panneau dans un autre salon")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(type=PANEL_CHOICES)
    async def cmd_panel(i:discord.Interaction,type:app_commands.Choice[str],
                        channel:discord.TextChannel=None,preview:bool=False):
        await publish(i,type.value,channel,preview)

    @tree.command(name="preview",description="Prévisualiser un panneau NATIX sans le publier")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(type=PANEL_CHOICES)
    async def cmd_preview(i:discord.Interaction,type:app_commands.Choice[str]):
        await publish(i,type.value,preview=True)

    @tree.command(name="setup",description="Configurer staff, tickets, logs et commandes")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_setup(i:discord.Interaction,staff_role:discord.Role,ticket_category:discord.CategoryChannel,
                        logs:discord.TextChannel=None,vouch_channel:discord.TextChannel=None):
        i.client.store.configure(i.guild_id,staff=staff_role.id,category=ticket_category.id,
                        logs=logs.id if logs else 0,
                        vouch_channel=vouch_channel.id if vouch_channel else 0)
        await respond(i,"✅ **NATIX configuré !**\nStaff : "+staff_role.mention+
                      "\nTickets : "+ticket_category.name+
                      "\nLogs : "+(logs.mention if logs else "Non configurés"))
        await audit(i,"setup:updated",str(staff_role.id))

    @tree.command(name="brand",description="Configurer la bannière NATIX, la couleur et le nom")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_brand(i:discord.Interaction,title:str="NATIX",color:str="E6E4F0",
                        banner_url:str=""):
        if not re.fullmatch(r"#?[a-fA-F0-9]{6}",color):
            return await respond(i,"Couleur hexadécimale invalide (ex : E6E4F0).")
        if banner_url and (not banner_url.startswith("https://") or len(banner_url)>1000):
            return await respond(i,"La bannière doit être une URL HTTPS valide.")
        i.client.store.configure(i.guild_id,name=title[:15],color=color.strip("#"),
                                  banner=banner_url)
        await respond(i,"✅ Identité NATIX mise à jour pour les futurs panneaux.")
        await audit(i,"brand:updated",title[:15])

    @tree.command(name="banner",description="Télécharger la bannière NATIX générée")
    async def cmd_banner(i:discord.Interaction):
        cfg=i.client.store.settings(i.guild_id)
        image=discord.File(banner(cfg["name"]),filename="natix-premium-banner.png")
        await i.response.send_message("✧ NATIX · Bannière originale",file=image,ephemeral=True)

    @tree.command(name="emojis",description="Installer les emojis premium originaux de NATIX")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_emojis(i:discord.Interaction):
        await i.response.defer(thinking=True,ephemeral=True)
        added=[];errors=[]
        for kind in ("shop","cart","gift","ticket","support","trade","star","shield","config"):
            name="nx_"+kind
            if discord.utils.get(i.guild.emojis,name=name):
                continue
            try:
                await i.guild.create_custom_emoji(name=name,image=emoji(kind),
                       reason="NATIX custom emoji pack")
                added.append(name)
            except (discord.Forbidden,discord.HTTPException):
                errors.append(name)
        await i.followup.send("🎨 **Emojis ajoutés :** "+(", ".join(added) or "Aucun")+
                              ("\nÀ vérifier (permissions / places) : "+", ".join(errors) if errors else ""),
                              ephemeral=True)

    @tree.command(name="settings",description="Afficher les réglages actuels de NATIX")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_settings(i:discord.Interaction):
        c=i.client.store.settings(i.guild_id)
        await respond(i,"**NATIX · Configuration**\n"
            "Rôle staff : "+str(c["staff"])+"\nTickets : "+str(c["category"])+
            "\nLogs : "+str(c["logs"])+"\nCouleur : #"+c["color"]+
            "\nNom : "+safe(c["name"])+"\nSupporter : "+str(c["supporter_role"]))

    @tree.command(name="textconfig",description="Personnaliser les conditions, FAQ ou partenaires")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(type=[
        app_commands.Choice(name="Conditions",value="rules"),
        app_commands.Choice(name="FAQ",value="faq"),
        app_commands.Choice(name="Partenaires",value="partners"),
    ])
    async def cmd_textconfig(i:discord.Interaction,type:app_commands.Choice[str],text:str):
        i.client.store.configure(i.guild_id,**{type.value:text[:2900]})
        await respond(i,"✅ Texte **"+type.name+"** enregistré.")
        await audit(i,"textconfig",type.value)

    @tree.command(name="supporter_config",description="Configurer le rôle et le statut Supporters")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_supporterconfig(i:discord.Interaction,role:discord.Role,status_prefix:str=".gg/natix"):
        i.client.store.configure(i.guild_id,supporter_role=role.id,status=status_prefix[:80])
        await respond(i,"✅ Supporter : "+role.mention+" · "+safe(status_prefix,80))

    @tree.command(name="announcement",description="Publier une annonce NATIX sans ping automatique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_announcement(i:discord.Interaction,channel:discord.TextChannel,title:str,message:str):
        embed=discord.Embed(title="✧ "+safe(title,160),description=safe(message,3200),
                            colour=discord.Colour(0xDDD3EE))
        embed.set_footer(text="NATIX · Official Announcement")
        await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        await respond(i,"✅ Annonce publiée sans mention automatique.")
        await audit(i,"announcement",str(channel.id))

    product=app_commands.Group(name="product",description="Ajouter, modifier, supprimer et réapprovisionner les produits")
    @product.command(name="add",description="Ajouter un produit à une catégorie")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(category=CATEGORIES_CHOICES)
    async def prod_add(i:discord.Interaction,category:app_commands.Choice[str],name:str,
                       price:str,details:str,stock:int=-1):
        if stock< -1:return await respond(i,"Le stock doit valoir -1 (illimité) ou plus.")
        pid=i.client.store.add_product(i.guild_id,category.value,name[:90],
                       details[:500],price[:60],stock)
        await respond(i,"✅ Produit **#"+str(pid)+"** ajouté à "+category.name+".")
        await audit(i,"product:add",str(pid))

    @product.command(name="edit",description="Modifier le prix, nom, description et catégorie d'un produit")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(category=CATEGORIES_CHOICES)
    async def prod_edit(i:discord.Interaction,id:int,name:str=None,price:str=None,
                        description:str=None,category:app_commands.Choice[str]=None):
        changes={}
        if name is not None:changes["name"]=name[:90]
        if price is not None:changes["price"]=price[:60]
        if description is not None:changes["details"]=description[:500]
        if category is not None:changes["category"]=category.value
        changed=i.client.store.modify_product(i.guild_id,id,**changes)
        await respond(i,"✅ Produit modifié." if changed else "Produit introuvable ou aucun changement.")
        if changed:await audit(i,"product:edit",str(id))

    @product.command(name="remove",description="Retirer un produit sans supprimer les anciennes commandes")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def prod_remove(i:discord.Interaction,id:int):
        ok=i.client.store.modify_product(i.guild_id,id,active=0)
        await respond(i,"✅ Produit retiré." if ok else "Produit introuvable.")
        if ok:await audit(i,"product:remove",str(id))

    @product.command(name="list",description="Lister les produits et leurs identifiants")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def prod_list(i:discord.Interaction):
        products=i.client.store.products(i.guild_id,limit=40)
        lines=["**NATIX · Catalogue**"]+[
          "#"+str(p["id"])+" · "+safe(p["name"],38)+" · "+safe(p["price"],35)+
          " · Stock "+str(p["stock"]) for p in products]
        await respond(i,"\n".join(lines)[:1900] if products else "Catalogue vide.")

    @product.command(name="restock",description="Changer le stock et publier facultativement un réassort")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def prod_restock(i:discord.Interaction,id:int,quantity:int,announce:bool=False):
        if quantity< -1:return await respond(i,"Stock invalide.")
        product=i.client.store.product(i.guild_id,id)
        if not product:return await respond(i,"Produit introuvable.")
        i.client.store.modify_product(i.guild_id,id,stock=quantity)
        await respond(i,"✅ Stock mis à jour : "+str(quantity))
        if announce:
            await i.channel.send("📦 **NATIX RESTOCK** · "+safe(product["name"])+
                "\nStock : "+("illimité" if quantity<0 else str(quantity)),
                allowed_mentions=discord.AllowedMentions.none())
        await audit(i,"product:restock",str(id)+"="+str(quantity))

    tree.add_command(product)

    orders=app_commands.Group(name="order",description="Voir et gérer les commandes enregistrées")
    @orders.command(name="mine",description="Voir tes propres commandes")
    async def orders_mine(i:discord.Interaction):
        rows=i.client.store.orders(i.guild_id,i.user.id)
        await respond(i,"\n".join("#"+str(x["id"])+" · "+safe(x["product_name"],45)+
              " · "+str(x["quantity"])+" · "+x["state"] for x in rows)[:1900]
              if rows else "Tu n'as aucune commande.")

    @orders.command(name="list",description="Lister les dernières commandes (staff)")
    async def orders_list(i:discord.Interaction):
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        rows=i.client.store.orders(i.guild_id,limit=30)
        await respond(i,"\n".join("#"+str(x["id"])+" · <@"+str(x["buyer"])+"> · "+
                    safe(x["product_name"],30)+" · "+x["state"] for x in rows)[:1900]
                    if rows else "Aucune commande.")

    @orders.command(name="status",description="Modifier l'état d'une commande")
    @app_commands.choices(state=STATES)
    async def order_status(i:discord.Interaction,id:int,state:app_commands.Choice[str]):
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        db=i.client.store
        order=db.order(i.guild_id,id)
        if not order:return await respond(i,"Commande introuvable.")
        if order["state"] in ("delivered","cancelled") and order["state"]!=state.value:
            return await respond(i,"Cette commande est déjà clôturée.")
        if state.value=="delivered" and order["state"]!="delivered":
            if not db.deduct_stock(i.guild_id,order["product_id"],order["quantity"]):
                return await respond(i,"Stock insuffisant, produit supprimé ou introuvable : livraison refusée.")
        db.order_state(i.guild_id,id,state.value,i.user.id)
        await respond(i,"✅ Commande #"+str(id)+" : "+state.value)
        await audit(i,"order:status",str(id)+"="+state.value)

    @orders.command(name="details",description="Afficher les informations d'une commande")
    async def order_details(i:discord.Interaction,id:int):
        r=i.client.store.order(i.guild_id,id)
        if not r:return await respond(i,"Commande introuvable.")
        if not is_staff(i) and i.user.id!=r["buyer"]:
            return await respond(i,"Cette commande ne t'appartient pas.")
        await respond(i,"**Commande #"+str(r["id"])+"**\nProduit : "+safe(r["product_name"])+
                      "\nQuantité : "+str(r["quantity"])+"\nPrix annoncé : "+safe(r["price"])+
                      "\nStatut : "+r["state"]+"\nCréation : <t:"+str(r["created"])+":F>\n"+
                      safe(r["notes"],500))

    tree.add_command(orders)

    tickets=app_commands.Group(name="ticket",description="Gestion des tickets NATIX")
    @tickets.command(name="close",description="Fermer le ticket actuel")
    async def t_close(i:discord.Interaction):
        from .services import ticket_action
        await ticket_action(i,"close")

    @tickets.command(name="reopen",description="Rouvrir le ticket actuel")
    async def t_reopen(i:discord.Interaction):
        from .services import ticket_action
        await ticket_action(i,"reopen")

    @tickets.command(name="transcript",description="Exporter tout l'historique du ticket")
    async def t_transcript(i:discord.Interaction):await export_transcript(i)

    @tickets.command(name="delete",description="Supprimer un ticket fermé")
    async def t_delete(i:discord.Interaction):
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        db=i.client.store
        row=db.ticket(i.channel_id)
        if not row:return await respond(i,"Ceci n'est pas un ticket NATIX.")
        if row["state"]!="closed":
            return await respond(i,"Ferme le ticket avant suppression.")
        await i.response.send_message("Suppression du ticket…",ephemeral=True)
        db.state_ticket(i.channel_id,"deleted")
        await i.channel.delete(reason="NATIX ticket deleted by "+str(i.user.id))

    tree.add_command(tickets)

    @tree.command(name="giveaway",description="Lancer un giveaway avec participations et tirage réel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_giveaway(i:discord.Interaction,prize:str,
                           minutes:app_commands.Range[int,1,10080]):
        await i.response.send_message(view=GiveawayPanel(prize))
        m=await i.original_response()
        i.client.store.execute("INSERT INTO giveaways(message,channel,prize,ends,closed) VALUES (?,?,?,?,0)",
             (m.id,i.channel_id,prize[:130],int(time.time())+minutes*60))
        await audit(i,"giveaway:created",str(m.id))

    @tree.command(name="giveaway_end",description="Terminer un concours et tirer un gagnant")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_giveaway_end(i:discord.Interaction,message_id:str):
        try:mid=int(message_id)
        except ValueError:return await respond(i,"ID de message invalide.")
        from .bot import finish_giveaway
        result=await finish_giveaway(i.client,mid)
        await respond(i,result)

    @tree.command(name="giveaway_reroll",description="Retirer un nouveau gagnant d'un concours terminé")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_giveaway_reroll(i:discord.Interaction,message_id:str):
        try:mid=int(message_id)
        except ValueError:return await respond(i,"ID invalide.")
        db=i.client.store
        g=db.giveaway(mid)
        if not g or not g["closed"]:return await respond(i,"Giveaway introuvable ou encore actif.")
        channel=i.guild.get_channel(g["channel"])
        if not channel:return await respond(i,"Salon du concours inaccessible.")
        entries=db.giveaway_entries(mid)
        if not entries:return await respond(i,"Pas de participants.")
        winner=secrets.SystemRandom().choice(entries)
        await channel.send("🎁 **NATIX reroll** : <@"+str(winner)+">",
            allowed_mentions=discord.AllowedMentions.none())
        await respond(i,"Nouveau gagnant tiré dans le salon du concours.")

    vouch=app_commands.Group(name="vouches",description="Validation des vrais avis clients")
    @vouch.command(name="queue",description="Voir les avis en attente")
    async def vouch_queue(i:discord.Interaction):
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        rows=i.client.store.many("SELECT * FROM reviews WHERE guild=? AND approved=0 ORDER BY id DESC LIMIT 15",(i.guild_id,))
        await respond(i,"\n\n".join("#"+str(x["id"])+" · ⭐"+str(x["rating"])+
                  " · <@"+str(x["author"])+"> : "+safe(x["comment"],130) for x in rows)
                  if rows else "Aucun avis en attente.")

    @vouch.command(name="approve",description="Approuver ou rejeter un témoignage")
    async def vouch_approve(i:discord.Interaction,id:int,approve:bool=True):
        if not is_staff(i):return await respond(i,"Réservé au staff.")
        db=i.client.store
        row=db.one("SELECT * FROM reviews WHERE id=? AND guild=? AND approved=0",(id,i.guild_id))
        if not row:return await respond(i,"Avis introuvable.")
        db.execute("UPDATE reviews SET approved=? WHERE id=?",(1 if approve else -1,id))
        await respond(i,"✅ Avis "+("approuvé." if approve else "rejeté."))
        channel=i.guild.get_channel(db.settings(i.guild_id)["vouch_channel"])
        if approve and channel:
            await channel.send("⭐ **NATIX · Avis vérifié**\n<@"+str(row["author"])+"> · "+
                 str(row["rating"])+"/5\n"+safe(row["comment"],800),
                 allowed_mentions=discord.AllowedMentions.none())
        await audit(i,"review:moderated",str(id)+" "+str(approve))

    tree.add_command(vouch)

    @tree.command(name="help",description="Aide et liste des commandes NATIX")
    async def help_cmd(i:discord.Interaction):
        await respond(i,"**✦ NATIX · Commandes boutique**\n"
            "Panneaux : /shop /support /trade /promo /rules /reviews /vouch /faq /partners /statistics /supporter\n"
            "Design : /brand /banner /emojis /preview /panel\n"
            "Catalogue : /product add|edit|remove|list|restock\n"
            "Commandes : /order mine|list|status|details\n"
            "Tickets : /ticket close|reopen|transcript|delete\n"
            "Concours : /giveaway /giveaway_end /giveaway_reroll\n"
            "Paramètres : /setup /settings /textconfig /supporter_config\n"
            "Avis : /vouches queue|approve\nAnnonces : /announcement\n"
            "-# Les actions administrateur sont protégées.")

    @tree.error
    async def on_error(i,error):
        LOG.warning("Slash command failed: %s",error)
        if isinstance(error,app_commands.MissingPermissions):
            await respond(i,"Cette commande nécessite la permission Gérer le serveur.")
        else:
            await respond(i,"Commande indisponible. Vérifie les paramètres et les permissions.")
