"""Petits utilitaires partagés."""
import re

import discord

NO_PINGS = discord.AllowedMentions.none()


def safe(text, limit=200):
    """Texte utilisateur sans Markdown ni mentions actives."""
    text = discord.utils.escape_markdown(str(text or ""))
    text = discord.utils.escape_mentions(text)
    return text[:limit]


def money(cents, currency="€"):
    cents = int(cents or 0)
    if cents % 100 == 0:
        value = str(cents // 100)
    else:
        value = f"{cents / 100:.2f}".rstrip("0").rstrip(".")
    return value + currency


def stock_text(stock):
    if stock == -1:
        return "Stock illimité"
    if stock == 0:
        return "Rupture de stock"
    return f"{stock} en stock"


def slug(text, limit=40):
    s = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")
    return (s or "membre")[:limit]


def parse_duration(text):
    """'30m', '2h', '1d12h', '45' (minutes) -> secondes ou None."""
    text = str(text).strip().lower().replace(" ", "")
    if text.isdigit():
        return int(text) * 60
    total = 0
    for value, unit in re.findall(r"(\d+)([smhdj])", text):
        total += int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "j": 86400}[unit]
    if not total or re.sub(r"\d+[smhdj]", "", text):
        return None
    return total


def modal_values(interaction):
    """custom_id -> valeur (str) ou liste de valeurs (menus) d'un formulaire soumis."""
    out = {}

    def walk(node):
        if isinstance(node, dict):
            cid = node.get("custom_id")
            if cid is not None:
                if "values" in node:
                    out[cid] = node["values"]
                elif "value" in node:
                    out[cid] = node["value"]
            for key in ("components", "component"):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk((interaction.data or {}).get("components", []))
    return out


def is_staff(member, settings):
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    return bool(settings.get("staff")) and any(r.id == settings["staff"] for r in member.roles)


async def reply(i, text, view=None):
    """Réponse éphémère courte, que l'interaction ait déjà répondu ou non."""
    kwargs = {"ephemeral": True, "allowed_mentions": NO_PINGS}
    if view is not None:
        kwargs["view"] = view
    else:
        kwargs["content"] = text
    if i.response.is_done():
        await i.followup.send(**kwargs)
    else:
        await i.response.send_message(**kwargs)
