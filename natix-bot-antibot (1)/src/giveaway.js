// Système de giveaways : création, participation par bouton, tirage pondéré (VIP x2), reroll, blacklist (+ rôle).
// Tout est stocké dans data/db.json (par serveur : g.gw) et survit aux redémarrages : les boutons restent actifs
// et la fin des giveaways est vérifiée toutes les 15 secondes (voir tick()).
const { ActionRowBuilder, ButtonBuilder, ButtonStyle, MessageFlags } = require('discord.js');
const db = require('./db');
const { embed, sendLog, formatDuration } = require('./utils');
const { emoji, component, localize } = require('./emojis');

const VIP_WEIGHT = 2;                 // un VIP compte pour 2 tickets
const BLACKLIST_ROLE_NAME = 'Blacklist Giveaway';
const KEEP_ENDED_MS = 60 * 864e5;     // les giveaways terminés sont purgés après 60 jours

// ---------- Données ----------
function store(guildId) {
  const g = db.guild(guildId);
  if (!g.gw) g.gw = { seq: 0, items: [], vipRole: null, blacklistRole: null, blacklist: {} };
  g.gw.blacklist ||= {};
  g.gw.items ||= [];
  return g.gw;
}
const findItem = (gw, id) => gw.items.find(x => x.id === id);

// ---------- Logique pure (testée dans test/giveaway.test.js) ----------
// entries : [{ id, weight }] → tire `count` gagnants distincts, chacun avec une probabilité proportionnelle à son poids.
function pickWinners(entries, count, rng = Math.random) {
  const pool = entries.map(e => ({ id: e.id, weight: e.weight }));
  const out = [];
  while (out.length < count && pool.length) {
    const total = pool.reduce((s, e) => s + e.weight, 0);
    let r = rng() * total;
    let idx = 0;
    for (; idx < pool.length - 1; idx++) { r -= pool[idx].weight; if (r < 0) break; }
    out.push(pool.splice(idx, 1)[0].id);
  }
  return out;
}

const isBlacklisted = (gw, member) =>
  !!(gw.blacklist[member.id] || (gw.blacklistRole && member.roles.cache.has(gw.blacklistRole)));

// Rôle VIP : celui configuré avec /giveaway config, sinon un rôle nommé « VIP » (insensible à la casse).
function vipRoleId(guild, gw) {
  if (gw.vipRole && guild.roles.cache.has(gw.vipRole)) return gw.vipRole;
  return guild.roles.cache.find(r => r.name.trim().toLowerCase() === 'vip')?.id ?? null;
}
const weightOf = (member, vipId) => (vipId && member.roles.cache.has(vipId) ? VIP_WEIGHT : 1);

// Participants encore valides : toujours sur le serveur, pas bots, pas blacklistés, pas exclus.
async function eligibleEntries(guild, item, { exclude = [] } = {}) {
  const gw = store(guild.id);
  const vipId = vipRoleId(guild, gw);
  const skip = new Set(exclude);
  const ids = item.entries.filter(id => !skip.has(id));
  const out = [];
  for (let k = 0; k < ids.length; k += 100) {
    const chunk = ids.slice(k, k + 100);
    const members = await guild.members.fetch({ user: chunk }).catch(() => null);
    for (const id of chunk) {
      const m = members?.get(id) ?? guild.members.cache.get(id);
      if (!m || m.user.bot || isBlacklisted(gw, m)) continue;
      out.push({ id, weight: weightOf(m, vipId) });
    }
  }
  return out;
}

// ---------- Affichage ----------
const mentions = ids => ids.map(id => `<@${id}>`).join(', ');

function buildEmbed(item, guild) {
  const gw = store(guild.id);
  const vipId = vipRoleId(guild, gw);
  const e = embed(item.ended ? 'log' : 0xf1c40f, `${emoji('reward')} ${item.prize}`);
  const lines = [
    `**Organisé par :** <@${item.hostId}>`,
    `**Gagnant(s) :** ${item.winnersCount}`,
    item.ended ? `**Terminé :** <t:${Math.floor(item.endedAt / 1000)}:R>` : `**Fin :** <t:${Math.floor(item.endAt / 1000)}:R> (<t:${Math.floor(item.endAt / 1000)}:f>)`,
    `**Participants :** ${item.entries.length}`,
  ];
  if (!item.ended) {
    lines.push('', `Clique sur le bouton pour participer (re-clique pour te retirer).`);
    if (vipId) lines.push(`${emoji('reward')} Les membres <@&${vipId}> ont **${VIP_WEIGHT}× plus de chances** de gagner.`);
  } else {
    lines.push('', item.winners.length ? `${emoji('success')} **Gagnant(s) :** ${mentions(item.winners)}` : `${emoji('error')} Aucun participant valide : pas de gagnant.`);
  }
  e.setDescription(lines.join('\n')).setFooter({ text: `Giveaway #${item.id}` });
  return e;
}

function buildRow(item) {
  const btn = new ButtonBuilder()
    .setCustomId(`gw:join:${item.id}`)
    .setLabel(item.ended ? 'Giveaway terminé' : 'Participer')
    .setStyle(item.ended ? ButtonStyle.Secondary : ButtonStyle.Primary)
    .setDisabled(!!item.ended);
  const em = component('reward');
  if (em) btn.setEmoji(em);
  return new ActionRowBuilder().addComponents(btn);
}

const payloadOf = (item, guild) => ({ embeds: [buildEmbed(item, guild)], components: [buildRow(item)] });

async function getChannel(guild, item) {
  return guild.channels.cache.get(item.channelId) ?? await guild.channels.fetch(item.channelId).catch(() => null);
}
async function getMessage(guild, item) {
  const ch = await getChannel(guild, item);
  if (!ch || !item.messageId) return { ch, msg: null };
  return { ch, msg: await ch.messages.fetch(item.messageId).catch(() => null) };
}

// Met à jour le message (compteur de participants) — regroupé pour ne pas dépasser les limites de Discord.
const refreshTimers = new Map();
function scheduleRefresh(guild, item) {
  if (refreshTimers.has(item.id + ':' + guild.id)) return;
  const key = item.id + ':' + guild.id;
  refreshTimers.set(key, setTimeout(async () => {
    refreshTimers.delete(key);
    const { ch, msg } = await getMessage(guild, item);
    if (msg && !item.ended) msg.edit(localize(payloadOf(item, guild), ch)).catch(() => {});
  }, 5000));
}

// ---------- Actions ----------
async function createGiveaway(guild, channel, { prize, durationMs, winnersCount, host }) {
  const gw = store(guild.id);
  const item = {
    id: ++gw.seq, channelId: channel.id, messageId: null, prize, hostId: host.id, winnersCount,
    createdAt: Date.now(), endAt: Date.now() + durationMs, ended: false, endedAt: null, entries: [], winners: [],
  };
  const msg = await channel.send(localize(payloadOf(item, guild), channel));
  item.messageId = msg.id;
  gw.items.push(item);
  db.save();
  sendLog(guild, embed('info', `${emoji('reward')} Giveaway #${item.id} créé`, `**Lot :** ${prize}\n**Salon :** ${channel}\n**Durée :** ${formatDuration(durationMs)}\n**Par :** ${host}`));
  return item;
}

const ending = new Set();
async function endGiveaway(guild, item, { cancel = false } = {}) {
  const key = guild.id + ':' + item.id;
  if (item.ended || ending.has(key)) return null;
  ending.add(key);
  try {
    item.ended = true;
    item.endedAt = Date.now();
    item.winners = cancel ? [] : pickWinners(await eligibleEntries(guild, item), item.winnersCount);
    db.save();
    const { ch, msg } = await getMessage(guild, item);
    if (cancel) {
      if (msg) await msg.delete().catch(() => {});
      return item;
    }
    if (msg) await msg.edit(localize(payloadOf(item, guild), ch)).catch(() => {});
    if (ch) {
      const text = item.winners.length
        ? `${emoji('reward')} Félicitations ${mentions(item.winners)} ! Vous avez gagné **${item.prize}** !`
        : `${emoji('error')} Giveaway **${item.prize}** terminé : aucun participant valide.`;
      await ch.send(localize({ content: text, allowedMentions: { users: item.winners }, ...(msg ? { reply: { messageReference: msg.id, failIfNotExists: false } } : {}) }, ch)).catch(() => {});
    }
    sendLog(guild, embed('ok', `${emoji('success')} Giveaway #${item.id} terminé`, `**Lot :** ${item.prize}\n**Participants :** ${item.entries.length}\n**Gagnant(s) :** ${item.winners.length ? mentions(item.winners) : 'aucun'}`));
    return item;
  } finally { ending.delete(key); }
}

// Reroll : sans `replace`, tire `count` gagnant(s) supplémentaire(s) ; avec `replace`, remplace ce gagnant.
// Les anciens gagnants ne peuvent jamais être retirés au sort (sauf celui qu'on remplace, qui est lui aussi exclu).
async function rerollGiveaway(guild, item, { count = 1, replace = null } = {}) {
  const previous = [...item.winners, ...(item.rerolled || [])];
  const need = replace ? 1 : count;
  const fresh = pickWinners(await eligibleEntries(guild, item, { exclude: previous }), need);
  if (!fresh.length) return { winners: [] };
  if (replace) { item.winners = item.winners.filter(id => id !== replace); (item.rerolled ||= []).push(replace); }
  item.winners.push(...fresh);
  db.save();
  const { ch, msg } = await getMessage(guild, item);
  if (msg) await msg.edit(localize(payloadOf(item, guild), ch)).catch(() => {});
  if (ch) await ch.send(localize({ content: `${emoji('reward')} Nouveau(x) gagnant(s) pour **${item.prize}** : ${mentions(fresh)} ! Félicitations !`, allowedMentions: { users: fresh }, ...(msg ? { reply: { messageReference: msg.id, failIfNotExists: false } } : {}) }, ch)).catch(() => {});
  sendLog(guild, embed('info', `${emoji('reward')} Reroll du giveaway #${item.id}`, `Nouveau(x) gagnant(s) : ${mentions(fresh)}`));
  return { winners: fresh };
}

// ---------- Blacklist ----------
async function ensureBlacklistRole(guild) {
  const gw = store(guild.id);
  let role = gw.blacklistRole && guild.roles.cache.get(gw.blacklistRole);
  if (!role) role = guild.roles.cache.find(r => r.name === BLACKLIST_ROLE_NAME);
  if (!role) role = await guild.roles.create({ name: BLACKLIST_ROLE_NAME, color: 0x7f8c8d, permissions: [], mentionable: false, reason: 'Rôle de blacklist giveaway' });
  if (gw.blacklistRole !== role.id) { gw.blacklistRole = role.id; db.save(); }
  return role;
}

// Donne le rôle de blacklist. Renvoie un message d'avertissement si impossible (la blacklist reste appliquée par le bot).
async function giveBlacklistRole(guild, member) {
  try {
    if (!guild.members.me?.permissions.has('ManageRoles')) return 'Je n\'ai pas la permission « Gérer les rôles » : le rôle n\'a pas été ajouté (la blacklist est quand même active).';
    const role = await ensureBlacklistRole(guild);
    if (role.position >= guild.members.me.roles.highest.position) return `Le rôle ${role} est au-dessus du mien : monte mon rôle pour que je puisse l'attribuer (la blacklist est quand même active).`;
    if (!member.roles.cache.has(role.id)) await member.roles.add(role, 'Blacklist giveaway');
    return null;
  } catch (e) { return `Rôle non ajouté (${e.message}) : la blacklist est quand même active.`; }
}
async function takeBlacklistRole(guild, member) {
  try {
    const gw = store(guild.id);
    if (gw.blacklistRole && member.roles.cache.has(gw.blacklistRole)) await member.roles.remove(gw.blacklistRole, 'Fin de la blacklist giveaway');
    return null;
  } catch (e) { return `Rôle non retiré (${e.message}) : retire-le à la main.`; }
}

async function blacklistAdd(guild, user, { by, reason }) {
  const gw = store(guild.id);
  gw.blacklist[user.id] = { by: by.id, reason: reason || 'Aucune raison', date: Date.now() };
  // Retire le membre de tous les giveaways en cours
  for (const it of gw.items) if (!it.ended) it.entries = it.entries.filter(id => id !== user.id);
  db.save();
  const member = await guild.members.fetch(user.id).catch(() => null);
  const warning = member ? await giveBlacklistRole(guild, member) : null;
  sendLog(guild, embed('ban', `${emoji('sanction')} Blacklist giveaway`, `${user} (\`${user.id}\`)\n**Raison :** ${gw.blacklist[user.id].reason}\n**Par :** ${by}`));
  return { warning, inGuild: !!member };
}
async function blacklistRemove(guild, user, { by }) {
  const gw = store(guild.id);
  const had = !!gw.blacklist[user.id];
  delete gw.blacklist[user.id];
  db.save();
  const member = await guild.members.fetch(user.id).catch(() => null);
  const hadRole = !!(member && gw.blacklistRole && member.roles.cache.has(gw.blacklistRole));
  const warning = member ? await takeBlacklistRole(guild, member) : null;
  if (had || hadRole) sendLog(guild, embed('ok', `${emoji('unlock')} Fin de blacklist giveaway`, `${user} (\`${user.id}\`)\n**Par :** ${by}`));
  return { had: had || hadRole, warning };
}
// Un blacklisté qui quitte puis revient récupère son rôle.
function onMemberAdd(member) {
  const gw = store(member.guild.id);
  if (gw.blacklist[member.id]) giveBlacklistRole(member.guild, member).catch(() => {});
}

// ---------- Bouton « Participer » ----------
const ephemeral = content => ({ content, flags: MessageFlags.Ephemeral });

async function handleButton(i) {
  const id = Number(i.customId.split(':')[2]);
  const gw = store(i.guild.id);
  const item = findItem(gw, id);
  if (!item || item.ended) return i.reply(ephemeral(`${emoji('error')} Ce giveaway est terminé.`));
  const member = i.member;
  if (isBlacklisted(gw, member)) {
    if (gw.blacklist[member.id]) giveBlacklistRole(i.guild, member).catch(() => {}); // remet le rôle s'il a été retiré
    return i.reply(ephemeral(`${emoji('denied')} Tu es blacklisté des giveaways : tu ne peux pas participer.`));
  }
  const at = item.entries.indexOf(member.id);
  if (at >= 0) {
    item.entries.splice(at, 1);
    db.save();
    scheduleRefresh(i.guild, item);
    return i.reply(ephemeral(`${emoji('success')} Ta participation à **${item.prize}** a été retirée.`));
  }
  item.entries.push(member.id);
  db.save();
  scheduleRefresh(i.guild, item);
  const vip = weightOf(member, vipRoleId(i.guild, gw)) > 1;
  return i.reply(ephemeral(`${emoji('success')} Tu participes à **${item.prize}** !${vip ? `\n${emoji('reward')} Tu es VIP : **${VIP_WEIGHT}× plus de chances** de gagner.` : ''}`));
}

// ---------- Minuteur ----------
async function tick(client) {
  const now = Date.now();
  for (const [guildId] of Object.entries(db.allGuilds())) {
    const gw = db.allGuilds()[guildId].gw;
    if (!gw) continue;
    const guild = client.guilds.cache.get(guildId);
    if (!guild) continue;
    for (const item of gw.items.filter(x => !x.ended && x.endAt <= now)) {
      await endGiveaway(guild, item).catch(e => console.error(`Erreur fin du giveaway #${item.id} :`, e.message));
    }
    const before = gw.items.length;
    gw.items = gw.items.filter(x => !x.ended || now - x.endedAt < KEEP_ENDED_MS);
    if (gw.items.length !== before) db.save();
  }
}

module.exports = {
  VIP_WEIGHT, BLACKLIST_ROLE_NAME, store, findItem, pickWinners, isBlacklisted, vipRoleId, weightOf, eligibleEntries,
  createGiveaway, endGiveaway, rerollGiveaway, blacklistAdd, blacklistRemove, ensureBlacklistRole, onMemberAdd,
  handleButton, tick, buildEmbed, mentions,
};
