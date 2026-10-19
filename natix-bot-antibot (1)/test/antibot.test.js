const test = require('node:test');
const assert = require('node:assert');
require('./helpers');
const antibot = require('../src/antibot');
const dbmod = require('../src/db');

function mkMember(id, bot, { kickFails = false, guildId = 'ab1' } = {}) {
  const kicked = [];
  return {
    kicked, id, user: { id, bot, tag: 'u' + id }, client: { user: { id: 'me' } },
    kick: async r => { if (kickFails) throw new Error('Missing Permissions'); kicked.push(r); },
    guild: { id: guildId, channels: { cache: new Map() }, fetchAuditLogs: async () => { throw new Error('no'); } },
  };
}
test('désactivé par défaut : un bot qui rejoint n\'est pas expulsé', async () => {
  delete dbmod.allGuilds().ab1;
  const m = mkMember('b1', true);
  assert.strictEqual(await antibot.onMemberAdd(m), false);
  assert.strictEqual(m.kicked.length, 0);
});
test('activé : un bot est expulsé, un humain non, le bot lui-même jamais', async () => {
  antibot.setEnabled('ab1', true);
  assert.strictEqual(antibot.isEnabled('ab1'), true);
  const bot = mkMember('b2', true), human = mkMember('h1', false), self = mkMember('me', true);
  assert.strictEqual(await antibot.onMemberAdd(bot), true);
  assert.strictEqual(bot.kicked.length, 1);
  assert.strictEqual(await antibot.onMemberAdd(human), false);
  assert.strictEqual(await antibot.onMemberAdd(self), false);
  assert.strictEqual(human.kicked.length + self.kicked.length, 0);
});
test('expulsion impossible : ne plante pas, renvoie false', async () => {
  assert.strictEqual(await antibot.onMemberAdd(mkMember('b3', true, { kickFails: true })), false);
});
test('désactivé à nouveau : plus d\'expulsion', async () => {
  antibot.setEnabled('ab1', false);
  const m = mkMember('b4', true);
  assert.strictEqual(await antibot.onMemberAdd(m), false);
  assert.strictEqual(m.kicked.length, 0);
});
