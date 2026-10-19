const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const db = require('../db');
const { reply, embed, parseDuration, formatDuration } = require('../utils');
const { emoji } = require('../emojis');
const gwlib = require('../giveaway');

const MIN = 10e3;          // 10 secondes
const MAX = 60 * 864e5;    // 60 jours

const idOption = (o, required) => o.setName('id').setDescription('Numéro du giveaway (voir /giveaway liste)').setRequired(required).setMinValue(1);

// Retrouve un giveaway : par numéro, sinon par défaut (le seul en cours / le dernier terminé)
function resolve(i, { ended }) {
  const gw = gwlib.store(i.guild.id);
  const id = i.options.getInteger('id');
  if (id != null) {
    const it = gwlib.findItem(gw, id);
    return it ? { item: it } : { error: `Giveaway #${id} introuvable (voir \`/giveaway liste\`).` };
  }
  if (ended) {
    const last = [...gw.items].filter(x => x.ended).sort((a, b) => b.endedAt - a.endedAt)[0];
    return last ? { item: last } : { error: 'Aucun giveaway terminé à reroll.' };
  }
  const active = gw.items.filter(x => !x.ended);
  if (active.length === 1) return { item: active[0] };
  return { error: active.length ? 'Plusieurs giveaways sont en cours : précise le numéro avec l\'option `id` (voir `/giveaway liste`).' : 'Aucun giveaway en cours.' };
}

module.exports = [
  {
    data: new SlashCommandBuilder().setName('giveaway').setDescription('Gérer les giveaways')
      .addSubcommand(s => s.setName('creer').setDescription('Lancer un giveaway')
        .addStringOption(o => o.setName('lot').setDescription('Ce qu\'il y a à gagner').setRequired(true).setMaxLength(200))
        .addStringOption(o => o.setName('duree').setDescription('Durée : 30m, 2h, 1j, 1sem...').setRequired(true))
        .addIntegerOption(o => o.setName('gagnants').setDescription('Nombre de gagnants (défaut : 1)').setMinValue(1).setMaxValue(20))
        .addChannelOption(o => o.setName('salon').setDescription('Salon du giveaway (défaut : ici)').addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement)))
      .addSubcommand(s => s.setName('terminer').setDescription('Terminer un giveaway maintenant et tirer les gagnants')
        .addIntegerOption(o => idOption(o, false)))
      .addSubcommand(s => s.setName('reroll').setDescription('Tirer un nouveau gagnant (jamais un ancien gagnant ni un blacklisté)')
        .addIntegerOption(o => idOption(o, false))
        .addIntegerOption(o => o.setName('gagnants').setDescription('Combien de nouveaux gagnants (défaut : 1)').setMinValue(1).setMaxValue(20))
        .addUserOption(o => o.setName('remplacer').setDescription('Remplacer ce gagnant précis par un nouveau tirage')))
      .addSubcommand(s => s.setName('annuler').setDescription('Annuler un giveaway en cours (supprime le message, pas de gagnant)')
        .addIntegerOption(o => idOption(o, false)))
      .addSubcommand(s => s.setName('liste').setDescription('Voir les giveaways en cours et récents'))
      .addSubcommand(s => s.setName('config').setDescription('Voir ou régler les rôles VIP et blacklist')
        .addRoleOption(o => o.setName('role_vip').setDescription('Rôle VIP : 2× plus de chances de gagner'))
        .addRoleOption(o => o.setName('role_blacklist').setDescription('Rôle donné aux blacklistés (créé automatiquement sinon)')))
      .addSubcommandGroup(g => g.setName('blacklist').setDescription('Interdire la participation aux giveaways')
        .addSubcommand(s => s.setName('ajouter').setDescription('Blacklister un membre (il reçoit aussi le rôle de blacklist)')
          .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true))
          .addStringOption(o => o.setName('raison').setDescription('La raison').setMaxLength(300)))
        .addSubcommand(s => s.setName('retirer').setDescription('Retirer un membre de la blacklist (le rôle lui est retiré)')
          .addUserOption(o => o.setName('membre').setDescription('Le membre').setRequired(true)))
        .addSubcommand(s => s.setName('liste').setDescription('Voir les membres blacklistés')))
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),

    async execute(i) {
      const group = i.options.getSubcommandGroup(false);
      const sub = i.options.getSubcommand();
      const gw = gwlib.store(i.guild.id);

      // ----- Blacklist -----
      if (group === 'blacklist') {
        if (sub === 'liste') {
          const rows = Object.entries(gw.blacklist);
          if (!rows.length) return reply(i, 'ok', `${emoji('success')} Aucun membre blacklisté.`, true);
          const lines = rows.slice(0, 25).map(([id, b]) => `<@${id}> (\`${id}\`) — ${b.reason}\n└ par <@${b.by}> • <t:${Math.floor(b.date / 1000)}:R>`);
          return i.reply({ embeds: [embed('ban', `${emoji('sanction')} Blacklist giveaway (${rows.length})`, lines.join('\n') + (rows.length > 25 ? `\n… et ${rows.length - 25} autre(s)` : ''))], flags: 64 });
        }
        const user = i.options.getUser('membre');
        if (user.bot) return reply(i, 'warn', `${emoji('error')} Les bots ne participent pas aux giveaways.`, true);
        await i.deferReply({ flags: 64 });
        if (sub === 'ajouter') {
          if (gw.blacklist[user.id]) return i.editReply({ embeds: [embed('warn', null, `${emoji('error')} **${user.tag}** est déjà blacklisté.`)] });
          const { warning, inGuild } = await gwlib.blacklistAdd(i.guild, user, { by: i.user, reason: i.options.getString('raison') });
          let txt = `${emoji('sanction')} **${user.tag}** est blacklisté : il ne peut plus participer aux giveaways${inGuild && !warning ? ' et a reçu le rôle de blacklist' : ''}.`;
          if (!inGuild) txt += '\nIl n\'est pas sur le serveur : il recevra le rôle s\'il revient.';
          if (warning) txt += `\n${emoji('warning')} ${warning}`;
          return i.editReply({ embeds: [embed('ban', null, txt)] });
        }
        const { had, warning } = await gwlib.blacklistRemove(i.guild, user, { by: i.user });
        if (!had) return i.editReply({ embeds: [embed('warn', null, `${emoji('error')} **${user.tag}** n'est pas blacklisté.`)] });
        return i.editReply({ embeds: [embed('ok', null, `${emoji('success')} **${user.tag}** peut de nouveau participer aux giveaways (rôle retiré).${warning ? `\n${emoji('warning')} ${warning}` : ''}`)] });
      }

      // ----- Création -----
      if (sub === 'creer') {
        const ms = parseDuration(i.options.getString('duree'));
        if (!ms || ms < MIN || ms > MAX) return reply(i, 'warn', `${emoji('error')} Durée invalide (de 10s à 60j). Exemples : \`30m\`, \`2h\`, \`1j\`, \`1sem\`.`, true);
        const channel = i.options.getChannel('salon') ?? i.channel;
        const me = i.guild.members.me;
        const perms = channel.permissionsFor?.(me);
        if (!perms?.has(['ViewChannel', 'SendMessages', 'EmbedLinks'])) return reply(i, 'warn', `${emoji('denied')} Je n'ai pas le droit d'envoyer des messages avec embed dans ${channel}.`, true);
        await i.deferReply({ flags: 64 });
        const item = await gwlib.createGiveaway(i.guild, channel, {
          prize: i.options.getString('lot'), durationMs: ms, winnersCount: i.options.getInteger('gagnants') ?? 1, host: i.user,
        });
        return i.editReply({ embeds: [embed('ok', null, `${emoji('success')} Giveaway **#${item.id}** lancé dans ${channel}, fin <t:${Math.floor(item.endAt / 1000)}:R>.`)] });
      }

      // ----- Liste -----
      if (sub === 'liste') {
        const active = gw.items.filter(x => !x.ended);
        const ended = gw.items.filter(x => x.ended).sort((a, b) => b.endedAt - a.endedAt).slice(0, 5);
        const line = x => `**#${x.id}** — ${x.prize} • <#${x.channelId}> • ${x.entries.length} participant(s)`;
        const e = embed('info', `${emoji('reward')} Giveaways`)
          .addFields(
            { name: `En cours (${active.length})`, value: active.map(x => `${line(x)} • fin <t:${Math.floor(x.endAt / 1000)}:R>`).join('\n') || '*Aucun*' },
            { name: 'Récemment terminés', value: ended.map(x => `${line(x)}\n└ ${x.winners.length ? gwlib.mentions(x.winners) : 'aucun gagnant'}`).join('\n') || '*Aucun*' },
          );
        return i.reply({ embeds: [e], flags: 64 });
      }

      // ----- Config -----
      if (sub === 'config') {
        const vip = i.options.getRole('role_vip');
        const bl = i.options.getRole('role_blacklist');
        if (vip) gw.vipRole = vip.id;
        if (bl) {
          if (bl.id === i.guild.id || bl.managed) return reply(i, 'warn', `${emoji('error')} Ce rôle ne peut pas être utilisé comme rôle de blacklist.`, true);
          gw.blacklistRole = bl.id;
        }
        if (vip || bl) db.save();
        const vipId = gwlib.vipRoleId(i.guild, gw);
        const e = embed('info', `${emoji('config')} Réglages giveaway`, [
          `**Rôle VIP :** ${vipId ? `<@&${vipId}> (${gwlib.VIP_WEIGHT}× plus de chances)` : `*aucun* — crée un rôle nommé « VIP » ou utilise \`/giveaway config role_vip\``}`,
          `**Rôle blacklist :** ${gw.blacklistRole && i.guild.roles.cache.has(gw.blacklistRole) ? `<@&${gw.blacklistRole}>` : `*créé automatiquement au premier \`/giveaway blacklist ajouter\` (« ${gwlib.BLACKLIST_ROLE_NAME} »)*`}`,
          `**Blacklistés :** ${Object.keys(gw.blacklist).length}`,
        ].join('\n'));
        return i.reply({ embeds: [e], flags: 64 });
      }

      // ----- Terminer / annuler / reroll -----
      const { item, error } = resolve(i, { ended: sub === 'reroll' });
      if (error) return reply(i, 'warn', `${emoji('error')} ${error}`, true);

      if (sub === 'terminer' || sub === 'annuler') {
        if (item.ended) return reply(i, 'warn', `${emoji('error')} Le giveaway #${item.id} est déjà terminé (utilise \`/giveaway reroll\`).`, true);
        await i.deferReply({ flags: 64 });
        await gwlib.endGiveaway(i.guild, item, { cancel: sub === 'annuler' });
        const txt = sub === 'annuler'
          ? `${emoji('success')} Giveaway **#${item.id}** annulé.`
          : `${emoji('success')} Giveaway **#${item.id}** terminé : ${item.winners.length ? gwlib.mentions(item.winners) : 'aucun participant valide'}.`;
        return i.editReply({ embeds: [embed('ok', null, txt)] });
      }

      // reroll
      if (!item.ended) return reply(i, 'warn', `${emoji('error')} Le giveaway #${item.id} n'est pas terminé (utilise \`/giveaway terminer\`).`, true);
      const replace = i.options.getUser('remplacer');
      if (replace && !item.winners.includes(replace.id)) return reply(i, 'warn', `${emoji('error')} ${replace} n'est pas un gagnant de ce giveaway.`, true);
      await i.deferReply({ flags: 64 });
      const { winners } = await gwlib.rerollGiveaway(i.guild, item, { count: i.options.getInteger('gagnants') ?? 1, replace: replace?.id ?? null });
      if (!winners.length) return i.editReply({ embeds: [embed('warn', null, `${emoji('error')} Aucun participant éligible restant (anciens gagnants, blacklistés et départs exclus).`)] });
      return i.editReply({ embeds: [embed('ok', null, `${emoji('success')} Reroll du giveaway **#${item.id}** : ${gwlib.mentions(winners)}.`)] });
    },
  },
];
