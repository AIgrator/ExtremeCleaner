# ExtremeCleaner — free disk cleaner that explains what it found

Free up disk space on Windows: find forgotten caches, leftovers and junk files —
and understand what each of them is before you delete anything.

![Status](https://img.shields.io/badge/status-beta-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-1.2.1-brightgreen)

## What's new in 1.1.2 (honest sizes)

- **NTFS hardlinks are no longer counted twice**: one physical file (Component
  Store, shared PyInstaller packages, git object pools) is now counted once per
  scan — the totals show the "real" bytes on disk, not inflated sums.
- **Overlap watchdog**: the built-in test suite (`tests/test_rules.py`, runs on
  GitHub CI) detects when two rules measure the same folder — the bug class that
  filtered the 3-GB Hugging Face cache through two rows in 1.1.1. Twenty more
  overlaps (Cherry Studio/Chatbox caches vs their data rows, Documents root,
  Adobe, Ubisoft, goose) were found and fixed with a per-rule `exclude` field:
  umbrella rows now show only the files they own.

## What's new in 1.2.1 (privacy hardening + save-name lookups)

Follow-up on 1.2.0's Goldberg save discovery:

- **Zero background network traffic.** The scan itself is now fully offline;
  unknown emulator AppIDs stay as honest `Steam AppID <id>` rows with a
  steamdb hint. A game name is fetched only when the user explicitly clicks
  "Get game name" in the row's context menu — one request to the official
  Steam Store API, stored next to the exe (`emu_appid_names.json`), so every
  later scan shows the name without touching the network.
- Fixed a silently dying lookup: QAction's `triggered(bool)` argument
  clobbered the first slot parameter, so clicks did nothing in the windowed
  exe. Any error now shows a dialog instead of vanishing.

## What's new in 1.2.0 (AI-IDE + game-store saves)

Rule count grew 294 → **298**, plus the honest-scan fixes:

- **Qoder IDE (Alibaba)** covered from the official FAQ: deletable `logs`/`tmp`
  inside `~/.Qoder` (512 MB found on a real machine), chats/projects/file-history
  stay a review-only row.
- **Goldberg-emulator save folders**, one rule per emulator state, auto-expand
  per game named by its Steam AppID:
  - classic `Goldberg SteamEmu Saves` (official Readme_release.txt),
  - `GSE Saves` (gbe_fork fork, official README).
  Known AppIDs resolve to game names (Resident Evil Requiem, Indiana Jones,
  Mafia: The Old Country, Evil West); unknown ones get a steamdb hint.
- **pip/npm caches no longer freeze the cleaner**: deleting the cache files
  directly (official pip/npm docs call both dirs pure caches) instead of
  running `pip cache purge` / `npm cache clean --force`, which could sit silent
  for minutes. Remaining command-based rules are capped at 5 minutes.
- Fixed in 1.1.1/1.1.2 earlier: Android Studio caches deletable, no double
  counting of AI model folders, NTFS hardlink dedup, overlap watchdog on CI.

## What's new in 1.1.1 (bug fixes)

- **Android Studio caches are now deletable**: the "File > Invalidate Caches"
  instruction row became a real cleanup — `caches`, `log`, `tmp` and crash dumps
  go to the bin, Studio reindexes on next start (same official mechanism).
- **No more double-counted AI models**: a new per-rule `exclude` field stops
  umbrella rules from re-scanning subfolders owned by dedicated rules. The
  `~/.cache` "Dev ML/tool caches" rule no longer duplicates the Hugging Face Hub
  rule's 3 GB (found on a real machine: 6 GB shown → 3 GB real), both in the
  size overview and in what gets deleted.

## What's new in 1.1.0

Rule count grew 254 → **294**, everything verified against official documentation only:

- **Devin Desktop (ex-Windsurf)** editor caches + `~/.devin` agent data (official
  migration FAQ: `%APPDATA%\Windsurf` → `%APPDATA%\Devin`, June 2026 rebrand).
- **JetBrains AI Assistant** official in-app cleanup of chats/requests log.
- **Full Visual Studio** (the "big" one): MEF ComponentModelCache + Roslyn cache
  (Microsoft Learn) — previously only the installer package cache was covered.
- **Popular-IDE sweep vs the Stack Overflow Survey top list**: Notepad++ unsaved
  snapshots, Sublime Text cache (official: deliberately separate from settings),
  Neovim state (shada/swap/undo — plugins untouched).
- **Voice transcription (local Whisper apps)**: Hugging Face Hub cache (one dir
  shared by faster-whisper, pyannote, WhisperX, transformers…), OpenAI Whisper CLI,
  Buzz, Vibe, Subtitle Edit engines, OpenWhispr, Whisper Transcriber Suite.
- **TTS + generic torch.hub** weights: Coqui TTS (`%LOCALAPPDATA%\tts`), PyTorch
  Hub checkpoints — the umbrella for local image/video-generation tools.
- Agent-vs-agent coverage kept in step with 2026 ecosystem: Cherry Studio,
  Chatbox, HammerAI, Dyad, Descript, Perplexity, PearAI, Amazon Q (MCP config),
  ZCode, MiniMax Code, omp, nanobot, claude-mem, hermes, openclaw, Zoo Code.

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

## Places we check (298 rules and counting)

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
   InsightFace, BentoML, Topaz — plus the shared Hugging Face Hub and torch.hub
   caches, the local voice-transcription stack (Whisper CLI, Buzz, Vibe, OpenWhispr,
   Subtitle Edit, Whisper Transcriber Suite) and Coqui TTS. Agent histories
   (Claude, Codex, Gemini, Qwen, Kimi, Copilot, Cursor, Cline, Roo, Kilo, Kiro,
   Trae, goose, Aider, Crush, Factory Droid, iFlow, Planner, cagent, Continue)
   shown separately as user data.
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

**System requirements:** Windows 10/11 64-bit. No Python needed (everything is
inside the exe). Admin rights only for automatic restore points — without them
the program warns and asks for confirmation instead.

From source (Windows, Python 3.10+):

```powershell
py -3.10 -m pip install pyyaml rich PySide6 Send2Trash
py -3.10 src/extreme_cleaner/cli.py gui
```

To build `ExtremeCleaner.exe` yourself: see [BUILDING.md](BUILDING.md).

Roadmap: [PLAN.md](PLAN.md), cross-platform notes: [CROSS_PLATFORM_PLAN.md](CROSS_PLATFORM_PLAN.md).

## License

MIT — free for everyone.







