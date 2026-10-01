# Cross-platform plan (Windows / Linux / macOS)

Status: NOT STARTED. Current target is Windows-only.
This file exists so the plan is not forgotten.

## Where we are now

- `os: [windows, linux, darwin]` on rules works only as a visibility filter.
- Paths are Windows-isms (`%LOCALAPPDATA%`, backslashes) and silently miss on other OSes.
- User form (`Add folder`) already tags OS by path portability
  (absolute/OS-specific path → current OS only; `~/{VAR}/$VAR` → all three).
- System section is Windows-only by design and must be rebuilt per OS from scratch.

## Steps (in order, each builds on the previous one)

### 1. Abstract path variables (foundation)
Add `{CACHE}`, `{CONFIG}`, `{DATA}` resolved per OS in `loader.expand_rule_path`:

| var      | Windows          | Linux              | macOS                    |
|----------|------------------|--------------------|--------------------------|
| `{CACHE}`  | `%LOCALAPPDATA%`   | `~/.cache`           | `~/Library/Caches`         |
| `{CONFIG}` | `%APPDATA%`        | `~/.config`          | `~/Library/Application Support` |
| `{DATA}`   | `%LOCALAPPDATA%`   | `~/.local/share`     | `~/Library/Application Support` |

Keep `{HOME}`, `~`, `$VAR` support. Without this, everything else is duct tape.

### 2. Per-OS paths
Replace single `path:` with:

```yaml
paths:
  windows: "%LOCALAPPDATA%/Google/Chrome/User Data/Default"
  linux: "~/.config/google-chrome/Default"
  darwin: "~/Library/Application Support/Google/Chrome/Default"
```

Derive `os` automatically: a rule is visible iff it has a path for the current OS.
Migrate ~200 rules file by file (browsers and VS Code first — paths differ most).

### 3. Per-OS commands
`command: {windows: ..., linux: ..., darwin: ...}`.
(`npm cache clean` is the same everywhere; `DISM`/`vssadmin`/`powercfg` are Windows-only.)

### 4. System section per OS, from scratch
- Linux: journald (`/var/log/journal`), apt/dnf/pacman caches, crash dumps.
- macOS: Xcode DerivedData, simulators, Homebrew cache.
- Windows: current set (hiberfil, VSS, WinSxS, ...).
Never port entries 1:1 — each OS gets its own research pass like the Habr article one.

### 5. User form
Done (OS tag by path portability). Nothing left here.

### 6. CI matrix (GitHub Actions: windows + linux + macOS)
- Load/scan smoke test per OS (missing-tolerant: unknown paths must show `missing`, never crash).
- Package builds per OS (PyInstaller/Nuitka or equivalent).
- No merges of OS-specific rules without a CI run on that OS — we cannot test other OSes locally.

### 7. Contributor docs
How to write cross-platform rules: abstract vars first, per-OS paths second,
official docs link required for new locations, `missing`-tolerance mandatory.
