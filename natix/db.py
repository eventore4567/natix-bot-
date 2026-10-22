"""Persistent multi-server storage. Existing NATIX 1.x tables are preserved."""
import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULT = {
    "staff": 0, "category": 0, "banner": "", "name": "NATIX",
    "color": "E6E4F0", "logs": 0, "vouch_channel": 0, "order_channel": 0,
    "supporter_role": 0, "status": ".gg/natix",
    "currency": "€", "welcome": False,
    "rules": (
        "Payez uniquement par les moyens officiels validés dans un ticket.\n"
        "Ne communiquez aucun mot de passe, token ou code de connexion.\n"
        "Les commandes sont confirmées uniquement après validation du staff."
    ),
    "faq": "Comment commander ? Ouvre /shop, choisis un produit puis clique sur Commander.\nBesoin d'aide ? Utilise /support.",
    "partners": "Nos partenaires seront affichés ici.",
}

class Store:
    def __init__(self, path=None):
        self.path = path or os.getenv("NATIX_DB_PATH", "/data/natix.sqlite" if Path("/data").is_dir() else "natix.sqlite")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.schema()

    def schema(self):
        for query in (
            "CREATE TABLE IF NOT EXISTS config(guild INTEGER PRIMARY KEY,json TEXT NOT NULL)",
            """CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild INTEGER,category TEXT,name TEXT,
                details TEXT,price TEXT,stock INTEGER DEFAULT -1,active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS tickets(
                channel INTEGER PRIMARY KEY,guild INTEGER,owner INTEGER,kind TEXT,state TEXT)""",
            """CREATE TABLE IF NOT EXISTS giveaways(
                message INTEGER PRIMARY KEY,channel INTEGER,prize TEXT,ends INTEGER,closed INTEGER DEFAULT 0)""",
            "CREATE TABLE IF NOT EXISTS entries(message INTEGER,member INTEGER,PRIMARY KEY(message,member))",
            "CREATE TABLE IF NOT EXISTS votes(message INTEGER,member INTEGER,yes INTEGER,PRIMARY KEY(message,member))",
            """CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild INTEGER,buyer INTEGER,product_id INTEGER,
                product_name TEXT,quantity INTEGER,price TEXT,state TEXT,channel INTEGER,created INTEGER,
                updated INTEGER,notes TEXT)""",
            """CREATE TABLE IF NOT EXISTS reviews(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild INTEGER,author INTEGER,rating INTEGER,
                comment TEXT,created INTEGER,approved INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS audits(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild INTEGER,actor INTEGER,action TEXT,
                details TEXT,created INTEGER)""",
            "CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(guild,owner,kind,state)",
            "CREATE INDEX IF NOT EXISTS idx_orders_guild ON orders(guild,state,created)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_guild ON reviews(guild,approved)",
        ):
            self.db.execute(query)

    def one(self, query, args=()):
        return self.db.execute(query, args).fetchone()

    def many(self, query, args=()):
        return self.db.execute(query, args).fetchall()

    def execute(self, query, args=()):
        return self.db.execute(query, args)

    def settings(self, guild):
        row=self.one("SELECT json FROM config WHERE guild=?", (guild,))
        try:
            stored=json.loads(row["json"]) if row else {}
        except (ValueError, TypeError):
            stored={}
        return {**DEFAULT, **stored}

    def configure(self, guild, **values):
        settings=self.settings(guild);settings.update(values)
        self.execute("INSERT OR REPLACE INTO config(guild,json) VALUES (?,?)",
                     (guild,json.dumps(settings,ensure_ascii=False)))

    def audit(self,guild,actor,action,details=""):
        self.execute("INSERT INTO audits(guild,actor,action,details,created) VALUES (?,?,?,?,?)",
                     (guild,actor,action,details[:400],int(time.time())))

    def categories(self, guild):
        return self.many("SELECT category,COUNT(*) n FROM products WHERE guild=? AND active=1 GROUP BY category", (guild,))

    def products(self,guild,category=None,limit=50):
        if category:
            return self.many("SELECT * FROM products WHERE guild=? AND category=? AND active=1 ORDER BY id DESC LIMIT ?",
                             (guild,category,limit))
        return self.many("SELECT * FROM products WHERE guild=? AND active=1 ORDER BY id DESC LIMIT ?",(guild,limit))

    def product(self,guild,pid):
        return self.one("SELECT * FROM products WHERE guild=? AND id=? AND active=1",(guild,pid))

    def add_product(self,guild,category,name,details,price,stock=-1):
        cur=self.execute("INSERT INTO products(guild,category,name,details,price,stock) VALUES (?,?,?,?,?,?)",
                         (guild,category,name,details,price,stock))
        return cur.lastrowid

    def modify_product(self,guild,pid,**kw):
        permitted={"name","details","price","stock","active","category"}
        items={k:v for k,v in kw.items() if k in permitted}
        if not items:
            return False
        sql=", ".join(k+"=?" for k in items)
        cur=self.execute("UPDATE products SET "+sql+" WHERE guild=? AND id=?",(*items.values(),guild,pid))
        return cur.rowcount>0

    def active_ticket(self,guild,user,kind):
        return self.one("SELECT * FROM tickets WHERE guild=? AND owner=? AND kind=? AND state='open'",
                        (guild,user,kind))

    def create_ticket(self,channel,guild,owner,kind):
        self.execute("INSERT INTO tickets(channel,guild,owner,kind,state) VALUES (?,?,?,?,'open')",
                     (channel,guild,owner,kind))

    def ticket(self,channel):
        return self.one("SELECT * FROM tickets WHERE channel=?", (channel,))

    def state_ticket(self,channel,state):
        self.execute("UPDATE tickets SET state=? WHERE channel=?", (state,channel))

    def create_order(self,guild,buyer,product,qty,note=""):
        now=int(time.time())
        cur=self.execute("""INSERT INTO orders
            (guild,buyer,product_id,product_name,quantity,price,state,channel,created,updated,notes)
            VALUES (?,?,?,?,?,?,'pending',NULL,?,?,?)""",
            (guild,buyer,product["id"],product["name"],qty,product["price"],now,now,note[:500]))
        return cur.lastrowid

    def order(self,guild,oid):
        return self.one("SELECT * FROM orders WHERE guild=? AND id=?", (guild,oid))

    def orders(self,guild,user=None,limit=20):
        if user is not None:
            return self.many("SELECT * FROM orders WHERE guild=? AND buyer=? ORDER BY id DESC LIMIT ?",(guild,user,limit))
        return self.many("SELECT * FROM orders WHERE guild=? ORDER BY id DESC LIMIT ?",(guild,limit))

    def order_state(self,guild,oid,state,actor):
        cur=self.execute("UPDATE orders SET state=?,updated=? WHERE guild=? AND id=?",
                         (state,int(time.time()),guild,oid))
        if cur.rowcount:
            self.audit(guild,actor,"order:"+state,str(oid))
        return cur.rowcount>0

    def deduct_stock(self,guild,pid,qty):
        # Atomic reduction. -1 means unlimited inventory.
        cur=self.execute("""UPDATE products SET stock=CASE WHEN stock=-1 THEN -1 ELSE stock-? END
            WHERE guild=? AND id=? AND active=1 AND (stock=-1 OR stock>=?)""",
            (qty,guild,pid,qty))
        return cur.rowcount>0

    def giveaway(self,message):
        return self.one("SELECT * FROM giveaways WHERE message=?", (message,))

    def giveaway_entries(self,message):
        return [r["member"] for r in self.many("SELECT member FROM entries WHERE message=?",(message,))]

    def toggle_entry(self,message,user):
        existing=self.one("SELECT 1 FROM entries WHERE message=? AND member=?",(message,user))
        if existing:
            self.execute("DELETE FROM entries WHERE message=? AND member=?",(message,user))
            return False
        self.execute("INSERT INTO entries VALUES (?,?)",(message,user))
        return True

    def metrics(self,guild):
        return {
            "products":self.one("SELECT COUNT(*) n FROM products WHERE guild=? AND active=1",(guild,))["n"],
            "orders":self.one("SELECT COUNT(*) n FROM orders WHERE guild=?",(guild,))["n"],
            "open_tickets":self.one("SELECT COUNT(*) n FROM tickets WHERE guild=? AND state='open'",(guild,))["n"],
            "reviews":self.one("SELECT COUNT(*) n FROM reviews WHERE guild=? AND approved=1",(guild,))["n"],
        }
