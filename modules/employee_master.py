# =============================
# employee_master.py — Employees (FASTNESS applied)
# (UI/design, business logic, and class names preserved)
# =============================

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QDialog, QFormLayout, QComboBox, QDialogButtonBox, QMessageBox, QHeaderView,
    QAbstractItemView, QToolBar, QAction, QStyle, QProgressDialog, QGroupBox,
    QShortcut, QTabWidget, QDateEdit
)
from PyQt5.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QColor, QBrush

from firebase.config import db
from firebase_admin import firestore

import uuid, datetime, re, os, csv, tempfile, json

APP_STYLE = """
QWidget { font-size: 14px; }
QGroupBox { border:1px solid #e3e7ef; border-radius:10px; margin-top:16px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#4a5568; }
QLineEdit, QComboBox, QDateEdit { border:1px solid #d5dbe7; border-radius:8px; padding:6px 8px; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border-color:#2d6cdf; }
QTableWidget { gridline-color:#e6e9f2; }
QHeaderView::section { background:#f7f9fc; padding:6px; border:none; border-bottom:1px solid #e6e9f2; }
"""

ACCOUNT_TYPE_PREFIX = {
    "Asset": "1",
    "Liability": "2",
    "Equity": "3",
    "Income": "4",
    "Expense": "5",
}

# -----------------------------
# Helpers
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
# FASTNESS: cache dir + read/write JSON + batched balances
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

# =============================
# FASTNESS: background loader thread
# =============================
class _EmployeesLoader(QThread):
    loaded = pyqtSignal(list)  # emits list[dict] rows with pre-batched _balance
    failed = pyqtSignal(str)

    def run(self):
        try:
            rows = []
            account_ids = set()
            try:
                stream = db.collection("employees").select([
                    "name","employee_code","designation","branch","contact","email",
                    "date_joined","salary_type","salary","active","status","coa_account_id"
                ]).stream()
            except Exception:
                stream = db.collection("employees").stream()

            for doc in stream:
                d = doc.to_dict() or {}
                d["_doc_id"] = doc.id
                coa = d.get("coa_account_id")
                if coa:
                    account_ids.add(coa)
                rows.append(d)

            balances = _batch_get_accounts_current_balances(account_ids)
            for r in rows:
                r["_balance"] = balances.get(r.get("coa_account_id", ""), None)
            self.loaded.emit(rows)
        except Exception as e:
            self.failed.emit(str(e))

# =============================
# Employee list module (CLASS NAME + UI preserved)
# =============================
class EmployeeModule(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data or {}
        self.setMinimumSize(1100, 650)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        QTimer.singleShot(0, self.load_employees)

    def _build_ui(self):
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("🧑‍💼 Employees"); title.setStyleSheet("font-size:20px; font-weight:700; padding:4px 2px;")
        header.addWidget(title); header.addStretch()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("Search name / code / designation / branch / phone / email…  (Ctrl+F)")
        self.search_box.textChanged.connect(self._apply_filter_to_current_tab)
        header.addWidget(self.search_box); root.addLayout(header)

        toolbar = QToolBar()
        act_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self); act_add.setShortcut("Ctrl+N"); act_add.triggered.connect(self.add_employee)
        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self); act_refresh.setShortcut("F5"); act_refresh.triggered.connect(self.load_employees)
        act_export = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export CSV", self); act_export.triggered.connect(self._export_csv_current_tab)
        toolbar.addAction(act_add); toolbar.addAction(act_refresh); toolbar.addSeparator(); toolbar.addAction(act_export)
        root.addWidget(toolbar)

        self.tabs = QTabWidget(); self.tabs.setTabPosition(QTabWidget.North); self.tabs.setDocumentMode(True)
        self.table_active = self._make_table(); w1=QWidget(); l1=QVBoxLayout(w1); l1.setContentsMargins(0,0,0,0); l1.addWidget(self.table_active); self.tabs.addTab(w1, "Active")
        self.table_inactive = self._make_table(); w2=QWidget(); l2=QVBoxLayout(w2); l2.setContentsMargins(0,0,0,0); l2.addWidget(self.table_inactive); self.tabs.addTab(w2, "Inactive")
        self.tabs.currentChanged.connect(self._apply_filter_to_current_tab); root.addWidget(self.tabs, stretch=1)

        footer = QHBoxLayout(); self.count_lbl = QLabel(""); self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        footer.addWidget(self.count_lbl); footer.addStretch(); root.addLayout(footer)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_box.setFocus())

    def _make_table(self):
        table = QTableWidget(0, 11)
        table.setHorizontalHeaderLabels([
            "Name", "Code", "Designation", "Branch", "Contact", "Email",
            "Date Joined", "Salary Type", "Base Salary", "Status", "Closing/Current Balance"
        ])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.cellDoubleClicked.connect(self._edit_employee_from_table)
        header = table.horizontalHeader(); header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 10): header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(10, QHeaderView.ResizeToContents)
        return table

    def _current_table(self):
        return self.table_active if self.tabs.currentIndex() == 0 else self.table_inactive

    # ---------- Data (FASTNESS applied; UI/logic preserved) ----------
    def load_employees(self):
        # 1) cache-first, instant paint (non-blocking)
        snap = _load_cache_json("employees_snapshot.json")
        if snap.get("rows"):
            self._paint_employees(snap["rows"])

        # 2) live refresh in background (with modal progress that auto-closes)
        self._progress = QProgressDialog("Loading employees…", None, 0, 0, self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setAutoClose(True)
        self._progress.show()

        self.table_active.setSortingEnabled(False)
        self.table_inactive.setSortingEnabled(False)

        self._loader = _EmployeesLoader()
        self._loader.loaded.connect(self._on_employees_loaded)
        self._loader.failed.connect(self._on_employees_failed)
        self._loader.start()

    def _on_employees_loaded(self, rows):
        try:
            self._paint_employees(rows)
            _save_cache_json("employees_snapshot.json", {"rows": rows})
        finally:
            try: self._progress.close()
            except Exception: pass
            self.table_active.setSortingEnabled(True)
            self.table_inactive.setSortingEnabled(True)

    def _on_employees_failed(self, msg):
        try: self._progress.close()
        except Exception: pass
        # If nothing is painted (no cache), inform the user. Otherwise keep whatever is visible.
        if not (self.table_active.rowCount() or self.table_inactive.rowCount()):
            QMessageBox.warning(self, "Load failed", msg)

    def _paint_employees(self, rows):
        for t in (self.table_active, self.table_inactive):
            t.clearContents(); t.setRowCount(0)

        count_a = 0
        count_i = 0

        for data in rows:
            name = data.get("name", "")
            code = data.get("employee_code", "")
            desg = data.get("designation", "")
            branch = data.get("branch", "")
            contact = data.get("contact", "")
            email = data.get("email", "")
            date_joined = data.get("date_joined", "")
            salary_type = data.get("salary_type", "")
            try:
                salary = float(data.get("salary", 0) or 0)
            except Exception:
                salary = 0.0

            # Existing status logic preserved: prefer explicit status, else active flag
            status_text = str(data.get("status") or ("Active" if bool(data.get("active", True)) else "Inactive"))
            active_flag = status_text.strip().lower() == "active"

            # --- Closing/Current Balance (signed) ---
            if "_balance" in data and data["_balance"] is not None:
                curr_num = float(data["_balance"] or 0.0)
            else:
                curr_num = 0.0
                try:
                    coa_id = data.get("coa_account_id")
                    if coa_id:
                        acc_snap = db.collection("accounts").document(coa_id).get()
                        if acc_snap.exists:
                            accd = acc_snap.to_dict() or {}
                            curr_num = float(accd.get("current_balance", 0.0) or 0.0)
                except Exception:
                    curr_num = 0.0

            bal_item = QTableWidgetItem(f"{curr_num:,.2f}")
            bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            bal_item.setData(Qt.UserRole, curr_num)

            cells = [
                QTableWidgetItem(name),
                QTableWidgetItem(code),
                QTableWidgetItem(desg),
                QTableWidgetItem(branch),
                QTableWidgetItem(contact),
                QTableWidgetItem(email),
                QTableWidgetItem(str(date_joined)),
                QTableWidgetItem(salary_type),
                QTableWidgetItem(f"{salary:,.2f}"),
                QTableWidgetItem(status_text),
                bal_item,
            ]
            cells[0].setData(Qt.UserRole, data.get("_doc_id"))
            cells[8].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            pill_brush = QBrush(QColor(50, 150, 50) if active_flag else QColor(200, 50, 50))
            cells[9].setBackground(pill_brush)
            cells[9].setData(Qt.BackgroundRole, pill_brush)
            cells[9].setForeground(QBrush(QColor(Qt.white)))

            t = self.table_active if active_flag else self.table_inactive
            r = t.rowCount()
            t.insertRow(r)
            for c, it in enumerate(cells):
                t.setItem(r, c, it)

            if active_flag: count_a += 1
            else: count_i += 1

        self._apply_filter_to_current_tab()
        # Update count for the currently visible tab
        total_visible = sum(not self._current_table().isRowHidden(r) for r in range(self._current_table().rowCount()))
        self.count_lbl.setText(
            f"Total: {total_visible} {'active' if self.tabs.currentIndex()==0 else 'inactive'} employees"
        )

    def _reapply_status_pills(self, table):
        col = 9
        for r in range(table.rowCount()):
            it = table.item(r, col)
            if not it: continue
            active = (it.text().strip().lower() == "active")
            pill_brush = QBrush(QColor(50,150,50) if active else QColor(200,50,50))
            it.setBackground(pill_brush); it.setData(Qt.BackgroundRole, pill_brush); it.setForeground(QBrush(QColor(Qt.white)))

    def _apply_filter_to_current_tab(self):
        table = self._current_table(); term = (self.search_box.text() or "").lower()
        was_sorting = table.isSortingEnabled(); table.setSortingEnabled(False)
        for r in range(table.rowCount()):
            row_text = " ".join((table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount()))
            table.setRowHidden(r, term not in row_text.lower())
        self._reapply_status_pills(table); table.setSortingEnabled(was_sorting)

    # ---------- Export (UNCHANGED) ----------
    def _export_csv_current_tab(self):
        if _is_admin_user(self.user_data):
            try:
                table = self._current_table()
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                if not os.path.isdir(desktop): desktop = tempfile.gettempdir()
                path = os.path.join(desktop, "employees_export.csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
                    w.writerow(headers)
                    for r in range(table.rowCount()):
                        if table.isRowHidden(r): continue
                        row = [(table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount())]
                        w.writerow(row)
                QMessageBox.information(self, "Exported", f"CSV saved to: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
        else:
            QMessageBox.warning(self, "Not Allowed", "You do not have permission to perform this action.")

    # ---------- Actions (UNCHANGED) ----------
    def add_employee(self):
        dlg = EmployeeDialog(self.user_data)
        if dlg.exec_(): self.load_employees()

    def _edit_employee_from_table(self, row, _col):
        table = self._current_table(); name_item = table.item(row, 0)
        if not name_item:
            QMessageBox.warning(self, "Not found", "Unable to locate selected employee."); return
        doc_id = name_item.data(Qt.UserRole)
        if not doc_id:
            QMessageBox.warning(self, "Missing", "Employee document not found."); return
        snap = db.collection("employees").document(doc_id).get()
        if not snap.exists:
            QMessageBox.warning(self, "Missing", "Employee document not found."); return
        dlg = EmployeeDialog(self.user_data, doc_id, snap.to_dict())
        if dlg.exec_(): self.load_employees()

# =============================
# EmployeeDialog (UNCHANGED business/UI; includes Auto-COA option for admins)
# =============================
class EmployeeDialog(QDialog):
    AUTO_VALUE = "__AUTO__"

    def __init__(self, user_data, doc_id=None, existing_data=None):
        super().__init__()
        self.user_data = user_data or {}
        self.doc_id = doc_id
        self.existing_data = existing_data or {}
        self.setWindowTitle("Edit Employee" if doc_id else "Add Employee")
        self.setMinimumWidth(560)
        self.setStyleSheet(APP_STYLE)
        self._init_ui()

        # For NEW: set next employee code as actual text (already handled in _init_ui), keep it.
        if not self.doc_id and not self.emp_code.text().strip():
            self.emp_code.setText(self._peek_next_employee_code())

        # Keep COA code preview in sync
        self._update_coa_code_display()

    def _init_ui(self):
        main = QVBoxLayout(self)
        subtitle = QLabel("Fill in the employee details. Fields marked * are required.")
        subtitle.setStyleSheet("color:#6b7280;")
        main.addWidget(subtitle)

        box = QGroupBox("Details")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        self.name = QLineEdit(self.existing_data.get("name", ""))
        self.emp_code = QLineEdit(self.existing_data.get("employee_code", ""))
        self.emp_code.setReadOnly(True)

        self.cnic = QLineEdit(self.existing_data.get("cnic", ""))
        self.cnic.setInputMask("00000-0000000-0;_")

        self.designation = QComboBox()
        self.designation.setEditable(True)
        self.designation.addItems(["Manager","Labour","Accountant","Sales","HR","Technician","Other"])
        if self.existing_data.get("designation"):
            idx = self.designation.findText(self.existing_data["designation"])
            if idx >= 0: self.designation.setCurrentIndex(idx)
            else: self.designation.setEditText(self.existing_data["designation"])

        # Branch (single-select) — will be required in save()
        self.branch = QComboBox()
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        for b in branches: self.branch.addItem(b)
        if self.existing_data.get("branch"):
            idx = self.branch.findText(self.existing_data["branch"])
            if idx >= 0: self.branch.setCurrentIndex(idx)

        self.contact = QLineEdit(self.existing_data.get("contact", ""))
        self.email = QLineEdit(self.existing_data.get("email", ""))

        self.date_joined = QDateEdit()
        self.date_joined.setCalendarPopup(True)
        if self.existing_data.get("date_joined"):
            try:
                y,m,d = map(int, str(self.existing_data["date_joined"]).split("-"))
                self.date_joined.setDate(QDate(y,m,d))
            except Exception:
                self.date_joined.setDate(QDate.currentDate())
        else:
            self.date_joined.setDate(QDate.currentDate())

        self.salary_type = QComboBox()
        self.salary_type.addItems(["Monthly","Weekly","Daily"])
        if self.existing_data.get("salary_type"):
            idx = self.salary_type.findText(self.existing_data["salary_type"])
            self.salary_type.setCurrentIndex(max(0, idx))
        self.salary = QLineEdit(str(self.existing_data.get("salary", 0)))

        # Opening advance: if editing, show placeholder "Managed from COA" and disable
        self.opening_advance = QLineEdit(str(self.existing_data.get("advance", 0)))
        if self.doc_id:
            self.opening_advance.clear()
            self.opening_advance.setPlaceholderText("Managed from COA")
            self.opening_advance.setDisabled(True)
            self.opening_advance.setToolTip("Opening advance is managed from COA / journals.")

        self.status = QComboBox()
        self.status.addItems(["Active","Inactive","Terminated"])
        if self.existing_data.get("status"):
            idx = self.status.findText(self.existing_data["status"])
            self.status.setCurrentIndex(max(0, idx))

        # --- COA selector with Auto option + read-only COA Code preview ---
        self.cmb_coa = None
        self._coa_cache = []  # (display, id)
        self.edt_coa_code = QLineEdit()
        self.edt_coa_code.setReadOnly(True)
        self.edt_coa_code.setStyleSheet("background:#f3f4f6;")
        self.edt_coa_code.setPlaceholderText("Will be auto-generated")

        if _is_admin_user(self.user_data):
            self.cmb_coa = QComboBox()
            self.cmb_coa.setEditable(True)
            self.cmb_coa.addItem("➕ Create New Account (auto)", self.AUTO_VALUE)
            self._populate_accounts_into_combo(self.cmb_coa, self.existing_data.get("coa_account_id"))
            self.cmb_coa.currentIndexChanged.connect(self._update_coa_code_display)
            form.addRow("COA Account", self.cmb_coa)
        else:
            form.addRow("COA Account", QLabel("Automatically create account (Admin can change)"))

        form.addRow("COA Code", self.edt_coa_code)

        # Layout
        form.addRow("Name *", self.name)
        form.addRow("Code *", self.emp_code)
        form.addRow("CNIC", self.cnic)
        form.addRow("Designation *", self.designation)
        form.addRow("Branch *", self.branch)
        form.addRow("Contact *", self.contact)
        form.addRow("Email", self.email)
        form.addRow("Date Joined *", self.date_joined)
        form.addRow("Salary Type *", self.salary_type)
        form.addRow("Base Salary *", self.salary)
        form.addRow("Opening Advance *", self.opening_advance)
        form.addRow("Status *", self.status)
        main.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setShortcut("Ctrl+S")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

    def _populate_accounts_into_combo(self, combo: QComboBox, current_id: str):
        try:
            accounts = db.collection("accounts").stream()
            cur_index = 0  # default to Auto at index 0
            idx = 1
            for acc_doc in accounts:
                acc = acc_doc.to_dict() or {}
                disp = _fmt_account_display(acc_doc.id, acc)
                combo.addItem(disp, acc_doc.id)
                self._coa_cache.append((disp, acc_doc.id))
                if current_id and acc_doc.id == current_id:
                    cur_index = idx
                idx += 1
            combo.setCurrentIndex(cur_index)
        except Exception as e:
            combo.addItem(f"(failed to load accounts: {e})", "")

    # ---------- Logic helpers (same as before) ----------
    def _peek_next_account_code(self, acc_type: str = "Liability") -> str:
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
            if self.cmb_coa is not None:
                sel = self.cmb_coa.currentData()
                if sel and sel != self.AUTO_VALUE:
                    snap = db.collection("accounts").document(sel).get()
                    if snap.exists:
                        acc = snap.to_dict() or {}
                        self.edt_coa_code.setText(str(acc.get("code", "")))
                        return
                    self.edt_coa_code.setText("")
                    return
                if not self.doc_id:
                    self.edt_coa_code.setText(self._peek_next_account_code("Liability"))
                else:
                    self.edt_coa_code.setText("")
                return

            current_id = self.existing_data.get("coa_account_id")
            if current_id:
                snap = db.collection("accounts").document(current_id).get()
                if snap.exists:
                    acc = snap.to_dict() or {}
                    self.edt_coa_code.setText(str(acc.get("code", "")))
                    return
                self.edt_coa_code.setText("")
                return

            if not self.doc_id:
                self.edt_coa_code.setText(self._peek_next_account_code("Liability"))
            else:
                self.edt_coa_code.setText("")
        except Exception:
            self.edt_coa_code.setText("")

    def _peek_next_employee_code(self):
        try:
            snap = db.collection("meta").document("employee_code_counter").get()
            data = snap.to_dict() or {}
            next_n = int(data.get("code", 0)) + 1
            return f"EMP-{str(next_n).zfill(3)}"
        except Exception:
            try:
                n = len(list(db.collection("employees").stream())) + 1
            except Exception:
                n = 1
            return f"EMP-{str(n).zfill(3)}"

    def _next_employee_code(self):
        counter_ref = db.collection("meta").document("employee_code_counter")
        transaction = firestore.client().transaction()
        @firestore.transactional
        def _inc(trans):
            snap = counter_ref.get(transaction=trans)
            data = snap.to_dict() or {}
            last = int(data.get("code", 0))
            new = last + 1
            trans.set(counter_ref, {"code": new}, merge=True)
            return new
        try:
            n = _inc(transaction)
        except Exception:
            n = len(list(db.collection("employees").stream())) + 1
        return f"EMP-{str(n).zfill(3)}"

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

    def _ensure_parent_account(self, name, acc_type, slug_value, branches_list):
        existing = db.collection("accounts").where("slug", "==", slug_value).limit(1).get()
        if existing: return existing[0].id
        code = self._generate_code_once(acc_type)
        parent_doc = {
            "name": name, "slug": slug_value, "type": acc_type, "code": code,
            "parent": None, "branch": branches_list, "description": f"System-generated parent for {name.lower()}",
            "active": True, "is_posting": False, "current_balance": 0.0
        }
        ref = db.collection("accounts").document(); ref.set(parent_doc); return ref.id

    def _create_employee_coa(self, emp_name, branches):
        if isinstance(branches, str) or branches is None:
            branches = [branches] if branches else []
        parent_id = self._ensure_parent_account("Employees Payables", "Liability", "employees_payables_parent", branches)
        code = self._generate_code_once("Liability")
        slug = re.sub(r"[^a-z0-9]+", "_", (emp_name or "").lower()).strip("_")
        child = {
            "name": emp_name, "slug": f"emp_{slug}", "type": "Liability", "code": code,
            "parent": parent_id, "branch": branches, "description": f"Auto-generated for employee {emp_name}",
            "active": True, "is_posting": True, "opening_balance": None, "current_balance": 0.0
        }
        ref = db.collection("accounts").document(); ref.set(child); return ref.id, child["name"]

    def _post_opening_advance_je(self, employee_account_id, employee_name, amount):
        try:
            amount = float(amount or 0)
            if amount <= 0:
                return

            eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if eq_q:
                equity_id = eq_q[0].id
                equity_name = (eq_q[0].to_dict() or {}).get("name", "System Offset Account")
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
                    "current_balance": 0.0
                }
                ref = db.collection("accounts").document()
                ref.set(equity_doc)
                equity_id = ref.id
                equity_name = "System Offset Account"

            emp_pre = 0.0
            eq_pre  = 0.0

            debit_line  = {
                "account_id": employee_account_id, "account_name": employee_name,
                "debit": amount, "credit": 0, "balance_before": emp_pre
            }
            credit_line = {
                "account_id": equity_id, "account_name": equity_name,
                "debit": 0, "credit": amount, "balance_before": eq_pre
            }

            now_server = firestore.SERVER_TIMESTAMP
            branch_val = self.user_data.get("branch")
            branch_val = (branch_val[0] if isinstance(branch_val, list) and branch_val else branch_val) or "-"
            je = {
                "date": now_server,
                "created_at": now_server,
                "created_by": self.user_data.get("email", "system"),
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
                "purpose": "Adjustment",
                "branch": branch_val,
                "description": f"Opening advance for {employee_name}",
                "lines": [debit_line, credit_line],
                "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
                "meta": {"kind": "opening_balance", "subtype": "opening_advance", "assume_prev_zero": True}
            }
            db.collection("journal_entries").document().set(je)

            db.collection("accounts").document(employee_account_id).update({
                "current_balance": firestore.Increment(-amount),
                "opening_balance": {"amount": amount, "type": "debit"}
            })

        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post opening advance JE: {e}")

    # ---------- Save (UNCHANGED business rules) ----------
    def save(self):
        name = self.name.text().strip()
        emp_code = self.emp_code.text().strip()
        designation = self.designation.currentText().strip()
        branch = self.branch.currentText().strip()
        contact = self.contact.text().strip()
        date_joined = self.date_joined.date().toString("yyyy-MM-dd")
        salary_type = self.salary_type.currentText().strip()
        salary_text = (self.salary.text() or "").replace(",", "").strip()
        status = self.status.currentText().strip()

        # Collect missing requireds (kept same behavior)
        missing = []
        if not name: missing.append("Name")
        if not emp_code: missing.append("Code")
        if not designation: missing.append("Designation")
        if not branch: missing.append("Branch")
        if not contact: missing.append("Contact")
        if not date_joined: missing.append("Date Joined")
        if not salary_type: missing.append("Salary Type")
        if not salary_text: missing.append("Base Salary")
        if not status: missing.append("Status")
        if missing:
            QMessageBox.warning(self, "Missing fields", "Please provide: " + ", ".join(missing)); return

        try:
            salary_val = float(salary_text)
        except Exception:
            QMessageBox.warning(self, "Invalid salary", "Base Salary must be a number."); return

        # Determine COA selection (admin dropdown vs auto)
        selected_account_id = None
        if _is_admin_user(self.user_data) and self.cmb_coa is not None:
            sel = self.cmb_coa.currentData()
            if sel and sel != self.AUTO_VALUE:
                selected_account_id = sel

        branches = branch if branch else None

        if not self.doc_id:
            # NEW employee
            if not emp_code:
                emp_code = self._next_employee_code()

            coa_id = selected_account_id
            coa_name = None
            if not coa_id:
                # auto-create employee liability account
                coa_id, coa_name = self._create_employee_coa(name, [branches] if branches else [])

            doc = {
                "name": name, "employee_code": emp_code, "designation": designation, "branch": branch,
                "contact": contact, "email": self.email.text().strip(), "date_joined": date_joined,
                "salary_type": salary_type, "salary": salary_val,
                "status": status, "active": (status.lower() == "active"),
                "coa_account_id": coa_id
            }
            ref = db.collection("employees").document()
            ref.set(doc)

            # Opening advance (if any) → create JE + update account balances
            try:
                adv_val = float((self.opening_advance.text() or "0").replace(",", "").strip() or 0)
            except Exception:
                adv_val = 0.0
            if adv_val > 0 and coa_id:
                self._post_opening_advance_je(coa_id, name, adv_val)

            QMessageBox.information(self, "Saved", "Employee created successfully.")
            self.accept()
            return

        # EDIT existing
        update = {
            "name": name, "designation": designation, "branch": branch,
            "contact": contact, "email": self.email.text().strip(), "date_joined": date_joined,
            "salary_type": salary_type, "salary": salary_val,
            "status": status, "active": (status.lower() == "active"),
        }

        # Allow admin to relink COA if a specific account picked
        if selected_account_id:
            update["coa_account_id"] = selected_account_id

        # Persist
        try:
            # Need the doc id → stored on the row when editing; caller passes existing_data on edit
            doc_id = self.existing_data.get("_doc_id")
            # Fallback: try to look up by employee_code if missing
            if not doc_id:
                q = db.collection("employees").where("employee_code", "==", emp_code).limit(1).get()
                if q: doc_id = q[0].id
            if not doc_id:
                QMessageBox.critical(self, "Update failed", "Could not determine employee record id."); return
            db.collection("employees").document(doc_id).set(update, merge=True)
            QMessageBox.information(self, "Updated", "Employee updated successfully.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Update failed", str(e))
