# =============================
# Employee Master (final w/ read-only code + styled calendar)
# - Code field is read-only and shows the next assignable code (preview)
# - Actual code assigned atomically on Save
# - QDateEdit styled to match QLineEdit/QComboBox
# =============================

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QDialogButtonBox, QMessageBox,
    QHeaderView, QAbstractItemView, QToolBar, QAction, QStyle, QProgressDialog,
    QGroupBox, QShortcut, QTabWidget, QDateEdit
)
from PyQt5.QtCore import Qt, QTimer, QDate
from PyQt5.QtGui import QKeySequence, QColor
from firebase.config import db
from firebase_admin import firestore
import uuid, datetime, re, os, csv, tempfile

APP_STYLE = """
QWidget { font-size: 14px; }
QPushButton { background:#2d6cdf; color:#fff; border:none; padding:8px 14px; border-radius:8px; }
QPushButton:hover { background:#2458b2; }
QPushButton:disabled { background:#a9b7d1; }
QGroupBox { border:1px solid #e3e7ef; border-radius:10px; margin-top:16px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#4a5568; }

/* Inputs match look for QLineEdit, QComboBox, and QDateEdit */
QLineEdit, QComboBox, QDateEdit {
  border:1px solid #d5dbe7; border-radius:8px; padding:6px 8px; background:#fff;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border-color:#2d6cdf; }

/* Also style the underlying spinbox part of QDateEdit for consistency */
QAbstractSpinBox { border:1px solid transparent; padding:0; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width:0; height:0; }
QDateEdit::drop-down { width:18px; }

/* Table */
QTableWidget { gridline-color:#e6e9f2; }
QHeaderView::section { background:#f7f9fc; padding:6px; border:none; border-bottom:1px solid #e6e9f2; }
"""

# -----------------------------
# EmployeeModule (List + actions)
# -----------------------------
class EmployeeModule(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setMinimumSize(1100, 650)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        QTimer.singleShot(0, self.load_employees)

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("🧑‍💼 Employees")
        title.setStyleSheet("font-size:20px; font-weight:700; padding:4px 2px;")
        header.addWidget(title)
        header.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search name / code / designation / branch / phone / email…  (Ctrl+F)")
        self.search_box.textChanged.connect(self._apply_filter_to_current_tab)
        header.addWidget(self.search_box)
        root.addLayout(header)

        toolbar = QToolBar()
        act_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self)
        act_add.setShortcut("Ctrl+N")
        act_add.triggered.connect(self.add_employee)
        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.load_employees)
        act_export = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export CSV", self)
        act_export.triggered.connect(self._export_csv_current_tab)
        toolbar.addAction(act_add); toolbar.addAction(act_refresh); toolbar.addSeparator(); toolbar.addAction(act_export)
        root.addWidget(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North); self.tabs.setDocumentMode(True)

        self.table_active = self._make_table()
        c1 = QWidget(); l1 = QVBoxLayout(c1); l1.setContentsMargins(0,0,0,0); l1.addWidget(self.table_active)
        self.tabs.addTab(c1, "Active")

        self.table_inactive = self._make_table()
        c2 = QWidget(); l2 = QVBoxLayout(c2); l2.setContentsMargins(0,0,0,0); l2.addWidget(self.table_inactive)
        self.tabs.addTab(c2, "Inactive")

        self.tabs.currentChanged.connect(self._apply_filter_to_current_tab)
        root.addWidget(self.tabs, stretch=1)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_box.setFocus())

        footer = QHBoxLayout()
        self.count_lbl = QLabel(""); self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        footer.addWidget(self.count_lbl); footer.addStretch()
        root.addLayout(footer)

    def _make_table(self):
        table = QTableWidget(0, 10)
        table.setHorizontalHeaderLabels([
            "Name", "Code", "Designation", "Branch",
            "Contact", "Email", "Date Joined", "Salary Type", "Base Salary", "Status"
        ])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.cellDoubleClicked.connect(self._edit_employee_from_table)
        table.setStyleSheet(self.styleSheet() + "\nQTableWidget::item { padding: 6px; }")

        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Name
        for c in range(1, 9):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)
        return table

    def _current_table(self):
        return self.table_active if self.tabs.currentIndex() == 0 else self.table_inactive

    # ---------- Data ----------
    def load_employees(self):
        progress = QProgressDialog("Loading employees…", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal); progress.setAutoClose(True); progress.show()
        try:
            self.table_active.setRowCount(0); self.table_inactive.setRowCount(0)
            count_a, count_i = 0, 0

            for doc in db.collection("employees").stream():
                data = doc.to_dict() or {}
                name = data.get("name", ""); code = data.get("employee_code", "")
                desg = data.get("designation", ""); branch = data.get("branch", "")
                contact = data.get("contact", ""); email = data.get("email", "")
                date_joined = data.get("date_joined", "")
                salary_type = data.get("salary_type", ""); salary = float(data.get("salary", 0) or 0)
                active_flag = bool(data.get("active", True))  # default to True if missing
                status = "Active" if active_flag else "Inactive"

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
                    QTableWidgetItem(status)
                ]
                cells[0].setData(Qt.UserRole, doc.id)
                cells[8].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                green_bg = QColor(50,150,50); red_bg = QColor(200,50,50)
                cells[9].setBackground(green_bg if active_flag else red_bg)
                cells[9].setForeground(Qt.white)

                t = self.table_active if active_flag else self.table_inactive
                r = t.rowCount(); t.insertRow(r)
                for c, it in enumerate(cells): t.setItem(r, c, it)
                if active_flag: count_a += 1
                else: count_i += 1

            self._apply_filter_to_current_tab()
            self.count_lbl.setText(
                f"Total: {count_a if self.tabs.currentIndex()==0 else count_i} "
                f"{'active' if self.tabs.currentIndex()==0 else 'inactive'} employees"
            )
        finally:
            progress.close()

    def _apply_filter_to_current_tab(self):
        table = self._current_table()
        term = (self.search_box.text() or "").lower()
        for r in range(table.rowCount()):
            row_text = " ".join((table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount()))
            table.setRowHidden(r, term not in row_text.lower())

    def _table_to_export(self):
        return self._current_table()

    def _export_csv_current_tab(self):
        try:
            table = self._table_to_export()
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
        table = self._current_table()
        name_item = table.item(row, 0)
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


# -----------------------------
# EmployeeDialog
# -----------------------------
class EmployeeDialog(QDialog):
    def __init__(self, user_data, doc_id=None, existing_data=None):
        super().__init__()
        self.user_data = user_data
        self.doc_id = doc_id
        self.existing_data = existing_data or {}
        self.setWindowTitle("Edit Employee" if doc_id else "Add Employee")
        self.setMinimumWidth(540)
        self.setStyleSheet(APP_STYLE)
        self._init_ui()

        # NEW: For new employee, show preview code (read-only) without incrementing the counter yet
        if not self.doc_id and not self.emp_code.text().strip():
            self.emp_code.setText(self._peek_next_employee_code())

    def _init_ui(self):
        main = QVBoxLayout(self)

        subtitle = QLabel("Fill in the employee details. Fields marked * are required.")
        subtitle.setStyleSheet("color:#6b7280;")
        main.addWidget(subtitle)

        box = QGroupBox("Details")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        # Name*
        self.name = QLineEdit(self.existing_data.get("name", ""))

        # Code* (always read-only; generated preview, final assigned on save)
        self.emp_code = QLineEdit(self.existing_data.get("employee_code", ""))
        self.emp_code.setReadOnly(True)

        # CNIC with auto dashes (XXXXX-XXXXXXX-X)
        self.cnic = QLineEdit(self.existing_data.get("cnic", ""))
        self.cnic.setInputMask("00000-0000000-0;_")

        # Designation* dropdown (editable)
        self.designation = QComboBox()
        self.designation.setEditable(True)
        self.designation.addItems(["Manager", "Labour", "Accountant", "Sales", "HR", "Technician", "Other"])
        if self.existing_data.get("designation"):
            idx = self.designation.findText(self.existing_data["designation"])
            if idx >= 0: self.designation.setCurrentIndex(idx)
            else: self.designation.setEditText(self.existing_data["designation"])

        # Branch* dropdown from user_data["branch"]
        self.branch = QComboBox()
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        for b in (branches or []): self.branch.addItem(b)
        if self.existing_data.get("branch"):
            idx = self.branch.findText(self.existing_data["branch"])
            if idx >= 0: self.branch.setCurrentIndex(idx)

        # Contact*
        self.contact = QLineEdit(self.existing_data.get("contact", ""))

        # Email
        self.email = QLineEdit(self.existing_data.get("email", ""))

        # Date Joined* (Calendar popup, styled)
        self.date_joined = QDateEdit()
        self.date_joined.setCalendarPopup(True)
        if self.existing_data.get("date_joined"):
            try:
                y, m, d = map(int, str(self.existing_data["date_joined"]).split("-"))
                self.date_joined.setDate(QDate(y, m, d))
            except Exception:
                self.date_joined.setDate(QDate.currentDate())
        else:
            self.date_joined.setDate(QDate.currentDate())

        # Salary Type*
        self.salary_type = QComboBox()
        self.salary_type.addItems(["Monthly", "Weekly", "Daily"])
        if self.existing_data.get("salary_type"):
            idx = self.salary_type.findText(self.existing_data["salary_type"])
            self.salary_type.setCurrentIndex(max(0, idx))

        # Base Salary*
        self.salary = QLineEdit(str(self.existing_data.get("salary", 0)))

        # Opening Advance*  (on create only; treated as CREDIT to employee)
        self.opening_advance = QLineEdit(str(self.existing_data.get("advance", 0)))
        if self.doc_id:
            self.opening_advance.setDisabled(True)
            self.opening_advance.setToolTip("Opening advance can only be set when creating an employee.")

        # Status*
        self.status = QComboBox()
        self.status.addItems(["Active", "Inactive", "Terminated"])
        if self.existing_data.get("status"):
            idx = self.status.findText(self.existing_data["status"]); self.status.setCurrentIndex(max(0, idx))

        # Layout per your order
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

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setShortcut("Ctrl+S")
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

    # ---------- Helpers / logic ----------
    def _normalize_drcr(self, val):
        v = (val or "").strip().lower()
        if v in ("dr", "debit"): return "debit"
        if v in ("cr", "credit"): return "credit"
        return "debit"

    def _peek_next_employee_code(self):
        """Preview next EMP-### without incrementing (read-only display)."""
        try:
            snap = db.collection("meta").document("employee_code_counter").get()
            data = snap.to_dict() or {}
            next_n = int(data.get("code", 0)) + 1
            return f"EMP-{str(next_n).zfill(3)}"
        except Exception:
            # fallback: count + 1
            try:
                n = len(list(db.collection("employees").stream())) + 1
            except Exception:
                n = 1
            return f"EMP-{str(n).zfill(3)}"

    def _next_employee_code(self):
        """EMP-### using a counter doc (atomic assignment on save)."""
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

    def _slugify(self, text: str) -> str:
        s = (text or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s.strip("_")

    def _gen_account_code(self, acc_type: str):
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
                    try:
                        codes.append(int(str(d.to_dict().get("code", "0"))))
                    except Exception:
                        pass
                last = max(codes) if codes else 3000
            new_code = int(last) + 1
            data[acc_type] = new_code
            trans.set(counter_ref, data, merge=True)
            return str(new_code)

        return increment_code(transaction)

    def _ensure_parent_account(self, name, acc_type, slug_value, branches_list):
        existing = db.collection("accounts").where("slug", "==", slug_value).limit(1).get()
        if existing: return existing[0].id
        code = self._gen_account_code(acc_type)
        doc = {
            "name": name, "slug": slug_value, "type": acc_type, "code": code, "parent": None, "branch": branches_list,
            "description": f"System-generated parent for {name.lower()}",
            "active": True, "is_posting": False, "current_balance": 0.0
        }
        ref = db.collection("accounts").document(); ref.set(doc); return ref.id

    def _post_opening_je(self, account_id, account_name, amount, drcr):
        try:
            amt = float(amount or 0.0)
            if amt <= 0: return
            drcr = self._normalize_drcr(drcr)

            # Opening Balances Equity
            eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if eq_q:
                eq_id = eq_q[0].id; eq_name = eq_q[0].to_dict().get("name", "Opening Balances Equity")
            else:
                code = self._gen_account_code("Equity")
                branches = self.user_data.get("branch", [])
                if isinstance(branches, str): branches = [branches] if branches else []
                eq_doc = {
                    "name":"Opening Balances Equity","slug":"opening_balances_equity","type":"Equity","code":code,
                    "parent":None,"branch":branches,"description":"System-generated equity for openings",
                    "active":True,"is_posting":True,"opening_balance":None,"current_balance":0.0
                }
                ref = db.collection("accounts").document(); ref.set(eq_doc)
                eq_id = ref.id; eq_name = "Opening Balances Equity"

            # snapshots
            def bal(doc_id):
                try:
                    d = db.collection("accounts").document(doc_id).get().to_dict() or {}
                    return float(d.get("current_balance", 0.0) or 0.0)
                except Exception:
                    return 0.0
            a_pre = bal(account_id); e_pre = bal(eq_id)

            debit_line = {"account_id": account_id, "account_name": account_name, "debit": amt, "credit": 0, "balance_before": a_pre}
            credit_line = {"account_id": eq_id, "account_name": eq_name, "debit": 0, "credit": amt, "balance_before": e_pre}
            if drcr == "credit":
                debit_line, credit_line = credit_line, debit_line

            now_server = firestore.SERVER_TIMESTAMP
            branch_val = self.user_data.get("branch")
            if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
            if not branch_val: branch_val = "-"

            je = {
                "date": now_server, "created_at": now_server,
                "created_by": self.user_data.get("email", "system"),
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
                "purpose": "Adjustment", "branch": branch_val,
                "description": f"Opening advance for {account_name}",
                "lines": [debit_line, credit_line],
                "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
                "meta": {"kind": "opening_balance"}
            }
            db.collection("journal_entries").document().set(je)
        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post JE: {e}")

    def _create_employee_coa(self, name, employee_id, opening_amount, branches):
        # Employees under Liability parent
        if isinstance(branches, str) or branches is None:
            branches = [branches] if branches else []
        parent_id = self._ensure_parent_account("Employees", "Liability", "employees_parent", branches)

        account_code = self._gen_account_code("Liability")
        child_slug = self._slugify(name)
        ob_amount = float(opening_amount or 0.0)

        # Interpret Opening Advance as CREDIT to employee (company owes employee)
        drcr_norm = "credit"
        computed_balance = ob_amount  # Liability: credit positive

        coa_data = {
            "name": name, "slug": child_slug, "type": "Liability", "code": account_code, "parent": parent_id,
            "branch": branches, "description": f"Employee account for {name}", "active": True, "is_posting": True,
            "linked_employee_id": employee_id,
            "opening_balance": {"amount": ob_amount, "type": drcr_norm},
            "current_balance": 0.0
        }
        ref = db.collection("accounts").document()
        ref.set(coa_data)

        # Post opening JE vs Opening Balances Equity
        self._post_opening_je(ref.id, name, ob_amount, drcr_norm)

        if ob_amount > 0:
            db.collection("accounts").document(ref.id).update({"current_balance": float(computed_balance)})
        return ref.id

    def _validate_required(self):
        missing = []
        if not self.name.text().strip(): missing.append("Name")
        # Code is read-only; for new, a preview is inserted; for edit it exists.
        if not (self.designation.currentText().strip()): missing.append("Designation")
        if self.branch.currentText().strip() == "": missing.append("Branch")
        if not self.contact.text().strip(): missing.append("Contact")
        if not self.date_joined.date().isValid(): missing.append("Date Joined")
        if self.salary_type.currentText().strip() == "": missing.append("Salary Type")
        try: float(self.salary.text() or "0")
        except Exception: missing.append("Base Salary (number)")
        try: float(self.opening_advance.text() or "0")
        except Exception: missing.append("Opening Advance (number)")
        if missing:
            QMessageBox.warning(self, "Validation", "Please fill required fields: " + ", ".join(missing))
            return False
        return True

    def save(self):
        if not self._validate_required(): return

        # Assign actual employee code atomically if this is a new record
        if not self.doc_id:
            self.emp_code.setText(self._next_employee_code())

        name = self.name.text().strip()
        code = self.emp_code.text().strip()

        # branches from user_data (for CoA), and selected branch for employee record
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        selected_branch = self.branch.currentText().strip() or (branches[0] if branches else "")

        data = {
            "name": name,
            "employee_code": code,
            "cnic": self.cnic.text().strip(),
            "designation": self.designation.currentText().strip(),
            "branch": selected_branch,
            "contact": self.contact.text().strip(),
            "email": self.email.text().strip(),
            "date_joined": self.date_joined.date().toString("yyyy-MM-dd"),
            "active": (self.status.currentText().strip().lower() == "active"),
            "salary_type": self.salary_type.currentText(),
            "salary": float(self.salary.text() or "0"),
            "advance": float(self.opening_advance.text() or "0"),
            # backend-only placeholder for future
            "attendence_Link": self.existing_data.get("attendence_Link", ""),
            "created_at": self.existing_data.get("created_at") or datetime.datetime.now(),
        }

        if self.doc_id:
            db.collection("employees").document(self.doc_id).set(data, merge=True)
            self.accept()
        else:
            new_id = str(uuid.uuid4())
            # Create CoA posting account and post opening (credit)
            coa_id = self._create_employee_coa(
                name=name,
                employee_id=new_id,
                opening_amount=data["advance"],
                branches=branches
            )
            data["coa_account_id"] = coa_id

            db.collection("employees").document(new_id).set(data)
            self.accept()
