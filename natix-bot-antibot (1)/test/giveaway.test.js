const test = require('node:test');
const assert = require('node:assert');
require('./helpers');
const gw = require('../src/giveaway');

// ----- Faux serveur minimal -----
const mkRoles = names => { const m = new Map(names.map(([id, name]) => [id, { id, name, position: 1 }])); m.find = f => [...m.values()].find(f); return m; };
function mkMember(id, roleIds = [], bot = false) {
  const roles = new Set(roleIds);
  const cache = { has: r => roles.has(r) };
  return { id, user: { id, bot, tag: 'u' + id }, roles: { cache, add: async r => { roles.add(r.id ?? r); }, remove: async r => { roles.delete(r.id ?? r); } } };
}
function mkGuild(id, members) {
  const sent = [];
  const roles = mkRoles([['vip', 'VIP']]);
  const msg = { id: 'm1', edit: async () => {}, delete: async () => {} };
  const channel = { id: 'c1', send: async p => { sent.push(p); return msg; }, messages: { fetch: async () => msg }, permissionsFor: () => ({ has: () => true }), guild: null };
  const g = {
    id, roles: { cache: roles, create: async o => { const r = { id: 'bl', name: o.name, position: 1 }; roles.set('bl', r); return r; }, everyone: { id } },
    members: { cache: new Map(members.map(m => [m.id, m])), fetch: async a => (typeof a === 'object' ? new Map(a.user.filter(u => members.some(m => m.id === u)).map(u => [u, members.find(m => m.id === u)])) : members.find(m => m.id === a) ?? Promise.reject(new Error('x'))), me: { permissions: { has: () => true }, roles: { highest: { position: 10 } } } },
    channels: { cache: new Map([['c1', channel]]), fetch: async () => channel },
  };
  g.channels.cache.get('c1').guild = g;
  return { g, channel, sent };
}
const dbmod = require('../src/db');
const fresh = id => { delete dbmod.allGuilds()[id]; };

test('pickWinners : pondéré, sans doublon, borné par le nombre de participants', () => {
  const entries = [{ id: 'a', weight: 1 }, { id: 'b', weight: 1 }, { id: 'c', weight: 2 }];
  const w = gw.pickWinners(entries, 5);
  assert.deepStrictEqual([...w].sort(), ['a', 'b', 'c']);
  assert.deepStrictEqual(gw.pickWinners([], 3), []);
  assert.strictEqual(new Set(gw.pickWinners(entries, 2)).size, 2);
});
test('pickWinners : un VIP (poids 2) gagne ~2x plus souvent', () => {
  const N = 40000; let vip = 0, normal = 0;
  for (let k = 0; k < N; k++) { const [w] = gw.pickWinners([{ id: 'vip', weight: 2 }, { id: 'n', weight: 1 }], 1); w === 'vip' ? vip++ : normal++; }
  const ratio = vip / normal;
  assert.ok(ratio > 1.9 && ratio < 2.1, `ratio ${ratio}`);
});
test('pickWinners : rng déterministe (bornes)', () => {
  const e = [{ id: 'a', weight: 1 }, { id: 'b', weight: 2 }];
  assert.deepStrictEqual(gw.pickWinners(e, 1, () => 0), ['a']);
  assert.deepStrictEqual(gw.pickWinners(e, 1, () => 0.34), ['b']);
  assert.deepStrictEqual(gw.pickWinners(e, 1, () => 0.999999), ['b']);
});

test('blacklist : ajoute le rôle, retire des giveaways en cours, bloque la participation, puis retire le rôle', async () => {
  fresh('G1');
  const alice = mkMember('alice'), bob = mkMember('bob');
  const { g, channel } = mkGuild('G1', [alice, bob]);
  const item = await gw.createGiveaway(g, channel, { prize: 'Nitro', durationMs: 60000, winnersCount: 1, host: { id: 'host' } });
  item.entries.push('alice', 'bob');

  const res = await gw.blacklistAdd(g, { id: 'bob', tag: 'bob' }, { by: { id: 'mod' }, reason: 'triche' });
  assert.strictEqual(res.warning, null);
  assert.ok(bob.roles.cache.has('bl'), 'bob a reçu le rôle');
  assert.deepStrictEqual(item.entries, ['alice'], 'bob retiré des giveaways en cours');

  let reply;
  await gw.handleButton({ customId: `gw:join:${item.id}`, guild: g, member: bob, reply: async r => { reply = r; } });
  assert.match(reply.content, /blacklist/);
  assert.deepStrictEqual(item.entries, ['alice']);

  const out = await gw.blacklistRemove(g, { id: 'bob', tag: 'bob' }, { by: { id: 'mod' } });
  assert.ok(out.had);
  assert.ok(!bob.roles.cache.has('bl'), 'rôle retiré');
  await gw.handleButton({ customId: `gw:join:${item.id}`, guild: g, member: bob, reply: async r => { reply = r; } });
  assert.deepStrictEqual(item.entries, ['alice', 'bob']);
});

test('rôle de blacklist posé à la main = participation refusée aussi', async () => {
  fresh('G2');
  const carl = mkMember('carl', ['bl']);
  const { g, channel } = mkGuild('G2', [carl]);
  const store = gw.store('G2'); store.blacklistRole = 'bl';
  const item = await gw.createGiveaway(g, channel, { prize: 'x', durationMs: 60000, winnersCount: 1, host: { id: 'h' } });
  let reply; await gw.handleButton({ customId: `gw:join:${item.id}`, guild: g, member: carl, reply: async r => { reply = r; } });
  assert.match(reply.content, /blacklist/); assert.deepStrictEqual(item.entries, []);
});

test('participer deux fois = se retirer', async () => {
  fresh('G3');
  const d = mkMember('d'); const { g, channel } = mkGuild('G3', [d]);
  const item = await gw.createGiveaway(g, channel, { prize: 'x', durationMs: 60000, winnersCount: 1, host: { id: 'h' } });
  const click = () => gw.handleButton({ customId: `gw:join:${item.id}`, guild: g, member: d, reply: async () => {} });
  await click(); assert.deepStrictEqual(item.entries, ['d']);
  await click(); assert.deepStrictEqual(item.entries, []);
});

test('tirage : exclut blacklistés, bots et membres partis ; VIP = poids 2 (rôle nommé « VIP » détecté)', async () => {
  fresh('G4');
  const vip = mkMember('vip1', ['vip']), norm = mkMember('n1'), bl = mkMember('bl1'), bot = mkMember('bot1', [], true);
  const { g, channel } = mkGuild('G4', [vip, norm, bl, bot]);
  const item = await gw.createGiveaway(g, channel, { prize: 'x', durationMs: 60000, winnersCount: 1, host: { id: 'h' } });
  gw.store('G4').blacklist.bl1 = { by: 'm', reason: 'r', date: 1 };
  item.entries.push('vip1', 'n1', 'bl1', 'bot1', 'parti');
  const e = await gw.eligibleEntries(g, item);
  assert.deepStrictEqual(e, [{ id: 'vip1', weight: 2 }, { id: 'n1', weight: 1 }]);
});

test('fin + reroll : jamais un ancien gagnant ; reroll ciblé remplace ; plus personne → liste vide', async () => {
  fresh('G5');
  const ms = ['a', 'b', 'c', 'd'].map(id => mkMember(id));
  const { g, channel, sent } = mkGuild('G5', ms);
  const item = await gw.createGiveaway(g, channel, { prize: 'Lot', durationMs: 60000, winnersCount: 2, host: { id: 'h' } });
  item.entries.push('a', 'b', 'c', 'd');
  await gw.endGiveaway(g, item);
  assert.strictEqual(item.ended, true);
  assert.strictEqual(item.winners.length, 2);
  assert.ok(sent.at(-1).content.includes('Lot'));
  assert.strictEqual(await gw.endGiveaway(g, item), null, 'pas de double fin');

  const first = [...item.winners];
  const r1 = await gw.rerollGiveaway(g, item, { count: 1 });
  assert.strictEqual(r1.winners.length, 1);
  assert.ok(!first.includes(r1.winners[0]));
  const r2 = await gw.rerollGiveaway(g, item, { replace: first[0] });
  assert.strictEqual(r2.winners.length, 1);
  assert.ok(!item.winners.includes(first[0]), 'remplacé');
  assert.ok(![...first, ...r1.winners].includes(r2.winners[0]), 'pas un ancien gagnant');
  const r3 = await gw.rerollGiveaway(g, item, { count: 1 });
  assert.deepStrictEqual(r3.winners, [], 'tout le monde a déjà gagné');
});

test('tick : termine seulement les giveaways échus', async () => {
  fresh('G6');
  const a = mkMember('a'); const { g, channel } = mkGuild('G6', [a]);
  const due = await gw.createGiveaway(g, channel, { prize: 'due', durationMs: 60000, winnersCount: 1, host: { id: 'h' } });
  const later = await gw.createGiveaway(g, channel, { prize: 'later', durationMs: 60000, winnersCount: 1, host: { id: 'h' } });
  due.endAt = Date.now() - 1; due.entries.push('a');
  await gw.tick({ guilds: { cache: new Map([['G6', g]]) } });
  assert.strictEqual(due.ended, true); assert.deepStrictEqual(due.winners, ['a']);
  assert.strictEqual(later.ended, false);
});
