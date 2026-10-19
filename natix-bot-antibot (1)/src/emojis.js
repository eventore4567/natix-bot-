// Gestionnaire centralisé des emojis du bot.
//
// - Les images sont dans assets/emojis/<clé>.png (ou .gif si animé) ; sur Discord elles s'appellent `nx_<clé>`.
// - Au démarrage, init() lit les « emojis d'application » du bot (Developer Portal → Emojis), téléverse ceux qui
//   manquent (désactivable : EMOJI_AUTO_UPLOAD=false) et mémorise leurs vrais identifiants. Ils s'utilisent sur
//   tous les serveurs et en MP, sans emoji à installer sur chaque serveur.
// - Si un emoji personnalisé n'existe pas (pas encore téléversé, API indisponible, EMOJIS_DISABLED=true...),
//   emoji('clé') renvoie l'emoji Unicode de secours : jamais de `:nom:` ni de `<:x:0>` cassé à l'écran.
// - Dans un salon où le bot n'a pas « Utiliser des émojis externes », localize() remplace les emojis personnalisés
//   par leur équivalent Unicode juste avant l'envoi.
// Une seule source de vérité : pour ajouter un emoji, ajoute son image + une ligne dans CATALOG.
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'assets', 'emojis');
const PREFIX = 'nx_';

// clé : { fallback = emoji Unicode de secours, animated = GIF }   (usage = où le bot s'en sert)
const CATALOG = {
  // Retours d'état
  success:      { fallback: '✅' },            // action réussie, confirmation
  error:        { fallback: '❌' },            // échec, saisie invalide, commande impossible
  denied:       { fallback: '🚫' },            // permission ou hiérarchie insuffisante
  warning:      { fallback: '⚠️' },            // avertissement, point d'attention
  info:         { fallback: 'ℹ️' },            // information
  loading:      { fallback: '⏳', animated: true }, // opération en cours
  // Modération
  security:     { fallback: '🛡️' },            // automod, protection
  sanction:     { fallback: '🔨' },            // bannissement
  kick:         { fallback: '👢' },            // expulsion
  mute:         { fallback: '🔇' },            // mute
  unmute:       { fallback: '🔊' },            // fin de mute
  timer:        { fallback: '⏱️' },            // sanction temporaire
  // Salons / accès
  lock:         { fallback: '🔒' },
  unlock:       { fallback: '🔓' },
  slowmode:     { fallback: '🐢' },
  clean:        { fallback: '🧹' },
  // Interface & suivi
  config:       { fallback: '⚙️' },
  logs:         { fallback: '📋' },
  help:         { fallback: '📖' },
  diagnostic:   { fallback: '🩺' },
  on:           { fallback: '🟢' },
  off:          { fallback: '🔴' },
  bot:          { fallback: '🤖' },
  user:         { fallback: '👤' },
  server:       { fallback: '🏠' },
  delete:       { fallback: '🗑️' },
  edit:         { fallback: '✏️' },
  join:         { fallback: '📥' },
  leave:        { fallback: '📤' },
  // Réservés aux futures fonctions (tickets, événements, classements)
  ticket:       { fallback: '🎫' },
  notification: { fallback: '🔔', animated: true },
  games:        { fallback: '🎮' },
  reward:       { fallback: '🏆', animated: true },
};

const fileOf = key => path.join(DIR, `${key}.${CATALOG[key].animated ? 'gif' : 'png'}`);
const MARKUP = new RegExp(`<a?:${PREFIX}(\\w+):\\d+>`, 'g');

const resolved = new Map(); // clé -> { id, name, animated }
const warned = new Set();
let report = { custom: 0, total: Object.keys(CATALOG).length, uploaded: [], missing: Object.keys(CATALOG), source: 'unicode' };

const markup = em => `<${em.animated ? 'a' : ''}:${em.name}:${em.id}>`;

// Emoji à insérer dans un texte / un embed (titre, description, champ). Jamais vide ni cassé.
function emoji(key) {
  const def = CATALOG[key];
  if (!def) {
    if (!warned.has(key)) { warned.add(key); console.warn(`⚠️ Emoji inconnu « ${key} » (à ajouter dans src/emojis.js)`); }
    return '';
  }
  const em = resolved.get(key);
  return em ? markup(em) : def.fallback;
}

// Emoji pour un bouton / un menu : objet { id, name, animated } ou chaîne Unicode (accepté par setEmoji()).
function component(key) {
  const def = CATALOG[key];
  if (!def) return undefined;
  const em = resolved.get(key);
  return em ? { id: em.id, name: em.name, animated: !!em.animated } : def.fallback;
}

// Remplace les emojis personnalisés d'un texte par leur équivalent Unicode.
function strip(text) {
  return String(text).replace(MARKUP, (m, key) => CATALOG[key]?.fallback ?? '');
}

function canUseExternal(channel) {
  if (!channel?.guild) return true; // MP : pas de restriction
  const me = channel.guild.members?.me;
  const perms = me && channel.permissionsFor?.(me);
  return perms ? perms.has('UseExternalEmojis') : true;
}

// À appliquer sur un message envoyé « à froid » dans un salon (logs, automod...).
// Les réponses aux commandes slash ne sont pas concernées : Discord y autorise toujours les emojis externes.
function localize(payload, channel) {
  if (canUseExternal(channel)) return payload;
  const walk = (v, key) => {
    if (typeof v === 'string') return strip(v);
    if (Array.isArray(v)) return v.map(x => walk(x));
    if (v && typeof v === 'object') {
      if (key === 'emoji' && typeof v.name === 'string' && v.name.startsWith(PREFIX)) return { name: CATALOG[v.name.slice(PREFIX.length)]?.fallback ?? '▪️' };
      if (typeof v.toJSON === 'function') return walk(v.toJSON());
      return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x, k)]));
    }
    return v;
  };
  return walk(payload);
}

// Charge les emojis du bot (à appeler une fois le client prêt). Ne lève jamais : en cas de problème, le Unicode est utilisé.
async function init(client, { upload = process.env.EMOJI_AUTO_UPLOAD !== 'false', disabled = process.env.EMOJIS_DISABLED === 'true' } = {}) {
  resolved.clear();
  const uploaded = [];
  let source = 'unicode';
  if (!disabled) {
    // 1) emojis d'application (utilisables partout)
    const existing = new Map();
    try {
      const all = await client.application.emojis.fetch();
      for (const em of all.values()) existing.set(em.name, em);
      source = 'application';
    } catch (err) {
      console.warn(`⚠️ Emojis d'application illisibles (${err.message}) : emojis Unicode de secours.`);
    }
    if (source === 'application' && upload) {
      for (const key of Object.keys(CATALOG)) {
        const name = PREFIX + key;
        if (existing.has(name)) continue;
        const file = fileOf(key);
        if (!fs.existsSync(file)) { console.warn(`⚠️ Image manquante pour « ${key} » : ${file}`); continue; }
        try {
          const em = await client.application.emojis.create({ attachment: file, name });
          existing.set(name, em);
          uploaded.push(key);
        } catch (err) {
          console.warn(`⚠️ Téléversement de « ${name} » impossible : ${err.message}`);
        }
      }
    }
    for (const key of Object.keys(CATALOG)) {
      const em = existing.get(PREFIX + key);
      if (em?.id) resolved.set(key, { id: em.id, name: em.name, animated: !!em.animated });
    }
    // 2) emojis `nx_*` installés à la main sur un serveur où est le bot (secours, utilisables sur ce serveur)
    for (const key of Object.keys(CATALOG)) {
      if (resolved.has(key)) continue;
      const em = client.emojis?.cache?.find(x => x.name === PREFIX + key && x.available !== false);
      if (em) { resolved.set(key, { id: em.id, name: em.name, animated: !!em.animated }); if (source === 'unicode') source = 'serveur'; }
    }
  }
  const missing = Object.keys(CATALOG).filter(k => !resolved.has(k));
  report = { custom: resolved.size, total: Object.keys(CATALOG).length, uploaded, missing, source };
  return report;
}

const status = () => ({ ...report });

// Réservé aux tests
const _reset = () => { resolved.clear(); warned.clear(); report = { custom: 0, total: Object.keys(CATALOG).length, uploaded: [], missing: Object.keys(CATALOG), source: 'unicode' }; };
const _set = (key, em) => resolved.set(key, em);

module.exports = { emoji, component, localize, strip, init, status, CATALOG, PREFIX, DIR, fileOf, _reset, _set };
