const test = require('node:test');
const assert = require('node:assert');
require('./helpers');
const { PermissionFlagsBits: P } = require('discord.js');
const { loadCommands, validate, buildPayload, verifyRegistered } = require('../src/commandRegistry');
const { PUBLIC_COMMANDS } = require('../src/commandPolicy');

const EXPECTED = {
  ban: P.BanMembers, tempban: P.BanMembers, unban: P.BanMembers, kick: P.KickMembers,
  mute: P.ModerateMembers, unmute: P.ModerateMembers, warn: P.ModerateMembers, warns: P.ModerateMembers, unwarn: P.ModerateMembers, clearwarns: P.ModerateMembers,
  clear: P.ManageMessages, speak: P.ManageMessages, lock: P.ManageChannels, unlock: P.ManageChannels, slowmode: P.ManageChannels,
  giveaway: P.ManageGuild, invitetracker: P.ManageGuild, setlogs: P.ManageGuild, automod: P.ManageGuild, diagnostic: P.ManageGuild, unbot: P.ManageGuild,
  aide: null, userinfo: null, serverinfo: null, invites: null,
};
const list = loadCommands();
const by = Object.fromEntries(list.map(c => [c.data.name, c]));

test('25 commandes chargées, aucune inconnue', () => {
  assert.strictEqual(list.length, 25);
  assert.deepStrictEqual(Object.keys(by).sort(), Object.keys(EXPECTED).sort());
});
test('commandes publiques = sans restriction par défaut', () => {
  assert.deepStrictEqual([...PUBLIC_COMMANDS].sort(), ['aide', 'invites', 'serverinfo', 'userinfo']);
  for (const n of PUBLIC_COMMANDS) assert.strictEqual(by[n].requiredPerms, null, `/${n}`);
});
test('commandes de gestion = permission attendue conservée', () => {
  for (const [n, perm] of Object.entries(EXPECTED)) if (perm != null) assert.strictEqual(by[n].requiredPerms, BigInt(perm), `/${n}`);
});
test('payload envoyé à Discord : public → pas de restriction, gestion → restriction, serveur uniquement', () => {
  const payload = Object.fromEntries(buildPayload(list).map(c => [c.name, c]));
  for (const [n, perm] of Object.entries(EXPECTED)) {
    const raw = payload[n].default_member_permissions;
    if (perm == null) assert.ok(raw == null, `/${n} ne doit pas être restreinte`); else assert.strictEqual(BigInt(raw), BigInt(perm), `/${n}`);
    assert.deepStrictEqual(payload[n].contexts, [0], `/${n} serveur uniquement`);
  }
});
test('fail-closed : commande non listée sans restriction → refusée', () => {
  const fakeCmd = { data: { name: 'oups' }, requiredPerms: null, isPublic: false };
  assert.throws(() => validate([...list, fakeCmd]), /\/oups/);
});
test('fail-safe : commande publique restreinte → refusée', () => {
  assert.throws(() => validate(list.map(c => c.data.name === 'aide' ? { ...c, requiredPerms: 8n } : c)), /\/aide/);
});
test('verifyRegistered détecte une commande publique restreinte par Discord', () => {
  const ok = list.map(c => ({ name: c.data.name, defaultMemberPermissions: c.requiredPerms == null ? null : { bitfield: c.requiredPerms } }));
  assert.deepStrictEqual(verifyRegistered(list, ok), []);
  const bad = ok.map(r => r.name === 'aide' ? { ...r, defaultMemberPermissions: { bitfield: 8n } } : r);
  assert.match(verifyRegistered(list, bad)[0], /\/aide/);
});
