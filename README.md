# 🎵🤖 MeLagu — Discord Music Bot + Gemini AI Assistant

> One bot, two strengths: a **stable Discord music player** and a **Google Gemini AI assistant** (text + real-time voice).

MeLagu is built for servers that want a complete experience: play music with modern controls, chat with contextual AI personas, and run real-time voice conversations directly in voice channels.

---

## ✨ Feature Highlights

### 🎶 Music System (YouTube/URL/Search)
- **Play from search query or URL** with `al!play`.
- **Full queue controls**: `queue`, `remove`, `shuffle`, `loop`, `skip`, `stop`.
- **Autoplay recommendations** when queue is empty (`al!autoplay`).
- **Session playback history** (`al!history` / `al!list`).
- **Real-time audio filters**:
  - `al!bb` / `al!bassboost`
  - `al!nightcore`
  - `al!vaporwave`
  - `al!speed`
  - `al!reset`
- **Auto-leave timer** when idle (owner-toggleable).
- **Voice reconnection handling** for unstable connections.

### 🧠 AI Chat (Google Gemini)
- **Mention the bot directly** or use a channel with `gemini` in the topic.
- **Persona system**:
  - list personas
  - set personal persona
  - add/delete private personas
- **Persistent conversation memory** (JSON history) for long-term context.
- **Private/public chat mode** to control memory behavior.
- **Automatic multi-key Gemini rotation** to reduce rate-limit disruption.
- **Maintenance-aware behavior**: interactions are restricted to owners during maintenance mode.

### 🎙️ MeLagu Live (Real-Time Voice AI)
- Use `al!live` to start real-time voice conversation with Gemini.
- Uses a **voice receive + playback pipeline** (Discord PCM ↔ Gemini audio).
- **Context sync** with text chat history for more consistent responses.
- Use `al!stoplive` to end the session.

### 🏘️ Server & Logic
- **Global Server Persona** (`al!gp`): Owners can set a server-wide persona for the shared history mode.
- **Smart Chat Isolation**:
  - **Individual Privacy**: `al!private` mode keeps your secrets safe from the shared history.
  - **Topic Isolation**: Specialized channels (e.g., `#gemini`) have dedicated memory.
  - **Maintenance Sandbox**: When maintenance is ON, AI history is funneled into a temporary test history that is wiped when maintenance ends.
- **Multi-key Gemini Rotation**: Automatically swaps to the next key if a rate limit is hit.

---

## 🧱 Architecture Overview

```text
main.py
├── cogs/music.py      # Core music player, queue, autoplay, history
├── cogs/controls.py   # Skip, volume, shuffle, loop
├── cogs/filters.py    # Bassboost, nightcore, vaporwave, speed, reset
├── cogs/chat.py       # AI chat, personas, memory, private/public mode
├── cogs/gemini.py     # MeLagu Live (real-time voice)
├── cogs/owner.py      # Owner commands (maintenance, backup, restart, global persona)
├── cogs/backup.py     # Auto-backup scheduler + zip sender
└── utils.py           # Embed helpers, key manager, owner checks, settings
```

---

## ⚙️ Requirements

- Python **3.10+**
- **FFmpeg** (available in `PATH`) - Required for audio processing.
- **Node.js** (available in `PATH`) - **CRITICAL** for yt-dlp to solve YouTube's JavaScript challenges (prevents SABR streaming errors).
- **Firefox Browser** - **CRITICAL** to extract YouTube cookies. Make sure to log into your YouTube account on Firefox so the bot can bypass bot-detection and age restrictions.
- Python dependencies in `requirements.txt`
- For Windows voice compatibility: `libopus-0.x64.dll` (already included in the repo)

---

## 🚀 Quick Start

### 1) Prerequisites Setup

Before running the bot, you **must** install these external tools:
1. Install [Python 3.10+](https://www.python.org/downloads/).
2. Install [FFmpeg](https://ffmpeg.org/download.html) and ensure it is added to your system `PATH`.
3. Install [Node.js](https://nodejs.org/) and ensure it is added to your system `PATH`.
4. Install **Mozilla Firefox**, open it, and log into your YouTube account. (The bot reads cookies directly from Firefox to bypass blocks).

### 2) Clone and install dependencies

```bash
git clone https://github.com/Fadlay/discord-bot-music.git
cd discord-bot-music
pip install -U -r requirements.txt
```

### 2) Create a `.env` file

Minimal example:

```env
TOKEN=your_discord_bot_token
GEMINI_API_KEYS=key_1,key_2,key_3
BACKUP_CHANNEL_ID=123456789012345678
```

> Notes:
> - `GEMINI_API_KEYS` supports **multiple keys** (comma-separated).
> - If `BACKUP_CHANNEL_ID` is empty/invalid, auto-backup is disabled.

### 3) Run the bot

```bash
python main.py
```

For Windows, you can also use helper scripts:
- `setup_windows.bat`
- `run_bot.bat`

---

## 📘 Command Reference

Primary prefix: **`al!`** (case-insensitive).

### 🎵 Music
- `al!join` — Join your voice channel.
- `al!play <query/url>` (`al!p`) — Play a track.
- `al!pause` / `al!resume`
- `al!skip` (`al!s`, `al!next`)
- `al!stop`
- `al!queue` (`al!q`)
- `al!remove <index>` (`al!rm`, `al!delete`)
- `al!autoplay`
- `al!loop [track|queue|off]`
- `al!shuffle`
- `al!volume <0-100>` (`al!vol`)
- `al!list` (`al!history`, `al!recent`)

### 🎧 Audio Filters
- `al!bassboost <level>` (`al!bb`)
- `al!nightcore` (`al!nc`)
- `al!vaporwave`
- `al!speed <0.5-2.0>`
- `al!reset`

### 💬 AI Chat & Personas
- `al!persona` (view active persona)
- `al!persona list`
- `al!persona set <name>`
- `al!persona add <name> <instruction>`
- `al!persona delete <name>`
- `al!forget` (clear personal memory)
- `al!private` / `al!public` (toggle history mode)

### 🎙️ Live Voice AI
- `al!live` — Start real-time voice chat.
- `al!stoplive` — End live session.

### 👑 Owner Only
- `al!autoleave` — Toggle idle disconnection.
- `al!backup` — Trigger manual data backup.
- `al!restart` — Hot-restart the bot process.
- `al!forgetshared` (`al!fs`) — Wipe the shared server history.
- `al!maintenance` (`al!mt`) [on/off] [reason] — Toggle global maintenance mode (optional reason).
- `al!globalpersona` (`al!gp`) — Manage server-wide default persona.

### ⚙️ General
- `al!help`
- `al!ping`
- `al!stats` (includes CPU/RAM usage)
- `al!speedtest` (`al!st`) — Test internet speed.
- `al!source`

---

## 🧪 Quick Troubleshooting

- **Bot does not respond to commands**
  - Ensure `message_content` intent is enabled in the Discord Developer Portal.
  - Confirm token is valid and bot is online.

- **No audio output / FFmpeg errors**
  - Ensure FFmpeg is installed and accessible from terminal (`ffmpeg -version`).

- **Gemini does not respond**
  - Check `GEMINI_API_KEYS` in `.env`.
  - Ensure keys are valid and quota is available.

- **Live voice does not capture speech**
  - Ensure Opus is loaded and bot has proper voice permissions.

---

## 🔐 Security Notes

- Never commit `.env` to a public repository.
- Rotate API keys regularly.
- Restrict owner commands to trusted IDs/roles only.

---

## 📄 License

This project is licensed under **GNU AGPL v3.0 or later**.

This means you can freely use, modify, copy, and distribute it, but if you deploy a modified version as a service (network use), the modified source code must remain open source under the same license. See [LICENSE](LICENSE).

---

If this project helps you, consider giving it a ⭐ on GitHub.
