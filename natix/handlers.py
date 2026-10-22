"""Routeur global des interactions NATIX (boutons, menus, formulaires).

Chaque composant porte un custom_id « nx:… » ; tout l'état vit dans SQLite.
Les panneaux restent donc fonctionnels après un redémarrage.
"""
import io
import logging
import re
import secrets
import time
from urllib.parse import urlsplit

import discord
from discord import ui

from . import ui as V
from .config import ORDER_STATES, TICKET_KINDS
from .db import parse_price
from .emojis import EMOJIS
from .util import NO_PINGS, is_staff, modal_values, money, reply, safe, slug

LOG = logging.getLogger("natix.handlers")
E = EMOJIS.text


class Oops(Exception):
    """Erreur affichée telle quelle à l'utilisateur (courte et claire)."""


# ====================================================================== helpers
def store_of(i):
    return i.client.store


def require_staff(i):
    if not is_staff(i.user, store_of(i).settings(i.guild_id)):
        raise Oops("Action réservée au staff.")


def require_admin(i):
    if not (isinstance(i.user, discord.Member) and i.user.guild_permissions.manage_guild):
        raise Oops("Action réservée aux administrateurs (Gérer le serveur).")


def modal(title, cid, *items):
    m = ui.Modal(title=title[:45], custom_id=cid, timeout=900)
    for item in items:
        m.add_item(item)
    return m


def text_input(label, cid, *, default=None, placeholder=None, paragraph=False, required=True, max_length=None,
               min_length=None):
    if default:
        default = str(default)[:max_length or 4000]
    return ui.TextInput(label=label[:45], custom_id=cid, default=default or None,
                        placeholder=placeholder, required=required, max_length=max_length, min_length=min_length,
                        style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)


def first(values, key):
    v = values.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def check_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or len(url) > 300:
        raise Oops("Les liens doivent commencer par https://")
    return url


async def refresh_panels(client, guild_id, kinds=None):
    """Met à jour les panneaux déjà publiés (prix, catégories, votes…)."""
    store = client.store
    done = 0
    for row in store.panels(guild_id):
        if kinds and row["kind"] not in kinds:
            continue
        builder = V.PANEL_BUILDERS.get(row["kind"])
        channel = client.get_channel(row["channel"])
        if not builder or channel is None:
            continue
        try:
            await channel.get_partial_message(row["message"]).edit(view=builder(store, guild_id)[0])
            done += 1
        except discord.NotFound:
            store.drop_panel(row["message"])
        except discord.HTTPException as exc:
            LOG.warning("Panneau %s non rafraîchi : %s", row["message"], exc)
    return done


# ====================================================================== tickets
def render_ticket(store, ticket):
    s = store.settings(ticket["guild"])
    rows = []
    if ticket["kind"] == "order":
        order = store.order(ticket["guild"], int(ticket["ref"] or 0))
        body = V.order_body(order, s) if order else ticket["subject"]
        if order:
            rows.append(V.order_row(order))
    else:
        body = ticket["subject"]
    if s.get("staff"):
        body += f"\n-# Staff notifié : <@&{s['staff']}>"
    return V.ticket_view(ticket, s, body, rows)


async def open_ticket(i, kind, body, ref=""):
    """Crée un salon de ticket privé. Lève Oops avec un message clair si impossible."""
    store = store_of(i)
    s = store.settings(i.guild_id)
    guild = i.guild
    category = guild.get_channel(s.get("category") or 0)
    if not isinstance(category, discord.CategoryChannel):
        raise Oops("Les tickets ne sont pas encore configurés. Un administrateur doit utiliser /setup.")
    me = guild.me
    perms = category.permissions_for(me)
    if not (perms.manage_channels and perms.manage_roles and perms.view_channel):
        raise Oops("NATIX n'a pas les permissions « Gérer les salons » et « Gérer les permissions » "
                   "sur la catégorie des tickets.")
    existing = store.open_ticket(i.guild_id, i.user.id, kind, ref if kind == "order" else None)
    if existing and guild.get_channel(existing["channel"]):
        raise Oops(f"Tu as déjà un ticket ouvert : <#{existing['channel']}>")
    if existing:  # salon supprimé à la main
        store.set_ticket(existing["channel"], state="deleted")

    number = store.next_ticket_number(i.guild_id)
    allow = dict(view_channel=True, send_messages=True, read_message_history=True, attach_files=True,
                 embed_links=True)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        i.user: discord.PermissionOverwrite(**allow),
        me: discord.PermissionOverwrite(**allow),
    }
    staff = guild.get_role(s.get("staff") or 0)
    if staff:
        overwrites[staff] = discord.PermissionOverwrite(**allow)
    prefix = {"order": "commande", "trade": "echange", "promo": "promo"}.get(kind, "ticket")
    try:
        channel = await guild.create_text_channel(
            f"{prefix}-{number:04d}-{slug(i.user.name, 20)}", category=category, overwrites=overwrites,
            topic=f"NATIX · {TICKET_KINDS.get(kind, ('Ticket',))[0]} · {i.user} ({i.user.id})",
            reason=f"Ticket NATIX ouvert par {i.user}")
    except discord.HTTPException as exc:
        LOG.warning("Création de ticket impossible : %s", exc)
        raise Oops("Impossible de créer le ticket (permissions ou limite de salons atteinte).")
    store.create_ticket(channel.id, i.guild_id, i.user.id, kind, number, ref, body)
    ticket = store.ticket(channel.id)
    mentions = discord.AllowedMentions(everyone=False, users=[i.user], roles=[staff] if staff else False)
    msg = await channel.send(view=render_ticket(store, ticket), allowed_mentions=mentions)
    store.set_ticket(channel.id, panel_message=msg.id)
    store.audit(i.guild_id, i.user.id, "ticket:open", f"{kind} {channel.id}")
    return channel


async def update_ticket_panel(i, ticket):
    store = store_of(i)
    ticket = store.ticket(ticket["channel"])
    view = render_ticket(store, ticket)
    if i.message and i.message.id == ticket["panel_message"] and not i.response.is_done():
        await i.response.edit_message(view=view)
        return
    if ticket["panel_message"]:
        try:
            await i.channel.get_partial_message(ticket["panel_message"]).edit(view=view)
        except discord.HTTPException:
            pass


def current_ticket(i):
    t = store_of(i).ticket(i.channel_id)
    if not t or t["state"] == "deleted":
        raise Oops("Ce salon n'est pas un ticket NATIX.")
    return t


def component_texts(components):
    out = []
    for c in components or []:
        content = getattr(c, "content", None)
        if isinstance(content, str):
            out.append(content)
        for attr in ("children", "components"):
            out.extend(component_texts(getattr(c, attr, None)))
        acc = getattr(c, "accessory", None)
        if acc is not None:
            out.extend(component_texts([acc]))
    return out


async def build_transcript(channel, ticket):
    lines = [f"NATIX · Transcript du ticket #{ticket['number']:04d} ({ticket['kind']})",
             f"Salon : #{channel.name} ({channel.id})", f"Propriétaire : {ticket['owner']}",
             f"Généré le : {time.strftime('%d/%m/%Y %H:%M:%S UTC', time.gmtime())}", "=" * 60]
    count = 0
    async for m in channel.history(limit=2000, oldest_first=True):
        count += 1
        stamp = m.created_at.strftime("%d/%m/%Y %H:%M")
        body = m.content or "\n".join(component_texts(m.components))
        lines.append(f"[{stamp}] {m.author} ({m.author.id}) : {body}")
        for a in m.attachments:
            lines.append(f"    pièce jointe : {a.filename} {a.url}")
    data = "\n".join(lines).encode("utf-8")
    return data, count


async def send_transcript(i, ticket, closed_by):
    store = store_of(i)
    s = store.settings(i.guild_id)
    data, count = await build_transcript(i.channel, ticket)
    name = f"transcript-{ticket['number']:04d}.txt"
    logs = i.guild.get_channel(s.get("logs") or 0)
    if not isinstance(logs, discord.TextChannel):
        return data, name, False
    kind = TICKET_KINDS.get(ticket["kind"], ("Ticket",))[0]
    card = V.view_of(V.container(
        ui.TextDisplay(f"### {E('nx_file')} Transcript · {kind} #{ticket['number']:04d}\n"
                       f"> Ouvert par <@{ticket['owner']}> · <t:{ticket['created']}:f>\n"
                       f"> Archivé par <@{closed_by}> · {count} messages"),
        ui.File(f"attachment://{name}"),
    ))
    try:
        await logs.send(view=card, file=discord.File(io.BytesIO(data), filename=name), allowed_mentions=NO_PINGS)
        return data, name, True
    except discord.HTTPException:
        return data, name, False


async def set_member_access(channel, member, allowed):
    if allowed:
        ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                         attach_files=True, embed_links=True)
        await channel.set_permissions(member, overwrite=ow, reason="NATIX ticket")
    else:
        await channel.set_permissions(member, overwrite=discord.PermissionOverwrite(view_channel=False),
                                      reason="NATIX ticket")


async def tk_claim(i, parts):
    require_staff(i)
    t = current_ticket(i)
    if t["state"] != "open":
        raise Oops("Ce ticket est fermé.")
    if t["claimed_by"] and t["claimed_by"] != i.user.id:
        raise Oops(f"Déjà pris en charge par <@{t['claimed_by']}>.")
    if t["claimed_by"] == i.user.id:
        raise Oops("Tu as déjà pris ce ticket en charge.")
    if not store_of(i).claim_ticket(i.channel_id, i.user.id):
        raise Oops("Ce ticket vient d'être pris en charge.")
    await update_ticket_panel(i, t)
    await i.channel.send(f"{E('nx_claim')} {i.user.mention} prend en charge ce ticket.", allowed_mentions=NO_PINGS)


async def tk_add(i, parts):
    t = current_ticket(i)
    if t["state"] != "open":
        raise Oops("Ce ticket est fermé.")
    if i.user.id != t["owner"]:
        require_staff(i)
    await reply(i, None, view=V.add_member_view())


async def tk_adduser(i, parts):
    t = current_ticket(i)
    if i.user.id != t["owner"]:
        require_staff(i)
    added = []
    for uid in i.data.get("values", []):
        member = i.guild.get_member(int(uid))
        if member is None:
            try:
                member = await i.guild.fetch_member(int(uid))
            except discord.HTTPException:
                continue
        if member.bot:
            continue
        await set_member_access(i.channel, member, True)
        added.append(member.mention)
    if not added:
        raise Oops("Aucun membre valide sélectionné.")
    await i.response.edit_message(view=V.notice("Ajouté : " + ", ".join(added)))
    await i.channel.send(f"{E('nx_userplus')} {', '.join(added)} ajouté(s) par {i.user.mention}.",
                         allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))


async def tk_close(i, parts):
    store = store_of(i)
    t = current_ticket(i)
    if i.user.id != t["owner"]:
        require_staff(i)
    if not store.transition_ticket(i.channel_id, "open", "closed"):
        raise Oops("Ce ticket est déjà fermé.")
    owner = i.guild.get_member(t["owner"])
    if owner:
        try:
            await set_member_access(i.channel, owner, False)
        except discord.HTTPException:
            pass
    for target, ow in list(i.channel.overwrites.items()):
        if isinstance(target, discord.Member) and not target.bot and target.id != t["owner"] and ow.view_channel:
            if not is_staff(target, store.settings(i.guild_id)):
                try:
                    await set_member_access(i.channel, target, False)
                except discord.HTTPException:
                    pass
    if t["kind"] == "trade":
        store.set_trade_state_by_channel(i.channel_id, "closed")
    await update_ticket_panel(i, t)
    if not i.response.is_done():
        await i.response.defer()
    await i.channel.send(view=V.view_of(V.container(
        ui.TextDisplay(f"{E('nx_lock')} Ticket fermé par {i.user.mention}."),
        V.ticket_controls("closed"))), allowed_mentions=NO_PINGS)


async def tk_reopen(i, parts):
    require_staff(i)
    store = store_of(i)
    t = current_ticket(i)
    if not store.transition_ticket(i.channel_id, "closed", "open"):
        raise Oops("Ce ticket est déjà ouvert.")
    owner = i.guild.get_member(t["owner"])
    if owner:
        await set_member_access(i.channel, owner, True)
    if t["kind"] == "trade":
        store.set_trade_state_by_channel(i.channel_id, "open")
    await update_ticket_panel(i, t)
    if not i.response.is_done():
        await i.response.defer()
    await i.channel.send(f"{E('nx_unlock')} Ticket rouvert par {i.user.mention}.", allowed_mentions=NO_PINGS)


async def tk_transcript(i, parts):
    require_staff(i)
    t = current_ticket(i)
    await i.response.defer(ephemeral=True, thinking=True)
    data, name, logged = await send_transcript(i, t, i.user.id)
    note = "Copie envoyée dans le salon des transcripts." if logged else "Salon des transcripts non configuré."
    await i.followup.send(f"{E('nx_file')} {note}", file=discord.File(io.BytesIO(data), filename=name),
                          ephemeral=True)


async def tk_delete(i, parts):
    require_staff(i)
    store = store_of(i)
    t = current_ticket(i)
    if t["state"] != "closed":
        raise Oops("Ferme le ticket avant de le supprimer.")
    await i.response.defer(ephemeral=True, thinking=True)
    _, _, logged = await send_transcript(i, t, i.user.id)
    if not logged:
        return await i.followup.send(
            "Transcript non archivé : configure un salon de transcripts dans /setup avant de supprimer.",
            ephemeral=True)
    store.set_ticket(i.channel_id, state="deleted")
    if t["kind"] == "trade":
        store.set_trade_state_by_channel(i.channel_id, "deleted")
    store.audit(i.guild_id, i.user.id, "ticket:delete", i.channel_id)
    await i.followup.send("Transcript archivé, suppression du ticket…", ephemeral=True)
    try:
        await i.channel.delete(reason=f"Ticket NATIX archivé par {i.user}")
    except discord.HTTPException:
        await i.channel.send("Suppression refusée : vérifie la permission « Gérer les salons ».")


# ====================================================================== commandes (orders)
async def ord_action(i, parts):
    require_staff(i)
    store = store_of(i)
    target, oid = parts[2], int(parts[3])
    if target not in ORDER_STATES:
        raise Oops("Action inconnue.")
    ok, err = store.transition_order(i.guild_id, oid, target, i.user.id)
    if not ok:
        raise Oops(err)
    t = store.ticket(i.channel_id)
    if t:
        await update_ticket_panel(i, t)
    if not i.response.is_done():
        await i.response.defer()
    order = store.order(i.guild_id, oid)
    msg = {"accepted": f"{E('nx_check')} Commande **#{oid}** acceptée par {i.user.mention}.",
           "delivered": f"{E('nx_box')} Commande **#{oid}** livrée ! Merci <@{order['buyer']}>, "
                        "n'hésite pas à laisser un avis.",
           "cancelled": f"{E('nx_cross')} Commande **#{oid}** annulée par {i.user.mention}. Stock restitué."}[target]
    await i.channel.send(msg, allowed_mentions=discord.AllowedMentions(
        users=[discord.Object(order["buyer"])] if target == "delivered" else False, roles=False, everyone=False))


# ====================================================================== boutique
async def reset_and_follow(i, panel_kind, view, files=None):
    """Réinitialise le menu du panneau public puis envoie la réponse en privé."""
    builder = V.PANEL_BUILDERS[panel_kind]
    await i.response.edit_message(view=builder(store_of(i), i.guild_id)[0])
    if view is not None:
        kwargs = {"view": view, "ephemeral": True, "allowed_mentions": NO_PINGS}
        if files:
            kwargs["files"] = files
        await i.followup.send(**kwargs)


async def home_nav(i, parts):
    value = i.data["values"][0]
    if value == "_reset":
        return await reset_and_follow(i, "home", None)
    view, files = V.PANEL_BUILDERS[value](store_of(i), i.guild_id)
    await reset_and_follow(i, "home", view, files)


async def shop_cat(i, parts):
    value = i.data["values"][0]
    if value == "_reset":
        return await reset_and_follow(i, "shop", None)
    if not store_of(i).category(i.guild_id, value):
        raise Oops("Catégorie introuvable.")
    await reset_and_follow(i, "shop", V.category_view(store_of(i), i.guild_id, value), [V.logo_file()])


async def show_category(i, key):
    if not store_of(i).category(i.guild_id, key):
        raise Oops("Catégorie introuvable.")
    view = V.category_view(store_of(i), i.guild_id, key)
    if i.message and i.message.flags.ephemeral:
        await i.response.edit_message(view=view)
    else:
        await i.response.send_message(view=view, files=[V.logo_file()], ephemeral=True)


async def shop_prod(i, parts):
    key = parts[3]
    value = i.data["values"][0]
    if value == "_reset":
        return await show_category(i, key)
    p = store_of(i).product(i.guild_id, int(value))
    if not p:
        raise Oops("Ce produit n'est plus disponible.")
    await i.response.edit_message(view=V.product_view(store_of(i), i.guild_id, p))


async def shop_back(i, parts):
    await show_category(i, parts[3])


async def buy(i, parts):
    p = store_of(i).product(i.guild_id, int(parts[2]))
    if not p:
        raise Oops("Ce produit n'est plus disponible.")
    if p["stock"] == 0:
        raise Oops("Ce produit est en rupture de stock.")
    max_qty = 99 if p["stock"] == -1 else min(99, p["stock"])
    await i.response.send_modal(modal(
        f"Commander · {p['name']}", f"nx:buym:{p['id']}",
        text_input(f"Quantité (1 à {max_qty})", "qty", default="1", max_length=2),
        text_input("Informations (optionnel)", "note", paragraph=True, required=False, max_length=400,
                   placeholder="Pseudo, serveur, précisions utiles…"),
    ))


async def buy_submit(i, parts):
    store = store_of(i)
    pid = int(parts[2])
    values = modal_values(i)
    try:
        qty = int(str(values.get("qty", "1")).strip())
    except ValueError:
        raise Oops("Quantité invalide.")
    if not 1 <= qty <= 99:
        raise Oops("Quantité invalide (1 à 99).")
    await i.response.defer(ephemeral=True, thinking=True)
    oid, err = store.create_order(i.guild_id, i.user.id, pid, qty, values.get("note") or "")
    if err:
        raise Oops(err)
    order = store.order(i.guild_id, oid)
    try:
        channel = await open_ticket(i, "order", V.order_body(order, store.settings(i.guild_id)), ref=oid)
    except Exception:
        store.transition_order(i.guild_id, oid, "cancelled", i.client.user.id)  # rend le stock
        raise
    store.attach_order(i.guild_id, oid, channel.id)
    await i.followup.send(view=V.notice(f"Commande **#{oid}** enregistrée. Ton ticket : {channel.mention}",
                                        "nx_cart"), ephemeral=True)


# ====================================================================== support / échanges / promos
async def support_kind(i, parts):
    kind = i.data["values"][0]
    if kind == "_reset":
        return await i.response.edit_message(view=V.support_panel(store_of(i), i.guild_id)[0])
    if kind not in TICKET_KINDS:
        raise Oops("Motif inconnu.")
    await i.response.send_modal(modal(
        f"Ticket · {TICKET_KINDS[kind][0]}", f"nx:supm:{kind}",
        text_input("Sujet", "subject", max_length=100, placeholder="En quelques mots"),
        text_input("Détails", "details", paragraph=True, required=False, max_length=1000),
    ))


async def support_submit(i, parts):
    kind = parts[2]
    v = modal_values(i)
    body = f"> **Sujet :** {safe(v.get('subject'), 100)}"
    if v.get("details"):
        body += "\n" + "\n".join("> " + safe(line, 300) for line in v["details"].splitlines() if line.strip())
    await i.response.defer(ephemeral=True, thinking=True)
    channel = await open_ticket(i, kind, body)
    await i.followup.send(view=V.notice(f"Ticket ouvert : {channel.mention}", "nx_ticket"), ephemeral=True)


async def trade_start(i, parts):
    existing = store_of(i).open_ticket(i.guild_id, i.user.id, "trade")
    if existing and i.guild.get_channel(existing["channel"]):
        raise Oops(f"Tu as déjà un échange en cours : <#{existing['channel']}>")
    await i.response.send_modal(modal(
        "Start A Trade", "nx:tradem",
        text_input("Tu donnes", "give", max_length=100, placeholder="Ex. 20€ PayPal"),
        text_input("Tu veux", "want", max_length=100, placeholder="Ex. 20€ en LTC"),
        text_input("Détails (optionnel)", "details", paragraph=True, required=False, max_length=500),
    ))


async def trade_submit(i, parts):
    store = store_of(i)
    v = modal_values(i)
    await i.response.defer(ephemeral=True, thinking=True)
    tid = store.create_trade(i.guild_id, i.user.id, v.get("give", ""), v.get("want", ""), v.get("details") or "")
    body = (f"> **Tu donnes :** {safe(v.get('give'), 100)}\n> **Tu veux :** {safe(v.get('want'), 100)}"
            + (f"\n> {safe(v.get('details'), 500)}" if v.get("details") else "")
            + f"\n-# Échange **#{tid}** · un membre du staff sécurise la transaction.")
    try:
        channel = await open_ticket(i, "trade", body, ref=tid)
    except Exception:
        store.execute("UPDATE trades SET state='cancelled' WHERE id=?", (tid,))
        raise
    store.attach_trade(tid, channel.id)
    await i.followup.send(view=V.notice(f"Échange **#{tid}** ouvert : {channel.mention}", "nx_trade"),
                          ephemeral=True)


async def trade_history(i, parts):
    await reply(i, None, view=V.trades_view(store_of(i), i.guild_id, i.user.id))


async def promo_plan(i, parts):
    store = store_of(i)
    s = store.settings(i.guild_id)
    p = store.plan(i.guild_id, parts[2])
    if not p:
        raise Oops("Ce plan n'existe plus.")
    await i.response.defer(ephemeral=True, thinking=True)
    steps = [f"{n}. {safe(line, 100)}" for n, line in enumerate(s["promo_steps"].splitlines(), 1) if line.strip()]
    body = (f"> **Plan :** {E(p['emoji'])} {safe(p['title'], 50)}\n"
            f"> **Prix :** {money(p['price_cents'], s['currency'])} · {safe(p['duration'], 40)}\n"
            + (f"> **Pings :** {p['pings']}\n" if p["pings"] else "")
            + "\n".join("> " + x for x in steps))
    channel = await open_ticket(i, "promo", body, ref=p["plan_key"])
    await i.followup.send(view=V.notice(f"Ticket promotion ouvert : {channel.mention}", "nx_megaphone"),
                          ephemeral=True)


# ====================================================================== avis
async def legit_vote(i, parts):
    store = store_of(i)
    result = store.vote(i.guild_id, i.user.id, parts[2] == "yes")
    await i.response.edit_message(view=V.reviews_panel(store, i.guild_id)[0])
    text = "Vote retiré." if result is None else ("Merci pour ton vote ✅" if result else "Vote ❌ enregistré.")
    await i.followup.send(text, ephemeral=True)


async def review_new(i, parts):
    last = store_of(i).last_review(i.guild_id, i.user.id)
    if last and time.time() - last["created"] < 86400:
        raise Oops(f"Tu as déjà laissé un avis. Prochain avis possible <t:{last['created'] + 86400}:R>.")
    await i.response.send_modal(modal(
        "Laisser un avis", "nx:revm",
        text_input("Note sur 5", "rating", max_length=1, placeholder="5"),
        text_input("Ton avis", "comment", paragraph=True, min_length=5, max_length=600,
                   placeholder="Livraison, rapidité, qualité du service…"),
    ))


async def review_submit(i, parts):
    store = store_of(i)
    v = modal_values(i)
    try:
        rating = int(str(v.get("rating", "")).strip())
    except ValueError:
        rating = 0
    if not 1 <= rating <= 5:
        raise Oops("La note doit être un chiffre entre 1 et 5.")
    store.add_review(i.guild_id, i.user.id, rating, v.get("comment", ""))
    await i.response.send_message(view=V.notice("Merci ! Ton avis a été publié.", "nx_star"), ephemeral=True)
    s = store.settings(i.guild_id)
    channel = i.guild.get_channel(s.get("reviews_channel") or 0)
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(view=V.review_card(i.user.id, rating, v.get("comment", "")), allowed_mentions=NO_PINGS)
        except discord.HTTPException:
            LOG.warning("Avis non publié dans %s", channel.id)
    await refresh_panels(i.client, i.guild_id, {"reviews"})


async def review_view(i, parts):
    await reply(i, None, view=V.review_stats_view(store_of(i), i.guild_id))


# ====================================================================== giveaways
async def gw_enter(i, parts):
    store = store_of(i)
    g = store.giveaway(i.message.id)
    if not g:
        raise Oops("Giveaway introuvable.")
    if g["closed"] or g["ends"] <= time.time():
        raise Oops("Ce giveaway est terminé.")
    joined = store.toggle_entry(g["message"], i.user.id)
    await i.response.edit_message(view=V.giveaway_view(g, len(store.entries(g["message"]))))
    await i.followup.send("Participation enregistrée, bonne chance !" if joined else "Participation retirée.",
                          ephemeral=True)


async def gw_list(i, parts):
    store = store_of(i)
    g = store.giveaway(i.message.id)
    if not g:
        raise Oops("Giveaway introuvable.")
    ids = store.entries(g["message"])
    shown = " ".join(f"<@{x}>" for x in ids[:60]) or "Aucun participant pour le moment."
    more = f"\n-# … et {len(ids) - 60} autres" if len(ids) > 60 else ""
    await reply(i, None, view=V.view_of(V.container(ui.TextDisplay(
        f"### {E('nx_search')} Participants · {len(ids)}\n{shown}{more}"))))


async def finish_giveaway(client, message_id, reroll=False):
    """Clôture (ou relance le tirage) d'un giveaway. Retourne un message de statut."""
    store = client.store
    g = store.giveaway(message_id)
    if not g:
        return "Giveaway introuvable."
    entries = store.entries(message_id)
    rng = secrets.SystemRandom()
    if reroll:
        if not g["closed"]:
            return "Ce giveaway n'est pas encore terminé."
        previous = {int(x) for x in (g["winner_ids"] or "").split(",") if x}
        pool = [x for x in entries if x not in previous] or entries
        winners = rng.sample(pool, min(g["winners"], len(pool))) if pool else []
        store.execute("UPDATE giveaways SET winner_ids=? WHERE message=?", (",".join(map(str, winners)), message_id))
    else:
        winners = rng.sample(entries, min(g["winners"], len(entries))) if entries else []
        if not store.close_giveaway(message_id, winners):
            return "Ce giveaway est déjà terminé."
    g = store.giveaway(message_id)
    channel = client.get_channel(g["channel"])
    if channel is None:
        try:
            channel = await client.fetch_channel(g["channel"])
        except discord.HTTPException:
            return "Giveaway clôturé, mais le salon est introuvable."
    try:
        msg = channel.get_partial_message(message_id)
        await msg.edit(view=V.giveaway_view(g, len(entries), ended=True))
        if winners:
            mentions = ", ".join(f"<@{w}>" for w in winners)
            await channel.send(f"{E('nx_gift')} Félicitations {mentions} ! Tu remportes **{safe(g['prize'], 100)}**."
                               f"\n-# Ouvre un ticket pour récupérer ton gain.",
                               reference=msg, mention_author=False,
                               allowed_mentions=discord.AllowedMentions(users=[discord.Object(w) for w in winners],
                                                                        roles=False, everyone=False))
        else:
            await channel.send(f"{E('nx_gift')} Giveaway **{safe(g['prize'], 100)}** terminé : aucun participant.",
                               reference=msg, mention_author=False, allowed_mentions=NO_PINGS)
    except discord.HTTPException:
        LOG.exception("Publication du résultat impossible")
        return "Giveaway clôturé, mais le résultat n'a pas pu être publié."
    return "Nouveau tirage effectué." if reroll else "Giveaway terminé, gagnant(s) tiré(s)."


# ====================================================================== configuration
async def cfg_home(i, parts):
    require_admin(i)
    await i.response.edit_message(view=V.setup_view(store_of(i), i.guild))


def _defaults(guild, *ids):
    """Valeurs pré-remplies des menus rôle/salon (ignore ce qui n'existe plus)."""
    out = []
    for x in ids:
        obj = guild.get_role(x or 0) or guild.get_channel(x or 0)
        if isinstance(obj, (discord.Role, discord.abc.GuildChannel, discord.Object)):
            out.append(obj)
    return out


async def cfg_open(i, parts):
    require_admin(i)
    store = store_of(i)
    s = store.settings(i.guild_id)
    section = parts[2]
    g = i.guild
    if section == "channels":
        m = modal("Salons & rôles", "nx:cfgm:channels",
                  ui.Label(text="Rôle staff", component=ui.RoleSelect(
                      custom_id="staff", required=False, min_values=0, default_values=_defaults(g, s["staff"]))),
                  ui.Label(text="Catégorie des tickets", component=ui.ChannelSelect(
                      custom_id="category", channel_types=[discord.ChannelType.category], required=False,
                      min_values=0, default_values=_defaults(g, s["category"]))),
                  ui.Label(text="Salon des transcripts (privé)", component=ui.ChannelSelect(
                      custom_id="logs", channel_types=[discord.ChannelType.text], required=False, min_values=0,
                      default_values=_defaults(g, s["logs"]))),
                  ui.Label(text="Salon des avis", component=ui.ChannelSelect(
                      custom_id="reviews_channel", channel_types=[discord.ChannelType.text], required=False,
                      min_values=0, default_values=_defaults(g, s["reviews_channel"]))),
                  ui.Label(text="Salon des promotions", component=ui.ChannelSelect(
                      custom_id="promo_channel", channel_types=[discord.ChannelType.text], required=False,
                      min_values=0, default_values=_defaults(g, s["promo_channel"]))))
    elif section == "identity":
        m = modal("Identité de la boutique", "nx:cfgm:identity",
                  text_input("Nom de la boutique", "name", default=s["name"], max_length=32),
                  text_input("Lien des Terms Of Services (https)", "tos_url", default=s["tos_url"], required=False),
                  text_input("Slogan boutique", "shop_tagline", default=s["shop_tagline"], max_length=150),
                  text_input("Slogan échanges", "exchange_tagline", default=s["exchange_tagline"], max_length=150),
                  text_input("Bannière personnalisée (URL https)", "banner_url", default=s["banner_url"],
                             required=False, placeholder="Laisser vide pour la bannière NATIX"))
    elif section == "texts":
        m = modal("Textes des panneaux", "nx:cfgm:texts",
                  text_input("Règlement (une règle par ligne)", "rules", default=s["rules"], paragraph=True,
                             max_length=3000),
                  text_input("Promotions · Inclus (une ligne = un point)", "promo_included",
                             default=s["promo_included"], paragraph=True, max_length=500),
                  text_input("Promotions · Comment ça marche", "promo_steps", default=s["promo_steps"],
                             paragraph=True, max_length=500),
                  text_input("Slogan support", "support_tagline", default=s["support_tagline"], max_length=150),
                  text_input("Slogan accueil", "home_tagline", default=s["home_tagline"], max_length=150))
    elif section == "social":
        m = modal("Réseaux officiels", "nx:cfgm:social",
                  *[text_input(f"{label} (https)", key, default=s[key], required=False)
                    for key, label, _ in V.SOCIALS])
    elif section == "restock":
        m = modal("Annonces de restock", "nx:cfgm:restock",
                  ui.Label(text="Salon des annonces", component=ui.ChannelSelect(
                      custom_id="restock_channel", channel_types=[discord.ChannelType.text], required=False,
                      min_values=0, default_values=_defaults(g, s["restock_channel"]))),
                  ui.Label(text="Mention", component=ui.Select(custom_id="restock_ping", options=[
                      discord.SelectOption(label="Aucune mention", value="none", default=s["restock_ping"] == "none"),
                      discord.SelectOption(label="@here", value="here", default=s["restock_ping"] == "here"),
                      discord.SelectOption(label="@everyone", value="everyone",
                                           default=s["restock_ping"] == "everyone")])))
    elif section == "cats":
        return await i.response.edit_message(view=V.categories_admin(store, i.guild_id))
    elif section == "plans":
        return await i.response.edit_message(view=V.plans_admin(store, i.guild_id))
    elif section == "refresh":
        await i.response.defer(ephemeral=True, thinking=True)
        n = await refresh_panels(i.client, i.guild_id)
        return await i.followup.send(view=V.notice(f"{n} panneau(x) mis à jour."), ephemeral=True)
    elif section == "home":
        return await cfg_home(i, parts)
    elif section == "catpick":
        key = i.data["values"][0]
        c = store.category(i.guild_id, key) if key != "_new" else None
        m = modal("Catégorie", f"nx:cfgm:cat:{key}",
                  text_input("Nom", "name", default=c["name"] if c else None, max_length=60),
                  text_input("Emoji (nom NATIX, Unicode ou <:emoji:id>)", "emoji",
                             default=c["emoji"] if c else "nx_other", max_length=60),
                  text_input("Description", "description", default=c["description"] if c else None,
                             max_length=100, required=False),
                  text_input("Visible ? (oui / non)", "active", default="oui" if not c or c["active"] else "non",
                             max_length=3))
    elif section == "planpick":
        key = i.data["values"][0]
        p = store.plan(i.guild_id, key) if key != "_new" else None
        m = modal("Plan de promotion", f"nx:cfgm:plan:{key}",
                  text_input("Nom du plan", "title", default=p["title"] if p else None, max_length=60),
                  text_input("Prix", "price", default=money(p["price_cents"], "") if p else None, max_length=10,
                             placeholder="10 ou 6.5"),
                  text_input("Durée", "duration", default=p["duration"] if p else None, max_length=40,
                             placeholder="7 jours"),
                  text_input("Pings", "pings", default=p["pings"] if p else None, required=False, max_length=120,
                             placeholder="`@here` tous les 3j"),
                  text_input("Emoji", "emoji", default=p["emoji"] if p else "nx_dollar", max_length=60))
    elif section == "plandel":
        store.delete_plan(i.guild_id, i.data["values"][0])
        await i.response.edit_message(view=V.plans_admin(store, i.guild_id))
        await refresh_panels(i.client, i.guild_id, {"promo"})
        return
    else:
        raise Oops("Section inconnue.")
    await i.response.send_modal(m)


async def cfg_submit(i, parts):
    require_admin(i)
    store = store_of(i)
    section = parts[2]
    v = modal_values(i)
    refresh = None
    back = "home"
    if section == "channels":
        def pick(key):
            val = first(v, key)
            return int(val) if val else 0
        values = {k: pick(k) for k in ("staff", "category", "logs", "reviews_channel", "promo_channel")}
        logs = i.guild.get_channel(values["logs"])
        if logs and logs.permissions_for(i.guild.default_role).view_channel:
            raise Oops("Le salon des transcripts doit être privé (invisible pour @everyone).")
        store.configure(i.guild_id, **values)
        refresh = {"promo"}
    elif section == "identity":
        store.configure(i.guild_id, name=v["name"].strip() or "NATIX", tos_url=check_url(v.get("tos_url")),
                        shop_tagline=v["shop_tagline"].strip(), exchange_tagline=v["exchange_tagline"].strip(),
                        banner_url=check_url(v.get("banner_url")))
        refresh = set()
    elif section == "texts":
        store.configure(i.guild_id, **{k: v[k].strip() for k in
                                      ("rules", "promo_included", "promo_steps", "support_tagline", "home_tagline")})
        refresh = set()
    elif section == "social":
        store.configure(i.guild_id, **{key: check_url(v.get(key)) for key, _, _ in V.SOCIALS})
        refresh = {"social"}
    elif section == "restock":
        ch = first(v, "restock_channel")
        ping = first(v, "restock_ping") or "none"
        store.configure(i.guild_id, restock_channel=int(ch) if ch else 0,
                        restock_ping=ping if ping in ("none", "here", "everyone") else "none")
    elif section == "cat":
        key = parts[3]
        name = v["name"].strip()
        if key == "_new":
            key = slug(name, 20).replace("-", "")[:20] or f"cat{int(time.time())}"
            if store.category(i.guild_id, key):
                key = f"{key}{int(time.time()) % 1000}"
        store.save_category(i.guild_id, key, name, v["emoji"].strip() or "nx_other",
                            (v.get("description") or "").strip(),
                            0 if v["active"].strip().lower() in ("non", "no", "n") else 1)
        refresh, back = {"shop", "home"}, "cats"
    elif section == "plan":
        key = parts[3]
        cents = parse_price(v["price"])
        if cents is None:
            raise Oops("Prix invalide (ex. 10 ou 6.5).")
        if key == "_new":
            if len(store.plans(i.guild_id)) >= 6:
                raise Oops("6 plans maximum.")
            key = slug(v["title"], 20).replace("-", "") or f"plan{int(time.time())}"
        store.save_plan(i.guild_id, key, v["title"].strip(), cents, v["duration"].strip(),
                        (v.get("pings") or "").strip(), v["emoji"].strip() or "nx_dollar")
        refresh, back = {"promo"}, "plans"
    else:
        raise Oops("Section inconnue.")
    store.audit(i.guild_id, i.user.id, "config:" + section)
    view = {"home": lambda: V.setup_view(store, i.guild), "cats": lambda: V.categories_admin(store, i.guild_id),
            "plans": lambda: V.plans_admin(store, i.guild_id)}[back]()
    if i.message is not None:
        await i.response.edit_message(view=view)
    else:
        await i.response.send_message(view=view, ephemeral=True)
    if refresh is not None:
        await refresh_panels(i.client, i.guild_id, refresh or None)


# ====================================================================== routeur
ROUTES = [
    (r"^nx:home:nav$", home_nav),
    (r"^nx:shop:cat$", shop_cat),
    (r"^nx:shop:prod:[\w-]+$", shop_prod),
    (r"^nx:shop:back:[\w-]+$", shop_back),
    (r"^nx:buy:\d+$", buy),
    (r"^nx:buym:\d+$", buy_submit),
    (r"^nx:ord:\w+:\d+$", ord_action),
    (r"^nx:sup:kind$", support_kind),
    (r"^nx:supm:\w+$", support_submit),
    (r"^nx:trade:start$", trade_start),
    (r"^nx:tradem$", trade_submit),
    (r"^nx:trade:history$", trade_history),
    (r"^nx:promo:[\w-]+$", promo_plan),
    (r"^nx:legit:(yes|no)$", legit_vote),
    (r"^nx:rev:new$", review_new),
    (r"^nx:revm$", review_submit),
    (r"^nx:rev:view$", review_view),
    (r"^nx:gw:enter$", gw_enter),
    (r"^nx:gw:list$", gw_list),
    (r"^nx:tk:claim$", tk_claim),
    (r"^nx:tk:add$", tk_add),
    (r"^nx:tk:adduser$", tk_adduser),
    (r"^nx:tk:close$", tk_close),
    (r"^nx:tk:reopen$", tk_reopen),
    (r"^nx:tk:transcript$", tk_transcript),
    (r"^nx:tk:delete$", tk_delete),
    (r"^nx:cfg:\w+$", cfg_open),
    (r"^nx:cfgm:\w+(:[\w-]+)?$", cfg_submit),
]
COMPILED = [(re.compile(p), fn) for p, fn in ROUTES]


def find_route(custom_id):
    for pattern, fn in COMPILED:
        if pattern.match(custom_id):
            return fn
    return None


async def route(i: discord.Interaction):
    if i.type not in (discord.InteractionType.component, discord.InteractionType.modal_submit):
        return
    cid = (i.data or {}).get("custom_id", "")
    if not cid.startswith("nx:"):
        return
    fn = find_route(cid)
    if fn is None:
        return await reply(i, "Ce bouton n'est plus actif. Demande au staff de republier le panneau.")
    if i.guild is None:
        return await reply(i, "NATIX fonctionne uniquement sur un serveur.")
    try:
        await fn(i, cid.split(":"))
    except Oops as exc:
        await safe_reply(i, f"{E('nx_cross')} {exc}")
    except discord.Forbidden:
        LOG.warning("Permission manquante pour %s", cid)
        await safe_reply(i, f"{E('nx_cross')} NATIX n'a pas la permission nécessaire pour cette action.")
    except Exception:
        LOG.exception("Erreur interaction %s", cid)
        await safe_reply(i, f"{E('nx_cross')} Une erreur est survenue, réessaie dans un instant.")


async def safe_reply(i, text):
    try:
        await reply(i, text)
    except discord.HTTPException:
        pass
