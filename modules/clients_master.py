# =============================
# Enhanced UI for clients_master.py (with tabs + desktop export + required fields)
# Drop-in replacement for PartyModule and PartyDialog with a modern, polished UI
# =============================

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QTextEdit, QListWidget, QListWidgetItem,
    QDialogButtonBox, QMessageBox, QHeaderView, QAbstractItemView, QToolBar, QAction, QStyle,
    QSizePolicy, QProgressDialog, QSplitter, QGroupBox, QGridLayout, QFrame, QShortcut, QTabWidget
)
from PyQt5.QtCore import Qt, QTimer, QSortFilterProxyModel, QRegExp
from PyQt5.QtGui import QIcon, QRegExpValidator, QKeySequence, QColor
from firebase.config import db
from firebase_admin import firestore
import uuid, datetime, re, os, csv, tempfile

ACCOUNT_TYPE_PREFIX = {
    "Asset": "1",
    "Liability": "2",
    "Equity": "3",
    "Income": "4",
    "Expense": "5"
}

APP_STYLE = """
/* Global */
QWidget { font-size: 14px; }

/* Buttons */
QPushButton {
    background: #2d6cdf; color: white; border: none; padding: 8px 14px; border-radius: 8px;
}
QPushButton:hover { background: #2458b2; }
QPushButton:disabled { background: #a9b7d1; }

/* Framed sections */
QGroupBox { border: 1px solid #e3e7ef; border-radius: 10px; margin-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #4a5568; }

/* Inputs */
QLineEdit, QComboBox, QTextEdit {
    border: 1px solid #d5dbe7; border-radius: 8px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #2d6cdf; }

/* Table */
QTableWidget { gridline-color: #e6e9f2; }
QHeaderView::section { background: #f7f9fc; padding: 6px; border: none; border-bottom: 1px solid #e6e9f2; }

/* Status pill look using background colors set in code */
"""

# -----------------------------
# PartyModule (List + actions)
# -----------------------------
class PartyModule(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setMinimumSize(1100, 650)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        QTimer.singleShot(0, self.load_parties)

    # UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Header row with title + search
        header = QHBoxLayout()
        title = QLabel("👥 Parties")
        title.setStyleSheet("font-size: 20px; font-weight: 700; padding: 4px 2px;")
        header.addWidget(title)
        header.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search name / contact / phone / branch…  (Ctrl+F)")
        self.search_box.textChanged.connect(self._apply_filter_to_current_tab)
        header.addWidget(self.search_box)
        root.addLayout(header)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(toolbar.iconSize())
        act_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self)
        act_add.setShortcut("Ctrl+N")
        act_add.triggered.connect(self.add_party)
        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.load_parties)
        act_export = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export CSV", self)
        act_export.triggered.connect(self._export_csv_current_tab)
        toolbar.addAction(act_add)
        toolbar.addAction(act_refresh)
        toolbar.addSeparator()
        toolbar.addAction(act_export)
        root.addWidget(toolbar)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)

        # Customers Table
        self.table_customers = self._make_table()
        cust_wrap = QWidget(); cust_lay = QVBoxLayout(cust_wrap); cust_lay.setContentsMargins(0,0,0,0)
        cust_lay.addWidget(self.table_customers)
        self.tabs.addTab(cust_wrap, "Customers")

        # Suppliers Table
        self.table_suppliers = self._make_table()
        supp_wrap = QWidget(); supp_lay = QVBoxLayout(supp_wrap); supp_lay.setContentsMargins(0,0,0,0)
        supp_lay.addWidget(self.table_suppliers)
        self.tabs.addTab(supp_wrap, "Suppliers")

        self.tabs.currentChanged.connect(self._apply_filter_to_current_tab)
        root.addWidget(self.tabs, stretch=1)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_box.setFocus())

        # Footer (row count)
        footer = QHBoxLayout()
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        footer.addWidget(self.count_lbl)
        footer.addStretch()
        root.addLayout(footer)

    def _make_table(self):
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["Name", "Type", "Contact", "Phone", "Branches", "Status", "Balance"])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.cellDoubleClicked.connect(self._edit_party_from_table)
        table.setStyleSheet(self.styleSheet() + "\nQTableWidget::item { padding: 6px; }")

        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 6):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        return table

    def _current_table(self):
        return self.table_customers if self.tabs.currentIndex() == 0 else self.table_suppliers

    # Data
    def load_parties(self):
        progress = QProgressDialog("Loading parties…", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        try:
            for t in (self.table_customers, self.table_suppliers):
                t.setRowCount(0)

            parties = db.collection("parties").stream()
            count_c, count_s = 0, 0

            for doc in parties:
                data = doc.to_dict() or {}
                ptype = (data.get("type") or "").strip()
                # prepare row contents once
                human_id = data.get("id", "")
                party_name = data.get("name", "")
                name_item = QTableWidgetItem(f"[{human_id}] - {party_name}")
                name_item.setData(Qt.UserRole, doc.id)

                type_item = QTableWidgetItem(ptype)
                contact_item = QTableWidgetItem(data.get("contact_person", ""))
                phone_item = QTableWidgetItem(data.get("phone", ""))
                branches_item = QTableWidgetItem(", ".join(data.get("branches", [])))

                status = "Active" if data.get("active", True) else "Inactive"
                status_item = QTableWidgetItem(status)
                # Subtle pill coloring
                green_bg = QColor(50, 150, 50)    # green
                red_bg   = QColor(200, 50, 50)     # red

                status_item.setBackground(green_bg if status == "Active" else red_bg)
                status_item.setForeground(Qt.white)

                # Balance from linked CoA
                balance_str = "-"
                try:
                    coa_id = data.get("coa_account_id")
                    if coa_id:
                        acc_snap = db.collection("accounts").document(coa_id).get()
                        if acc_snap.exists:
                            acc = acc_snap.to_dict() or {}
                            curr = float(acc.get("current_balance", 0.0) or 0.0)
                            a_type = (acc.get("type") or "Asset")
                            dr = (curr >= 0) if a_type in ["Asset", "Expense"] else (curr < 0)
                            balance_str = f"{abs(curr):,.2f} {'DR' if dr else 'CR'}"
                except Exception:
                    balance_str = "-"
                balance_item = QTableWidgetItem(balance_str)
                balance_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Decide which tables to populate
                goes_customers = ptype in ("Customer", "Both")
                goes_suppliers = ptype in ("Supplier", "Both")

                if goes_customers:
                    row = self.table_customers.rowCount()
                    self.table_customers.insertRow(row)
                    self.table_customers.setItem(row, 0, name_item.clone())
                    self.table_customers.setItem(row, 1, type_item.clone())
                    self.table_customers.setItem(row, 2, contact_item.clone())
                    self.table_customers.setItem(row, 3, phone_item.clone())
                    self.table_customers.setItem(row, 4, branches_item.clone())
                    self.table_customers.setItem(row, 5, status_item.clone())
                    self.table_customers.setItem(row, 6, balance_item.clone())
                    # Preserve doc id on the "name" cell
                    self.table_customers.item(row,0).setData(Qt.UserRole, doc.id)
                    count_c += 1

                if goes_suppliers:
                    row = self.table_suppliers.rowCount()
                    self.table_suppliers.insertRow(row)
                    self.table_suppliers.setItem(row, 0, name_item.clone())
                    self.table_suppliers.setItem(row, 1, type_item.clone())
                    self.table_suppliers.setItem(row, 2, contact_item.clone())
                    self.table_suppliers.setItem(row, 3, phone_item.clone())
                    self.table_suppliers.setItem(row, 4, branches_item.clone())
                    self.table_suppliers.setItem(row, 5, status_item.clone())
                    self.table_suppliers.setItem(row, 6, balance_item.clone())
                    self.table_suppliers.item(row,0).setData(Qt.UserRole, doc.id)
                    count_s += 1

            self._apply_filter_to_current_tab()
            # Footer count
            if self.tabs.currentIndex() == 0:
                self.count_lbl.setText(f"Total: {count_c} customers")
            else:
                self.count_lbl.setText(f"Total: {count_s} suppliers")
        finally:
            progress.close()

    def _apply_filter_to_current_tab(self):
        table = self._current_table()
        term = (self.search_box.text() or "").lower()
        for r in range(table.rowCount()):
            row_text = " ".join(
                (table.item(r, c).text() if table.item(r, c) else "")
                for c in range(table.columnCount())
            )
            table.setRowHidden(r, term not in row_text.lower())

    def _table_to_export(self):
        return self._current_table()

    def _export_csv_current_tab(self):
        try:
            table = self._table_to_export()
            # Prefer user's Desktop; fallback to temp
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
            QMessageBox.information(self, "Exported", f"CSV saved to: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # Actions
    def add_party(self):
        dialog = PartyDialog(self.user_data)
        if dialog.exec_():
            self.load_parties()

    def _edit_party_from_table(self, row, _col):
        table = self._current_table()
        name_item = table.item(row, 0)
        if not name_item:
            QMessageBox.warning(self, "Not found", "Unable to locate selected party.")
            return
        doc_id = name_item.data(Qt.UserRole)
        if not doc_id:
            # Fallback by human id if old rows
            cell_text = name_item.text() or ""
            guessed = cell_text.split("]")[0].replace("[", "").strip()
            try:
                match = list(db.collection("parties").where("id", "==", guessed).limit(1).stream())
                doc_id = match[0].id if match else None
            except Exception:
                doc_id = None
        if not doc_id:
            QMessageBox.warning(self, "Missing", "Party document not found.")
            return
        snap = db.collection("parties").document(doc_id).get()
        if not snap.exists:
            QMessageBox.warning(self, "Missing", "Party document not found.")
            return
        dialog = PartyDialog(self.user_data, doc_id, snap.to_dict())
        if dialog.exec_():
            self.load_parties()


# -----------------------------
# PartyDialog (nice form)
# -----------------------------
class PartyDialog(QDialog):
    def __init__(self, user_data, doc_id=None, existing_data=None):
        super().__init__()
        self.user_data = user_data
        self.doc_id = doc_id
        self.existing_data = existing_data or {}
        self.setWindowTitle("Edit Party" if doc_id else "Add Party")
        self.new_customer_id = None
        self.generated_code = None
        self.setMinimumWidth(540)
        self.setStyleSheet(APP_STYLE)
        self._init_ui()
        if not self.doc_id:
            self.fetch_next_code()

    def fetch_next_code(self):
        doc_ref = db.collection("meta").document("cust_supp")
        doc = doc_ref.get()
        current_code = 1
        if doc.exists:
            data = doc.to_dict()
            current_code = int(data.get("code", 1))
        self.generated_code = str(current_code).zfill(3)

    def _init_ui(self):
        main = QVBoxLayout(self)

        # Title
        subtitle = QLabel("Fill in the party details. Fields marked * are required.")
        subtitle.setStyleSheet("color:#6b7280;")
        main.addWidget(subtitle)

        # Form
        form_box = QGroupBox("Details")
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignRight)

        self.name = QLineEdit(self.existing_data.get("name", ""))
        self.name.setPlaceholderText("e.g., Ali Traders")

        self.contact = QLineEdit(self.existing_data.get("contact_person", ""))
        self.contact.setPlaceholderText("Contact person name")

        self.phone = QLineEdit(self.existing_data.get("phone", ""))
        self.phone.setPlaceholderText("03xx-xxxxxxx")
        self.phone.setMaxLength(20)

        self.email = QLineEdit(self.existing_data.get("email", ""))
        self.email.setPlaceholderText("Optional")

        self.address = QTextEdit(self.existing_data.get("address", ""))
        self.address.setFixedHeight(60)
        self.address.setPlaceholderText("Street, City…")

        self.gst = QLineEdit(self.existing_data.get("gst", ""))
        self.gst.setPlaceholderText("Optional")

        self.ntn = QLineEdit(self.existing_data.get("ntn", ""))
        self.ntn.setPlaceholderText("Optional")

        self.type = QComboBox()
        self.type.addItems(["Customer", "Supplier"])
        if self.existing_data.get("type"):
            idx = self.type.findText(self.existing_data["type"]);  self.type.setCurrentIndex(max(0, idx))

        self.branches = QListWidget()
        for b in self.user_data.get("branch", []):
            item = QListWidgetItem(b)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if b in self.existing_data.get("branches", []) else Qt.Unchecked)
            self.branches.addItem(item)

        # Opening balance only when adding new
        self.balance = QLineEdit(str(self.existing_data.get("opening_balance", 0)))
        self.balance.setPlaceholderText("0.00")
        self.balance_type = QComboBox(); self.balance_type.addItems(["DR", "CR"])
        if self.existing_data.get("opening_type") == "CR":
            self.balance_type.setCurrentIndex(1)
        ob_container = QWidget(); ob_layout = QHBoxLayout(ob_container); ob_layout.setContentsMargins(0,0,0,0)
        ob_layout.addWidget(self.balance); ob_layout.addWidget(self.balance_type)
        if self.doc_id:
            ob_container.setDisabled(True)
            self.balance.setToolTip("Opening balance can only be set when creating a party.")

        self.status = QComboBox(); self.status.addItems(["Active", "Inactive"])
        if not self.existing_data.get("active", True): self.status.setCurrentIndex(1)

        # NOTE: Mark all except Email, NTN, GST as important (*)
        form.addRow("Name *", self.name)
        form.addRow("Contact *", self.contact)
        form.addRow("Phone *", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Address *", self.address)
        form.addRow("GST", self.gst)
        form.addRow("NTN", self.ntn)
        form.addRow("Type *", self.type)
        form.addRow("Branches *", self.branches)
        form.addRow("Opening Balance *", ob_container)
        form.addRow("Status *", self.status)
        main.addWidget(form_box)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setShortcut("Ctrl+S")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

    # -------- Business Logic --------
    def _normalize_drcr(self, val):
        v = (val or "").strip().lower()
        if v in ("dr", "debit"): return "debit"
        if v in ("cr", "credit"): return "credit"
        return "debit"

    def post_opening_journal_entry(self, account_id, account_name, amount, drcr):
        try:
            if not amount or amount <= 0:
                return
            drcr = self._normalize_drcr(drcr)

            # Find or create Opening Balances Equity (by slug)
            equity_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if equity_q:
                equity_account_id = equity_q[0].id
                equity_account_name = equity_q[0].to_dict().get("name", "Opening Balances Equity")
            else:
                code = self.generate_code_once("Equity")
                branch_list = self.user_data.get("branch", [])
                if isinstance(branch_list, str): branch_list = [branch_list]
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
                ref = db.collection("accounts").document(); ref.set(equity_doc)
                equity_account_id = ref.id; equity_account_name = "Opening Balances Equity"

            # balance_before snapshots
            a_pre = 0.0; e_pre = 0.0
            try:
                a_doc = db.collection("accounts").document(account_id).get().to_dict() or {}
                a_pre = float(a_doc.get("current_balance", 0.0) or 0.0)
            except Exception: pass
            try:
                e_doc = db.collection("accounts").document(equity_account_id).get().to_dict() or {}
                e_pre = float(e_doc.get("current_balance", 0.0) or 0.0)
            except Exception: pass

            debit_line = {"account_id": account_id, "account_name": account_name, "debit": amount, "credit": 0, "balance_before": a_pre}
            credit_line = {"account_id": equity_account_id, "account_name": equity_account_name, "debit": 0, "credit": amount, "balance_before": e_pre}
            if drcr == "credit":
                debit_line, credit_line = credit_line, debit_line

            now_server = firestore.SERVER_TIMESTAMP
            branch_val = self.user_data.get("branch")
            if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
            if not branch_val: branch_val = "-"

            je = {
                "date": now_server,
                "created_at": now_server,
                "created_by": self.user_data.get("email", "system"),
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
                "purpose": "Adjustment",
                "branch": branch_val,
                "description": f"Opening balance for {account_name}",
                "lines": [debit_line, credit_line],
                "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
                "meta": {"kind": "opening_balance"}
            }
            db.collection("journal_entries").document().set(je)
        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post JE: {e}")

    def generate_code_once(self, acc_type):
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
                codes = [int(doc.to_dict().get("code", "0")) for doc in query if doc.to_dict().get("code", "").startswith(prefix)]
                last = max(codes) if codes else int(prefix + "000")
            new_code = last + 1
            data[acc_type] = new_code
            trans.set(counter_ref, data, merge=True)
            return str(new_code)
        return increment_code(transaction)

    def create_coa_account_for_party(self, name, type_, party_type, party_id, opening_balance, drcr, branches):
        def _slugify(text: str) -> str:
            s = (text or "").strip().lower(); s = re.sub(r"[^a-z0-9]+", "_", s); return s.strip("_")
        def ensure_parent_account(name, acc_type, slug_value, branches_list):
            existing = db.collection("accounts").where("slug", "==", slug_value).limit(1).get()
            if existing: return existing[0].id
            code = self.generate_code_once(acc_type)
            parent_doc = {
                "name": name, "slug": slug_value, "type": acc_type, "code": code, "parent": None, "branch": branches_list,
                "description": f"System-generated parent for {name.lower()}", "active": True, "is_posting": False, "current_balance": 0.0
            }
            ref = db.collection("accounts").document(); ref.set(parent_doc); return ref.id

        if isinstance(branches, str) or branches is None:
            branches = [branches] if branches else []
        try:
            ob_amount = float(opening_balance or 0.0)
        except Exception:
            ob_amount = 0.0
        drcr_norm = self._normalize_drcr(drcr)

        parent_name = "Clients" if party_type == "Customer" else "Suppliers"
        parent_slug = "clients_parent" if party_type == "Customer" else "suppliers_parent"
        parent_id = ensure_parent_account(parent_name, type_, parent_slug, branches)

        computed_balance = ob_amount if drcr_norm == "debit" else -ob_amount
        if type_ not in ["Asset", "Expense"]: computed_balance *= -1

        account_code = self.generate_code_once(type_)
        child_slug = _slugify(name)
        coa_data = {
            "name": name, "slug": child_slug, "type": type_, "code": account_code, "parent": parent_id,
            "branch": branches, "description": f"{party_type} account for {name}", "active": True, "is_posting": True,
            "linked_party_id": party_id, "opening_balance": {"amount": ob_amount, "type": drcr_norm}, "current_balance": 0.0
        }
        coa_ref = db.collection("accounts").document(); coa_ref.set(coa_data)

        self.post_opening_journal_entry(account_id=coa_ref.id, account_name=name, amount=ob_amount, drcr=drcr_norm)
        if ob_amount > 0:
            db.collection("accounts").document(coa_ref.id).update({"current_balance": computed_balance})
        return coa_ref.id

    def _validate_required(self):
        missing = []
        if not self.name.text().strip(): missing.append("Name")
        if not self.contact.text().strip(): missing.append("Contact")
        if not self.phone.text().strip(): missing.append("Phone")
        if not self.address.toPlainText().strip(): missing.append("Address")
        if self.type.currentText().strip() == "": missing.append("Type")
        # Branches: require at least one checked
        checked = [self.branches.item(i).text() for i in range(self.branches.count()) if self.branches.item(i).checkState() == Qt.Checked]
        if not self.doc_id and len(checked) == 0:
            # when adding, force a branch; when editing, keep as-is if none were set earlier
            missing.append("Branches")
        # Opening balance: field present but zero is allowed; just ensure numeric
        try:
            float(self.balance.text() or "0")
        except Exception:
            missing.append("Opening Balance (number)")
        if missing:
            QMessageBox.warning(self, "Validation", "Please fill required fields: " + ", ".join(missing))
            return None
        return checked

    def save(self):
        checked_branches = self._validate_required()
        if checked_branches is None:
            return

        name = self.name.text().strip()
        opening_balance = float(self.balance.text() or "0")
        opening_type_raw = self.balance_type.currentText().lower()
        opening_type = self._normalize_drcr(opening_type_raw)
        party_type = self.type.currentText()
        acc_type = "Asset" if party_type == "Customer" else "Liability"
        code = self.generated_code if not self.doc_id else self.existing_data.get("id", "000")

        party_data = {
            "id": code,
            "name": name,
            "contact_person": self.contact.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),          # optional
            "address": self.address.toPlainText().strip(),
            "gst": self.gst.text().strip(),              # optional
            "ntn": self.ntn.text().strip(),              # optional
            "type": party_type,
            "branches": checked_branches if checked_branches is not None else [],
            "active": self.status.currentText() == "Active",
            "created_at": self.existing_data.get("created_at") or datetime.datetime.now(),
        }

        if self.doc_id:
            db.collection("parties").document(self.doc_id).set(party_data, merge=True)
            self.new_customer_id = self.doc_id
        else:
            new_id = str(uuid.uuid4())
            party_data["coa_account_id"] = self.create_coa_account_for_party(
                name=name, type_=acc_type, party_type=party_type, party_id=new_id,
                opening_balance=opening_balance, drcr=opening_type, branches=party_data["branches"]
            )
            db.collection("parties").document(new_id).set(party_data)
            db.collection("meta").document("cust_supp").set({"code": int(self.generated_code) + 1}, merge=True)
            self.new_customer_id = new_id
        self.accept()