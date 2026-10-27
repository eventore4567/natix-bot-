"""Client Discord NATIX : synchronisation propre des commandes, routeur, giveaways."""
import logging
import os

import discord
from discord import app_commands
from discord.ext import tasks

from .commands import register
from .db import Store
from .emojis import EMOJIS
from .handlers import finish_giveaway, route
from .util import NO_PINGS

LOG = logging.getLogger("natix.bot")


class Natix(discord.Client):
    def __init__(self, store=None):
        intents = discord.Intents.default()
        intents.members = os.getenv("NATIX_MEMBERS_INTENT", "0") == "1"
        super().__init__(intents=intents, allowed_mentions=NO_PINGS)
        self.store = store or Store()
        self.tree = app_commands.CommandTree(self)
        register(self.tree)
        self._cleaned = False

    async def setup_hook(self):
        await EMOJIS.sync(self)
        test_guild = os.getenv("DISCORD_GUILD_ID", "").strip()
        if test_guild.isdigit():
            # Mode test : commandes instantanées sur un serveur, et plus aucune commande globale
            # (sinon chaque commande apparaîtrait en double).
            obj = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=obj)
            synced = await self.tree.sync(guild=obj)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            LOG.info("%s commandes NATIX synchronisées sur le serveur %s (globales vidées)", len(synced), test_guild)
        else:
            synced = await self.tree.sync()
            LOG.info("%s commandes NATIX globales : %s", len(synced), ", ".join(sorted(c.name for c in synced)))
        if not self.giveaway_loop.is_running():
            self.giveaway_loop.start()

    async def on_ready(self):
        LOG.info("NATIX connecté en tant que %s (%s serveurs)", self.user, len(self.guilds))
        if self._cleaned:
            return
        self._cleaned = True
        # Supprime les anciennes commandes propres à chaque serveur (versions précédentes).
        test_guild = os.getenv("DISCORD_GUILD_ID", "").strip()
        for guild in self.guilds:
            self.store.ensure_defaults(guild.id)
            if str(guild.id) == test_guild:
                continue
            try:
                old = await self.tree.fetch_commands(guild=guild)
                if old:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    LOG.info("%s anciennes commandes supprimées sur %s", len(old), guild.id)
            except discord.HTTPException as exc:
                LOG.warning("Nettoyage des commandes impossible sur %s : %s", guild.id, exc)

    async def on_guild_join(self, guild):
        self.store.ensure_defaults(guild.id)

    async def on_interaction(self, interaction: discord.Interaction):
        await route(interaction)

    async def on_guild_channel_delete(self, channel):
        t = self.store.ticket(channel.id)
        if t and t["state"] != "deleted":
            self.store.set_ticket(channel.id, state="deleted")
            if t["kind"] == "trade":
                self.store.set_trade_state_by_channel(channel.id, "deleted")

    @tasks.loop(seconds=30)
    async def giveaway_loop(self):
        for g in self.store.due_giveaways():
            try:
                LOG.info("Giveaway %s : %s", g["message"], await finish_giveaway(self, g["message"]))
            except Exception:
                LOG.exception("Clôture du giveaway %s impossible", g["message"])

    @giveaway_loop.before_loop
    async def _wait(self):
        await self.wait_until_ready()


def launch():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant : configure la variable sur Railway.")
    Natix().run(token, log_handler=None)
