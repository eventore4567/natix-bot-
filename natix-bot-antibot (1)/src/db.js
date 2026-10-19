// Stockage simple dans data/db.json (réglages, warns, tempbans par serveur)
const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'data', 'db.json');

const DEFAULT_CONFIG = () => ({
  logChannel: null,
  antiBot: false,
  automod: {
    antiSpam: true,
    antiLinks: false,
    antiInvites: true,
    antiCaps: true,
    antiMentions: true,
    badWords: true,
  },
  badWords: [],
  bypassRoles: [],
  spam: { messages: 5, seconds: 5, muteMinutes: 10 },
  maxMentions: 5,
  capsPercent: 70,
  warnThresholds: { mute: 3, kick: 5, ban: 7 },
  warnMuteMinutes: 60,
});

let data = { guilds: {} };
try {
  if (fs.existsSync(FILE)) data = JSON.parse(fs.readFileSync(FILE, 'utf8'));
} catch (e) {
  console.error('⚠️ db.json illisible, sauvegarde de secours créée.', e.message);
  fs.copyFileSync(FILE, FILE + '.backup-' + Date.now());
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE + '.tmp', JSON.stringify(data, null, 2));
    fs.renameSync(FILE + '.tmp', FILE);
  }, 500);
}

function guild(id) {
  if (!data.guilds[id]) data.guilds[id] = { config: DEFAULT_CONFIG(), warns: {}, tempbans: [], caseId: 0 };
  const g = data.guilds[id];
  // Ajoute les nouvelles options si la config est ancienne
  const def = DEFAULT_CONFIG();
  for (const k of Object.keys(def)) if (g.config[k] === undefined) g.config[k] = def[k];
  for (const k of Object.keys(def.automod)) if (g.config.automod[k] === undefined) g.config.automod[k] = def.automod[k];
  return g;
}

function allGuilds() {
  return data.guilds;
}

module.exports = { guild, allGuilds, save };
