"""Honest size scanner (no NTFS hardlink double-count handling yet — MVP)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dataclasses import replace

from .loader import expand_rule_path
from .models import Rule, RuleOption


SUBPATH_MEANING = {
    "cache": "Images, video, scripts and styles of visited pages",
    "code cache": "Compiled JavaScript (V8 bytecode), rebuilt on visit",
    "gpucache": "Compiled GPU shaders, rebuilt on visit",
    "shadercache": "Compiled GPU shaders, rebuilt on visit",
    "shader-cache": "Compiled GPU shaders, rebuilt on visit",
    "startupcache": "Startup cache, rebuilt on launch",
    "cache2": "Web content cache (pages/images) — rebuilt as you browse",
    "thumbnails": "Page thumbnails, rebuilt on demand",
    "image_cache": "In-memory image cache copy on disk, rebuilt",
    "dawngraphitecache": "WebGPU (Graphite) shader cache, rebuilt on visit",
    "dawnwebgpucache": "WebGPU shader cache, rebuilt on visit",
    "system cache": "Browser component/Safe Browsing cache, re-downloaded",
    "service worker": "Offline data of web apps — may log you out of sites",
    "indexeddb": "Local site databases (Figma, Telegram Web, Notion) — may log you out",
    "file system": "Temporary files saved by websites",
    "history": "Visited sites + downloads log. Program never deletes — clear in-app (Ctrl+Shift+Del)",
    "cookies": "Site login sessions. Clearing logs you out everywhere; program never deletes",
    "web data": "Form autofill: addresses, search history. Program never deletes",
    "sessions": "Open tabs/windows. Program never deletes",
    "login data": "SAVED PASSWORDS — program never touches",
    "places.sqlite": "History + downloads + bookmarks (Firefox). Program never deletes",
    "cookies.sqlite": "Site cookies (Firefox). Program never deletes",
    "formhistory.sqlite": "Form autofill (Firefox). Program never deletes",
    "sessionstore.jsonlz4": "Open tabs/session (Firefox). Program never deletes",
}

# Human-readable row names, CCleaner-style categories (folder leaf -> label).
SUBPATH_LABEL = {
    "cache": "Internet cache",
    "cache2": "Internet cache",
    "system cache": "Component cache",
    "code cache": "Code cache",
    "gpucache": "GPU cache",
    "dawngraphitecache": "GPU cache (WebGPU)",
    "dawnwebgpucache": "GPU cache (WebGPU)",
    "dawncache": "GPU cache (WebGPU)",
    "shader-cache": "Shader cache",
    "shadercache": "Shader cache",
    "grshadercache": "GPU shader cache",
    "graphitedawncache": "GPU shader cache (WebGPU)",
    "gpupersistentcache": "GPU persistent cache",
    "startupcache": "Startup cache",
    "thumbnails": "Thumbnails",
    "image_cache": "Image cache",
    "autofillaimodelcache": "AI model cache",
    "optimization_guide_hint_cache_store": "AI hint cache",
    "tablo cache": "Tablo cache",
    "turboappcache": "Turbo app cache",
    "service worker": "Service Worker (offline web apps)",
    "indexeddb": "IndexedDB (site databases)",
    "file system": "File System (site files)",
    "history": "History: visited sites + downloads",
    "cookies": "Cookies (site logins)",
    "web data": "Form autofill",
    "sessions": "Session (open tabs)",
    "login data": "Saved passwords (never touched)",
    "places.sqlite": "History + downloads (places.sqlite)",
    "cookies.sqlite": "Cookies (cookies.sqlite)",
    "formhistory.sqlite": "Form autofill (formhistory.sqlite)",
    "sessionstore.jsonlz4": "Open tabs/session (sessionstore)",
}


def _subpath_to_option(rule: Rule, base, sub: str) -> RuleOption:
    leaf = Path(sub).name
    return RuleOption(
        id=sub.lower().replace(" ", "-"),
        name=SUBPATH_LABEL.get(leaf.lower(), sub),
        kind="clean_contents",
        path=str(base / sub),
        safe="careful" if sub in (rule.careful_subpaths or []) else rule.safe,
        describe=SUBPATH_MEANING.get(leaf.lower(), f"Part of {rule.name}"),
        processes=list(rule.processes),
    )


def _expand_selected_options(rule: Rule) -> list[RuleOption]:
    """Fixed subpaths + glob patterns (e.g. Firefox *.default*/cache2)."""
    base = expand_rule_path(rule.path)
    opts: list[RuleOption] = []
    careful = {Path(s).name.lower() for s in (rule.careful_subpaths or [])}
    for sub in rule.subpaths:
        if any(c in sub for c in "*?["):
            try:
                matches = sorted(base.glob(sub), key=lambda p: p.name.lower())
            except OSError:
                continue
            parents = sorted({m.parent for m in matches}, key=lambda p: p.name.lower())
            multi = len(parents) > 1
            for m in matches:
                try:
                    if m.is_symlink():
                        continue
                except OSError:
                    continue
                rel = m.relative_to(base) if base in m.parents else m.name
                leaf = m.name
                disp = SUBPATH_LABEL.get(leaf.lower(), leaf)
                if multi:
                    prof = m.parent.name
                    if "." in prof:
                        prof = prof.split(".", 1)[1]  # "f1a2b3.default-release" -> "default-release"
                    name = f"{disp} ({prof})"
                else:
                    name = disp
                opts.append(
                    RuleOption(
                        id=str(rel).lower().replace(" ", "-").replace("\\", "-").replace("/", "-"),
                        name=name,
                        kind="clean_contents",
                        path=str(m),
                        safe="careful" if leaf.lower() in careful else rule.safe,
                        describe=SUBPATH_MEANING.get(leaf.lower(), f"Part of {rule.name}"),
                        processes=list(rule.processes),
                    )
                )
        else:
            opts.append(_subpath_to_option(rule, base, sub))
    return opts


@dataclass
class ScanResult:
    rule: Rule
    exists: bool
    size_bytes: int = 0
    files: int = 0
    errors: int = 0
    resolved: str = ""
    parts: list[str] = None  # per-folder breakdown, e.g. ["130.0 — 1.2 GB", ...]
    children: list["ScanResult"] = None  # nested options, e.g. opencode cache vs history

    def __post_init__(self) -> None:
        if self.parts is None:
            self.parts = []
        if self.children is None:
            self.children = []


def _size_subtree(root: Path) -> tuple[int, int, int]:
    total, count, errors = 0, 0, 0
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            errors += 1
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.name.lower() == "desktop.ini":
                    continue  # shell metadata, never user content
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                    count += 1
            except OSError:
                errors += 1
    return total, count, errors


def dir_size(root: Path, workers: int = 8) -> tuple[int, int, int]:
    """Honest size. Top-level files counted inline, subdirs fanned out to threads (SSD win)."""
    from concurrent.futures import ThreadPoolExecutor

    total, count, errors = 0, 0, 0
    subdirs: list[str] = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.name.lower() == "desktop.ini":
                        continue  # shell metadata, never user content
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                        count += 1
                except OSError:
                    errors += 1
    except OSError:
        return 0, 0, 1
    if len(subdirs) < 2 or workers <= 1:
        for sd in subdirs:
            s, c, e = _size_subtree(Path(sd))
            total += s
            count += c
            errors += e
        return total, count, errors
    with ThreadPoolExecutor(max_workers=min(workers, len(subdirs))) as ex:
        for s, c, e in ex.map(_size_subtree, [Path(sd) for sd in subdirs]):
            total += s
            count += c
            errors += e
    return total, count, errors


def _option_to_rule(rule: Rule, opt) -> Rule:
    return Rule(
        id=f"{rule.id}:{opt.id}",
        name=opt.name,
        path=opt.path,
        kind=opt.kind,
        command=opt.command,
        safe=opt.safe,
        describe=opt.describe,
        os=list(rule.os),
        subpaths=list(opt.subpaths),
        category=rule.category,
        group=rule.group,
        program=rule.program,
        tier=rule.tier,
        docs=rule.docs,
        user_made=rule.user_made,
        pin=rule.pin,
        exec=rule.exec,
        parent=opt.parent,
        match=opt.match,
        keep=list(opt.keep),
        auto_keep=rule.auto_keep,
        exe=rule.exe,
        processes=list(opt.processes or rule.processes),
    )


def _parse_vdf(text: str) -> dict:
    """Minimal Valve KeyValue parser: quoted strings + braces. Enough for manifests."""
    import re

    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\{|\}', text)
    stack: list[dict] = [{}]
    keys: list[str] = []
    pending: str | None = None
    for tok in tokens:
        if tok == "{":
            node: dict = {}
            if pending is not None:
                stack[-1][pending] = node
                keys.append(pending)
                pending = None
            stack.append(node)
        elif tok == "}":
            if len(stack) > 1:
                stack.pop()
        else:
            val = tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if pending is None:
                pending = val
            else:
                stack[-1][pending] = val
                pending = None
    return stack[0]


def _steam_roots(hint: Path | None = None) -> list[Path]:
    roots: list[Path] = []
    if hint is not None:
        roots.append(hint)
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except OSError:
        pass
    for cand in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
        roots.append(cand)
    seen, out = set(), []
    for r in roots:
        try:
            rp = r.resolve()
        except OSError:
            continue
        if rp not in seen and (rp / "steamapps" / "libraryfolders.vdf").exists():
            seen.add(rp)
            out.append(rp)
    return out


def _discover_steam_games(roots: list[Path] | None = None) -> list[tuple[str, Path, int]]:
    """Installed Steam games from manifests: (name, dir, SizeOnDisk). No disk walk."""
    if roots is None:
        roots = _steam_roots()
    libs: list[Path] = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            data = _parse_vdf(vdf.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        for node in data.get("libraryfolders", {}).values():
            if isinstance(node, dict) and node.get("path"):
                libs.append(Path(node["path"]) / "steamapps")
        libs.append(root / "steamapps")
    games: dict[str, tuple[str, Path, int]] = {}
    for lib in libs:
        try:
            manifests = sorted(lib.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for mf in manifests:
            try:
                app = _parse_vdf(mf.read_text(encoding="utf-8", errors="ignore")).get("AppState", {})
                name = str(app.get("name", mf.stem))
                inst = str(app.get("installdir", ""))
                size = int(str(app.get("SizeOnDisk", "0") or "0"))
            except (OSError, ValueError):
                continue
            if inst and name not in games:
                games[name] = (name, lib / "common" / inst, size)
    return sorted(games.values(), key=lambda g: g[0].lower())


def _scan_discovered_steam(rule: Rule) -> ScanResult:
    children: list[ScanResult] = []
    for name, path, size in _discover_steam_games():
        sub = Rule(
            id=f"{rule.id}:{name[:40]}", name=name,
            path=str(path), kind="run_command",
            command="Uninstall via Steam (or delete; cloud saves stay in Steam Cloud)",
            safe="careful", describe="Installed game — size from manifest, no disk walk",
            os=list(rule.os), category=rule.category,
        )
        c = scan_rule(sub)
        c.size_bytes = size or c.size_bytes  # manifest is instant; walk only as fallback
        children.append(c)
    total = sum(c.size_bytes for c in children)
    files = sum(c.files for c in children)
    errors = sum(c.errors for c in children)
    exists = bool(children)
    parts = [f"{c.rule.name} — {fmt_size(c.size_bytes)}" for c in children if c.exists]
    res = ScanResult(rule, exists, total, files, errors, "; ".join(parts) or rule.describe, parts)
    res.children = children
    return res


def _discover_gog_games(db_path: Path | None = None) -> list[tuple[str, Path, int]]:
    """Installed GOG games from galaxy.db (missing-tolerant: unknown schema/version -> [])."""
    import sqlite3

    db = db_path or Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db"
    games: list[tuple[str, Path, int]] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    except Exception:
        return []
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "InstalledBaseProducts" in tables:
            cols = [c[1] for c in con.execute("PRAGMA table_info(InstalledBaseProducts)")]
            name_c = next((c for c in ("title", "productTitle", "productId") if c in cols), None)
            path_c = next((c for c in ("installationPath", "installPath", "path") if c in cols), None)
            if name_c and path_c:
                for row in con.execute(f'SELECT "{name_c}", "{path_c}" FROM InstalledBaseProducts'):
                    nm, p = str(row[0] or ""), str(row[1] or "")
                    if nm and p:
                        games.append((nm, Path(p), 0))
        if "LibraryReleases" in tables:
            cols = {c[1] for c in con.execute("PRAGMA table_info(LibraryReleases)")}
            if {"title", "installationPath"} <= cols:
                seen = {g[0] for g in games}
                for title, ipath in con.execute("SELECT title, installationPath FROM LibraryReleases WHERE installationPath IS NOT NULL AND installationPath != ''"):
                    if title not in seen:
                        games.append((str(title), Path(str(ipath)), 0))
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass
    return sorted(games, key=lambda g: g[0].lower())


def _discover_epic_games(manifest_dir: Path | None = None) -> list[tuple[str, Path, int]]:
    """Installed Epic games from *.item manifests (JSON)."""
    import json

    base = manifest_dir or Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    games: list[tuple[str, Path, int]] = []
    try:
        files = sorted(base.glob("*.item"))
    except OSError:
        return []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            nm, loc = str(d.get("DisplayName", "") or ""), str(d.get("InstallLocation", "") or "")
            size = int(d.get("InstallSize", 0) or 0)
        except (OSError, ValueError, TypeError):
            continue
        if nm and loc:
            games.append((nm, Path(loc), size))
    return sorted(games, key=lambda g: g[0].lower())


def _scan_discovered_list(rule: Rule, games: list[tuple[str, Path, int]], hint: str) -> ScanResult:
    children: list[ScanResult] = []
    for name, path, size in games:
        sub = Rule(
            id=f"{rule.id}:{name[:40]}", name=name,
            path=str(path), kind="run_command",
            command=hint,
            safe="careful", describe="Installed game — uninstall via its launcher",
            os=list(rule.os), category=rule.category,
        )
        c = scan_rule(sub)
        c.size_bytes = size or c.size_bytes
        children.append(c)
    total = sum(c.size_bytes for c in children)
    files = sum(c.files for c in children)
    errors = sum(c.errors for c in children)
    exists = bool(children)
    parts = [f"{c.rule.name} — {fmt_size(c.size_bytes)}" for c in children if c.exists]
    res = ScanResult(rule, exists, total, files, errors, "; ".join(parts) or rule.describe, parts)
    res.children = children
    return res


def _scan_discovered_steam(rule: Rule) -> ScanResult:
    return _scan_discovered_list(
        rule, _discover_steam_games(),
        "Uninstall via Steam (or delete; cloud saves stay in Steam Cloud)",
    )


def _discover_virtualbox_machines(xml_path=None) -> list[tuple[str, Path]]:
    """Read VM registry: VirtualBox allows VM folders anywhere, XML knows all.

    Returns [(vm_name, vm_dir)]. Empty list if VirtualBox never ran / no VMs.
    """
    from xml.etree import ElementTree as ET

    xml = Path(xml_path) if xml_path else Path.home() / ".VirtualBox" / "VirtualBox.xml"
    try:
        tree = ET.parse(xml)
    except (OSError, ET.ParseError):
        return []
    found = []
    for el in tree.getroot().iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "MachineEntry":
            src = el.get("src", "")
            if not src:
                continue
            vbox = Path(src)
            vm_dir = vbox.parent if vbox.is_absolute() else (xml.parent / vbox).parent
            found.append((vbox.stem, vm_dir))
    return found


def _scan_discovered_virtualbox(rule: Rule) -> ScanResult:
    children: list[ScanResult] = []
    for vm_name, vm_dir in _discover_virtualbox_machines():
        logs = Rule(
            id=f"{rule.id}:{vm_name}:logs", name=f"{vm_name} — logs",
            path=str(vm_dir / "Logs"), kind="clean_contents",
            safe="safe", describe="Per-VM Logs, rotate freely",
            os=list(rule.os), category=rule.category,
        )
        snaps = Rule(
            id=f"{rule.id}:{vm_name}:snapshots", name=f"{vm_name} — snapshots",
            path=str(vm_dir / "Snapshots"), kind="run_command",
            command="VirtualBox Manager > Snapshots > Delete (merges). NEVER by hand",
            safe="careful", describe="SIZE ONLY + in-manager delete",
            os=list(rule.os), category=rule.category,
        )
        children.append(scan_rule(logs))
        children.append(scan_rule(snaps))
    total = sum(c.size_bytes for c in children)
    files = sum(c.files for c in children)
    errors = sum(c.errors for c in children)
    exists = bool(children)
    parts = [f"{c.rule.name} — {fmt_size(c.size_bytes)}" for c in children if c.exists]
    res = ScanResult(rule, exists, total, files, errors, "; ".join(parts) or rule.describe, parts)
    res.children = children
    return res


def scan_rule(rule: Rule) -> ScanResult:
    if rule.discover == "virtualbox":
        return _scan_discovered_virtualbox(rule)
    if rule.discover == "steam":
        return _scan_discovered_steam(rule)
    if rule.discover == "gog":
        return _scan_discovered_list(
            rule, _discover_gog_games(), "Uninstall via GOG Galaxy (DRM-free games run without it)")
    if rule.discover == "epic":
        return _scan_discovered_list(
            rule, _discover_epic_games(), "Uninstall via Epic launcher; verify files first")
    if rule.discover == "restore-points":
        return _scan_restore_points(rule)
    if rule.kind == "empty_bin":
        return _scan_bin(rule)
    if not rule.options and rule.kind == "clean_selected" and rule.subpaths and rule.path:
        # Every subfolder gets its own checkbox: Chrome Cache vs IndexedDB etc.
        opts = _expand_selected_options(rule)
        if not opts:
            base = expand_rule_path(rule.path)
            ex = _safe_exists(base)
            if ex is True:
                return ScanResult(rule, True, 0, 0, 0, str(base))
            if ex is None:
                return ScanResult(rule, True, 0, 0, 1, str(base))
        rule = replace(rule, options=opts)
    if rule.options:
        children = [scan_rule(_option_to_rule(rule, o)) for o in rule.options]
        total = sum(c.size_bytes for c in children)
        files = sum(c.files for c in children)
        errors = sum(c.errors for c in children)
        exists = any(c.exists for c in children)
        if not exists and rule.kind == "clean_selected" and rule.path:
            # base there, just no matches (None = locked, counts as there)
            exists = _safe_exists(expand_rule_path(rule.path)) is not False
        by_size = sorted((c for c in children if c.exists), key=lambda c: c.size_bytes, reverse=True)
        parts = [f"{c.rule.name} — {fmt_size(c.size_bytes)}" for c in by_size]
        resolved = "; ".join(c.resolved for c in children if c.exists) or rule.describe
        res = ScanResult(rule, exists, total, files, errors, resolved, parts)
        res.children = children
        return res
    if rule.kind == "old_versions" and rule.parent:
        return _scan_old_versions(rule)
    if not rule.path:
        # Command-only info rule: NO folder of its own. Never fall back to the
        # current working directory (it measured the app's own project folder).
        return ScanResult(rule, True, 0, 0, 0, "")
    base = expand_rule_path(rule.path)
    if rule.kind == "clean_selected" and rule.subpaths:
        total, count, errors, found = 0, 0, 0, False
        parts = []
        for sub in rule.subpaths:
            p = base / sub
            parts.append(str(p))
            if _safe_exists(p) is True:
                found = True
                s, c, e = dir_size(p)
                total += s
                count += c
                errors += e
        return ScanResult(rule, found, total, count, errors, "; ".join(parts))
    base = expand_rule_path(rule.path)
    ex = _safe_exists(base)
    if ex is False:
        return ScanResult(rule, False, 0, 0, 0, str(base))
    if ex is None:
        return ScanResult(rule, True, 0, 0, 1, str(base))
    try:
        if base.is_file() and not base.is_symlink():
            st = base.stat()
            return ScanResult(rule, True, st.st_size, 1, 0, str(base))
    except OSError:
        return ScanResult(rule, False, 0, 0, 1, str(base))
    s, c, e = dir_size(base)
    return ScanResult(rule, True, s, c, e, str(base))


def _detect_used_system_images() -> set[str]:
    """Parse all AVD config.ini files: image.sysdir.1=system-images\\android-35\\... ."""
    used: set[str] = set()
    avd_dir = Path.home() / ".android" / "avd"
    try:
        inis = list(avd_dir.glob("*.avd/config.ini"))
    except OSError:
        return used
    for ini in inis:
        try:
            text = ini.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("image.sysdir"):
                _, _, val = line.partition("=")
                parts = val.strip().replace("\\", "/").split("/")
                if len(parts) >= 2 and parts[0] == "system-images":
                    used.add(parts[1].lower())
    return used


# Service-account bins are not the user's trash and need admin anyway.
BIN_SKIP_SIDS = {"S-1-5-18", "S-1-5-19", "S-1-5-20"}


def _query_bin() -> tuple[int, int] | None:
    """(size, items) exactly as the shell reports the bin — what Explorer shows.

    The raw folder holds per-drive/per-user metadata ($I orphans, system SIDs)
    that Explorer never lists; walking it lies. None = API unavailable.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class RBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("i64Size", ctypes.c_int64),
                    ("i64NumItems", ctypes.c_int64)]

    try:
        shedll = ctypes.WinDLL("shell32", use_last_error=True)
        info = RBINFO()
        info.cbSize = ctypes.sizeof(RBINFO)
        # NULL root = aggregated over all drives (the "Recycle Bin" Explorer window)
        if shedll.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
            if shedll.SHQueryRecycleBinW("C:\\", ctypes.byref(info)) != 0:
                return None
        return max(0, int(info.i64Size)), max(0, int(info.i64NumItems))
    except (OSError, ValueError):
        return None


def _vss_copy_count(text: str) -> int:
    """How many shadow copies in `vssadmin list shadows` output.

    The text is localized, but kernel device paths are not: every copy has
    exactly one \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy<N> line.
    """
    import re

    return len(re.findall(r"HarddiskVolumeShadowCopy\d+", text, re.IGNORECASE))


_VSS_UNITS = {"B": 1, "Б": 1, "BYTES": 1, "БАЙТ": 1, "БАЙТА": 1, "БАЙТОВ": 1,
              "KB": 1024, "КБ": 1024, "MB": 1024**2, "МБ": 1024**2,
              "GB": 1024**3, "ГБ": 1024**3, "TB": 1024**4, "ТБ": 1024**4,
              "PB": 1024**5, "ПБ": 1024**5}
_VSS_SIZE_RE = (r"(\d+(?:(?:[^\S\r\n]|,)\d{3})*(?:[.,]\d+)?)"
                r"\s*(bytes?|KB|MB|GB|TB|PB|байт(?:а|ов)?|Б|КБ|МБ|ГБ|ТБ|ПБ)"
                r"(?![A-Za-zА-Яа-яЁё])")


def _vss_used_bytes(text: str) -> int:
    """Used shadow storage from `vssadmin list shadowstorage` output.

    The labels are localized, but the print order is fixed: the FIRST size in
    every association block is the Used value. Numbers may use a decimal comma
    and space thousands (RU) or decimal dot and comma thousands (EN).
    """
    import re

    total = 0
    for block in re.split(r"\r?\n\s*\r?\n", text):
        m = re.search(_VSS_SIZE_RE, block, re.IGNORECASE)
        if not m:
            continue
        num = re.sub(r"[^\S\r\n]", "", m.group(1))
        if "," in num and "." in num:
            num = num.replace(",", "")
        elif "," in num:
            num = num.replace(",", ".")
        try:
            value = float(num)
        except ValueError:
            continue
        total += int(value * _VSS_UNITS.get(m.group(2).upper(), 0))
    return total


def _scan_restore_points(rule: Rule) -> ScanResult:
    """Count + measure VSS shadow copies (System Restore points).

    vssadmin list works WITHOUT admin; never parse its words (localized),
    only the markers above. rc is useless (2 even when simply empty).
    """
    import subprocess

    from .loader import no_console

    def _run(args: list[str]) -> str | None:
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               encoding="oem", errors="replace", timeout=60,
                               **no_console())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return r.stdout or ""

    out = _run(["vssadmin", "list", "shadows"])
    if out is None:
        return ScanResult(rule, True, 0, 0, 1, rule.describe or "")
    count = _vss_copy_count(out)
    used = 0
    stor = _run(["vssadmin", "list", "shadowstorage"])
    if stor is not None:
        used = _vss_used_bytes(stor)
    resolved = f"{count} restore point(s), {fmt_size(used)} in shadow storage"
    return ScanResult(rule, True, used, count, 0, resolved)


def _scan_bin(rule: Rule) -> ScanResult:
    from .loader import expand_rule_path as _expand

    base = _expand(rule.path)
    if _safe_exists(base) is False:
        return ScanResult(rule, False, 0, 0, 0, str(base))
    if _safe_exists(base) is None:
        return ScanResult(rule, True, 0, 0, 1, str(base))
    queried = _query_bin()
    if queried is not None:
        size, files = queried
        return ScanResult(rule, True, size, files, 0, str(base))
    total, count, errors = 0, 0, 0
    try:
        with os.scandir(base) as it:
            entries = [e for e in it if e.name not in BIN_SKIP_SIDS]
    except OSError:
        return ScanResult(rule, True, 0, 0, 1, str(base))
    for entry in entries:
        try:
            if entry.is_symlink() or entry.name.lower() == "desktop.ini":
                continue
            if entry.is_dir(follow_symlinks=False):
                s, c, e = dir_size(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                s, c, e = entry.stat(follow_symlinks=False).st_size, 1, 0
            else:
                continue
            total += s
            count += c
            errors += e
        except OSError:
            errors += 1
    return ScanResult(rule, True, total, count, errors, str(base))


def _safe_exists(p: Path) -> bool | None:
    try:
        return p.exists()
    except OSError:
        return None  # locked (AV self-defense, admin-only): exists, but unreadable


def _exe_file_version(path) -> str:
    """VS_FIXEDFILEINFO dwFileVersion of a Windows exe ('' if unreadable)."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version.dll")
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return ""
        p, ln = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(ln)) or ln.value < 16:
            return ""
        ffi = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32))
        if ffi[0] != 0xFEEF04BD:
            return ""
        ms, ls = ffi[2], ffi[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except OSError:
        return ""


def _scan_old_versions(rule: Rule) -> ScanResult:
    """Enumerate versioned children in parent, skip active (keep) ones.

    Active version is never touched: manual `keep` names, plus
    auto_keep=exe (FileVersion of rule.exe at the parent root, else the
    child dir containing the exe) and auto_keep=android-avd.
    Returns one child ScanResult per stale version dir so the GUI gets
    per-version checkboxes and deletion gets concrete paths.
    """
    parent = expand_rule_path(rule.parent)
    if _safe_exists(parent) is False:
        return ScanResult(rule, False, 0, 0, 0, str(parent))
    if _safe_exists(parent) is None:
        return ScanResult(rule, True, 0, 0, 1, str(parent))
    keep = {k.lower() for k in rule.keep}
    if rule.auto_keep == "android-avd":
        keep |= _detect_used_system_images()
    try:
        children = sorted(parent.glob(rule.match), key=lambda p: p.name.lower())
    except OSError:
        return ScanResult(rule, True, 0, 0, 1, str(parent))
    if rule.auto_keep == "exe" and rule.exe:
        active = _exe_file_version(parent / rule.exe)
        if active and (parent / active).is_dir():
            keep.add(active.lower())
        else:  # no exe at root: keep dirs that contain it (their copy is in use)
            try:
                keep |= {c.name.lower() for c in children if c.is_dir() and (c / rule.exe).is_file()}
            except OSError:
                pass
    total, count, errors, found = 0, 0, 0, False
    scored: list[tuple[str, int]] = []
    kids: list[ScanResult] = []
    for child in children:
        if child.name.lower() in keep:
            continue
        try:
            if child.is_symlink():
                continue
            if child.is_dir():
                s, c, e = dir_size(child)
            elif child.is_file():
                s, c, e = child.stat().st_size, 1, 0
            else:
                continue
        except OSError:
            errors += 1
            continue
        found = True
        total += s
        count += c
        errors += e
        scored.append((child.name, s))
        kid_rule = replace(
            rule,
            id=f"{rule.id}:{child.name}",
            name=child.name,
            path=str(child),
            kind="clean_selected",
            parent="",
            subpaths=[],
            options=[],
            keep=[],
        )
        kids.append(ScanResult(kid_rule, True, s, c, 0, str(child)))
    scored.sort(key=lambda t: t[1], reverse=True)  # largest first for top-N display
    parts = [f"{name} — {fmt_size(s)}" for name, s in scored]
    res = ScanResult(rule, found, total, count, errors, str(parent), parts)
    res.children = kids
    return res


def scan_all(rules: list[Rule], workers: int = 4) -> list[ScanResult]:
    if len(rules) < 2 or workers <= 1:
        return [scan_rule(r) for r in rules]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(workers, len(rules))) as ex:
        return list(ex.map(scan_rule, rules))


def fmt_size(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{v:.1f} TB"
