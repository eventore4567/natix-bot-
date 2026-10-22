"""Panneaux Discord Components V2 (fidèles aux captures de référence).

Les vues ne sont jamais conservées en mémoire : chaque bouton/menu porte un
custom_id stable (« nx:… ») traité par le routeur de natix/handlers.py, ce qui
les rend fonctionnels même après un redémarrage du bot.
"""
import discord
from discord import ui

from .config import BANNERS, ORDER_STATES, TICKET_KINDS
from .emojis import EMOJIS
from .util import money, safe, stock_text

E = EMOJIS.text
P = EMOJIS.partial
LOGO = "natix_logo.png"


class Layout(ui.LayoutView):
    """Vue Components V2 sans état : le routeur global gère les interactions."""

    def __init__(self):
        super().__init__(timeout=None)

    def is_dispatchable(self):
        return False


# ------------------------------------------------------------------ éléments communs
def banner_file(kind):
    return discord.File(BANNERS / f"{kind}.png", filename=f"natix_{kind}.png")


def logo_file():
    return discord.File(BANNERS / "logo.png", filename=LOGO)


def banner(kind, s):
    url = s.get("banner_url") or f"attachment://natix_{kind}.png"
    return ui.MediaGallery(discord.MediaGalleryItem(url))


def thumb():
    return ui.Thumbnail(f"attachment://{LOGO}")


def tos_line(s):
    if s.get("tos_url"):
        return f"We recommend reviewing our [Terms Of Services]({s['tos_url']})."
    return "We recommend reviewing our **Terms Of Services**."


def header(kind, s, title, body, with_banner=True):
    items = []
    if with_banner:
        items += [banner(kind, s), ui.Separator(spacing=discord.SeparatorSpacing.large)]
    items.append(ui.Section(ui.TextDisplay(f"{title}\n{body}"), accessory=thumb()))
    return items


def files_for(kind, s):
    files = [logo_file()]
    if not s.get("banner_url"):
        files.insert(0, banner_file(kind))
    return files


def quote(lines):
    return "\n".join("> " + line for line in lines if line.strip())


def btn(label, cid, emoji=None, style=discord.ButtonStyle.secondary, disabled=False):
    return ui.Button(label=label, custom_id=cid, emoji=P(emoji) if emoji else None,
                     style=style, disabled=disabled)


def reset_option():
    return discord.SelectOption(label="Resélectionner", value="_reset",
                                description="Réinitialiser le menu", emoji=P("nx_clock"))


def container(*items):
    return ui.Container(*[i for i in items if i is not None])


def view_of(*items):
    v = Layout()
    for item in items:
        v.add_item(item)
    return v


# ------------------------------------------------------------------ accueil
def home_panel(store, guild_id):
    s = store.settings(guild_id)
    name = safe(s["name"], 40)
    cats = store.categories(guild_id)
    services = "\n".join(f"{E(c['emoji'])} **{safe(c['name'], 60)}** · {safe(c['description'], 90)}"
                         for c in cats)
    select = ui.Select(custom_id="nx:home:nav", placeholder="Pick a section", options=[
        discord.SelectOption(label="Shop", value="shop", description="Catégories et produits", emoji=P("nx_food")),
        discord.SelectOption(label="Exchange", value="exchange", description="Démarrer un échange", emoji=P("nx_trade")),
        discord.SelectOption(label="Promotion Slots", value="promo", description="Promouvoir ton serveur",
                             emoji=P("nx_megaphone")),
        discord.SelectOption(label="Support", value="support", description="Ouvrir un ticket privé",
                             emoji=P("nx_ticket")),
        discord.SelectOption(label="Reviews", value="reviews", description="Avis clients", emoji=P("nx_star")),
        discord.SelectOption(label="Terms Of Services", value="rules", description="Règlement", emoji=P("nx_book")),
        discord.SelectOption(label="Socials", value="social", description="Nos réseaux", emoji=P("nx_link")),
        reset_option(),
    ])
    v = view_of(container(
        *header("home", s, f"## {E('nx_home')} Welcome To __{name}__",
                quote([f"At **{name}**, {safe(s['home_tagline'], 200)}", tos_line(s)])),
        ui.Separator(),
        ui.TextDisplay(f"### {E('nx_box')} Nos services\n{services or 'Bientôt disponible.'}"),
        ui.Separator(),
        ui.ActionRow(select),
    ))
    return v, files_for("home", s)


# ------------------------------------------------------------------ boutique
def shop_panel(store, guild_id):
    s = store.settings(guild_id)
    name = safe(s["name"], 40)
    options = [discord.SelectOption(label=c["name"][:100], value=c["key"], emoji=P(c["emoji"]))
               for c in store.categories(guild_id)[:24]]
    options.append(reset_option())
    v = view_of(container(
        *header("shop", s, f"## {E('nx_food')} Welcome To __{name} Shop__",
                quote([f"At **{name}**, {safe(s['shop_tagline'], 200)}", tos_line(s)])),
        ui.Separator(),
        ui.ActionRow(ui.Select(custom_id="nx:shop:cat", placeholder="Pick a category", options=options)),
    ))
    return v, files_for("shop", s)


def category_view(store, guild_id, key):
    s = store.settings(guild_id)
    cat = store.category(guild_id, key)
    products = store.products(guild_id, key, limit=24)
    title = f"## {E(cat['emoji'])} {safe(cat['name'], 80)}"
    body = quote([safe(cat["description"], 200)]) + f"\n-# {len(products)} produit(s) disponible(s)"
    items = [ui.Section(ui.TextDisplay(f"{title}\n{body}"), accessory=thumb()), ui.Separator()]
    if products:
        opts = []
        for p in products:
            desc = f"{money(p['price_cents'], s['currency'])} · "
            desc += "Rupture de stock" if p["stock"] == 0 else safe(p["details"] or stock_text(p["stock"]), 90)
            opts.append(discord.SelectOption(label=p["name"][:100], value=str(p["id"]), description=desc[:100],
                                             emoji=P(p["emoji"] or cat["emoji"])))
        opts.append(reset_option())
        items.append(ui.ActionRow(ui.Select(custom_id=f"nx:shop:prod:{key}", placeholder="Pick a product",
                                            options=opts)))
    else:
        items.append(ui.TextDisplay(f"{E('nx_clock')} Aucun produit pour le moment, reviens bientôt."))
    return view_of(container(*items))


def product_view(store, guild_id, product):
    s = store.settings(guild_id)
    cat = store.category(guild_id, product["category"])
    cat_name = safe(cat["name"], 60) if cat else "Boutique"
    emoji = product["emoji"] or (cat["emoji"] if cat else "nx_box")
    lines = [
        f"## {E(emoji)} {safe(product['name'], 80)}",
        quote([safe(product["details"], 300)]) if product["details"] else "",
        "",
        f"{E('nx_dollar')} **Prix** · {money(product['price_cents'], s['currency'])}",
        f"{E('nx_box')} **Stock** · {stock_text(product['stock'])}",
        f"{E('nx_tag')} **Catégorie** · {cat_name}",
    ]
    out = product["stock"] == 0
    return view_of(container(
        ui.Section(ui.TextDisplay("\n".join(l for l in lines if l is not None)), accessory=thumb()),
        ui.Separator(),
        ui.ActionRow(
            btn("Rupture de stock" if out else "Commander", f"nx:buy:{product['id']}", "nx_cart",
                discord.ButtonStyle.success, disabled=out),
            btn("Retour", f"nx:shop:back:{product['category']}", "nx_reset"),
        ),
    ))


# ------------------------------------------------------------------ support
def support_panel(store, guild_id):
    s = store.settings(guild_id)
    name = safe(s["name"], 40)
    options = [discord.SelectOption(label=label, value=key, description=desc[:100], emoji=P(emoji))
               for key, (label, emoji, desc) in TICKET_KINDS.items() if desc]
    options.append(reset_option())
    v = view_of(container(
        *header("support", s, f"## {E('nx_ticket')} Welcome To __{name} Support__",
                quote([f"At **{name}**, {safe(s['support_tagline'], 200)}", tos_line(s)])),
        ui.Separator(),
        ui.ActionRow(ui.Select(custom_id="nx:sup:kind", placeholder="Pick a reason", options=options)),
    ))
    return v, files_for("support", s)


# ------------------------------------------------------------------ échanges
def exchange_panel(store, guild_id):
    s = store.settings(guild_id)
    name = safe(s["name"], 40)
    v = view_of(container(
        *header("exchange", s, f"## {E('nx_trade')} Welcome To __{name} Exchange__",
                quote([f"At **{name}**, {safe(s['exchange_tagline'], 200)}", tos_line(s)])),
        ui.Separator(),
        ui.ActionRow(btn("Start A Trade", "nx:trade:start", "nx_trade"),
                     btn("Previous Trades", "nx:trade:history", "nx_clock")),
    ))
    return v, files_for("exchange", s)


def trades_view(store, guild_id, user_id):
    rows = store.trades(guild_id, user_id)
    states = {"open": "En cours", "closed": "Terminé", "deleted": "Archivé"}
    if rows:
        lines = [f"**#{t['id']}** · {safe(t['give'], 60)} → {safe(t['want'], 60)}\n"
                 f"-# {states.get(t['state'], t['state'])} · <t:{t['created']}:R>"
                 + (f" · <#{t['channel']}>" if t["channel"] and t["state"] == "open" else "")
                 for t in rows]
        body = "\n".join(lines)
    else:
        body = "Aucun échange pour le moment. Clique sur **Start A Trade** pour commencer."
    return view_of(container(ui.TextDisplay(f"## {E('nx_clock')} Previous Trades\n{body}")))


# ------------------------------------------------------------------ promotions
def promo_panel(store, guild_id):
    s = store.settings(guild_id)
    where = f"<#{s['promo_channel']}>" if s.get("promo_channel") else "dédié"
    items = header("promo", s, f"## {E('nx_food')} Promotion Slots",
                   f"Salon {where} pour promouvoir ton serveur.\nChoisis un plan pour ouvrir un ticket.")
    items += [ui.Separator(),
              ui.TextDisplay("### Inclus\n" + quote(s["promo_included"].splitlines()))]
    for p in store.plans(guild_id):
        details = [f"**{money(p['price_cents'], s['currency'])}** · {safe(p['duration'], 40)}"]
        if p["pings"]:
            details.append(p["pings"].replace("@", "@​") if "`" not in p["pings"] else p["pings"])
        items += [ui.Separator(), ui.Section(
            ui.TextDisplay(f"### {E(p['emoji'])} {safe(p['title'], 50)}\n" + quote(details)),
            accessory=ui.Button(custom_id=f"nx:promo:{p['plan_key']}", emoji=P(p["emoji"]) or P("nx_dollar"),
                                style=discord.ButtonStyle.secondary))]
    steps = [f"{n}. {line}" for n, line in enumerate(s["promo_steps"].splitlines(), 1) if line.strip()]
    items += [ui.Separator(), ui.TextDisplay("### Comment ça marche\n" + quote(steps))]
    return view_of(container(*items)), files_for("promo", s)


# ------------------------------------------------------------------ avis
def reviews_panel(store, guild_id):
    s = store.settings(guild_id)
    yes, no = store.votes(guild_id)
    avg, total, _, _ = store.review_stats(guild_id)
    rating = f"\n-# {E('nx_star')} {avg:.1f}/5 · {total} avis" if total else ""
    v = view_of(container(
        *header("reviews", s, "## Are we legit?",
                f"✅ = Yes\n❌ = {safe(s['legit_no'], 80)}{rating}"),
        ui.Separator(),
        ui.ActionRow(
            ui.Button(label=str(yes), emoji="✅", custom_id="nx:legit:yes", style=discord.ButtonStyle.secondary),
            ui.Button(label=str(no), emoji="❌", custom_id="nx:legit:no", style=discord.ButtonStyle.secondary),
            btn("Laisser un avis", "nx:rev:new", "nx_star", discord.ButtonStyle.primary),
            btn("Voir les avis", "nx:rev:view", "nx_search"),
        ),
    ))
    return v, files_for("reviews", s)


def stars(n):
    return "★" * n + "☆" * (5 - n)


def review_card(author_id, rating, comment):
    return view_of(container(ui.TextDisplay(
        f"### {E('nx_star')} Nouvel avis · {stars(rating)}\n" + quote([safe(comment, 600)])
        + f"\n-# par <@{author_id}>")))


def review_stats_view(store, guild_id):
    avg, total, dist, recent = store.review_stats(guild_id)
    yes, no = store.votes(guild_id)
    if not total:
        body = "Aucun avis pour le moment. Sois le premier à donner le tien !"
    else:
        bars = "\n".join(f"`{k}★` {'█' * round(dist[k] / total * 12):<12} {dist[k]}" for k in range(5, 0, -1))
        last = "\n".join(f"{stars(r['rating'])} · {safe(r['comment'], 80)} · <@{r['author']}>" for r in recent)
        body = f"**{avg:.1f}/5** sur {total} avis\n{bars}\n\n**Derniers avis**\n{last}"
    return view_of(container(ui.TextDisplay(
        f"## {E('nx_star')} Avis clients\n{body}\n-# Legit : ✅ {yes} · ❌ {no}")))


# ------------------------------------------------------------------ règlement / réseaux
def rules_panel(store, guild_id):
    s = store.settings(guild_id)
    lines = [f"**{n}.** {safe(line, 300)}" for n, line in enumerate(s["rules"].splitlines(), 1) if line.strip()]
    v = view_of(container(
        *header("rules", s, f"## {E('nx_book')} Terms Of Services",
                f"Les règles de **{safe(s['name'], 40)}**, à lire avant toute commande."),
        ui.Separator(),
        ui.TextDisplay(quote(lines) or "Règlement à venir."),
        ui.Separator(),
        ui.TextDisplay(f"-# {E('nx_shield')} Commander ou ouvrir un ticket vaut acceptation de ce règlement."),
    ))
    return v, files_for("rules", s)


SOCIALS = [("social_discord", "Discord", "nx_message"), ("social_tiktok", "TikTok", "nx_megaphone"),
           ("social_instagram", "Instagram", "nx_heart"), ("social_youtube", "YouTube", "nx_star"),
           ("social_site", "Site web", "nx_link")]


def social_panel(store, guild_id):
    s = store.settings(guild_id)
    buttons = [ui.Button(label=label, url=s[key], emoji=P(emoji)) for key, label, emoji in SOCIALS if s.get(key)]
    v = view_of(container(
        *header("social", s, f"## {E('nx_link')} Socials",
                quote([f"Suis **{safe(s['name'], 40)}** sur nos réseaux officiels.",
                       "Méfie-toi des faux comptes : seuls ces liens sont officiels."])),
        ui.Separator(),
        ui.ActionRow(*buttons) if buttons else ui.TextDisplay("-# Aucun lien configuré pour le moment."),
    ))
    return v, files_for("social", s)


PANEL_BUILDERS = {
    "home": home_panel, "shop": shop_panel, "support": support_panel, "exchange": exchange_panel,
    "promo": promo_panel, "reviews": reviews_panel, "rules": rules_panel, "social": social_panel,
}


# ------------------------------------------------------------------ giveaways
def giveaway_view(g, count, ended=False):
    title = f"## {E('nx_gift')} {safe(g['prize'], 100)}"
    win = f"### {E('nx_gift')} {g['winners']} winner{'s' if g['winners'] > 1 else ''}"
    if ended:
        ids = [x for x in (g["winner_ids"] or "").split(",") if x]
        names = ", ".join(f"<@{x}>" for x in ids) or "Aucun participant"
        state = f"### Ended <t:{g['ends']}:R>\n{E('nx_crown')} **Gagnant{'s' if len(ids) > 1 else ''} :** {names}"
    else:
        state = f"### Ends <t:{g['ends']}:R>"
    return view_of(container(
        ui.TextDisplay(f"{title}\n{win}\n{state}"),
        ui.Separator(),
        ui.ActionRow(
            btn(f"Enter ({count})", "nx:gw:enter", "nx_gift", discord.ButtonStyle.primary, disabled=ended),
            btn("Participants", "nx:gw:list", "nx_search"),
        ),
    ))


# ------------------------------------------------------------------ tickets
def ticket_controls(state, claimed_by=0):
    if state == "open":
        return ui.ActionRow(
            btn("Pris en charge" if claimed_by else "Prendre en charge", "nx:tk:claim", "nx_claim",
                discord.ButtonStyle.success if not claimed_by else discord.ButtonStyle.secondary),
            btn("Ajouter un membre", "nx:tk:add", "nx_userplus"),
            btn("Fermer", "nx:tk:close", "nx_lock", discord.ButtonStyle.danger),
        )
    return ui.ActionRow(
        btn("Rouvrir", "nx:tk:reopen", "nx_unlock", discord.ButtonStyle.success),
        btn("Transcript", "nx:tk:transcript", "nx_file"),
        btn("Supprimer", "nx:tk:delete", "nx_trash", discord.ButtonStyle.danger),
    )


def ticket_view(ticket, settings, body, extra_rows=()):
    kind = TICKET_KINDS.get(ticket["kind"], ("Ticket", "nx_ticket", ""))
    claimed = f"\n{E('nx_claim')} Pris en charge par <@{ticket['claimed_by']}>" if ticket["claimed_by"] else ""
    state = "" if ticket["state"] == "open" else f"\n{E('nx_lock')} **Ticket fermé**"
    text = (f"## {E(kind[1])} {kind[0]} · #{ticket['number']:04d}\n"
            f"{body}\n-# Ouvert par <@{ticket['owner']}> · <t:{ticket['created']}:R>{claimed}{state}")
    rows = list(extra_rows) if ticket["state"] == "open" else []
    return view_of(container(ui.TextDisplay(text), ui.Separator(), *rows,
                             ticket_controls(ticket["state"], ticket["claimed_by"])))


def order_body(order, settings):
    lines = [
        f"> **{safe(order['product_name'], 80)}** × {order['quantity']}",
        f"> Total : **{money(order['total_cents'], settings['currency'])}**",
        f"> Commande : **#{order['id']}** · Statut : **{ORDER_STATES.get(order['state'], order['state'])}**",
    ]
    if order["notes"]:
        lines.append(f"> Infos : {safe(order['notes'], 300)}")
    lines.append("-# Le paiement se fait uniquement dans ce ticket.")
    return "\n".join(lines)


CURRENCY_CODES = {"€": "EUR", "$": "USD", "£": "GBP", "CHF": "CHF", "CAD": "CAD"}


def paypal_link(s, cents):
    """Lien PayPal.me avec le montant pré-rempli (ou None si PayPal n'est pas configuré)."""
    base = (s.get("paypal") or "").strip()
    if not base:
        return None
    if not base.startswith("https://"):
        base = "https://paypal.me/" + base.lstrip("@")
    code = CURRENCY_CODES.get(s.get("currency", "€").strip(), "EUR")
    return f"{base.rstrip('/')}/{int(cents) / 100:.2f}{code}"


def payment_section(s, cents, paid):
    """Bloc paiement d'un ticket : montant, consignes, bouton PayPal et « J'ai payé »."""
    if not (s.get("paypal") or s.get("paypal_email") or s.get("pay_other")):
        return []
    lines = [f"> Montant : **{money(cents, s['currency'])}**"]
    if s.get("paypal_email"):
        lines.append(f"> PayPal : `{safe(s['paypal_email'], 80)}`")
    if s.get("pay_note"):
        lines.append(f"> {safe(s['pay_note'], 200)}")
    lines += [f"> {safe(x, 200)}" for x in (s.get("pay_other") or "").splitlines() if x.strip()]
    hint = (f"{E('nx_check')} **Paiement signalé** · le staff vérifie et valide ta commande." if paid else
            "-# Une fois le paiement envoyé, clique sur **J'ai payé**.")
    buttons = []
    link = paypal_link(s, cents)
    if link:
        buttons.append(ui.Button(label="Payer avec PayPal", url=link, emoji=P("nx_dollar")))
    buttons.append(btn("Paiement signalé" if paid else "J'ai payé", "nx:pay:done", "nx_check",
                       discord.ButtonStyle.success, disabled=bool(paid)))
    return [ui.TextDisplay(f"### {E('nx_dollar')} Paiement\n" + "\n".join(lines) + "\n" + hint),
            ui.ActionRow(*buttons), ui.Separator()]


def order_row(order):
    st = order["state"]
    return ui.ActionRow(
        btn("Accepter", f"nx:ord:accepted:{order['id']}", "nx_check", discord.ButtonStyle.success,
            disabled=st != "pending"),
        btn("Livrée", f"nx:ord:delivered:{order['id']}", "nx_box", discord.ButtonStyle.primary,
            disabled=st != "accepted"),
        btn("Annuler", f"nx:ord:cancelled:{order['id']}", "nx_cross", discord.ButtonStyle.danger,
            disabled=st not in ("pending", "accepted")),
    )


def add_member_view():
    return view_of(container(
        ui.TextDisplay(f"### {E('nx_userplus')} Ajouter un membre au ticket"),
        ui.ActionRow(ui.UserSelect(custom_id="nx:tk:adduser", placeholder="Choisir un membre",
                                   min_values=1, max_values=3)),
    ))


# ------------------------------------------------------------------ configuration
def setup_view(store, guild):
    s = store.settings(guild.id)
    m = store.metrics(guild.id)

    def ch(key):
        return f"<#{s[key]}>" if s.get(key) else "*non défini*"

    staff = f"<@&{s['staff']}>" if s.get("staff") else "*non défini*"
    status = "\n".join([
        f"{E('nx_shield')} **Staff** · {staff}",
        f"{E('nx_ticket')} **Catégorie tickets** · {ch('category')}",
        f"{E('nx_archive')} **Transcripts** · {ch('logs')}",
        f"{E('nx_megaphone')} **Restock** · {ch('restock_channel')} · ping `{s['restock_ping']}`",
        f"{E('nx_star')} **Avis** · {ch('reviews_channel')}",
        f"{E('nx_food')} **Promotions** · {ch('promo_channel')}",
        f"{E('nx_dollar')} **PayPal** · " + (f"`{safe(s['paypal'], 60)}`" if s.get("paypal") else
                                            f"`{safe(s['paypal_email'], 60)}`" if s.get("paypal_email")
                                            else "*non défini*"),
    ])
    ready = s.get("staff") and s.get("category") and s.get("logs")
    hint = ("-# Tout est prêt. Publie les panneaux avec `/panel`." if ready else
            f"-# {E('nx_info')} Commence par **Salons & rôles** : staff, catégorie tickets et transcripts.")
    return view_of(container(
        ui.TextDisplay(f"## {E('nx_settings')} Configuration · {safe(s['name'], 40)}\n"
                       f"-# {m['products']} produits · {m['pending']} commandes en cours · "
                       f"{m['tickets']} tickets ouverts"),
        ui.Separator(),
        ui.TextDisplay(status),
        ui.Separator(),
        ui.ActionRow(btn("Salons & rôles", "nx:cfg:channels", "nx_shield", discord.ButtonStyle.primary),
                     btn("Identité", "nx:cfg:identity", "nx_tag"),
                     btn("Textes", "nx:cfg:texts", "nx_book"),
                     btn("Réseaux", "nx:cfg:social", "nx_link"),
                     btn("Paiements", "nx:cfg:payment", "nx_dollar", discord.ButtonStyle.primary)),
        ui.ActionRow(btn("Catégories", "nx:cfg:cats", "nx_list"),
                     btn("Promotions", "nx:cfg:plans", "nx_dollar"),
                     btn("Restock", "nx:cfg:restock", "nx_megaphone"),
                     btn("Rafraîchir les panneaux", "nx:cfg:refresh", "nx_reset", discord.ButtonStyle.success)),
        ui.TextDisplay(hint),
    ))


def categories_admin(store, guild_id):
    cats = store.categories(guild_id, include_inactive=True)
    lines = "\n".join(f"{E(c['emoji'])} **{safe(c['name'], 50)}** `{c['key']}`"
                      + ("" if c["active"] else " · *masquée*") for c in cats)
    opts = [discord.SelectOption(label=c["name"][:100], value=c["key"], emoji=P(c["emoji"])) for c in cats[:24]]
    opts.append(discord.SelectOption(label="Nouvelle catégorie", value="_new", emoji=P("nx_userplus")))
    return view_of(container(
        ui.TextDisplay(f"## {E('nx_list')} Catégories de la boutique\n{lines}"),
        ui.ActionRow(ui.Select(custom_id="nx:cfg:catpick", placeholder="Modifier ou créer une catégorie",
                               options=opts)),
        ui.ActionRow(btn("Retour", "nx:cfg:home", "nx_reset")),
    ))


def plans_admin(store, guild_id):
    s = store.settings(guild_id)
    plans = store.plans(guild_id)
    lines = "\n".join(f"{E(p['emoji'])} **{safe(p['title'], 40)}** · {money(p['price_cents'], s['currency'])}"
                      f" · {safe(p['duration'], 30)}" for p in plans) or "Aucun plan."
    opts = [discord.SelectOption(label=p["title"][:100], value=p["plan_key"], emoji=P(p["emoji"])) for p in plans]
    rows = []
    if len(plans) < 6:
        opts.append(discord.SelectOption(label="Nouveau plan", value="_new", emoji=P("nx_userplus")))
    rows.append(ui.ActionRow(ui.Select(custom_id="nx:cfg:planpick", placeholder="Modifier ou créer un plan",
                                       options=opts)))
    if plans:
        rows.append(ui.ActionRow(ui.Select(custom_id="nx:cfg:plandel", placeholder="Supprimer un plan", options=[
            discord.SelectOption(label=p["title"][:100], value=p["plan_key"], emoji=P("nx_trash")) for p in plans])))
    return view_of(container(
        ui.TextDisplay(f"## {E('nx_dollar')} Plans de promotion\n{lines}\n-# 6 plans maximum."),
        *rows,
        ui.ActionRow(btn("Retour", "nx:cfg:home", "nx_reset")),
    ))


def notice(text, emoji="nx_check"):
    return view_of(container(ui.TextDisplay(f"{E(emoji)} {text}")))
