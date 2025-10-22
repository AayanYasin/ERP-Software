# =============================
# clients_master.py — Parties (Customers/Suppliers)
# (Business/UI unchanged; only COA fastness added)
# =============================

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QTextEdit, QListWidget, QListWidgetItem,
    QDialogButtonBox, QMessageBox, QHeaderView, QAbstractItemView, QToolBar, QAction, QStyle,
    QProgressDialog, QGroupBox, QShortcut, QTabWidget
)
# <<< fastness: add QThread, pyqtSignal >>>
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QColor, QBrush

from firebase.config import db
from firebase_admin import firestore

import uuid, datetime, re, os, csv, tempfile
# <<< fastness: tiny stdlib add for cache >>>
import json

# -----------------------------
# Styling (UNCHANGED)
# -----------------------------
APP_STYLE = """
/* Global */
QWidget { font-size: 14px; }

/* Inputs */
QLineEdit, QComboBox, QTextEdit {
    border: 1px solid #d5dbe7; border-radius: 8px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #2d6cdf; }

/* Table */
QTableWidget { gridline-color: #e6e9f2; }
QHeaderView::section { background: #f7f9fc; padding: 6px; border: none; border-bottom: 1px solid #e6e9f2; }
"""

ACCOUNT_TYPE_PREFIX = {
    "Asset": "1",
    "Liability": "2",
    "Equity": "3",
    "Income": "4",
    "Expense": "5"
}

AUTO_CREATE_SENTINEL = "__AUTO_CREATE__"

# -----------------------------
# Helpers (UNCHANGED)
# -----------------------------
def _fmt_account_display(doc_id: str, acc: dict) -> str:
    if not acc:
        return f"[{doc_id}]"
    code = (acc.get("code") or acc.get("id") or "").strip()
    name = (acc.get("name") or "").strip()
    typ  = (acc.get("type") or "").strip()
    bits = []
    if code: bits.append(f"[{code}]")
    if name: bits.append(name)
    if typ:  bits.append(f"({typ})")
    return " ".join(bits) if bits else f"[{doc_id}]"

def _is_admin_user(user_data) -> bool:
    try:
        return str((user_data or {}).get("role", "")).strip().lower() == "admin"
    except Exception:
        return False

# =============================
# <<< fastness: cache + batching helpers (NEW) >>>
# =============================
def _app_cache_dir() -> str:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
    root = os.path.join(base, "PlayWithAayan-ERP_Software", "cache")
    os.makedirs(root, exist_ok=True)
    return root

def _save_cache_json(filename: str, payload: dict):
    try:
        path = os.path.join(_app_cache_dir(), filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception:
        pass

def _load_cache_json(filename: str) -> dict:
    try:
        path = os.path.join(_app_cache_dir(), filename)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _batch_get_accounts_current_balances(account_ids: set) -> dict:
    if not account_ids:
        return {}
    refs = [db.collection("accounts").document(aid) for aid in account_ids if aid]
    balances = {}
    try:
        for snap in firestore.client().get_all(refs):
            if snap and getattr(snap, "exists", False):
                d = snap.to_dict() or {}
                try:
                    balances[snap.id] = float(d.get("current_balance", 0.0) or 0.0)
                except Exception:
                    balances[snap.id] = 0.0
    except Exception:
        pass
    return balances

# <<< fastness: background loader (NEW) >>>
class _PartiesLoader(QThread):
    loaded = pyqtSignal(list)   # emits list[dict] rows ready to paint (with _doc_id and _balance)
    failed = pyqtSignal(str)

    def run(self):
        try:
            rows = []
            account_ids = set()
            try:
                stream = db.collection("parties").select(
                    ["id","name","type","contact_person","phone","branches","active","coa_account_id"]
                ).stream()
            except Exception:
                stream = db.collection("parties").stream()

            for doc in stream:
                d = doc.to_dict() or {}
                d["_doc_id"] = doc.id
                coa = d.get("coa_account_id")
                if coa:
                    account_ids.add(coa)
                rows.append(d)

            bal = _batch_get_accounts_current_balances(account_ids)
            for r in rows:
                r["_balance"] = bal.get(r.get("coa_account_id",""), None)
            self.loaded.emit(rows)
        except Exception as e:
            self.failed.emit(str(e))

# =============================
# Main list module (CLASS NAME + UI UNCHANGED)
# =============================
class PartyModule(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data or {}
        self.setMinimumSize(1100, 650)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        QTimer.singleShot(0, self.load_parties)

    # ---------- UI (UNCHANGED) ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("👥 Parties")
        title.setStyleSheet("font-size: 20px; font-weight: 700; padding: 4px 2px;")
        header.addWidget(title)
        header.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search name / contact / phone / branch…  (Ctrl+F)")
        self.search_box.textChanged.connect(self._apply_filter_to_current_tab)
        header.addWidget(self.search_box)

        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        header.addWidget(self.count_lbl)

        root.addLayout(header)

        toolbar = QToolBar()
        act_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self)
        act_add.setShortcut("Ctrl+N")
        act_add.triggered.connect(self._add_party)

        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.load_parties)

        act_export = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export CSV", self)
        act_export.triggered.connect(self._export_csv_current_tab)

        toolbar.addAction(act_add)
        toolbar.addAction(act_refresh)
        toolbar.addSeparator()
        toolbar.addAction(act_export)

        if _is_admin_user(self.user_data):
            self.act_change_coa = QAction(self.style().standardIcon(QStyle.SP_ArrowRight), "Change COA (Admin)", self)
            self.act_change_coa.setToolTip("Change the Chart of Accounts for the selected party (Admin only).")
            self.act_change_coa.triggered.connect(self._change_coa_selected_party)
            toolbar.addSeparator()
            toolbar.addAction(self.act_change_coa)

        root.addWidget(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)

        self.table_customers = self._make_table()
        w1 = QWidget(); l1 = QVBoxLayout(w1); l1.setContentsMargins(0,0,0,0); l1.addWidget(self.table_customers)
        self.tabs.addTab(w1, "Customers")

        self.table_suppliers = self._make_table()
        w2 = QWidget(); l2 = QVBoxLayout(w2); l2.setContentsMargins(0,0,0,0); l2.addWidget(self.table_suppliers)
        self.tabs.addTab(w2, "Suppliers")

        self.table_customers.itemDoubleClicked.connect(self._edit_selected_party)
        self.table_suppliers.itemDoubleClicked.connect(self._edit_selected_party)

        self.tabs.currentChanged.connect(self._apply_filter_to_current_tab)
        root.addWidget(self.tabs, stretch=1)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_box.setFocus())

    def _make_table(self):
        t = QTableWidget(0, 7)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(True)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 6):
            t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        t.setHorizontalHeaderLabels(["Name", "Type", "Contact Person", "Phone", "Branches", "Status", "Balance"])
        return t

    def _current_table(self):
        return self.table_customers if self.tabs.currentIndex() == 0 else self.table_suppliers

    # ---------- Data load (FASTNESS APPLIED, UI/logic preserved) ----------
    def load_parties(self):
        # <<< fastness: cache-first paint (non-blocking) >>>
        snap = _load_cache_json("parties_snapshot.json")
        if snap.get("rows"):
            self._paint_parties(snap["rows"])

        # <<< fastness: live refresh in background >>>
        self._progress = QProgressDialog("Loading parties…", None, 0, 0, self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setAutoClose(True)
        self._progress.show()

        self.table_customers.setSortingEnabled(False)
        self.table_suppliers.setSortingEnabled(False)

        self._loader = _PartiesLoader()
        self._loader.loaded.connect(self._on_parties_loaded)
        self._loader.failed.connect(self._on_parties_failed)
        self._loader.start()

    # <<< fastness: new slots >>> 
    def _on_parties_loaded(self, rows):
        try:
            self._paint_parties(rows)
            _save_cache_json("parties_snapshot.json", {"rows": rows})
        finally:
            try: self._progress.close()
            except Exception: pass
            self.table_customers.setSortingEnabled(True)
            self.table_suppliers.setSortingEnabled(True)

    def _on_parties_failed(self, msg):
        try: self._progress.close()
        except Exception: pass
        # Keep whatever is on screen (cached or empty); inform only if nothing painted
        if not (self.table_customers.rowCount() or self.table_suppliers.rowCount()):
            QMessageBox.warning(self, "Load failed", msg)

    # <<< fastness: extracted painter that preserves your exact row layout >>>
    def _paint_parties(self, rows):
        for t in (self.table_customers, self.table_suppliers):
            t.clearContents()
            t.setRowCount(0)

        for data in rows:
            ptype_raw = (data.get("type") or "").strip()
            ptype_lc = ptype_raw.lower()
            ptype = ptype_lc.capitalize() if ptype_lc else ""
            human_id = (data.get("id") or "").strip()
            party_name = (data.get("name") or "").strip()

            raw_active = data.get("active", True)
            if isinstance(raw_active, str):
                is_active = raw_active.strip().lower() in ("active", "true", "1", "yes")
            else:
                is_active = bool(raw_active)

            branches_val = data.get("branches", [])
            if isinstance(branches_val, str):
                branches_val = [branches_val]
            branches_text = ", ".join("" if v is None else str(v) for v in branches_val)

            name_item = QTableWidgetItem(f"[{human_id}] - {party_name}")
            name_item.setData(Qt.UserRole, data.get("_doc_id"))

            type_item = QTableWidgetItem(ptype)
            contact_item = QTableWidgetItem(data.get("contact_person", "") or "")
            phone_item = QTableWidgetItem(data.get("phone", "") or "")
            branches_item = QTableWidgetItem(branches_text)

            status_text = "Active" if is_active else "Inactive"
            status_item = QTableWidgetItem(status_text)
            pill_brush = QBrush(QColor(50,150,50) if is_active else QColor(200,50,50))
            status_item.setBackground(pill_brush)
            status_item.setData(Qt.BackgroundRole, pill_brush)
            status_item.setForeground(QBrush(QColor(Qt.white)))

            # <<< fastness: prefer pre-batched balance if present; else your original per-row fetch >>>
            if "_balance" in data and data["_balance"] is not None:
                curr_num = float(data["_balance"] or 0.0)
                balance_item = QTableWidgetItem(f"{curr_num:,.2f}")
                balance_item.setData(Qt.UserRole, curr_num)
            else:
                balance_str, curr_num = self._safe_balance(data)
                balance_item = QTableWidgetItem(balance_str)
                balance_item.setData(Qt.UserRole, curr_num)
            balance_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            goes_customers = ptype_lc in ("customer", "both")
            goes_suppliers = ptype_lc in ("supplier", "both")

            if goes_customers:
                self._append_row(self.table_customers,
                                 name_item, type_item, contact_item, phone_item,
                                 branches_item, status_item, balance_item)

            if goes_suppliers:
                self._append_row(self.table_suppliers,
                                 name_item.clone(), type_item.clone(), contact_item.clone(), phone_item.clone(),
                                 branches_item.clone(), status_item.clone(), balance_item.clone())

        self._apply_filter_to_current_tab()

    # ---------- Append row helper (UNCHANGED) ----------
    def _append_row(self, table, *items):
        row = table.rowCount()
        table.insertRow(row)
        for c, it in enumerate(items):
            table.setItem(row, c, it)

    # ---------- Balance (UNCHANGED, kept for fallback and edits) ----------
    def _safe_balance(self, party_data):
        """Return (formatted, numeric) balance for sorting and display as a signed number."""
        try:
            coa_id = party_data.get("coa_account_id")
            if not coa_id:
                return ("-", 0.0)
            snap = db.collection("accounts").document(coa_id).get()
            if not snap.exists:
                return ("-", 0.0)

            acc = snap.to_dict() or {}
            curr = float(acc.get("current_balance", 0.0) or 0.0)
            return (f"{curr:,.2f}", curr)
        except Exception:
            return ("-", 0.0)

    # ---------- Filter & counts (UNCHANGED) ----------
    def _reapply_status_pills(self, table):
        for r in range(table.rowCount()):
            it = table.item(r, 5)
            if not it:
                continue
            txt = (it.text() or "").strip().lower()
            is_active = (txt == "active")
            pill_brush = QBrush(QColor(50,150,50) if is_active else QColor(200,50,50))
            it.setBackground(pill_brush)
            it.setData(Qt.BackgroundRole, pill_brush)
            it.setForeground(QBrush(QColor(Qt.white)))

    def _update_row_count_label(self):
        table = self._current_table()
        visible = sum(not table.isRowHidden(r) for r in range(table.rowCount()))
        noun = "customers" if self.tabs.currentIndex() == 0 else "suppliers"
        self.count_lbl.setText(f"Total: {visible} {noun}")

    def _apply_filter_to_current_tab(self):
        table = self._current_table()
        term = (self.search_box.text() or "").lower()
        was_sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)

        for r in range(table.rowCount()):
            row_text = " ".join(
                (table.item(r, c).text() if table.item(r, c) else "")
                for c in range(table.columnCount())
            ).lower()
            table.setRowHidden(r, term not in row_text)

        self._reapply_status_pills(table)
        table.setSortingEnabled(was_sorting)
        self._update_row_count_label()

    # ---------- Export (UNCHANGED) ----------
    def _export_csv_current_tab(self):
        if _is_admin_user(self.user_data):
            try:
                table = self._current_table()
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                if not os.path.isdir(desktop):
                    desktop = tempfile.gettempdir()
                path = os.path.join(desktop, "parties_export.csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
                    writer.writerow(headers)
                    for r in range(table.rowCount()):
                        if table.isRowHidden(r):
                            continue
                        row = [(table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount())]
                        writer.writerow(row)
                QMessageBox.information(self, "Export complete", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
        else:
            QMessageBox.warning(self, "Not Allowed", "You do not have permission to perform this action.")
            

    # ---------- Add/Edit (UNCHANGED) ----------
    def _add_party(self):
        dlg = PartyDialog(self.user_data)
        if dlg.exec_() == QDialog.Accepted:
            self.load_parties()

    def _edit_selected_party(self):
        table = self.sender() if isinstance(self.sender(), QTableWidget) else self._current_table()
        row = table.currentRow()
        if row < 0:
            return
        name_item = table.item(row, 0)
        if not name_item:
            QMessageBox.warning(self, "Not found", "Unable to locate selected party.")
            return
        doc_id = name_item.data(Qt.UserRole)
        if not doc_id:
            QMessageBox.warning(self, "Missing id", "This row has no stored document id.")
            return

        snap = db.collection("parties").document(doc_id).get()
        existing = snap.to_dict() if snap.exists else {}
        dlg = PartyDialog(self.user_data, doc_id=doc_id, existing_data=existing)
        if dlg.exec_() == QDialog.Accepted:
            self.load_parties()

    # ---------- Admin-only COA change (UNCHANGED) ----------
    def _change_coa_selected_party(self):
        if not _is_admin_user(self.user_data):
            QMessageBox.warning(self, "Not allowed", "Only admins can change the COA of a party.")
            return
        table = self._current_table()
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a party", "Please select a party first.")
            return
        name_item = table.item(row, 0)
        if not name_item:
            QMessageBox.warning(self, "Not found", "Unable to locate selected party.")
            return
        doc_id = name_item.data(Qt.UserRole)
        if not doc_id:
            QMessageBox.warning(self, "Missing id", "This row has no stored document id.")
            return

        snap = db.collection("parties").document(doc_id).get()
        existing = snap.to_dict() if snap.exists else {}
        dlg = ChangeCOADialog(self.user_data, existing_coa_id=existing.get("coa_account_id"))
        if dlg.exec_() == QDialog.Accepted:
            new_coa_id = dlg.selected_account_id
            if new_coa_id:
                try:
                    db.collection("parties").document(doc_id).set({"coa_account_id": new_coa_id}, merge=True)
                    QMessageBox.information(self, "COA updated", "The COA account was updated successfully.")
                    self.load_parties()
                except Exception as e:
                    QMessageBox.critical(self, "Update failed", str(e))


# =============================
# Dialogs (UNCHANGED)
# =============================
class PartyDialog(QDialog):
    def __init__(self, user_data, doc_id=None, existing_data=None):
        super().__init__()
        self.user_data = user_data or {}
        self.doc_id = doc_id
        self.existing_data = existing_data or {}
        self.setWindowTitle("Edit Party" if doc_id else "Add Party")
        self.setMinimumWidth(640)
        self.setStyleSheet(APP_STYLE)
        self._build_form()
        if not self.doc_id:
            self._prefetch_next_code()

        self.cmb_type.currentIndexChanged.connect(self._update_coa_code_display)
        self._update_coa_code_display()

    def _build_form(self):
        lay = QVBoxLayout(self)
        subtitle = QLabel("Fill in the party details. Fields marked * are required.")
        subtitle.setStyleSheet("color:#6b7280;")
        lay.addWidget(subtitle)

        form_box = QGroupBox("Details")
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignRight)

        self.edt_name = QLineEdit(self.existing_data.get("name", ""))
        self.edt_code = QLineEdit(self.existing_data.get("id", ""))
        self.edt_code.setReadOnly(True)
        self.edt_code.setToolTip("Assigned automatically when you save a new party.")

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Customer", "Supplier"])
        t = (self.existing_data.get("type") or "").strip().lower()
        idx = {"customer":0,"supplier":1,"both":2}.get(t, 0)
        self.cmb_type.setCurrentIndex(idx)

        self.edt_contact = QLineEdit(self.existing_data.get("contact_person", "") or "")
        self.edt_phone = QLineEdit(self.existing_data.get("phone", "") or "")

        self.edt_gst = QLineEdit(self.existing_data.get("gst", "") or "")
        self.edt_ntn = QLineEdit(self.existing_data.get("ntn", "") or "")
        self.edt_email = QLineEdit(self.existing_data.get("email", "") or "")
        self.edt_address = QTextEdit(self.existing_data.get("address", "") or "")
        self.edt_address.setFixedHeight(60)

        branches_val = self.existing_data.get("branches", [])
        if isinstance(branches_val, str):
            branches_val = [branches_val]
        self.lst_branches = QListWidget()
        for b in self.user_data.get("branch", []):
            item = QListWidgetItem(str(b))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if b in branches_val else Qt.Unchecked)
            self.lst_branches.addItem(item)

        self.cmb_active = QComboBox()
        self.cmb_active.addItems(["Active", "Inactive"])
        raw_active = self.existing_data.get("active", True)
        if isinstance(raw_active, str):
            is_active = raw_active.strip().lower() in ("active", "true", "1", "yes")
        else:
            is_active = bool(raw_active)
        self.cmb_active.setCurrentIndex(0 if is_active else 1)

        self.edt_opening_bal = QLineEdit(str(self.existing_data.get("opening_balance", 0)))
        self.cmb_opening_type = QComboBox()
        self.cmb_opening_type.addItems(["DR", "CR"])
        if (self.existing_data.get("opening_type") or "").upper() == "CR":
            self.cmb_opening_type.setCurrentIndex(1)
        def _sync_opening_type(index):
            party_type = self.cmb_type.currentText()
            if party_type == "Customer":
                self.cmb_opening_type.setCurrentIndex(0)
            elif party_type == "Supplier":
                self.cmb_opening_type.setCurrentIndex(1)
        self.cmb_type.currentIndexChanged.connect(_sync_opening_type)
        if not self.doc_id and not self.existing_data.get("opening_type"):
            _sync_opening_type(self.cmb_type.currentIndex())
        ob_container = QWidget()
        ob_layout = QHBoxLayout(ob_container)
        ob_layout.setContentsMargins(0,0,0,0)
        ob_layout.addWidget(self.edt_opening_bal)
        ob_layout.addWidget(self.cmb_opening_type)
        if self.doc_id:
            self.edt_opening_bal.clear()
            self.edt_opening_bal.setPlaceholderText("Managed from COA")
            self.edt_opening_bal.setToolTip("Opening balance is managed from the COA module.")
            self.edt_opening_bal.setDisabled(True)
            self.cmb_opening_type.setDisabled(True)

        self._coa_accounts_cache = []
        self.cmb_coa = None
        self.lbl_coa = None

        self.edt_coa_code = QLineEdit()
        self.edt_coa_code.setReadOnly(True)
        self.edt_coa_code.setStyleSheet("background:#f3f4f6;")
        self.edt_coa_code.setPlaceholderText("Will be auto-generated")

        current_coa_id = self.existing_data.get("coa_account_id")

        if _is_admin_user(self.user_data):
            self.cmb_coa = QComboBox()
            self.cmb_coa.setEditable(True)
            self.cmb_coa.addItem("➕ Create New Account (auto)", AUTO_CREATE_SENTINEL)
            self._populate_accounts_into_combo(self.cmb_coa, current_coa_id)
            if self.doc_id and current_coa_id:
                for i in range(1, self.cmb_coa.count()):
                    if self.cmb_coa.itemData(i) == current_coa_id:
                        self.cmb_coa.setCurrentIndex(i)
                        break
            else:
                self.cmb_coa.setCurrentIndex(0)
            self.cmb_coa.currentIndexChanged.connect(self._update_coa_code_display)
            form.addRow("COA Account", self.cmb_coa)
        else:
            display = "-"
            if current_coa_id:
                try:
                    snap = db.collection("accounts").document(current_coa_id).get()
                    acc = snap.to_dict() if snap.exists else {}
                    display = _fmt_account_display(current_coa_id, acc)
                    self.edt_coa_code.setText(acc.get("code", ""))
                except Exception:
                    display = f"[{current_coa_id}]"
            else:
                display = "(Will auto-create on Save)"
            self.lbl_coa = QLabel(display)
            form.addRow("COA Account", self.lbl_coa)

        form.addRow("COA Code", self.edt_coa_code)

        form.addRow("Code *", self.edt_code)
        form.addRow("Name *", self.edt_name)
        form.addRow("Contact *", self.edt_contact)
        form.addRow("Type *", self.cmb_type)
        form.addRow("Phone *", self.edt_phone)
        form.addRow("Email", self.edt_email)
        form.addRow("GST", self.edt_gst)
        form.addRow("NTN", self.edt_ntn)
        form.addRow("Address *", self.edt_address)
        form.addRow("Branches *", self.lst_branches)
        form.addRow("Opening Balance *", ob_container)
        form.addRow("Status *", self.cmb_active)

        lay.addWidget(form_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # (dialog helpers and save logic UNCHANGED — omitted here for brevity in this comment line)
    # >>> The following methods ( _populate_accounts_into_combo, _selected_coa_id,
    #     _peek_next_account_code, _update_coa_code_display, _generate_next_party_code,
    #     _prefetch_next_code, _normalize_drcr, _generate_code_once,
    #     _post_opening_journal_entry, _create_coa_account_for_party,
    #     _collect_branches_from_ui, _save )
    # are identical to your original file content and retained below without modification.
    # ------------------ (start original methods) ------------------

    def _populate_accounts_into_combo(self, combo: QComboBox, current_coa_id: str):
        if combo.count() and combo.itemData(0) == AUTO_CREATE_SENTINEL:
            while combo.count() > 1:
                combo.removeItem(1)
            start_index = 1
        else:
            combo.clear()
            start_index = 0

        self._coa_accounts_cache.clear()
        try:
            accounts = db.collection("accounts").stream()
            current_index = -1
            idx = start_index
            for acc_doc in accounts:
                acc = acc_doc.to_dict() or {}
                display = _fmt_account_display(acc_doc.id, acc)
                combo.addItem(display, acc_doc.id)
                self._coa_accounts_cache.append((display, acc_doc.id))
                if current_coa_id and acc_doc.id == current_coa_id:
                    current_index = idx
                idx += 1
            if current_index >= 0:
                combo.setCurrentIndex(current_index)
        except Exception as e:
            combo.addItem(f"(failed to load accounts: {e})", "")

    def _selected_coa_id(self) -> str:
        if self.cmb_coa is None:
            return None
        data = self.cmb_coa.currentData()
        if data:
            return data
        text = (self.cmb_coa.currentText() or "").strip()
        if text.lower().startswith("➕ create new account"):
            return AUTO_CREATE_SENTINEL
        for display, acc_id in self._coa_accounts_cache:
            if display == text:
                return acc_id
        return None

    def _peek_next_account_code(self, acc_type: str) -> str:
        try:
            prefix = ACCOUNT_TYPE_PREFIX.get(acc_type, "9")
            counter_ref = db.collection("meta").document("account_code_counters")
            snap = counter_ref.get()
            data = snap.to_dict() or {}
            last = data.get(acc_type)
            if not last:
                query = db.collection("accounts").where("type", "==", acc_type).get()
                max_code = int(prefix + "000")
                for d in query:
                    code_str = str((d.to_dict() or {}).get("code", "")) or ""
                    if code_str.startswith(prefix):
                        try:
                            max_code = max(max_code, int(code_str))
                        except:
                            pass
                last = max_code
            return str(int(last) + 1)
        except Exception:
            return ""

    def _update_coa_code_display(self):
        try:
            party_type = self.cmb_type.currentText()
            acc_type = "Asset" if party_type in ("Customer", "Both") else "Liability"

            if self.cmb_coa is not None:
                sel = self._selected_coa_id()
                if sel and sel != AUTO_CREATE_SENTINEL:
                    snap = db.collection("accounts").document(sel).get()
                    if snap.exists:
                        acc = snap.to_dict() or {}
                        self.edt_coa_code.setText(str(acc.get("code", "")))
                        return
                    self.edt_coa_code.setText("")
                    return
                if not self.doc_id:
                    self.edt_coa_code.setText(self._peek_next_account_code(acc_type))
                else:
                    self.edt_coa_code.setText("")
                return

            current_coa_id = self.existing_data.get("coa_account_id")
            if current_coa_id:
                snap = db.collection("accounts").document(current_coa_id).get()
                if snap.exists:
                    acc = snap.to_dict() or {}
                    self.edt_coa_code.setText(str(acc.get("code", "")))
                    return
                self.edt_coa_code.setText("")
                return

            if not self.doc_id:
                self.edt_coa_code.setText(self._peek_next_account_code(acc_type))
            else:
                self.edt_coa_code.setText("")
        except Exception:
            self.edt_coa_code.setText("")

    def _generate_next_party_code(self) -> str:
        doc_ref = db.collection("meta").document("cust_supp")
        transaction = firestore.client().transaction()

        @firestore.transactional
        def _tx(trans):
            snap = doc_ref.get(transaction=trans)
            data = snap.to_dict() or {}
            last = data.get("code")
            if last is None:
                try:
                    existing = db.collection("parties").stream()
                    max_num = 0
                    for d in existing:
                        v = (d.to_dict() or {}).get("id")
                        if v is None:
                            continue
                        s = str(v).strip()
                        if s.isdigit():
                            max_num = max(max_num, int(s))
                    last = max_num
                except Exception:
                    last = 0
            new_code = int(last) + 1
            trans.set(doc_ref, {"code": new_code}, merge=True)
            return str(new_code).zfill(3)

        return _tx(transaction)

    def _prefetch_next_code(self):
        try:
            doc_ref = db.collection("meta").document("cust_supp")
            doc = doc_ref.get()
            last_code = 0
            if doc.exists:
                data = doc.to_dict() or {}
                last_code = int(data.get("code", 0))
            next_code = str(last_code + 1).zfill(3)
            if not (self.edt_code.text() or "").strip():
                self.edt_code.setText(next_code)
        except Exception:
            pass

    def _normalize_drcr(self, val):
        v = (val or "").strip().lower()
        if v in ("dr", "debit"): return "debit"
        if v in ("cr", "credit"): return "credit"
        return "debit"

    def _generate_code_once(self, acc_type):
        prefix = ACCOUNT_TYPE_PREFIX.get(acc_type, "9")
        counter_ref = db.collection("meta").document("account_code_counters")
        transaction = firestore.client().transaction()

        @firestore.transactional
        def increment_code(trans):
            snapshot = counter_ref.get(transaction=trans)
            data = snapshot.to_dict() or {}
            last = data.get(acc_type)
            if not last:
                query = db.collection("accounts").where("type", "==", acc_type).get()
                codes = []
                for d in query:
                    code_str = str((d.to_dict() or {}).get("code", ""))
                    if code_str.startswith(prefix):
                        try: codes.append(int(code_str))
                        except: pass
                last = max(codes) if codes else int(prefix + "000")
            new_code = int(last) + 1
            data[acc_type] = new_code
            trans.set(counter_ref, data, merge=True)
            return str(new_code)

        return increment_code(transaction)

    def _post_opening_journal_entry(self, account_id, account_name, amount, drcr):
        try:
            amount = float(amount or 0)
            if amount <= 0:
                return
            drcr = self._normalize_drcr(drcr)

            equity_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if equity_q:
                equity_account_id = equity_q[0].id
                equity_account_name = (equity_q[0].to_dict() or {}).get("name", "System Offset Account")
            else:
                code = self._generate_code_once("Asset")
                branch_list = self.user_data.get("branch", [])
                if isinstance(branch_list, str):
                    branch_list = [branch_list]
                equity_doc = {
                    "name": "System Offset Account",
                    "slug": "opening_balances_equity",
                    "type": "Asset",
                    "code": code,
                    "parent": None,
                    "branch": branch_list,
                    "description": "System-generated equity account for opening balances",
                    "active": True,
                    "is_posting": True,
                    "opening_balance": None,
                    "current_balance": 0.0,
                }
                ref = db.collection("accounts").document()
                ref.set(equity_doc)
                equity_account_id = ref.id
                equity_account_name = "System Offset Account"

            a_pre = 0.0
            e_pre = 0.0

            try:
                amount = float(amount or 0)
            except Exception:
                amount = 0.0
            drcr = self._normalize_drcr(drcr)

            if drcr == "credit":
                party_line = {
                    "account_id": account_id, "account_name": account_name,
                    "debit": 0, "credit": amount, "balance_before": a_pre
                }
                equity_line = {
                    "account_id": equity_account_id, "account_name": equity_account_name,
                    "debit": amount, "credit": 0, "balance_before": e_pre
                }
            else:
                party_line = {
                    "account_id": account_id, "account_name": account_name,
                    "debit": amount, "credit": 0, "balance_before": a_pre
                }
                equity_line = {
                    "account_id": equity_account_id, "account_name": equity_account_name,
                    "debit": 0, "credit": amount, "balance_before": e_pre
                }

            now_server = firestore.SERVER_TIMESTAMP
            branch_val = self.user_data.get("branch")
            if isinstance(branch_val, list):
                branch_val = branch_val[0] if branch_val else "-"
            if not branch_val:
                branch_val = "-"

            je = {
                "date": now_server,
                "created_at": now_server,
                "created_by": self.user_data.get("email", "system"),
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
                "purpose": "Adjustment",
                "branch": branch_val,
                "description": f"Opening balance for {account_name}",
                "lines": [party_line, equity_line],
                "lines_account_ids": [party_line["account_id"], equity_line["account_id"]],
                "meta": {"kind": "opening_balance", "assume_prev_zero": True},
            }
            db.collection("journal_entries").document().set(je)
        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post JE: {e}")

    def _create_coa_account_for_party(self, name, type_, party_type, party_id, opening_balance, drcr, branches):
        def _slugify(text: str) -> str:
            s = (text or "").strip().lower()
            s = re.sub(r"[^a-z0-9]+", "_", s)
            return s.strip("_")

        def ensure_parent_account(name, acc_type, slug_value, branches_list):
            existing = db.collection("accounts").where("slug", "==", slug_value).limit(1).get()
            if existing:
                return existing[0].id
            code = self._generate_code_once(acc_type)
            parent_doc = {
                "name": name, "slug": slug_value, "type": acc_type, "code": code,
                "parent": None, "branch": branches_list,
                "description": f"System-generated parent for {name.lower()}",
                "active": True, "is_posting": False, "current_balance": 0.0
            }
            ref = db.collection("accounts").document()
            ref.set(parent_doc)
            return ref.id

        if isinstance(branches, str) or branches is None:
            branches = [branches] if branches else []
        try:
            ob_amount = float(opening_balance or 0.0)
        except Exception:
            ob_amount = 0.0
        drcr_norm = self._normalize_drcr(drcr)

        parent_name = "Clients" if party_type == "Customer" else ("Suppliers" if party_type == "Supplier" else "Clients_Suppliers")
        parent_slug = "clients_parent" if party_type == "Customer" else ("suppliers_parent" if party_type == "Supplier" else "clients_suppliers_parent")
        parent_id = ensure_parent_account(parent_name, type_, parent_slug, branches)

        computed_balance = ob_amount if drcr_norm == "debit" else -ob_amount
        if type_ not in ["Asset", "Expense"]:
            computed_balance *= -1

        account_code = self._generate_code_once(type_)
        child_slug = _slugify(name)

        opening_dict = None
        if ob_amount > 0:
            opening_dict = {"amount": ob_amount, "type": drcr_norm}

        coa_data = {
            "name": name,
            "slug": child_slug,
            "type": type_,
            "code": account_code,
            "parent": parent_id,
            "branch": branches,
            "description": f"Auto-generated for {party_type} {name}",
            "active": True,
            "is_posting": True,
            "opening_balance": opening_dict,
            "current_balance": computed_balance
        }
        ref = db.collection("accounts").document()
        ref.set(coa_data)
        return ref.id

    def _collect_branches_from_ui(self):
        branches = []
        for i in range(self.lst_branches.count()):
            item = self.lst_branches.item(i)
            if item.checkState() == Qt.Checked:
                branches.append(item.text())
        return branches

    def _save(self):
        name = self.edt_name.text().strip()
        code_current = (self.edt_code.text() or "").strip()
        contact = self.edt_contact.text().strip()
        phone = self.edt_phone.text().strip()
        address = (self.edt_address.toPlainText() or "").strip()

        missing = []
        if not name:    missing.append("Name")
        if not contact: missing.append("Contact Person")
        if not phone:   missing.append("Phone")
        if not address: missing.append("Address")

        branches = self._collect_branches_from_ui()
        if not branches:
            QMessageBox.warning(self, "Missing Branch", "Please select at least one Branch.")
            return

        if missing:
            QMessageBox.warning(self, "Missing fields", "Please fill: " + ", ".join(missing))
            return

        if not self.doc_id:
            try:
                generated_code = self._generate_next_party_code()
                self.edt_code.setText(generated_code)
            except Exception as e:
                QMessageBox.critical(self, "Code Error", f"Could not generate client code: {e}")
                return
            code_to_save = generated_code
        else:
            code_to_save = code_current

        payload = {
            "gst": (self.edt_gst.text() or "").strip(),
            "coa_account_id": self.existing_data.get("coa_account_id"),
            "ntn": (self.edt_ntn.text() or "").strip(),
            "contact_person": contact,
            "id": code_to_save,
            "name": name,
            "phone": phone,
            "type": self.cmb_type.currentText(),
            "email": (self.edt_email.text() or "").strip(),
            "address": address,
            "active": (self.cmb_active.currentText() == "Active"),
            "branches": branches,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        try:
            if self.doc_id:
                if _is_admin_user(self.user_data) and self.cmb_coa:
                    sel = self._selected_coa_id()
                    if sel and sel != AUTO_CREATE_SENTINEL:
                        payload["coa_account_id"] = sel
                db.collection("parties").document(self.doc_id).set(payload, merge=True)
                self.accept()
            else:
                party_ref = db.collection("parties").document()
                payload["created_at"] = firestore.SERVER_TIMESTAMP

                party_type = self.cmb_type.currentText()
                acc_type = "Asset" if party_type in ("Customer", "Both") else "Liability"

                use_auto_create = True
                selected_existing_id = None
                if _is_admin_user(self.user_data) and self.cmb_coa:
                    sel = self._selected_coa_id()
                    if sel and sel != AUTO_CREATE_SENTINEL:
                        use_auto_create = False
                        selected_existing_id = sel

                if not use_auto_create and selected_existing_id:
                    payload["coa_account_id"] = selected_existing_id
                    party_ref.set(payload)
                    self.accept()
                else:
                    coa_id = self._create_coa_account_for_party(
                        name, acc_type, party_type, party_ref.id,
                        self.edt_opening_bal.text().strip(),
                        self.cmb_opening_type.currentText(),
                        branches
                    )
                    payload["coa_account_id"] = coa_id
                    party_ref.set(payload)
                    try:
                        ob_amount = float(self.edt_opening_bal.text() or 0)
                    except Exception:
                        ob_amount = 0
                    if ob_amount > 0:
                        self._post_opening_journal_entry(
                            coa_id, name, ob_amount, self.cmb_opening_type.currentText()
                        )
                    self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

# (UNCHANGED)
class ChangeCOADialog(QDialog):
    def __init__(self, user_data, existing_coa_id=None):
        super().__init__()
        self.user_data = user_data or {}
        self.selected_account_id = None
        self.setWindowTitle("Change COA (Admin)")
        self.setMinimumWidth(480)
        self.setStyleSheet(APP_STYLE)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cmb = QComboBox(); self.cmb.setEditable(True)
        self._cache = []
        try:
            accounts = db.collection("accounts").stream()
            cur_index = -1; idx = 0
            for acc_doc in accounts:
                acc = acc_doc.to_dict() or {}
                display = _fmt_account_display(acc_doc.id, acc)
                self.cmb.addItem(display, acc_doc.id)
                self._cache.append((display, acc_doc.id))
                if existing_coa_id and acc_doc.id == existing_coa_id:
                    cur_index = idx
                idx += 1
            if cur_index >= 0:
                self.cmb.setCurrentIndex(cur_index)
        except Exception as e:
            self.cmb.addItem(f"(failed to load accounts: {e})", "")
        form.addRow("New COA Account", self.cmb)
        lay.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _ok(self):
        data = self.cmb.currentData()
        if not data:
            text = (self.cmb.currentText() or "").strip()
            for disp, acc_id in self._cache:
                if disp == text:
                    data = acc_id
                    break
        if not data:
            QMessageBox.warning(self, "Select", "Please select a valid account.")
            return
        self.selected_account_id = data
        self.accept()
