const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const db = require('../db');
const { reply, embed } = require('../utils');
const { emoji } = require('../emojis');

const MODULES = {
  antiSpam: 'Anti-spam',
  antiInvites: 'Anti-invitations Discord',
  antiLinks: 'Anti-liens (tous)',
  antiCaps: 'Anti-majuscules',
  antiMentions: 'Anti-mentions de masse',
  badWords: 'Mots interdits',
};

module.exports = [
  {
    data: new SlashCommandBuilder().setName('setlogs').setDescription('Choisir le salon des logs')
      .addChannelOption(o => o.setName('salon').setDescription('Le salon de logs (vide = désactiver)').addChannelTypes(ChannelType.GuildText))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),
    async execute(i) {
      const ch = i.options.getChannel('salon');
      db.guild(i.guild.id).config.logChannel = ch ? ch.id : null;
      db.save();
      reply(i, 'ok', ch ? `${emoji('logs')} Les logs seront envoyés dans ${ch}.` : `${emoji('off')} Logs désactivés.`);
    },
  },
  {
    data: new SlashCommandBuilder().setName('automod').setDescription("Configurer l'automodération")
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
      .addSubcommand(s => s.setName('voir').setDescription('Voir la configuration actuelle'))
      .addSubcommand(s => s.setName('activer').setDescription('Activer / désactiver un module')
        .addStringOption(o => o.setName('module').setDescription('Le module').setRequired(true)
          .addChoices(...Object.entries(MODULES).map(([value, name]) => ({ name, value }))))
        .addBooleanOption(o => o.setName('etat').setDescription('Activé ?').setRequired(true)))
      .addSubcommand(s => s.setName('mots').setDescription('Gérer les mots interdits')
        .addStringOption(o => o.setName('action').setDescription('Action').setRequired(true)
          .addChoices({ name: 'Ajouter', value: 'add' }, { name: 'Retirer', value: 'remove' }, { name: 'Voir la liste', value: 'list' }, { name: 'Tout effacer', value: 'clear' }))
        .addStringOption(o => o.setName('mot').setDescription('Le mot (plusieurs possibles, séparés par des virgules)')))
      .addSubcommand(s => s.setName('bypass').setDescription("Rôle ignoré par l'automod")
        .addRoleOption(o => o.setName('role').setDescription('Le rôle').setRequired(true))
        .addBooleanOption(o => o.setName('ignorer').setDescription('Ignorer ce rôle ?').setRequired(true)))
      .addSubcommand(s => s.setName('sanctions').setDescription('Sanctions auto selon le nombre de warns (0 = désactivé)')
        .addIntegerOption(o => o.setName('mute').setDescription('Warns avant mute').setMinValue(0).setMaxValue(50))
        .addIntegerOption(o => o.setName('kick').setDescription('Warns avant kick').setMinValue(0).setMaxValue(50))
        .addIntegerOption(o => o.setName('ban').setDescription('Warns avant ban').setMinValue(0).setMaxValue(50))
        .addIntegerOption(o => o.setName('duree_mute').setDescription('Durée du mute auto en minutes').setMinValue(1).setMaxValue(40320)))
      .addSubcommand(s => s.setName('spam').setDescription("Réglages de l'anti-spam et des limites")
        .addIntegerOption(o => o.setName('messages').setDescription('Nombre de messages...').setMinValue(2).setMaxValue(30))
        .addIntegerOption(o => o.setName('secondes').setDescription('...en combien de secondes').setMinValue(1).setMaxValue(60))
        .addIntegerOption(o => o.setName('duree_mute').setDescription('Durée du mute anti-spam en minutes').setMinValue(1).setMaxValue(40320))
        .addIntegerOption(o => o.setName('max_mentions').setDescription('Mentions max par message').setMinValue(2).setMaxValue(50))
        .addIntegerOption(o => o.setName('pourcent_majuscules').setDescription('% de majuscules max').setMinValue(30).setMaxValue(100))),
    async execute(i) {
      const g = db.guild(i.guild.id);
      const cfg = g.config;
      const sub = i.options.getSubcommand();

      if (sub === 'voir') {
        const mods = Object.entries(MODULES).map(([k, n]) => `${emoji(cfg.automod[k] ? 'on' : 'off')} ${n}`).join('\n');
        const t = cfg.warnThresholds;
        const e = embed('info', `${emoji('security')} Configuration de l'automod`)
          .addFields(
            { name: 'Modules', value: mods },
            { name: 'Anti-spam', value: `${cfg.spam.messages} messages en ${cfg.spam.seconds}s → mute ${cfg.spam.muteMinutes} min`, inline: true },
            { name: 'Limites', value: `${cfg.maxMentions} mentions max\n${cfg.capsPercent}% de majuscules max`, inline: true },
            { name: 'Sanctions auto (warns)', value: `Mute : ${t.mute || emoji('off')} (${cfg.warnMuteMinutes} min)\nKick : ${t.kick || emoji('off')}\nBan : ${t.ban || emoji('off')}`, inline: true },
            { name: 'Mots interdits', value: `${cfg.badWords.length} mot(s)`, inline: true },
            { name: 'Rôles ignorés', value: cfg.bypassRoles.map(r => `<@&${r}>`).join(' ') || 'Aucun (admins et modos toujours ignorés)', inline: true },
            { name: 'Salon de logs', value: cfg.logChannel ? `<#${cfg.logChannel}>` : `${emoji('off')} Non défini (\`/setlogs\`)`, inline: true },
          );
        return i.reply({ embeds: [e] });
      }

      if (sub === 'activer') {
        const m = i.options.getString('module');
        const on = i.options.getBoolean('etat');
        cfg.automod[m] = on;
        db.save();
        return reply(i, on ? 'ok' : 'ban', `${emoji(on ? 'on' : 'off')} **${MODULES[m]}** ${on ? 'activé' : 'désactivé'}.`);
      }

      if (sub === 'mots') {
        const action = i.options.getString('action');
        const words = (i.options.getString('mot') || '').split(',').map(w => w.trim().toLowerCase()).filter(Boolean);
        if (action === 'list') {
          return reply(i, 'info', cfg.badWords.length ? `${emoji('denied')} **Mots interdits :**\n||${cfg.badWords.join(', ')}||` : 'Aucun mot interdit.', true);
        }
        if (action === 'clear') { cfg.badWords = []; db.save(); return reply(i, 'ok', `${emoji('success')} Liste des mots interdits vidée.`, true); }
        if (!words.length) return reply(i, 'warn', `${emoji('error')} Précise le ou les mots dans l'option \`mot\`.`, true);
        if (action === 'add') cfg.badWords = [...new Set([...cfg.badWords, ...words])];
        else cfg.badWords = cfg.badWords.filter(w => !words.includes(w));
        db.save();
        return reply(i, 'ok', `${emoji('success')} ${words.length} mot(s) ${action === 'add' ? 'ajouté(s)' : 'retiré(s)'}. Total : ${cfg.badWords.length}.`, true);
      }

      if (sub === 'bypass') {
        const role = i.options.getRole('role');
        const ignore = i.options.getBoolean('ignorer');
        cfg.bypassRoles = cfg.bypassRoles.filter(r => r !== role.id);
        if (ignore) cfg.bypassRoles.push(role.id);
        db.save();
        return reply(i, 'ok', ignore ? `${emoji('success')} ${role} est maintenant ignoré par l'automod.` : `${emoji('success')} ${role} n'est plus ignoré par l'automod.`);
      }

      if (sub === 'sanctions') {
        for (const k of ['mute', 'kick', 'ban']) {
          const v = i.options.getInteger(k);
          if (v !== null) cfg.warnThresholds[k] = v;
        }
        const d = i.options.getInteger('duree_mute');
        if (d) cfg.warnMuteMinutes = d;
        db.save();
        const t = cfg.warnThresholds;
        return reply(i, 'ok', `${emoji('success')} Sanctions auto :\n${emoji('mute')} Mute : ${t.mute ? `à **${t.mute}** warns (${cfg.warnMuteMinutes} min)` : `${emoji('off')} désactivé`}\n${emoji('kick')} Kick : ${t.kick ? `à **${t.kick}** warns` : `${emoji('off')} désactivé`}\n${emoji('sanction')} Ban : ${t.ban ? `à **${t.ban}** warns` : `${emoji('off')} désactivé`}`);
      }

      if (sub === 'spam') {
        const set = (opt, fn) => { const v = i.options.getInteger(opt); if (v !== null) fn(v); };
        set('messages', v => cfg.spam.messages = v);
        set('secondes', v => cfg.spam.seconds = v);
        set('duree_mute', v => cfg.spam.muteMinutes = v);
        set('max_mentions', v => cfg.maxMentions = v);
        set('pourcent_majuscules', v => cfg.capsPercent = v);
        db.save();
        return reply(i, 'ok', `${emoji('success')} Anti-spam : **${cfg.spam.messages}** messages en **${cfg.spam.seconds}s** → mute **${cfg.spam.muteMinutes} min**\nMentions max : **${cfg.maxMentions}** • Majuscules max : **${cfg.capsPercent}%**`);
      }
    },
  },
];
