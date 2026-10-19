const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { modAction, canModerate, reply, parseDuration, formatDuration } = require('../utils');
const { emoji } = require('../emojis');

const MAX = 28 * 864e5; // limite Discord : 28 jours

module.exports = [
  {
    data: new SlashCommandBuilder().setName('mute').setDescription('Rendre muet un membre (timeout)')
      .addUserOption(o => o.setName('membre').setDescription('Le membre à mute').setRequired(true))
      .addStringOption(o => o.setName('duree').setDescription('Durée : 10m, 1h, 1j... (max 28j)').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison') || 'Aucune raison';
      const ms = parseDuration(i.options.getString('duree'));
      if (!member) return reply(i, 'mute', `${emoji('error')} Ce membre n'est pas sur le serveur.`, true);
      if (!ms || ms > MAX) return reply(i, 'mute', `${emoji('error')} Durée invalide (max 28j). Exemples : \`10m\`, \`1h\`, \`2j\`.`, true);
      const err = canModerate(i, member);
      if (err) return reply(i, 'mute', `${emoji('denied')} ${err}`, true);
      await member.timeout(ms, `${i.user.tag} : ${reason}`);
      await modAction(i.guild, { type: 'mute', target: member.user, moderator: i.user, reason, duration: ms });
      reply(i, 'mute', `${emoji('mute')} **${member.user.tag}** est mute pour **${formatDuration(ms)}**.\n**Raison :** ${reason}`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('unmute').setDescription("Retirer le mute d'un membre")
      .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison') || 'Aucune raison';
      if (!member) return reply(i, 'mute', `${emoji('error')} Ce membre n'est pas sur le serveur.`, true);
      if (!member.isCommunicationDisabled()) return reply(i, 'mute', `${emoji('error')} Ce membre n'est pas mute.`, true);
      await member.timeout(null, `${i.user.tag} : ${reason}`);
      await modAction(i.guild, { type: 'unmute', target: member.user, moderator: i.user, reason });
      reply(i, 'ok', `${emoji('unmute')} **${member.user.tag}** n'est plus mute.`);
    },
  },
];
