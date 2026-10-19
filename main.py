import os
import asyncio
import logging
from collections import defaultdict, deque

import discord
from discord import app_commands
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["DISCORD_TOKEN"].strip()
ai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=20.0, max_retries=1)
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
history = defaultdict(lambda: deque(maxlen=12))
locks = defaultdict(asyncio.Lock)
SYSTEM = "Tu es Natix AI, assistant Discord intelligent, rapide et naturel. Réponds dans la langue de l'utilisateur, clairement et sans longueurs. Ne divulgue jamais de secrets."

async def respond(user_id: int, channel_id: int, question: str) -> str:
    key = (channel_id, user_id)
    async with locks[key]:
        messages = [{"role": "system", "content": SYSTEM}, *history[key],
                    {"role": "user", "content": question[:3000]}]
        result = await ai.chat.completions.create(model=MODEL, messages=messages, max_tokens=450)
        reply = (result.choices[0].message.content or "Je n'ai pas de réponse.")[:1900]
        history[key].append({"role": "user", "content": question[:3000]})
        history[key].append({"role": "assistant", "content": reply})
        return reply

@tree.command(name="ask", description="Pose une question à Natix AI")
@app_commands.describe(question="Ta question")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer(thinking=True)
    try:
        reply = await respond(interaction.user.id, interaction.channel_id or 0, question)
        await interaction.followup.send(reply, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        logging.exception("AI request failed")
        await interaction.followup.send("L'IA est temporairement indisponible.")

@tree.command(name="resetai", description="Efface ta conversation avec Natix AI")
async def resetai(interaction: discord.Interaction):
    history.pop((interaction.channel_id or 0, interaction.user.id), None)
    await interaction.response.send_message("Historique effacé.", ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or bot.user is None:
        return

    content = message.content.strip()
    mentioned = bot.user in message.mentions
    starts_with_natix = content.lower().startswith("natix") and (
        len(content) == 5 or not content[5].isalnum()
    )
    if not mentioned and not starts_with_natix:
        return

    if mentioned:
        question = content.replace(f"<@{bot.user.id}>", "").replace(
            f"<@!{bot.user.id}>", ""
        ).strip()
    else:
        question = content[5:].lstrip(" ,:!?-").strip()

    if not question:
        return

    try:
        async with message.channel.typing():
            reply = await respond(message.author.id, message.channel.id, question)
        await message.reply(
            reply, mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except Exception:
        logging.exception("AI message response failed")
        try:
            await message.reply("L'IA est temporairement indisponible.", mention_author=False)
        except discord.HTTPException:
            pass

@bot.event
async def on_ready():
    if not getattr(bot, "_synced", False):
        await tree.sync()
        bot._synced = True
    logging.info("Natix AI connected as %s", bot.user)

bot.run(TOKEN)
