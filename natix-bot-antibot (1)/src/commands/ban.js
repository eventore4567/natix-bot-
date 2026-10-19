const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const db = require('../db');
const { modAction, canModerate, reply, parseDuration, formatDuration } = require('../utils');
const { emoji } = require('../emojis');

module.exports = [
  {
    data: new SlashCommandBuilder().setName('ban').setDescription('Bannir un membre')
      .addUserOption(o => o.setName('membre').setDescription('Le membre à bannir').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .addIntegerOption(o => o.setName('supprimer_messages').setDescription('Supprimer ses messages des X derniers jours (0-7)').setMinValue(0).setMaxValue(7))
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers),
    async execute(i) {
      const user = i.options.getUser('membre');
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison') || 'Aucune raison';
      const days = i.options.getInteger('supprimer_messages') || 0;
      const err = canModerate(i, member);
      if (err) return reply(i, 'ban', `${emoji('denied')} ${err}`, true);
      await modAction(i.guild, { type: 'ban', target: user, moderator: i.user, reason });
      await i.guild.members.ban(user.id, { reason: `${i.user.tag} : ${reason}`, deleteMessageSeconds: days * 86400 });
      reply(i, 'ban', `${emoji('sanction')} **${user.tag}** a été banni.\n**Raison :** ${reason}`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('tempban').setDescription('Bannir un membre temporairement')
      .addUserOption(o => o.setName('membre').setDescription('Le membre à bannir').setRequired(true))
      .addStringOption(o => o.setName('duree').setDescription('Durée : 30m, 2h, 7j, 1sem...').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers),
    async execute(i) {
      const user = i.options.getUser('membre');
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison') || 'Aucune raison';
      const ms = parseDuration(i.options.getString('duree'));
      if (!ms) return reply(i, 'ban', `${emoji('error')} Durée invalide. Exemples : \`30m\`, \`2h\`, \`7j\`, \`1sem\`.`, true);
      const err = canModerate(i, member);
      if (err) return reply(i, 'ban', `${emoji('denied')} ${err}`, true);
      await modAction(i.guild, { type: 'tempban', target: user, moderator: i.user, reason, duration: ms });
      await i.guild.members.ban(user.id, { reason: `${i.user.tag} (tempban ${formatDuration(ms)}) : ${reason}` });
      const g = db.guild(i.guild.id);
      g.tempbans = g.tempbans.filter(t => t.userId !== user.id);
      g.tempbans.push({ userId: user.id, until: Date.now() + ms });
      db.save();
      reply(i, 'ban', `${emoji('timer')} **${user.tag}** est banni pour **${formatDuration(ms)}**.\n**Raison :** ${reason}`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('unban').setDescription('Débannir un utilisateur')
      .addStringOption(o => o.setName('id').setDescription("L'ID de l'utilisateur").setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers),
    async execute(i) {
      const id = i.options.getString('id').replace(/\D/g, '');
      const reason = i.options.getString('raison') || 'Aucune raison';
      const ban = await i.guild.bans.fetch(id).catch(() => null);
      if (!ban) return reply(i, 'ban', `${emoji('error')} Cet utilisateur n'est pas banni.`, true);
      await i.guild.members.unban(id, `${i.user.tag} : ${reason}`);
      const g = db.guild(i.guild.id);
      g.tempbans = g.tempbans.filter(t => t.userId !== id);
      db.save();
      await modAction(i.guild, { type: 'unban', target: ban.user, moderator: i.user, reason });
      reply(i, 'ok', `${emoji('unlock')} **${ban.user.tag}** a été débanni.`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('kick').setDescription('Expulser un membre')
      .addUserOption(o => o.setName('membre').setDescription('Le membre à expulser').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison'))
      .setDefaultMemberPermissions(PermissionFlagsBits.KickMembers),
    async execute(i) {
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison') || 'Aucune raison';
      if (!member) return reply(i, 'kick', `${emoji('error')} Ce membre n'est pas sur le serveur.`, true);
      const err = canModerate(i, member);
      if (err) return reply(i, 'kick', `${emoji('denied')} ${err}`, true);
      await modAction(i.guild, { type: 'kick', target: member.user, moderator: i.user, reason });
      await member.kick(`${i.user.tag} : ${reason}`);
      reply(i, 'kick', `${emoji('kick')} **${member.user.tag}** a été expulsé.\n**Raison :** ${reason}`);
    },
  },
];
