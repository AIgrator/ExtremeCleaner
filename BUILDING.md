# How to Build ExtremeCleaner.exe from Source

Steps to compile a working `ExtremeCleaner.exe` from the source code (Windows).

### 1. Prerequisites

- **Python 3.10** (64-bit): https://www.python.org/downloads/
- **Git**: https://git-scm.com/

### 2. Clone the repository

```powershell
git clone https://github.com/AIgrator/ExtremeCleaner.git
cd ExtremeCleaner
```

### 3. Install dependencies

```powershell
py -3.10 -m pip install pyyaml rich PySide6 Send2Trash
py -3.10 -m pip install pyinstaller
```

### 4. Bake the build stamp (required!)

The app shows a build stamp in the bottom-right corner. Generate it before
every build, or the exe will report `dev` instead of the real stamp:

```powershell
$stamp = "$(git rev-parse --short HEAD)-$(Get-Date -Format 'yyyyMMdd-HHmm')"
$stamp | Set-Content assets/build_info.txt -NoNewline
```

### 5. Close the running exe

Windows locks the running file — close `ExtremeCleaner.exe` before rebuilding,
or the build fails with `PermissionError: [WinError 5]`.

### 6. Build

```powershell
py -3.10 -m PyInstaller --noconfirm --clean --name ExtremeCleaner --onefile --windowed --icon assets/icon.ico --add-data "rules;rules" --add-data "assets;assets" --paths src --exclude-module numpy --exclude-module PIL --exclude-module matplotlib src/extreme_cleaner/cli.py
```

### 7. Result + self-test

`dist\ExtremeCleaner.exe` (~47 MB, single file, no installer needed).

Smoke test — full scan inside the exe, no window opens:

```powershell
$env:EXTREME_CLEANER_SMOKE="1"
.\dist\ExtremeCleaner.exe
Remove-Item env:EXTREME_CLEANER_SMOKE
Get-Content dist\smoke_result.txt -TotalCount 5
Remove-Item dist\smoke_result.txt
```

Expected: exit code 0, `scan_done=True`, ~239 results.

### Notes

- `assets/build_info.txt`, `dist/`, `build/`, `*.spec` are git-ignored build artifacts.
- First launch of a fresh exe takes 30–60 s (unpacking + Defender check) — normal.
- `user_rules.yaml` next to the exe holds user-added folders; `deletions.jsonl`
  next to it is the deletion log. Neither is bundled into the exe.
