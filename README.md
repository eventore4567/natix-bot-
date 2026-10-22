# NATIX SHOP — simple boutique Discord

Ce bot est une **boutique Discord** indépendante de SentriX. La navigation reprend les rubriques des captures de référence : Accueil, Boutique, Support, Giveaways, Statistiques, Réseaux, Règlement.

## Seulement 9 commandes principales

- /home : accueil NATIX et panneaux de services
- /shop : catégories Nitro Boost, Décorations, Server Boost, Custom Bots et Fastfood
- /support : tickets, signalements et candidatures
- /giveaway : panneau avec les concours actifs
- /stats : chiffres réels de la boutique
- /social : liens officiels configurés
- /rules : règlement affiché sur un panneau
- /setup : rôle staff, catégorie tickets, salon de transcripts privé
- /manage : regroupement de la gestion (produits, stocks, commandes, concours, liens, règlement, archivage)

Les autres systèmes (commandes, tickets, échange et promotion) fonctionnent via **boutons et menus dans les panneaux** au lieu d'ajouter des commandes slash inutiles.

La commande /emojis est supprimée et le générateur d'emojis personnalisés n'est plus proposé.

## Première installation

1. Exécuter /setup avec le rôle staff, la catégorie tickets et le salon de logs **privé**.
2. Ajouter des articles avec /manage add, puis vérifier avec /manage products.
3. Publier /home, /shop et /support dans les salons appropriés.
4. Créer les concours avec /manage giveaway, afficher le panneau /giveaway.
5. Configurer les réseaux avec /manage social. Modifier le règlement avec /manage rules.

## Conception

- Bandeau NATIX 1400×420 noir, gris et blanc, avec lettrage vectoriel central lisible à grande taille. Il ne dépend d'aucune police externe sur Railway.
- Discord Components V2 : MediaGallery, Container, Section, Select, boutons latéraux.
- Les commandes admin exigent la permission Gérer le serveur. Les tickets et commandes sont privés.
- Pas de paiements automatiques, pas de pings massifs et pas de gains fictifs.
- Pas de génération d'emojis personnalisés.
- /manage delete_ticket archive le transcript complet dans le salon de logs privé avant suppression.
- La suppression des anciennes commandes **globales** se fait pendant la synchronisation au démarrage. Les anciennes commandes propres à un serveur sont également nettoyées. Il peut être nécessaire de relancer Discord pour rafraîchir l'affichage local.

## Railway

Variables : DISCORD_TOKEN requis ; DISCORD_GUILD_ID facultatif. Base SQLite persistante dans /data/natix.sqlite grâce au volume Railway déjà configuré. Démarrage : python main.py.

L'ancien code IA, ses commandes et sa clé OpenAI ne sont plus utilisés par cette version boutique. Retirer les variables obsolètes si elles ne servent plus à aucun autre service et renouveler les secrets potentiellement exposés.

GitHub Actions vérifie la syntaxe, l'interface, la taille réelle du logo, les permissions, les commandes utiles et les transitions de stocks.
