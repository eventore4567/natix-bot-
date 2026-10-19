const { SlashCommandBuilder, PermissionFlagsBits, MessageFlags } = require('discord.js');

module.exports = [
  {
    data: new SlashCommandBuilder().setName('speak').setDescription('Faire envoyer un message par le bot')
      .addStringOption(o => o.setName('texte').setDescription('Le message que le bot va envoyer').setRequired(true).setMaxLength(2000))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages),
    async execute(i) {
      const texte = i.options.getString('texte');
      await i.deferReply({ flags: MessageFlags.Ephemeral });
      // Pas de @everyone / @here : seulement les mentions de membres et de rôles
      await i.channel.send({ content: texte, allowedMentions: { parse: ['users', 'roles'] } });
      await i.deleteReply().catch(() => {}); // rien d'autre n'apparaît : seul le message du bot reste
    },
  },
];
