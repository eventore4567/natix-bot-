const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const db = require('../db');
const { reply, embed } = require('../utils');
const { emoji } = require('../emojis');
const inv = require('../invites');

const medal = i => ['🥇', '🥈', '🥉'][i] ?? `**${i + 1}.**`;

module.exports = [
  // ----- PUBLIC : consulter les invitations (listé dans commandPolicy.js) -----
  {
    data: new SlashCommandBuilder().setName('invites').setDescription('Voir les invitations')
      .addSubcommand(s => s.setName('voir').setDescription('Voir le nombre d\'invitations d\'un membre')
        .addUserOption(o => o.setName('membre').setDescription('Le membre (défaut : toi)')))
      .addSubcommand(s => s.setName('classement').setDescription('Top 10 des membres qui ont le plus invité'))
      .addSubcommand(s => s.setName('invitepar').setDescription('Savoir qui a invité un membre')
        .addUserOption(o => o.setName('membre').setDescription('Le membre (défaut : toi)'))),

    async execute(i) {
      const sub = i.options.getSubcommand();
      if (!inv.store(i.guild.id).enabled) return reply(i, 'warn', `${emoji('error')} Le suivi des invitations est désactivé sur ce serveur.`, true);

      if (sub === 'classement') {
        const rows = inv.leaderboard(i.guild.id, 10);
        if (!rows.length) return reply(i, 'info', `${emoji('info')} Aucune invitation enregistrée pour le moment.`, true);
        const lines = rows.map((r, n) => `${medal(n)} <@${r.id}> — **${r.total}** invitation${r.total > 1 ? 's' : ''} *(${r.regular} réelles, ${r.left} parties, ${r.fake} fake${r.bonus ? `, ${r.bonus > 0 ? '+' : ''}${r.bonus} bonus` : ''})*`);
        return i.reply({ embeds: [embed('info', `${emoji('reward')} Classement des invitations`, lines.join('\n'))], allowedMentions: { parse: [] } });
      }

      const user = i.options.getUser('membre') ?? i.user;

      if (sub === 'invitepar') {
        const j = inv.inviterOf(i.guild.id, user.id);
        if (!j) return reply(i, 'info', `${emoji('info')} Je n'ai pas d'information sur l'arrivée de **${user.tag}** (arrivé avant l'activation du suivi ?).`, true);
        const txt = inv.who({ ...j, total: j.inviterId ? inv.getStats(i.guild.id, j.inviterId).total : 0 });
        return i.reply({ embeds: [embed('info', `${emoji('join')} Arrivée de ${user.tag}`, `${user} — ${txt}\nArrivé <t:${Math.floor(j.at / 1000)}:R>${j.code ? `\nInvitation : \`${j.code}\`` : ''}`)], allowedMentions: { parse: [] } });
      }

      // voir
      const s = inv.getStats(i.guild.id, user.id);
      const e = embed('info', `${emoji('join')} Invitations de ${user.tag}`)
        .setThumbnail(user.displayAvatarURL())
        .setDescription(`**${s.total}** invitation${s.total > 1 ? 's' : ''}`)
        .addFields(
          { name: 'Réelles', value: String(s.regular), inline: true },
          { name: 'Parties', value: String(s.left), inline: true },
          { name: 'Fake', value: String(s.fake), inline: true },
          { name: 'Bonus', value: String(s.bonus), inline: true },
        );
      return i.reply({ embeds: [e] });
    },
  },

  // ----- GESTION : réglages et corrections (permission « Gérer le serveur ») -----
  {
    data: new SlashCommandBuilder().setName('invitetracker').setDescription('Régler le suivi des invitations')
      .addSubcommand(s => s.setName('config').setDescription('Voir ou régler le suivi')
        .addBooleanOption(o => o.setName('actif').setDescription('Activer ou couper le suivi'))
        .addChannelOption(o => o.setName('salon').setDescription('Salon où annoncer arrivées et départs').addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement))
        .addBooleanOption(o => o.setName('retirer_salon').setDescription('Ne plus annoncer dans un salon dédié'))
        .addIntegerOption(o => o.setName('age_min').setDescription('Âge minimum du compte en jours, en dessous = fake (défaut : 7)').setMinValue(0).setMaxValue(365)))
      .addSubcommand(s => s.setName('bonus').setDescription('Ajouter ou retirer des invitations bonus à un membre')
        .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
        .addIntegerOption(o => o.setName('nombre').setDescription('Positif = ajoute, négatif = retire').setRequired(true).setMinValue(-1000).setMaxValue(1000)))
      .addSubcommand(s => s.setName('reset').setDescription('Remettre à zéro les invitations d\'un membre')
        .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true)))
      .addSubcommand(s => s.setName('resettout').setDescription('Remettre à zéro TOUTES les invitations du serveur')
        .addBooleanOption(o => o.setName('confirmer').setDescription('Mets « True » pour confirmer (irréversible)').setRequired(true)))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),

    async execute(i) {
      const sub = i.options.getSubcommand();
      const cfg = inv.store(i.guild.id);

      if (sub === 'config') {
        const actif = i.options.getBoolean('actif');
        const salon = i.options.getChannel('salon');
        const age = i.options.getInteger('age_min');
        if (salon) {
          const perms = salon.permissionsFor?.(i.guild.members.me);
          if (!perms?.has(['ViewChannel', 'SendMessages', 'EmbedLinks'])) return reply(i, 'warn', `${emoji('denied')} Je n'ai pas le droit d'envoyer des messages avec embed dans ${salon}.`, true);
          cfg.channel = salon.id;
        }
        if (i.options.getBoolean('retirer_salon')) cfg.channel = null;
        if (actif != null) cfg.enabled = actif;
        if (age != null) cfg.minAgeDays = age;
        if (actif != null || salon || age != null || i.options.getBoolean('retirer_salon') != null) db.save();
        const canSee = i.guild.members.me?.permissions.has(PermissionFlagsBits.ManageGuild);
        const e = embed('info', `${emoji('config')} Invite tracker`, [
          `**État :** ${cfg.enabled ? `${emoji('on')} actif` : `${emoji('off')} désactivé`}`,
          `**Salon d'annonces :** ${cfg.channel ? `<#${cfg.channel}>` : '*aucun (les arrivées apparaissent dans le salon de logs)*'}`,
          `**Compte « fake » si créé depuis moins de :** ${cfg.minAgeDays} jour${cfg.minAgeDays > 1 ? 's' : ''}`,
          `**Membres suivis :** ${Object.keys(cfg.joins).length}`,
          canSee ? '' : `${emoji('warning')} Il me manque la permission **Gérer le serveur** : sans elle je ne peux pas lire les invitations.`,
        ].filter(Boolean).join('\n'));
        return i.reply({ embeds: [e], flags: 64 });
      }

      if (sub === 'bonus') {
        const user = i.options.getUser('membre');
        if (user.bot) return reply(i, 'warn', `${emoji('error')} Les bots n'ont pas d'invitations.`, true);
        const n = i.options.getInteger('nombre');
        if (!n) return reply(i, 'warn', `${emoji('error')} Le nombre ne peut pas être 0.`, true);
        const s = inv.addBonus(i.guild.id, user.id, n);
        return reply(i, 'ok', `${emoji('success')} ${n > 0 ? '+' : ''}${n} bonus pour **${user.tag}** : il a maintenant **${s.total}** invitation${s.total > 1 ? 's' : ''}.`, true);
      }

      if (sub === 'reset') {
        const user = i.options.getUser('membre');
        inv.resetUser(i.guild.id, user.id);
        return reply(i, 'ok', `${emoji('success')} Invitations de **${user.tag}** remises à zéro.`, true);
      }

      // resettout
      if (!i.options.getBoolean('confirmer')) return reply(i, 'warn', `${emoji('error')} Annulé : mets \`confirmer: True\` pour tout remettre à zéro.`, true);
      inv.resetAll(i.guild.id);
      return reply(i, 'ok', `${emoji('success')} Toutes les invitations du serveur ont été remises à zéro.`, true);
    },
  },
];
