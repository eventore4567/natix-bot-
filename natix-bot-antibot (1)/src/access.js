// Résolution « qui peut utiliser quelle commande, où » — fonctions pures (sans discord.js), donc testables.
// Reproduit l'ordre d'évaluation de Discord (documenté) : admin → permission native serveur/salon →
// salons autorisés (Intégrations) → utilisateurs/rôles/@everyone (Intégrations) → permission par défaut de la commande.
// C'est une SIMULATION : si elle diverge de ce que vous voyez dans Discord, c'est Discord qui fait foi.

const FLAGS = { Administrator: 1n << 3n, UseApplicationCommands: 1n << 31n };
const TYPE = { Role: 1, User: 2, Channel: 3 };

const asBig = v => (v == null ? null : BigInt(v));

// Id Discord « tous les salons » = guildId - 1
const allChannelsId = guildId => (BigInt(guildId) - 1n).toString();

// Décision d'un jeu de surcharges pour ce membre : { allowed, source } ou null si rien ne s'applique
function memberDecision(perms, { guildId, userId, roleIds }) {
  if (!perms?.length) return null;
  const user = perms.find(p => p.type === TYPE.User && p.id === userId);
  if (user) return { allowed: user.permission, source: 'user', ids: [user.id] };
  const roles = perms.filter(p => p.type === TYPE.Role && p.id !== guildId && roleIds.includes(p.id));
  const allow = roles.filter(p => p.permission);
  if (allow.length) return { allowed: true, source: 'role', ids: allow.map(p => p.id) };
  const deny = roles.filter(p => !p.permission);
  if (deny.length) return { allowed: false, source: 'role', ids: deny.map(p => p.id) };
  const every = perms.find(p => p.type === TYPE.Role && p.id === guildId);
  if (every) return { allowed: every.permission, source: 'everyone', ids: [guildId] };
  return null;
}

function channelDecision(perms, { guildId, channelId }) {
  if (!perms?.length) return null;
  const ch = perms.find(p => p.type === TYPE.Channel && p.id === channelId);
  if (ch) return { allowed: ch.permission, source: 'channel' };
  const all = perms.find(p => p.type === TYPE.Channel && p.id === allChannelsId(guildId));
  if (all) return { allowed: all.permission, source: 'all-channels' };
  return null;
}

/**
 * @param {object} a
 * @param {string} a.guildId @param {string} a.channelId @param {string} a.userId @param {string[]} a.roleIds
 * @param {boolean} a.isAdmin  administrateur ou propriétaire
 * @param {{guild:boolean, channel:boolean}} a.native  « Utiliser les commandes d'application » (serveur / salon, calculé par discord.js)
 * @param {Array|null} a.commandPerms  surcharges Intégrations propres à la commande
 * @param {Array|null} a.appPerms      surcharges Intégrations valables pour tout le bot
 * @param {bigint|string|null} a.defaultMemberPermissions
 * @param {bigint|string} a.memberPerms permissions serveur du membre
 * @returns {{allowed:boolean, code:string, reason:string}}
 */
function canUseCommand(a) {
  if (a.isAdmin) return { allowed: true, code: 'admin', reason: 'Administrateur : accès à toutes les commandes' };
  if (!a.native.guild) return { allowed: false, code: 'native-guild', reason: "« Utiliser les commandes d'application » est refusé au niveau du serveur" };
  if (!a.native.channel) return { allowed: false, code: 'native-channel', reason: "« Utiliser les commandes d'application » est refusé dans ce salon (salon ou catégorie)" };

  const ctx = { guildId: a.guildId, channelId: a.channelId, userId: a.userId, roleIds: a.roleIds };
  const ch = channelDecision(a.commandPerms, ctx) ?? channelDecision(a.appPerms, ctx);
  if (ch && !ch.allowed) return { allowed: false, code: 'integration-channel', reason: 'Salon non autorisé dans Paramètres du serveur → Intégrations' };

  const m = memberDecision(a.commandPerms, ctx) ?? memberDecision(a.appPerms, ctx);
  if (m) {
    const where = { user: 'ce membre', role: 'un de ses rôles', everyone: '@everyone' }[m.source];
    return m.allowed
      ? { allowed: true, code: 'integration-allow', reason: `Autorisé dans Intégrations pour ${where}` }
      : { allowed: false, code: 'integration-deny', reason: `Refusé dans Intégrations pour ${where}` };
  }

  const need = asBig(a.defaultMemberPermissions);
  if (need == null) return { allowed: true, code: 'public', reason: 'Commande publique' };
  if ((asBig(a.memberPerms) & need) === need) return { allowed: true, code: 'has-perm', reason: 'Possède la permission requise' };
  return { allowed: false, code: 'default-perms', reason: 'Permission requise manquante (commande de gestion)' };
}

module.exports = { canUseCommand, memberDecision, channelDecision, allChannelsId, FLAGS, TYPE };
