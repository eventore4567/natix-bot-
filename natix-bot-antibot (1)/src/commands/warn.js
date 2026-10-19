const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const db = require('../db');
const { canModerate, reply, embed } = require('../utils');
const { addWarn, syncWarnRole } = require('../warns');
const { emoji } = require('../emojis');

module.exports = [
  {
    data: new SlashCommandBuilder().setName('warn').setDescription('Avertir un membre')
      .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
      .addStringOption(o => o.setName('raison').setDescription('La raison').setRequired(true))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const member = i.options.getMember('membre');
      const reason = i.options.getString('raison');
      if (!member) return reply(i, 'warn', `${emoji('error')} Ce membre n'est pas sur le serveur.`, true);
      const err = canModerate(i, member);
      if (err) return reply(i, 'warn', `${emoji('denied')} ${err}`, true);
      await i.deferReply();
      const { count, auto } = await addWarn(i.guild, member, i.user, reason);
      let txt = `${emoji('warning')} **${member.user.tag}** a reçu un avertissement (**${count}** au total).\n**Raison :** ${reason}`;
      if (auto) txt += `\n\n${emoji('security')} Sanction automatique : **${auto}** (${count} warns).`;
      i.editReply({ embeds: [embed('warn', null, txt)] });
    },
  },
  {
    data: new SlashCommandBuilder().setName('warns').setDescription("Voir les avertissements d'un membre")
      .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const user = i.options.getUser('membre');
      const list = db.guild(i.guild.id).warns[user.id] || [];
      if (!list.length) return reply(i, 'ok', `${emoji('success')} **${user.tag}** n'a aucun avertissement.`);
      const lines = list.slice(-15).map((w, idx) =>
        `**${list.length - Math.min(list.length, 15) + idx + 1}.** ${w.reason}\n└ par ${w.mod === 'AutoMod' ? 'AutoMod' : `<@${w.mod}>`} • <t:${Math.floor(w.date / 1000)}:R>`);
      i.reply({ embeds: [embed('warn', `${emoji('warning')} Avertissements de ${user.tag} (${list.length})`, lines.join('\n'))] });
    },
  },
  {
    data: new SlashCommandBuilder().setName('unwarn').setDescription("Retirer un avertissement précis")
      .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
      .addIntegerOption(o => o.setName('numero').setDescription('Le numéro du warn (voir /warns)').setRequired(true).setMinValue(1))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const user = i.options.getUser('membre');
      const n = i.options.getInteger('numero');
      const g = db.guild(i.guild.id);
      const list = g.warns[user.id] || [];
      if (n > list.length) return reply(i, 'warn', `${emoji('error')} Ce warn n'existe pas (${list.length} au total).`, true);
      const [removed] = list.splice(n - 1, 1);
      db.save();
      const m = await i.guild.members.fetch(user.id).catch(() => null);
      if (m) await syncWarnRole(i.guild, m, list.length);
      reply(i, 'ok', `${emoji('success')} Warn n°${n} retiré à **${user.tag}** : *${removed.reason}*`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('clearwarns').setDescription("Effacer tous les avertissements d'un membre")
      .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers),
    async execute(i) {
      const user = i.options.getUser('membre');
      const g = db.guild(i.guild.id);
      const n = (g.warns[user.id] || []).length;
      delete g.warns[user.id];
      db.save();
      const m = await i.guild.members.fetch(user.id).catch(() => null);
      if (m) await syncWarnRole(i.guild, m, 0);
      reply(i, 'ok', `${emoji('success')} ${n} avertissement(s) effacé(s) pour **${user.tag}**.`);
    },
  },
];
