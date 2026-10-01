# ExtremeCleaner — master plan

Started as "just clean caches". Growing into something bigger.
Order matters: safety first, speed second, new powers after.

## P0. Safety before the first deletion — DONE
- Windows System Restore Point created automatically before every cleanup.
- Hardcoded sacred names never deleted (`tdata`, `.config`, keys, credentials).
- Dry-run preview + deletion log (what, when, how much).
- Recycle Bin as default destination where possible, not permanent delete.
- Without this, one angry "it deleted my files" post kills the project.

## P1. Deletion engine — DONE
- Delete checked items in Safe tab only (User data / System tabs never get a delete path).
- Per-kind logic: `clean_contents`, `run_command` (official tools), `clean_selected`, `old_versions` (keep active).
- Progress, errors, summary "freed X".

## P2. MFT-accelerated scan — OPEN
- Today: minutes (WinSxS = 140k files via os.scandir).
- WizTree reads NTFS MFT directly = seconds. Research Python options
  (raw MFT parsing lib vs optional native helper), fallback to current walker.
- Until then: progressive scan (already done) hides the pain.

## P3. Uninstaller + leftovers (Revo/Geek territory, our way) — OPEN
- Detect orphaned folders of uninstalled programs
  (`AppData/Roaming/*`, `Packages/*`, registry Uninstall list cross-check).
- Fits our "extreme leftovers" positioning perfectly.

## P4. Duplicate finder — OPEN
- Users love it (Glary/CCleaner have it). Hash-based, size-first,
  grouped view. Natural fit for "forgotten files".

## P5. Rules update from the internet — OPEN
- `extreme-cleaner rules update`: fetch fresh YAMLs from this repo.
- Community contributions: one file per area, like now.
- (BleachBit's winapp2 model, but curated and safety-tiered.)

## P6. Scheduler + age filters — OPEN
- "Clean caches older than N days" automatically (CCleaner/PrivaZer style).
- "Last cleaned X days ago" reminders.

## P7. Export + CLI automation — PARTIAL
- CLI scan/list/audit commands: done.
- JSON/CSV scan reports (WizTree-style capacity planning): open.
- `clean --execute` for scripts: open.

## P8. Portable mode — DONE
- Onefile exe, user config + deletion log next to it, USB-friendly.

## P9. Cloud drives — OPEN
Duplicates / large / old files in Google Drive / OneDrive / Dropbox
  (CCleaner's newest feature). Lands in the User data tab doctrine.

## P10. Cross-platform (Windows / Linux / macOS) — OPEN
Full plan lives in CROSS_PLATFORM_PLAN.md. In short:
1. Abstract path vars (`{CACHE}`, `{CONFIG}`, `{DATA}`).
2. Per-OS `paths:` + auto-derived `os`.
3. Per-OS `command:`.
4. System section rebuilt per OS from scratch (Linux: journald/apt; macOS: Xcode/simulators).
5. User form OS-tagging — done.
6. CI matrix (win/linux/mac) — can't test other OSes locally.
7. Contributor docs.

## P11. Translations (i18n) — OPEN
- UI is English-only by design today; all strings already centralized in widgets.
- Add a string table + Russian first when asked.

## P12. Settings + user exclusion list (DEFERRED, do not build yet)
- Context menu "Exclude this folder (never delete)": Safe tab only (never tabs 2/3).
- "Exclusions..." dialog (toolbar button): list of paths with Remove + Open location.
- Excluded rows get a visible "excluded" mark; at deletion they land in
  "Blocked/skipped (excluded by user)" instead of being deleted.
- Storage: per-user file (e.g. %APPDATA%/ExtremeCleaner/exclusions.json),
  match exact path + children.
- Open question: folder-level only (precise, preferred) vs whole-program level.
- Backend was prototyped and fully removed (see git history) to keep the UI
  uncluttered; reimplement fresh when this item is scheduled.

## Deliberately OUT of scope
- Registry cleaning (no space gain, high risk, experts agree it's useless).
- Driver / software updaters, "PC speed boosters".
- Treemap disk map (WizTree owns it).
- Startup managers, process monitors.
