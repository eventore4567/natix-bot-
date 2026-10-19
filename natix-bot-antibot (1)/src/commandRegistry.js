const fs = require('fs');
const path = require('path');
const { PUBLIC_COMMANDS } = require('./commandPolicy');

// Charge toutes les commandes de src/commands. Ne modifie PAS leurs permissions par défaut :
// - commandes publiques  → default_member_permissions absent (visibles par @everyone)
// - commandes de gestion → default_member_permissions défini (cachées aux membres sans la permission)
function loadCommands(dir = path.join(__dirname, 'commands')) {
  const list = [];
  for (const file of fs.readdirSync(dir).filter(f => f.endsWith('.js'))) {
    for (const c of [].concat(require(path.join(dir, file)))) {
      const raw = c.data.default_member_permissions;
      c.requiredPerms = raw != null ? BigInt(raw) : null; // vérifié aussi à l'exécution (défense en profondeur)
      c.isPublic = PUBLIC_COMMANDS.includes(c.data.name);
      // Serveur uniquement : la commande n'apparaît pas en MP (le bot ne sait y répondre de toute façon).
      c.data.setContexts?.(0);          // 0 = Guild
      c.data.setIntegrationTypes?.(0);  // 0 = installation sur un serveur
      list.push(c);
    }
  }
  validate(list);
  return list;
}

function validate(list) {
  const problems = [];
  const names = new Set();
  for (const c of list) {
    const n = c.data.name;
    if (names.has(n)) problems.push(`/${n} est déclarée deux fois`);
    names.add(n);
    if (c.isPublic && c.requiredPerms != null) problems.push(`/${n} est listée PUBLIQUE mais a une restriction par défaut`);
    if (!c.isPublic && c.requiredPerms == null) problems.push(`/${n} n'est pas listée publique mais n'a AUCUNE restriction (ajoute setDefaultMemberPermissions, ou ajoute-la à PUBLIC_COMMANDS)`);
  }
  for (const p of PUBLIC_COMMANDS) if (!names.has(p)) problems.push(`/${p} est listée publique dans commandPolicy.js mais n'existe pas`);
  if (problems.length) throw new Error('Politique de commandes invalide :\n - ' + problems.join('\n - '));
}

// JSON envoyé à Discord (les permissions par défaut sont conservées telles que déclarées)
const buildPayload = list => list.map(c => c.data.toJSON());

// Compare ce que Discord a réellement enregistré avec ce qui était voulu.
// `registered` : itérable de commandes Discord (objet avec name + defaultMemberPermissions).
function verifyRegistered(list, registered) {
  const wanted = new Map(list.map(c => [c.data.name, c]));
  const problems = [];
  for (const r of registered) {
    const c = wanted.get(r.name);
    if (!c) { problems.push(`/${r.name} existe sur Discord mais pas dans le code`); continue; }
    const bits = r.defaultMemberPermissions ? BigInt(r.defaultMemberPermissions.bitfield ?? r.defaultMemberPermissions) : null;
    if (c.isPublic && bits != null) problems.push(`/${r.name} devrait être publique mais Discord la restreint (${bits})`);
    if (!c.isPublic && bits !== c.requiredPerms) problems.push(`/${r.name} : restriction attendue ${c.requiredPerms}, enregistrée ${bits}`);
  }
  return problems;
}

module.exports = { loadCommands, validate, buildPayload, verifyRegistered };
