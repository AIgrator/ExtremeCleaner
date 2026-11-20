"""Rule-set sanity gate. Plain script (no pytest dep): py -3 P tests/test_rules.py

Run locally or via CI (.github/workflows/ci.yml). Exit 0 = the rule set is valid.
"""

import compileall
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extreme_cleaner.loader import (  # noqa: E402
    check_rule_overlaps,
    load_all_rules,
    validate_rule_files,
)
from extreme_cleaner.models import CATEGORY_ORDER, Rule  # noqa: E402


def fail(msg: str, problems: list[str]) -> None:
    problems.append(msg)


def check_old_versions_guards(bad: list[str]) -> None:
    """The 1.3.x Opera regression: the newest version dir must never be offered.

    Scenario that broke the browser: launcher still reported 1.0.0.18 while the
    1.0.0.36 update had already landed; the rule deleted .36 as "old", then the
    launcher switched to it and stopped starting (SxS/parallel configuration).
    """
    import shutil
    import tempfile

    from extreme_cleaner import scanner as sc

    orig = sc._exe_file_version
    try:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "App"
            (parent / "1.0.0.18").mkdir(parents=True)
            (parent / "1.0.0.36").mkdir()
            (parent / "1.0.0.18" / "x.bin").write_bytes(b"x")
            (parent / "1.0.0.36" / "x.bin").write_bytes(b"x")
            (parent / "app.exe").write_bytes(b"")
            rule = Rule(
                id="test-old-versions",
                name="test",
                path="",
                kind="old_versions",
                parent=str(parent),
                match="[0-9]*",
                auto_keep="exe",
                exe="app.exe",
            )

            # 1. Staged update, launcher lags behind: newer dir must survive.
            sc._exe_file_version = lambda p: "1.0.0.18"
            names = [c.rule.name for c in sc._scan_old_versions(rule).children]
            if "1.0.0.36" in names:
                fail("old_versions: newest version offered for deletion (Opera regression)", bad)

            # 2. Normal case: active is the newest -> the old one is offered.
            sc._exe_file_version = lambda p: "1.0.0.36"
            names = [c.rule.name for c in sc._scan_old_versions(rule).children]
            if names != ["1.0.0.18"]:
                fail(f"old_versions: stale dir not detected: {names}", bad)

            # 3. Plan-time re-check: a scan snapshot may go stale before the
            #    click. With both dirs present the old one may be deleted...
            from extreme_cleaner import cleaner as cl

            old_dir = parent / "1.0.0.18"
            kid = Rule(
                id="test-old-versions:1.0.0.18",
                name="1.0.0.18",
                path=str(old_dir),
                kind="clean_selected",
                tier="safe",
                category="old_versions",
            )
            leaf = sc.ScanResult(kid, True, 1, 1, 0, str(old_dir))
            parent_res = sc.ScanResult(rule, True, 1, 1, 0, str(parent))
            parent_res.children = [leaf]
            actions, _ = cl.plan_deletion([parent_res])
            if not actions:
                fail("plan_deletion: refused a legitimately stale version dir", bad)

            # ...and after the update finished (newest .36 gone), the same
            # directory became the newest install: never delete it.
            shutil.rmtree(parent / "1.0.0.36")
            actions, _ = cl.plan_deletion([parent_res])
            if actions:
                fail("plan_deletion: offered a version dir that became newest after the scan", bad)

            # 4. Only the old dir survived, launcher points at a missing newer
            #    one: never delete the last installation.
            names = [c.rule.name for c in sc._scan_old_versions(rule).children]
            if names:
                fail(f"old_versions: last remaining install offered for deletion: {names}", bad)
    finally:
        sc._exe_file_version = orig


def main() -> int:
    bad: list[str] = []

    # 1. Every built-in YAML parses.
    parse_errors = validate_rule_files(ROOT)
    for err in parse_errors:
        fail(f"parse: {err}", bad)

    # 2. All rules load; ids unique; categories known.
    rules = load_all_rules(ROOT)
    if len(rules) < 250:
        fail(f"too few rules for the current set: {len(rules)}", bad)
    seen: set[str] = set()
    for r in rules:
        if r.id in seen:
            fail(f"duplicate id: {r.id}", bad)
        seen.add(r.id)
        if r.category not in CATEGORY_ORDER:
            fail(f"{r.id}: unknown category '{r.category}'", bad)
        if r.tier not in ("safe", "userdata", "system"):
            fail(f"{r.id}: unknown tier '{r.tier}'", bad)
        if r.safe not in ("safe", "careful", "never_full"):
            fail(f"{r.id}: unknown safe '{r.safe}'", bad)

    # 3. No overlaps outside declared exclude (the ~​/.cache class of bugs).
    for overlap in check_rule_overlaps(rules):
        fail(f"overlap: {overlap}", bad)

    # 4. Bytecode still compiles (imports in scanner/cleaner stay honest).
    if not compileall.compile_dir(str(ROOT / "src" / "extreme_cleaner"), quiet=2):
        fail("compileall failed under src/extreme_cleaner", bad)

    # 5. Old-version rules never propose the newest / updated version dir.
    check_old_versions_guards(bad)

    if bad:
        print(f"FAIL ({len(bad)}):")
        for m in bad:
            print(" -", m)
        return 1
    print(f"OK: {len(rules)} rules, no parse errors, no overlaps, compiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
