const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const antibot = require('../antibot');
const { reply } = require('../utils');
const { emoji } = require('../emojis');

module.exports = [
  {
    data: new SlashCommandBuilder().setName('unbot').setDescription("Activer ou désactiver l'anti-bot (expulse les bots qui rejoignent le serveur)")
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
      .addSubcommand(s => s.setName('activate').setDescription("Activer l'anti-bot"))
      .addSubcommand(s => s.setName('desactivate').setDescription("Désactiver l'anti-bot")),
    async execute(i) {
      const on = i.options.getSubcommand() === 'activate';
      const was = antibot.isEnabled(i.guild.id);
      if (was === on) return reply(i, 'info', `${emoji(on ? 'on' : 'off')} L'anti-bot est déjà **${on ? 'activé' : 'désactivé'}**.`, true);
      antibot.setEnabled(i.guild.id, on);
      const warnPerm = on && !i.guild.members.me?.permissions.has(PermissionFlagsBits.KickMembers)
        ? `\n${emoji('warning')} Il me manque la permission **Expulser des membres** pour que ça fonctionne.` : '';
      reply(i, on ? 'ok' : 'ban', on
        ? `${emoji('on')} **Anti-bot activé** : tout bot qui rejoint le serveur sera expulsé automatiquement.${warnPerm}`
        : `${emoji('off')} **Anti-bot désactivé** : les bots peuvent à nouveau être ajoutés.`);
    },
  },
];
