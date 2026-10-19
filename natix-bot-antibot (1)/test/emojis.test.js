const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
require('./helpers');
const em = require('../src/emojis');

const ROOT = path.join(__dirname, '..');
const RESERVED = ['ticket', 'notification', 'games', 'reward']; // prévus pour de futures fonctions
const keys = Object.keys(em.CATALOG);

const sources = [path.join(ROOT, 'index.js'), ...['src', 'src/commands'].flatMap(d => fs.readdirSync(path.join(ROOT, d)).filter(f => f.endsWith('.js')).map(f => path.join(ROOT, d, f)))];
const code = sources.filter(f => !f.endsWith('emojis.js')).map(f => fs.readFileSync(f, 'utf8')).join('\n');
const used = new Set([...code.matchAll(/\bemoji\(\s*(?:[^'")]*\?\s*)?'(\w+)'(?:\s*:\s*'(\w+)')?/g)].flatMap(m => [m[1], m[2]].filter(Boolean)));

const fakeClient = ({ existing = [], failFetch = false, failCreate = [], guildEmojis = [] } = {}) => {
  const store = new Map(existing.map(e => [e.id, e]));
  let next = 9000;
  const created = [];
  return {
    created,
    application: { emojis: {
      fetch: async () => { if (failFetch) throw new Error('boom'); return store; },
      create: async ({ attachment, name }) => {
        if (failCreate.includes(name)) throw new Error('quota');
        assert.ok(fs.existsSync(attachment), `fichier introuvable : ${attachment}`);
        const e = { id: String(next++), name, animated: attachment.endsWith('.gif') };
        store.set(e.id, e); created.push(name); return e;
      },
    } },
    emojis: { cache: { find: fn => guildEmojis.find(fn) } },
  };
};
test.beforeEach(() => em._reset());

test('chaque emoji a son image valide (PNG ou GIF animé, ≤ 256 Ko, 128×128), sans fichier orphelin', () => {
  const files = fs.readdirSync(em.DIR);
  assert.deepStrictEqual([...files].sort(), keys.map(k => path.basename(em.fileOf(k))).sort());
  for (const k of keys) {
    const f = em.fileOf(k), buf = fs.readFileSync(f);
    assert.ok(buf.length <= 256 * 1024, `${k} trop lourd`);
    if (f.endsWith('.png')) { assert.strictEqual(buf.subarray(1, 4).toString(), 'PNG'); assert.deepStrictEqual([buf.readUInt32BE(16), buf.readUInt32BE(20)], [128, 128]); assert.strictEqual(buf[25], 6, `${k} doit avoir un canal alpha`); }
    else { assert.strictEqual(buf.subarray(0, 3).toString(), 'GIF'); assert.deepStrictEqual([buf.readUInt16LE(6), buf.readUInt16LE(8)], [128, 128]); assert.ok(em.CATALOG[k].animated); }
  }
});
test('pas de doublon : Unicode de secours uniques, emojis utilisés par le code, aucun emoji inutile', () => {
  const fb = keys.map(k => em.CATALOG[k].fallback);
  assert.strictEqual(new Set(fb).size, fb.length);
  for (const u of used) assert.ok(em.CATALOG[u], `emoji('${u}') absent du catalogue`);
  const unused = keys.filter(k => !used.has(k) && !RESERVED.includes(k));
  assert.deepStrictEqual(unused, [], 'emojis du catalogue jamais utilisés');
});
test('avant init / sans emoji personnalisé : Unicode de secours, jamais vide ni cassé', () => {
  for (const k of keys) { const v = em.emoji(k); assert.strictEqual(v, em.CATALOG[k].fallback); assert.doesNotMatch(v, /<a?:|:\w+:/); }
  assert.strictEqual(em.component('success'), '✅');
  assert.strictEqual(em.emoji('nimporte_quoi'), '');
});
test('init : téléverse les manquants, garde les identifiants existants, gère animé / statique', async () => {
  const c = fakeClient({ existing: [{ id: '111', name: 'nx_success', animated: false }, { id: '222', name: 'autre', animated: false }] });
  const r = await em.init(c);
  assert.strictEqual(r.custom, keys.length); assert.deepStrictEqual(r.missing, []);
  assert.strictEqual(c.created.length, keys.length - 1);
  assert.ok(!c.created.includes('nx_success'));
  assert.strictEqual(em.emoji('success'), '<:nx_success:111>');
  assert.match(em.emoji('loading'), /^<a:nx_loading:\d+>$/);
  assert.match(em.emoji('error'), /^<:nx_error:\d+>$/);
  assert.deepStrictEqual(em.component('success'), { id: '111', name: 'nx_success', animated: false });
  const again = fakeClient({ existing: [...await c.application.emojis.fetch().then(m => m.values())] });
  await em.init(again); assert.strictEqual(again.created.length, 0, 'deuxième démarrage = aucun téléversement');
});
test('init : jamais d\'exception, secours Unicode (API KO, quota, désactivé, upload coupé)', async () => {
  await em.init(fakeClient({ failFetch: true }));
  assert.strictEqual(em.status().custom, 0); assert.strictEqual(em.emoji('error'), '❌');
  await em.init(fakeClient({ failCreate: ['nx_lock', 'nx_error'] }));
  assert.deepStrictEqual(em.status().missing.sort(), ['error', 'lock']);
  assert.strictEqual(em.emoji('lock'), '🔒'); assert.match(em.emoji('success'), /^<:nx_success:/);
  await em.init(fakeClient(), { disabled: true }); assert.strictEqual(em.status().custom, 0);
  const c = fakeClient(); await em.init(c, { upload: false }); assert.strictEqual(c.created.length, 0); assert.strictEqual(em.emoji('info'), 'ℹ️');
});
test('init : emojis nx_* installés à la main sur un serveur utilisés en secours', async () => {
  await em.init(fakeClient({ failFetch: true, guildEmojis: [{ id: '777', name: 'nx_ticket', animated: false, available: true }, { id: '778', name: 'nx_games', animated: false, available: false }] }));
  assert.strictEqual(em.emoji('ticket'), '<:nx_ticket:777>'); assert.strictEqual(em.emoji('games'), '🎮');
});
test('localize : salon sans « émojis externes » → Unicode ; avec → inchangé ; MP → inchangé', async () => {
  await em.init(fakeClient());
  const payload = { content: `${em.emoji('security')} x`, embeds: [{ toJSON: () => ({ title: `${em.emoji('loading')} t`, fields: [{ name: em.emoji('lock'), value: 'v' }] }) }],
    components: [{ components: [{ type: 2, emoji: em.component('success') }] }] };
  const chan = ext => ({ guild: { members: { me: {} } }, permissionsFor: () => ({ has: p => p === 'UseExternalEmojis' && ext }) });
  assert.strictEqual(em.localize(payload, chan(true)), payload);
  assert.strictEqual(em.localize(payload, {}), payload);
  const out = em.localize(payload, chan(false));
  assert.strictEqual(out.content, '🛡️ x'); assert.strictEqual(out.embeds[0].title, '⏳ t'); assert.strictEqual(out.embeds[0].fields[0].name, '🔒');
  assert.deepStrictEqual(out.components[0].components[0].emoji, { name: '✅' });
  assert.doesNotMatch(JSON.stringify(out), /<a?:nx_/);
});
test('limites Discord : un emoji personnalisé tient dans un titre d\'embed (256) et ne dépasse pas 40 caractères', async () => {
  await em.init(fakeClient());
  for (const k of keys) assert.ok(em.emoji(k).length <= 40, k);
});
