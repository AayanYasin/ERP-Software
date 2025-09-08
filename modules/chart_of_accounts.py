# modules/chart_of_accounts.py
# ------------------------------------------------
# Performance + UX upgrades with logic preserved:
# - NO journal_entries scan on refresh (uses current_balance or opening fallback)
# - Background QThread for Firestore fetch (fast, responsive UI)
# - Background QThread for Save (no "Not Responding" on save)
# - Robust opening-edit guard: allows true opening-only state, blocks real activity
# - Parent accounts list comes from already-loaded tree data (no network on dialog open)
# - Tree build with repaint suppression + single-pass column resize
# ------------------------------------------------

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QMessageBox, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QDialog, QFormLayout, QListWidget, QListWidgetItem, QDialogButtonBox,
    QProgressDialog, QApplication, QFrame, QMenu, QFileDialog, QHeaderView, QWidget as QtWidget
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from firebase.config import db
from firebase_admin import firestore

import datetime
import re
import uuid
import csv
import os


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
# UI helpers
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
    bg = colors.get(kind, colors["neutral"]) + "20"
    fg = colors.get(kind, colors["neutral"])
    return f"<span style='padding:2px 8px;border-radius:10px;background:{bg};color:{fg};font-weight:600'>{text}</span>"


def _fmt_amount(val: float) -> str:
    try:
        return f"{float(val):,.2f}"
    except Exception:
        return "0.00"


# ------------------------------------------------
# Domain helpers (pure; safe to call from threads)
# ------------------------------------------------
def _signed_opening(acc_t: str, amount: float, drcr: str) -> float:
    drcr = (drcr or "debit").lower()
    if acc_t in ("Asset", "Expense"):
        return amount if drcr == "debit" else -amount
    else:
        return amount if drcr == "credit" else -amount


def _drcr_for_increase(acc_t: str) -> str:
    return "debit" if acc_t in ("Asset", "Expense") else "credit"


def _is_opening_like_je(doc_dict: dict) -> bool:
    """Treat legacy 'Opening balance' entries as opening-like even if meta.kind is missing."""
    d = doc_dict or {}
    meta_kind = ((d.get("meta") or {}).get("kind") or "").lower()
    if meta_kind == "opening_balance":
        return True
    desc = (d.get("description") or "").lower()
    if "opening balance" in desc:
        return True
    purpose = (d.get("purpose") or "").lower()
    if purpose == "adjustment" and "opening" in desc:
        return True
    return False


def _has_non_opening_activity(db_ref, account_id: str, sample_size: int = 25) -> bool:
    """
    True iff there's at least ONE JE touching this account that is NOT opening-like.
    Uses small, bounded reads to avoid heavy scans.
    """
    q = db_ref.collection("journal_entries") \
              .where("lines_account_ids", "array_contains", account_id) \
              .select(["description", "purpose", "meta.kind"]) \
              .limit(sample_size)
    docs = q.get()
    if not docs:
        return False
    for d in docs:
        if not _is_opening_like_je(d.to_dict() or {}):
            return True
    # If we hit the sample limit, peek one more page conservatively
    if len(docs) == sample_size:
        more = q.offset(sample_size).limit(sample_size).get()
        for d in more:
            if not _is_opening_like_je(d.to_dict() or {}):
                return True
    return False


def _generate_code_once_tx(db_ref, acc_type: str) -> str:
    """Transactional, thread-safe account code generation for a given type."""
    prefix = ACCOUNT_TYPE_PREFIX.get(acc_type, "9")
    counter_ref = db_ref.collection("meta").document("account_code_counters")
    transaction = firestore.client().transaction()

    @firestore.transactional
    def _inc(trans):
        snap = counter_ref.get(transaction=trans)
        data = snap.to_dict() or {}
        last = data.get(acc_type)
        if not last:
            query = db_ref.collection("accounts").where("type", "==", acc_type).get()
            codes = []
            for doc in query:
                code = str((doc.to_dict() or {}).get("code", "") or "")
                if code.isdigit() and code.startswith(prefix):
                    try:
                        codes.append(int(code))
                    except Exception:
                        pass
            last = max(codes) if codes else int(prefix + "000")
        new_code = int(last) + 1
        data[acc_type] = new_code
        trans.set(counter_ref, data, merge=True)
        return str(new_code)

    return _inc(transaction)


def _post_opening_balance_je(db_ref, user_data: dict, account_id: str, account_name: str,
                             amount: float, drcr: str, acc_type: str, description: str = None):
    """Pure DB helper: create (if needed) 'Opening Balances Equity' and post a two-line JE."""
    if not amount or amount <= 0:
        return

    drcr = (drcr or "debit").strip().lower()
    if drcr not in ("debit", "credit"):
        drcr = "debit"

    # Locate or create equity account by slug
    eq_q = db_ref.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
    if eq_q:
        equity_account_id = eq_q[0].id
        equity_account_name = (eq_q[0].to_dict() or {}).get("name", "Opening Balances Equity")
    else:
        equity_code = _generate_code_once_tx(db_ref, "Equity")
        branches = user_data.get("branch", [])
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
        doc_ref = db_ref.collection("accounts").document()
        doc_ref.set(equity_account)
        equity_account_id = doc_ref.id
        equity_account_name = "Opening Balances Equity"

    # Get 'before' balances (best-effort)
    try:
        a_doc = (db_ref.collection("accounts").document(account_id).get().to_dict() or {})
        a_pre = float(a_doc.get("current_balance", 0.0) or 0.0)
    except Exception:
        a_pre = 0.0
    try:
        e_doc = (db_ref.collection("accounts").document(equity_account_id).get().to_dict() or {})
        e_pre = float(e_doc.get("current_balance", 0.0) or 0.0)
    except Exception:
        e_pre = 0.0

    debit_line = {"account_id": account_id, "account_name": account_name, "debit": amount, "credit": 0, "balance_before": a_pre}
    credit_line = {"account_id": equity_account_id, "account_name": equity_account_name, "debit": 0, "credit": amount, "balance_before": e_pre}

    if drcr == "credit":
        debit_line, credit_line = credit_line, debit_line

    now_server = firestore.SERVER_TIMESTAMP
    branch_val = user_data.get("branch")
    if isinstance(branch_val, list):
        branch_val = branch_val[0] if branch_val else "-"
    branch_val = branch_val or "-"

    je_data = {
        "date": now_server,
        "created_at": now_server,
        "created_by": user_data.get("email", "system"),
        "purpose": "Adjustment",
        "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
        "branch": branch_val,
        "description": (description or f"Opening balance for {account_name}"),
        "lines": [debit_line, credit_line],
        "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
        "meta": {"kind": "opening_balance"}
    }
    db_ref.collection("journal_entries").document().set(je_data)


# ------------------------------------------------
# Background workers
# ------------------------------------------------
class AccountsLoader(QThread):
    loaded = pyqtSignal(list, dict, int, int)  # rows, parent_map, active_cnt, inactive_cnt
    failed = pyqtSignal(str)

    def run(self):
        try:
            fields = ["name", "code", "type", "branch", "active", "is_posting",
                      "parent", "current_balance", "opening_balance"]
            account_docs = db.collection("accounts").select(fields).get()

            rows = []
            parent_map = {}
            active_count = 0
            inactive_count = 0

            for doc in account_docs:
                data = doc.to_dict() or {}
                acc_id = doc.id

                # Prefer cached current_balance; fall back to opening-only
                if "current_balance" in data:
                    base_balance = float(data.get("current_balance", 0.0) or 0.0)
                else:
                    opening = data.get("opening_balance") or {}
                    opening_amount = float(opening.get("amount", 0.0) or 0.0)
                    opening_type = (opening.get("type", "debit") or "debit").lower()
                    if data.get("type") in ("Asset", "Expense"):
                        base_balance = opening_amount if opening_type == "debit" else -opening_amount
                    else:
                        base_balance = -opening_amount if opening_type == "debit" else opening_amount

                rows.append((acc_id, data, base_balance))
                parent_map[acc_id] = data.get("parent")
                if data.get("active", True):
                    active_count += 1
                else:
                    inactive_count += 1

            self.loaded.emit(rows, parent_map, active_count, inactive_count)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveAccountWorker(QThread):
    ok = pyqtSignal(dict)    # e.g., {"id": "..."}
    fail = pyqtSignal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.p = payload

    def run(self):
        try:
            # Unpack
            doc_id = self.p["doc_id"]
            is_new = self.p["is_new"]
            doc = self.p["doc"]
            user_data = self.p["user_data"]
            name = self.p["name"]
            acc_type = self.p["acc_type"]
            opening = self.p["opening"]
            guard_needed = self.p["guard_needed"]
            prev_signed = self.p["prev_signed"]
            new_signed = self.p["new_signed"]
            tol = self.p["tol"]

            doc_ref = db.collection("accounts").document(doc_id)

            # Guard: block opening edits if there is non-opening activity
            if guard_needed:
                if _has_non_opening_activity(db, doc_id, sample_size=25):
                    self.fail.emit(
                        "Opening balance cannot be edited after other (non-opening) transactions exist.\n"
                        "Please post an adjusting journal entry instead."
                    )
                    return

            # Persist account doc (set or update)
            if is_new:
                doc_ref.set(doc)
            else:
                doc_ref.update(doc)

            # Opening/Delta handling
            if is_new:
                if opening["has"]:
                    # Post opening JE
                    _post_opening_balance_je(
                        db_ref=db,
                        user_data=user_data,
                        account_id=doc_id,
                        account_name=name,
                        amount=opening["amount"],
                        drcr=opening["type"],
                        acc_type=acc_type,
                        description=f"Opening balance for {name}"
                    )
                    # Seed current_balance
                    doc_ref.update({"current_balance": _signed_opening(acc_type, opening["amount"], opening["type"])})
                else:
                    doc_ref.update({"current_balance": 0.0})
            else:
                # Edit: if opening changed, post delta and bump cache atomically
                delta = new_signed - prev_signed
                if abs(delta) > tol:
                    inc_dir = _drcr_for_increase(acc_type)  # debit for A/E, credit for L/Eq/Inc
                    delta_drcr = inc_dir if delta > 0 else ("credit" if inc_dir == "debit" else "debit")
                    _post_opening_balance_je(
                        db_ref=db,
                        user_data=user_data,
                        account_id=doc_id,
                        account_name=name,
                        amount=abs(delta),
                        drcr=delta_drcr,
                        acc_type=acc_type,
                        description=f"Opening balance adjustment Δ={delta:+,.2f}"
                    )
                    # Atomic bump to avoid race
                    doc_ref.update({"current_balance": firestore.Increment(delta)})

            self.ok.emit({"id": doc_id})
        except Exception as e:
            self.fail.emit(str(e))


# ------------------------------------------------
# Account Dialog (business logic intact; fast save; preloaded parents)
# ------------------------------------------------
class AccountDialog(QDialog):
    def __init__(self, user_data, existing=None, parent=None, parents_seed=None):
        super().__init__(parent)
        self.user_data = user_data
        self.existing = existing
        self._parents_seed = parents_seed or []  # list[(acc_id, data)] of non-posting accounts
        self.setWindowTitle("Edit Account" if existing else "Add New Account")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

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
        self._populate_parents_from_seed()  # instant; no I/O
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

        # Opening Balance block
        self.opening_amount = QLineEdit()
        self.opening_amount.setPlaceholderText("0.00")
        self.opening_type = QComboBox()
        self.opening_type.addItems(["Debit", "Credit"])
        ob_row = QHBoxLayout()
        ob_row.addWidget(self.opening_amount)
        ob_row.addWidget(self.opening_type)
        ob_wrap = QtWidget()
        ob_wrap.setLayout(ob_row)
        form.addRow("Opening Balance:", ob_wrap)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_account)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if existing:
            self.load_existing_data()
        else:
            self.code_edit.setText("(will be auto-generated)")

        QTimer.singleShot(0, self.name_edit.setFocus)

    def _slugify(self, text: str) -> str:
        s = (text or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s.strip("_")

    def _populate_parents_from_seed(self):
        """Fill parent combo from preloaded non-posting accounts (no network)."""
        self.parent_combo.blockSignals(True)
        while self.parent_combo.count() > 1:
            self.parent_combo.removeItem(1)
        self.parent_map = {}
        me_id = self.existing.get("id") if self.existing else None

        sorted_seed = sorted(self._parents_seed, key=lambda t: str((t[1] or {}).get("code", "")))
        for acc_id, data in sorted_seed:
            if me_id and acc_id == me_id:
                continue  # cannot be own parent
            # Only non-posting accounts can be parents (same rule as before)
            if not (data or {}).get("is_posting", True):
                self.parent_combo.addItem(f"[{data.get('code','')}] {data.get('name','')}", acc_id)
                self.parent_map[acc_id] = data

        if self.existing:
            parent_id = self.existing.get("parent")
            if parent_id:
                idx = self.parent_combo.findData(parent_id)
                self.parent_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.parent_combo.blockSignals(False)

    def generate_code_once(self, acc_type):
        return _generate_code_once_tx(db, acc_type)

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

    def save_account(self):
        # -------- gather + validate form --------
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

        # Block converting to posting if there are children
        if self.existing and is_posting:
            children = db.collection("accounts").where("parent", "==", self.existing["id"]).limit(1).get()
            if children:
                QMessageBox.warning(self, "Invalid Action", "Cannot convert to posting account — it has child accounts.")
                return

        # Validate/normalize parent and inherit type from a non-posting parent
        if parent:
            parent_doc = db.collection("accounts").document(parent).get()
            if parent_doc.exists:
                parent_data = parent_doc.to_dict()
                if parent_data.get("is_posting", True):
                    QMessageBox.warning(self, "Invalid Parent", "Cannot create a sub-account under a posting account.")
                    return
                acc_type = parent_data.get("type", acc_type)

        # Previous opening (for comparison)
        prev_amt = 0.0
        prev_type = "debit"
        if self.existing:
            prev_opening = (self.existing or {}).get("opening_balance") or {}
            try:
                prev_amt = float(prev_opening.get("amount", 0.0) or 0.0)
            except Exception:
                prev_amt = 0.0
            prev_type = (prev_opening.get("type") or "debit").lower()

        # New opening from form
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

        # Account code
        if not self.existing:
            try:
                code = self.generate_code_once(acc_type)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to generate code: {e}")
                return
        else:
            code = self.code_edit.text()

        # Slug
        existing_slug = (self.existing or {}).get("slug") if self.existing else None
        slug_val = existing_slug or self._slugify(name)

        # Document payload
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

        # Compute signed values for delta calc (thread passes these; no UI I/O)
        prev_signed = _signed_opening(acc_type, prev_amt, prev_type) if self.existing and prev_amt > 0 else 0.0
        new_signed = _signed_opening(acc_type, new_amt, new_type) if opening_balance and new_amt > 0 else 0.0

        # Determine whether the opening actually changed
        tol = 1e-6
        prev_has_opening = (prev_amt > 0)
        new_has_opening = (opening_balance is not None) and (new_amt > 0)
        same_opening = (
            (not prev_has_opening and not new_has_opening)
            or (prev_has_opening and new_has_opening and abs(prev_amt - new_amt) < tol and prev_type == new_type)
        )

        # Pre-assign / reuse doc id, avoid passing object refs across threads
        if self.existing:
            doc_id = self.existing["id"]
            is_new = False
        else:
            doc_id = db.collection("accounts").document().id
            is_new = True

        # Spinner + disable dialog while saving in background
        spinner = QProgressDialog("Saving account…", None, 0, 0, self)
        spinner.setWindowModality(Qt.WindowModal)
        spinner.setCancelButton(None)
        spinner.setMinimumDuration(0)
        spinner.show()
        self.setEnabled(False)
        QApplication.processEvents()

        payload = {
            "doc_id": doc_id,
            "is_new": is_new,
            "doc": doc,
            "user_data": self.user_data,
            "name": name,
            "acc_type": acc_type,
            "opening": {"has": new_has_opening, "amount": new_amt, "type": new_type},
            "guard_needed": (self.existing is not None) and (not same_opening),
            "prev_signed": prev_signed,
            "new_signed": new_signed,
            "tol": tol,
        }

        self._save_worker = _SaveAccountWorker(payload, parent=self)
        self._save_worker.ok.connect(lambda _: (spinner.close(), self.setEnabled(True), self.accept()))
        self._save_worker.fail.connect(lambda msg: (spinner.close(), self.setEnabled(True), QMessageBox.warning(self, "Save Failed", msg)))
        self._save_worker.start()


# ------------------------------------------------
# Chart of Accounts (non-blocking + parent cache)
# ------------------------------------------------
class ChartOfAccounts(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setWindowTitle("Chart of Accounts")
        self.resize(1000, 680)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)  # debounce filters

        self._build_ui()
        self._wire_shortcuts()
        self._loader_thread = None
        self._parents_seed = []  # cache of non-posting accounts for dialogs
        self.refresh()

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

        # Toolbar / Filters
        tools = QHBoxLayout()
        tools.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name/code/branch… (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda: self._filter_timer.start())
        self._filter_timer.timeout.connect(self._apply_filters)
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

        # Actions
        self.btn_add = QPushButton("➕ Add")
        self.btn_add.clicked.connect(self.add_account)
        self.btn_edit = QPushButton("✏️ Edit")
        self.btn_edit.clicked.connect(self.edit_selected)
        self.btn_delete = QPushButton("🗑️ Delete")
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_expand = QPushButton("▾ Expand All")
        self.btn_expand.clicked.connect(lambda: self._expand_collapse(True))
        self.btn_collapse = QPushButton("▸ Collapse All")
        self.btn_collapse.clicked.connect(lambda: self._expand_collapse(False))
        self.btn_export = QPushButton("📤 Export CSV")
        self.btn_export.clicked.connect(self.export_csv)

        for b in [self.btn_add, self.btn_edit, self.btn_delete, self.btn_refresh, self.btn_expand, self.btn_collapse, self.btn_export]:
            b.setCursor(Qt.PointingHandCursor)

        tools.addWidget(self.btn_add)
        tools.addWidget(self.btn_edit)
        tools.addWidget(self.btn_delete)
        tools.addWidget(self.btn_refresh)
        tools.addWidget(self.btn_expand)
        tools.addWidget(self.btn_collapse)
        tools.addWidget(self.btn_export)
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

        base_font = QFont(self.tree.font())
        base_font.setPointSize(12)
        self.tree.setFont(base_font)
        self.tree.setStyleSheet('''
            QTreeWidget { font-size: 14px; }
            QTreeWidget::item { padding: 10px 12px; }
            QTreeWidget::item:selected { background-color: #e6f2ff; }
            QHeaderView::section { background: #f8fafc; padding: 10px 12px; font-weight:600; font-size:13px; }
        ''')

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        root.addWidget(self.tree, 1)

    def _wire_shortcuts(self):
        self.tree.keyPressEvent = self._tree_keypress_wrapper(self.tree.keyPressEvent)

    def _tree_keypress_wrapper(self, original):
        def handler(event):
            key = event.key()
            if key == Qt.Key_Insert:
                self.add_account(); return
            if key == Qt.Key_F2:
                self.edit_selected(); return
            if key == Qt.Key_Delete:
                self.delete_selected(); return
            if key == Qt.Key_F5:
                self.refresh(); return
            if key == Qt.Key_F and (event.modifiers() & Qt.ControlModifier):
                self.search_edit.setFocus(); self.search_edit.selectAll(); return
            return original(event)
        return handler

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

    def _set_toolbar_enabled(self, enabled: bool):
        for b in [self.btn_add, self.btn_edit, self.btn_delete, self.btn_refresh, self.btn_expand, self.btn_collapse, self.btn_export]:
            b.setEnabled(enabled)
        self.search_edit.setEnabled(enabled)
        self.filter_type.setEnabled(enabled)
        self.filter_status.setEnabled(enabled)
        self.filter_post.setEnabled(enabled)

    def refresh(self):
        self.loader_dialog = self.show_loader("Loading Accounts", "Fetching chart of accounts…")
        self._set_toolbar_enabled(False)

        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.terminate()
            self._loader_thread.wait()

        self._loader_thread = AccountsLoader(self)
        self._loader_thread.loaded.connect(self._on_loaded_accounts)
        self._loader_thread.failed.connect(self._on_load_failed)
        self._loader_thread.start()

    def _on_load_failed(self, msg: str):
        try:
            self.loader_dialog.close()
        except Exception:
            pass
        self._set_toolbar_enabled(True)
        QMessageBox.critical(self, "Load Error", msg)

    def _on_loaded_accounts(self, rows, parent_map, active_count, inactive_count):
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self._account_map = {}
            for acc_id, data, base_balance in rows:
                name_txt = f"[{data.get('code','')}] {data.get('name','')}"
                type_txt = data.get("type", "")
                branches_txt = ", ".join(data.get("branch", []))
                status_txt = "🟢" if data.get("active", True) else "🔴"
                post_txt = "📝" if data.get("is_posting", True) else "📁"

                item = QTreeWidgetItem([name_txt, type_txt, _fmt_amount(base_balance), branches_txt, status_txt, post_txt])
                item.setData(0, Qt.UserRole, acc_id)
                item.setData(1, Qt.UserRole, data)

                if not data.get("is_posting", True):
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                    item.setForeground(0, Qt.darkGray)

                self._account_map[acc_id] = (item, parent_map.get(acc_id), base_balance)

            # Build adjacency + totals (memoized)
            children_of = {}
            for acc_id, (_, parent_id, _) in self._account_map.items():
                children_of.setdefault(parent_id, []).append(acc_id)

            memo_total = {}

            def compute_total(aid):
                if aid in memo_total:
                    return memo_total[aid]
                item, _, base = self._account_map[aid]
                total = base
                for cid in children_of.get(aid, []):
                    total += compute_total(cid)
                memo_total[aid] = total
                return total

            roots = []
            for acc_id in list(self._account_map.keys()):
                total_balance = compute_total(acc_id)
                self._account_map[acc_id][0].setText(2, _fmt_amount(total_balance))

            for acc_id, (item, parent_id, _) in self._account_map.items():
                if parent_id and parent_id in self._account_map:
                    self._account_map[parent_id][0].addChild(item)
                else:
                    roots.append(item)

            if roots:
                self.tree.addTopLevelItems(roots)
                for it in roots:
                    it.setExpanded(True)

            for i in range(1, self.tree.columnCount()):
                self.tree.resizeColumnToContents(i)

            self.badge_active.setText(_badge(f"Active: {active_count}", "ok"))
            self.badge_inactive.setText(_badge(f"Inactive: {inactive_count}", "muted"))

            # Build non-posting parent cache for dialogs
            self._parents_seed = [
                (acc_id, (itm.data(1, Qt.UserRole) or {}))
                for acc_id, (itm, _parent, _base) in self._account_map.items()
                if not (itm.data(1, Qt.UserRole) or {}).get("is_posting", True)
            ]

            self._apply_filters()
        finally:
            self.tree.setUpdatesEnabled(True)
            QTimer.singleShot(200, self.loader_dialog.close)
            self._set_toolbar_enabled(True)

    def _apply_filters(self):
        query = (self.search_edit.text() or "").strip().lower()
        type_sel = self.filter_type.currentData()
        status_sel = self.filter_status.currentText()
        post_sel = self.filter_post.currentText()

        def match_item(item: QTreeWidgetItem) -> bool:
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

        def apply_visibility(item: QTreeWidgetItem) -> bool:
            visible = match_item(item)
            for i in range(item.childCount()):
                if apply_visibility(item.child(i)):
                    visible = True
            item.setHidden(not visible)
            return visible

        self.tree.setUpdatesEnabled(False)
        try:
            for i in range(self.tree.topLevelItemCount()):
                apply_visibility(self.tree.topLevelItem(i))
        finally:
            self.tree.setUpdatesEnabled(True)

    def _on_double_click(self, item):
        if item:
            self.edit_account(item)

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        a_add = menu.addAction("➕ Add")
        a_edit = menu.addAction("✏️ Edit")
        a_del = menu.addAction("🗑️ Delete")
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
        dialog = AccountDialog(self.user_data, parent=self, parents_seed=self._parents_seed)
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
        dialog = AccountDialog(self.user_data, {"id": acc_id, **(acc_data or {})}, parent=self, parents_seed=self._parents_seed)
        if dialog.exec_():
            self.refresh()

    def edit_selected(self):
        acc = self.get_selected_account()
        if acc:
            dialog = AccountDialog(self.user_data, acc, parent=self, parents_seed=self._parents_seed)
            if dialog.exec_():
                self.refresh()

    def delete_selected(self):
        acc = self.get_selected_account()
        if not acc:
            return

        # 1) Block if it has children
        children = db.collection("accounts").where("parent", "==", acc["id"]).limit(1).get()
        if children:
            QMessageBox.warning(self, "Cannot Delete", "This account has child accounts.")
            return

        # 2) Block if referenced in any journal entry
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

    def export_csv(self):
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


# If you want to test standalone:
# if __name__ == "__main__":
#     import sys
#     app = QApplication(sys.argv)
#     w = ChartOfAccounts({"email":"tester@example.com", "branch":["Main"]})
#     w.show()
#     sys.exit(app.exec_())
