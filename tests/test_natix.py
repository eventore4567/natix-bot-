"""Tests NATIX sans connexion Discord : base de données, panneaux, routeur et parcours complets.

Lancer : python -m unittest discover -s tests -v
"""
import asyncio
import itertools
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import discord  # noqa: E402

from natix import handlers as H  # noqa: E402
from natix import ui as V  # noqa: E402
from natix.bot import Natix  # noqa: E402
from natix.db import Store, parse_price  # noqa: E402
from natix.util import modal_values, money, parse_duration  # noqa: E402

GUILD = 100
REAL_TEXT_CHANNEL = discord.TextChannel
IDS = itertools.count(10_000)


# ---------------------------------------------------------------- validation des payloads
def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def check_view(tc, view):
    payload = view.to_components()
    json.dumps(payload)
    comps = [n for n in walk(payload) if "type" in n and isinstance(n["type"], int) and n["type"] in range(1, 20)]
    tc.assertLessEqual(len(comps), 40, "trop de composants")
    text = sum(len(n.get("content", "")) for n in comps if n["type"] == 10)
    tc.assertLessEqual(text, 4000, "texte trop long")
    for n in comps:
        if "custom_id" in n:
            tc.assertLessEqual(len(n["custom_id"]), 100)
            tc.assertTrue(n["custom_id"].startswith("nx:"), n["custom_id"])
            if n["type"] in (2, 3, 5, 6, 7, 8):
                tc.assertIsNotNone(H.find_route(n["custom_id"]), "aucune route pour " + n["custom_id"])
        if n["type"] == 3:
            tc.assertLessEqual(len(n["options"]), 25)
            for o in n["options"]:
                tc.assertLessEqual(len(o["label"]), 100)
                tc.assertLessEqual(len(o.get("description") or ""), 100)
        if n["type"] == 1:
            tc.assertLessEqual(len(n["components"]), 5)
        if n["type"] == 17:
            tc.assertLessEqual(len(n["components"]), 40)
    return payload


# ---------------------------------------------------------------- faux objets Discord
class FakeResponse:
    def __init__(self):
        self.calls = []
        self._done = False

    def is_done(self):
        return self._done

    async def _record(self, name, *a, **kw):
        self.calls.append((name, a, kw))
        self._done = True

    async def send_message(self, *a, **kw):
        await self._record("send_message", *a, **kw)

    async def send_modal(self, modal):
        await self._record("send_modal", modal)

    async def edit_message(self, *a, **kw):
        await self._record("edit_message", *a, **kw)

    async def defer(self, *a, **kw):
        await self._record("defer", *a, **kw)


def fake_member(uid, admin=False, roles=()):
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.bot = False
    m.name = f"user{uid}"
    m.mention = f"<@{uid}>"
    m.roles = [SimpleNamespace(id=r) for r in roles]
    m.guild_permissions = SimpleNamespace(manage_guild=admin, administrator=admin)
    m.__str__ = lambda self: f"user{uid}"
    return m


class FakeChannel:
    def __init__(self, cid, name="salon", private=True):
        self.id = cid
        self.name = name
        self.mention = f"<#{cid}>"
        self.sent = []
        self.overwrites = {}
        self.deleted = False
        self.private = private
        self.edits = []

    async def send(self, content=None, **kw):
        msg = SimpleNamespace(id=next(IDS), content=content, kw=kw)
        self.sent.append(msg)
        return msg

    def get_partial_message(self, mid):
        ch = self

        class PM:
            async def edit(self, **kw):
                ch.edits.append((mid, kw))
        return PM()

    async def set_permissions(self, target, overwrite=None, reason=None):
        self.overwrites[target] = overwrite

    async def delete(self, reason=None):
        self.deleted = True

    def permissions_for(self, who):
        return SimpleNamespace(view_channel=not self.private, send_messages=True, attach_files=True,
                               manage_channels=True, manage_roles=True)

    def history(self, limit=None, oldest_first=True):
        async def gen():
            for m in self.sent:
                yield SimpleNamespace(content=m.content or "", components=[], attachments=[],
                                      created_at=discord.utils.utcnow(),
                                      author=SimpleNamespace(id=1, __str__=lambda s: "NATIX"))
        return gen()


class FakeGuild:
    def __init__(self):
        self.id = GUILD
        self.default_role = discord.Object(id=GUILD)
        self.me = fake_member(1, admin=True)
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.id = 500
        cat.permissions_for = lambda who: SimpleNamespace(manage_channels=True, manage_roles=True, view_channel=True)
        self.category = cat
        self.logs = FakeChannel(600, "logs")
        self.reviews = FakeChannel(700, "avis", private=False)
        self.staff_role = discord.Object(id=800)
        self.channels = {500: cat, 600: self.logs, 700: self.reviews}
        self.members = {}

    def get_channel(self, cid):
        return self.channels.get(cid)

    def get_role(self, rid):
        return self.staff_role if rid == 800 else None

    def get_member(self, uid):
        return self.members.get(uid)

    async def create_text_channel(self, name, category=None, overwrites=None, topic=None, reason=None):
        ch = FakeChannel(next(IDS), name)
        ch.overwrites = dict(overwrites or {})
        self.channels[ch.id] = ch
        return ch


class FakeClient:
    def __init__(self, store):
        self.store = store
        self.user = SimpleNamespace(id=1)
        self.channels = {}

    def get_channel(self, cid):
        return self.channels.get(cid)


def interaction(client, guild, user, custom_id, *, values=None, components=None, channel=None, message=None,
                modal=False):
    data = {"custom_id": custom_id}
    if values is not None:
        data["values"] = values
    if components is not None:
        data["components"] = components
    i = SimpleNamespace(
        type=discord.InteractionType.modal_submit if modal else discord.InteractionType.component,
        data=data, client=client, guild=guild, guild_id=guild.id, user=user, channel=channel,
        channel_id=channel.id if channel else 0, message=message, response=FakeResponse())
    i.followup = SimpleNamespace(send=AsyncMock())
    return i


def text_fields(**fields):
    return [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]} for k, v in fields.items()]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------- tests
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.db = Store(":memory:")

    def test_prices_and_formatting(self):
        self.assertEqual(parse_price("10"), 1000)
        self.assertEqual(parse_price("6,5 €"), 650)
        self.assertEqual(parse_price("10 EUR"), 1000)
        self.assertIsNone(parse_price("gratuit"))
        self.assertEqual(money(650), "6.5€")
        self.assertEqual(money(1000), "10€")
        self.assertEqual(money(1099), "10.99€")
        self.assertEqual(parse_duration("1d12h"), 129600)
        self.assertEqual(parse_duration("30"), 1800)
        self.assertIsNone(parse_duration("demain"))

    def test_stock_reserved_once_and_restored_once(self):
        pid = self.db.add_product(GUILD, "nitro", "Nitro", "", 1000, 3)
        oid, err = self.db.create_order(GUILD, 5, pid, 2)
        self.assertIsNone(err)
        self.assertEqual(self.db.product(GUILD, pid)["stock"], 1)
        _, err = self.db.create_order(GUILD, 6, pid, 2)
        self.assertIn("Stock insuffisant", err)
        self.assertTrue(self.db.transition_order(GUILD, oid, "accepted", 9)[0])
        self.assertTrue(self.db.transition_order(GUILD, oid, "delivered", 9)[0])
        self.assertFalse(self.db.transition_order(GUILD, oid, "delivered", 9)[0])
        self.assertFalse(self.db.transition_order(GUILD, oid, "cancelled", 9)[0])
        self.assertEqual(self.db.product(GUILD, pid)["stock"], 1)
        oid2, _ = self.db.create_order(GUILD, 6, pid, 1)
        self.assertEqual(self.db.product(GUILD, pid)["stock"], 0)
        self.assertTrue(self.db.transition_order(GUILD, oid2, "cancelled", 9)[0])
        self.assertFalse(self.db.transition_order(GUILD, oid2, "cancelled", 9)[0])
        self.assertEqual(self.db.product(GUILD, pid)["stock"], 1)
        self.assertEqual(self.db.order(GUILD, oid)["total_cents"], 2000)

    def test_unlimited_stock(self):
        pid = self.db.add_product(GUILD, "bots", "Bot", "", 500, -1)
        oid, _ = self.db.create_order(GUILD, 5, pid, 50)
        self.assertEqual(self.db.product(GUILD, pid)["stock"], -1)
        self.db.transition_order(GUILD, oid, "cancelled", 1)
        self.assertEqual(self.db.product(GUILD, pid)["stock"], -1)

    def test_tickets_claim_and_states(self):
        self.db.create_ticket(1, GUILD, 5, "support", 1)
        self.assertTrue(self.db.claim_ticket(1, 22))
        self.assertFalse(self.db.claim_ticket(1, 33))
        self.assertTrue(self.db.transition_ticket(1, "open", "closed"))
        self.assertFalse(self.db.transition_ticket(1, "open", "closed"))
        self.assertIsNone(self.db.open_ticket(GUILD, 5, "support"))
        self.assertEqual(self.db.next_ticket_number(GUILD), 1)
        self.assertEqual(self.db.next_ticket_number(GUILD), 2)

    def test_votes_reviews_giveaways(self):
        self.assertTrue(self.db.vote(GUILD, 1, True))
        self.assertFalse(self.db.vote(GUILD, 1, False))
        self.assertIsNone(self.db.vote(GUILD, 1, False))
        self.db.vote(GUILD, 2, True)
        self.assertEqual(self.db.votes(GUILD), (1, 0))
        self.db.add_review(GUILD, 1, 5, "Top")
        self.db.add_review(GUILD, 2, 4, "Bien")
        avg, total, dist, _ = self.db.review_stats(GUILD)
        self.assertEqual((avg, total, dist[5]), (4.5, 2, 1))
        self.db.create_giveaway(77, GUILD, 1, "5€", 0, 1, 9)
        self.assertTrue(self.db.toggle_entry(77, 3))
        self.assertFalse(self.db.toggle_entry(77, 3))
        self.assertTrue(self.db.close_giveaway(77, []))
        self.assertFalse(self.db.close_giveaway(77, []))

    def test_legacy_migration(self):
        path = os.path.join(os.path.dirname(__file__), "legacy.sqlite")
        if os.path.exists(path):
            os.remove(path)
        import sqlite3
        con = sqlite3.connect(path)
        con.execute("""CREATE TABLE products(id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, category TEXT,
            name TEXT, details TEXT, price TEXT, stock INTEGER DEFAULT -1, active INTEGER DEFAULT 1)""")
        con.execute("INSERT INTO products(guild,category,name,details,price,stock) VALUES (1,'nitro','N','','6,50 EUR',2)")
        con.execute("CREATE TABLE tickets(channel INTEGER PRIMARY KEY, guild INTEGER, owner INTEGER, kind TEXT, state TEXT)")
        con.commit()
        con.close()
        try:
            db = Store(path)
            self.assertEqual(db.product(1, 1)["price_cents"], 650)
            self.assertIn("claimed_by", db._columns("tickets"))
        finally:
            os.remove(path)
            for ext in ("-wal", "-shm"):
                if os.path.exists(path + ext):
                    os.remove(path + ext)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.db = Store(":memory:")
        for n in range(30):
            self.db.add_product(GUILD, "nitro", f"Produit {n} " + "x" * 70, "d" * 300, 1000 + n, n % 3)

    def test_all_panels_valid(self):
        for kind, builder in V.PANEL_BUILDERS.items():
            view, files = builder(self.db, GUILD)
            payload = check_view(self, view)
            refs = {n["media"]["url"] for n in walk(payload) if isinstance(n.get("media"), dict)}
            refs |= {i["media"]["url"] for n in walk(payload) for i in n.get("items", []) if isinstance(i, dict)}
            names = {"attachment://" + f.filename for f in files}
            self.assertTrue(refs <= names, (kind, refs, names))

    def test_shop_views(self):
        check_view(self, V.category_view(self.db, GUILD, "nitro"))
        check_view(self, V.category_view(self.db, GUILD, "boost"))
        check_view(self, V.product_view(self.db, GUILD, self.db.product(GUILD, 2)))
        out = V.product_view(self.db, GUILD, self.db.product(GUILD, 1))  # stock 0
        btn = [n for n in walk(out.to_components()) if n.get("custom_id") == "nx:buy:1"][0]
        self.assertTrue(btn["disabled"])

    def test_admin_and_misc_views(self):
        guild = FakeGuild()
        check_view(self, V.setup_view(self.db, guild))
        check_view(self, V.categories_admin(self.db, GUILD))
        check_view(self, V.plans_admin(self.db, GUILD))
        check_view(self, V.trades_view(self.db, GUILD, 5))
        check_view(self, V.review_stats_view(self.db, GUILD))
        g = {"prize": "5€", "winners": 1, "ends": 1, "winner_ids": "5"}
        check_view(self, V.giveaway_view(g, 51))
        check_view(self, V.giveaway_view(g, 51, ended=True))
        self.db.create_ticket(9, GUILD, 5, "support", 4, subject="> test")
        check_view(self, H.render_ticket(self.db, self.db.ticket(9)))

    def test_pplme_is_plain_text_not_a_payment_panel(self):
        from natix.config import PANEL_KINDS
        from natix.commands import paypal_contact_message
        self.assertNotIn("paypal", PANEL_KINDS)
        self.assertNotIn("paypal", V.PANEL_BUILDERS)
        self.assertIsNone(paypal_contact_message({}))
        self.assertIsNone(paypal_contact_message({"paypal": "natixshop"}))
        self.assertIsNone(paypal_contact_message(
            {"paypal": "https://evil.example/username", "paypal_email":"example@gmail.com"}))
        configured={"paypal":"@natixshop","paypal_email":"natixshop9@gmail.com"}
        msg=paypal_contact_message(configured)
        self.assertIn("@natixshop",msg)
        self.assertIn("natixshop9@gmail.com",msg)
        self.assertNotIn("Payer avec PayPal",msg)
        self.assertNotIn("J'ai payé",msg)
        same=paypal_contact_message({
            "paypal":"https://paypal.me/natixshop", "paypal_email":"natixshop9@gmail.com"})
        self.assertEqual(same,msg)
        self.db.configure(GUILD,**configured)
        bot=Natix(store=self.db)
        command=bot.tree.get_command("pplme")
        guild=FakeGuild()
        channel=FakeChannel(5000, "paiements")
        i=SimpleNamespace(client=bot,guild=guild,guild_id=GUILD,
                          channel=channel,response=FakeResponse())
        i.followup=SimpleNamespace(send=AsyncMock())
        run(command.callback(i))
        self.assertEqual(i.response.calls[0][0],"send_message")
        sent_args=i.response.calls[0][1]
        sent_kw=i.response.calls[0][2]
        self.assertEqual(sent_args[0],msg)
        self.assertFalse(sent_kw["allowed_mentions"].everyone)
        self.assertNotIn("embed",sent_kw)
        self.assertNotIn("view",sent_kw)
        self.assertNotIn("file",sent_kw)
        # No accidental panel or message sent in the channel separately.
        self.assertFalse(channel.sent)
        self.assertEqual(V.paypal_link(self.db.settings(GUILD),1998),
                         "https://paypal.me/natixshop/19.98EUR")

    def test_command_tree(self):
        bot = Natix(store=self.db)
        names = {c.name for c in bot.tree.get_commands()}
        self.assertEqual(names, {"setup", "panel", "product", "giveaway", "orders", "pplme"})
        self.assertNotIn("emojis", names)

    def test_modal_values_walker(self):
        i = SimpleNamespace(data={"components": [
            {"type": 1, "components": [{"type": 4, "custom_id": "a", "value": "1"}]},
            {"type": 18, "component": {"type": 6, "custom_id": "r", "values": ["5"]}},
            {"type": 18, "component": {"type": 4, "custom_id": "b", "value": "x"}}]})
        self.assertEqual(modal_values(i), {"a": "1", "r": ["5"], "b": "x"})


class FlowTests(unittest.TestCase):
    """Parcours complets via le routeur, avec un faux serveur Discord."""

    def setUp(self):
        # Les faux salons passent les vérifications isinstance(…, discord.TextChannel).
        patcher = patch.object(discord, "TextChannel", FakeChannel)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = Store(":memory:")
        self.guild = FakeGuild()
        self.client = FakeClient(self.db)
        self.admin = fake_member(2, admin=True)
        self.buyer = fake_member(5)
        self.staff = fake_member(3, roles=(800,))
        self.guild.members = {2: self.admin, 5: self.buyer, 3: self.staff}
        self.db.configure(GUILD, staff=800, category=500, logs=600, reviews_channel=700)
        self.pid = self.db.add_product(GUILD, "nitro", "Nitro Boost 1M", "1 mois", 999, 2)

    def route(self, *a, **kw):
        i = interaction(self.client, self.guild, *a, **kw)
        run(H.route(i))
        return i

    def last_error(self, i):
        texts = [kw.get("content") for name, a, kw in i.response.calls if name == "send_message"]
        texts += [c.kwargs.get("content") for c in i.followup.send.call_args_list]
        return [t for t in texts if t]

    def test_full_order_flow(self):
        i = self.route(self.buyer, "nx:shop:cat", values=["nitro"], message=SimpleNamespace(id=1))
        self.assertEqual(i.response.calls[0][0], "edit_message")
        self.assertTrue(i.followup.send.called)
        i = self.route(self.buyer, "nx:shop:prod:nitro", values=[str(self.pid)],
                       message=SimpleNamespace(id=2, flags=SimpleNamespace(ephemeral=True)))
        self.assertEqual(i.response.calls[0][0], "edit_message")
        i = self.route(self.buyer, f"nx:buy:{self.pid}")
        self.assertEqual(i.response.calls[0][0], "send_modal")
        modal = i.response.calls[0][1][0]
        self.assertLessEqual(len(modal.to_dict()["components"]), 5)
        i = self.route(self.buyer, f"nx:buym:{self.pid}", modal=True, components=text_fields(qty="2", note="pseudo"))
        self.assertEqual(self.last_error(i), [], self.last_error(i))
        order = self.db.orders(GUILD)[0]
        self.assertEqual((order["quantity"], order["total_cents"], order["state"]), (2, 1998, "pending"))
        self.assertEqual(self.db.product(GUILD, self.pid)["stock"], 0)
        channel = self.guild.channels[order["channel"]]
        self.assertTrue(channel.name.startswith("commande-0001"))
        self.assertFalse(channel.overwrites[self.guild.default_role].view_channel)
        first = channel.sent[0]
        mentions = first.kw["allowed_mentions"]
        self.assertFalse(mentions.everyone)
        # Le client ne peut pas valider sa propre commande.
        i = self.route(self.buyer, f"nx:ord:delivered:{order['id']}", channel=channel)
        self.assertIn("staff", self.last_error(i)[0])
        # Le staff accepte puis livre ; un deuxième clic ne change rien.
        panel = SimpleNamespace(id=first.id)
        self.route(self.staff, f"nx:ord:accepted:{order['id']}", channel=channel, message=panel)
        self.route(self.staff, f"nx:ord:delivered:{order['id']}", channel=channel, message=panel)
        i = self.route(self.staff, f"nx:ord:delivered:{order['id']}", channel=channel, message=panel)
        self.assertTrue(self.last_error(i))
        self.assertEqual(self.db.order(GUILD, order["id"])["state"], "delivered")
        self.assertEqual(self.db.product(GUILD, self.pid)["stock"], 0)
        # Rupture : impossible de recommander.
        i = self.route(self.buyer, f"nx:buy:{self.pid}")
        self.assertIn("rupture", self.last_error(i)[0])

    def test_ticket_lifecycle(self):
        i = self.route(self.buyer, "nx:sup:kind", values=["support"])
        self.assertEqual(i.response.calls[0][0], "send_modal")
        i = self.route(self.buyer, "nx:supm:support", modal=True, components=text_fields(subject="Aide", details="x"))
        t = self.db.many("SELECT * FROM tickets")[0]
        ch = self.guild.channels[t["channel"]]
        self.client.channels[ch.id] = ch
        # doublon refusé
        i = self.route(self.buyer, "nx:supm:support", modal=True, components=text_fields(subject="Encore"))
        self.assertIn("déjà un ticket", self.last_error(i)[0])
        # prise en charge réservée au staff
        i = self.route(self.buyer, "nx:tk:claim", channel=ch)
        self.assertIn("staff", self.last_error(i)[0])
        self.route(self.staff, "nx:tk:claim", channel=ch, message=SimpleNamespace(id=t["panel_message"]))
        self.assertEqual(self.db.ticket(ch.id)["claimed_by"], 3)
        i = self.route(self.admin, "nx:tk:claim", channel=ch)
        self.assertIn("Déjà pris", self.last_error(i)[0])
        # ajout d'un membre
        self.route(self.buyer, "nx:tk:adduser", values=["2"], channel=ch)
        self.assertIn(self.admin, ch.overwrites)
        # suppression impossible tant que le ticket est ouvert
        i = self.route(self.staff, "nx:tk:delete", channel=ch)
        self.assertIn("Ferme", self.last_error(i)[0])
        # fermeture par le client puis réouverture staff
        self.route(self.buyer, "nx:tk:close", channel=ch, message=SimpleNamespace(id=1))
        self.assertEqual(self.db.ticket(ch.id)["state"], "closed")
        self.assertFalse(ch.overwrites[self.buyer].view_channel)
        i = self.route(self.buyer, "nx:tk:reopen", channel=ch)
        self.assertIn("staff", self.last_error(i)[0])
        self.route(self.staff, "nx:tk:reopen", channel=ch, message=SimpleNamespace(id=1))
        self.assertEqual(self.db.ticket(ch.id)["state"], "open")
        self.assertTrue(ch.overwrites[self.buyer].view_channel)
        # fermeture, transcript archivé, suppression
        self.route(self.staff, "nx:tk:close", channel=ch, message=SimpleNamespace(id=1))
        self.route(self.staff, "nx:tk:delete", channel=ch)
        self.assertTrue(ch.deleted)
        self.assertEqual(self.db.ticket(ch.id)["state"], "deleted")
        self.assertTrue(self.guild.logs.sent and "file" in self.guild.logs.sent[-1].kw)
        # un nouveau ticket est possible ensuite
        self.route(self.buyer, "nx:supm:support", modal=True, components=text_fields(subject="Nouveau"))
        self.assertEqual(len(self.db.many("SELECT * FROM tickets WHERE state='open'")), 1)

    def test_trade_promo_reviews_giveaway(self):
        self.route(self.buyer, "nx:tradem", modal=True, components=text_fields(give="20€ PayPal", want="LTC"))
        trades = self.db.trades(GUILD, 5)
        self.assertEqual(len(trades), 1)
        self.assertTrue(trades[0]["channel"])
        i = self.route(self.buyer, "nx:trade:start")
        self.assertIn("déjà un échange", self.last_error(i)[0])
        i = self.route(self.buyer, "nx:trade:history")
        self.assertTrue(i.response.calls)

        self.route(self.buyer, "nx:promo:premium")
        self.assertEqual(len(self.db.many("SELECT * FROM tickets WHERE kind='promo'")), 1)

        i = self.route(self.buyer, "nx:legit:yes", message=SimpleNamespace(id=1))
        self.assertEqual(self.db.votes(GUILD), (1, 0))
        self.route(self.buyer, "nx:revm", modal=True, components=text_fields(rating="5", comment="Super service"))
        self.assertEqual(self.db.review_stats(GUILD)[1], 1)
        self.assertTrue(self.guild.reviews.sent)
        i = self.route(self.buyer, "nx:rev:new")
        self.assertIn("déjà laissé", self.last_error(i)[0])
        i = self.route(self.buyer, "nx:revm", modal=True, components=text_fields(rating="9", comment="?????"))

        ch = FakeChannel(900, "gw", private=False)
        self.client.channels[900] = ch
        self.db.create_giveaway(4242, GUILD, 900, "5€", 4_000_000_000, 1, 2)
        self.route(self.buyer, "nx:gw:enter", message=SimpleNamespace(id=4242))
        self.assertEqual(self.db.entries(4242), [5])
        self.db.execute("UPDATE giveaways SET ends=0 WHERE message=4242")
        msg = run(H.finish_giveaway(self.client, 4242))
        self.assertIn("terminé", msg)
        self.assertEqual(self.db.giveaway(4242)["winner_ids"], "5")
        self.assertIn("<@5>", ch.sent[-1].content)
        self.assertIn("déjà terminé", run(H.finish_giveaway(self.client, 4242)))
        i = self.route(self.buyer, "nx:gw:enter", message=SimpleNamespace(id=4242))
        self.assertIn("terminé", self.last_error(i)[0])

    def test_setup_forms(self):
        for section in ("channels", "identity", "texts", "social", "restock"):
            i = self.route(self.admin, f"nx:cfg:{section}")
            self.assertEqual(i.response.calls[0][0], "send_modal", section)
            self.assertLessEqual(len(i.response.calls[0][1][0].to_dict()["components"]), 5)
        i = self.route(self.buyer, "nx:cfg:identity")
        self.assertIn("administrateurs", self.last_error(i)[0])
        self.route(self.admin, "nx:cfgm:identity", modal=True, message=SimpleNamespace(id=1), components=text_fields(
            name="NATIX", tos_url="https://natix.gg/tos", shop_tagline="a", exchange_tagline="b", banner_url=""))
        self.assertEqual(self.db.settings(GUILD)["tos_url"], "https://natix.gg/tos")
        i = self.route(self.admin, "nx:cfgm:social", modal=True, message=SimpleNamespace(id=1),
                       components=text_fields(social_discord="http://pas-securise"))
        self.assertIn("https", self.last_error(i)[0])
        # Catégorie et plan via les menus d'administration
        i = self.route(self.admin, "nx:cfg:catpick", values=["_new"])
        self.assertEqual(i.response.calls[0][0], "send_modal")
        self.route(self.admin, "nx:cfgm:cat:_new", modal=True, message=SimpleNamespace(id=1),
                   components=text_fields(name="Comptes Spotify", emoji="🎵", description="Premium", active="oui"))
        self.assertTrue(any(c["name"] == "Comptes Spotify" for c in self.db.categories(GUILD)))
        self.route(self.admin, "nx:cfgm:plan:basic", modal=True, message=SimpleNamespace(id=1),
                   components=text_fields(title="Basic", price="12", duration="7 jours", pings="", emoji="nx_dollar"))
        self.assertEqual(self.db.plan(GUILD, "basic")["price_cents"], 1200)
        self.route(self.admin, "nx:cfg:plandel", values=["basic"], message=SimpleNamespace(id=1))
        self.assertIsNone(self.db.plan(GUILD, "basic"))
        # Le salon des transcripts doit rester privé
        i = self.route(self.admin, "nx:cfgm:channels", modal=True, message=SimpleNamespace(id=1), components=[
            {"type": 18, "component": {"type": 7, "custom_id": "logs", "values": ["700"]}}])
        self.assertIn("privé", self.last_error(i)[0])

    def test_unconfigured_ticket_error_is_clean(self):
        self.db.configure(GUILD, category=0)
        i = self.route(self.buyer, f"nx:buym:{self.pid}", modal=True, components=text_fields(qty="1"))
        self.assertIn("/setup", self.last_error(i)[0])
        self.assertEqual(self.db.product(GUILD, self.pid)["stock"], 2)  # stock rendu
        self.assertEqual(self.db.orders(GUILD)[0]["state"], "cancelled")

    def test_paypal_payment_flow(self):
        # Configuration via /setup → Paiements
        i = self.route(self.admin, "nx:cfg:payment")
        self.assertEqual(i.response.calls[0][0], "send_modal")
        i = self.route(self.admin, "nx:cfgm:payment", modal=True, message=SimpleNamespace(id=1),
                       components=text_fields(paypal="https://evil.com/x", paypal_email="", pay_note="", pay_other=""))
        self.assertIn("paypal.me", self.last_error(i)[0])
        self.route(self.admin, "nx:cfgm:payment", modal=True, message=SimpleNamespace(id=1),
                   components=text_fields(paypal="@natixshop", paypal_email="pay@natix.gg",
                                          pay_note="Pseudo en note", pay_other="LTC : ltc1qtest"))
        s = self.db.settings(GUILD)
        self.assertEqual((s["paypal"], s["paypal_email"]), ("natixshop", "pay@natix.gg"))
        check_view(self, V.setup_view(self.db, self.guild))
        # Commande → ticket avec bouton PayPal au bon montant
        self.route(self.buyer, f"nx:buym:{self.pid}", modal=True, components=text_fields(qty="2"))
        order = self.db.orders(GUILD)[0]
        ch = self.guild.channels[order["channel"]]
        payload = json.dumps(ch.sent[0].kw["view"].to_components())
        self.assertIn("https://paypal.me/natixshop/19.98EUR", payload)
        self.assertIn("pay@natix.gg", payload)
        self.assertIn("ltc1qtest", payload)
        # Seul le client signale le paiement, une seule fois, et le staff est notifié
        i = self.route(self.staff, "nx:pay:done", channel=ch)
        self.assertIn("client", self.last_error(i)[0])
        panel = SimpleNamespace(id=self.db.ticket(ch.id)["panel_message"])
        i = self.route(self.buyer, "nx:pay:done", channel=ch, message=panel)
        self.assertEqual(self.last_error(i), [])
        self.assertEqual(self.db.ticket(ch.id)["paid"], 1)
        self.assertIn("indique avoir payé", ch.sent[-1].content)
        rendered = json.dumps(H.render_ticket(self.db, self.db.ticket(ch.id)).to_components())
        self.assertIn("Paiement signal", rendered)
        i = self.route(self.buyer, "nx:pay:done", channel=ch)
        self.assertIn("déjà signalé", self.last_error(i)[0])
        # Promo : montant du plan
        self.route(self.buyer, "nx:promo:standard")
        t = self.db.many("SELECT * FROM tickets WHERE kind='promo'")[0]
        payload = json.dumps(self.guild.channels[t["channel"]].sent[0].kw["view"].to_components())
        self.assertIn("https://paypal.me/natixshop/20.00EUR", payload)

    def test_slash_commands(self):
        with patch.object(discord, "TextChannel", REAL_TEXT_CHANNEL):
            bot = Natix(store=self.db)
        cmds = {c.name: c for c in bot.tree.get_commands()}
        here = FakeChannel(950, "boutique", private=False)
        restock = FakeChannel(960, "restock", private=False)
        self.guild.channels.update({950: here, 960: restock})
        self.guild.me.guild_permissions = SimpleNamespace(manage_guild=True, administrator=True)
        self.db.configure(GUILD, restock_channel=960, restock_ping="everyone")

        def call(cmd, **kw):
            i = interaction(self.client, self.guild, self.admin, "", channel=here)
            run(cmd.callback(i, **kw))
            return i
        choice = SimpleNamespace(value="shop", name="Boutique")
        call(cmds["panel"], type=choice, salon=None)
        self.assertEqual(self.db.panels(GUILD, "shop")[0]["channel"], 950)
        self.assertEqual(len(here.sent[0].kw["files"]), 2)
        product = cmds["product"]
        call(product.get_command("add"), categorie="nitro", nom="Nitro Basic", prix="4,99", stock=0,
             description="1 mois", emoji="")
        pid = self.db.products(GUILD, "nitro")[-1]["id"]
        self.assertEqual(self.db.product(GUILD, pid)["price_cents"], 499)
        call(product.get_command("stock"), produit=pid, quantite=3, mode=None)
        self.assertEqual(self.db.product(GUILD, pid)["stock"], 3)
        text = restock.sent[-1].content
        self.assertIn("Restock", text)
        self.assertIn("+3", text)
        self.assertIn("/950/", text)
        self.assertTrue(restock.sent[-1].kw["allowed_mentions"].everyone)
        call(product.get_command("edit"), produit=pid, prix="5")
        self.assertEqual(self.db.product(GUILD, pid)["price_cents"], 500)
        call(product.get_command("list"))
        call(product.get_command("remove"), produit=pid)
        self.assertIsNone(self.db.product(GUILD, pid))
        call(cmds["giveaway"].get_command("start"), lot="5€", duree="2h", gagnants=1, salon=None)
        self.assertEqual(len(self.db.active_giveaways(GUILD)), 1)
        i = call(cmds["orders"])
        self.assertTrue(i.response.calls)


if __name__ == "__main__":
    unittest.main()
