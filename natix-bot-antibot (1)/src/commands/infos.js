const { SlashCommandBuilder } = require('discord.js');
const db = require('../db');
const { embed } = require('../utils');
const { emoji } = require('../emojis');

const ts = (d, f = 'F') => `<t:${Math.floor(d / 1000)}:${f}>`;

module.exports = [
  {
    data: new SlashCommandBuilder().setName('userinfo').setDescription("Infos sur un membre")
      .addUserOption(o => o.setName('membre').setDescription('Le membre (par défaut : toi)')),
    async execute(i) {
      const user = i.options.getUser('membre') || i.user;
      const member = i.options.getMember('membre') || (user.id === i.user.id ? i.member : null);
      const warns = (db.guild(i.guild.id).warns[user.id] || []).length;
      const e = embed('info', `${emoji('user')} ${user.tag}`).setThumbnail(user.displayAvatarURL({ size: 256 }))
        .addFields(
          { name: 'ID', value: user.id, inline: true },
          { name: 'Compte créé', value: ts(user.createdTimestamp, 'R'), inline: true },
          { name: 'Avertissements', value: String(warns), inline: true },
        );
      if (member) {
        e.addFields({ name: 'A rejoint', value: ts(member.joinedTimestamp, 'R'), inline: true });
        const roles = member.roles.cache.filter(r => r.id !== i.guild.id).sort((a, b) => b.position - a.position).map(r => `${r}`);
        e.addFields({ name: `Rôles (${roles.length})`, value: roles.slice(0, 20).join(' ') || 'Aucun' });
        if (member.isCommunicationDisabled()) e.addFields({ name: `${emoji('mute')} Mute jusqu'à`, value: ts(member.communicationDisabledUntilTimestamp) });
      }
      i.reply({ embeds: [e] });
    },
  },
  {
    data: new SlashCommandBuilder().setName('serverinfo').setDescription('Infos sur le serveur'),
    async execute(i) {
      const g = i.guild;
      const owner = await g.fetchOwner().catch(() => null);
      const e = embed('info', `${emoji('server')} ${g.name}`).setThumbnail(g.iconURL({ size: 256 }))
        .addFields(
          { name: 'Propriétaire', value: owner ? `${owner.user.tag}` : '?', inline: true },
          { name: 'Membres', value: String(g.memberCount), inline: true },
          { name: 'Créé', value: ts(g.createdTimestamp, 'R'), inline: true },
          { name: 'Salons', value: String(g.channels.cache.size), inline: true },
          { name: 'Rôles', value: String(g.roles.cache.size), inline: true },
          { name: 'Boosts', value: `${g.premiumSubscriptionCount || 0} (niveau ${g.premiumTier})`, inline: true },
        );
      i.reply({ embeds: [e] });
    },
  },
  {
    data: new SlashCommandBuilder().setName('aide').setDescription('Liste des commandes du bot'),
    async execute(i) {
      const e = embed('info', `${emoji('help')} Commandes du bot`)
        .addFields(
          { name: `${emoji('info')} Pour tout le monde`, value: '`/aide` `/userinfo` `/serverinfo`' },
          { name: `${emoji('sanction')} Modération (équipe)`, value: '`/ban` `/tempban` `/unban` `/kick` `/mute` `/unmute`' },
          { name: `${emoji('warning')} Avertissements`, value: '`/warn` `/warns` `/unwarn` `/clearwarns`' },
          { name: `${emoji('lock')} Salons`, value: '`/clear` `/lock` `/unlock` `/slowmode`' },
          { name: `${emoji('security')} Automod`, value: '`/automod voir` `/automod activer` `/automod mots` `/automod bypass` `/automod sanctions` `/automod spam`' },
          { name: `${emoji('reward')} Giveaways`, value: '`/giveaway creer` `/giveaway terminer` `/giveaway reroll` `/giveaway annuler` `/giveaway liste` `/giveaway config` `/giveaway blacklist ajouter|retirer|liste`' },
          { name: `${emoji('logs')} Logs`, value: '`/setlogs`' },
          { name: `${emoji('diagnostic')} Admin`, value: '`/diagnostic`' },
        );
      i.reply({ embeds: [e] });
    },
  },
];
