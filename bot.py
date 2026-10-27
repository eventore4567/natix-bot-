from discord.ext import commands
import discord, os, json, hashlib
from discord_webhook import DiscordWebhook, DiscordEmbed
import requests
from boosting import *
if os.name == 'nt':
    import ctypes
            
    
config = json.load(open("config.json", encoding="utf-8"))

def clear(): #clears the terminal
    os.system('cls' if os.name =='nt' else 'clear')
      

if os.name == "nt":
    ctypes.windll.kernel32.SetConsoleTitleW(f"Boost Bot")
else:
    pass



activity = discord.Activity(type=discord.ActivityType.watching, name=config["bot_status"])
bot = commands.Bot(command_prefix = ">", intents = discord.Intents.all(), activity = activity)
  

            
os.system(f"title Boost Crew Bot")
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('______')
    



class Utils():
    @staticmethod
    async def isWhitelisted(ctx) -> bool:
        if (
            str(ctx.author.id) in open("input/whitelist.txt", "r").read().splitlines()
            or str(ctx.author.id) == config["owner"]
        ):
            return True
        else:
            return False

@bot.slash_command(
    guild_ids=[config["guildID"]], name="restock", description="Restocks your tokens!"
)
async def restock(
    ctx,
    attachment: discord.Option(
        discord.Attachment, "Drag your file with tokens here.", required=True
    ),
    months: discord.Option(int, "Uses 1m or 3m stock to boost servers", required=True)
):
    if not await Utils.isWhitelisted(ctx):
        return await ctx.respond(
            embed=discord.Embed(
                title="Not Whitelisted",
                description="_You are not allowed to use the bot, please contact the respective owner._",
                color=0x5B13E3
            )
        )

    if months == 1:
        filename = "input/1m_tokens.txt"
    if months == 3:
        filename = "input/3m_tokens.txt"

    tokens = await attachment.read()
    tokens = tokens.decode()
    with open(filename, "a") as tokens_input:
        for token in tokens.splitlines():
            tokens_input.write(token + "\n")

    embed = discord.Embed(
        title="Successfully Restocked",
        description=f"*Restocked {len(tokens.splitlines())} tokens*",
        color=0x5B13E3
    )

    await ctx.respond(embed=embed)
                        
                       

  
@bot.slash_command(
    name="stock",
    description="Allows you to see the stock in the bot.")
async def stock(
    ctx: discord.ApplicationContext, type: discord.Option(str, name="type", choices=["All", "1 Month", "3 Month"])):
    
    

    if type == "1 Month":
        stock       = len(open("./input/1m_tokens.txt", encoding="utf-8").read().splitlines())
        boosts      = stock * 2
        title       = "1 Month Stock"
    elif type == "3 Month":
        stock       = len(open("./input/3m_tokens.txt", encoding="utf-8").read().splitlines())
        boosts      = stock * 2
        title       = "3 Month Stock"
    else:
        stock1month     = len(open("./input/1m_tokens.txt", encoding="utf-8").read().splitlines())
        stock3month     = len(open("./input/3m_tokens.txt", encoding="utf-8").read().splitlines())
        boost1month   = stock1month * 2
        boost3month     = stock3month * 2
        emb = discord.Embed(color=0x9900ff)
        emb.description = (
            f"**1 Month Stock**\nBoosts: `{boost3month}`\nTokens: `{stock1month}`\n\n**3 Month Stock**\nBoosts: `{boost3month}`\nTokens: `{stock3month}`"
        )
        return await ctx.respond(embed=emb)


    emb = discord.Embed(color=0x9900ff)
    emb.description = (
        f"**{title}**\nThere is currently `{boosts}` boosts and `{stock}` tokens in stock!"
    )
    return await ctx.respond(embed=emb)

  

###################################################################

@bot.slash_command(
    guild_ids=[config["guildID"]], name="boost", description="Boost a server"
)
async def boost(
    ctx,
    invite: discord.Option(
        str,
        "invite link (can be full link)",
        required=True,
    ),
    amount: discord.Option(
        int, "amount of boosts", required=True
    ),
    months: discord.Option(int, "What stock", required=True
    ),
    nick: discord.Option(str,"Nickname Of The Tokens", required=False)
):
    if not await Utils.isWhitelisted(ctx):
        return await ctx.respond(
            embed=discord.Embed(
                title="Not Whitelisted",
                description="_You are not allowed to use the bot, please contact the respective owner._",
                color=0x5B13E3
            )
        )

    if ".gg/" in invite:
        invite = str(invite).split(".gg/")[1]
    elif "invite/" in invite:
        invite = str(invite).split("invite/")[1]

    if (
        '{"message": "Unknown Invite", "code": 10006}'
        in httpx.get(f"https://discord.com/api/v9/invites/{invite}").text
    ):
        return await ctx.respond(
            embed=discord.Embed(
                title="Error!",
                description=f"discord.gg/{invite} is invalid. Please set a valid invite.",
                color=0x5B13E3
            )
        )

    if amount % 2 != 0:
        return await ctx.respond(
            embed=discord.Embed(
                title="Error!",
                description="`amount` must be even.",
                color=0x5B13E3
            )
        )

    await ctx.respond(
        embed=discord.Embed(
            title="Started!",
            description=f"Started Boosting https://discord.gg/{invite} {amount}x",
            color=0x5B13E3
        )
    )  

    go = time.time()
    tboost(invite, amount, months, nick)
    end = time.time()
    time_went = round(end - go, 2)

    await ctx.edit(
        embed=discord.Embed(
            title="Boost Completd!",
            description=f"We have boosted the server below `{amount}x` in `{time_went}s` Here is the amount of Finished and the amount of failed boosts\n\n**Finished Boosts: **`{len(variables.success_tokens)*2}`\n**Failed Boosts: **`{len(variables.failed_tokens)*2}`",
            color=0x5B13E3
        )
    )
        
    if tboost == False:
        with open('success.txt', 'w') as f:
            for line in variables.success_tokens:
                f.write(f"{line}\n")
            
        with open('failed.txt', 'w') as g:
            for line in variables.failed_tokens:
                g.write(f"{line}\n")
        
        embed2 = DiscordEmbed(title = "Boost Log", description = f"*Failed to boost https://discord.gg/{invite} {amount}x for {months} month(s)*", color = 'FF0004')
        embed2.set_timestamp()
        webhook = DiscordWebhook(url=config["boost_failed_log_webhook"])
        webhook.add_embed(embed2)
        webhook.execute()
        print()
        print()

        webhook = DiscordWebhook(url=config["boost_failed_log_webhook"])
        with open("success.txt", "rb") as f:
            webhook.add_file(file=f.read(), filename='success.txt')
        with open("failed.txt", "rb") as f:
            webhook.add_file(file=f.read(), filename='failed.txt')
        webhook.execute()
            
        os.remove("success.txt")
        os.remove("failed.txt")
                
    elif tboost:
        with open('success.txt', 'w') as f:
            for line in variables.success_tokens:
                f.write(f"{line}\n")
            
        with open('failed.txt', 'w') as g:
            for line in variables.failed_tokens:
                g.write(f"{line}\n")
                    
        embed3 = DiscordEmbed(title = f"Boost Log", description=f"*Boosted https://discord.gg/{invite} {amount}x in {time_went}s for {months} month(s)*\n**Finished Boosts: **`{len(variables.success_tokens)*2}`\n**Failed Boosts: **`{len(variables.failed_tokens)*2}`", color = 'ED00FF')
        embed3.set_timestamp()
        webhook = DiscordWebhook(url=config["boost_log_webhook"])
        webhook.add_embed(embed3)
        webhook.execute()
        print()
        print()

        webhook = DiscordWebhook(url=config["boost_log_webhook"])
        with open("success.txt", "rb") as f:
            webhook.add_file(file=f.read(), filename='success.txt')
        with open("failed.txt", "rb") as f:
            webhook.add_file(file=f.read(), filename='failed.txt')
        webhook.execute()
            
        os.remove("success.txt")
        os.remove("failed.txt")

 

    
    
@bot.slash_command(guild_ids=[config["guildID"]],name="send", description="Give nitro tokens to a user")
async def send(ctx, amount: int, user: discord.User, file_type: str = "1m"):
    if not await Utils.isWhitelisted(ctx):
        return await ctx.respond(
            embed=discord.Embed(
                title="Not Whitelisted",
                description="_You are not allowed to use the bot, please contact the respective owner._",
                color=discord.Colour.red(),
                timestamp=datetime.datetime.now(),
            )
        )

    tokens_file = f"input/3m_tokens.txt"
    if not os.path.exists(tokens_file):
        return await ctx.respond(f"Unable to find {tokens_file}")

    with open(tokens_file, 'r') as f:
        tokens = f.read().splitlines()

    if len(tokens) < amount:
        return await ctx.respond("Not enough tokens in stock.")

    tokens_to_give = tokens[:amount]
    tokens = tokens[amount:]

    with open(tokens_file, 'w') as f:
        f.write("\n".join(tokens))

    temp_file = "temp.txt"
    with open(temp_file, 'w') as f:
        f.write("\n".join(tokens_to_give))

    try:
        await ctx.respond(f"Sucessfully sent {user} {amount} nitro tokens.")
        await user.send(f"Thank you for buying {amount} nitro token(s)", file=discord.File(temp_file))
    except discord.errors.Forbidden:
        await ctx.respond("Unable to send tokens to user, please make sure I have permission.")
    os.remove(temp_file)    

                
    

import aiohttp
import datetime
import discord
from discord.ext import commands
from typing import Optional, List
import logging
import asyncio

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logger.addHandler(handler)




clear()
bot.run(config['bot_token'])