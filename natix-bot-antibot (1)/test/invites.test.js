const test = require('node:test');
const assert = require('node:assert');
require('./helpers');
const inv = require('../src/invites');
const dbmod = require('../src/db');
const fresh = id => { delete dbmod.allGuilds()[id]; };

const E = (uses, inviterId = 'A', maxUses = 0, extra = {}) => ({ uses, inviterId, maxUses, ...extra });
const L = (code, uses, inviterId = 'A', maxUses = 0) => ({ code, uses, inviterId, maxUses });

test('detectUsed : trouve l\'invitation dont le compteur a augmenté', () => {
  const before = new Map([['x', E(1, 'A')], ['y', E(4, 'B')]]);
  assert.deepStrictEqual(inv.detectUsed(before, [L('x', 1, 'A'), L('y', 5, 'B')]), { code: 'y', inviterId: 'B' });
});
test('detectUsed : invitation créée puis utilisée, inconnue du cache', () => {
  assert.strictEqual(inv.detectUsed(new Map(), [L('n', 1, 'C')]).code, 'n');
});
test('detectUsed : invitation à usage unique supprimée par Discord après usage', () => {
  const before = new Map([['one', E(0, 'A', 1)], ['y', E(4, 'B')]]);
  assert.deepStrictEqual(inv.detectUsed(before, [L('y', 4, 'B')]), { code: 'one', inviterId: 'A' });
});
test('detectUsed : invitation supprimée à la main il y a longtemps = ignorée', () => {
  const before = new Map([['old', E(0, 'A', 1, { deletedAt: 1000 })]]);
  assert.strictEqual(inv.detectUsed(before, [], 1000 + 60e3).code, null);
});
test('detectUsed : plusieurs candidats = ambigu, on ne devine pas', () => {
  const before = new Map([['x', E(1)], ['y', E(1, 'B')]]);
  const r = inv.detectUsed(before, [L('x', 2), L('y', 2, 'B')]);
  assert.strictEqual(r.code, null);
  assert.strictEqual(r.ambiguous, true);
});
test('detectUsed : aucun changement = rien (lien vanity / OAuth)', () => {
  assert.strictEqual(inv.detectUsed(new Map([['x', E(1)]]), [L('x', 1)]).code, null);
});

// ----- Faux serveur : arrivée / départ / retour -----
function mkGuild(id, invites) {
  const g = { id, name: 'S', vanityURLCode: null, invites: { fetch: async () => new Map((g._script?.shift() ?? g._inv).map(i => [i.code, { code: i.code, uses: i.uses, maxUses: i.maxUses ?? 0, inviter: i.inviterId ? { id: i.inviterId } : null }])) }, _inv: invites };
  return g;
}
const mkMember = (guild, id, ageDays = 100) => ({ id, guild, user: { id, bot: false, tag: 'u' + id, createdTimestamp: Date.now() - ageDays * 864e5 } });

test('arrivée → attribuée, départ → retirée, retour → recompté', async () => {
  fresh('g1');
  const g = mkGuild('g1', [{ code: 'x', uses: 0, inviterId: 'A' }]);
  await inv.refresh(g);

  g._inv[0].uses = 1;
  let r = await inv.onMemberAdd(mkMember(g, 'm1'));
  assert.strictEqual(r.type, 'regular'); assert.strictEqual(r.inviterId, 'A'); assert.strictEqual(r.total, 1);
  assert.deepStrictEqual(inv.inviterOf('g1', 'm1').inviterId, 'A');

  r = inv.onMemberRemove(mkMember(g, 'm1'));
  assert.strictEqual(r.total, 0);
  assert.strictEqual(inv.onMemberRemove(mkMember(g, 'm1')), null, 'un départ ne compte qu\'une fois');

  g._inv[0].uses = 2;
  r = await inv.onMemberAdd(mkMember(g, 'm1'));
  assert.strictEqual(r.total, 1, 'retour = 1 invitation nette, pas 2');
  const s = inv.getStats('g1', 'A');
  assert.deepStrictEqual([s.regular, s.left, s.total], [2, 1, 1]);
});

test('compte trop récent = fake, non compté, son départ ne retire rien', async () => {
  fresh('g2');
  const g = mkGuild('g2', [{ code: 'x', uses: 0, inviterId: 'A' }]);
  await inv.refresh(g);
  g._inv[0].uses = 1;
  const r = await inv.onMemberAdd(mkMember(g, 'm1', 2));
  assert.strictEqual(r.type, 'fake');
  inv.onMemberRemove(mkMember(g, 'm1'));
  const s = inv.getStats('g2', 'A');
  assert.deepStrictEqual([s.regular, s.fake, s.left, s.total], [0, 1, 0, 0]);
});

test('arrivées simultanées : traitées l\'une après l\'autre, chacune attribuée à la bonne invitation', async () => {
  fresh('g3');
  const g = mkGuild('g3', [{ code: 'x', uses: 0, inviterId: 'A' }, { code: 'y', uses: 0, inviterId: 'B' }]);
  await inv.refresh(g);
  // Ce que Discord renverrait à chaque lecture : d'abord m1 est passé par x, puis m2 par y.
  g._script = [
    [{ code: 'x', uses: 1, inviterId: 'A' }, { code: 'y', uses: 0, inviterId: 'B' }],
    [{ code: 'x', uses: 1, inviterId: 'A' }, { code: 'y', uses: 1, inviterId: 'B' }],
  ];
  const [r1, r2] = await Promise.all([inv.onMemberAdd(mkMember(g, 'm1')), inv.onMemberAdd(mkMember(g, 'm2'))]);
  assert.strictEqual(r1.inviterId, 'A');
  assert.strictEqual(r2.inviterId, 'B');
});

test('vanity, auto-invitation, bot, suivi coupé', async () => {
  fresh('g4');
  const g = mkGuild('g4', [{ code: 'x', uses: 0, inviterId: 'A' }]);
  await inv.refresh(g);
  g.vanityURLCode = 'natix';
  assert.strictEqual((await inv.onMemberAdd(mkMember(g, 'v1'))).type, 'vanity');
  g.vanityURLCode = null;
  g._inv[0].uses = 1;
  assert.strictEqual((await inv.onMemberAdd(mkMember(g, 'A'))).type, 'self');
  g._inv[0].uses = 2;
  const bot = mkMember(g, 'b1'); bot.user.bot = true;
  assert.strictEqual((await inv.onMemberAdd(bot)).type, 'bot');
  inv.store('g4').enabled = false;
  assert.strictEqual(await inv.onMemberAdd(mkMember(g, 'm9')), null);
});

test('bonus, classement, reset', async () => {
  fresh('g5');
  inv.addBonus('g5', 'A', 5);
  inv.addBonus('g5', 'B', 2);
  inv.addBonus('g5', 'B', -1);
  assert.deepStrictEqual(inv.leaderboard('g5').map(r => [r.id, r.total]), [['A', 5], ['B', 1]]);
  inv.resetUser('g5', 'A');
  assert.strictEqual(inv.getStats('g5', 'A').total, 0);
  inv.resetAll('g5');
  assert.strictEqual(inv.leaderboard('g5').length, 0);
});
