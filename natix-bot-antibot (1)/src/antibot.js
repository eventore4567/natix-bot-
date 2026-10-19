// Anti-bot : quand il est activé (/unbot activate), tout BOT qui rejoint le serveur est expulsé automatiquement.
// Ne touche jamais au bot lui-même. Journalise dans le salon de logs (avec l'ajouteur si le journal d'audit est lisible).
const { AuditLogEvent } = require('discord.js');
const db = require('./db');
const { embed, sendLog } = require('./utils');
const { emoji } = require('./emojis');

const isEnabled = guildId => !!db.guild(guildId).config.antiBot;

function setEnabled(guildId, on) {
  db.guild(guildId).config.antiBot = !!on;
  db.save();
}

// Qui a ajouté le bot ? (nécessite « Voir les logs du serveur », sinon null)
async function findAdder(member) {
  try {
    const logs = await member.guild.fetchAuditLogs({ type: AuditLogEvent.BotAdd, limit: 5 });
    const entry = logs.entries.find(e => e.targetId === member.id && Date.now() - e.createdTimestamp < 60e3);
    return entry?.executor ?? null;
  } catch { return null; }
}

// À appeler sur GuildMemberAdd. Renvoie true si le bot a été expulsé.
async function onMemberAdd(member) {
  if (!member.user?.bot) return false;
  if (member.id === member.client?.user?.id) return false;
  if (!isEnabled(member.guild.id)) return false;

  const adder = await findAdder(member);
  try {
    await member.kick("Anti-bot activé : l'ajout de bots est interdit");
  } catch (e) {
    sendLog(member.guild, embed('warn', `${emoji('warning')} Anti-bot : expulsion impossible`,
      `Le bot **${member.user.tag}** (\`${member.id}\`) a rejoint mais je n'ai pas pu l'expulser (${e.message}).\nVérifie ma permission « Expulser des membres » et que mon rôle est au-dessus du sien.`));
    return false;
  }
  sendLog(member.guild, embed('kick', `${emoji('security')} Anti-bot : bot expulsé`)
    .addFields(
      { name: 'Bot', value: `${member.user.tag} (\`${member.id}\`)`, inline: true },
      { name: 'Ajouté par', value: adder ? `${adder} (\`${adder.id}\`)` : 'Inconnu', inline: true },
    ));
  return true;
}

module.exports = { isEnabled, setEnabled, onMemberAdd };
