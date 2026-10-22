"""Discord client, persistent view registration and scheduled giveaway settlements."""
import logging
import os
import secrets
import time

import discord
from discord import app_commands
from discord.ext import tasks

from .assets import PANELS, safe
from .commands import register
from .db import Store
from .panels import Panel, TicketControls, GiveawayPanel

LOG=logging.getLogger("natix.bot")

class Natix(discord.Client):
    def __init__(self,store=None):
        intents=discord.Intents.default()
        # Enable only after they are allowed in Discord Developer Portal.
        intents.members=os.getenv("NATIX_MEMBERS_INTENT","0")=="1"
        intents.presences=os.getenv("NATIX_PRESENCES_INTENT","0")=="1"
        super().__init__(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        self.store=store or Store()
        self.tree=app_commands.CommandTree(self)
        register(self.tree)

    async def setup_hook(self):
        # Register dispatch mappings for persistent components BEFORE Discord events.
        for key in PANELS:
            self.add_view(Panel(key,self.store))
        self.add_view(TicketControls())
        self.add_view(GiveawayPanel())
        test_guild=os.getenv("DISCORD_GUILD_ID","").strip()
        if test_guild:
            obj=discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=obj)
            synced=await self.tree.sync(guild=obj)
            LOG.info("Synced %s NATIX commands to guild %s",len(synced),test_guild)
        else:
            synced=await self.tree.sync()
            LOG.info("Synced %s NATIX global commands",len(synced))
        if not self.settle_giveaways.is_running():
            self.settle_giveaways.start()

    async def on_ready(self):
        LOG.info("NATIX logged in as %s (guilds: %s)",self.user,len(self.guilds))

    @tasks.loop(seconds=45)
    async def settle_giveaways(self):
        rows=self.store.many("SELECT message FROM giveaways WHERE closed=0 AND ends<=?",
                             (int(time.time()),))
        for row in rows:
            try:
                await finish_giveaway(self,row["message"])
            except Exception:
                LOG.exception("Giveaway settlement failed %s",row["message"])

    @settle_giveaways.before_loop
    async def before_settle(self):
        await self.wait_until_ready()

async def finish_giveaway(bot,message_id):
    db=bot.store
    game=db.giveaway(message_id)
    if not game:return "Concours introuvable."
    if game["closed"]:return "Ce concours est déjà terminé."
    # Mark first to avoid awarding two winners on concurrent settlement.
    cursor=db.execute("UPDATE giveaways SET closed=1 WHERE message=? AND closed=0",(message_id,))
    if not cursor.rowcount:return "Déjà clôturé."
    entries=db.giveaway_entries(message_id)
    winner=secrets.SystemRandom().choice(entries) if entries else None
    channel=bot.get_channel(game["channel"])
    if channel is None:
        try:channel=await bot.fetch_channel(game["channel"])
        except discord.HTTPException:
            LOG.warning("Giveaway channel unavailable: %s",game["channel"])
            return "Concours clôturé, salon introuvable."
    try:
        message=await channel.fetch_message(message_id)
        await message.edit(view=GiveawayPanel(game["prize"],True,len(entries)))
        await channel.send("🏆 **NATIX · Résultat du giveaway**\n"
            +safe(game["prize"],100)+"\n"
            +("<@"+str(winner)+">" if winner else "Aucun participant."),
            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        LOG.exception("Could not publish giveaway winner")
        return "Concours clôturé, résultat non publié (erreur Discord)."
    return "Concours terminé, gagnant tiré."

def launch():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    token=os.getenv("DISCORD_TOKEN","").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant : configure la variable sur Railway.")
    bot=Natix()
    bot.run(token,log_handler=None)
