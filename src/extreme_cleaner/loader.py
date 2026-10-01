"""Load YAML rules, expand paths, filter by current OS."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import yaml

from .models import Rule, RuleOption


def _dict_to_option(d: dict) -> RuleOption:
    return RuleOption(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        kind=str(d.get("kind", "clean_contents")),
        path=str(d.get("path", "")),
        command=str(d.get("command", "")),
        safe=str(d.get("safe", "safe")),
        describe=str(d.get("describe", "")),
        subpaths=list(d.get("subpaths", [])),
        parent=str(d.get("parent", "")),
        match=str(d.get("match", "*")),
        keep=list(d.get("keep", [])),
        processes=list(d.get("processes", [])),
    )

_CURRENT_OS = {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(
    platform.system().lower(), platform.system().lower()
)


def expand_rule_path(raw: str) -> Path:
    """Expand %VAR% (Windows), $VAR, ~ and {HOME}/{LOCALAPPDATA}/{APPDATA}."""
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return Path("")  # never resolve empty to cwd — missing by design
    s = s.replace("{HOME}", str(Path.home()))
    if "LOCALAPPDATA" in os.environ:
        s = s.replace("{LOCALAPPDATA}", os.environ["LOCALAPPDATA"])
    if "APPDATA" in os.environ:
        s = s.replace("{APPDATA}", os.environ["APPDATA"])
    s = os.path.expandvars(os.path.expanduser(s))
    return Path(s)


def _default_tier(d: dict) -> str:
    # safe tab: trash anyone may delete. userdata tab: YOUR data, program never touches.
    if d.get("category") == "system" or d.get("safe") == "never_full":
        return "system"
    if d.get("safe") == "safe" or d.get("kind") == "old_versions":
        return "safe"
    return "userdata"


def _dict_to_rule(d: dict, file_group: str = "", user_made: bool = False) -> Rule:
    return Rule(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        path=str(d.get("path", "")),
        kind=str(d.get("kind", "clean_contents")),
        command=str(d.get("command", "")),
        safe=str(d.get("safe", "safe")),
        describe=str(d.get("describe", "")),
        os=list(d.get("os", ["windows"])),
        subpaths=list(d.get("subpaths", [])),
        careful_subpaths=list(d.get("careful_subpaths", [])),
        category=str(d.get("category", file_group or "cache")),
        group=str(d.get("group", file_group or "")),
        program=str(d.get("program", "")),
        parent=str(d.get("parent", "")),
        match=str(d.get("match", "*")),
        keep=list(d.get("keep", [])),
        options=[_dict_to_option(o) for o in d.get("options", []) if isinstance(o, dict)],
        discover=str(d.get("discover", "")),
        auto_keep=str(d.get("auto_keep", "")),
        exe=str(d.get("exe", "")),
        search=str(d.get("search", "")),
        tier=str(d.get("tier") or _default_tier(d)),
        docs=str(d.get("docs", "")),
        user_made=user_made,
        pin=bool(d.get("pin", False)),
        exec=bool(d.get("exec", False)),
        processes=list(d.get("processes", [])),
    )


def load_rules_from_file(path: Path, user_made: bool = False) -> list[Rule]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    if isinstance(data, list):
        items, file_group = data, ""
    else:
        items, file_group = data.get("rules", []), str(data.get("group", "") or "")
    return [_dict_to_rule(d, file_group, user_made) for d in items if isinstance(d, dict) and d.get("id")]


def load_all_rules(project_root: Path) -> list[Rule]:
    """Built-in + custom + user rules. Skip rules not meant for this OS."""
    base = bundle_dir()  # bundled YAML when frozen, project tree otherwise
    files: list[Path] = []
    files += sorted((base / "rules" / "built-in").glob("*.yaml"))
    files += sorted((base / "rules" / "custom").glob("*.yaml"))
    user_file = project_root / "user_rules.yaml"
    if user_file.exists():
        files.append(user_file)
    rules: list[Rule] = []
    for fp in files:
        try:
            rules.extend(load_rules_from_file(fp, user_made=(fp.name == "user_rules.yaml")))
        except Exception as e:
            print(f"[warn] skip {fp.name}: {e}")
    return [r for r in rules if _CURRENT_OS in [o.lower() for o in r.os]]


def validate_rule_files(project_root: Path) -> list[str]:
    """Return [filename: error] for built-in files that fail to parse. Empty = all good."""
    bad: list[str] = []
    for fp in sorted((bundle_dir() / "rules" / "built-in").glob("*.yaml")):
        try:
            load_rules_from_file(fp)
        except Exception as e:  # noqa: BLE001 - report, keep going
            bad.append(f"{fp.name}: {e}")
    return bad


def project_root_from_here() -> Path:
    # src/extreme_cleaner/loader.py -> project root (3 levels up).
    # Frozen (PyInstaller onefile): the exe folder — writable user data lives there.
    import sys

    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """Read-only bundled data (rules/, assets/): inside the exe package when frozen."""
    import sys

    if bool(getattr(sys, "frozen", False)):
        return Path(sys._MEIPASS)  # noqa: SLF001 - PyInstaller runtime dir
    return project_root_from_here()


def data_dir() -> Path:
    """Writable user data (user_rules.yaml, deletions.jsonl, smoke_result.txt)."""
    return project_root_from_here()


def build_label() -> str:
    """'build <stamp>' for a frozen exe (stamp baked into assets/ at compile time), else 'dev'."""
    try:
        stamp = (bundle_dir() / "assets" / "build_info.txt").read_text(encoding="utf-8").strip()
    except OSError:
        stamp = ""
    return f"build {stamp}" if stamp else "dev"


def no_console() -> dict:
    """subprocess kwargs hiding child console windows (a windowed exe would flash them)."""
    import subprocess

    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _slug(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "custom"


def _read_user_entries(project_root: Path) -> list[dict]:
    import yaml

    user_file = project_root / "user_rules.yaml"
    try:
        data = yaml.safe_load(user_file.read_text(encoding="utf-8")) or []
    except OSError:
        data = []
    return [r for r in data if isinstance(r, dict)]


def _write_user_entries(project_root: Path, entries: list[dict]) -> None:
    import yaml

    header = "# User folders added via GUI (Add folder). Safe = trash tab, userdata = manual review tab.\n"
    (project_root / "user_rules.yaml").write_text(
        header + yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _rule_oses(path: str) -> list[str]:
    """Absolute/OS-specific paths stick to the current OS; portable ones (~/{VAR}) go everywhere."""
    import platform
    import re

    current = {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(platform.system().lower(), "windows")
    p = (path or "").strip()
    if p.startswith(("~", "{")) or "$" in p:
        return ["windows", "linux", "darwin"]
    if re.match(r"^[A-Za-z]:", p) or "\\" in p or "%" in p:
        return [current]
    if p.startswith("/"):
        return [current]  # absolute POSIX path, almost surely not portable
    return ["windows", "linux", "darwin"]


def save_user_rule(project_root: Path, name: str, path: str, tier: str, describe: str = "") -> Rule:
    """Append a user folder to user_rules.yaml. Tier: safe (trash) or userdata (manual review)."""
    import yaml

    if tier not in ("safe", "userdata"):
        raise ValueError("tier must be 'safe' or 'userdata'")
    if not path.strip():
        raise ValueError("path is empty")
    user_file = project_root / "user_rules.yaml"
    try:
        existing = yaml.safe_load(user_file.read_text(encoding="utf-8")) or []
    except OSError:
        existing = []
    taken = {str(r.get("id", "")) for r in existing if isinstance(r, dict)}
    base, suffix, rid = _slug(name), 2, _slug(name)
    while rid in taken:
        rid, suffix = f"{base}-{suffix}", suffix + 1
    entry = {
        "id": rid,
        "name": name.strip(),
        "path": path.strip(),
        "kind": "clean_contents",
        "category": "other",
        "group": "User",
        "safe": "safe" if tier == "safe" else "careful",
        "tier": tier,
        "describe": describe.strip() or "Added by user",
        "os": _rule_oses(path),
    }
    existing.append(entry)
    _write_user_entries(project_root, existing)
    return _dict_to_rule(entry)


def update_user_rule(project_root: Path, rid: str, name: str, path: str, tier: str, describe: str = "") -> Rule:
    """Edit a user folder in place (matched by id)."""
    if tier not in ("safe", "userdata"):
        raise ValueError("tier must be 'safe' or 'userdata'")
    if not path.strip():
        raise ValueError("path is empty")
    entries = _read_user_entries(project_root)
    for r in entries:
        if str(r.get("id", "")) == rid:
            r["name"] = name.strip()
            r["path"] = path.strip()
            r["safe"] = "safe" if tier == "safe" else "careful"
            r["tier"] = tier
            r["describe"] = describe.strip() or "Added by user"
            r["group"] = "User"
            _write_user_entries(project_root, entries)
            return _dict_to_rule(r)
    raise ValueError(f"unknown user rule: {rid}")


def delete_user_rule(project_root: Path, rid: str) -> None:
    entries = [r for r in _read_user_entries(project_root) if str(r.get("id", "")) != rid]
    _write_user_entries(project_root, entries)
