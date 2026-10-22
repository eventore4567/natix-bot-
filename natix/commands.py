"""Les 6 commandes slash de NATIX. Tout le reste passe par les panneaux.

/setup     tableau de bord de configuration (boutons + formulaires)
/panel     publier un panneau (accueil, boutique, échanges, promos, support, avis, règlement, réseaux)
/product   ajouter, modifier, réapprovisionner, retirer, lister les produits
/giveaway  lancer, terminer, relancer un tirage
/orders    suivre les commandes clients
/pplme     afficher la bannière et les coordonnées PayPal configurées
"""
import logging
import time
import re
from urllib.parse import urlsplit

import discord
from discord import app_commands

from . import ui as V
from .config import ORDER_STATES, PANEL_KINDS
from .db import parse_price
from .emojis import EMOJIS
from .handlers import finish_giveaway
from .util import NO_PINGS, is_staff, money, parse_duration, reply, safe, stock_text

LOG = logging.getLogger("natix.commands")
E = EMOJIS.text
ADMIN = discord.Permissions(manage_guild=True)


def staff_only():
    async def predicate(i: discord.Interaction):
        if not is_staff(i.user, i.client.store.settings(i.guild_id)):
            raise app_commands.CheckFailure("staff")
        return True
    return app_commands.check(predicate)


# ------------------------------------------------------------------ autocomplétions
async def ac_category(i, current):
    cur = current.lower()
    return [app_commands.Choice(name=c["name"][:100], value=c["key"])
            for c in i.client.store.categories(i.guild_id, include_inactive=True)
            if cur in c["name"].lower() or cur in c["key"]][:25]


async def ac_product(i, current):
    cur = current.lower()
    s = i.client.store.settings(i.guild_id)
    out = []
    for p in i.client.store.products(i.guild_id, limit=200):
        label = f"#{p['id']} · {p['name']} · {money(p['price_cents'], s['currency'])} · {stock_text(p['stock'])}"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=p["id"]))
    return out[:25]


async def ac_giveaway(i, current):
    out = []
    for g in i.client.store.recent_giveaways(i.guild_id):
        state = "terminé" if g["closed"] else "en cours"
        label = f"{g['prize']} · {state}"
        if current.lower() in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=str(g["message"])))
    return out[:25]


async def announce_restock(i, product, added):
    store = i.client.store
    s = store.settings(i.guild_id)
    channel = i.guild.get_channel(s.get("restock_channel") or 0)
    if not isinstance(channel, discord.TextChannel):
        return
    cat = store.category(i.guild_id, product["category"])
    shop = store.panels(i.guild_id, "shop")
    link = (f"\n[Voir la catégorie](https://discord.com/channels/{i.guild_id}/{shop[0]['channel']}/{shop[0]['message']})"
            if shop else "")
    ping = {"here": "@here ", "everyone": "@everyone "}.get(s["restock_ping"], "")
    emoji = E(product["emoji"] or (cat["emoji"] if cat else "nx_box"))
    text = (f"{ping}**Restock !**\n\n{emoji} **{safe(cat['name'] if cat else 'Boutique', 60)} · "
            f"{safe(product['name'], 80)}**\n+{added} ajouté{link}")
    try:
        await channel.send(text, allowed_mentions=discord.AllowedMentions(everyone=bool(ping), users=False,
                                                                           roles=False))
    except discord.HTTPException:
        LOG.warning("Annonce de restock impossible dans %s", channel.id)


def paypal_contact_message(settings):
    """Render just the configured PayPal contact, never an order-payment panel.

    Returns None while the owner has not set both the username and email.
    """
    raw=(settings.get("paypal") or "").strip()
    if raw.startswith("https://"):
        parsed=urlsplit(raw)
        if parsed.hostname not in ("paypal.me","www.paypal.me"):
            raw=""
        else:
            raw=(parsed.path.strip("/").split("/") or [""])[0]
    username=raw.lstrip("@")
    email=(settings.get("paypal_email") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}",username):
        return None
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",email):
        return None
    return "**Mon user PayPal :** @"+safe(username,80)+"\n**Mon mail PayPal :** "+safe(email,160)


def register(tree: app_commands.CommandTree):
    # -------------------------------------------------------------- /setup
    @tree.command(name="setup", description="Configurer NATIX (salons, staff, textes, catégories, promotions)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(i: discord.Interaction):
        await i.response.send_message(view=V.setup_view(i.client.store, i.guild), ephemeral=True,
                                      allowed_mentions=NO_PINGS)

    # -------------------------------------------------------------- /pplme
    @tree.command(name="pplme", description="Afficher le PayPal NATIX avec sa bannière")
    @app_commands.guild_only()
    @staff_only()
    @app_commands.describe(salon="Facultatif : publier le panneau dans un autre salon")
    async def pplme(i: discord.Interaction, salon: discord.TextChannel = None):
        message = paypal_contact_message(i.client.store.settings(i.guild_id))
        if not message:
            return await reply(i,"Configure ton pseudo et ton email dans /setup → Paiements.")
        destination = salon or i.channel
        perms = destination.permissions_for(i.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.attach_files):
            return await reply(i,"NATIX ne peut pas publier la bannière dans ce salon.")
        view, files = V.pplme_panel(i.client.store, i.guild_id, message)
        if destination.id == i.channel_id:
            return await i.response.send_message(
                view=view, files=files, allowed_mentions=NO_PINGS
            )
        await destination.send(view=view, files=files, allowed_mentions=NO_PINGS)
        await reply(i,f"Panneau PayPal publié dans {destination.mention}.")


    # -------------------------------------------------------------- /panel    # -------------------------------------------------------------- /panel
    @tree.command(name="panel", description="Publier un panneau NATIX dans un salon")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(type="Panneau à publier", salon="Salon de destination (par défaut : ici)")
    @app_commands.choices(type=[app_commands.Choice(name=v, value=k) for k, v in PANEL_KINDS.items()])
    async def panel(i: discord.Interaction, type: app_commands.Choice[str], salon: discord.TextChannel = None):
        channel = salon or i.channel
        perms = channel.permissions_for(i.guild.me)
        if not (perms.send_messages and perms.attach_files and perms.view_channel):
            return await reply(i, f"NATIX ne peut pas envoyer de message avec image dans {channel.mention}.")
        view, files = V.PANEL_BUILDERS[type.value](i.client.store, i.guild_id)
        msg = await channel.send(view=view, files=files, allowed_mentions=NO_PINGS)
        i.client.store.register_panel(msg.id, i.guild_id, channel.id, type.value)
        i.client.store.audit(i.guild_id, i.user.id, "panel:" + type.value, msg.id)
        await reply(i, None, view=V.notice(f"Panneau **{type.name}** publié dans {channel.mention}."))

    # -------------------------------------------------------------- /product
    product = app_commands.Group(name="product", description="Gérer les produits de la boutique",
                                 guild_only=True, default_permissions=ADMIN)

    @product.command(name="add", description="Ajouter un produit")
    @staff_only()
    @app_commands.describe(categorie="Catégorie", nom="Nom affiché", prix="Prix (ex. 10 ou 6.5)",
                           stock="Quantité disponible (-1 = illimité)", description="Courte description",
                           emoji="Emoji optionnel (Unicode ou <:nom:id>)")
    @app_commands.autocomplete(categorie=ac_category)
    async def p_add(i: discord.Interaction, categorie: str, nom: app_commands.Range[str, 1, 80],
                    prix: str, stock: app_commands.Range[int, -1, 100000] = -1,
                    description: app_commands.Range[str, 0, 300] = "", emoji: str = ""):
        store = i.client.store
        if not store.category(i.guild_id, categorie):
            return await reply(i, "Catégorie introuvable. Choisis-la dans la liste.")
        cents = parse_price(prix)
        if cents is None:
            return await reply(i, "Prix invalide (ex. 10 ou 6.5).")
        pid = store.add_product(i.guild_id, categorie, nom, description, cents, stock, emoji.strip())
        store.audit(i.guild_id, i.user.id, "product:add", pid)
        s = store.settings(i.guild_id)
        await reply(i, None, view=V.notice(f"Produit **#{pid} · {safe(nom, 80)}** ajouté · "
                                           f"{money(cents, s['currency'])} · {stock_text(stock)}"))

    @product.command(name="edit", description="Modifier un produit")
    @staff_only()
    @app_commands.autocomplete(produit=ac_product, categorie=ac_category)
    @app_commands.describe(produit="Produit à modifier", prix="Nouveau prix (ex. 10 ou 6.5)")
    async def p_edit(i: discord.Interaction, produit: int, nom: app_commands.Range[str, 1, 80] = None,
                     prix: str = None, description: app_commands.Range[str, 0, 300] = None,
                     categorie: str = None, emoji: str = None):
        store = i.client.store
        cents = None
        if prix is not None:
            cents = parse_price(prix)
            if cents is None:
                return await reply(i, "Prix invalide (ex. 10 ou 6.5).")
        if categorie is not None and not store.category(i.guild_id, categorie):
            return await reply(i, "Catégorie introuvable.")
        changed = store.update_product(i.guild_id, produit, name=nom, price_cents=cents, details=description,
                                       category=categorie, emoji=emoji.strip() if emoji is not None else None)
        if not changed:
            return await reply(i, "Produit introuvable ou aucun champ modifié.")
        store.audit(i.guild_id, i.user.id, "product:edit", produit)
        await reply(i, None, view=V.notice(f"Produit **#{produit}** mis à jour."))

    @product.command(name="stock", description="Réapprovisionner ou corriger le stock")
    @staff_only()
    @app_commands.autocomplete(produit=ac_product)
    @app_commands.describe(produit="Produit", quantite="Quantité", mode="Ajouter au stock ou le remplacer")
    @app_commands.choices(mode=[app_commands.Choice(name="Ajouter (restock)", value="add"),
                                app_commands.Choice(name="Définir la valeur exacte", value="set"),
                                app_commands.Choice(name="Rendre illimité", value="unlimited")])
    async def p_stock(i: discord.Interaction, produit: int, quantite: app_commands.Range[int, 0, 100000] = 0,
                      mode: app_commands.Choice[str] = None):
        store = i.client.store
        p = store.product(i.guild_id, produit)
        if not p:
            return await reply(i, "Produit introuvable.")
        how = mode.value if mode else "add"
        before = p["stock"]
        if how == "unlimited":
            store.update_product(i.guild_id, produit, stock=-1)
            new = -1
        elif how == "set" or before == -1:
            store.update_product(i.guild_id, produit, stock=quantite)
            new = quantite
        else:
            if quantite == 0:
                return await reply(i, "Indique une quantité à ajouter.")
            new = store.add_stock(i.guild_id, produit, quantite)
        store.audit(i.guild_id, i.user.id, "product:stock", f"{produit} {before}->{new}")
        await reply(i, None, view=V.notice(f"**{safe(p['name'], 80)}** · {stock_text(before)} → {stock_text(new)}",
                                           "nx_box"))
        added = (new - max(before, 0)) if new != -1 and before != -1 else 0
        if added > 0:
            await announce_restock(i, p, added)

    @product.command(name="remove", description="Retirer un produit de la boutique")
    @staff_only()
    @app_commands.autocomplete(produit=ac_product)
    async def p_remove(i: discord.Interaction, produit: int):
        store = i.client.store
        p = store.product(i.guild_id, produit)
        if not p or not store.update_product(i.guild_id, produit, active=0):
            return await reply(i, "Produit introuvable.")
        store.audit(i.guild_id, i.user.id, "product:remove", produit)
        await reply(i, None, view=V.notice(f"**{safe(p['name'], 80)}** retiré de la boutique.", "nx_trash"))

    @product.command(name="list", description="Voir le catalogue (prix, stock, identifiants)")
    @staff_only()
    @app_commands.autocomplete(categorie=ac_category)
    async def p_list(i: discord.Interaction, categorie: str = None):
        store = i.client.store
        s = store.settings(i.guild_id)
        blocks = []
        for c in store.categories(i.guild_id, include_inactive=True):
            if categorie and c["key"] != categorie:
                continue
            rows = store.products(i.guild_id, c["key"], limit=25)
            lines = "\n".join(f"`#{p['id']}` {safe(p['name'], 50)} · **{money(p['price_cents'], s['currency'])}**"
                              f" · {stock_text(p['stock'])}" for p in rows) or "-# Aucun produit"
            blocks.append(f"### {E(c['emoji'])} {safe(c['name'], 50)}\n{lines}")
        text = "\n".join(blocks)[:3900] or "Aucune catégorie."
        await reply(i, None, view=V.view_of(V.container(V.ui.TextDisplay(f"## {E('nx_list')} Catalogue\n{text}"))))

    tree.add_command(product)

    # -------------------------------------------------------------- /giveaway
    giveaway = app_commands.Group(name="giveaway", description="Gérer les giveaways",
                                  guild_only=True, default_permissions=ADMIN)

    @giveaway.command(name="start", description="Lancer un giveaway")
    @staff_only()
    @app_commands.describe(lot="Ce qui est à gagner (ex. 5€)", duree="Durée : 30m, 2h, 1d…",
                           gagnants="Nombre de gagnants", salon="Salon (par défaut : ici)")
    async def g_start(i: discord.Interaction, lot: app_commands.Range[str, 1, 100], duree: str,
                      gagnants: app_commands.Range[int, 1, 20] = 1, salon: discord.TextChannel = None):
        seconds = parse_duration(duree)
        if not seconds or not 60 <= seconds <= 60 * 86400:
            return await reply(i, "Durée invalide : entre 1 minute et 60 jours (ex. 30m, 2h, 1d).")
        channel = salon or i.channel
        ends = int(time.time()) + seconds
        preview = {"prize": lot, "winners": gagnants, "ends": ends, "winner_ids": ""}
        msg = await channel.send(view=V.giveaway_view(preview, 0), allowed_mentions=NO_PINGS)
        i.client.store.create_giveaway(msg.id, i.guild_id, channel.id, lot, ends, gagnants, i.user.id)
        i.client.store.audit(i.guild_id, i.user.id, "giveaway:start", msg.id)
        await reply(i, None, view=V.notice(f"Giveaway lancé dans {channel.mention}, fin <t:{ends}:R>.", "nx_gift"))

    @giveaway.command(name="end", description="Terminer un giveaway maintenant")
    @staff_only()
    @app_commands.autocomplete(giveaway=ac_giveaway)
    async def g_end(i: discord.Interaction, giveaway: str):
        if not giveaway.isdigit():
            return await reply(i, "Giveaway introuvable.")
        await i.response.defer(ephemeral=True)
        await i.followup.send(await finish_giveaway(i.client, int(giveaway)), ephemeral=True)

    @giveaway.command(name="reroll", description="Tirer de nouveaux gagnants")
    @staff_only()
    @app_commands.autocomplete(giveaway=ac_giveaway)
    async def g_reroll(i: discord.Interaction, giveaway: str):
        if not giveaway.isdigit():
            return await reply(i, "Giveaway introuvable.")
        await i.response.defer(ephemeral=True)
        await i.followup.send(await finish_giveaway(i.client, int(giveaway), reroll=True), ephemeral=True)

    tree.add_command(giveaway)

    # -------------------------------------------------------------- /orders
    @tree.command(name="orders", description="Suivre les commandes clients")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @staff_only()
    @app_commands.describe(membre="Filtrer par client", statut="Filtrer par statut")
    @app_commands.choices(statut=[app_commands.Choice(name=v, value=k) for k, v in ORDER_STATES.items()])
    async def orders(i: discord.Interaction, membre: discord.Member = None,
                     statut: app_commands.Choice[str] = None):
        store = i.client.store
        s = store.settings(i.guild_id)
        rows = store.orders(i.guild_id, buyer=membre.id if membre else None,
                            state=statut.value if statut else None, limit=15)
        if not rows:
            return await reply(i, "Aucune commande trouvée.")
        lines = []
        for o in rows:
            where = f" · <#{o['channel']}>" if o["channel"] else ""
            lines.append(f"`#{o['id']}` **{safe(o['product_name'], 50)}** ×{o['quantity']} · "
                         f"{money(o['total_cents'], s['currency'])} · {ORDER_STATES.get(o['state'], o['state'])}\n"
                         f"-# <@{o['buyer']}> · <t:{o['created']}:R>{where}")
        m = store.metrics(i.guild_id)
        await reply(i, None, view=V.view_of(V.container(V.ui.TextDisplay(
            f"## {E('nx_cart')} Commandes\n-# {m['orders']} au total · {m['pending']} en cours · "
            f"{m['delivered']} livrées\n" + "\n".join(lines)))))

    # -------------------------------------------------------------- erreurs
    @tree.error
    async def on_error(i: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            text = "Commande réservée au staff."
        elif isinstance(error, app_commands.NoPrivateMessage):
            text = "Commande disponible uniquement sur un serveur."
        else:
            LOG.exception("Erreur de commande", exc_info=error)
            text = "La commande a échoué. Vérifie la configuration avec /setup."
        try:
            await reply(i, f"{E('nx_cross')} {text}")
        except discord.HTTPException:
            pass
