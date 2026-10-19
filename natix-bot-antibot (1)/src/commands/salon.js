const { SlashCommandBuilder, PermissionFlagsBits, ChannelType, MessageFlags } = require('discord.js');
const { reply, sendLog, embed } = require('../utils');
const { emoji } = require('../emojis');

module.exports = [
  {
    data: new SlashCommandBuilder().setName('clear').setDescription('Supprimer des messages')
      .addIntegerOption(o => o.setName('nombre').setDescription('Nombre de messages (1-100)').setRequired(true).setMinValue(1).setMaxValue(100))
      .addUserOption(o => o.setName('membre').setDescription('Seulement les messages de ce membre'))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages),
    async execute(i) {
      const n = i.options.getInteger('nombre');
      const user = i.options.getUser('membre');
      await i.deferReply({ flags: MessageFlags.Ephemeral });
      i.editReply({ embeds: [embed('info', null, `${emoji('loading')} Suppression en cours…`)] }).catch(() => {});
      let msgs = await i.channel.messages.fetch({ limit: 100 });
      if (user) msgs = msgs.filter(m => m.author.id === user.id);
      msgs = [...msgs.values()].slice(0, n);
      const deleted = await i.channel.bulkDelete(msgs, true); // ignore les messages de +14 jours
      await i.editReply({ embeds: [embed('ok', null, `${emoji('clean')} **${deleted.size}** message(s) supprimé(s).${deleted.size < msgs.length ? '\n*(Les messages de plus de 14 jours ne peuvent pas être supprimés en masse.)*' : ''}`)] });
      sendLog(i.guild, embed('log', `${emoji('clean')} Messages supprimés`, `**${deleted.size}** messages dans ${i.channel} par ${i.user}${user ? ` (de ${user})` : ''}`));
    },
  },
  {
    data: new SlashCommandBuilder().setName('lock').setDescription('Verrouiller un salon')
      .addChannelOption(o => o.setName('salon').setDescription('Le salon (par défaut : celui-ci)').addChannelTypes(ChannelType.GuildText))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels),
    async execute(i) {
      const ch = i.options.getChannel('salon') || i.channel;
      await ch.permissionOverwrites.edit(i.guild.roles.everyone, { SendMessages: false });
      reply(i, 'ban', `${emoji('lock')} ${ch} est verrouillé.`);
      sendLog(i.guild, embed('log', `${emoji('lock')} Salon verrouillé`, `${ch} par ${i.user}`));
    },
  },
  {
    data: new SlashCommandBuilder().setName('unlock').setDescription('Déverrouiller un salon')
      .addChannelOption(o => o.setName('salon').setDescription('Le salon (par défaut : celui-ci)').addChannelTypes(ChannelType.GuildText))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels),
    async execute(i) {
      const ch = i.options.getChannel('salon') || i.channel;
      await ch.permissionOverwrites.edit(i.guild.roles.everyone, { SendMessages: null });
      reply(i, 'ok', `${emoji('unlock')} ${ch} est déverrouillé.`);
      sendLog(i.guild, embed('log', `${emoji('unlock')} Salon déverrouillé`, `${ch} par ${i.user}`));
    },
  },
  {
    data: new SlashCommandBuilder().setName('slowmode').setDescription('Mettre un mode lent sur le salon')
      .addIntegerOption(o => o.setName('secondes').setDescription('Secondes entre 2 messages (0 = désactiver, max 21600)').setRequired(true).setMinValue(0).setMaxValue(21600))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels),
    async execute(i) {
      const s = i.options.getInteger('secondes');
      await i.channel.setRateLimitPerUser(s);
      reply(i, 'info', s ? `${emoji('slowmode')} Mode lent : **${s}s** entre chaque message.` : `${emoji('success')} Mode lent désactivé.`);
    },
  },
];
