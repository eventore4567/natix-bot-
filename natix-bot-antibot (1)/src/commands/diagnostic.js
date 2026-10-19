const { SlashCommandBuilder, PermissionFlagsBits, PermissionsBitField, MessageFlags, ChannelType } = require('discord.js');
const { embed } = require('../utils');
const { canUseCommand } = require('../access');
const { PUBLIC_COMMANDS } = require('../commandPolicy');
const { emoji } = require('../emojis');

const F = PermissionsBitField.Flags;
const BOT_NEEDS = ['ViewChannel', 'SendMessages', 'EmbedLinks', 'ReadMessageHistory', 'ManageMessages', 'ManageChannels', 'ManageRoles', 'BanMembers', 'KickMembers', 'ModerateMembers'];
const cut = (s, n = 1024) => { if (s.length <= n) return s; const k = s.lastIndexOf('\n', n - 2); return s.slice(0, k > 0 ? k : n - 1) + '…'; };
const errText = e => `${e.message}${e.code ? ` (code ${e.code})` : ''}`;

// Profil simulé : ce que Discord calcule pour un membre dans le salon examiné
function profileFor(guild, channel, label, member) {
  if (!member) {
    const ev = guild.roles.everyone;
    return { label, userId: '0', roleIds: [], isAdmin: false, memberPerms: ev.permissions.bitfield,
      native: { guild: ev.permissions.has(F.UseApplicationCommands), channel: !!channel.permissionsFor(ev)?.has(F.UseApplicationCommands) }, who: ev, member: null };
  }
  return { label, userId: member.id, roleIds: [...member.roles.cache.keys()], member,
    isAdmin: member.id === guild.ownerId || member.permissions.has(F.Administrator, false),
    memberPerms: member.permissions.bitfield,
    native: { guild: member.permissions.has(F.UseApplicationCommands, false), channel: !!channel.permissionsFor(member)?.has(F.UseApplicationCommands) }, who: member };
}

// Explique OÙ se trouve le refus natif « Utiliser les commandes d'application »
function nativeBlockOrigin(guild, channel, p) {
  const out = [];
  if (!p.native.guild) out.push('rôles du serveur (Paramètres du serveur → Rôles)');
  const ids = new Set([guild.id, p.userId, ...p.roleIds]);
  for (const o of channel.permissionOverwrites?.cache.values() ?? []) {
    if (!ids.has(o.id) || !o.deny.has(F.UseApplicationCommands)) continue;
    const who = o.id === guild.id ? '@everyone' : o.type === 1 ? `<@${o.id}>` : `<@&${o.id}>`;
    out.push(`${who} refusé sur ${channel}${channel.permissionsLocked && channel.parent ? ` (synchronisé avec la catégorie « ${channel.parent.name} »)` : ''}`);
  }
  return out;
}

const labelOf = (perm, guildId) => perm.type === 3 ? (perm.id === (BigInt(guildId) - 1n).toString() ? 'tous les salons' : `<#${perm.id}>`)
  : perm.type === 2 ? `<@${perm.id}>` : perm.id === guildId ? '@everyone' : `<@&${perm.id}>`;

module.exports = [
  {
    data: new SlashCommandBuilder().setName('diagnostic')
      .setDescription('Diagnostiquer pourquoi des membres ne voient/utilisent pas les commandes')
      .addUserOption(o => o.setName('membre').setDescription('Tester les droits réels de ce membre (en plus de @everyone)'))
      .addChannelOption(o => o.setName('salon').setDescription('Salon à examiner (par défaut : celui-ci)').addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),
    async execute(i) {
      await i.deferReply({ flags: MessageFlags.Ephemeral });
      i.editReply({ embeds: [embed('info', null, `${emoji('loading')} Analyse des permissions en cours…`)] }).catch(() => {});
      const { guild, client } = i;
      const channel = i.options.getChannel('salon') ?? i.channel;
      const target = i.options.getMember('membre') ?? i.member;
      const fixes = new Set();
      const install = [];
      const ok = emoji('success'), ko = emoji('error'), warn = emoji('warning');

      // 1) Installation : commandes lisibles = scope applications.commands OK
      let guildCmds = null;
      try { guildCmds = await guild.commands.fetch(); } catch (e) {
        install.push(`${ko} Commandes du serveur illisibles : ${errText(e)}`);
        fixes.add('Ré-inviter le bot avec le scope **bot + applications.commands** (Developer Portal → OAuth2 → URL Generator), puis redémarrer le bot.');
      }
      if (guildCmds) install.push(`${ok} ${guildCmds.size} commandes enregistrées sur ce serveur (scope \`applications.commands\` OK)`);
      try {
        const g = await client.application.commands.fetch();
        install.push(g.size ? `${warn} ${g.size} commande(s) GLOBALE(S) résiduelle(s) : doublons possibles (redémarre le bot pour les purger)` : `${ok} Aucune commande globale résiduelle`);
      } catch (e) { install.push(`${warn} Commandes globales illisibles : ${errText(e)}`); }
      const missing = guild.members.me.permissions.missing(BOT_NEEDS);
      install.push(missing.length ? `${warn} Permissions manquantes au bot (rôle de ${client.user}) : ${missing.join(', ')}` : `${ok} Le bot a les permissions de serveur nécessaires`);
      if (missing.length) fixes.add('Donner au rôle du bot les permissions manquantes et le placer **au-dessus** des rôles qu\'il doit modérer.');

      // 2) Réglages « Intégrations » (surcharges par commande / pour tout le bot)
      let overrides = null; let overridesErr = null;
      try { overrides = await guild.commands.permissions.fetch({}); } catch (e) { overridesErr = errText(e); }
      const appPerms = overrides?.get(client.application.id) ?? [];
      const integ = [];
      if (!overrides) {
        integ.push(`${warn} Réglages Intégrations **illisibles** (${overridesErr}). Résultats ci-dessous = hors Intégrations. Vérifie à la main : Paramètres du serveur → Intégrations → ${client.user.username}.`);
      } else {
        const named = [];
        if (appPerms.length) named.push(`Tout le bot : ${appPerms.map(p => `${labelOf(p, guild.id)} ${p.permission ? ok : ko}`).join(', ')}`);
        for (const c of guildCmds ?? []) {
          const cp = overrides.get(c.id);
          if (cp?.length) named.push(`/${c.name} : ${cp.map(p => `${labelOf(p, guild.id)} ${p.permission ? ok : ko}`).join(', ')}`);
        }
        integ.push(named.length ? `Surcharges trouvées :\n${named.join('\n')}` : `${ok} Aucune surcharge : les permissions par défaut des commandes s'appliquent`);
      }

      // 3) Test d'accès par profil
      const profiles = [profileFor(guild, channel, '@everyone seul (membre classique)', null)];
      if (target) profiles.push(profileFor(guild, channel, `${target.displayName}${target.id === i.user.id ? ' (toi)' : ''}`, target));
      const results = {};
      const policyIssues = [];
      for (const p of profiles) {
        results[p.label] = (guildCmds ? [...guildCmds.values()] : []).map(c => {
          const pub = PUBLIC_COMMANDS.includes(c.name);
          const bits = c.defaultMemberPermissions?.bitfield ?? null;
          if (p === profiles[0] && pub && bits != null) policyIssues.push(`/${c.name} est restreinte par défaut alors qu'elle doit être publique → redémarre le bot pour resynchroniser`);
          const r = canUseCommand({ guildId: guild.id, channelId: channel.id, userId: p.userId, roleIds: p.roleIds, isAdmin: p.isAdmin, native: p.native,
            commandPerms: overrides?.get(c.id) ?? null, appPerms, defaultMemberPermissions: bits, memberPerms: p.memberPerms });
          return { name: c.name, pub, ...r };
        });
      }

      const fields = [];
      for (const p of profiles) {
        const res = results[p.label];
        const lines = [];
        const pubRes = res.filter(r => r.pub);
        const okPub = pubRes.filter(r => r.allowed);
        if (!res.length) lines.push(`${warn} Test impossible (commandes illisibles)`);
        else if (okPub.length === pubRes.length) lines.push(`${ok} Commandes publiques utilisables dans ${channel} : ${okPub.map(r => '/' + r.name).join(' ')}`);
        else {
          lines.push(`${ko} Commandes publiques bloquées dans ${channel} (${okPub.length}/${pubRes.length} utilisables)`);
          for (const reason of new Set(pubRes.filter(r => !r.allowed).map(r => r.reason))) lines.push(`• ${reason}`);
          const code = pubRes.find(r => !r.allowed).code;
          if (code.startsWith('native')) for (const o of nativeBlockOrigin(guild, channel, p)) lines.push(`• Origine : ${o}`);
          const everyone = p === profiles[0];
          if (code === 'native-guild') fixes.add('Paramètres du serveur → Rôles → **@everyone** → activer « Utiliser les commandes d\'application ».');
          if (code === 'native-channel') fixes.add(`Salon ${channel} (et sa catégorie si synchronisé) → Modifier → Permissions → ${everyone ? '**@everyone**' : 'le rôle concerné'} → mettre « Utiliser les commandes d'application » sur ✅ (ou neutre « / » si la catégorie l'autorise). Le bot ne peut pas et ne doit pas le contourner.`);
          if (code === 'integration-channel') fixes.add(`Paramètres du serveur → Intégrations → ${client.user.username} → autoriser ${channel} dans les salons.`);
          if (code === 'integration-deny') fixes.add(`Paramètres du serveur → Intégrations → ${client.user.username} → retirer le refus pour ${everyone ? '@everyone' : 'ce membre/ses rôles'} (ou cliquer « Réinitialiser les permissions »).`);
        }
        const mgmt = res.filter(r => !r.pub);
        const okMgmt = mgmt.filter(r => r.allowed);
        if (res.length) {
          if (p.isAdmin) lines.push(`${emoji('unlock')} Commandes de gestion : ${okMgmt.length}/${mgmt.length} (administrateur : normal)`);
          else if (!okMgmt.length) lines.push(`${emoji('lock')} Commandes de gestion : 0/${mgmt.length} (conforme)`);
          else lines.push(`${p === profiles[0] ? warn : emoji('unlock')} Commandes de gestion accessibles : ${okMgmt.map(r => '/' + r.name).join(' ')}${p === profiles[0] ? ' — @everyone ne devrait pas y avoir accès (réglage Intégrations ?)' : ''}`);
        }
        fields.push({ name: `${emoji('user')} ${p.label}`, value: cut(lines.join('\n')) });
      }

      const everyoneOk = results[profiles[0].label].length && results[profiles[0].label].filter(r => r.pub).every(r => r.allowed);
      if (policyIssues.length) fixes.add([...new Set(policyIssues)].join('\n'));
      const verdict = !guildCmds ? `${ko} **Le bot ne peut pas lire ses commandes** : voir ci-dessous.`
        : everyoneOk ? `${ok} **Un membre normal peut utiliser les commandes publiques dans ${channel}.** Si quelqu\'un ne les voit pas : il doit redémarrer Discord (Ctrl+R / relancer l\'app).`
        : `${ko} **Un membre normal NE peut PAS utiliser les commandes publiques dans ${channel}.** Cause(s) ci-dessous.`;

      const e = embed(everyoneOk ? 'ok' : 'ban', `${emoji('diagnostic')} Diagnostic des commandes`, verdict)
        .addFields({ name: `${emoji('config')} Installation`, value: cut(install.join('\n')) }, { name: `${emoji('bot')} Intégrations`, value: cut(integ.join('\n')) }, ...fields);
      if (fixes.size) e.addFields({ name: `${warn} À corriger manuellement dans Discord`, value: cut([...fixes].map((f, n) => `${n + 1}. ${f}`).join('\n')) });
      e.setFooter({ text: 'Simulation basée sur les règles documentées de Discord ; en cas de doute, Discord fait foi.' });
      i.editReply({ embeds: [e] });
    },
  },
];
