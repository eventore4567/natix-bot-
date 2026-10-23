"""Stockage SQLite persistant (volume Railway /data).

Les tables des versions précédentes sont conservées et migrées en place.
Toutes les opérations sensibles (stock, commandes, tickets, giveaways) sont
atomiques : une commande ne peut jamais débiter le stock deux fois.
"""
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import DEFAULT_CATEGORIES, DEFAULT_PLANS, DEFAULT_SETTINGS


def parse_price(value):
    """'10', '6.5', '6,50 €', '10 EUR' -> centimes (int) ; None si invalide."""
    if value is None:
        return None
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", str(value))
    if not m:
        return None
    return int(round(float(m.group(1).replace(",", ".")) * 100))


class Store:
    def __init__(self, path=None):
        default = "/data/natix.sqlite" if Path("/data").is_dir() else "natix.sqlite"
        self.path = path or os.getenv("NATIX_DB_PATH", default)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.schema()

    # ------------------------------------------------------------------ bas niveau
    def one(self, q, a=()):
        return self.db.execute(q, a).fetchone()

    def many(self, q, a=()):
        return self.db.execute(q, a).fetchall()

    def execute(self, q, a=()):
        return self.db.execute(q, a)

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def _columns(self, table):
        return {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}

    def _add_columns(self, table, spec):
        have = self._columns(table)
        for name, decl in spec.items():
            if name not in have:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def schema(self):
        for q in (
            "CREATE TABLE IF NOT EXISTS config(guild INTEGER PRIMARY KEY, json TEXT NOT NULL)",
            """CREATE TABLE IF NOT EXISTS categories(
                guild INTEGER, key TEXT, name TEXT, emoji TEXT, description TEXT,
                position INTEGER DEFAULT 0, active INTEGER DEFAULT 1, PRIMARY KEY(guild, key))""",
            """CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, category TEXT, name TEXT,
                details TEXT, price TEXT, stock INTEGER DEFAULT -1, active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, buyer INTEGER, product_id INTEGER,
                product_name TEXT, quantity INTEGER, price TEXT, state TEXT, channel INTEGER,
                created INTEGER, updated INTEGER, notes TEXT)""",
            """CREATE TABLE IF NOT EXISTS tickets(
                channel INTEGER PRIMARY KEY, guild INTEGER, owner INTEGER, kind TEXT, state TEXT)""",
            """CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, user INTEGER, give TEXT,
                want TEXT, details TEXT, state TEXT DEFAULT 'open', channel INTEGER, created INTEGER)""",
            """CREATE TABLE IF NOT EXISTS promo_plans(
                guild INTEGER, plan_key TEXT, title TEXT, price TEXT, description TEXT,
                active INTEGER DEFAULT 1, PRIMARY KEY(guild, plan_key))""",
            """CREATE TABLE IF NOT EXISTS giveaways(
                message INTEGER PRIMARY KEY, channel INTEGER, prize TEXT, ends INTEGER,
                closed INTEGER DEFAULT 0)""",
            "CREATE TABLE IF NOT EXISTS entries(message INTEGER, member INTEGER, PRIMARY KEY(message, member))",
            "CREATE TABLE IF NOT EXISTS legit_votes(guild INTEGER, member INTEGER, yes INTEGER, PRIMARY KEY(guild, member))",
            """CREATE TABLE IF NOT EXISTS reviews(
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, author INTEGER, rating INTEGER,
                comment TEXT, created INTEGER, approved INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS panels(
                message INTEGER PRIMARY KEY, guild INTEGER, channel INTEGER, kind TEXT, created INTEGER)""",
            """CREATE TABLE IF NOT EXISTS audits(
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER, actor INTEGER, action TEXT,
                details TEXT, created INTEGER)""",
        ):
            self.db.execute(q)
        self._add_columns("products", {
            "price_cents": "INTEGER", "emoji": "TEXT DEFAULT ''", "position": "INTEGER DEFAULT 0",
        })
        self._add_columns("orders", {
            "unit_cents": "INTEGER DEFAULT 0", "total_cents": "INTEGER DEFAULT 0",
            "reserved": "INTEGER DEFAULT 0", "staff": "INTEGER DEFAULT 0",
        })
        self._add_columns("tickets", {
            "claimed_by": "INTEGER NOT NULL DEFAULT 0", "number": "INTEGER DEFAULT 0",
            "ref": "TEXT DEFAULT ''", "subject": "TEXT DEFAULT ''", "created": "INTEGER DEFAULT 0",
            "closed_at": "INTEGER DEFAULT 0", "panel_message": "INTEGER DEFAULT 0",
            "paid": "INTEGER DEFAULT 0",
        })
        self._add_columns("promo_plans", {
            "price_cents": "INTEGER", "duration": "TEXT DEFAULT ''", "pings": "TEXT DEFAULT ''",
            "emoji": "TEXT DEFAULT 'nx_dollar'", "position": "INTEGER DEFAULT 0",
        })
        self._add_columns("giveaways", {
            "guild": "INTEGER DEFAULT 0", "winners": "INTEGER DEFAULT 1", "host": "INTEGER DEFAULT 0",
            "winner_ids": "TEXT DEFAULT ''",
        })
        # Migration des prix texte des anciennes versions.
        for r in self.many("SELECT id, price FROM products WHERE price_cents IS NULL"):
            self.execute("UPDATE products SET price_cents=? WHERE id=?", (parse_price(r["price"]) or 0, r["id"]))
        for r in self.many("SELECT guild, plan_key, price FROM promo_plans WHERE price_cents IS NULL"):
            self.execute("UPDATE promo_plans SET price_cents=? WHERE guild=? AND plan_key=?",
                         (parse_price(r["price"]) or 0, r["guild"], r["plan_key"]))
        for q in (
            "CREATE INDEX IF NOT EXISTS ix_products ON products(guild, category, active)",
            "CREATE INDEX IF NOT EXISTS ix_orders ON orders(guild, buyer, state)",
            "CREATE INDEX IF NOT EXISTS ix_tickets ON tickets(guild, owner, kind, state)",
            "CREATE INDEX IF NOT EXISTS ix_trades ON trades(guild, user)",
            "CREATE INDEX IF NOT EXISTS ix_panels ON panels(guild, kind)",
        ):
            self.db.execute(q)

    # ------------------------------------------------------------------ réglages
    def settings(self, guild):
        row = self.one("SELECT json FROM config WHERE guild=?", (guild,))
        try:
            stored = json.loads(row["json"]) if row else {}
        except (TypeError, ValueError):
            stored = {}
        return {**DEFAULT_SETTINGS, **stored}

    def configure(self, guild, **values):
        with self.tx():
            s = self.settings(guild)
            s.update(values)
            self.execute("INSERT OR REPLACE INTO config(guild, json) VALUES (?, ?)",
                         (guild, json.dumps(s, ensure_ascii=False)))

    def next_ticket_number(self, guild):
        with self.tx():
            s = self.settings(guild)
            s["ticket_counter"] = int(s.get("ticket_counter", 0)) + 1
            self.execute("INSERT OR REPLACE INTO config(guild, json) VALUES (?, ?)",
                         (guild, json.dumps(s, ensure_ascii=False)))
            return s["ticket_counter"]

    def audit(self, guild, actor, action, details=""):
        self.execute("INSERT INTO audits(guild, actor, action, details, created) VALUES (?,?,?,?,?)",
                     (guild, actor, action, str(details)[:400], int(time.time())))

    # ------------------------------------------------------------------ catégories
    def ensure_defaults(self, guild):
        if not self.one("SELECT 1 FROM categories WHERE guild=?", (guild,)):
            for pos, (key, name, emoji, desc) in enumerate(DEFAULT_CATEGORIES):
                self.execute("INSERT OR IGNORE INTO categories VALUES (?,?,?,?,?,?,1)",
                             (guild, key, name, emoji, desc, pos))
        if not self.one("SELECT 1 FROM promo_plans WHERE guild=?", (guild,)):
            for pos, (key, title, cents, duration, pings, emoji) in enumerate(DEFAULT_PLANS):
                self.execute("""INSERT OR IGNORE INTO promo_plans
                    (guild, plan_key, title, price, description, active, price_cents, duration, pings, emoji, position)
                    VALUES (?,?,?,?,?,1,?,?,?,?,?)""",
                             (guild, key, title, "", "", cents, duration, pings, emoji, pos))

    def categories(self, guild, include_inactive=False):
        self.ensure_defaults(guild)
        q = "SELECT * FROM categories WHERE guild=?" + ("" if include_inactive else " AND active=1")
        return self.many(q + " ORDER BY position, name", (guild,))

    def category(self, guild, key):
        self.ensure_defaults(guild)
        return self.one("SELECT * FROM categories WHERE guild=? AND key=?", (guild, key))

    def save_category(self, guild, key, name, emoji, description, active=1):
        pos = self.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM categories WHERE guild=?", (guild,))["p"]
        self.execute("""INSERT INTO categories VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(guild, key) DO UPDATE SET name=excluded.name, emoji=excluded.emoji,
            description=excluded.description, active=excluded.active""",
                     (guild, key, name[:80], emoji[:60], description[:100], pos, active))

    # ------------------------------------------------------------------ produits
    def products(self, guild, category=None, limit=25):
        if category:
            return self.many("""SELECT * FROM products WHERE guild=? AND category=? AND active=1
                ORDER BY position, id LIMIT ?""", (guild, category, limit))
        return self.many("SELECT * FROM products WHERE guild=? AND active=1 ORDER BY category, position, id LIMIT ?",
                         (guild, limit))

    def search_products(self, guild, query="", limit=25):
        """Search every active product, not just the first 200 from /product list.

        Case-insensitive names and category, plus partial numeric product IDs.
        Result count stays within Discord's 25-choice autocomplete limit.
        """
        limit = max(1, min(int(limit), 25))
        term = str(query or "").strip().lstrip("#")
        if not term:
            return self.many(
                "SELECT * FROM products WHERE guild=? AND active=1 "
                "ORDER BY category, position, id LIMIT ?", (guild, limit)
            )
        # Escape LIKE metacharacters entered in a product name.
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped + "%"
        return self.many(
            """SELECT * FROM products WHERE guild=? AND active=1
               AND (name LIKE ? ESCAPE '\' COLLATE NOCASE
                    OR category LIKE ? ESCAPE '\' COLLATE NOCASE
                    OR CAST(id AS TEXT) LIKE ? ESCAPE '\')
               ORDER BY category, position, id LIMIT ?""",
            (guild, pattern, pattern, pattern, limit)
        )

    def resolve_product(self, guild, reference):
        """Accept a product ID or an unambiguous product name for mobile commands.

        Returns (product, error), never picks an ambiguous name silently.
        """
        reference = str(reference or "").strip()
        if reference.startswith("#"):
            reference = reference[1:].strip()
        if not reference or reference.startswith("__"):
            return None, "Aucun produit sélectionné. Crée un article avec /product add."
        if reference.isdecimal():
            row = self.product(guild, int(reference))
            return (row, None) if row else (
                None, "Produit introuvable. Vérifie son identifiant avec /product list."
            )
        exact = self.many(
            "SELECT * FROM products WHERE guild=? AND active=1 "
            "AND name=? COLLATE NOCASE LIMIT 2", (guild, reference)
        )
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return None, "Plusieurs produits portent ce nom. Utilise l'identifiant #ID."
        matches = self.search_products(guild, reference, limit=2)
        if len(matches) == 1:
            return matches[0], None
        if matches:
            return None, "Plusieurs produits correspondent. Précise le nom ou utilise le numéro #ID."
        return None, "Aucun produit trouvé. Utilise /product list ou crée-le avec /product add."

    def product(self, guild, pid):
        return self.one("SELECT * FROM products WHERE guild=? AND id=? AND active=1", (guild, pid))

    def add_product(self, guild, category, name, details, cents, stock=-1, emoji=""):
        cur = self.execute("""INSERT INTO products(guild, category, name, details, price, stock, active, price_cents, emoji)
            VALUES (?,?,?,?,?,?,1,?,?)""", (guild, category, name[:80], details[:300], "", stock, cents, emoji[:60]))
        return cur.lastrowid

    def update_product(self, guild, pid, **fields):
        allowed = {"name", "details", "price_cents", "stock", "active", "category", "emoji"}
        items = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not items:
            return False
        sql = ", ".join(f"{k}=?" for k in items)
        return self.execute(f"UPDATE products SET {sql} WHERE guild=? AND id=? AND active=1",
                            (*items.values(), guild, pid)).rowcount > 0

    def add_stock(self, guild, pid, amount):
        """Ajoute du stock (un stock illimité reste illimité). Retourne le nouveau stock."""
        with self.tx():
            row = self.one("SELECT stock FROM products WHERE guild=? AND id=? AND active=1", (guild, pid))
            if not row:
                return None
            if row["stock"] == -1:
                return -1
            new = max(0, row["stock"] + amount)
            self.execute("UPDATE products SET stock=? WHERE guild=? AND id=?", (new, guild, pid))
            return new

    # ------------------------------------------------------------------ commandes
    def create_order(self, guild, buyer, pid, qty, note=""):
        """Crée une commande en réservant le stock de façon atomique.

        Retourne (order_id, None) ou (None, message d'erreur).
        """
        with self.tx():
            p = self.one("SELECT * FROM products WHERE guild=? AND id=? AND active=1", (guild, pid))
            if not p:
                return None, "Ce produit n'est plus disponible."
            if p["stock"] != -1:
                if p["stock"] < qty:
                    return None, f"Stock insuffisant ({p['stock']} restant)."
                self.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, pid))
            now = int(time.time())
            unit = p["price_cents"] or 0
            cur = self.execute("""INSERT INTO orders(guild, buyer, product_id, product_name, quantity, price,
                state, channel, created, updated, notes, unit_cents, total_cents, reserved)
                VALUES (?,?,?,?,?,?,'pending',NULL,?,?,?,?,?,?)""",
                               (guild, buyer, pid, p["name"], qty, "", now, now, note[:500], unit, unit*qty,
                                qty if p["stock"] != -1 else 0))
            return cur.lastrowid, None

    def order(self, guild, oid):
        return self.one("SELECT * FROM orders WHERE guild=? AND id=?", (guild, oid))

    def order_by_channel(self, channel):
        return self.one("SELECT * FROM orders WHERE channel=? ORDER BY id DESC LIMIT 1", (channel,))

    def orders(self, guild, buyer=None, state=None, limit=20):
        q, a = "SELECT * FROM orders WHERE guild=?", [guild]
        if buyer:
            q += " AND buyer=?"
            a.append(buyer)
        if state:
            q += " AND state=?"
            a.append(state)
        return self.many(q + " ORDER BY id DESC LIMIT ?", (*a, limit))

    def attach_order(self, guild, oid, channel):
        self.execute("UPDATE orders SET channel=? WHERE guild=? AND id=?", (channel, guild, oid))

    def transition_order(self, guild, oid, target, actor):
        """Fait évoluer une commande. Le stock réservé est rendu une seule fois en cas d'annulation."""
        allowed = {"pending": {"accepted", "cancelled"}, "accepted": {"delivered", "cancelled"}}
        with self.tx():
            o = self.one("SELECT * FROM orders WHERE guild=? AND id=?", (guild, oid))
            if not o:
                return False, "Commande introuvable."
            if o["state"] == target:
                return False, "La commande est déjà dans cet état."
            if target not in allowed.get(o["state"], set()):
                return False, "Action impossible sur une commande " + o["state"] + "."
            if target == "cancelled" and o["reserved"]:
                self.execute("UPDATE products SET stock=stock+? WHERE guild=? AND id=? AND stock!=-1",
                             (o["reserved"], guild, o["product_id"]))
            self.execute("""UPDATE orders SET state=?, updated=?, staff=?,
                reserved=CASE WHEN ?='cancelled' THEN 0 ELSE reserved END WHERE id=? AND state=?""",
                         (target, int(time.time()), actor, target, oid, o["state"]))
            self.audit(guild, actor, "order:" + target, oid)
            return True, None

    # ------------------------------------------------------------------ tickets
    def open_ticket(self, guild, owner, kind, ref=None):
        q = "SELECT * FROM tickets WHERE guild=? AND owner=? AND kind=? AND state='open'"
        a = [guild, owner, kind]
        if ref is not None:
            q += " AND ref=?"
            a.append(str(ref))
        return self.one(q, a)

    def create_ticket(self, channel, guild, owner, kind, number, ref="", subject=""):
        self.execute("""INSERT INTO tickets(channel, guild, owner, kind, state, claimed_by, number, ref, subject, created)
            VALUES (?,?,?,?, 'open', 0, ?,?,?,?)""",
                     (channel, guild, owner, kind, number, str(ref), subject[:1800], int(time.time())))

    def ticket(self, channel):
        return self.one("SELECT * FROM tickets WHERE channel=?", (channel,))

    def set_ticket(self, channel, **fields):
        allowed = {"state", "claimed_by", "closed_at", "panel_message"}
        items = {k: v for k, v in fields.items() if k in allowed}
        sql = ", ".join(f"{k}=?" for k in items)
        self.execute(f"UPDATE tickets SET {sql} WHERE channel=?", (*items.values(), channel))

    def mark_paid(self, channel):
        """Le client signale son paiement (une seule fois)."""
        return self.execute("UPDATE tickets SET paid=1 WHERE channel=? AND state='open' AND paid=0",
                            (channel,)).rowcount > 0

    def claim_ticket(self, channel, staff):
        return self.execute("""UPDATE tickets SET claimed_by=? WHERE channel=? AND state='open'
            AND claimed_by IN (0, ?)""", (staff, channel, staff)).rowcount > 0

    def transition_ticket(self, channel, src, dst):
        extra = ", closed_at=%d" % int(time.time()) if dst == "closed" else ""
        return self.execute(f"UPDATE tickets SET state=?{extra} WHERE channel=? AND state=?",
                            (dst, channel, src)).rowcount > 0

    # ------------------------------------------------------------------ échanges
    def create_trade(self, guild, user, give, want, details):
        return self.execute("""INSERT INTO trades(guild, user, give, want, details, state, created)
            VALUES (?,?,?,?,?, 'open', ?)""", (guild, user, give[:200], want[:200], details[:500],
                                               int(time.time()))).lastrowid

    def attach_trade(self, tid, channel):
        self.execute("UPDATE trades SET channel=? WHERE id=?", (channel, tid))

    def trades(self, guild, user, limit=10):
        return self.many("SELECT * FROM trades WHERE guild=? AND user=? ORDER BY id DESC LIMIT ?", (guild, user, limit))

    def set_trade_state_by_channel(self, channel, state):
        self.execute("UPDATE trades SET state=? WHERE channel=?", (state, channel))

    # ------------------------------------------------------------------ promotions
    def plans(self, guild):
        self.ensure_defaults(guild)
        return self.many("SELECT * FROM promo_plans WHERE guild=? AND active=1 ORDER BY position, plan_key LIMIT 6",
                         (guild,))

    def plan(self, guild, key):
        self.ensure_defaults(guild)
        return self.one("SELECT * FROM promo_plans WHERE guild=? AND plan_key=? AND active=1", (guild, key))

    def save_plan(self, guild, key, title, cents, duration, pings, emoji):
        pos = self.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM promo_plans WHERE guild=?", (guild,))["p"]
        self.execute("""INSERT INTO promo_plans(guild, plan_key, title, price, description, active, price_cents,
                duration, pings, emoji, position) VALUES (?,?,?,'','',1,?,?,?,?,?)
            ON CONFLICT(guild, plan_key) DO UPDATE SET title=excluded.title, price_cents=excluded.price_cents,
                duration=excluded.duration, pings=excluded.pings, emoji=excluded.emoji, active=1""",
                     (guild, key, title[:60], cents, duration[:40], pings[:120], emoji[:60], pos))

    def delete_plan(self, guild, key):
        return self.execute("UPDATE promo_plans SET active=0 WHERE guild=? AND plan_key=?", (guild, key)).rowcount > 0

    # ------------------------------------------------------------------ giveaways
    def create_giveaway(self, message, guild, channel, prize, ends, winners, host):
        self.execute("""INSERT INTO giveaways(message, channel, prize, ends, closed, guild, winners, host)
            VALUES (?,?,?,?,0,?,?,?)""", (message, channel, prize[:120], ends, guild, winners, host))

    def giveaway(self, message):
        return self.one("SELECT * FROM giveaways WHERE message=?", (message,))

    def entries(self, message):
        return [r["member"] for r in self.many("SELECT member FROM entries WHERE message=? ORDER BY rowid", (message,))]

    def toggle_entry(self, message, member):
        with self.tx():
            if self.one("SELECT 1 FROM entries WHERE message=? AND member=?", (message, member)):
                self.execute("DELETE FROM entries WHERE message=? AND member=?", (message, member))
                return False
            self.execute("INSERT INTO entries VALUES (?,?)", (message, member))
            return True

    def close_giveaway(self, message, winner_ids):
        return self.execute("UPDATE giveaways SET closed=1, winner_ids=? WHERE message=? AND closed=0",
                            (",".join(map(str, winner_ids)), message)).rowcount > 0

    def due_giveaways(self):
        return self.many("SELECT * FROM giveaways WHERE closed=0 AND ends<=?", (int(time.time()),))

    def active_giveaways(self, guild):
        return self.many("SELECT * FROM giveaways WHERE guild=? AND closed=0 ORDER BY ends", (guild,))

    def recent_giveaways(self, guild, limit=25):
        return self.many("SELECT * FROM giveaways WHERE guild=? ORDER BY ends DESC LIMIT ?", (guild, limit))

    # ------------------------------------------------------------------ avis
    def vote(self, guild, member, yes):
        with self.tx():
            row = self.one("SELECT yes FROM legit_votes WHERE guild=? AND member=?", (guild, member))
            if row and row["yes"] == int(yes):
                self.execute("DELETE FROM legit_votes WHERE guild=? AND member=?", (guild, member))
                return None
            self.execute("INSERT OR REPLACE INTO legit_votes VALUES (?,?,?)", (guild, member, int(yes)))
            return bool(yes)

    def votes(self, guild):
        r = self.one("""SELECT COALESCE(SUM(yes),0) AS y, COALESCE(SUM(1-yes),0) AS n
            FROM legit_votes WHERE guild=?""", (guild,))
        return r["y"], r["n"]

    def add_review(self, guild, author, rating, comment):
        return self.execute("INSERT INTO reviews(guild, author, rating, comment, created, approved) VALUES (?,?,?,?,?,1)",
                            (guild, author, rating, comment[:600], int(time.time()))).lastrowid

    def last_review(self, guild, author):
        return self.one("SELECT * FROM reviews WHERE guild=? AND author=? ORDER BY id DESC LIMIT 1", (guild, author))

    def review_stats(self, guild):
        rows = self.many("SELECT rating, COUNT(*) AS n FROM reviews WHERE guild=? AND approved=1 GROUP BY rating",
                         (guild,))
        dist = {k: 0 for k in range(1, 6)}
        for r in rows:
            if r["rating"] in dist:
                dist[r["rating"]] = r["n"]
        total = sum(dist.values())
        avg = sum(k*v for k, v in dist.items())/total if total else 0
        recent = self.many("SELECT * FROM reviews WHERE guild=? AND approved=1 ORDER BY id DESC LIMIT 5", (guild,))
        return avg, total, dist, recent

    # ------------------------------------------------------------------ panneaux publiés
    def register_panel(self, message, guild, channel, kind):
        self.execute("INSERT OR REPLACE INTO panels VALUES (?,?,?,?,?)", (message, guild, channel, kind, int(time.time())))

    def panels(self, guild, kind=None):
        if kind:
            return self.many("SELECT * FROM panels WHERE guild=? AND kind=? ORDER BY created DESC", (guild, kind))
        return self.many("SELECT * FROM panels WHERE guild=? ORDER BY created DESC", (guild,))

    def drop_panel(self, message):
        self.execute("DELETE FROM panels WHERE message=?", (message,))

    def metrics(self, guild):
        def n(q):
            return self.one(q, (guild,))[0]
        return {
            "products": n("SELECT COUNT(*) FROM products WHERE guild=? AND active=1"),
            "orders": n("SELECT COUNT(*) FROM orders WHERE guild=?"),
            "pending": n("SELECT COUNT(*) FROM orders WHERE guild=? AND state IN ('pending','accepted')"),
            "delivered": n("SELECT COUNT(*) FROM orders WHERE guild=? AND state='delivered'"),
            "tickets": n("SELECT COUNT(*) FROM tickets WHERE guild=? AND state='open'"),
        }
