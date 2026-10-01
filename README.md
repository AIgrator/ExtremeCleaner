# ExtremeCleaner — free disk cleaner that explains what it found

Free up disk space on Windows: find forgotten caches, leftovers and junk files —
and understand what each of them is before you delete anything.

![Status](https://img.shields.io/badge/status-beta-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Keywords: disk cleaner, PC cleaner, junk file remover, cache cleaner,
free up disk space, disk space analyzer, developer cache cleaner.

## Not just a cache cleaner — a finder of forgotten files

Over months and years programs pile up files you forgot existed — typical story:
two years ago you installed something, tried it once, it downloaded gigabytes,
and you forgot it ever existed. Old SDKs, package caches, "try once" AI models,
shader caches of long-deleted games, messenger media, emulator images, saves of
uninstalled games, installer leftovers on `C:/` — the disk remembers.
ExtremeCleaner shows you those places so you decide yourself whether you still need them.

Deletion is gentle by design: console tools are cleaned through their own
official commands, everything else goes to the Recycle Bin — never wiped
permanently by the program.

## Places we check (239 rules and counting)

- **Cache (31 places)**: Python (pip, uv, poetry, conda), Node.js (npm, yarn, pnpm, bun, deno),
  Java/Android (gradle, maven), Rust (cargo), Go, C++ (vcpkg, conan), .NET (nuget),
  PHP (composer), Flutter, ML tool caches, GPU driver caches, Recycle Bin.
- **11 browsers with per-subfolder checkboxes**: Chrome, Edge, Firefox (all profiles),
  Brave, Opera, Opera GX, Vivaldi, Yandex, LibreWolf, Waterfox, Epic Privacy Browser.
   Cache/Code/GPUCache checked, site data opt-in, passwords and autofill shown but never touched.
- **Old versions**: Opera, Chrome, Android Studio dirs, JetBrains leftovers,
  Android SDK build-tools — the active version is always protected.
- **AI models**: EasyOCR, Ollama (incl. Hermes/Llama/Qwen), LM Studio, ComfyUI,
  InvokeAI, YOLO datasets, GPT4All, NLTK, Stanza, Gensim, Flair, DeepFace,
  InsightFace, BentoML, Topaz — plus agent histories (Claude, Codex, Gemini,
  Qwen, Kimi, Copilot, Cursor, Cline, Roo, Kilo, Kiro) shown separately as user data.
- **Messengers**: Discord, Slack, Skype, Teams, Telegram, WhatsApp, Viber,
  Zoom recordings, Signal, Notion, Obsidian, Bitwarden, Mailbird, Thunderbird.
- **Media**: Adobe (Premiere, After Effects, Camera Raw), Spotify, CapCut, DaVinci,
  VLC, foobar2000, Kodi, Plex, Jellyfin, OBS, HandBrake, GIMP, Krita, Figma,
  Lightshot-class captures (Game Bar, ShareX, Bandicam).
- **Development**: VS Code, JetBrains (per-product caches + Toolbox),
  Android SDK (caches, old build-tools, system images), Postman, Figma, Zed,
  Eclipse, NetBeans, TortoiseSVN, Unreal DDC, PlatformIO, Arduino,
  Visual Studio installer payloads, 12 AI coding agents.
- **Games**: Steam/GOG/Epic (+manifest discovery, so installed games are found
  automatically), EA App, Ubisoft, Blizzard, Minecraft (+worlds), Roblox, FiveM,
  PUBG, Twitch, Wargaming, Unity emulators data; common save hubs
  (Steam userdata, My Games, Saved Games, LocalLow, EA/Rockstar/Paradox documents,
  Ubisoft savegames, Xbox containers) **plus 229 non-standard save locations**
  of individual titles and publishers.
- **Hypervisors & emulators**: VirtualBox (incl. registry discovery),
  VMware, Hyper-V checkpoints, Docker, WSL vhdx compact, Android AVD.
- **Antivirus**: Defender history/quarantine/old bases, Avast chest,
  Malwarebytes, McAfee logs, Kaspersky leftovers — shown, cleaned via the AV itself.
- **3D & CAD**: Blender, Revit journals, DAZ caches.
- **System (info only)**: hiberfil, WinSxS, VSS storage, restore points (counted),
  Windows.old, update downloads,
  CBS logs, Delivery Optimization, pagefile — sizes plus official commands and doc links.
- **Other**: Office cache, iPhone backups, LibreOffice, Dropbox/Nextcloud/MEGA,
  qBittorrent/uTorrent/BitTorrent, AnyDesk, WinRAR, screenshots, downloads.
- Nested checkboxes, tooltips with path/action/safety, right-click
  open/copy/web-search, `Show all` toggle, progressive scan, your own folders
  via `Add folder`, `audit` command.
## Three tabs

1. **Safe cleanup** — trash that re-downloads from the internet:
   package caches (npm, pip, gradle, cargo…), shader caches, logs,
   old program versions (the active one is always protected).
   Checked = safe by default, the rest is opt-in.
2. **User data** — YOUR files: chat and agent histories, game saves,
   downloads, screenshots, messenger data, AI models.
   No checkboxes at all: the program never deletes here.
   Single click opens the folder — you review and delete manually.
3. **System (info only)** — Windows folder, hiberfil.sys, WinSxS,
   shadow copies… You cannot delete here either. Instead you get
   the official command and a link to the instructions for each item,
   so you know exactly which way to go if you want to optimize it.

## Every location is explained

Each of the 200+ checked places carries:

- **what it is** — e.g. "compiled GPU shaders", "per-project AI chat transcripts";
- **safety verdict** — safe (restores itself), caution (read the note first),
  or never-touch (sessions, keys, saves);
- **the official way to clean it** — the tool's own command where one exists
  (`npm cache clean`, `pip cache purge`, `File > Invalidate Caches…`);
- **a web search in one click** — the query contains only generic folder names,
  your username never leaves the PC.

Hover any row for the full card. Right click opens the folder,
copies the path, or searches the web for it.

## Two ways of cleaning (never mixed up)

- **Files** (caches, logs, old versions) — deleted by the program into the
  Recycle Bin, never permanently. The folder itself stays.
- **Console tools with their own clean commands are cleaned through those commands**:
  `npm cache clean`, `pip cache purge`, `go clean`, `docker system prune` and the like
  run exactly as the tool vendor prescribes — we never rip their folders by hand.
- **Human instructions** ("File > Invalidate Caches…", "Wipe Data…") are shown
  as steps for you and are never executed as commands.

## Safety net

- A System Restore Point is created automatically before every cleanup
  (needs admin rights — otherwise the program warns and asks for explicit
  confirmation instead of deleting silently).
- Sacred names (sessions, keys, configs, credentials) are never touched
  wherever they appear.
- Running programs are detected first: you get offered to close them
  (CCleaner-style), antivirus excluded, before anything is deleted.

## Your own folders

No cleaner knows every program. If you know a folder on your system that keeps
growing and the program doesn't list it — add it yourself, right from the interface:

- **Add folder** button: name, folder (Browse…), and the tab it belongs to —
  **Safe cleanup** (trash with a checkbox) or **User data** (size + open, never deleted).
- Your entries live in their own top-level **User** section with edit (✎)
  and delete (✕) buttons right in the row — stored in `user_rules.yaml`,
  never overwritten by updates.
- Next scans will watch those folders together with everything else,
  so regrowing junk is visible from one place.
- `Show all locations` toggle, expansion memory, progressive scan
  (cleanup first, system last), `audit` command showing the safe defaults.
- Trash-first deletion (Recycle Bin), deletion log.

## Run

**Easiest (Windows):** download `ExtremeCleaner.exe` from
[Releases](../../releases) and run it — no Python needed, nothing is installed.
Run as administrator if you want automatic restore points before cleanups.

From source (Windows, Python 3.10+):

```powershell
py -3.10 -m pip install pyyaml rich PySide6 Send2Trash
py -3.10 src/extreme_cleaner/cli.py gui
```

To build `ExtremeCleaner.exe` yourself: see [BUILDING.md](BUILDING.md).

Roadmap: [PLAN.md](PLAN.md), cross-platform notes: [CROSS_PLATFORM_PLAN.md](CROSS_PLATFORM_PLAN.md).

## License

MIT — free for everyone.
