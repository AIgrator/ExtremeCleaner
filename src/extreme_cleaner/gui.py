"""GUI preview (read-only): single tree, categories collapsed, language groups. No deletion yet."""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt, QThread, QEvent, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from extreme_cleaner.loader import build_label, load_all_rules, project_root_from_here
from extreme_cleaner.models import CATEGORY_LABELS, CATEGORY_ORDER
from extreme_cleaner.scanner import ScanResult, fmt_size, scan_all


class DeleteWorker(QThread):
    progress = Signal(int, int, str)  # permille, 1000, "freed of ~total — label"
    done = Signal(float, list)  # freed_bytes as float: bytes exceed int32 above ~2 GB

    def __init__(self, actions, total_bytes: int):
        super().__init__()
        self._actions = actions
        self._total = max(1, int(total_bytes))

    def _permille(self, freed: int) -> int:
        return max(0, min(1000, int(1000 * freed / self._total)))

    def _note(self, freed: int, label: str) -> str:
        from extreme_cleaner.scanner import fmt_size

        return f"{fmt_size(freed)} of ~{fmt_size(self._total)} — {label[:90]}"

    def run(self) -> None:
        import subprocess

        from extreme_cleaner import cleaner as C

        freed, errors = 0, []
        dels = [a for a in self._actions if a.kind == "delete"]
        cmds = [a for a in self._actions if a.kind == "command"]
        bins = [a for a in self._actions if a.kind == "empty_bin"]
        for a in dels:
            f, e = C.execute_delete(a.paths, use_trash=True)
            freed += f
            errors += e
            self.progress.emit(self._permille(freed), 1000, self._note(freed, a.label))
        for a in bins:
            f, e = C.empty_recycle_bin()
            freed += f
            errors += e
            self.progress.emit(self._permille(freed), 1000, self._note(freed, a.label))
        for a in cmds:
            import shlex
            import shutil as _shutil

            try:
                prog_bin = shlex.split(a.command, posix=False)[0].strip('"') if a.command.strip() else ""
            except ValueError:
                prog_bin = ""
            if prog_bin and _shutil.which(prog_bin) is None and not Path(prog_bin).exists():
                errors.append(f"{a.label}: tool not found in PATH, skipping")
            else:
                try:
                    # NOTE: Russian Windows console speaks cp866, not the locale default.
                    r = subprocess.run(a.command, shell=True, capture_output=True, text=True,
                                       encoding="cp866", errors="replace", timeout=900, **C.no_console())
                    if r.returncode != 0:
                        errors.append(f"{a.label}: exit {r.returncode}: {(r.stderr or r.stdout or '')[:300]}")
                except Exception as e:  # noqa: BLE001 - report, keep going
                    errors.append(f"{a.label}: {C.english_error(e)}")
            self.progress.emit(self._permille(freed), 1000, self._note(freed, a.label))
        self.done.emit(float(freed), errors)


class ScanWorker(QThread):
    partial = Signal(list, int, int, str)  # chunk, done, total, chunk label
    finished = Signal()

    def __init__(self, root: Path, tier: str | None = None, ids: list[str] | None = None):
        super().__init__()
        self._root = root
        self._tier = tier        # scan only rules of this tier (per-tab refresh)
        self._ids = set(ids) if ids is not None else None  # scan only these rule ids

    def run(self) -> None:
        from itertools import groupby

        from extreme_cleaner.models import CATEGORY_ORDER, CATEGORY_LABELS

        rules = load_all_rules(self._root)
        if self._ids is not None:
            rules = [r for r in rules if r.id in self._ids]
        elif self._tier is not None:
            rules = [r for r in rules if (r.tier or "safe") == self._tier]
        if not rules:
            return
        order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
        sysrules = [r for r in rules if r.category == "system"]
        cleanup = [r for r in rules if r.category != "system"]
        cleanup.sort(key=lambda r: (order.get(r.category, 99), r.id))
        total = len(rules)
        done = 0
        for cat, grp in groupby(cleanup, key=lambda r: r.category):
            chunk = scan_all(list(grp))
            done += len(chunk)
            self.partial.emit(chunk, done, total, CATEGORY_LABELS.get(cat, cat))
        for r in sorted(sysrules, key=lambda r: r.id):  # slowest (WinSxS) goes last, one rule per chunk
            chunk = scan_all([r])
            done += 1
            self.partial.emit(chunk, done, total, "System")


class MainWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__()
        self._root = root
        self._results: list[ScanResult] = []
        self._updating = False
        self._user_sel: dict[str, bool] = {}  # per-rule-id user choices (survive every rescan)
        self._del_ids: list[str] = []
        self.setWindowTitle("ExtremeCleaner")
        self.resize(1060, 620)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(lambda _checked=False: self.start_scan())
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(lambda: self._set_all(True))
        self.clear_btn = QPushButton("Clear selection")
        self.clear_btn.clicked.connect(lambda: self._set_all(False))
        self.show_all_box = QCheckBox("Show all locations")
        self.show_all_box.setToolTip("Off (default): only found items. On: every place we scan, including missing ones.")
        self.show_all_box.checkStateChanged.connect(lambda _: self._fill_tree())
        self.add_btn = QPushButton("Add folder")
        self.add_btn.setToolTip("Add your own folder: Safe trash (checkbox tab) or User data (manual review tab).")
        self.add_btn.clicked.connect(self._on_add_folder)
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.setToolTip("Delete checked items in Safe cleanup (Recycle Bin, with confirm).")
        self.delete_btn.clicked.connect(self._on_delete)
        self.scan_btn.setIcon(MainWindow._glyph_icon("play"))
        self.select_all_btn.setIcon(MainWindow._glyph_icon("check"))
        self.clear_btn.setIcon(MainWindow._glyph_icon("remove"))
        self.add_btn.setIcon(MainWindow._glyph_icon("folder"))
        self.delete_btn.setIcon(MainWindow._glyph_icon("trash"))
        self.about_btn = QPushButton("About")
        self.about_btn.setIcon(MainWindow._glyph_icon("info"))
        self.about_btn.clicked.connect(self._on_about)
        top.addWidget(self.scan_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.clear_btn)
        top.addWidget(self.delete_btn)
        top.addWidget(self.show_all_box)
        top.addWidget(self.add_btn)
        top.addStretch(1)
        top.addWidget(self.about_btn)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Files", "Status", "Details"])
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setMouseTracking(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.viewport().installEventFilter(self)
        self._tip = None

        self.info_tree = QTreeWidget()
        self.info_tree.setHeaderLabels(["Name", "Size", "Files", "Status", "Details"])
        self.info_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_tree.setMouseTracking(True)
        self.info_tree.viewport().installEventFilter(self)
        self.info_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.info_tree.customContextMenuRequested.connect(self._on_context_menu)

        self.user_tree = QTreeWidget()
        self.user_tree.setHeaderLabels(["Name", "Size", "Files", "Status", "Details"])
        self.user_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.user_tree.setMouseTracking(True)
        self.user_tree.viewport().installEventFilter(self)
        self.user_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.user_tree.customContextMenuRequested.connect(self._on_context_menu)
        self.user_tree.itemClicked.connect(self._on_userdata_open)

        self.tabs = QTabWidget()
        cleanup_page = QWidget()
        cleanup_layout = QVBoxLayout(cleanup_page)
        cleanup_layout.setContentsMargins(0, 0, 0, 0)
        cleanup_layout.addWidget(self.tree)
        self.tabs.addTab(cleanup_page, "Safe cleanup")
        self.tabs.setTabToolTip(0, "Only safe trash: caches and leftovers that re-download from the internet. Checked items are selected for future cleanup.")
        user_page = QWidget()
        user_layout = QVBoxLayout(user_page)
        user_layout.setContentsMargins(0, 0, 0, 0)
        self.user_hint = QLabel("YOUR data: the program never deletes anything here. Single click opens the folder in Explorer — review and delete manually.")
        self.user_hint.setWordWrap(True)
        user_layout.addWidget(self.user_hint)
        user_layout.addWidget(self.user_tree)
        self.tabs.addTab(user_page, "User data")
        self.tabs.setTabToolTip(1, "YOUR files: chat histories, saves, downloads, messenger data. The program never deletes anything here — single click opens the folder, you decide yourself.")
        info_page = QWidget()
        info_page = QWidget()
        info_layout = QVBoxLayout(info_page)
        info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_hint = QLabel("System areas: shown for analysis only. Nothing here is ever deleted — use the official commands from the tooltips.")
        self.info_hint.setWordWrap(True)
        info_layout.addWidget(self.info_hint)
        info_layout.addWidget(self.info_tree)
        self.tabs.addTab(info_page, "System (info only)")
        self.tabs.setTabToolTip(2, "System areas, info only. Admin-level actions via official commands and linked instructions — nothing is ever deleted here.")
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(MainWindow._glyph_icon("reload"))
        self.refresh_btn.setToolTip("Rescan only this tab")
        self.refresh_btn.clicked.connect(self._on_refresh_tab)
        self.tabs.setCornerWidget(self.refresh_btn, Qt.Corner.TopLeftCorner)
        # System is info-only: nothing can be added there, hide the button.
        self.tabs.currentChanged.connect(lambda i: self.add_btn.setVisible(i != 2))
        layout.addWidget(self.tabs)

        bottom = QHBoxLayout()
        self.total_label = QLabel("Total: -")
        self.selected_label = QLabel("Selected for future cleanup: -")
        self.build_label = QLabel(build_label())
        self.build_label.setToolTip("Build stamp, baked in at compile time. Screenshot it when reporting a bug.")
        bottom.addWidget(self.total_label)
        bottom.addWidget(self.selected_label)
        bottom.addStretch(1)
        bottom.addWidget(self.build_label)
        layout.addLayout(bottom)

        self._worker: ScanWorker | None = None
        self.start_scan()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(800, self._check_rule_files)

    def _check_rule_files(self) -> None:
        from extreme_cleaner.loader import validate_rule_files

        bad = validate_rule_files(self._root)
        if bad:
            QMessageBox.warning(
                self, "Broken rules",
                "These rule files failed to load and are SKIPPED:\n\n" + "\n".join(bad) +
                "\n\nFix the YAML to bring those locations back.")

    # --- scan ---

    def start_scan(self, tier: str | None = None, ids: list[str] | None = None) -> None:
        """Full scan (tier=None, ids=None), one tab only (tier=...), or just these rules (ids=...)."""
        if self._worker is not None and self._worker.isRunning():
            return  # one scan at a time; buttons are disabled while busy
        if tier is None and ids is None:
            self._results = []  # full rescan replaces everything
        self.scan_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.total_label.setText("Scanning…")
        self._worker = ScanWorker(self._root, tier=tier, ids=ids)
        self._worker.partial.connect(self._on_partial)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_refresh_tab(self) -> None:
        tier = ("safe", "userdata", "system")[self.tabs.currentIndex()]
        self.start_scan(tier=tier)

    def _on_partial(self, chunk: list, done: int, total: int, label: str) -> None:
        if self._worker is None or self.sender() is not self._worker:
            return  # stale worker (user rescanned) — ignore to avoid duplicates
        new_ids = {r.rule.id for r in chunk}
        self._results = [r for r in self._results if r.rule.id not in new_ids]  # partial rescans replace old rows
        self._results.extend(chunk)
        self._results.sort(key=lambda r: r.size_bytes, reverse=True)
        self._fill_tree()
        self.total_label.setText(f"Scanning… {label} ({done}/{total})")

    def _on_scan_done(self) -> None:
        if self._worker is not None and self.sender() is not self._worker:
            return
        self._fill_tree()  # final totals
        self.scan_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

    def rescan_blocking(self) -> None:
        """For smoke tests: scan synchronously without threads."""
        self._worker = None  # invalidate pending threaded chunks (no duplicates)
        self._results = sorted(scan_all(load_all_rules(self._root)), key=lambda r: r.size_bytes, reverse=True)
        self._fill_tree()

    # --- tree: category -> group -> rule -> options, all collapsed ---

    @staticmethod
    def _mid_node(label: str, checkable: bool = True) -> QTreeWidgetItem:
        node = QTreeWidgetItem([label, "", "", "", ""])
        if checkable:
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            node.setCheckState(0, Qt.Checked)
        else:
            node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
        node.setData(0, Qt.UserRole, label)  # base label without selection suffix
        return node

    def _is_visible(self, res: ScanResult) -> bool:
        if res.rule.pin:
            return True  # pinned rows (Recycle Bin) are always shown
        if self.show_all_box.isChecked():
            return True
        if res.rule.tier == "system":
            # info tab: command-only rows (no folder) always listed; absent folders are not
            return not (res.rule.path and not res.exists)
        if res.errors:
            return True  # denied/locked places stay visible (status explains why)
        if res.children:
            return any(c.exists and (c.size_bytes > 0 or c.files > 0) for c in res.children)
        return res.exists and (res.size_bytes > 0 or res.files > 0)

    def _fill_tree(self) -> None:
        self._updating = True
        try:
            tiers: dict[str, list[ScanResult]] = {"safe": [], "userdata": [], "system": []}
            for res in self._results:
                tiers.setdefault(res.rule.tier or "safe", tiers["safe"]).append(res)
            safe_total = self._build_tree(self.tree, tiers["safe"], checkable=True)
            user_total = self._build_tree(self.user_tree, tiers["userdata"], checkable=False,
                                          cat_rename={"media": "Files", "other": "Files"})
            sys_total = self._build_tree(self.info_tree, tiers["system"], checkable=False)
            self.tabs.setTabText(0, f"Safe cleanup — {fmt_size(safe_total)}")
            self.tabs.setTabText(1, f"User data — {fmt_size(user_total)}")
            self.tabs.setTabText(2, f"System (info only) — {fmt_size(sys_total)}")
            grand = safe_total + user_total + sys_total
            self.total_label.setText(
                f"Theoretical total: {fmt_size(grand)}"
                f" (Safe: {fmt_size(safe_total)} · User data: {fmt_size(user_total)} · System: {fmt_size(sys_total)})"
            )
        finally:
            self._updating = False

    @staticmethod
    def _exp_key(item) -> str:
        """Expansion key without the trailing ' — 6.7 GB' part: sizes change after
        every rescan, name-based keys keep nodes expanded across cleanups."""
        base = item.data(0, Qt.UserRole) or item.text(0)
        name, sep, _tail = base.rpartition(" — ")
        return name if sep else base

    def _build_tree(self, tree: QTreeWidget, results: list[ScanResult], checkable: bool,
                    cat_rename: dict | None = None) -> int:
        # Remember expanded nodes by name (size-independent); totals always come
        # from the full scan so labels stay stable across filter toggles and chunks.
        expanded: set = set()
        stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.isExpanded():
                expanded.add(self._exp_key(it))
            stack.extend(it.child(i) for i in range(it.childCount()))
        # Detach item widgets explicitly: tree.clear() may orphan them, leaving
        # ghost checkboxes painted over the rebuilt rows on rapid rescans.
        orphan_stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while orphan_stack:
            dead = orphan_stack.pop()
            widget = tree.itemWidget(dead, 0)
            if widget is not None:
                tree.removeItemWidget(dead, 0)
                widget.deleteLater()
            orphan_stack.extend(dead.child(i) for i in range(dead.childCount()))
        tree.clear()
        rename = cat_rename or {}

        def key_of(c):
            return rename.get(c, c)

        all_groups: dict = {}
        for res in results:
            if not res.rule.user_made and not res.rule.pin:
                all_groups.setdefault(key_of(res.rule.category), []).append(res)
        groups: dict = {}
        for res in results:
            if not res.rule.user_made and not res.rule.pin and self._is_visible(res):
                groups.setdefault(key_of(res.rule.category), []).append(res)
        ordered = [c for c in CATEGORY_ORDER if c in groups] + [c for c in groups if c not in CATEGORY_ORDER]
        mine = [r for r in results if r.rule.user_made]
        visible_mine = [r for r in mine if self._is_visible(r)]
        if visible_mine:
            mine_total = sum(r.size_bytes for r in mine)
            user_node = self._mid_node(f"User \u2014 {fmt_size(mine_total)}", checkable)
            tree.addTopLevelItem(user_node)
            for res in sorted(visible_mine, key=lambda r: r.size_bytes, reverse=True):
                self._add_rule(user_node, res, checkable)
            user_node.setToolTip(0, "<b>User</b><br>Folders you added yourself (Add folder button)")
            if "User" in expanded:
                user_node.setExpanded(True)
        total = sum(r.size_bytes for r in mine)
        pinned = sorted(
            [r for r in results if r.rule.pin and self._is_visible(r)],
            key=lambda r: r.size_bytes, reverse=True,
        )
        for res in pinned:
            self._add_rule(tree, res, checkable)
            total += res.size_bytes
        single_cat = len(ordered) == 1

        def attach(parent, node):
            if isinstance(parent, QTreeWidget):
                parent.addTopLevelItem(node)
            else:
                parent.addChild(node)

        for cat in ordered:
            items = groups[cat]
            cat_total = sum(r.size_bytes for r in all_groups.get(cat, []))
            total += cat_total
            if single_cat:
                cat_node = None
            else:
                cat_node = self._mid_node(f"{CATEGORY_LABELS.get(cat, cat)} \u2014 {fmt_size(cat_total)}", checkable)
                tree.addTopLevelItem(cat_node)
            buckets: dict = {}
            for res in items:
                buckets.setdefault((res.rule.group, res.rule.program), []).append(res)
            all_buckets: dict = {}
            for res in all_groups.get(cat, []):
                all_buckets.setdefault((res.rule.group, res.rule.program), []).append(res)
            order = sorted(buckets, key=lambda k: (k[0] == "" and k[1] == "", k[0].lower(), k[1].lower()))
            for (gname, pname) in order:
                sub = buckets[(gname, pname)]
                full = all_buckets.get((gname, pname), sub)
                parent = cat_node if cat_node is not None else tree
                if gname:
                    g_total = sum(r.size_bytes for r in full)
                    g_node = self._mid_node(f"{gname} \u2014 {fmt_size(g_total)}", checkable)
                    g_node.setData(0, Qt.UserRole + 9, "folder")  # never flattened by _collapse_singles
                    attach(parent, g_node)
                    parent = g_node
                if pname:
                    p_total = sum(r.size_bytes for r in full)
                    p_node = self._mid_node(f"{pname} \u2014 {fmt_size(p_total)}", checkable)
                    p_node.setData(0, Qt.UserRole + 9, "folder")  # keep the browser/program name visible
                    attach(parent, p_node)
                    parent = p_node
                if cat_node is None and parent is tree:
                    for res in sub:
                        self._add_rule(tree, res, checkable)
                else:
                    for res in sub:
                        self._add_rule(parent, res, checkable)
                if gname:
                    g_node.setToolTip(0, f"<b>{gname}</b><br>Total: {fmt_size(g_total)} in {len(sub)} locations<br>Expand to choose")
                if pname:
                    p_node.setToolTip(0, f"<b>{pname}</b><br>Total: {fmt_size(p_total)} in {len(sub)} locations<br>Expand to choose")
            if cat_node is not None:
                cat_node.setToolTip(0, f"<b>{CATEGORY_LABELS.get(cat, cat)}</b><br>Total: {fmt_size(cat_total)} in {len(items)} locations<br>Expand to choose")
        self._collapse_singles(tree)
        restore = []
        stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if self._exp_key(it) in expanded:
                restore.append(it)
            stack.extend(it.child(i) for i in range(it.childCount()))
        for it in restore:
            it.setExpanded(True)
        if checkable:
            self._refresh_parents()
            self._update_labels()
        tree.resizeColumnToContents(0)
        return total

    def _on_userdata_open(self, item: QTreeWidgetItem) -> None:
        # User data tab: program never deletes — single click opens the folder for manual review.
        path = item.data(0, Qt.UserRole + 1) or ""
        if path:
            self._open_path(path)

    @staticmethod
    def _default_checked(safe: str, exists: bool, size: int) -> bool:
        # Value (history, sessions) is never pre-selected: safe junk is checked, careful is opt-in.
        return safe == "safe" and exists and size > 0

    KIND_ACTION = {
        "clean_contents": "Delete everything inside the folder (folder itself stays)",
        "empty_bin": "EMPTY the Recycle Bin permanently (no undo!)",
        "run_command": "Official cleanup / instructions",
        "clean_selected": "Delete selected subfolders",
        "old_versions": "Delete only inactive versions (active one excluded)",
        "manual": "Manual review in Explorer (program never deletes)",
    }
    SAFE_LABEL = {
        "safe": "Safe - restores itself",
        "careful": "Caution - read the note",
        "never_full": "Never wipe entirely!",
    }

    @staticmethod
    def _short_list(parts: list[str], limit: int) -> str:
        if len(parts) <= limit:
            return "; ".join(parts)
        return "; ".join(parts[:limit]) + f"; … top {limit} largest, {len(parts) - limit} more"

    @classmethod
    def _tooltip(cls, name: str, path: str, kind: str, command: str, safe: str, describe: str, parts: list[str] | None = None, docs: str = "") -> str:
        action = cls.KIND_ACTION.get(kind, kind)
        if kind == "run_command" and command:
            action = f"{action}: {command}"
        note = (describe or "").split(" | ")[0]
        if len(note) > 220:
            note = note[:217] + "…"
        lines = [
            f"<b>{name}</b>",
            f"<nobr>Path: {path or '—'}</nobr>",
            f"Action: {action}",
            f"Safety: {cls.SAFE_LABEL.get(safe, safe)}",
        ]
        if parts:
            lines.append(f"Includes: {cls._short_list(parts, 5)}")
        if note:
            lines.append(f"Note: {note}")
        if docs:
            lines.append(f"Docs: {docs}")
        return "<br>".join(lines)

    def _make_leaf(self, name: str, size: int, files: int, status: str, details: str, safe: str, exists: bool,
                   path: str = "", kind: str = "", command: str = "", parts: list[str] | None = None,
                   checkable: bool = True, docs: str = "", rid: str = "", search: str = "") -> QTreeWidgetItem:
        label = f"[{safe}] " if (checkable and safe != "safe") else ""
        item = QTreeWidgetItem([label + name, fmt_size(size), str(files), status, details])
        if checkable:
            # user's explicit choice (remembered per rule id) always beats the default
            checked = self._user_sel[rid] if (rid and rid in self._user_sel) else MainWindow._default_checked(safe, exists, size)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        item.setData(1, Qt.UserRole, size)
        item.setData(0, Qt.UserRole + 1, path)
        item.setData(0, Qt.UserRole + 2, docs)
        item.setData(0, Qt.UserRole + 4, rid)
        item.setData(0, Qt.UserRole + 6, search)
        item.setToolTip(0, MainWindow._tooltip(label + name, path, kind, command, safe, details, parts, docs))
        return item

    @staticmethod
    def _details(res: ScanResult) -> str:
        details = res.rule.describe or res.resolved
        if res.parts:
            extra = MainWindow._short_list(res.parts, 3)
            details = f"{details} | {extra}" if details else extra
        if len(details) > 160:
            details = details[:157] + "…"
        return details

    @staticmethod
    def _status(res: ScanResult) -> str:
        if not res.exists:
            status = "missing"
        elif res.rule.kind in ("run_command", "manual") and not res.rule.path:
            status = "via command"  # no folder of its own; size comes from the command
        elif res.errors and res.size_bytes == 0 and res.files == 0:
            status = "denied"
        elif res.size_bytes == 0 and res.files == 0:
            status = "empty"
        else:
            status = "found"
        if res.errors:
            status += f" ({res.errors} err)"
        return status

    @staticmethod
    def _glyph_icon(kind: str):
        # Drawn icons: font glyphs like U+270E do not render in every font.
        # Stroke color comes from the app palette, so icons follow the theme
        # (light on dark, dark on light) automatically.
        from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygon

        app = QApplication.instance()
        color = app.palette().color(QPalette.ColorRole.ButtonText) if app is not None else QColor("#cccccc")
        pm = QPixmap(16, 16)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        if kind == "edit":
            p.drawLine(4, 12, 11, 5)  # pencil body
            p.drawLine(11, 5, 13, 3)  # tip
            p.drawLine(4, 12, 6, 12)  # back end
        elif kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygon([QPoint(5, 3), QPoint(5, 13), QPoint(12, 8)]))
        elif kind == "check":
            p.drawPolyline(QPolygon([QPoint(3, 8), QPoint(7, 12), QPoint(13, 4)]))
        elif kind == "folder":
            p.drawLine(3, 6, 3, 4)  # tab
            p.drawLine(3, 4, 6, 4)
            p.drawLine(6, 4, 6, 6)
            p.drawRect(3, 6, 10, 6)  # body
            p.drawLine(8, 8, 8, 10)  # plus
            p.drawLine(7, 9, 9, 9)
        elif kind == "trash":
            p.drawLine(4, 4, 12, 4)  # lid
            p.drawLine(7, 4, 7, 2)  # handle
            p.drawLine(7, 2, 9, 2)
            p.drawLine(9, 2, 9, 4)
            p.drawLine(5, 4, 6, 13)  # body
            p.drawLine(11, 4, 10, 13)
            p.drawLine(6, 13, 10, 13)
            p.drawLine(8, 6, 8, 11)  # ribs
        elif kind == "reload":
            p.drawArc(3, 3, 10, 10, 45 * 16, 270 * 16)
            p.drawLine(11, 11, 11, 8)  # arrowhead
            p.drawLine(11, 11, 8, 11)
        elif kind == "info":
            p.drawEllipse(3, 3, 10, 10)
            p.drawPoint(8, 5)  # dot
            p.drawLine(8, 8, 8, 12)  # stem
        else:  # remove
            p.drawLine(4, 4, 12, 12)
            p.drawLine(12, 4, 4, 12)
        p.end()
        return QIcon(pm)

    def _attach_user_actions(self, parent, item, rid: str, checkable: bool) -> None:
        from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QToolButton, QWidget

        tree = parent if isinstance(parent, QTreeWidget) else parent.treeWidget()
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        if checkable:
            cb = QCheckBox()
            cb.setTristate(True)
            cb.setCheckState(item.checkState(0))
            cb.stateChanged.connect(lambda _s, it=item: self._on_custom_check(it))
            lay.addWidget(cb)
            # The widget checkbox is the control — drop the native one, no doubles.
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            # Win11 paints a phantom box for any check-state data: move the state
            # into the widget checkbox and keep the item data-free.
            item.setData(0, Qt.CheckStateRole, None)
        edit_b = QToolButton()
        edit_b.setIcon(self._glyph_icon("edit"))
        edit_b.setToolTip("edit")
        edit_b.clicked.connect(lambda: self._on_edit_user(rid))
        del_b = QToolButton()
        del_b.setIcon(self._glyph_icon("remove"))
        del_b.setToolTip("remove")
        del_b.clicked.connect(lambda: self._on_delete_user(rid))
        lay.addWidget(edit_b)
        lay.addWidget(del_b)
        name = QLabel(item.text(0))
        lay.addWidget(name, 1)
        # No box.setToolTip: the hover bubbles to the viewport where the single
        # wide tip is shown — otherwise the small native bubble doubles it.
        tree.setItemWidget(item, 0, box)
        # Hide the native text (it would shine through the transparent widget),
        # keep the name for search actions.
        item.setData(0, Qt.UserRole + 3, item.text(0))
        item.setText(0, "")

    def _on_custom_check(self, item) -> None:
        from PySide6.QtWidgets import QCheckBox

        if self._updating:
            return
        box = self.tree.itemWidget(item, 0)
        cb = box.findChild(QCheckBox) if box is not None else None
        if cb is None:
            return
        self._updating = True
        try:
            # The widget checkbox IS the state — the item stays data-free (no phantom).
            rid = item.data(0, Qt.UserRole + 4)
            if rid and cb.checkState() != Qt.PartiallyChecked:
                self._user_sel[rid] = cb.checkState() == Qt.Checked
            self._refresh_parents()
            self._sync_row_widgets()
            self._update_labels()
        finally:
            self._updating = False

    def _sync_row_widgets(self) -> None:
        from PySide6.QtWidgets import QCheckBox

        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            box = self.tree.itemWidget(it, 0)
            if box is not None:
                cb = box.findChild(QCheckBox)
                if cb is not None:
                    cb.blockSignals(True)
                    cb.setCheckState(MainWindow._row_state(it))
                    cb.blockSignals(False)
            stack.extend(it.child(i) for i in range(it.childCount()))

    def _add_rule(self, parent, res: ScanResult, checkable: bool = True) -> None:
        add = parent.addTopLevelItem if isinstance(parent, QTreeWidget) else parent.addChild
        if res.children:
            mid = self._mid_node(res.rule.name, checkable)
            mid.setText(1, fmt_size(res.size_bytes))
            mid.setText(2, str(res.files))
            mid.setText(4, res.rule.describe or "")
            mid.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            first_path = next((c.resolved for c in res.children if c.exists and c.resolved), res.resolved)
            mid.setData(0, Qt.UserRole + 1, first_path)
            mid.setData(0, Qt.UserRole + 2, res.rule.docs)
            mid.setData(0, Qt.UserRole + 6, res.rule.search)
            mid.setToolTip(0, self._tooltip(res.rule.name, first_path, res.rule.kind, res.rule.command, res.rule.safe, self._details(res), res.parts, res.rule.docs))
            add(mid)
            if res.rule.user_made:
                self._attach_user_actions(parent, mid, res.rule.id, checkable)
            for sub in [c for c in res.children if self._is_visible(c)]:
                mid.addChild(self._make_leaf(sub.rule.name, sub.size_bytes, sub.files, self._status(sub), self._details(sub), sub.rule.safe, sub.exists, sub.resolved, sub.rule.kind, sub.rule.command, sub.parts, checkable, sub.rule.docs, sub.rule.id, search=sub.rule.search))
        else:
            leaf = self._make_leaf(res.rule.name, res.size_bytes, res.files, self._status(res), self._details(res), res.rule.safe, res.exists, res.resolved, res.rule.kind, res.rule.command, res.parts, checkable, res.rule.docs, res.rule.id, search=res.rule.search)
            add(leaf)
            if res.rule.user_made:
                self._attach_user_actions(parent, leaf, res.rule.id, checkable)

    @staticmethod
    def _collapse_singles(tree) -> None:
        """Flatten mid nodes with exactly one child (except top categories and User).

        One folder per program => no point expanding twice. Base labels and
        checkboxes of the surviving child stay intact.
        """
        def is_top(item) -> bool:
            for i in range(tree.topLevelItemCount()):
                if tree.topLevelItem(i) is item:
                    return True
            return False

        def base_of(item) -> str:
            return item.data(0, Qt.UserRole) or item.text(0)

        changed = True
        while changed:
            changed = False
            stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
            while stack:
                it = stack.pop()
                if (not is_top(it) and base_of(it) != "User"
                        and it.data(0, Qt.UserRole + 9) != "folder" and it.childCount() == 1):
                    kid = it.child(0)
                    it.removeChild(kid)
                    parent = it.parent()
                    if parent is None:
                        idx = tree.indexOfTopLevelItem(it)
                        tree.takeTopLevelItem(idx)
                        tree.insertTopLevelItem(idx, kid)
                    else:
                        idx = parent.indexOfChild(it)
                        parent.takeChild(idx)
                        parent.insertChild(idx, kid)
                    changed = True
                    break
                stack.extend(it.child(i) for i in range(it.childCount()))
        return

    def _refresh_parents(self) -> None:
        """Bottom-up tristate recalc: parent is checked only if ALL children are.

        Needed because children added after the parent's state was set do not
        trigger Qt's automatic tristate update — without this a parent with one
        checked child wrongly shows as fully checked.
        """
        def recalc(item) -> int:
            if item.childCount() == 0:
                return MainWindow._row_state(item)
            states = {recalc(item.child(i)) for i in range(item.childCount())}
            if len(states) == 1:
                state = states.pop()
            else:
                state = Qt.PartiallyChecked
            if state != MainWindow._row_state(item):
                self._set_row_state(item, state)
            return state

        for i in range(self.tree.topLevelItemCount()):
            recalc(self.tree.topLevelItem(i))
        self._sync_row_widgets()

    def _set_all(self, checked: bool) -> None:
        self._updating = True
        try:
            state = Qt.Checked if checked else Qt.Unchecked
            for leaf in self._iter_leaves():
                self._set_row_state(leaf, state)
                rid = leaf.data(0, Qt.UserRole + 4)
                if rid:
                    self._user_sel[rid] = checked  # bulk choice = user intent, survives rescans
            self._refresh_parents()
        finally:
            self._updating = False
        self._update_labels()

    @staticmethod
    def _row_state(item):
        """Effective check state of a row: the widget checkbox wins on attached
        rows (their item must stay data-free, or Win11 paints a phantom twin)."""
        from PySide6.QtWidgets import QCheckBox

        tree = item.treeWidget()
        box = tree.itemWidget(item, 0) if tree is not None else None
        if box is not None:
            cb = box.findChild(QCheckBox)
            if cb is not None:
                return cb.checkState()
        return item.checkState(0)

    def _set_row_state(self, item, state) -> None:
        """Write state to the widget checkbox when attached, else to the item."""
        from PySide6.QtWidgets import QCheckBox

        tree = item.treeWidget()
        box = tree.itemWidget(item, 0) if tree is not None else None
        cb = box.findChild(QCheckBox) if box is not None else None
        if cb is not None:
            cb.blockSignals(True)
            try:
                cb.setCheckState(state)
            finally:
                cb.blockSignals(False)
        else:
            item.setCheckState(0, state)

    def _record_choice(self, item) -> None:
        """Remember the user's explicit check choice for this row (and its leaves)."""
        stack = [item]
        while stack:
            it = stack.pop()
            if it.childCount():
                stack.extend(it.child(i) for i in range(it.childCount()))
                continue
            rid = it.data(0, Qt.UserRole + 4)
            if rid:
                self._user_sel[rid] = MainWindow._row_state(it) == Qt.Checked

    def _on_item_changed(self, item=None) -> None:
        if self._updating:
            return
        if item is not None:
            self._record_choice(item)  # user click (or parent->children propagation)
        # User click: Qt propagates parent->children itself, but children->parent
        # is unreliable (stale fully-checked parent) — recalc bottom-up explicitly.
        self._updating = True
        try:
            self._refresh_parents()
            self._update_labels()
        finally:
            self._updating = False

    def _iter_leaves(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.childCount():
                stack.extend(item.child(i) for i in range(item.childCount()))
            else:
                yield item

    def _selected_bytes(self) -> int:
        total = 0
        for leaf in self._iter_leaves():
            if MainWindow._row_state(leaf) == Qt.Checked:
                total += int(leaf.data(1, Qt.UserRole) or 0)
        return total

    def child_row_count(self) -> int:
        """For smoke tests."""
        return sum(1 for _ in self._iter_leaves())

    def _subtree_sum(self, node) -> tuple[int, int]:
        sel = tot = 0
        stack = [node]
        while stack:
            it = stack.pop()
            if it.childCount():
                stack.extend(it.child(i) for i in range(it.childCount()))
            else:
                s = int(it.data(1, Qt.UserRole) or 0)
                tot += s
                if MainWindow._row_state(it) == Qt.Checked:
                    sel += s
        return sel, tot

    def _update_labels(self) -> None:
        """Bottom totals + 'selected X' suffix on every parent node. Self-guarded."""
        self._updating = True
        try:
            self.selected_label.setText(f"Selected for future cleanup: {fmt_size(self._selected_bytes())}")
            stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
            while stack:
                node = stack.pop()
                if node.childCount() == 0:
                    continue
                stack.extend(node.child(i) for i in range(node.childCount()))
                sel, tot = self._subtree_sum(node)
                base = node.data(0, Qt.UserRole) or node.text(0)
                if sel == tot:
                    node.setText(0, base)
                elif sel == 0:
                    node.setText(0, f"{base} (not selected)")
                else:
                    node.setText(0, f"{base} (selected {fmt_size(sel)})")
        finally:
            self._updating = False

    def eventFilter(self, obj, ev) -> bool:
        tree = {self.tree.viewport(): self.tree, self.info_tree.viewport(): self.info_tree,
                self.user_tree.viewport(): self.user_tree}.get(obj)
        if tree is not None:
            if ev.type() == QEvent.Type.ToolTip:
                item = tree.itemAt(ev.pos())
                html = item.toolTip(0) if item is not None else ""
                if html:
                    self._show_wide_tip(tree, html, ev.pos())
                else:
                    self._hide_tip()
                return True  # suppress the narrow native bubble
            if ev.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
                self._hide_tip()
        return super().eventFilter(obj, ev)

    def _show_wide_tip(self, tree, html: str, pos) -> None:
        from PySide6.QtWidgets import QLabel

        if self._tip is None:
            tip = QLabel(None, Qt.ToolTip)
            tip.setWordWrap(True)
            tip.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            tip.setMargin(8)
            self._tip = tip
        width = max(400, tree.viewport().width() - 16)
        self._tip.setFixedWidth(width)
        self._tip.setText(html)
        self._tip.adjustSize()  # shrink height to content (heightForWidth lies)
        if self._tip.height() > 400:
            self._tip.setFixedHeight(400)
        height = self._tip.height()
        cursor = tree.viewport().mapToGlobal(pos)
        left = tree.viewport().mapToGlobal(QPoint(0, 0)).x() + 8
        top = cursor.y() + 18
        screen = QApplication.primaryScreen().availableGeometry()
        if top + height > screen.bottom():
            top = cursor.y() - height - 8
        if left + width > screen.right():
            left = screen.right() - width - 8
        self._tip.move(left, top)
        self._tip.show()

    def _hide_tip(self) -> None:
        if self._tip is not None:
            self._tip.hide()

    def _on_context_menu(self, pos) -> None:
        tree = self.sender() or self.tree
        item = tree.itemAt(pos)
        if item is None:
            return
        path = item.data(0, Qt.UserRole + 1) or ""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(tree)
        has_concrete = bool(path) and Path(path).is_absolute() and Path(path).exists()
        if has_concrete:
            open_act = QAction("Open folder", menu)
            open_act.triggered.connect(lambda: self._open_path(path))
            menu.addAction(open_act)
        if path:  # no folder of its own -> no path actions at all, links only
            copy_act = QAction("Copy path", menu)
            copy_act.triggered.connect(lambda: QApplication.clipboard().setText(path))
            menu.addAction(copy_act)
        shown_name = item.data(0, Qt.UserRole + 3) or item.text(0)
        query = item.data(0, Qt.UserRole + 6) or self._web_query(shown_name, path)
        web_act = QAction(f"Search the web: {query[:60]}", menu)
        web_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query))))
        menu.addAction(web_act)
        docs = item.data(0, Qt.UserRole + 2) or ""
        if docs:
            is_video = "youtube.com" in docs or "youtu.be" in docs
            doc_act = QAction("Watch video guide" if is_video else "Read guide with pictures", menu)
            doc_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(docs)))
            menu.addAction(doc_act)
        menu.exec(tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _web_query(name: str, path: str) -> str:
        """English query from generic folder names only — username never leaves the PC."""
        import re

        parts = [p for p in Path(path).parts if p not in ("\\", "/", "")] if path and Path(path).is_absolute() else []
        if parts:
            tail = " ".join(parts[-2:])
            return f"{tail} folder safe to delete Windows"
        clean = name.split("]", 1)[-1]
        clean = re.sub(r"[\[(][^\])]*[\])]", " ", clean)  # drop (VSS), [careful] noise
        clean = re.sub(r"~?\d+(?:\.\d+)?\s*(?:GB|MB|TB)", " ", clean, flags=re.I)
        clean = clean.replace("+", " ").replace("&", " and ")
        clean = re.sub(r"\s+", " ", clean).strip(" —-")
        return f"{clean} safe to delete"

    @staticmethod
    def _open_path(path: str) -> None:
        if not path:
            return
        norm = str(path).replace("/", "\\").lower()
        if "$recycle.bin" in norm:
            import subprocess
            subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
            return
        p = Path(path)
        if not p.is_absolute() or not p.exists():
            return  # relative/empty paths would open the program's own folder
        if p.is_file():
            p = p.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _folder_dialog(self, title: str, preset: dict | None = None) -> dict | None:
        from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLineEdit, QTextEdit

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(480, 260)
        form = QFormLayout(dlg)
        name_edit = QLineEdit(preset.get("name", "") if preset else "")
        path_edit = QLineEdit(preset.get("path", "") if preset else "")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(lambda: path_edit.setText(QFileDialog.getExistingDirectory(dlg, "Choose folder") or path_edit.text()))
        tier_combo = QComboBox()
        tier_combo.addItem("Safe trash (checkbox, future deletion)", "safe")
        tier_combo.addItem("User data (manual review, never deleted)", "userdata")
        if preset:
            tier_combo.setCurrentIndex(0 if preset.get("tier") == "safe" else 1)
        note_edit = QTextEdit(preset.get("describe", "") if preset else "")
        note_edit.setPlaceholderText("Optional note")
        note_edit.setFixedHeight(66)  # ~3 rows
        form.addRow("Name:", name_edit)
        form.addRow("Folder:", path_edit)
        form.addRow("", browse_btn)
        form.addRow("Tab:", tier_combo)
        form.addRow("Note:", note_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.Accepted:
            return None
        return {"name": name_edit.text().strip(), "path": path_edit.text().strip(),
                "tier": tier_combo.currentData(), "describe": note_edit.toPlainText().strip()}

    def _on_about(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle("About ExtremeCleaner")
        dlg.resize(460, 380)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        top.setSpacing(24)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(self.windowIcon().pixmap(48, 48))
        top.addWidget(icon_lbl)
        info = QLabel(
            "<b>ExtremeCleaner</b><br>"
            "Version: 1.0.0<br>"
            "Author: Yaroslav Litovchenko<br>"
            'Email: <a href="mailto:aigrator@gmail.com">aigrator@gmail.com</a><br>'
            'GitHub page: <a href="https://github.com/AIgrator/ExtremeCleaner">github.com/AIgrator/ExtremeCleaner</a><br>'
            'Home page: <a href="https://ExtremeCleaner.sourceforge.net">ExtremeCleaner.sourceforge.net</a><br>'
            'Bugs/Suggestions: <a href="https://github.com/AIgrator/ExtremeCleaner/issues">github.com/AIgrator/ExtremeCleaner/issues</a>'
        )
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        info.setOpenExternalLinks(True)
        top.addWidget(info, 1)
        lay.addLayout(top)
        lic_title = QLabel("License: MIT")
        lic_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lic_title)
        lic = QTextEdit()
        lic.setReadOnly(True)
        lic.setPlainText(
            "Copyright (c) 2026 Yaroslav Litovchenko\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy "
            "of this software and associated documentation files (the \"Software\"), to deal "
            "in the Software without restriction, including without limitation the rights "
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
            "copies of the Software, and to permit persons to whom the Software is "
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included in all "
            "copies or substantial portions of the Software.\n\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR "
            "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE "
            "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER "
            "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, "
            "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE "
            "SOFTWARE."
        )
        lay.addWidget(lic)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.exec()

    def _on_add_folder(self) -> None:
        from extreme_cleaner.loader import save_user_rule

        values = self._folder_dialog("Add folder")
        if values is None:
            return
        if not values["name"] or not values["path"]:
            QMessageBox.warning(self, "Add folder", "Name and folder are required.")
            return
        try:
            rule = save_user_rule(self._root, values["name"], values["path"], values["tier"], values["describe"])
        except ValueError as e:
            QMessageBox.warning(self, "Add folder", str(e))
            return
        self.start_scan()  # reload rules, new folder appears under User in its tab
        QMessageBox.information(self, "Add folder", f"Added '{rule.name}' to the '{values['tier']}' tab.")

    def _on_edit_user(self, rid: str) -> None:
        from extreme_cleaner.loader import _read_user_entries, update_user_rule

        preset = next((r for r in _read_user_entries(self._root) if str(r.get("id")) == rid), None)
        values = self._folder_dialog("Edit folder", preset)
        if values is None:
            return
        if not values["name"] or not values["path"]:
            QMessageBox.warning(self, "Edit folder", "Name and folder are required.")
            return
        try:
            update_user_rule(self._root, rid, values["name"], values["path"], values["tier"], values["describe"])
        except ValueError as e:
            QMessageBox.warning(self, "Edit folder", str(e))
            return
        self.start_scan()

    def _on_delete_user(self, rid: str) -> None:
        from extreme_cleaner.loader import delete_user_rule

        if QMessageBox.question(self, "Delete folder", "Remove this entry? (Files on disk stay untouched.)") != QMessageBox.Yes:
            return
        delete_user_rule(self._root, rid)
        self.start_scan()

    def _collect_checked(self) -> list:
        by_id: dict = {}

        def flat(res):
            by_id[res.rule.id] = res
            for c in res.children or []:
                flat(c)

        for r in self._results:
            flat(r)
        out = []
        for leaf in self._iter_leaves():  # safe tree only
            if MainWindow._row_state(leaf) == Qt.Checked:
                rid = leaf.data(0, Qt.UserRole + 4)
                if rid and rid in by_id:
                    out.append(by_id[rid])
        return out

    def _on_delete(self) -> None:
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QMessageBox, QProgressDialog, QTextEdit, QVBoxLayout

        from extreme_cleaner import cleaner as C
        from extreme_cleaner.scanner import fmt_size

        checked = self._collect_checked()
        if not checked:
            QMessageBox.information(self, "Delete", "Nothing checked in Safe cleanup.")
            return
        checked_ids = {r.rule.id for r in checked}

        def _touches(res) -> bool:
            if res.rule.id in checked_ids:
                return True
            return any(_touches(c) for c in res.children or [])

        # Rescan the TOP-LEVEL rules that contained the checked rows: option rows
        # have composite ids ("rule:opt") that match no rule on reload.
        self._del_ids = [r.rule.id for r in self._results if _touches(r)]
        # The Recycle Bin must always be re-measured after any deletion: its size
        # changes whether files went in or it got emptied (even if never checked).
        for r in self._results:
            if r.rule.pin and r.rule.id not in self._del_ids:
                self._del_ids.append(r.rule.id)
        actions, blocked = C.plan_deletion(checked)
        if not actions:
            self._show_manual_dialog(checked, blocked)
            return
        rp_ok, rp_msg = C.create_restore_point()
        # Estimate from UNIQUE checked rules (their scan sizes), never from actions:
        # one rule fans out to many paths and every action carries the full rule
        # size — summing actions multiplies the estimate. Matches the tree suffix.
        seen_ids: set[str] = set()
        total = 0
        for _r in checked:
            if _r.rule.id not in seen_ids:
                seen_ids.add(_r.rule.id)
                total += _r.size_bytes
        want: set[str] = set()
        seen: set[str] = set()

        def collect(res):
            if res.rule.id in seen:
                return
            seen.add(res.rule.id)
            want.update(p.lower() for p in (res.rule.processes or []))
            for c in res.children or []:
                collect(c)
        for _r in checked:
            collect(_r)
        procs = C.running_processes(sorted(want))
        closeable = C.closeable_processes(procs)
        closed_note = ""
        self._kept_running = []
        if closeable:
            # CCleaner-style offer: close what holds the files, never AV/security.
            held = [p for p in procs if p not in closeable]
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Programs are running")
            text = ("These programs are using the files you selected:\n\n"
                    + ", ".join(closeable)
                    + "\n\nClose them now and continue?\n"
                      "Browsers reopen with your tabs; other apps may first ask to save unsaved work.")
            if held:
                text += "\n\nNever closed automatically: " + ", ".join(held) + " (antivirus/security)"
            box.setText(text)
            b_close = box.addButton("Close and continue", QMessageBox.AcceptRole)
            b_cont = box.addButton("Continue anyway", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is None or clicked is box.button(QMessageBox.Cancel):
                return
            if clicked is b_close:
                closed, still = C.close_programs(closeable)
                if closed:
                    closed_note = "Closed: " + ", ".join(closed) + "."
                procs = C.running_processes(sorted(want))
            elif clicked is b_cont:
                self._kept_running = C.running_processes(closeable)
        import shutil

        try:
            disk_total = shutil.disk_usage("C:/").total
        except OSError:
            disk_total = 100 * 1024**3
        bin_hint = min(4 * 1024**3, int(disk_total * 0.05))
        bin_warn = ""
        if total > bin_hint:
            from extreme_cleaner.scanner import fmt_size as _fmt

            bin_warn = (f"WARNING: {_fmt(total)} likely exceeds the Recycle Bin "
                        f"(~{_fmt(bin_hint)}). Oversized items will FAIL to move (files stay put) — "
                        "clean in smaller parts or empty the bin between runs.")
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm deletion")
        dlg.resize(620, 420)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        lines = [f"Actions: {len(actions)}, estimated {fmt_size(total)} -> Recycle Bin",
                 f"Restore point: {'OK' if rp_ok else 'FAILED: ' + rp_msg}", ""]
        if closed_note:
            lines += [closed_note, ""]
        if procs:
            lines += [f"WARNING: these programs are RUNNING: {', '.join(procs)}. "
                      "Close them first — locked files will be skipped with errors.", ""]
        if bin_warn:
            lines += [bin_warn, ""]
        lines += [f"• {a.label}" for a in actions[:200]]
        if len(actions) > 200:
            lines.append(f"… and {len(actions) - 200} more")
        if blocked:
            lines += ["", f"Blocked/skipped ({len(blocked)}):"] + [f"  - {b}" for b in blocked[:20]]
        txt.setPlainText("\n".join(lines))
        lay.addWidget(txt)
        ack = QCheckBox("I understand: no restore point, proceed anyway")
        ack.setChecked(rp_ok)
        ack.setVisible(not rp_ok)
        lay.addWidget(ack)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Delete")
        buttons.button(QDialogButtonBox.Ok).setEnabled(rp_ok)
        ack.toggled.connect(lambda on: buttons.button(QDialogButtonBox.Ok).setEnabled(on))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        prog = QProgressDialog("Deleting…", "Cancel", 0, 1000, self)
        prog.setWindowTitle("ExtremeCleaner")
        prog.setMinimumDuration(0)

        def _center_prog() -> None:
            center = self.geometry().center()
            prog.move(center.x() - prog.width() // 2, center.y() - prog.height() // 2)

        prog.adjustSize()
        prog.setMinimumWidth(660)
        _center_prog()
        prog.show()
        self._del_worker = DeleteWorker(actions, total)
        self._del_worker.progress.connect(
            lambda i, n, label: (prog.setMaximum(n), prog.setValue(i),
                                 prog.setLabelText(label[:120]), _center_prog()))
        self._del_worker.done.connect(lambda freed, errors: self._on_delete_done(actions, freed, errors, prog))
        prog.canceled.connect(self._del_worker.terminate)
        self._del_worker.start()

    def _on_delete_done(self, actions, freed: int, errors: list, prog) -> None:
        from extreme_cleaner import cleaner as C
        from extreme_cleaner.scanner import fmt_size

        freed = int(freed)  # done-signal carries float (bytes overflow int32)
        prog.close()
        log = C.log_deletion(actions, freed, errors)
        # If the Recycle Bin is emptied in this run, "sent to Recycle Bin" would be a lie.
        emptied_bin = any(a.kind == "empty_bin" for a in actions)
        msg = f"Freed ~{fmt_size(freed)}" + ("" if emptied_bin else " to Recycle Bin") + "."
        if errors:
            kept = [p for p in getattr(self, "_kept_running", []) if p]
            if kept:
                names = ", ".join(kept)
                msg += (f"\n\n{len(errors)} item(s) could NOT be deleted because you chose to "
                        f"keep these programs running:\n  {names}\n\n"
                        f"Close {names} and run the cleanup again. Everything else was deleted.")
            else:
                msg += (f"\n\n{len(errors)} item(s) could not be deleted. "
                        "Close the programs that use these files and run the cleanup again.")
            msg += f"\n\nDetails: {log}"
        else:
            msg += f"\n\nLog: {log}"
        QMessageBox.information(self, "Delete done", msg)
        self.start_scan(ids=self._del_ids)  # only what was touched — tabs 2/3 stay as-is

    def _show_manual_dialog(self, checked, blocked) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

        from extreme_cleaner.scanner import fmt_size

        dlg = QDialog(self)
        dlg.setWindowTitle("Manual steps needed")
        dlg.resize(640, 420)
        lay = QVBoxLayout(dlg)
        info = QLabel("The program cannot do this itself — each item needs a manual step. Do them one by one:")
        info.setWordWrap(True)
        lay.addWidget(info)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        vbox = QVBoxLayout(inner)
        items = []

        def flat(res):
            items.append(res)
            for c in res.children or []:
                flat(c)

        for r in checked:
            flat(r)
        shown = 0
        for res in items:
            rule = res.rule
            if rule.kind == "run_command" and rule.exec:
                continue  # executable ones never land here
            text = rule.command or rule.describe or ""
            if not text and not res.resolved:
                continue
            shown += 1
            box = QGroupBox(f"{rule.name} — {fmt_size(res.size_bytes)}")
            blay = QVBoxLayout(box)
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            blay.addWidget(lbl)
            row = QHBoxLayout()
            if res.resolved and Path(res.resolved).exists():
                b_open = QPushButton("Open folder")
                b_open.clicked.connect(lambda _=False, p=res.resolved: self._open_path(p))
                row.addWidget(b_open)
            if rule.command:
                b_copy = QPushButton("Copy command")
                b_copy.clicked.connect(lambda _=False, c=rule.command: QApplication.clipboard().setText(c))
                row.addWidget(b_copy)
            if rule.docs:
                b_docs = QPushButton("Open instructions")
                b_docs.clicked.connect(lambda _=False, u=rule.docs: QDesktopServices.openUrl(QUrl(u)))
                row.addWidget(b_docs)
            row.addStretch(1)
            blay.addLayout(row)
            vbox.addWidget(box)
        if not shown:
            vbox.addWidget(QLabel("Nothing actionable:\n" + "\n".join(blocked[:20])))
        scroll.setWidget(inner)
        lay.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.exec()

    def _delete_placeholder(self) -> None:
        QMessageBox.information(self, "Later", "Deletion is the next step. Selection only for now.")


def main() -> int:
    import os
    import time

    from PySide6.QtGui import QIcon

    from extreme_cleaner.loader import bundle_dir, data_dir

    root = project_root_from_here()
    if os.environ.get("EXTREME_CLEANER_SMOKE") == "1":
        # Frozen-exe self test (a windowed exe has no stdout): run the real
        # threaded scan headless and report into smoke_result.txt next to the exe.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv)
        window = MainWindow(root)
        deadline = time.time() + 300
        while window._worker is not None and window._worker.isRunning() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        app.processEvents()
        scanned = window._worker is None or not window._worker.isRunning()
        top = sorted(window._results, key=lambda r: r.size_bytes, reverse=True)[:10]
        from extreme_cleaner import cleaner as _C

        sub_procs = {
            "tasklist": _C.running_processes(["explorer.exe", "nonexistent_xyz.exe"]),
            "taskkill": _C.close_programs(["nonexistent_xyz.exe"], timeout=1),
        }
        # Probe what the binary really renders on user rows: (name, native_cb, widget_cbs).
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QCheckBox as _QCB

        probe = []
        _stack = [window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())]
        while _stack:
            _it = _stack.pop()
            _box = window.tree.itemWidget(_it, 0)
            if _box is not None:
                probe.append((_it.data(0, _Qt.UserRole + 3) or _it.text(0),
                              bool(_it.flags() & _Qt.ItemIsUserCheckable),
                              len(_box.findChildren(_QCB))))
            _stack.extend(_it.child(i) for i in range(_it.childCount()))
        lines = [
            f"scan_done={scanned}",
            f"build={build_label()}",
            f"results={len(window._results)}",
            "bin=" + repr([(r.size_bytes, r.files) for r in window._results if r.rule.id == "recycle-bin"]),
            f"sub={sub_procs}",
            f"probe={probe}",
        ]
        lines += [f"{r.rule.id}={r.size_bytes}/{r.files}" for r in top]
        (data_dir() / "smoke_result.txt").write_text("\n".join(lines), encoding="utf-8")
        return 0
    app = QApplication(sys.argv)
    # VS Code-like tooltip: dark readable bubble instead of gray-on-gray.
    app.setStyleSheet(
        "QToolTip { background-color: #252526; color: #cccccc;"
        " border: 1px solid #454545; padding: 6px; opacity: 235; }"
    )
    window = MainWindow(root)
    icon = bundle_dir() / "assets" / "icon.png"
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
