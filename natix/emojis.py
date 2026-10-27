"""Emojis personnalisés NATIX.

Les icônes (style des captures) sont envoyées une seule fois comme *emojis
d'application* : elles appartiennent au bot, n'occupent aucun slot d'emoji du
serveur et ne nécessitent aucune commande. Si l'envoi échoue, NATIX retombe
automatiquement sur des emojis Unicode.
"""
import logging
import os

import discord

from .config import EMOJI_DIR

LOG = logging.getLogger("natix.emojis")

FALLBACK = {
    "nx_nitro": "💎", "nx_decor": "✨", "nx_boost": "🚀", "nx_bots": "🤖", "nx_food": "🛍️",
    "nx_other": "📁", "nx_clock": "🕒", "nx_gift": "🎁", "nx_dollar": "💲", "nx_book": "📖",
    "nx_trade": "🔁", "nx_search": "🔍", "nx_ticket": "🎫", "nx_check": "✅", "nx_cross": "❌",
    "nx_star": "⭐", "nx_lock": "🔒", "nx_unlock": "🔓", "nx_userplus": "➕", "nx_shield": "🛡️",
    "nx_link": "🔗", "nx_megaphone": "📣", "nx_trash": "🗑️", "nx_archive": "🗄️", "nx_claim": "🙋",
    "nx_cart": "🛒", "nx_box": "📦", "nx_info": "ℹ️", "nx_home": "🏠", "nx_file": "📄",
    "nx_crown": "👑", "nx_heart": "🤍", "nx_message": "💬", "nx_tag": "🏷️", "nx_settings": "⚙️",
    "nx_list": "📋", "nx_reset": "🔄",
}


class EmojiBook:
    def __init__(self):
        self.custom = {}

    def text(self, name):
        """Emoji pour du texte Markdown."""
        if not name:
            return ""
        e = self.custom.get(name)
        if e:
            return str(e)
        return FALLBACK.get(name, name if not name.startswith("nx_") else "")

    def partial(self, name):
        """Emoji pour un bouton ou une option de menu."""
        if not name:
            return None
        e = self.custom.get(name)
        if e:
            return discord.PartialEmoji(name=e.name, id=e.id, animated=False)
        value = FALLBACK.get(name)
        if value:
            return discord.PartialEmoji(name=value)
        if not name.startswith("nx_"):
            return discord.PartialEmoji.from_str(name)
        return None

    async def sync(self, client):
        if os.getenv("NATIX_APP_EMOJIS", "1") == "0":
            return
        try:
            existing = {e.name: e for e in await client.fetch_application_emojis()}
        except discord.HTTPException:
            LOG.warning("Emojis d'application indisponibles, Unicode utilisé.")
            return
        created = 0
        for path in sorted(EMOJI_DIR.glob("nx_*.png")):
            name = path.stem
            if name in existing:
                self.custom[name] = existing[name]
                continue
            try:
                emoji = await client.create_application_emoji(name=name, image=path.read_bytes())
                self.custom[name] = emoji
                created += 1
            except discord.HTTPException as exc:
                LOG.warning("Emoji %s non créé : %s", name, exc)
        LOG.info("Emojis NATIX prêts (%s, %s nouveaux)", len(self.custom), created)


EMOJIS = EmojiBook()
