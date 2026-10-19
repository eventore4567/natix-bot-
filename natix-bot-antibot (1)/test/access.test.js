const test = require('node:test');
const assert = require('node:assert');
const { canUseCommand, allChannelsId } = require('../src/access');

const G = '1000', CH = '2000', APP = '3000';
const base = { guildId: G, channelId: CH, userId: '42', roleIds: [], isAdmin: false, native: { guild: true, channel: true }, commandPerms: null, appPerms: [], defaultMemberPermissions: null, memberPerms: 0n };
const BAN = 1n << 2n, MANAGE_GUILD = 1n << 5n;
const run = o => canUseCommand({ ...base, ...o });

test('membre @everyone : commande publique OK', () => assert.strictEqual(run({}).allowed, true));
test('membre @everyone : /ban refusé (permission manquante)', () => {
  const r = run({ defaultMemberPermissions: BAN });
  assert.deepStrictEqual([r.allowed, r.code], [false, 'default-perms']);
});
test('modérateur avec BanMembers : /ban OK', () => assert.strictEqual(run({ defaultMemberPermissions: BAN, memberPerms: BAN }).allowed, true));
test('administrateur : tout OK', () => assert.strictEqual(run({ isAdmin: true, defaultMemberPermissions: MANAGE_GUILD, native: { guild: false, channel: false } }).code, 'admin'));
test('REPRO du bug : @everyone refusé dans #commandes → bloqué, cause native-channel', () => {
  const r = run({ native: { guild: true, channel: false } });
  assert.deepStrictEqual([r.allowed, r.code], [false, 'native-channel']);
});
test('refus au niveau serveur → native-guild', () => assert.strictEqual(run({ native: { guild: false, channel: true } }).code, 'native-guild'));
test('Intégrations : salon refusé pour le bot → integration-channel', () => {
  assert.strictEqual(run({ appPerms: [{ id: CH, type: 3, permission: false }] }).code, 'integration-channel');
});
test('Intégrations : « tous les salons » refusé, salon précis autorisé → OK', () => {
  const r = run({ appPerms: [{ id: allChannelsId(G), type: 3, permission: false }, { id: CH, type: 3, permission: true }] });
  assert.strictEqual(r.allowed, true);
});
test('Intégrations : @everyone refusé pour une commande → integration-deny', () => {
  assert.strictEqual(run({ commandPerms: [{ id: G, type: 1, permission: false }] }).code, 'integration-deny');
});
test('Intégrations : rôle autorisé bat @everyone refusé', () => {
  const r = run({ roleIds: ['7'], commandPerms: [{ id: G, type: 1, permission: false }, { id: '7', type: 1, permission: true }] });
  assert.strictEqual(r.allowed, true);
});
test('Intégrations : surcharge utilisateur prioritaire', () => {
  const r = run({ roleIds: ['7'], commandPerms: [{ id: '7', type: 1, permission: true }, { id: '42', type: 2, permission: false }] });
  assert.strictEqual(r.code, 'integration-deny');
});
test('surcharge de la commande prioritaire sur celle du bot entier', () => {
  const r = run({ commandPerms: [{ id: G, type: 1, permission: true }], appPerms: [{ id: G, type: 1, permission: false }] });
  assert.strictEqual(r.allowed, true);
});
test('allChannelsId = guildId - 1 (sans perte de précision)', () => assert.strictEqual(allChannelsId('1100000000000000001'), '1100000000000000000'));
