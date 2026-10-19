// Ajout d'un warn + sanctions automatiques selon les seuils
const db = require('./db');
const { modAction } = require('./utils');

// Rôles "Warn 1", "Warn 2"... : le membre n'a toujours que le rôle correspondant à son nombre de warns
const WARN_ROLE = /^Warn (\d+)$/;

async function syncWarnRole(guild, member, count) {
  try {
    if (!member || !guild.members.me?.permissions.has('ManageRoles')) return;
    // Retire les anciens rôles Warn
    const old = member.roles.cache.filter(r => WARN_ROLE.test(r.name) && r.name !== `Warn ${count}`);
    if (old.size) await member.roles.remove(old, 'Mise à jour des warns');
    if (count <= 0) return;
    const name = `Warn ${count}`;
    let role = guild.roles.cache.find(r => r.name === name);
    if (!role) role = await guild.roles.create({ name, color: 0xf39c12, permissions: [], mentionable: false, reason: 'Rôle de warn automatique' });
    if (role.position >= guild.members.me.roles.highest.position) return console.error(`Rôle "${name}" au-dessus du bot : impossible de l'attribuer.`);
    if (!member.roles.cache.has(role.id)) await member.roles.add(role, `${count} warn(s)`);
  } catch (e) {
    console.error('Rôle de warn impossible :', e.message);
  }
}

async function addWarn(guild, member, moderator, reason) {
  const g = db.guild(guild.id);
  if (!g.warns[member.id]) g.warns[member.id] = [];
  g.warns[member.id].push({ reason: reason || 'Aucune raison', mod: moderator ? moderator.id : 'AutoMod', date: Date.now() });
  db.save();

  const count = g.warns[member.id].length;
  await syncWarnRole(guild, member, count);
  await modAction(guild, { type: 'warn', target: member.user, moderator, reason: `${reason || 'Aucune raison'} (warn n°${count})` });

  // Sanction automatique selon le nombre de warns
  const t = g.config.warnThresholds;
  let auto = null;
  try {
    if (t.ban && count === t.ban && member.bannable) {
      await modAction(guild, { type: 'ban', target: member.user, moderator: null, reason: `${count} avertissements atteints` });
      await member.ban({ reason: `AutoMod : ${count} warns` });
      auto = 'banni';
    } else if (t.kick && count === t.kick && member.kickable) {
      await modAction(guild, { type: 'kick', target: member.user, moderator: null, reason: `${count} avertissements atteints` });
      await member.kick(`AutoMod : ${count} warns`);
      auto = 'expulsé';
    } else if (t.mute && count === t.mute && member.moderatable) {
      const d = g.config.warnMuteMinutes * 60e3;
      await member.timeout(d, `AutoMod : ${count} warns`);
      await modAction(guild, { type: 'mute', target: member.user, moderator: null, reason: `${count} avertissements atteints`, duration: d });
      auto = 'mute';
    }
  } catch (e) {
    console.error('Sanction auto impossible :', e.message);
  }
  return { count, auto };
}

module.exports = { addWarn, syncWarnRole };
