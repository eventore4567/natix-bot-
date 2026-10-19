// Minimal stand-in for discord.js, used ONLY when the real package is not installed
// (lets the permission wiring of the real command files be tested offline).
const chain = () => new Proxy(function () {}, { get: (_, k) => (k === 'then' ? undefined : chain()), apply: () => chain() });
class SlashCommandBuilder {
  constructor() { this.options = []; }
  setName(n) { this.name = n; return this; }
  setDescription(d) { this.description = d; return this; }
  setDefaultMemberPermissions(p) { this.default_member_permissions = p == null ? null : String(p); return this; }
  setContexts(...c) { this.contexts = c.flat(); return this; }
  setIntegrationTypes(...c) { this.integration_types = c.flat(); return this; }
  toJSON() { return { name: this.name, description: this.description, default_member_permissions: this.default_member_permissions ?? null, contexts: this.contexts, integration_types: this.integration_types }; }
}
for (const m of ['addUserOption', 'addStringOption', 'addIntegerOption', 'addChannelOption', 'addBooleanOption', 'addRoleOption', 'addSubcommand', 'addSubcommandGroup']) SlashCommandBuilder.prototype[m] = function () { return this; };
const bit = n => 1n << BigInt(n);
const PermissionFlagsBits = { KickMembers: bit(1), BanMembers: bit(2), Administrator: bit(3), ManageChannels: bit(4), ManageGuild: bit(5), ManageMessages: bit(13), UseApplicationCommands: bit(31), ModerateMembers: bit(40) };
const B = class { constructor() { return chain(); } };
module.exports = { ActionRowBuilder: B, ButtonBuilder: B, ButtonStyle: { Primary: 1, Secondary: 2 }, SlashCommandBuilder, PermissionFlagsBits, PermissionsBitField: { Flags: PermissionFlagsBits }, ChannelType: { GuildText: 0, GuildAnnouncement: 5 },
  MessageFlags: { Ephemeral: 64 }, EmbedBuilder: class { constructor() { return chain(); } }, __fake: true };
