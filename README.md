# NATIX — boutique Discord premium

NATIX est un bot de **boutique Discord** construit entièrement en **Components V2** :
panneaux sombres avec bannière NATIX, vignette logo, menus déroulants, boutons latéraux et
emojis personnalisés. Tout se passe dans les panneaux ; il n'y a que **5 commandes slash**,
réservées au staff.

## Commandes

| Commande | Rôle |
| --- | --- |
| `/setup` | Tableau de bord : salons & rôles, identité, textes, réseaux, catégories, plans promo, restock, rafraîchissement des panneaux |
| `/panel` | Publier un panneau : Accueil, Boutique, Échanges, Promotions, Support, Avis (Are we legit?), Règlement, Réseaux |
| `/product` | `add` · `edit` · `stock` · `remove` · `list` (avec autocomplétion) |
| `/giveaway` | `start` · `end` · `reroll` |
| `/orders` | Suivi des commandes (filtre client / statut) |

Au démarrage, NATIX remplace toutes les anciennes commandes globales et supprime les anciennes
commandes propres à chaque serveur : plus de doublons ni de `/emojis`.

## Panneaux (fidèles aux captures de référence)

- **Shop** — « Welcome To NATIX Shop », menu *Pick a category* (Nitro Boost, Discord Decoration,
  Server Boost, Custom Bots, Fastfood, Other, *Resélectionner*). Le client reçoit en privé la
  catégorie, choisit un produit (*Pick a product* : `10€ · description`), voit prix et stock, puis
  clique **Commander** → formulaire (quantité, infos) → ticket de commande privé.
- **Exchange** — *Start A Trade* (formulaire → ticket d'échange) et *Previous Trades*.
- **Promotion Slots** — Inclus, plans (Basic, Standard, Premium, Lifetime) avec bouton latéral qui
  ouvre un ticket, et « Comment ça marche ». Plans modifiables dans `/setup`.
- **Support** — menu *Pick a reason* → formulaire → ticket privé.
- **Are we legit?** — votes ✅ / ❌ comptés en direct, *Laisser un avis* (note /5 + commentaire,
  publié dans le salon des avis) et *Voir les avis* (moyenne, répartition, derniers avis).
- **Giveaways** — lot, nombre de gagnants, *Ends dans …*, boutons *Enter (n)* et *Participants*,
  fin automatique, tirage aléatoire sécurisé, annonce des gagnants.
- **Accueil**, **Règlement**, **Réseaux** — configurables depuis `/setup`.
- **Restock** — `/product stock` annonce « Restock ! · +3 ajouté · Voir la catégorie » (mention
  configurable : aucune, @here ou @everyone).

## Tickets

Prendre en charge · Ajouter un membre · Fermer · Rouvrir · Transcript · Supprimer (le transcript
est archivé dans le salon privé avant suppression). Les tickets de commande ont en plus
**Accepter / Livrée / Annuler**, réservés au staff.

Tous les boutons utilisent des identifiants fixes et l'état est en base : panneaux et tickets
restent fonctionnels après un redémarrage.

## Stock et commandes

Le stock est **réservé à la création de la commande** (impossible de vendre plus que le stock),
rendu **une seule fois** si la commande est annulée, et jamais débité deux fois. `-1` = illimité.

## Installation

1. `/setup` → **Salons & rôles** : rôle staff, catégorie des tickets, salon de transcripts
   (privé), salon des avis, salon des promotions. Puis **Restock** si besoin.
2. `/product add` pour chaque produit (catégorie, nom, prix, stock, description).
3. `/panel` pour publier chaque panneau dans son salon.
4. Après une modification (catégories, plans, textes), les panneaux publiés se mettent à jour
   automatiquement ; le bouton **Rafraîchir les panneaux** force la mise à jour.

Permissions du bot : Voir les salons, Envoyer des messages, Joindre des fichiers, Intégrer des
liens, Gérer les salons, Gérer les permissions (sur la catégorie des tickets), Lire l'historique.

## Railway

- `DISCORD_TOKEN` (obligatoire). `DISCORD_GUILD_ID` (facultatif : commandes instantanées sur un
  serveur de test ; les commandes globales sont alors vidées pour éviter les doublons).
- Base SQLite persistante : `/data/natix.sqlite` (volume Railway). Les anciennes tables sont
  migrées automatiquement.
- `NATIX_APP_EMOJIS=0` désactive l'envoi des icônes en emojis d'application (Unicode à la place).

## Visuels et emojis

- Bannières 1500×500 noir/blanc (feuillages au pinceau, trame manga, lignes de vitesse, katakana),
  **NATIX** centré en grand : `assets/banners/`. Logo vignette : `assets/banners/logo.png`.
- Icônes au trait (style des captures) envoyées automatiquement comme **emojis d'application** :
  elles appartiennent au bot, n'occupent aucun emplacement d'emoji du serveur et n'ajoutent
  aucune commande.
- Régénérer les visuels : `pip install cairosvg && python tools/build_assets.py`.
  Licences des polices et icônes : `assets/LICENSES.md`.

## Tests

```
python -m unittest discover -s tests -v
```

Les tests couvrent la base (stock, migrations, tickets, votes, giveaways), la validité de chaque
panneau (limites Discord), le routeur, les parcours complets (commande, ticket, échange, promo,
avis, giveaway, configuration) et les commandes slash.
