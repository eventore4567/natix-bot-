// Automodération : analyse chaque message
const db = require('./db');
const { isBypassed, embed, modAction } = require('./utils');
const { addWarn } = require('./warns');
const { emoji, localize } = require('./emojis');

const INVITE = /(discord\.(gg|io|me|li)|discord(app)?\.com\/invite)\/\S+/i;
const LINK = /https?:\/\/\S+|www\.\S+/i;

// guildId-userId -> timestamps des derniers messages
const recent = new Map();

// Normalise pour attraper "M.0.T", "mOt", accents...
const normalize = s => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[0@]/g, 'o').replace(/[1!]/g, 'i').replace(/3/g, 'e').replace(/4/g, 'a').replace(/\$/g, 's');

async function punish(message, reason, { warn = true } = {}) {
  await message.delete().catch(() => {});
  const notice = await message.channel.send(localize({
    content: `${message.author}`,
    embeds: [embed('warn', null, `${emoji('security')} Ton message a été supprimé : **${reason}**`)],
  }, message.channel)).catch(() => null);
  if (notice) setTimeout(() => notice.delete().catch(() => {}), 6000);
  if (warn) await addWarn(message.guild, message.member, null, `AutoMod : ${reason}`);
}

async function check(message) {
  if (!message.guild || message.author.bot || !message.member) return;
  if (isBypassed(message.member)) return;

  const cfg = db.guild(message.guild.id).config;
  const am = cfg.automod;
  const content = message.content || '';

  // Anti-spam
  if (am.antiSpam) {
    const key = `${message.guild.id}-${message.author.id}`;
    const now = Date.now();
    const list = (recent.get(key) || []).filter(t => now - t < cfg.spam.seconds * 1000);
    list.push(now);
    recent.set(key, list);
    if (list.length >= cfg.spam.messages) {
      recent.delete(key);
      const d = cfg.spam.muteMinutes * 60e3;
      if (message.member.moderatable) {
        await message.member.timeout(d, 'AutoMod : spam').catch(() => {});
        await modAction(message.guild, { type: 'mute', target: message.author, moderator: null, reason: 'AutoMod : spam', duration: d });
      }
      // Supprime les messages de spam récents
      const msgs = await message.channel.messages.fetch({ limit: 30 }).catch(() => null);
      if (msgs) {
        const spam = msgs.filter(m => m.author.id === message.author.id && now - m.createdTimestamp < cfg.spam.seconds * 1000 + 2000);
        await message.channel.bulkDelete(spam, true).catch(() => {});
      }
      message.channel.send(localize({ embeds: [embed('mute', null, `${emoji('security')} ${message.author} a été mute **${cfg.spam.muteMinutes} min** pour spam.`)] }, message.channel))
        .then(m => setTimeout(() => m.delete().catch(() => {}), 8000)).catch(() => {});
      return;
    }
  }

  if (!content) return;

  // Mots interdits
  if (am.badWords && cfg.badWords.length) {
    const norm = normalize(content);
    const words = norm.split(/[^a-z0-9]+/);
    const squashed = norm.replace(/[^a-z0-9]/g, '');
    const hit = cfg.badWords.find(w => {
      const nw = normalize(w);
      return nw.includes(' ') ? norm.includes(nw) : (words.includes(nw) || (nw.length >= 5 && squashed.includes(nw)));
    });
    if (hit) return punish(message, 'mot interdit');
  }

  // Invitations Discord
  if (am.antiInvites && INVITE.test(content)) return punish(message, 'invitation Discord interdite');

  // Liens
  if (am.antiLinks && LINK.test(content)) return punish(message, 'les liens sont interdits');

  // Mentions de masse
  if (am.antiMentions) {
    const count = message.mentions.users.size + message.mentions.roles.size + (message.mentions.everyone ? 5 : 0);
    if (count >= cfg.maxMentions) return punish(message, 'trop de mentions');
  }

  // Majuscules
  if (am.antiCaps) {
    const letters = content.replace(/<a?:\w+:\d+>|<@[!&]?\d+>|https?:\/\/\S+/g, '').replace(/[^a-zA-ZÀ-ÿ]/g, '');
    if (letters.length >= 10) {
      const upper = letters.replace(/[^A-ZÀ-Þ]/g, '').length;
      if ((upper / letters.length) * 100 >= cfg.capsPercent) return punish(message, 'trop de majuscules', { warn: false });
    }
  }
}

// Nettoyage mémoire de l'anti-spam
setInterval(() => {
  const now = Date.now();
  for (const [k, v] of recent) if (!v.length || now - v[v.length - 1] > 60e3) recent.delete(k);
}, 60e3).unref();

module.exports = { check };
