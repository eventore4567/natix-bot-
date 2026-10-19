const Module = require('module');
let real = true;
try { require.resolve('discord.js'); require('discord.js'); } catch { real = false; }
if (!real) {
  const fake = require('./fake-discord');
  const load = Module._load;
  Module._load = function (req, ...rest) { return req === 'discord.js' ? fake : load.call(this, req, ...rest); };
}
module.exports = { usingRealDiscordJs: real };
