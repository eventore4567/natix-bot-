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
            """CREATE TABLE IF NOT EXISTS custom_panels(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild INTEGER,title TEXT,
                description TEXT,active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS custom_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,panel_id INTEGER,label TEXT,
                description TEXT,action_kind TEXT,action_value TEXT,emoji TEXT)""",
            """CREATE TABLE IF NOT EXISTS promo_plans(
                guild INTEGER,plan_key TEXT,title TEXT,price TEXT,description TEXT,
                active INTEGER DEFAULT 1,PRIMARY KEY(guild,plan_key))""",
            "CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(guild,owner,kind,state)",
            "CREATE INDEX IF NOT EXISTS idx_orders_guild ON orders(guild,state,created)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_guild ON reviews(guild,approved)",
        ):
            self.db.execute(query)

        # Existing NATIX databases predate staff ticket claiming.
        # Apply this migration once without discarding historic ticket records.
        columns={col["name"] for col in self.db.execute("PRAGMA table_info(tickets)")}
        if "claimed_by" not in columns:
            self.db.execute("ALTER TABLE tickets ADD COLUMN claimed_by INTEGER NOT NULL DEFAULT 0")

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

    def products_page(self,guild,category,page=0,page_size=6):
        page=max(0,min(int(page),10000))
        page_size=max(1,min(int(page_size),8))
        rows=self.many("""SELECT * FROM products WHERE guild=? AND category=? AND active=1
            ORDER BY id DESC LIMIT ? OFFSET ?""",
            (guild,category,page_size,page*page_size))
        total=self.one("""SELECT COUNT(*) AS n FROM products
            WHERE guild=? AND category=? AND active=1""",(guild,category))["n"]
        return rows,total

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

    def claim_ticket(self,channel,staff_id):
        """Atomically assign an unclaimed, open ticket to exactly one staff member."""
        cursor=self.execute(
            """UPDATE tickets SET claimed_by=?
               WHERE channel=? AND state='open'
               AND (claimed_by=0 OR claimed_by=?)""",
            (staff_id,channel,staff_id))
        return cursor.rowcount>0

    def release_ticket(self,channel,staff_id,override=False):
        """Only the claimer or a server manager may release an assignment."""
        if override:
            cursor=self.execute(
                "UPDATE tickets SET claimed_by=0 WHERE channel=? AND state='open' AND claimed_by!=0",
                (channel,))
        else:
            cursor=self.execute(
                "UPDATE tickets SET claimed_by=0 WHERE channel=? AND state='open' AND claimed_by=?",
                (channel,staff_id))
        return cursor.rowcount>0

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


    def attach_order_ticket(self,guild,order_id,channel):
        self.execute(
            "UPDATE orders SET channel=?,updated=? WHERE guild=? AND id=?",
            (channel,int(time.time()),guild,order_id))

    def transition_order(self,guild,order_id,target,actor):
        """Advance orders atomically. Deduct stock exactly once on delivery.

        Returns (success, status) and rolls back both order and stock changes on
        invalid transitions, insufficient stock or database errors.
        """
        allowed={
            "pending":{"accepted","cancelled"},
            "accepted":{"processing","cancelled"},
            "processing":{"delivered","cancelled"},
            "delivered":set(),
            "cancelled":set(),
        }
        if target not in {"pending","accepted","processing","delivered","cancelled"}:
            return False,"Statut inconnu."
        self.db.execute("BEGIN IMMEDIATE")
        try:
            order=self.one("SELECT * FROM orders WHERE guild=? AND id=?",
                           (guild,order_id))
            if not order:
                self.db.execute("ROLLBACK")
                return False,"Commande introuvable."
            state=order["state"]
            if state==target:
                self.db.execute("ROLLBACK")
                return True,"Commande déjà dans cet état, aucun nouveau débit de stock."
            if target not in allowed.get(state,set()):
                self.db.execute("ROLLBACK")
                return False,"Transition impossible : "+state+" → "+target+"."
            if target=="delivered":
                if not self.deduct_stock(guild,order["product_id"],order["quantity"]):
                    self.db.execute("ROLLBACK")
                    return False,"Stock insuffisant ou produit indisponible : aucune livraison enregistrée."
            now=int(time.time())
            self.db.execute(
                "UPDATE orders SET state=?,updated=? WHERE guild=? AND id=?",
                (target,now,guild,order_id))
            self.audit(guild,actor,"order:"+target,str(order_id))
            self.db.execute("COMMIT")
            return True,"Commande #"+str(order_id)+" : "+target
        except Exception:
            self.db.execute("ROLLBACK")
            raise

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

    def custom_panel(self,guild,pid):
        return self.one("SELECT * FROM custom_panels WHERE guild=? AND id=? AND active=1",(guild,pid))

    def custom_panels(self,guild=None):
        if guild is None:
            return self.many("SELECT * FROM custom_panels WHERE active=1")
        return self.many("SELECT * FROM custom_panels WHERE guild=? AND active=1 ORDER BY id",(guild,))

    def custom_items(self,pid):
        return self.many("SELECT * FROM custom_items WHERE panel_id=? ORDER BY id",(pid,))

    def create_custom_panel(self,guild,title,description):
        cur=self.execute("INSERT INTO custom_panels(guild,title,description) VALUES (?,?,?)",
                         (guild,title[:100],description[:1500]))
        return cur.lastrowid

    def create_custom_item(self,pid,label,description,kind,value,emoji):
        cur=self.execute("INSERT INTO custom_items(panel_id,label,description,action_kind,action_value,emoji) VALUES (?,?,?,?,?,?)",
                         (pid,label[:70],description[:160],kind,value[:80],emoji[:12]))
        return cur.lastrowid

    def promo_plans(self,guild):
        from .assets import PLANS
        rows=self.many("SELECT * FROM promo_plans WHERE guild=? AND active=1 ORDER BY plan_key LIMIT 8",(guild,))
        if not rows:
            return [(k,title,detail) for k,title,detail in PLANS]
        return [(r["plan_key"],r["title"],r["price"]+" · "+r["description"]) for r in rows]

    def set_promo_plan(self,guild,key,title,price,description):
        self.execute("""INSERT INTO promo_plans(guild,plan_key,title,price,description,active)
            VALUES (?,?,?,?,?,1) ON CONFLICT(guild,plan_key)
            DO UPDATE SET title=excluded.title,price=excluded.price,
                          description=excluded.description,active=1""",
            (guild,key,title[:50],price[:60],description[:160]))
