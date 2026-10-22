"""NATIX SHOP: small command surface faithful to the server hub reference.

Seven independent public panels, /setup and a single staff /manage group.
No emoji creation command, no duplicates, no extra unused slash commands.
"""
import io
import logging
from urllib.parse import urlsplit

import discord
from discord import app_commands

from .assets import CATEGORIES, banner, safe
from .panels import Panel, GiveawayPanel
from .services import archive_ticket, is_staff, respond, audit

LOG=logging.getLogger("natix.commands")
CATEGORY_CHOICES=[app_commands.Choice(name=name,value=key) for key,name,_ in CATEGORIES]
ORDER_STATES=[app_commands.Choice(name=k,value=k)
              for k in ("accepted","processing","delivered","cancelled")]

async def post_panel(i,kind):
    if not i.guild:
        return await respond(i,"Cette commande fonctionne uniquement sur ton serveur.")
    conf=i.client.store.settings(i.guild_id)
    view=Panel(kind,i.client.store,i.guild)
    attachment=(discord.File(banner(),filename="natix_banner.png")
                if kind not in ("reviews",) and not conf["banner"] else None)
    await i.response.send_message(view=view,file=attachment,
                                  allowed_mentions=discord.AllowedMentions.none())

def register(tree):
    # Only the panel names from the supplied NATIX reference are slash commands.
    @tree.command(name="home",description="NATIX • Accueil et accès à tous les services")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_home(i:discord.Interaction):
        await post_panel(i,"home")

    @tree.command(name="shop",description="NATIX • Boutique et produits")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_shop(i:discord.Interaction):
        await post_panel(i,"shop")

    @tree.command(name="support",description="NATIX • Panneau de tickets et assistance")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_support(i:discord.Interaction):
        await post_panel(i,"support")

    @tree.command(name="giveaway",description="NATIX • Panneau des giveaways actifs")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_giveaway(i:discord.Interaction):
        await post_panel(i,"giveaways")

    @tree.command(name="stats",description="NATIX • Statistiques de la boutique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_stats(i:discord.Interaction):
        await post_panel(i,"stats")

    @tree.command(name="social",description="NATIX • Liens officiels et réseaux")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_social(i:discord.Interaction):
        await post_panel(i,"social")

    @tree.command(name="rules",description="NATIX • Règlement de la boutique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_rules(i:discord.Interaction):
        await post_panel(i,"terms")

    @tree.command(name="setup",description="NATIX • Configurer tickets, staff et archives")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_setup(i:discord.Interaction,staff_role:discord.Role,
                        tickets:discord.CategoryChannel,logs:discord.TextChannel):
        if logs.category_id==tickets.id:
            return await respond(i,"Le salon des archives doit rester privé et séparé des tickets.")
        everyone=i.guild.default_role
        perms=logs.overwrites_for(everyone)
        if perms.view_channel is not False and logs.permissions_for(everyone).view_channel:
            return await respond(i,"Le salon de logs doit être caché aux membres (@everyone).")
        i.client.store.configure(i.guild_id,staff=staff_role.id,
                                 category=tickets.id,logs=logs.id)
        await respond(i,"✅ NATIX configuré : staff "+staff_role.mention+
             ", tickets **"+safe(tickets.name,70)+"**, archives "+logs.mention+".")
        await audit(i,"setup:updated",str(staff_role.id))

    manage=app_commands.Group(name="manage",description="NATIX • Un seul menu staff pour gérer la boutique")

    @manage.command(name="add",description="Ajouter un produit")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(category=CATEGORY_CHOICES)
    async def add(i:discord.Interaction,category:app_commands.Choice[str],
                  name:str,price:str,description:str,stock:int=-1):
        if stock < -1:
            return await respond(i,"Stock : -1 (illimité) ou un nombre positif.")
        pid=i.client.store.add_product(i.guild_id,category.value,
            name[:80],description[:400],price[:50],stock)
        await respond(i,"Produit **#"+str(pid)+"** créé. Il apparaît dans /shop.")
        await audit(i,"product:add",str(pid))

    @manage.command(name="edit",description="Modifier un produit existant")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def edit(i:discord.Interaction,id:int,name:str=None,
                   price:str=None,description:str=None):
        updates={}
        if name is not None:updates["name"]=name[:80]
        if price is not None:updates["price"]=price[:50]
        if description is not None:updates["details"]=description[:400]
        if not updates:
            return await respond(i,"Indique au moins un champ à modifier.")
        changed=i.client.store.modify_product(i.guild_id,id,**updates)
        await respond(i,"Produit mis à jour." if changed else "Produit introuvable.")
        if changed:await audit(i,"product:edit",str(id))

    @manage.command(name="remove",description="Retirer un produit de la boutique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(i:discord.Interaction,id:int):
        changed=i.client.store.modify_product(i.guild_id,id,active=0)
        await respond(i,"Produit désactivé." if changed else "Produit introuvable.")
        if changed:await audit(i,"product:remove",str(id))

    @manage.command(name="stock",description="Modifier le stock d'un produit")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stock(i:discord.Interaction,id:int,quantity:int):
        if quantity < -1:
            return await respond(i,"Stock : -1 (illimité) ou un nombre positif.")
        changed=i.client.store.modify_product(i.guild_id,id,stock=quantity)
        await respond(i,"Stock actualisé : "+str(quantity) if changed else "Produit introuvable.")
        if changed:await audit(i,"product:stock",str(id)+"="+str(quantity))

    @manage.command(name="products",description="Voir les identifiants, prix et stocks")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def products(i:discord.Interaction):
        rows=i.client.store.products(i.guild_id,limit=30)
        if not rows:return await respond(i,"Boutique vide. Ajoute un produit avec /manage add.")
        lines=["**NATIX • Catalogue staff**"]
        for item in rows:
            lines.append("#"+str(item["id"])+" — "+safe(item["name"],35)
                         +" · "+safe(item["price"],25)+" · stock "+str(item["stock"]))
        await respond(i,"\n".join(lines)[:1900])

    @manage.command(name="orders",description="Afficher les commandes en attente")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def orders(i:discord.Interaction):
        rows=i.client.store.orders(i.guild_id,limit=25)
        if not rows:return await respond(i,"Aucune commande.")
        await respond(i,"\n".join(
            "#"+str(o["id"])+" — "+safe(o["product_name"],45)
            +" — "+o["state"] for o in rows)[:1900])

    @manage.command(name="order",description="Accepter, préparer ou livrer une commande")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(state=ORDER_STATES)
    async def order(i:discord.Interaction,id:int,state:app_commands.Choice[str]):
        ok,message=i.client.store.transition_order(i.guild_id,id,state.value,i.user.id)
        await respond(i,("✅ " if ok else "⚠️ ")+message)
        if ok:await audit(i,"order:state",str(id)+"="+state.value)

    @manage.command(name="giveaway",description="Créer un giveaway avec un vrai tirage")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def make_giveaway(i:discord.Interaction,prize:str,
                            minutes:app_commands.Range[int,1,10080]):
        if not i.guild:
            return await respond(i,"Disponible sur un serveur.")
        await i.response.send_message(view=GiveawayPanel(prize))
        message=await i.original_response()
        import time
        i.client.store.execute(
            "INSERT INTO giveaways(message,channel,prize,ends,closed) VALUES (?,?,?,?,0)",
            (message.id,i.channel_id,prize[:120],int(time.time())+minutes*60)
        )
        await audit(i,"giveaway:new",str(message.id))

    @manage.command(name="social",description="Définir les liens officiels du serveur")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social(i:discord.Interaction,discord_url:str=None,
                     tiktok_url:str=None,website_url:str=None):
        values={}
        for key,value in (
            ("social_discord",discord_url),("social_tiktok",tiktok_url),
            ("social_site",website_url)
        ):
            if value is None:continue
            url=value.strip()
            if url and (len(url)>220 or urlsplit(url).scheme!="https" or
                        not urlsplit(url).netloc):
                return await respond(i,"Utilise des liens HTTPS valides.")
            values[key]=url
        if not values:return await respond(i,"Indique au moins un lien.")
        i.client.store.configure(i.guild_id,**values)
        await respond(i,"Liens officiels enregistrés. Republie /social.")
        await audit(i,"social:update",",".join(values))

    @manage.command(name="rules",description="Modifier le règlement de la boutique")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules(i:discord.Interaction,text:str):
        i.client.store.configure(i.guild_id,rules=text[:2900])
        await respond(i,"Règlement enregistré. Republie /rules.")
        await audit(i,"rules:update","")

    @manage.command(name="delete_ticket",description="Archiver puis supprimer un ticket fermé")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def delete_ticket(i:discord.Interaction):
        row=i.client.store.ticket(i.channel_id)
        if not row or row["state"]!="closed":
            return await respond(i,"Ferme ce ticket NATIX avant de le supprimer.")
        await i.response.defer(ephemeral=True,thinking=True)
        archived,detail=await archive_ticket(i)
        if not archived:
            return await i.followup.send(detail,ephemeral=True)
        try:
            await i.channel.delete(reason="NATIX transcript archived; ticket deleted by staff")
        except discord.HTTPException:
            return await i.followup.send("Archive enregistrée, mais suppression refusée.",ephemeral=True)
        i.client.store.state_ticket(i.channel_id,"deleted")
        await i.followup.send("Ticket archivé et supprimé.",ephemeral=True)

    tree.add_command(manage)

    @tree.error
    async def error(i,exc):
        LOG.warning("NATIX command error: %s",exc)
        try:
            if isinstance(exc,app_commands.MissingPermissions):
                await respond(i,"Commande réservée aux responsables du serveur.")
            else:
                await respond(i,"La commande n'a pas pu être exécutée. Vérifie la configuration.")
        except discord.HTTPException:
            LOG.exception("Could not send command error")
