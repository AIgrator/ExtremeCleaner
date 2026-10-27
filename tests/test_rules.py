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
from extreme_cleaner.models import CATEGORY_ORDER  # noqa: E402


def fail(msg: str, problems: list[str]) -> None:
    problems.append(msg)


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

    if bad:
        print(f"FAIL ({len(bad)}):")
        for m in bad:
            print(" -", m)
        return 1
    print(f"OK: {len(rules)} rules, no parse errors, no overlaps, compiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
