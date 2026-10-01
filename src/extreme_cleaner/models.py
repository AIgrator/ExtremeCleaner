"""Rule model. One rule = one cleanable location. Keep it to 6 fields max."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleOption:
    """Nested checkbox inside one rule, e.g. opencode: cache (safe) vs history (careful)."""

    id: str
    name: str
    kind: str = "clean_contents"
    path: str = ""
    command: str = ""
    safe: str = "safe"
    describe: str = ""
    subpaths: list[str] = field(default_factory=list)
    parent: str = ""
    match: str = "*"
    keep: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)

@dataclass
class Rule:
    id: str
    name: str
    path: str
    kind: str = "clean_contents"  # clean_contents | run_command | clean_selected | old_versions
    command: str = ""
    safe: str = "safe"  # safe | careful | never_full
    describe: str = ""
    os: list[str] = field(default_factory=lambda: ["windows"])
    subpaths: list[str] = field(default_factory=list)  # only for clean_selected
    careful_subpaths: list[str] = field(default_factory=list)  # opt-out subset, unchecked by default
    category: str = "cache"
    group: str = ""
    program: str = ""
    tier: str = ""  # cache | old_versions | ai_models | messengers | media | games | other
    parent: str = ""  # only for old_versions: dir with versioned children
    match: str = "*"  # glob for children inside parent
    keep: list[str] = field(default_factory=list)  # child names = active version, never touch
    options: list[RuleOption] = field(default_factory=list)  # nested checkboxes
    discover: str = ""
    auto_keep: str = ""
    exe: str = ""  # auto_keep=exe: exe whose FileVersion marks the active dir
    search: str = ""  # curated web-search query for the context menu (else built from name/path)
    docs: str = ""
    user_made: bool = False
    pin: bool = False
    exec: bool = False
    processes: list[str] = field(default_factory=list)  # exe names to warn about if running


CATEGORY_ORDER = ("cache", "browsers", "old_versions", "ai_models", "messengers", "media",     "hypervisors", "devtools", "threed", "games", "antivirus", "system", "other")

CATEGORY_LABELS = {
    "cache": "Cache",
    "browsers": "Browsers",
    "old_versions": "Old versions",
    "ai_models": "AI models",
    "messengers": "Messengers",
    "media": "Media",
    "hypervisors": "Hypervisors",
    "devtools": "Development",
    "threed": "3D & CAD",
    "games": "Games",
    "antivirus": "Antivirus",
    "system": "System (read-only)",
    "other": "Other",
}
