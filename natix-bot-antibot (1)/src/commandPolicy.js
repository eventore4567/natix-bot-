// Politique d'accès des commandes slash.
//
// RÈGLE : une commande listée ici est PUBLIQUE (aucun default_member_permissions → visible et
// utilisable par @everyone, dans les salons où Discord autorise les commandes d'application).
// TOUTE autre commande DOIT déclarer setDefaultMemberPermissions(...) : sinon le bot refuse de
// démarrer (voir commandRegistry.validate) pour qu'une commande de gestion ne devienne jamais
// publique par oubli.
const PUBLIC_COMMANDS = ['aide', 'userinfo', 'serverinfo', 'invites'];

module.exports = { PUBLIC_COMMANDS };
