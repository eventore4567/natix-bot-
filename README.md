# Natix AI

Bot Discord avec OpenAI : `/ask`, `/resetai` et réponses aux mentions.

## Railway
Variables requises : `DISCORD_TOKEN` et `OPENAI_API_KEY`. Optionnelle : `OPENAI_MODEL` (défaut : `gpt-4.1-mini`).

Active **Message Content Intent** dans Discord Developer Portal pour les mentions. Invite le bot avec les scopes `bot` et `applications.commands`.

Démarrage : `python main.py`. Les conversations sont conservées en mémoire vive et réinitialisées au redémarrage.

Ne publie jamais tes tokens ou clés API dans GitHub. Révoque toute clé précédemment exposée.
