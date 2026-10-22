# NATIX Shop Discord Bot

This replaces the earlier Natix AI bot and legacy anti-bot folder with a Discord shop using Components V2.

## Features
Persistent panels with large NATIX banners, side buttons, selects, tickets, catalog with prices and stock, promo plans, giveaways, reviews, original emojis and editable terms.

## Commands
`/setup`, `/brand`, `/emojis`, `/product add`, `/product remove`, `/product list`, `/restock`, `/shop`, `/support`, `/trade`, `/promo`, `/rules`, `/terms`, `/supporter`, `/supporter_config`, `/reviews`, `/giveaway`, `/preview`, `/ticket_delete`, `/help`.

## Railway
`DISCORD_TOKEN` required; optional `DISCORD_GUILD_ID` for instant server-scoped commands, `NATIX_DB_PATH` defaults to `/data/natix.sqlite` when a `/data` volume is mounted. Railway start: `python main.py`.

Enable Server Members Intent and Presence Intent for the supporter check. The bot needs Manage Channels, Manage Roles, View Channels, Send Messages, Read Message History, Use Application Commands, and Manage Expressions for custom emojis. Configure `/setup` first. A persistent Railway volume is essential for durable SQLite data.

Discord Components V2 requires discord.py >=2.6; it cannot mix classic embed/content with LayoutView. Promo prices and schedules are examples only, and **no automatic payment, crypto withdrawal, voucher payout or mass ping is performed**.
