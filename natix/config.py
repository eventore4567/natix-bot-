"""Constantes NATIX : réglages par défaut, catégories, plans et types de tickets."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BANNERS = ASSETS / "banners"
EMOJI_DIR = ASSETS / "emojis"

# Couleur d'accent des conteneurs (gris anthracite, comme les captures).
ACCENT = None

DEFAULT_SETTINGS = {
    "name": "NATIX",
    "currency": "€",
    "tos_url": "",
    "banner_url": "",
    "staff": 0,
    "category": 0,          # catégorie Discord des tickets
    "logs": 0,              # salon privé des transcripts
    "restock_channel": 0,
    "restock_ping": "none",  # none | here | everyone
    "reviews_channel": 0,
    "promo_channel": 0,
    "ticket_counter": 0,
    "shop_tagline": "we make ordering simple and safe.",
    "exchange_tagline": "we make all kind of trades simple and safe.",
    "support_tagline": "our team answers every request in a private ticket.",
    "home_tagline": "premium Discord services, delivered fast and safe.",
    "rules": (
        "Les paiements se font uniquement dans un ticket, avec un membre du staff.\n"
        "Ne partage jamais ton mot de passe, ton token ou un code de connexion.\n"
        "Une commande est confirmée uniquement après validation du staff.\n"
        "Aucun remboursement après livraison, sauf erreur de notre part.\n"
        "Tout abus, insulte ou tentative d'arnaque entraîne un bannissement."
    ),
    "promo_included": "Salon privé à ton nom\nPings selon le plan\nPub validée par le staff",
    "promo_steps": "Clique sur le plan\nPaie dans le ticket\nEnvoie ta pub · validation staff",
    "legit_no": "No (ban sans preuve)",
    "social_discord": "",
    "social_tiktok": "",
    "social_instagram": "",
    "social_youtube": "",
    "social_site": "",
    # Paiements
    "paypal": "",          # pseudo PayPal.me ou lien https://paypal.me/…
    "paypal_email": "",
    "pay_note": "Indique ton pseudo Discord dans la note du paiement.",
    "pay_other": "",
}

# key, nom, emoji (nom d'emoji NATIX), description
DEFAULT_CATEGORIES = [
    ("nitro", "Nitro Boost", "nx_nitro", "Abonnements Nitro Boost."),
    ("decor", "Discord Decoration", "nx_decor", "Décorations d'avatar et effets de profil."),
    ("boost", "Server Boost", "nx_boost", "Boosts pour ton serveur Discord."),
    ("bots", "Custom Bots", "nx_bots", "Bots Discord sur mesure."),
    ("food", "Fastfood", "nx_food", "Commandes fastfood."),
    ("other", "Other", "nx_other", "Autres services."),
]

# key, titre, prix (centimes), durée, pings, emoji
DEFAULT_PLANS = [
    ("basic", "Basic", 1000, "7 jours", "`@here` tous les 3j", "nx_dollar"),
    ("standard", "Standard", 2000, "14 jours", "`@everyone` tous les 6j", "nx_dollar"),
    ("premium", "Premium", 3000, "21 jours", "`@here` tous les 3j · `@everyone` tous les 6j", "nx_food"),
    ("lifetime", "Lifetime", 4500, "À vie", "`@here` tous les 4j · `@everyone` tous les 7j", "nx_gift"),
]

TICKET_KINDS = {
    "support": ("Support", "nx_info", "Une question ou un problème."),
    "order_help": ("Problème de commande", "nx_box", "Suivi ou souci avec une commande."),
    "partner": ("Partenariat", "nx_link", "Proposer un partenariat."),
    "report": ("Signalement", "nx_shield", "Signaler un membre ou une arnaque."),
    "apply": ("Candidature", "nx_crown", "Rejoindre l'équipe NATIX."),
    # Types ouverts par les autres panneaux
    "order": ("Commande", "nx_cart", ""),
    "trade": ("Échange", "nx_trade", ""),
    "promo": ("Promotion", "nx_megaphone", ""),
}

ORDER_STATES = {
    "pending": "En attente",
    "accepted": "Acceptée",
    "delivered": "Livrée",
    "cancelled": "Annulée",
}

PANEL_KINDS = {
    "home": "Accueil",
    "shop": "Boutique",
    "exchange": "Échanges",
    "promo": "Promotions",
    "support": "Support",
    "reviews": "Avis clients (Are we legit?)",
    "rules": "Règlement",
    "social": "Réseaux",
    "paypal": "PayPal / Paiement",
}
