# Telegram setup

Talk to M3allema from your phone: send tasks, send voice notes, and approve or
decline her actions with one tap. The bot runs on your own computer and polls
Telegram, so you do not need a public server.

## 1. Create the bot

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Choose a name and a username. BotFather replies with a **token**.
3. Put the token in your workspace's `.env`:

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   ```

## 2. Add it to `config.yaml`

```yaml
telegram:
  bot_token: env:TELEGRAM_BOT_TOKEN
  owner_ids: []          # filled in the next step
```

## 3. Find your Telegram id

Run the bot:

```bash
m3allema telegram
```

Send `/start` to your bot. It replies with your Telegram user id. Add it to
`owner_ids` (for example `owner_ids: [123456789]`) and restart the bot.

Only ids in `owner_ids` can use the bot. Anyone else who finds it gets nothing
back except their own id when they send `/start`.

## Using it

| You send | M3allema |
|---|---|
| A text message | Runs it as a task and replies with the result |
| A voice note | Replies with the transcript and **Send** / **Edit** buttons. Nothing runs until you tap Send |
| *(she needs approval)* | Sends the action with **Approve** / **Decline** buttons |

Approvals follow your `policy.yaml`, exactly as in the terminal and the dashboard.
An approval you never answer is declined after 15 minutes.

`m3allema telegram --resume` continues your most recent conversation.

## Voice notes

Voice notes use the `speech` engine from `config.yaml`. The default is local
faster-whisper, which needs the voice extra:

```bash
uv tool install "m3allema[voice] @ git+https://github.com/BackendNeuron/m3allema"
```

On a slow machine, Groq's hosted Whisper is much faster:

```yaml
speech:
  engine: groq
  api_key: env:GROQ_API_KEY
```

## Privacy

The bot token is only read from `.env`. Messages pass through Telegram's servers
like any Telegram chat; use the dashboard if a task must stay on your computer.
