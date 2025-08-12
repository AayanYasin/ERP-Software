# modules/chart_of_accounts.py
# Refined UI/UX + safe business logic kept intact
# ------------------------------------------------
# Highlights:
# - Clean header with title, counters, and quick actions
# - Toolbar (Add, Edit, Delete, Refresh, Expand/Collapse, Export CSV)
# - Fast search + multi-filter (Type, Status, Postable)
# - Better tree visuals (badges, zebra rows, condensed spacing, autosizing)
# - Context menu + keyboard shortcuts (Ins=Add, F2=Edit, Del=Delete, F5=Refresh)
# - Non-blocking loader overlay during fetch
# - Same AccountDialog logic preserved (including opening-balance JE flow with slug)

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QMessageBox, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QDialog, QFormLayout, QListWidget, QListWidgetItem, QDialogButtonBox,
    QProgressDialog, QApplication, QFrame, QMenu, QFileDialog, QHeaderView
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from firebase.config import db
from firebase_admin import firestore
import datetime, re, uuid, csv, os

# ------------------------------------------------
# Constants
# ------------------------------------------------
ACCOUNT_TYPE_PREFIX = {
    "Asset": "1",
    "Liability": "2",
    "Equity": "3",
    "Income": "4",
    "Expense": "5"
}

# ------------------------------------------------
# Helpers
# ------------------------------------------------
def _badge(text: str, kind: str = "neutral") -> str:
    colors = {
        "ok": "#0E9F6E",           # green
        "warn": "#B45309",         # amber
        "bad": "#DC2626",          # red
        "muted": "#6B7280",        # gray
        "chip": "#2563EB",         # blue
        "neutral": "#374151"
    }
    bg = colors.get(kind, colors["neutral"]) + "20"  # translucent
    fg = colors.get(kind, colors["neutral"])         # solid
    return f"<span style='padding:2px 8px;border-radius:10px;background:{bg};color:{fg};font-weight:600'>{text}</span>"


def _fmt_amount(val: float) -> str:
    try:
        return f"{float(val):,.2f}"
    except Exception:
        return "0.00"


# ------------------------------------------------
# Account Dialog (business logic intact; minor UI polish)
# ------------------------------------------------
class AccountDialog(QDialog):
    def __init__(self, user_data, existing=None, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.existing = existing
        self.setWindowTitle("Edit Account" if existing else "Add New Account")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<div style='font-size:18px;font-weight:700'>" + ("Edit Account" if existing else "Add New Account") + "</div>")
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        form = QFormLayout()
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Cash in hand")
        form.addRow("Account Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Asset", "Liability", "Equity", "Income", "Expense"])
        form.addRow("Account Type:", self.type_combo)

        self.subtype_combo = QComboBox()
        self.subtype_combo.addItems([
            "Cash & Bank", "Accounts Receivable", "Inventory", "Fixed Assets",
            "Accounts Payable", "Loans", "Capital", "Retained Earnings",
            "Sales Revenue", "Service Revenue", "Other Income",
            "Cost of Goods Sold", "Operating Expenses", "Interest Expense"
        ])
        form.addRow("Subtype:", self.subtype_combo)

        self.code_edit = QLineEdit()
        self.code_edit.setReadOnly(True)
        self.code_edit.setPlaceholderText("(auto-generated)")
        form.addRow("Auto Code:", self.code_edit)

        self.parent_combo = QComboBox()
        self.parent_combo.addItem("-- None --", None)
        self.parent_map = {}
        self.load_parent_accounts()
        form.addRow("Parent Account:", self.parent_combo)

        self.branch_list = QListWidget()
        self.branch_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for b in self.user_data.get("branch", []):
            self.branch_list.addItem(QListWidgetItem(b))
        form.addRow("Branches:", self.branch_list)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Optional description")
        form.addRow("Description:", self.desc_edit)

        self.active_checkbox = QCheckBox("Active")
        self.active_checkbox.setChecked(True)
        form.addRow("Status:", self.active_checkbox)

        self.posting_checkbox = QCheckBox("Allow Posting to this Account")
        self.posting_checkbox.setChecked(True)
        form.addRow("Account Nature:", self.posting_checkbox)

        # Opening Balance block (always visible for consistency)
        self.opening_amount = QLineEdit()
        self.opening_amount.setPlaceholderText("0.00")
        self.opening_type = QComboBox()
        self.opening_type.addItems(["Debit", "Credit"])
        ob_row = QHBoxLayout()
        ob_row.addWidget(self.opening_amount)
        ob_row.addWidget(self.opening_type)
        ob_wrap = QWidget()
        ob_wrap.setLayout(ob_row)
        form.addRow("Opening Balance:", ob_wrap)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_account)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if existing:
            self.load_existing_data()
        else:
            self.code_edit.setText("(will be auto-generated)")

    # ---------- Business helpers (unchanged core logic) ----------
    def _slugify(self, text: str) -> str:
        s = (text or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s.strip("_")

    def load_parent_accounts(self):
        self.parent_combo.clear()
        self.parent_combo.addItem("-- None --", None)
        self.parent_map = {}
        try:
            for acc in db.collection("accounts").stream():
                acc_id = acc.id
                data = acc.to_dict() or {}
                if self.existing and acc_id == self.existing.get("id"):
                    continue
                # Only non-posting accounts can be parents
                if not data.get("is_posting", True):
                    self.parent_combo.addItem(f"[{data.get('code','')}] {data.get('name','')}", acc_id)
                    self.parent_map[acc_id] = data
        except Exception:
            # Fallback – allow any
            for acc in db.collection("accounts").stream():
                acc_id = acc.id
                data = acc.to_dict() or {}
                if self.existing and acc_id == self.existing.get("id"):
                    continue
                self.parent_combo.addItem(f"[{data.get('code','')}] {data.get('name','')}", acc_id)
                self.parent_map[acc_id] = data

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
                codes = [int(doc.to_dict().get("code", "0")) for doc in query if str(doc.to_dict().get("code", "")).startswith(prefix)]
                last = max(codes) if codes else int(prefix + "000")
            new_code = last + 1
            data[acc_type] = new_code
            trans.set(counter_ref, data, merge=True)
            return str(new_code)

        return increment_code(transaction)

    def load_existing_data(self):
        acc = self.existing
        self.name_edit.setText(acc.get("name", ""))
        self.type_combo.setCurrentText(acc.get("type", "Asset"))
        self.subtype_combo.setCurrentText(acc.get("subtype", ""))
        self.code_edit.setText(str(acc.get("code", "")))
        self.desc_edit.setText(acc.get("description", ""))
        self.active_checkbox.setChecked(acc.get("active", True))
        self.posting_checkbox.setChecked(acc.get("is_posting", True))

        parent_id = acc.get("parent")
        if parent_id:
            idx = self.parent_combo.findData(parent_id)
            self.parent_combo.setCurrentIndex(idx if idx >= 0 else 0)

        selected_branches = acc.get("branch", [])
        for i in range(self.branch_list.count()):
            item = self.branch_list.item(i)
            if item.text() in selected_branches:
                item.setSelected(True)

        opening = acc.get("opening_balance", {})
        if opening:
            self.opening_amount.setText(str(opening.get("amount", "")))
            self.opening_type.setCurrentText((opening.get("type", "Debit")).capitalize())

    def post_opening_balance_journal(self, account_id, account_name, amount, drcr, acc_type, description=None, reverse=False):
        try:
            if not amount or amount <= 0:
                return

            drcr = (drcr or "debit").strip().lower()
            if drcr not in ("debit", "credit"):
                drcr = "debit"

            # Find or create Opening Balances Equity by slug
            eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
            if eq_q:
                equity_account_id = eq_q[0].id
                equity_account_name = eq_q[0].to_dict().get("name", "Opening Balances Equity")
            else:
                equity_code = self.generate_code_once("Equity")
                branches = self.user_data.get("branch", [])
                if isinstance(branches, str):
                    branches = [branches]
                equity_account = {
                    "name": "Opening Balances Equity",
                    "slug": "opening_balances_equity",
                    "type": "Equity",
                    "code": equity_code,
                    "parent": None,
                    "branch": branches,
                    "description": "System-generated equity account for opening balances",
                    "active": True,
                    "is_posting": True,
                    "opening_balance": None,
                    "current_balance": 0.0
                }
                doc_ref = db.collection("accounts").document()
                doc_ref.set(equity_account)
                equity_account_id = doc_ref.id
                equity_account_name = "Opening Balances Equity"

            try:
                a_snap = db.collection("accounts").document(account_id).get()
                a_doc = a_snap.to_dict() or {}
                a_pre = float(a_doc.get("current_balance", 0.0) or 0.0)
            except Exception:
                a_pre = 0.0
            try:
                e_snap = db.collection("accounts").document(equity_account_id).get()
                e_doc = e_snap.to_dict() or {}
                e_pre = float(e_doc.get("current_balance", 0.0) or 0.0)
            except Exception:
                e_pre = 0.0

            debit_line = {"account_id": account_id, "account_name": account_name, "debit": amount, "credit": 0, "balance_before": a_pre}
            credit_line = {"account_id": equity_account_id, "account_name": equity_account_name, "debit": 0, "credit": amount, "balance_before": e_pre}

            if drcr == "credit":
                debit_line, credit_line = credit_line, debit_line

            if reverse:
                debit_line, credit_line = credit_line, debit_line
                debit_line["debit"], debit_line["credit"] = debit_line["credit"], debit_line["debit"]
                credit_line["debit"], credit_line["credit"] = credit_line["credit"], credit_line["debit"]

            now_server = firestore.SERVER_TIMESTAMP
            branch_val = self.user_data.get("branch")
            if isinstance(branch_val, list):
                branch_val = branch_val[0] if branch_val else "-"
            branch_val = branch_val or "-"

            je_data = {
                "date": now_server,
                "created_at": now_server,
                "created_by": self.user_data.get("email", "system"),
                "purpose": "Adjustment",
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
                "branch": branch_val,
                "description": (description or f"Opening balance for {account_name}"),
                "lines": [debit_line, credit_line],
                "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
                "meta": {"kind": "opening_balance", "reverse": bool(reverse)}
            }
            db.collection("journal_entries").document().set(je_data)
        except Exception as e:
            QMessageBox.critical(self, "Journal Error", f"Failed to post opening balance journal entry: {e}")

    def save_account(self):
        name = self.name_edit.text().strip()
        acc_type = self.type_combo.currentText()
        parent = self.parent_combo.currentData()
        branches = [item.text() for item in self.branch_list.selectedItems()]
        description = self.desc_edit.text().strip()
        active = self.active_checkbox.isChecked()
        is_posting = self.posting_checkbox.isChecked()

        if not name:
            QMessageBox.warning(self, "Validation Error", "Account name is required.")
            return

        if self.existing and is_posting:
            children = db.collection("accounts").where("parent", "==", self.existing["id"]).get()
            if children:
                QMessageBox.warning(self, "Invalid Action", "Cannot convert to posting account — it has child accounts.")
                return

        if parent:
            parent_doc = db.collection("accounts").document(parent).get()
            if parent_doc.exists:
                parent_data = parent_doc.to_dict()
                if parent_data.get("is_posting", True):
                    QMessageBox.warning(self, "Invalid Parent", "Cannot create a sub-account under a posting account.")
                    return
                acc_type = parent_data.get("type", acc_type)

        prev_opening = None
        prev_amt = 0.0
        prev_type = "debit"
        if self.existing:
            prev_opening = (self.existing or {}).get("opening_balance") or {}
            try:
                prev_amt = float(prev_opening.get("amount", 0.0) or 0.0)
            except Exception:
                prev_amt = 0.0
            prev_type = (prev_opening.get("type") or "debit").lower()

        opening_balance = None
        new_amt = 0.0
        new_type = "debit"
        amt_text = self.opening_amount.text().strip()
        if amt_text:
            try:
                new_amt = float(amt_text)
                if new_amt < 0:
                    raise ValueError
                new_type = self.opening_type.currentText().lower()
                opening_balance = {"amount": new_amt, "type": new_type}
            except ValueError:
                QMessageBox.warning(self, "Validation Error", "Opening balance must be a positive number.")
                return

        if not self.existing:
            try:
                code = self.generate_code_once(acc_type)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to generate code: {e}")
                return
        else:
            code = self.code_edit.text()

        existing_slug = (self.existing or {}).get("slug") if self.existing else None
        slug_val = existing_slug or self._slugify(name)

        doc = {
            "name": name,
            "slug": slug_val,
            "type": acc_type,
            "subtype": self.subtype_combo.currentText(),
            "code": code,
            "parent": parent,
            "branch": branches,
            "description": description,
            "active": active,
            "is_posting": is_posting,
            "opening_balance": opening_balance
        }

        try:
            if self.existing:
                doc_ref = db.collection("accounts").document(self.existing["id"])
                doc_ref.update(doc)
            else:
                doc_ref = db.collection("accounts").document()
                doc_ref.set(doc)

            # Opening balance JE + current_balance sync
            if not self.existing:
                if opening_balance and new_amt > 0:
                    self.post_opening_balance_journal(
                        account_id=doc_ref.id,
                        account_name=name,
                        amount=new_amt,
                        drcr=new_type,
                        acc_type=acc_type,
                        description=f"Opening balance for {name}"
                    )

                if opening_balance:
                    balance = new_amt
                    if new_type == "credit":
                        balance *= -1
                    if acc_type not in ["Asset", "Expense"]:
                        balance *= -1
                    doc_ref.update({"current_balance": balance})
                else:
                    doc_ref.update({"current_balance": 0.0})
            else:
                tol = 1e-6
                prev_has_opening = prev_amt > 0
                new_has_opening = (opening_balance is not None) and (new_amt > 0)
                same_opening = ((not prev_has_opening and not new_has_opening) or (prev_has_opening and new_has_opening and abs(prev_amt - new_amt) < tol and prev_type == new_type))

                if not same_opening:
                    if prev_has_opening:
                        self.post_opening_balance_journal(
                            account_id=doc_ref.id,
                            account_name=name,
                            amount=prev_amt,
                            drcr=prev_type,
                            acc_type=acc_type,
                            description=f"Reversal: opening balance correction for {name} (was {prev_amt} {prev_type})",
                            reverse=True
                        )
                    if new_has_opening:
                        corr_note = f" (was {prev_amt} {prev_type})" if prev_has_opening else ""
                        self.post_opening_balance_journal(
                            account_id=doc_ref.id,
                            account_name=name,
                            amount=new_amt,
                            drcr=new_type,
                            acc_type=acc_type,
                            description=f"Corrected opening balance for {name}{corr_note}"
                        )

                if new_has_opening:
                    balance = new_amt
                    if new_type == "credit":
                        balance *= -1
                    if acc_type not in ["Asset", "Expense"]:
                        balance *= -1
                    doc_ref.update({"current_balance": balance})
                else:
                    doc_ref.update({"current_balance": 0.0})

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")


# ------------------------------------------------
# Chart of Accounts — Enhanced UI
# ------------------------------------------------
class ChartOfAccounts(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setWindowTitle("Chart of Accounts")
        self.resize(1000, 680)

        self._build_ui()
        self._wire_shortcuts()
        self.refresh()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("<div style='font-size:22px;font-weight:800'>Chart of Accounts</div>")
        title.setTextFormat(Qt.RichText)
        header.addWidget(title)
        header.addStretch(1)

        self.badge_active = QLabel(_badge("Active: 0", "ok"))
        self.badge_inactive = QLabel(_badge("Inactive: 0", "muted"))
        header.addWidget(self.badge_active)
        header.addWidget(self.badge_inactive)
        root.addLayout(header)

        # Toolbar / Filters Row
        tools = QHBoxLayout()
        tools.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name/code/branch… (Ctrl+F)")
        self.search_edit.textChanged.connect(self._apply_filters)
        self.search_edit.setClearButtonEnabled(True)
        tools.addWidget(self.search_edit, 2)

        self.filter_type = QComboBox()
        self.filter_type.addItem("All Types", "")
        for t in ["Asset", "Liability", "Equity", "Income", "Expense"]:
            self.filter_type.addItem(t, t)
        self.filter_type.currentIndexChanged.connect(self._apply_filters)
        tools.addWidget(self.filter_type)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["All Status", "Active", "Inactive"])
        self.filter_status.currentIndexChanged.connect(self._apply_filters)
        tools.addWidget(self.filter_status)

        self.filter_post = QComboBox()
        self.filter_post.addItems(["All", "Postable", "Non-Postable"])
        self.filter_post.currentIndexChanged.connect(self._apply_filters)
        tools.addWidget(self.filter_post)

        # Quick action buttons
        btn_add = QPushButton("➕ Add")
        btn_add.clicked.connect(self.add_account)
        btn_edit = QPushButton("✏️ Edit")
        btn_edit.clicked.connect(self.edit_selected)
        btn_delete = QPushButton("🗑️ Delete")
        btn_delete.clicked.connect(self.delete_selected)
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.refresh)
        btn_expand = QPushButton("▾ Expand All")
        btn_expand.clicked.connect(lambda: self._expand_collapse(True))
        btn_collapse = QPushButton("▸ Collapse All")
        btn_collapse.clicked.connect(lambda: self._expand_collapse(False))
        btn_export = QPushButton("📤 Export CSV")
        btn_export.clicked.connect(self.export_csv)

        for b in [btn_add, btn_edit, btn_delete, btn_refresh, btn_expand, btn_collapse, btn_export]:
            b.setCursor(Qt.PointingHandCursor)
        tools.addWidget(btn_add)
        tools.addWidget(btn_edit)
        tools.addWidget(btn_delete)
        tools.addWidget(btn_refresh)
        tools.addWidget(btn_expand)
        tools.addWidget(btn_collapse)
        tools.addWidget(btn_export)
        root.addLayout(tools)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Account", "Type", "Closing Balance", "Branches", "Status", "Postable"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setAnimated(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)

        # Bigger, clearer font + padding
        base_font = QFont(self.tree.font())
        base_font.setPointSize(12)
        self.tree.setFont(base_font)
        self.tree.setStyleSheet('''
            QTreeWidget { font-size: 14px; }
            QTreeWidget::item { padding: 10px 12px; }
            QTreeWidget::item:selected { background-color: #e6f2ff; }
            QHeaderView::section { background: #f8fafc; padding: 10px 12px; font-weight:600; font-size:13px; }
        ''')

        # Column sizing: make name stretch, others resize to content
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        root.addWidget(self.tree, 1)

    def _wire_shortcuts(self):
        # Lightweight shortcuts without QShortcut objects to avoid extra imports
        self.tree.keyPressEvent = self._tree_keypress_wrapper(self.tree.keyPressEvent)

    def _tree_keypress_wrapper(self, original):
        def handler(event):
            key = event.key()
            if key == Qt.Key_Insert:
                self.add_account()
                return
            if key == Qt.Key_F2:
                self.edit_selected()
                return
            if key == Qt.Key_Delete:
                self.delete_selected()
                return
            if key == Qt.Key_F5:
                self.refresh()
                return
            if key == Qt.Key_F and (event.modifiers() & Qt.ControlModifier):
                self.search_edit.setFocus(); self.search_edit.selectAll(); return
            return original(event)
        return handler

    # ---------- Data ops ----------
    def show_loader(self, title="Please wait…", message="Processing…"):
        loader = QProgressDialog(message, None, 0, 0, self)
        loader.setWindowModality(Qt.WindowModal)
        loader.setMinimumDuration(0)
        loader.setAutoClose(True)
        loader.setCancelButton(None)
        loader.setWindowTitle(title)
        loader.show()
        QApplication.processEvents()
        return loader

    def refresh(self):
        loader = self.show_loader("Loading Accounts", "Fetching chart of accounts…")
        try:
            self._load_accounts()
            self._apply_filters()  # re-run filters after fresh load
        finally:
            QTimer.singleShot(200, loader.close)

    def _load_accounts(self):
        self.tree.clear()
        self._account_map = {}

        query = db.collection("accounts").stream()
        active_count = 0
        inactive_count = 0

        for doc in query:
            data = doc.to_dict() or {}
            acc_id = doc.id

            # Use precomputed current_balance if present
            if "current_balance" in data:
                closing_balance = float(data.get("current_balance", 0.0))
            else:
                # Fallback to historical computation (slower, legacy safety)
                opening = data.get("opening_balance") or {}
                opening_amount = float(opening.get("amount", 0.0))
                opening_type = (opening.get("type", "debit")).lower()
                if data.get("type") in ["Asset", "Expense"]:
                    opening_balance = opening_amount if opening_type == "debit" else -opening_amount
                else:
                    opening_balance = -opening_amount if opening_type == "debit" else opening_amount
                debit_total = credit_total = 0.0
                for journal_doc in db.collection("journal_entries").stream():
                    entry = journal_doc.to_dict() or {}
                    for line in entry.get("lines", []):
                        if line.get("account_id") == acc_id:
                            debit_total += float(line.get("debit", 0))
                            credit_total += float(line.get("credit", 0))
                closing_balance = opening_balance + debit_total - credit_total

            # Plain, always-visible text (no QLabel widgets)
            name_txt = f"[{data.get('code','')}] {data.get('name','')}"
            type_txt = data.get("type", "")
            branches_txt = ", ".join(data.get("branch", []))
            status_txt = "🟢" if data.get("active", True) else "🔴"
            post_txt = "📝" if data.get("is_posting", True) else "📁"

            item = QTreeWidgetItem([name_txt, type_txt, _fmt_amount(closing_balance), branches_txt, status_txt, post_txt])
            item.setData(0, Qt.UserRole, acc_id)
            item.setData(1, Qt.UserRole, data)

            # Visual weight for non-posting (parents)
            if not data.get("is_posting", True):
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                item.setForeground(0, Qt.darkGray)

            self._account_map[acc_id] = (item, data.get("parent"), closing_balance)
            if data.get("active", True):
                active_count += 1
            else:
                inactive_count += 1

        # Propagate balances upward
        def compute_balance(account_id):
            item, parent_id, balance = self._account_map[account_id]
            total = balance
            for cid, (citem, cparent, cbalance) in self._account_map.items():
                if cparent == account_id:
                    total += compute_balance(cid)
            return total

        for acc_id in list(self._account_map.keys()):
            total_balance = compute_balance(acc_id)
            self._account_map[acc_id][0].setText(2, _fmt_amount(total_balance))

        # Build hierarchy
        roots = []
        for acc_id, (item, parent_id, _) in self._account_map.items():
            if parent_id and parent_id in self._account_map:
                self._account_map[parent_id][0].addChild(item)
            else:
                roots.append(item)
        for it in roots:
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)

        # Resize once after population; name column will stretch due to header policy
        for i in range(self.tree.columnCount()):
            if i != 0:
                self.tree.resizeColumnToContents(i)

        self.badge_active.setText(_badge(f"Active: {active_count}", "ok"))
        self.badge_inactive.setText(_badge(f"Inactive: {inactive_count}", "muted"))

    # ---------- Filters & Search ----------
    def _apply_filters(self):
        query = (self.search_edit.text() or "").strip().lower()
        type_sel = self.filter_type.currentData()
        status_sel = self.filter_status.currentText()
        post_sel = self.filter_post.currentText()

        def match_item(item: QTreeWidgetItem) -> bool:
            acc_id = item.data(0, Qt.UserRole)
            data = item.data(1, Qt.UserRole) or {}
            text_blob = f"{data.get('name','')} {data.get('code','')} {', '.join(data.get('branch', []))}".lower()

            if query and query not in text_blob:
                return False
            if type_sel and data.get("type") != type_sel:
                return False
            if status_sel == "Active" and not data.get("active", True):
                return False
            if status_sel == "Inactive" and data.get("active", True):
                return False
            if post_sel == "Postable" and not data.get("is_posting", True):
                return False
            if post_sel == "Non-Postable" and data.get("is_posting", True):
                return False
            return True

        # We also keep parents visible if any child matches
        def apply_visibility(item: QTreeWidgetItem) -> bool:
            visible = match_item(item)
            for i in range(item.childCount()):
                if apply_visibility(item.child(i)):
                    visible = True
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            apply_visibility(self.tree.topLevelItem(i))

    # ---------- Context/Actions ----------
    def _on_double_click(self, item):
        if item:
            self.edit_account(item)

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        a_add = menu.addAction("➕ Add")
        a_edit = menu.addAction("✏️ Edit")
        a_del  = menu.addAction("🗑️ Delete")
        menu.addSeparator()
        a_expand = menu.addAction("▾ Expand All")
        a_collapse = menu.addAction("▸ Collapse All")
        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if action == a_add:
            self.add_account()
        elif action == a_edit and item:
            self.edit_account(item)
        elif action == a_del and item:
            self.delete_selected()
        elif action == a_expand:
            self._expand_collapse(True)
        elif action == a_collapse:
            self._expand_collapse(False)

    def _expand_collapse(self, expand=True):
        def walk(item):
            item.setExpanded(expand)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ---------- CRUD ----------
    def add_account(self):
        dialog = AccountDialog(self.user_data, parent=self)
        if dialog.exec_():
            self.refresh()

    def get_selected_account(self):
        selected = self.tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "Select Account", "Please select an account.")
            return None
        acc_id = selected.data(0, Qt.UserRole)
        acc_data = selected.data(1, Qt.UserRole)
        return {"id": acc_id, **(acc_data or {})}

    def edit_account(self, item):
        acc_id = item.data(0, Qt.UserRole)
        acc_data = item.data(1, Qt.UserRole)
        dialog = AccountDialog(self.user_data, {"id": acc_id, **(acc_data or {})}, parent=self)
        if dialog.exec_():
            self.refresh()

    def edit_selected(self):
        acc = self.get_selected_account()
        if acc:
            dialog = AccountDialog(self.user_data, acc, parent=self)
            if dialog.exec_():
                self.refresh()

    def delete_selected(self):
        acc = self.get_selected_account()
        if not acc:
            return

        # 1) Block if it has children
        children = db.collection("accounts").where("parent", "==", acc["id"]).get()
        if children:
            QMessageBox.warning(self, "Cannot Delete", "This account has child accounts.")
            return

        # 2) Block if referenced in any journal entry (requires index on lines_account_ids)
        je_refs = db.collection("journal_entries").where("lines_account_ids", "array_contains", acc["id"]).limit(1).get()
        if je_refs:
            QMessageBox.warning(self, "Cannot Delete", "This account is used in journal entries. Deletion is not allowed.")
            return

        # 3) Block if linked to a party
        party_link = db.collection("parties").where("coa_account_id", "==", acc["id"]).limit(1).get()
        if party_link:
            QMessageBox.warning(self, "Cannot Delete", "This account is linked to a party (Customer/Supplier). Unlink the party first.")
            return

        confirm = QMessageBox.question(self, "Delete Account", f"Are you sure you want to delete account '{acc['name']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            try:
                db.collection("accounts").document(acc["id"]).delete()
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    # ---------- Export ----------
    def export_csv(self):
        # Default to user's Desktop (per your preference in other modules)
        default_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        try:
            os.makedirs(default_dir, exist_ok=True)
        except Exception:
            pass
        default_path = os.path.join(default_dir, "chart_of_accounts.csv")

        path, _ = QFileDialog.getSaveFileName(self, "Export Accounts", default_path, "CSV Files (*.csv)")
        if not path:
            return
        try:
            rows = []
            def collect(item):
                data = item.data(1, Qt.UserRole) or {}
                rows.append([
                    data.get("code", ""),
                    data.get("name", ""),
                    data.get("type", ""),
                    item.text(2),
                    ", ".join(data.get("branch", [])),
                    "Active" if data.get("active", True) else "Inactive",
                    "Yes" if data.get("is_posting", True) else "No"
                ])
                for i in range(item.childCount()):
                    collect(item.child(i))

            for i in range(self.tree.topLevelItemCount()):
                collect(self.tree.topLevelItem(i))

            with open(path, "w", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Code", "Name", "Type", "Closing Balance", "Branches", "Status", "Postable"])
                writer.writerows(rows)
            QMessageBox.information(self, "Exported", f"CSV exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")


# If you want to quickly test this widget alone, you can uncomment below:
# if __name__ == "__main__":
#     import sys
#     app = QApplication(sys.argv)
#     w = ChartOfAccounts({"email":"tester@example.com", "branch":["Main"]})
#     w.show()
#     sys.exit(app.exec_())
