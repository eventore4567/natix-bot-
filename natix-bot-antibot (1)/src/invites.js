// Invite tracker : sait QUELLE invitation (donc QUEL membre) a amené chaque arrivant.
//
// Principe : on garde en mémoire le nombre d'utilisations de chaque invitation du serveur. À chaque arrivée on relit
// les invitations et celle dont le compteur a augmenté est celle qui a été utilisée. Cas particuliers gérés :
// invitation à usage limité supprimée par Discord juste après usage, lien personnalisé (vanity), arrivées simultanées
// (traitées l'une après l'autre), invitation introuvable (OAuth, découverte...), retour d'un ancien membre.
//
// Les données sont dans data/db.json (par serveur : g.inv) et survivent aux redémarrages :
//   stats[inviterId] = { regular, left, fake, bonus }   joins[memberId] = { inviterId, code, type, at, left }
//   Total affiché = regular + bonus - left   (les « fake » = comptes trop récents ne comptent pas)
const db = require('./db');
const { embed } = require('./utils');
const { emoji, localize } = require('./emojis');

const DEFAULT_MIN_AGE_DAYS = 7;
const DELETED_GRACE_MS = 15e3;   // une invitation supprimée il y a moins de 15 s peut encore être celle qui vient d'être utilisée

// ---------- Données ----------
function store(guildId) {
  const g = db.guild(guildId);
  g.inv ||= {};
  const inv = g.inv;
  inv.enabled ??= true;
  inv.channel ??= null;
  inv.minAgeDays ??= DEFAULT_MIN_AGE_DAYS;
  inv.stats ||= {};
  inv.joins ||= {};
  return inv;
}
const statsOf = (inv, id) => (inv.stats[id] ||= { regular: 0, left: 0, fake: 0, bonus: 0 });
const total = s => Math.max(0, s.regular + s.bonus - s.left);
function getStats(guildId, userId) {
  const s = { ...statsOf(store(guildId), userId) };
  return { ...s, total: total(s) };
}
function leaderboard(guildId, limit = 10) {
  const inv = store(guildId);
  return Object.entries(inv.stats)
    .map(([id, s]) => ({ id, ...s, total: total(s) }))
    .filter(r => r.total > 0 || r.regular > 0)
    .sort((a, b) => b.total - a.total || b.regular - a.regular)
    .slice(0, limit);
}
const inviterOf = (guildId, memberId) => store(guildId).joins[memberId] ?? null;

function addBonus(guildId, userId, n) {
  const s = statsOf(store(guildId), userId);
  s.bonus += n;
  db.save();
  return getStats(guildId, userId);
}
function resetUser(guildId, userId) {
  const inv = store(guildId);
  delete inv.stats[userId];
  // Les arrivées déjà attribuées à ce membre ne comptent plus pour lui.
  for (const j of Object.values(inv.joins)) if (j.inviterId === userId) j.inviterId = null;
  db.save();
}
function resetAll(guildId) {
  const inv = store(guildId);
  inv.stats = {};
  inv.joins = {};
  db.save();
}

// ---------- Logique pure (testée dans test/invites.test.js) ----------
// before : Map code → { uses, inviterId, maxUses, deletedAt? }   after : [{ code, uses, inviterId, maxUses }]
// Renvoie { code, inviterId } si UNE seule invitation correspond, sinon { code: null } (inconnue ou ambiguë).
function detectUsed(before, after, now = Date.now()) {
  const afterMap = new Map(after.map(i => [i.code, i]));
  const candidates = [];
  for (const i of after) {
    if (i.uses > (before.get(i.code)?.uses ?? 0)) candidates.push(i);
    else if (!before.has(i.code) && i.uses > 0) candidates.push(i); // créée et utilisée pendant que le bot ne regardait pas
  }
  for (const [code, old] of before) {
    if (afterMap.has(code)) continue;
    if (old.deletedAt && now - old.deletedAt > DELETED_GRACE_MS) continue;   // supprimée depuis longtemps : sans rapport
    if (old.maxUses > 0 && old.uses + 1 >= old.maxUses) candidates.push({ code, inviterId: old.inviterId }); // dernier usage, Discord l'a supprimée
  }
  if (candidates.length === 1) return { code: candidates[0].code, inviterId: candidates[0].inviterId ?? null };
  return { code: null, inviterId: null, ambiguous: candidates.length > 1 };
}

// ---------- Cache des invitations (en mémoire) ----------
const cache = new Map();   // guildId → Map(code → { uses, inviterId, maxUses, deletedAt? })
const warned = new Set();
const queues = new Map();  // sérialise le traitement par serveur

const toEntry = i => ({ uses: i.uses ?? 0, inviterId: i.inviter?.id ?? i.inviterId ?? null, maxUses: i.maxUses ?? 0 });
const toMap = list => new Map(list.map(i => [i.code, toEntry(i)]));

async function fetchInvites(guild) {
  try {
    const col = await guild.invites.fetch();
    return [...col.values()].map(i => ({ code: i.code, ...toEntry(i) }));
  } catch (e) {
    if (!warned.has(guild.id)) {
      warned.add(guild.id);
      console.warn(`⚠️ [${guild.name}] Invite tracker : impossible de lire les invitations (${e.message}). Donne au bot la permission « Gérer le serveur ».`);
    }
    return null;
  }
}

async function refresh(guild) {
  const list = await fetchInvites(guild);
  if (list) { cache.set(guild.id, toMap(list)); warned.delete(guild.id); }
  return !!list;
}

const enqueue = (guildId, fn) => {
  const next = (queues.get(guildId) ?? Promise.resolve()).catch(() => {}).then(fn);
  queues.set(guildId, next);
  return next;
};

function onInviteCreate(invite) {
  if (!invite.guild) return;
  const c = cache.get(invite.guild.id) ?? new Map();
  c.set(invite.code, toEntry(invite));
  cache.set(invite.guild.id, c);
}
function onInviteDelete(invite) {
  const e = cache.get(invite.guild?.id)?.get(invite.code);
  if (e) e.deletedAt = Date.now();   // gardée un court instant : peut être l'invitation à usage unique qui vient de servir
}

// ---------- Arrivée / départ ----------
// Renvoie { type: 'regular'|'fake'|'vanity'|'unknown'|'self'|'bot', inviterId, code, total } ou null si le suivi est coupé.
function onMemberAdd(member) {
  const guild = member.guild;
  const inv = store(guild.id);
  if (!inv.enabled) return Promise.resolve(null);
  return enqueue(guild.id, async () => {
    const before = cache.get(guild.id);   // undefined = jamais chargé : on ne devine rien, on mémorise seulement
    const after = await fetchInvites(guild);
    let used = { code: null, inviterId: null };
    if (after) {
      if (before) used = detectUsed(before, after);
      cache.set(guild.id, toMap(after));
    }

    // Un ancien membre qui revient : si son départ n'avait pas été vu (bot hors ligne), on le rattrape avant d'écraser.
    const old = inv.joins[member.id];
    if (old && !old.left && old.type === 'regular' && old.inviterId) statsOf(inv, old.inviterId).left++;

    let type, inviterId = used.inviterId;
    if (member.user.bot) { type = 'bot'; inviterId = null; }
    else if (used.code && inviterId === member.id) { type = 'self'; inviterId = null; }
    else if (used.code && inviterId) {
      const tooYoung = Date.now() - member.user.createdTimestamp < inv.minAgeDays * 864e5;
      type = tooYoung ? 'fake' : 'regular';
      statsOf(inv, inviterId)[type === 'fake' ? 'fake' : 'regular']++;
    } else if (used.code) type = 'unknown';            // invitation dont l'auteur est inconnu (supprimé...)
    else if (guild.vanityURLCode && !used.ambiguous) type = 'vanity';
    else type = 'unknown';

    inv.joins[member.id] = { inviterId, code: used.code, type, at: Date.now(), left: false };
    db.save();
    return { type, inviterId, code: used.code, total: inviterId ? getStats(guild.id, inviterId).total : 0 };
  });
}

// Départ : l'invitation est retirée du total de celui qui l'avait invité.
function onMemberRemove(member) {
  const inv = store(member.guild.id);
  const j = inv.joins[member.id];
  if (!j || j.left) return null;
  j.left = true;
  if (j.type === 'regular' && j.inviterId) statsOf(inv, j.inviterId).left++;
  db.save();
  return { type: j.type, inviterId: j.inviterId, code: j.code, total: j.inviterId ? getStats(member.guild.id, j.inviterId).total : 0 };
}

// ---------- Affichage ----------
const who = info => ({
  regular: info.inviterId ? `invité par <@${info.inviterId}> (**${info.total}** invitation${info.total > 1 ? 's' : ''})` : 'invitation inconnue',
  fake: info.inviterId ? `invité par <@${info.inviterId}> — compte trop récent, **non compté**` : 'invitation inconnue',
  vanity: 'via le lien personnalisé du serveur',
  self: 'via sa propre invitation (non compté)',
  bot: 'bot ajouté au serveur',
  unknown: 'invitation introuvable',
}[info.type]);

// Message dans le salon dédié (/invitetracker salon), si défini et différent du salon de logs.
async function announce(guild, kind, member, info) {
  const inv = store(guild.id);
  if (!inv.channel || inv.channel === db.guild(guild.id).config.logChannel) return;
  const ch = guild.channels.cache.get(inv.channel);
  if (!ch) return;
  const e = kind === 'join'
    ? embed('ok', `${emoji('join')} Nouveau membre`, `${member} a rejoint, ${who(info)}.`)
    : embed('ban', `${emoji('leave')} Départ`, `**${member.user.tag}** a quitté${info.inviterId ? `, il avait été invité par <@${info.inviterId}> (**${info.total}** invitation${info.total > 1 ? 's' : ''} restantes)` : ''}.`);
  await ch.send(localize({ embeds: [e] }, ch)).catch(() => {});
}

module.exports = {
  store, getStats, leaderboard, inviterOf, addBonus, resetUser, resetAll,
  detectUsed, refresh, onInviteCreate, onInviteDelete, onMemberAdd, onMemberRemove, announce, who,
  DEFAULT_MIN_AGE_DAYS,
};
