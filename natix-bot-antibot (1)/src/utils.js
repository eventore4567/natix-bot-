const { EmbedBuilder, PermissionFlagsBits, MessageFlags } = require('discord.js');
const db = require('./db');
const { emoji, localize } = require('./emojis');

const COLORS = { ban: 0xe74c3c, kick: 0xe67e22, mute: 0xf1c40f, warn: 0xf39c12, ok: 0x2ecc71, info: 0x3498db, log: 0x95a5a6 };

// "10m", "2h", "7j", "1d", "30s", "1sem" -> millisecondes
function parseDuration(str) {
  if (!str) return null;
  const m = String(str).trim().toLowerCase().match(/^(\d+)\s*(s|sec|m|min|h|j|d|sem|w)$/);
  if (!m) return null;
  const n = parseInt(m[1], 10);
  const mult = { s: 1e3, sec: 1e3, m: 6e4, min: 6e4, h: 36e5, j: 864e5, d: 864e5, sem: 6048e5, w: 6048e5 }[m[2]];
  return n * mult;
}

function formatDuration(ms) {
  const parts = [];
  const units = [['j', 864e5], ['h', 36e5], ['min', 6e4], ['s', 1e3]];
  for (const [u, v] of units) {
    const q = Math.floor(ms / v);
    if (q) { parts.push(q + u); ms -= q * v; }
  }
  return parts.join(' ') || '0s';
}

function embed(color, title, desc) {
  const e = new EmbedBuilder().setColor(COLORS[color] ?? color).setTimestamp();
  if (title) e.setTitle(title);
  if (desc) e.setDescription(desc);
  return e;
}

async function sendLog(guild, emb) {
  const cfg = db.guild(guild.id).config;
  if (!cfg.logChannel) return;
  const ch = guild.channels.cache.get(cfg.logChannel);
  if (ch) await ch.send(localize({ embeds: [emb] }, ch)).catch(() => {});
}

// Enregistre une sanction : MP au membre + log + numéro de cas
async function modAction(guild, { type, target, moderator, reason, duration }) {
  const g = db.guild(guild.id);
  g.caseId = (g.caseId || 0) + 1;
  db.save();

  const labels = {
    ban: `${emoji('sanction')} Bannissement`, tempban: `${emoji('timer')} Ban temporaire`, unban: `${emoji('unlock')} Débannissement`,
    kick: `${emoji('kick')} Expulsion`, mute: `${emoji('mute')} Mute`, unmute: `${emoji('unmute')} Unmute`, warn: `${emoji('warning')} Avertissement`,
  };
  const color = { tempban: 'ban', unban: 'ok', unmute: 'ok' }[type] || type;

  const e = embed(color, `${labels[type]} • Cas #${g.caseId}`)
    .addFields(
      { name: 'Membre', value: `${target.tag ?? target.username} (\`${target.id}\`)`, inline: true },
      { name: 'Modérateur', value: moderator ? `${moderator.tag ?? moderator.username}` : 'AutoMod', inline: true },
      { name: 'Raison', value: reason || 'Aucune raison' },
    );
  if (duration) e.addFields({ name: 'Durée', value: formatDuration(duration), inline: true });
  await sendLog(guild, e);

  // MP au membre (pas pour unban)
  if (type !== 'unban') {
    const dm = embed(color, `${labels[type]} sur ${guild.name}`)
      .addFields({ name: 'Raison', value: reason || 'Aucune raison' });
    if (duration) dm.addFields({ name: 'Durée', value: formatDuration(duration) });
    await target.send?.({ embeds: [dm] }).catch(() => {});
  }
  return g.caseId;
}

// Vérifie qu'on peut sanctionner ce membre (hiérarchie des rôles)
function canModerate(interaction, member) {
  if (!member) return null;
  if (member.id === interaction.user.id) return 'Tu ne peux pas te sanctionner toi-même.';
  if (member.id === interaction.client.user.id) return 'Je ne peux pas me sanctionner moi-même.';
  if (member.id === interaction.guild.ownerId) return 'Impossible de sanctionner le propriétaire du serveur.';
  const me = interaction.guild.members.me;
  if (member.roles.highest.position >= me.roles.highest.position) return 'Ce membre a un rôle supérieur ou égal au mien. Monte mon rôle dans les paramètres du serveur.';
  if (interaction.user.id !== interaction.guild.ownerId && member.roles.highest.position >= interaction.member.roles.highest.position) return 'Ce membre a un rôle supérieur ou égal au tien.';
  return null;
}

function isBypassed(member) {
  if (!member) return false;
  if (member.permissions.has(PermissionFlagsBits.Administrator) || member.permissions.has(PermissionFlagsBits.ManageMessages)) return true;
  const cfg = db.guild(member.guild.id).config;
  return member.roles.cache.some(r => cfg.bypassRoles.includes(r.id));
}

const reply = (i, color, text, ephemeral = false) =>
  i.reply({ embeds: [embed(color, null, text)], flags: ephemeral ? MessageFlags.Ephemeral : undefined });

module.exports = { parseDuration, formatDuration, embed, sendLog, modAction, canModerate, isBypassed, reply, COLORS };
