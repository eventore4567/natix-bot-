# NATIX — Premium Discord Marketplace

NATIX is a shop-only Discord bot. This repository has been rewritten into separate Python modules instead of the former Natix AI bot and old anti-bot code.

## Architecture
- main.py: Railway entrypoint.
- natix/bot.py: Discord client, persistent views, command sync, scheduled giveaways.
- natix/db.py: SQLite inventory, tickets, orders, reviews and per-server settings.
- natix/assets.py: original monochrome NATIX banners and custom icons generated with Pillow.
- natix/panels.py: separate native Discord Components V2 panels with accessory buttons on the right.
- natix/services.py: ticket handling, orders, giveaways, transcripts and modals.
- natix/commands.py: shop and administrative slash commands.
- .github/workflows/smoke.yml: automated checks.

## Separate premium panels
/shop, /support, /trade, /promo, /rules, /supporter, /reviews, /vouch, /faq, /partners, /statistics.

Use /panel to choose where to publish a panel, or /preview to test one privately.

## Product and order administration
/product add, /product edit, /product remove, /product restock, /product list.
/order mine, /order details, /order list, /order status.
/ticket close, /ticket reopen, /ticket transcript, /ticket delete.

## Customization
/setup, /brand, /banner, /emojis, /textconfig, /settings, /supporter_config, /announcement.

## Promotions and giveaways
/promo publishes example plans requiring staff approval. No automated mass mentions.
/giveaway starts a giveaway; /giveaway_end closes it; /giveaway_reroll picks another entrant.
/vouches queue and /vouches approve moderate actual written customer testimonials.

## Railway deployment
Start command is python main.py (see railway.json).
Environment variables:
- DISCORD_TOKEN: required bot token.
- DISCORD_GUILD_ID: optional single-guild slash sync for fast testing.
- NATIX_DB_PATH: defaults to /data/natix.sqlite when the /data directory is present.
- NATIX_MEMBERS_INTENT=1: optional, enable Server Members Intent in Discord Portal too.
- NATIX_PRESENCES_INTENT=1: optional, enable Presence Intent in Discord Portal too.

Attach a persistent Railway volume at /data to preserve database across builds/redeploys.
Give the bot permission to manage ticket channels, send messages, read history, assign supporter roles, and manage expressions for custom emoji creation. Configure /setup before opening tickets.

## Important limitations
- Prices in promotion panels are example placeholders, not real payment products. Payments and product delivery require staff validation in tickets.
- No automatic payments, crypto transfers, voucher payments or mass pings.
- The custom supporter status check is available only with authorized Presence Intent; time-based supporter credit/rewards are not implemented.
- Transcripts export all messages still available in the Discord channel history, with attachment URLs; already deleted messages cannot be reconstructed.
- Original emoji pack is generated with /emojis; failures are reported if permissions or server emoji slots are insufficient.
- Passing automated tests does not replace acceptance testing against a live Discord server.
