require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { Client, GatewayIntentBits, Partials, Collection, ActivityType, MessageFlags, Events, PermissionsBitField } = require('discord.js');
const db = require('./src/db');
const automod = require('./src/automod');
const { embed, sendLog } = require('./src/utils');
const { loadCommands, buildPayload, verifyRegistered } = require('./src/commandRegistry');
const emojis = require('./src/emojis');
const giveaway = require('./src/giveaway');
const invites = require('./src/invites');
const antibot = require('./src/antibot');
const { emoji } = emojis;

if (!process.env.DISCORD_TOKEN) {
  console.error('❌ Token manquant : mets DISCORD_TOKEN=... dans le fichier .env');
  process.exit(1);
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildModeration,
    GatewayIntentBits.GuildInvites,   // invite tracker
  ],
  partials: [Partials.Message, Partials.Channel],
});

// Chargement des commandes.
// Les permissions par défaut sont CONSERVÉES : commandes publiques (voir src/commandPolicy.js) = visibles par @everyone,
// commandes de gestion = cachées aux membres sans la permission requise (et revérifiées à l'exécution).
const commandList = loadCommands();
client.commands = new Collection(commandList.map(c => [c.data.name, c]));
const commandData = buildPayload(commandList);

async function registerCommands(guild) {
  try {
    const registered = await guild.commands.set(commandData);
    const problems = verifyRegistered(commandList, registered.values());
    if (problems.length) console.warn(`⚠️ [${guild.name}] Commandes enregistrées différentes de la politique :\n  - ${problems.join('\n  - ')}`);
    else console.log(`✅ [${guild.name}] ${registered.size} commandes synchronisées (${commandList.filter(c => c.isPublic).length} publiques, ${commandList.filter(c => !c.isPublic).length} de gestion).`);

    // Réglages Discord que le bot ne peut ni changer ni contourner : on avertit seulement.
    const F = PermissionsBitField.Flags;
    const everyone = guild.roles.everyone;
    if (!everyone.permissions.has(F.UseApplicationCommands)) {
      console.warn(`⚠️ [${guild.name}] @everyone n'a PAS « Utiliser les commandes d'application » au niveau du serveur → les membres ne verront aucune commande (Paramètres du serveur → Rôles → @everyone).`);
    }
    const blocked = guild.channels.cache.filter(ch => !ch.isThread() && ch.isTextBased() && ch.permissionsFor(everyone)?.has(F.ViewChannel) && !ch.permissionsFor(everyone)?.has(F.UseApplicationCommands));
    if (blocked.size) console.warn(`⚠️ [${guild.name}] Salons visibles par @everyone où les commandes sont refusées : ${blocked.map(c => '#' + c.name).join(', ')} (Modifier le salon → Permissions → @everyone → « Utiliser les commandes d'application »). Détail : /diagnostic`);
  } catch (e) {
    console.error(`⚠️ Impossible d'enregistrer les commandes sur ${guild.name} :`, e.message,
      e.code === 50001 ? '→ Le bot a été invité sans le scope "applications.commands". Ré-invite-le avec ce scope.' : '');
  }
}

client.once(Events.ClientReady, async () => {
  console.log(`✅ Connecté en tant que ${client.user.tag} sur ${client.guilds.cache.size} serveur(s)`);
  client.user.setActivity('le serveur 👀 | /aide', { type: ActivityType.Watching }); // le statut d'un bot n'accepte que l'Unicode
  // Emojis personnalisés : chargés (et téléversés si besoin) AVANT d'accepter des commandes, sinon Unicode de secours.
  const er = await emojis.init(client);
  console.log(`${er.custom === er.total ? '✅' : '⚠️'} Emojis personnalisés : ${er.custom}/${er.total} (${er.source})${er.uploaded.length ? ` — ${er.uploaded.length} téléversé(s)` : ''}${er.missing.length ? ` — Unicode de secours pour : ${er.missing.join(', ')}` : ''}`);
  // Supprime d'anciennes commandes GLOBALES (anciennes versions du bot) qui gardaient les permissions restreintes
  // et créaient des doublons cachés pour certains rôles.
  await client.application.commands.set([]).catch(e => console.error('⚠️ Nettoyage des commandes globales impossible :', e.message));
  // Commandes par serveur = disponibles instantanément
  for (const guild of client.guilds.cache.values()) await registerCommands(guild);
  console.log(`📋 ${commandData.length} commandes enregistrées.`);
  for (const guild of client.guilds.cache.values()) await invites.refresh(guild); // invite tracker : état de départ des invitations
  checkTempbans();
  setInterval(checkTempbans, 30e3);
  giveaway.tick(client).catch(e => console.error('Erreur giveaways :', e.message));
  setInterval(() => giveaway.tick(client).catch(e => console.error('Erreur giveaways :', e.message)), 15e3);
});

client.on(Events.GuildCreate, guild => {
  console.log(`➕ Ajouté sur ${guild.name}`);
  registerCommands(guild);
  invites.refresh(guild);
});

// Commandes slash
client.on(Events.InteractionCreate, async interaction => {
  // Bouton « Participer » des giveaways (fonctionne aussi après un redémarrage)
  if (interaction.isButton() && interaction.customId.startsWith('gw:')) {
    if (!interaction.guild) return;
    return giveaway.handleButton(interaction).catch(e => {
      console.error('Erreur bouton giveaway :', e);
      const payload = { content: `${emoji('error')} Une erreur est survenue, réessaie.`, flags: MessageFlags.Ephemeral };
      (interaction.replied || interaction.deferred ? interaction.followUp(payload) : interaction.reply(payload)).catch(() => {});
    });
  }
  if (!interaction.isChatInputCommand()) return;
  if (!interaction.guild) return interaction.reply({ content: `${emoji('error')} Ces commandes sont utilisables uniquement sur un serveur.`, flags: MessageFlags.Ephemeral }).catch(() => {});
  const cmd = client.commands.get(interaction.commandName);
  if (!cmd) return;
  // Défense en profondeur : même si Discord laisse passer (réglages Intégrations modifiés), les commandes de gestion
  // exigent la permission correspondante. Les commandes publiques (requiredPerms = null) passent toujours ici.
  if (cmd.requiredPerms && !interaction.memberPermissions?.has(cmd.requiredPerms)) {
    const names = new PermissionsBitField(cmd.requiredPerms).toArray().join(', ');
    return interaction.reply({ embeds: [embed('ban', null, `${emoji('denied')} Tu n'as pas la permission d'utiliser cette commande. (Permission requise : \`${names}\`)`)], flags: MessageFlags.Ephemeral }).catch(() => {});
  }
  try {
    await cmd.execute(interaction);
  } catch (e) {
    console.error(`Erreur /${interaction.commandName} :`, e);
    let msg = e.code === 50013 ? "Je n'ai pas la permission de faire ça. Vérifie mes permissions et que mon rôle est assez haut." : `Une erreur est survenue : ${e.message}`;
    const payload = { embeds: [embed('ban', null, `${emoji('error')} ${msg}`)], flags: MessageFlags.Ephemeral };
    if (interaction.replied || interaction.deferred) interaction.followUp(payload).catch(() => {});
    else interaction.reply(payload).catch(() => {});
  }
});

// Automod
client.on(Events.MessageCreate, message => {
  automod.check(message).catch(e => console.error('Erreur automod :', e.message));
});
client.on(Events.MessageUpdate, (oldMsg, newMsg) => {
  if (newMsg.partial || oldMsg.content === newMsg.content) return;
  automod.check(newMsg).catch(() => {});
});

// ===== Logs =====
const cut = (s, n = 1000) => (s && s.length > n ? s.slice(0, n) + '…' : s || '*vide*');

client.on(Events.MessageDelete, message => {
  if (!message.guild || message.partial || message.author?.bot) return;
  sendLog(message.guild, embed('log', `${emoji('delete')} Message supprimé`)
    .addFields(
      { name: 'Auteur', value: `${message.author} (\`${message.author.id}\`)`, inline: true },
      { name: 'Salon', value: `${message.channel}`, inline: true },
      { name: 'Contenu', value: cut(message.content) },
    ));
});

client.on(Events.MessageUpdate, (oldMsg, newMsg) => {
  if (!newMsg.guild || oldMsg.partial || newMsg.author?.bot || oldMsg.content === newMsg.content) return;
  sendLog(newMsg.guild, embed('info', `${emoji('edit')} Message modifié`)
    .setURL(newMsg.url)
    .addFields(
      { name: 'Auteur', value: `${newMsg.author}`, inline: true },
      { name: 'Salon', value: `${newMsg.channel}`, inline: true },
      { name: 'Avant', value: cut(oldMsg.content) },
      { name: 'Après', value: cut(newMsg.content) },
    ));
});

client.on(Events.InviteCreate, invite => invites.onInviteCreate(invite));
client.on(Events.InviteDelete, invite => invites.onInviteDelete(invite));

client.on(Events.GuildMemberAdd, async member => {
  antibot.onMemberAdd(member).catch(e => console.error('Erreur anti-bot :', e.message)); // expulse les bots si /unbot activate
  giveaway.onMemberAdd(member); // un blacklisté qui revient récupère son rôle
  const info = await invites.onMemberAdd(member).catch(e => { console.error('Erreur invite tracker :', e.message); return null; });
  if (info) invites.announce(member.guild, 'join', member, info).catch(() => {});
  const age = Date.now() - member.user.createdTimestamp;
  sendLog(member.guild, embed('ok', `${emoji('join')} Arrivée`)
    .setThumbnail(member.user.displayAvatarURL())
    .setDescription(`${member} (\`${member.user.tag}\`)\nCompte créé <t:${Math.floor(member.user.createdTimestamp / 1000)}:R>${age < 7 * 864e5 ? `\n${emoji('warning')} **Compte récent (moins de 7 jours)**` : ''}\nMembres : **${member.guild.memberCount}**${info ? `\n${emoji('join')} ${invites.who(info)}` : ''}`));
});

client.on(Events.GuildMemberRemove, member => {
  const info = invites.onMemberRemove(member);
  if (info) invites.announce(member.guild, 'leave', member, info).catch(() => {});
  sendLog(member.guild, embed('ban', `${emoji('leave')} Départ`)
    .setThumbnail(member.user.displayAvatarURL())
    .setDescription(`${member.user.tag} (\`${member.id}\`)\nMembres : **${member.guild.memberCount}**${info?.inviterId ? `\nInvité par <@${info.inviterId}>` : ''}`));
});

// ===== Tempbans : débannissement automatique =====
async function checkTempbans() {
  const now = Date.now();
  for (const [guildId, g] of Object.entries(db.allGuilds())) {
    const due = (g.tempbans || []).filter(t => t.until <= now);
    if (!due.length) continue;
    const guild = client.guilds.cache.get(guildId);
    if (!guild) continue;
    for (const t of due) {
      const user = await client.users.fetch(t.userId).catch(() => null);
      await guild.members.unban(t.userId, 'Fin du ban temporaire').catch(() => {});
      sendLog(guild, embed('ok', `${emoji('unlock')} Fin du ban temporaire`, `${user ? user.tag : t.userId} (\`${t.userId}\`) a été débanni automatiquement.`));
    }
    g.tempbans = g.tempbans.filter(t => t.until > now);
    db.save();
  }
}

process.on('unhandledRejection', e => console.error('Erreur :', e?.message || e));

client.login(process.env.DISCORD_TOKEN).catch(e => {
  console.error('❌ Connexion impossible :', e.message);
  if (/disallowed intents/i.test(e.message)) console.error('👉 Active "Server Members Intent" et "Message Content Intent" sur le Developer Portal (onglet Bot).');
  process.exit(1);
});
