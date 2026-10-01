"""P0/P1: guarded deletion engine.

Doctrine: trash-first (Recycle Bin, never permanent), rails before every
delete, everything logged. Only the Safe tab can
reach this module — user data and system never do.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .loader import expand_rule_path, no_console
from .scanner import ScanResult

# Names that are never deleted wherever they appear (sessions, keys, configs).
SACRED_PARTS = {"tdata", "auth.json", "account.json", "credentials.json", ".env"}


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def is_sacred(path: str) -> bool:
    return any(part.lower() in SACRED_PARTS for part in Path(path).parts)


def _blocklisted(path: str) -> str | None:
    """Exact dangerous roots. Returns reason or None."""
    p = Path(os.path.normpath(path))
    if len(p.parts) == 1 or (len(p.parts) == 2 and p.parts[1] in ("/", "\\")):
        return "drive root"
    home = _norm(str(Path.home()))
    if _norm(str(p)) == home:
        return "user profile root"
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    if _norm(str(p)) == _norm(windir):
        return "Windows directory"
    for var in ("APPDATA", "LOCALAPPDATA", "ProgramData"):
        v = os.environ.get(var)
        if v and _norm(str(p)) == _norm(v):
            return f"{var} root itself (only subfolders may be cleaned)"
    return None


def create_restore_point() -> tuple[bool, str]:
    """Best effort. Returns (ok, message). Fails without admin — caller must warn."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Checkpoint-Computer -Description 'ExtremeCleaner' -RestorePointType 'MODIFY_SETTINGS'"],
            capture_output=True, text=True, timeout=180, **no_console(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"cannot start powershell: {english_error(e)}"
    if r.returncode == 0:
        return True, "restore point created"
    # PowerShell stderr follows the OS language — never surface it raw.
    return False, f"checkpoint failed (exit {r.returncode}) — usually: not running as admin"


@dataclass
class CleanAction:
    label: str
    kind: str  # "delete" | "command"
    paths: list[str] = field(default_factory=list)
    command: str = ""
    size_bytes: int = 0


def _concrete_paths(res: ScanResult) -> list[str]:
    """Leaf dirs/files this result would delete. clean_contents keeps the base dir itself."""
    rule = res.rule
    if rule.kind == "empty_bin":
        return []  # handled by SHEmptyRecycleBin, never by file walk
    if rule.options or (rule.kind == "clean_selected" and rule.subpaths):
        out = []
        for c in (res.children or []):
            if c.exists and c.resolved and (c.size_bytes > 0 or c.files > 0):
                out.extend(_targets_of_single(c.resolved, c.rule.kind))
        return out
    if rule.kind == "old_versions" and rule.parent:
        return [c.resolved for c in (res.children or []) if c.exists and c.resolved]
    if rule.path:
        base = expand_rule_path(rule.path)
        if _safe_exists(base):
            return _targets_of_single(str(base), rule.kind)
    return []


def _targets_of_single(path: str, kind: str) -> list[str]:
    p = Path(path)
    if kind == "clean_contents":
        try:
            if p.is_dir() and not p.is_symlink():
                return [str(x) for x in p.iterdir()]
        except OSError:
            return []
    return [path]


def _tool_missing(command: str) -> bool:
    import shlex
    import shutil

    try:
        prog = shlex.split(command, posix=False)[0].strip('"') if command.strip() else ""
    except ValueError:
        return True
    return bool(prog) and shutil.which(prog) is None and not Path(prog).exists()


def _safe_exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:
        return False


def plan_deletion(results: list[ScanResult]) -> tuple[list[CleanAction], list[str]]:
    """Build actions for CHECKED safe-tab leaves. Returns (actions, blocked_reasons)."""
    actions: list[CleanAction] = []
    blocked: list[str] = []
    for res in results:
        for leaf in _iter_checked_leaves(res):
            rule = leaf.rule
            if rule.tier != "safe" or rule.category == "system" or rule.safe == "never_full":
                blocked.append(f"{rule.id}: not a safe-tab item, skipped")
                continue
            if rule.kind == "empty_bin":
                actions.append(CleanAction(f"{rule.name}: empty permanently (no undo!)", "empty_bin",
                                           size_bytes=leaf.size_bytes))
                continue
            if rule.kind == "run_command" and rule.command:
                if rule.exec:
                    if _tool_missing(rule.command):
                        if rule.path and _safe_exists(expand_rule_path(rule.path)):
                            base = str(expand_rule_path(rule.path))
                            actions.append(CleanAction(
                                f"{rule.name}: tool missing, deleting cache files directly: {base}",
                                "delete", _targets_of_single(base, "clean_contents"),
                                size_bytes=leaf.size_bytes))
                        else:
                            blocked.append(f"{rule.id}: tool not found in PATH, skipping")
                    else:
                        actions.append(CleanAction(f"{rule.name} [{rule.command}]", "command",
                                                   command=rule.command, size_bytes=leaf.size_bytes))
                else:
                    blocked.append(f"{rule.id}: manual instruction, do it yourself — {rule.command}")
                continue
            for p in _concrete_paths(leaf):
                reason = _blocklisted(p)
                if reason:
                    blocked.append(f"{p}: blocked ({reason})")
                    continue
                if is_sacred(p):
                    blocked.append(f"{p}: sacred name, skipped")
                    continue
                actions.append(CleanAction(f"{rule.name}: {p}", "delete", [p], size_bytes=leaf.size_bytes))
    # Drop file actions nested inside dir actions (dir delete covers them; avoids double estimate).
    dirs = {a.paths[0] for a in actions if a.kind == "delete" and Path(a.paths[0]).is_dir()}
    if dirs:
        kept = []
        for a in actions:
            if a.kind == "delete" and any(
                _norm(a.paths[0]) != _norm(d) and _norm(a.paths[0]).startswith(_norm(d) + os.sep) for d in dirs
            ):
                continue
            kept.append(a)
        actions = kept
    return actions, blocked


def _iter_checked_leaves(res: ScanResult):
    """Yield leaf ScanResults. Caller passes only checked ones (GUI) or all (CLI audit)."""
    if res.children:
        for c in res.children:
            yield from _iter_checked_leaves(c)
    else:
        yield res


# Windows error messages follow the OS language — never show them raw in the UI.
_WINERROR_EN: dict[int, str] = {
    2: "The system cannot find the file specified",
    3: "The system cannot find the path specified",
    5: "Access is denied",
    6: "The handle is invalid",
    32: "The file is being used by another process",
    33: "The process cannot access the file because it is being used by another process",
    80: "The file exists",
    87: "The parameter is incorrect",
    123: "The filename, directory name, or volume label syntax is incorrect",
    145: "The directory is not empty",
    161: "The specified path is invalid",
    183: "Cannot create a file when that file already exists",
    206: "The filename or extension is too long",
}


def english_error(e: BaseException) -> str:
    """One-line English OS error text (localized Windows messages are dropped)."""
    code = getattr(e, "winerror", None)
    if isinstance(code, int) and code in _WINERROR_EN:
        return f"[WinError {code}] {_WINERROR_EN[code]}"
    if isinstance(code, int):
        return f"[WinError {code}] OS error"
    if isinstance(e, OSError) and isinstance(getattr(e, "errno", None), int):
        txt = os.strerror(e.errno)  # CRT table — always English
        if txt and txt.isascii():
            return f"{type(e).__name__}: {txt}"
    if isinstance(e, OSError) and e.strerror and e.strerror.isascii():
        return e.strerror
    return type(e).__name__


def execute_delete(paths: list[str], use_trash: bool = True) -> tuple[int, list[str]]:
    """Delete entries (files or dirs). Returns (freed_bytes_estimate, errors)."""
    import send2trash

    freed, errors = 0, []
    for p in paths:
        try:
            size = _quick_size(p)
            if use_trash:
                send2trash.send2trash(p)
            else:
                import shutil

                if Path(p).is_dir() and not Path(p).is_symlink():
                    shutil.rmtree(p, ignore_errors=False)
                else:
                    Path(p).unlink(missing_ok=True)
            freed += size
        except Exception as e:  # noqa: BLE001 - report, keep going
            errors.append(f"{p}: {english_error(e)}")
    return freed, errors


def _quick_size(p: str) -> int:
    total = 0
    try:
        pp = Path(p)
        if pp.is_file():
            return pp.stat().st_size
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def empty_recycle_bin() -> tuple[int, list[str]]:
    """Really empty the bin. send2trash is denied there, so: SHEmpty (all drives,
    then C:), then PowerShell Clear-RecycleBin. Returns (freed, errors)."""
    import ctypes
    from ctypes import wintypes

    shedll = ctypes.WinDLL("shell32", use_last_error=True)

    class RBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("i64Size", ctypes.c_int64),
                    ("i64NumItems", ctypes.c_int64)]

    def bin_size() -> int:
        info = RBINFO()
        info.cbSize = ctypes.sizeof(RBINFO)
        if shedll.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return max(0, info.i64Size)
        return -1

    before = bin_size()
    if before == 0:
        return 0, []
    flags = 0x1 | 0x2 | 0x4  # NOCONFIRMATION | NOPROGRESSUI | NOSOUND
    if shedll.SHEmptyRecycleBinW(None, None, flags) != 0:
        if shedll.SHEmptyRecycleBinW("C:\\", None, flags) != 0:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -DriveLetter 'C:' -Force -ErrorAction Stop"],
                               capture_output=True, text=True, encoding="cp866", errors="replace", timeout=300,
                               **no_console())
            if r.returncode != 0:
                return 0, [f"empty bin failed (tried API all-drives, C:, PowerShell): {(r.stderr or '')[:200]}"]
    after = bin_size()
    freed = max(0, before - after) if before >= 0 and after >= 0 else 0
    return freed, []


def running_processes(wanted: list[str]) -> list[str]:
    """Which of the wanted exe names are currently running (case-insensitive)."""
    want = {w.lower() for w in wanted}
    if not want:
        return []
    found: set[str] = set()
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                           encoding="cp866", errors="replace", timeout=30, **no_console())
    except (OSError, subprocess.SubprocessError):
        return []
    for line in (r.stdout or "").splitlines():
        name = line.strip().strip('"').split('","')[0].strip('"').lower()
        if name in want:
            found.add(name)
    return sorted(found)


# Never offered for closing: antivirus/security must not be touched (their cache
# is shown as instructions only — the product manages itself).
NO_CLOSE_EXES = {
    "msmpeng.exe", "securityhealthservice.exe",                      # Windows Defender
    "avp.exe", "avpui.exe",                                          # Kaspersky
    "ekrn.exe", "egui.exe",                                          # ESET
    "avastsvc.exe", "avgui.exe",                                     # Avast
    "avgidsagent.exe", "avgui.exe",                                  # AVG
    "bdagent.exe", "bdservicehost.exe",                              # Bitdefender
    "ccsvchst.exe", "ns.exe",                                        # Norton/Symantec
    "savservice.exe", "sophosui.exe",                                # Sophos
    "wrsa.exe",                                                      # Webroot
    "dwservice.exe", "dwengine.exe",                                 # Dr.Web
    "cmdagent.exe",                                                  # Comodo
    "mbamservice.exe", "mbamtray.exe",                               # Malwarebytes
}


def closeable_processes(running: list[str]) -> list[str]:
    """Subset of running exes we are allowed to ask to close (no AV/security)."""
    return [p for p in running if p not in NO_CLOSE_EXES]


def close_programs(names: list[str], timeout: float = 6.0) -> tuple[list[str], list[str]]:
    """Ask running programs to close gracefully (taskkill /IM posts WM_CLOSE, no /F).

    Returns (closed, still_running). Apps showing their own prompts (unsaved
    work) may stay — the caller re-checks and lets the user decide.
    """
    import time

    for name in names:
        try:
            subprocess.run(["taskkill", "/IM", name], capture_output=True, timeout=15, **no_console())
        except (OSError, subprocess.SubprocessError):
            pass
    still = running_processes(names)
    deadline = time.time() + timeout
    while still and time.time() < deadline:
        time.sleep(1.0)
        still = running_processes(names)
    return ([n for n in names if n not in still], still)


def log_deletion(actions: list[CleanAction], freed: int, errors: list[str], path=None) -> Path:
    from .loader import data_dir

    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "freed_bytes": freed,
        "errors": errors,
        "actions": [{"label": a.label, "kind": a.kind, "paths": a.paths, "command": a.command} for a in actions],
    }
    log = Path(path) if path else data_dir() / "deletions.jsonl"
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log
