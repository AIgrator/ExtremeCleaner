"""CLI: list rules and scan real sizes (dry-run, no deletion in MVP)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extreme_cleaner.loader import load_all_rules, project_root_from_here
from extreme_cleaner.models import CATEGORY_LABELS
from extreme_cleaner.scanner import fmt_size, scan_all


def _print_table(rows: list[tuple], total: int) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="ExtremeCleaner — scan (dry-run, nothing deleted)")
        table.add_column("Category", style="magenta")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Size", justify="right", style="green")
        table.add_column("Files", justify="right")
        table.add_column("Status")
        for cat, rid, name, size, files, status in rows:
            table.add_row(cat, rid, name, size, files, status)
        table.add_row("", "", "[bold]TOTAL[/bold]", f"[bold]{fmt_size(total)}[/bold]", "", "")
        console.print(table)
        return
    except ImportError:
        pass
    print(f"{'CATEGORY':14} {'ID':24} {'SIZE':>10} {'FILES':>8}  NAME / STATUS")
    for cat, rid, name, size, files, status in rows:
        print(f"{cat:14} {rid:24} {size:>10} {files:>8}  {name} [{status}]")
    print(f"\nTOTAL: {fmt_size(total)}")


def cmd_audit(root: Path) -> int:
    """Show what WOULD be auto-selected: safe + found + non-empty. Histories never here."""
    from extreme_cleaner.scanner import fmt_size, scan_all

    total = 0
    print(f"{'SIZE':>10}  RULE")
    for r in sorted(scan_all(load_all_rules(root)), key=lambda x: x.size_bytes, reverse=True):
        if r.rule.tier != "safe":
            continue
        if r.children:
            kids = [s for s in r.children]  # parent size already equals children sum
        else:
            kids = []
        if not kids and r.rule.safe == "safe" and r.exists and (r.size_bytes > 0 or r.files > 0):
            print(f"{fmt_size(r.size_bytes):>10}  {r.rule.id} ({r.rule.name})")
            total += r.size_bytes
        for sub in kids:
            if sub.rule.safe == "safe" and sub.exists and (sub.size_bytes > 0 or sub.files > 0):
                print(f"{fmt_size(sub.size_bytes):>10}  + {sub.rule.id} ({sub.rule.name})")
                total += sub.size_bytes
    print(f"\nAUTO-SELECTED TOTAL: {fmt_size(total)} (careful/history items excluded by design)")
    return 0


def cmd_scan(root: Path, min_mb: float = 0, found_only: bool = False, tier: str | None = None) -> int:
    rules = load_all_rules(root)
    if not rules:
        print("No rules for this OS.")
        return 0
    results = scan_all(rules)
    rows, total = [], 0
    for r in sorted(results, key=lambda x: x.size_bytes, reverse=True):
        if tier and r.rule.tier != tier:
            continue
        if found_only and not (r.exists and (r.size_bytes > 0 or r.files > 0)):
            continue
        if not r.exists:
            status = "missing"
        elif r.size_bytes == 0 and r.files == 0:
            status = "empty"
        else:
            status = "found"
        if r.errors:
            status += f" ({r.errors} err)"
        cat = CATEGORY_LABELS.get(r.rule.category, r.rule.category)
        if r.rule.group:
            cat = f"{cat} / {r.rule.group}"
        rows.append((cat, r.rule.id, r.rule.name, fmt_size(r.size_bytes), str(r.files), status))
        for sub in r.children:
            if not sub.exists:
                sstatus = "missing"
            elif sub.size_bytes == 0 and sub.files == 0:
                sstatus = "empty"
            else:
                sstatus = "found"
            if sub.errors:
                sstatus += f" ({sub.errors} err)"
            rows.append((cat, f"  + {sub.rule.id}", f"[{sub.rule.safe}] {sub.rule.name}", fmt_size(sub.size_bytes), str(sub.files), sstatus))
        total += r.size_bytes
    _print_table(rows, total)
    print("\nMVP: scan only, deletion comes next.")
    return 0


def cmd_list(root: Path) -> int:
    for r in load_all_rules(root):
        print(f"- {r.id:28} kind={r.kind:15} safe={r.safe:11} path={r.path}")
    return 0


def _fix_frozen_streams() -> None:
    """A windowed exe has no console: sys.stdout/stderr are None and any print
    (or argparse usage text) crashes. Swallow prints, keep tracebacks in a log."""
    import sys as _sys
    import traceback

    if not bool(getattr(_sys, "frozen", False)):
        return
    if _sys.stdout is not None and _sys.stderr is not None:
        return
    try:
        devnull = open(os.devnull, "w")
    except OSError:
        import io

        devnull = io.StringIO()
    if _sys.stdout is None:
        _sys.stdout = devnull
    if _sys.stderr is None:
        _sys.stderr = devnull

    def _hook(exc_type, exc, tb) -> None:
        try:
            from extreme_cleaner.loader import data_dir

            with open(data_dir() / "extreme-cleaner-errors.log", "a", encoding="utf-8") as f:
                f.write("\n--- unhandled error ---\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except OSError:
            pass

    _sys.excepthook = _hook


def main(argv: list[str] | None = None) -> int:
    import sys as _sys

    _fix_frozen_streams()
    if argv is None:
        argv = _sys.argv[1:]
    if not argv:
        argv = ["gui"]  # double-clicked exe opens the window, never a usage error
    parser = argparse.ArgumentParser(prog="extreme-cleaner", description="Extreme cache cleaner (MVP: scan)")
    sub = parser.add_subparsers(dest="cmd")
    p_scan = sub.add_parser("scan", help="scan all rules and show sizes")
    p_scan.add_argument("--min-mb", type=float, default=0, help="hide entries smaller than N MB")
    p_scan.add_argument("--found-only", action="store_true", help="show only existing non-empty locations")
    p_scan.add_argument("--tier", choices=["safe", "userdata", "system"], default=None, help="show one tier only")
    sub.add_parser("list", help="list loaded rules")
    sub.add_parser("gui", help="open Qt GUI preview (no deletion yet)")
    sub.add_parser("audit", help="show what would be auto-selected (safe only, no histories)")
    args = parser.parse_args(argv)
    root = project_root_from_here()
    if args.cmd == "audit":
        return cmd_audit(root)
    if args.cmd == "scan":
        return cmd_scan(root, args.min_mb, args.found_only, args.tier)
    if args.cmd == "gui":
        from extreme_cleaner.gui import main as gui_main

        return gui_main()
    return cmd_list(root)


if __name__ == "__main__":
    raise SystemExit(main())
