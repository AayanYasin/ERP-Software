# =============================
# employee_master_AUTOCOA.py — COA: add "Automatically create account" option (admin may pick specific)
# =============================
# Key points
# - In the Add/Edit dialog, the COA row now has a first option: "Automatically create account".
# - On create, choosing Auto will generate a Liability child account under Employees Payables (same logic as before).
# - Only Admins can choose a specific existing account from the dropdown. Non-admins see a read-only note that the
#   account will be auto-created; they cannot change it.
# - Keeps the Closing/Current Balance column in the list, opening-advance JE, atomic employee-code counter, etc.
#
# Drop-in compatible with employee_master_MERGED_BALANCE variant.

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QDialog, QFormLayout, QComboBox, QDialogButtonBox, QMessageBox, QHeaderView,
    QAbstractItemView, QToolBar, QAction, QStyle, QProgressDialog, QGroupBox,
    QShortcut, QTabWidget, QDateEdit
)
from PyQt5.QtCore import Qt, QTimer, QDate
from PyQt5.QtGui import QKeySequence, QColor, QBrush

from firebase.config import db
from firebase_admin import firestore

import uuid, datetime, re, os, csv, tempfile

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
# Employee list module
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

    # ---------- Data ----------
    def load_employees(self):
        progress = QProgressDialog("Loading employees…", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()
        try:
            self.table_active.setSortingEnabled(False)
            self.table_inactive.setSortingEnabled(False)
            self.table_active.setRowCount(0)
            self.table_inactive.setRowCount(0)

            count_a, count_i = 0, 0
            for doc in db.collection("employees").stream():
                data = doc.to_dict() or {}

                name = data.get("name", "")
                code = data.get("employee_code", "")
                desg = data.get("designation", "")
                branch = data.get("branch", "")
                contact = data.get("contact", "")
                email = data.get("email", "")
                date_joined = data.get("date_joined", "")
                salary_type = data.get("salary_type", "")
                salary = float(data.get("salary", 0) or 0)

                active_flag = bool(data.get("active", True))
                status = "Active" if active_flag else "Inactive"

                # --- Closing/Current Balance (signed) ---
                bal_item = QTableWidgetItem("-")
                try:
                    curr = 0.0
                    coa_id = data.get("coa_account_id")
                    if coa_id:
                        acc_snap = db.collection("accounts").document(coa_id).get()
                        if acc_snap.exists:
                            accd = acc_snap.to_dict() or {}
                            curr = float(accd.get("current_balance", 0.0) or 0.0)

                    # Show the raw signed value (e.g., -8,000.00). No DR/CR, no abs().
                    bal_item = QTableWidgetItem(f"{curr:,.2f}")
                    bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    # Keep the signed number for proper numeric sorting.
                    bal_item.setData(Qt.UserRole, curr)
                except Exception:
                    bal_item = QTableWidgetItem("-")

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
                    QTableWidgetItem(status),
                    bal_item,
                ]
                # stash doc id on the name cell
                cells[0].setData(Qt.UserRole, doc.id)
                # align salary
                cells[8].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # status pill styling
                pill_brush = QBrush(QColor(50, 150, 50) if active_flag else QColor(200, 50, 50))
                cells[9].setBackground(pill_brush)
                cells[9].setData(Qt.BackgroundRole, pill_brush)
                cells[9].setForeground(QBrush(QColor(Qt.white)))

                # insert row
                t = self.table_active if active_flag else self.table_inactive
                r = t.rowCount()
                t.insertRow(r)
                for c, it in enumerate(cells):
                    t.setItem(r, c, it)

                if active_flag:
                    count_a += 1
                else:
                    count_i += 1

            self._apply_filter_to_current_tab()
            self.count_lbl.setText(
                f"Total: {count_a if self.tabs.currentIndex()==0 else count_i} "
                f"{'active' if self.tabs.currentIndex()==0 else 'inactive'} employees"
            )
        finally:
            progress.close()
            self.table_active.setSortingEnabled(True)
            self.table_inactive.setSortingEnabled(True)


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

    # ---------- Export ----------
    def _export_csv_current_tab(self):
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

    # ---------- Actions ----------
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
# EmployeeDialog with Auto-COA option
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
            self.cmb_coa.addItem("Automatically create account", self.AUTO_VALUE)
            self._populate_accounts_into_combo(self.cmb_coa, self.existing_data.get("coa_account_id"))
            self.cmb_coa.currentIndexChanged.connect(self._update_coa_code_display)
            form.addRow("COA Account", self.cmb_coa)
        else:
            form.addRow("COA Account", QLabel("Automatically create account (Admin can change)"))

        # Read-only COA Code row (actual code if chosen; predicted next code if auto)
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
        """
        Best-effort, non-writing prediction of the next COA code for a given account type.
        Employees create Liability accounts under Employees Payables.
        """
        try:
            prefix = ACCOUNT_TYPE_PREFIX.get(acc_type, "9")
            counter_ref = db.collection("meta").document("account_code_counters")
            snap = counter_ref.get()
            data = snap.to_dict() or {}
            last = data.get(acc_type)
            if not last:
                # Fallback: scan accounts of this type to infer max
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
        """
        Populate the read-only COA Code field:
        - If a specific existing account is selected → show its code.
        - If 'Automatically create' on NEW → show predicted next Liability code.
        - If editing with 'Automatically create' → leave blank (no auto on edit).
        - For non-admins: show existing code if linked; otherwise predict on NEW.
        """
        try:
            # Admin path (dropdown present)
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
                # Auto selected
                if not self.doc_id:
                    self.edt_coa_code.setText(self._peek_next_account_code("Liability"))
                else:
                    self.edt_coa_code.setText("")
                return

            # Non-admin: use existing linked account if any, otherwise predict on NEW
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

            # 1) Locate or create the Equity account used for openings
            eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if eq_q:
                equity_id = eq_q[0].id
                equity_name = (eq_q[0].to_dict() or {}).get("name", "Opening Balances Equity")
            else:
                code = self._generate_code_once("Equity")
                branch_list = self.user_data.get("branch", [])
                if isinstance(branch_list, str):
                    branch_list = [branch_list]
                equity_doc = {
                    "name": "Opening Balances Equity",
                    "slug": "opening_balances_equity",
                    "type": "Equity",
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
                equity_name = "Opening Balances Equity"

            # 2) FORCE the 'previous balance' snapshot to ZERO for both lines (JE UI only)
            emp_pre = 0.0
            eq_pre  = 0.0

            # 3) Opening ADVANCE on a Liability = DEBIT the employee (reduces payable), CREDIT equity
            debit_line  = {
                "account_id": employee_account_id, "account_name": employee_name,
                "debit": amount, "credit": 0, "balance_before": emp_pre
            }
            credit_line = {
                "account_id": equity_id, "account_name": equity_name,
                "debit": 0, "credit": amount, "balance_before": eq_pre
            }

            # 4) Create JE (mark we assumed prev=0)
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

            # 5) Keep your existing behavior: bump cached current_balance and store opening_balance
            #    For Liability: a DEBIT means negative movement (reduces payable).
            db.collection("accounts").document(employee_account_id).update({
                "current_balance": firestore.Increment(-amount),
                "opening_balance": {"amount": amount, "type": "debit"}
            })

        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post opening advance JE: {e}")


    # ---------- Save ----------
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

        # Collect missing requireds
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

        # Opening Advance is required only on create (since in edit it's managed from COA)
        adv_required = not self.doc_id
        adv_text = (self.opening_advance.text() or "").strip()
        if adv_required and not adv_text:
            missing.append("Opening Advance")

        if missing:
            QMessageBox.warning(self, "Missing Fields", "Please fill: " + ", ".join(missing))
            return

        # Convert salary safely
        try:
            salary_val = float(salary_text)
        except Exception:
            QMessageBox.warning(self, "Invalid Salary", "Base Salary must be a number.")
            return

        payload = {
            "name": name,
            "designation": designation,
            "branch": branch,
            "contact": contact,
            "email": self.email.text().strip(),
            "date_joined": date_joined,
            "salary_type": salary_type,
            "salary": salary_val,
            "status": status,
            "active": (status == "Active"),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        try:
            if self.doc_id:
                # Edit existing
                if _is_admin_user(self.user_data) and self.cmb_coa is not None:
                    sel = self.cmb_coa.currentData()
                    if sel and sel != self.AUTO_VALUE:
                        payload["coa_account_id"] = sel
                db.collection("employees").document(self.doc_id).set(payload, merge=True)
                self.accept()
            else:
                # Create new
                emp_code = self._next_employee_code()
                payload.update({
                    "employee_code": emp_code,
                    "created_at": firestore.SERVER_TIMESTAMP
                })

                branches = self.user_data.get("branch", [])
                if isinstance(branches, str): branches = [branches] if branches else []

                chosen_id = None
                if _is_admin_user(self.user_data) and self.cmb_coa is not None:
                    sel = self.cmb_coa.currentData()
                    if sel and sel != self.AUTO_VALUE:
                        chosen_id = sel

                if chosen_id:
                    coa_id, coa_name = chosen_id, name
                else:
                    coa_id, coa_name = self._create_employee_coa(name, branches)
                payload["coa_account_id"] = coa_id

                emp_ref = db.collection("employees").document()
                emp_ref.set(payload)

                try:
                    adv_amount = float(adv_text or 0)
                except Exception:
                    adv_amount = 0
                if adv_amount > 0:
                    self._post_opening_advance_je(coa_id, coa_name, adv_amount)
                self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
