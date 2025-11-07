# modules/powder_coating_cycle.py
# Powder Coating Cycle — Orders, Keyword Rates, Gate Pass/Bill PDFs, Inventory & Accounting
# Implements:
# - PDFs only (Bill + Gate Pass) via FPDF, regenerated on demand
# - Double-click on order row => actions: Download Bill, Download Gate Pass, Make Payment, Change Status
# - Inventory updates nested in products.qty[branch][color][condition] with transactions
# - Accounts: System Offset creation per spec; JE on bill (Dr Offset, Cr Vendor) without changing offset balance
# - Payment JE (Dr Vendor, Cr Cash/Bank)
# - Color list from meta/colors.pc_colors (array) with fallbacks
# - UI polish

# modules/powder_coating_cycle.py
# UI restyle to match app theme (flat white/gray, Segoe UI, blue buttons).
# All original business logic (Firestore operations, PDF exports, JE posting,
# inventory mutation functions, etc.) is preserved. Only visual/layout parts
# were modernized to match view_inventory.py design language.

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit,
    QHeaderView, QAbstractItemView, QMessageBox, QDateEdit, QFileDialog,
    QDoubleSpinBox, QToolBar, QAction, QFrame, QSpinBox
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont
from firebase.config import db
from firebase_admin import firestore
import os, sys, tempfile, shutil, datetime

# If you use your Inventory selector
try:
    from modules.delivery_chalan import InventorySelectorDialog
except Exception:
    InventorySelectorDialog = None

# ============ Utilities & Helpers ============
def _fmt_money(n):
    try:
        return f"{float(n or 0):,.2f}"
    except Exception:
        return "0.00"


# -------- Colors: meta -> colors -> pc_colors (array), with legacy fallbacks --------
def _load_pc_colors():
    """
    Preferred: meta/colors { pc_colors: [...] }
    Fallbacks: meta/pc_colors { colors: [...] } or list/dict
    """
    try:
        doc = db.collection("meta").document("colors").get()
        data = doc.to_dict() or {}
        arr = data.get("pc_colors")
        if isinstance(arr, list) and arr:
            return [str(x) for x in arr if x]
    except Exception:
        pass
    try:
        doc_legacy = db.collection("meta").document("pc_colors").get()
        legacy = doc_legacy.to_dict() or {}
        if isinstance(legacy.get("colors"), list):
            return [str(x) for x in legacy.get("colors") if x]
        if isinstance(legacy, list):
            return [str(x) for x in legacy if x]
        if isinstance(legacy, dict) and legacy:
            vals = []
            for _, v in legacy.items():
                if isinstance(v, (str, int, float)):
                    vals.append(str(v))
                elif isinstance(v, dict) and "name" in v:
                    vals.append(str(v["name"]))
            if vals:
                return vals
    except Exception:
        pass
    return []


# -------- Rate storage (per Vendor) --------
def _rates_key(vendor_id):
    return f"{vendor_id}" if vendor_id else None

def _load_rates(vendor_id) -> dict:
    doc = db.collection("meta").document("powder_coating_rates").get()
    data = doc.to_dict() or {}
    node = data.get(_rates_key(vendor_id), {})
    return node if isinstance(node, dict) else {}

def _save_rates(vendor_id, rate_map: dict):
    ref = db.collection("meta").document("powder_coating_rates")
    ref.set({_rates_key(vendor_id): rate_map}, merge=True)

def _rate_for_product(rates_map: dict, product_name: str, item_code: str) -> float:
    # Back-compat per-code
    try:
        node = rates_map.get(item_code)
        if isinstance(node, dict):
            return float(node.get("rate", 0) or 0)
    except Exception:
        pass
    # Keyword rules
    name_lc = (product_name or "").lower()
    for rule in (rates_map.get("rules") or []):
        kw = str(rule.get("keyword") or "").lower().strip()
        if kw and kw in name_lc:
            try:
                return float(rule.get("rate") or 0)
            except Exception:
                return 0.0
    # Default
    try:
        return float(rates_map.get("default_rate") or 0)
    except Exception:
        return 0.0


# -------- Tx counters --------
def _tx_next_numbers():
    """Transactional counter increments for PCID and BILL number."""
    meta_ref = db.collection("meta").document("pc_counters")
    transaction = firestore.client().transaction()
    @firestore.transactional
    def _inc(trans):
        snap = meta_ref.get(transaction=trans)
        data = snap.to_dict() or {}
        last_pcid = int(data.get("last_pcid", 0))
        last_bill = int(data.get("last_bill_no", 0))
        new_pcid = last_pcid + 1
        new_bill = last_bill + 1
        trans.set(meta_ref, {"last_pcid": new_pcid, "last_bill_no": new_bill}, merge=True)
        return f"PC-{new_pcid:02d}", f"BILL-{new_bill:02d}"
    return _inc(transaction)


# -------- FPDF exports --------
def _export_pc_bill_pdf(pc_doc: dict, out_path: str):
    from fpdf import FPDF

    class PDF(FPDF):
        def header(self):
            self.set_fill_color(60, 60, 60)
            self.set_text_color(255, 255, 255)
            self.set_font("Arial", "B", 15)
            self.cell(0, 12, f"Powder Coating Bill: {pc_doc.get('bill_ref', '')}", 0, 1, "C", True)
            self.ln(6)

    pdf = PDF("L", "mm", "A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_auto_page_break(True, 15)
    pdf.set_text_color(0, 0, 0)

    # --- Bill Info ---
    pdf.set_font("Arial", "B", 12)
    info = [
        ("PCID", pc_doc.get("pcid", "")),
        ("Date", str(pc_doc.get("date", ""))),
        ("Branch", pc_doc.get("branch", "")),
        ("Vendor", pc_doc.get("vendor_name", "")),
    ]
    for k, v in info:
        pdf.cell(30, 8, f"{k}:", 0, 0)
        pdf.set_font("Arial", "", 12)
        pdf.cell(0, 8, str(v), 0, 1)
        pdf.set_font("Arial", "B", 12)
    pdf.ln(5)

    # --- Table Header ---
    headers = ["Sr", "Item Code", "Product Name", "Src Color", "PC Color", "Cond.", "Qty", "Rate", "Amount"]
    widths = [10, 25, 55, 25, 25, 18, 15, 22, 25]
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font("Arial", "B", 10)
    for h, w in zip(headers, widths):
        pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()

    # --- Table Rows ---
    pdf.set_font("Arial", "", 9)
    total_amount = 0
    fill = False

    for i, item in enumerate(pc_doc.get("items", []), start=1):
        pdf.set_fill_color(245, 245, 245) if fill else pdf.set_fill_color(255, 255, 255)
        fill = not fill

        try:
            amount = float(item.get("qty", 0)) * float(item.get("rate", 0))
        except Exception:
            amount = 0.0
        row = [
            str(i),
            item.get("item_code", ""),
            (item.get("product_name", "") or "")[:45],
            item.get("src_color", ""),
            item.get("pc_color", ""),
            item.get("condition", ""),
            str(item.get("qty", 0)),
            f"{item.get('rate', 0):,.2f}",
            f"{amount:,.2f}",
        ]

        for w, text in zip(widths, row):
            align = "R" if w in [22, 25] else "C" if w in [10, 15, 18] else "L"
            pdf.cell(w, 7, text, 1, 0, align, True)
        pdf.ln()

        total_amount += amount

        if pdf.get_y() > 270:
            pdf.add_page()

    # --- Total ---
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.set_fill_color(60, 60, 60)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(sum(widths[:-1]), 9, "TOTAL", 1, 0, "R", True)
    pdf.cell(widths[-1], 9, f"{total_amount:,.2f}", 1, 1, "R", True)

    pdf.output(out_path)


def _export_gate_pass_pdf(pcid: str, bill_ref: str, branch: str, vendor_name: str, items: list, out_path: str):
    from fpdf import FPDF
    import datetime

    class PDF(FPDF):
        def header(self):
            self.set_fill_color(80, 80, 80)
            self.set_text_color(255, 255, 255)
            self.set_font("Arial", "B", 15)
            self.cell(0, 12, f"Powder Coating Gate Pass: {pcid}", 0, 1, "C", True)
            self.ln(6)

    margin = 15
    pdf = PDF("L", "mm", "A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_auto_page_break(True, 15)
    pdf.set_text_color(0, 0, 0)

    # --- Details ---
    pdf.set_font("Arial", "B", 12)
    for k, v in [
        ("Bill Ref", bill_ref),
        ("Branch", branch),
        ("Vendor", vendor_name),
        ("Date", str(datetime.date.today())),
    ]:
        pdf.cell(30, 8, f"{k}:", 0, 0)
        pdf.set_font("Arial", "", 12)
        pdf.cell(0, 8, str(v), 0, 1)
        pdf.set_font("Arial", "B", 12)
    pdf.ln(5)

    # --- Table Header ---
    headers = ["Sr", "Item Code", "Product Name", "Current -> PC Color", "Cond.", "Qty"]
    widths = [10, 25, 70, 55, 20, 15]
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font("Arial", "B", 10)
    for h, w in zip(headers, widths):
        pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()

    # --- Rows ---
    pdf.set_font("Arial", "", 9)
    fill = False
    for i, item in enumerate(items, 1):
        color_pair = f"{item.get('src_color', '-') or '-'} -> {item.get('pc_color', '-') or '-'}"
        row = [
            str(i),
            item.get("item_code", ""),
            (item.get("product_name", "") or "")[:45],
            color_pair,
            item.get("condition", ""),
            str(item.get("qty", 0)),
        ]

        pdf.set_fill_color(245, 245, 245) if fill else pdf.set_fill_color(255, 255, 255)
        fill = not fill

        for w, text in zip(widths, row):
            align = "C" if w in [10, 15, 20] else "L"
            pdf.cell(w, 7, text, 1, 0, align, True)
        pdf.ln()

        if pdf.get_y() > 270:
            pdf.add_page()

    # --- Signatures Row (Left + Right) ---
    pdf.ln(15)
    pdf.set_text_color(100, 100, 100)
    pdf.set_font("Arial", "I", 10)

    page_width = 297 - 2 * margin
    half_width = page_width / 2

    pdf.cell(half_width, 8, "Authorized by _______________________", 0, 0, "L")
    pdf.cell(half_width, 8, "Receiver Signature ___________________", 0, 1, "R")

    pdf.output(out_path)


# -------- Inventory (products.qty[branch][color][condition]) --------
def _get_product_doc_by_code(item_code: str):
    q = db.collection("products").where("item_code", "==", item_code).limit(1).get()
    if not q:
        raise RuntimeError(f"Product not found for code {item_code}")
    return q[0].reference

def _tx_update_qty(item_code: str, branch: str, color: str, condition: str, delta: float, allow_negative: bool = False):
    """
    Transactionally adjust nested qty; prevents negatives unless allowed.
    Uses set(merge=True) with minimal nested maps to avoid field path escaping.
    """
    ref = _get_product_doc_by_code(item_code)
    tr = firestore.client().transaction()

    @firestore.transactional
    def _do(tx):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() or {}
        qty = data.get("qty") or {}

        curr = int(((qty.get(branch) or {}).get(color) or {}).get(condition) or 0)
        newv = curr + int(delta)
        if not allow_negative and newv < 0:
            raise RuntimeError(f"Insufficient stock for {item_code} [{branch}/{color}/{condition}] (have {curr}, need {abs(int(delta))})")

        update_map = {"qty": {branch: {color: {condition: newv}}}}
        tx.set(ref, update_map, merge=True)

    _do(tr)

def _subtract_inventory_for_pc(branch, items):
    for it in items:
        code = str(it.get("item_code") or "")
        src_color = str(it.get("src_color") or "No Color")
        cond = str(it.get("condition") or "New")
        qty = float(it.get("qty") or 0)
        if code and qty > 0:
            _tx_update_qty(code, branch, src_color, cond, -qty, allow_negative=False)

def _add_inventory_after_pc(branch, items):
    for it in items:
        code = str(it.get("item_code") or "")
        pc_color = str(it.get("pc_color") or "No Color")
        qty = float(it.get("qty") or 0)
        if code and qty > 0:
            _tx_update_qty(code, branch, pc_color, "New", +qty, allow_negative=True)


# -------- Accounts & JEs (kept intact) --------
def _ensure_system_offset_account(user_data):
    equity_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
    if equity_q:
        equity_account_id = equity_q[0].id
        equity_account_name = (equity_q[0].to_dict() or {}).get("name", "System Offset Account")
    else:
        from modules.chart_of_accounts import _generate_code_once_tx
        code = _generate_code_once_tx(db, "Asset")
        branch_list = user_data.get("branch", [])
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
    return equity_account_id, equity_account_name

def _post_pc_bill_je(user_data, branch, vendor_party_id, vendor_name, total_amount, bill_ref):
    if total_amount <= 0:
        return None

    sys_acc_id, sys_acc_name = _ensure_system_offset_account(user_data)

    party_doc = db.collection("parties").document(vendor_party_id).get()
    party = party_doc.to_dict() or {}
    vendor_acc_id = party.get("coa_account_id")
    if not vendor_acc_id:
        raise RuntimeError("Selected vendor does not have a linked COA account.")

    def _curr_bal(acc_id):
        try:
            a = db.collection("accounts").document(acc_id).get().to_dict() or {}
            return float(a.get("current_balance", 0.0) or 0.0)
        except Exception:
            return 0.0

    debit_line  = {"account_id": sys_acc_id,    "account_name": sys_acc_name, "debit": -float(total_amount), "credit": 0, "balance_before": _curr_bal(sys_acc_id)}
    credit_line = {"account_id": vendor_acc_id, "account_name": vendor_name,  "debit": 0, "credit": float(total_amount), "balance_before": _curr_bal(vendor_acc_id)}

    now_server = firestore.SERVER_TIMESTAMP
    branch_val = branch or (user_data.get("branch")[0] if isinstance(user_data.get("branch"), list) else user_data.get("branch") or "-")
    je = {
        "date": now_server,
        "created_at": now_server,
        "created_by": user_data.get("email","system"),
        "purpose": "Vendor Bill",
        "reference_no": bill_ref,
        "branch": branch_val,
        "description": f"Powder Coating Bill {bill_ref} for vendor {vendor_name}",
        "lines": [debit_line, credit_line],
        "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
        "meta": {"kind": "opening_balance"}
    }
    je_ref = db.collection("journal_entries").document()
    je_ref.set(je)

    # Only update Vendor A/P balance; leave System Offset at 0
    db.collection("accounts").document(vendor_acc_id).update({"current_balance": firestore.Increment(float(total_amount))})
    return je_ref.id

def _post_payment_je(user_data, bill_ref, cashbank_account_id, pcid, amount):
    if amount <= 0:
        return None
    q = db.collection("pc_bills").where("bill_ref","==",bill_ref).limit(1).get()
    if not q:
        raise RuntimeError("Bill not found for payment.")
    bill = q[0].to_dict() or {}
    vendor_party_id = bill.get("vendor_party_id")
    party_doc = db.collection("parties").document(vendor_party_id).get()
    party = party_doc.to_dict() or {}
    vendor_acc_id = party.get("coa_account_id")
    if not vendor_acc_id:
        raise RuntimeError("Vendor has no COA account.")

    def _curr_bal(acc_id):
        try:
            a = db.collection("accounts").document(acc_id).get().to_dict() or {}
            return float(a.get("current_balance", 0.0) or 0.0)
        except Exception:
            return 0.0

    now = firestore.SERVER_TIMESTAMP
    debit_line  = {"account_id": vendor_acc_id,     "account_name": party.get("name") or "Vendor", "debit": float(amount), "credit": 0, "balance_before": _curr_bal(vendor_acc_id)}
    credit_line = {"account_id": cashbank_account_id,"account_name": "Cash/Bank",                    "debit": 0,            "credit": float(amount), "balance_before": _curr_bal(cashbank_account_id)}
    je = {
        "date": now, "created_at": now, "created_by": user_data.get("email","system"),
        "purpose": "Vendor Payment", "reference_no": bill_ref, "branch": bill.get("branch"),
        "description": f"Payment for {bill_ref} (PC {pcid})",
        "lines": [debit_line, credit_line],
        "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
        "meta": {"kind": "powder_coating_payment"}
    }
    je_ref = db.collection("journal_entries").document(); je_ref.set(je)

    # Update balances: Vendor (debit -> less negative), Cash/Bank (credit -> reduce asset)
    db.collection("accounts").document(vendor_acc_id).update({"current_balance": firestore.Increment(-float(amount))})
    db.collection("accounts").document(cashbank_account_id).update({"current_balance": firestore.Increment(-float(amount))})
    return je_ref.id


# ============ Windows & Dialogs (UI restyled to match view_inventory theme) ============

# Shared style used across the module to match app theme
_COMMON_STYLE = """
    QWidget { background-color: #f4f6f9; font-family: "Segoe UI", sans-serif; }
    QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QTextEdit {
        padding: 6px 8px; border: 1px solid #d0d6db; border-radius: 6px;
        background: white; font-size: 13px;
    }
    QPushButton {
        padding: 6px 12px; border-radius: 8px;
        background-color: #2d98da; color: white; font-weight: 700;
    }
    QPushButton:hover { background-color: #1e77c2; }
    QHeaderView::section { background-color: #dfe6e9; font-weight: 700; padding: 8px; border: 1px solid #c8d3d8; }
    QTableWidget {
        background-color: white; border: 1px solid #dcdde1; font-size: 13px;
        alternate-background-color: #fafafa; selection-background-color: #e8f2ff;
    }
    QTableWidget::item { padding: 6px; }
    QLabel#Title { color: #2d3436; font-size: 18px; font-weight: 900; margin: 10px 0; }
    QLabel#SubTitle { color: #2d3436; font-size: 13px; font-weight: 700; }
"""

class PowderCoatingMain(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data or {}
        self.setWindowTitle("Powder Coating Cycle")
        self.setMinimumSize(1100, 640)
        self.setStyleSheet(_COMMON_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Title
        title = QLabel("🖌️ Powder Coating Cycle")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        root.addWidget(title)

        # Action row (filters & actions)
        action_row = QHBoxLayout(); action_row.setSpacing(8)
        # Keep the same actions as before (wired to existing handlers)
        btn_add = QPushButton("➕ Add New PC Order")
        btn_add.clicked.connect(self._open_add_pc)
        btn_rates = QPushButton("⚖️ Modify Rates")
        btn_rates.clicked.connect(self._open_rates)
        btn_inprog = QPushButton("📋 Grouped In-Progress")
        btn_inprog.clicked.connect(self._open_inprogress_grouped)
        btn_complete = QPushButton("✅ Mark Selected Completed")
        btn_complete.clicked.connect(self._mark_selected_completed)

        # Slightly smaller action buttons
        for b in (btn_add, btn_inprog, btn_rates, btn_complete):
            b.setMinimumHeight(36)

        action_row.addWidget(btn_add)
        action_row.addWidget(btn_inprog)
        action_row.addWidget(btn_rates)
        action_row.addStretch(1)
        action_row.addWidget(btn_complete)
        root.addLayout(action_row)

        # Table card (wrap in QFrame to give card-like visual)
        card = QFrame()
        card.setStyleSheet("QFrame { background: white; border: 1px solid #e6e9ec; border-radius: 12px; }")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 12, 12, 12)
        card_l.setSpacing(8)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["PCID","Bill","Status","Date","Branch","Vendor","Lines","Qty","Total"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        card_l.addWidget(self.table)

        root.addWidget(card, 1)

        # small footer: info label
        self.info_lbl = QLabel("Double-click a row for actions (Bill / Gate Pass / Make Payment / Change Status).")
        self.info_lbl.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(self.info_lbl)

        # load orders
        self._load_orders()

    # --- unchanged logic; same method names and internals as original file ---
    def _load_orders(self):
        self.table.setRowCount(0)
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str):
            branches = [branches] if branches else []
        q = db.collection("powder_coating_orders").order_by("created_at", direction=firestore.Query.DESCENDING)
        docs = q.get()
        for d in docs:
            row = d.to_dict() or {}
            if branches and row.get("branch") not in branches:
                continue
            r = self.table.rowCount(); self.table.insertRow(r)
            def cell(txt, align=Qt.AlignLeft):
                it = QTableWidgetItem(str(txt or "")); it.setTextAlignment(align | Qt.AlignVCenter); return it
            self.table.setItem(r,0, cell(row.get("pcid")))
            self.table.setItem(r,1, cell(row.get("bill_ref")))
            self.table.setItem(r,2, cell(row.get("status","")))
            self.table.setItem(r,3, cell(str(row.get("date",""))))
            self.table.setItem(r,4, cell(row.get("branch")))
            self.table.setItem(r,5, cell(row.get("vendor_name")))
            self.table.setItem(r,6, cell(int(row.get("totals",{}).get("lines",0)), Qt.AlignRight))
            self.table.setItem(r,7, cell(row.get("totals",{}).get("qty",0), Qt.AlignRight))
            self.table.setItem(r,8, cell(_fmt_money(row.get("totals",{}).get("net",0)), Qt.AlignRight))

    def _selected_order_id(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None
        row = sel[0].row()
        return self.table.item(row, 0).text() if self.table.item(row,0) else None

    def _mark_selected_completed(self):
        pcid = self._selected_order_id()
        if not pcid:
            QMessageBox.information(self, "Select Order", "Please select an order in the table.")
            return
        q = db.collection("powder_coating_orders").where("pcid","==",pcid).limit(1).get()
        if not q:
            QMessageBox.warning(self, "Not found", f"Order {pcid} not found.")
            return
        doc = q[0]
        order = doc.to_dict() or {}
        if order.get("status") == "COMPLETED":
            QMessageBox.information(self, "Already Completed", "This order is already marked completed.")
            return
        _add_inventory_after_pc(order.get("branch"), order.get("items") or [])
        db.collection("powder_coating_orders").document(doc.id).update({"status": "COMPLETED"})
        QMessageBox.information(self, "Completed", f"Order {pcid} marked COMPLETED and inventory added back.")
        self._load_orders()

    def _open_add_pc(self):
        dlg = AddPowderCoatingDialog(self.user_data, parent=self)
        if dlg.exec_():
            self._load_orders()

    def _open_rates(self):
        dlg = ModifyRatesDialog(self.user_data, parent=self)
        dlg.exec_()

    def _open_inprogress_grouped(self):
        w = InProgressGroupedWindow(self.user_data, parent=self)
        w.show()

    # ---- Double-click dialog with 4 actions (kept intact) ----
    def _on_row_double_clicked(self, item):
        row = item.row()
        pcid = self.table.item(row, 0).text()
        bill_ref = self.table.item(row, 1).text()
        vendor = self.table.item(row, 5).text()
        date_txt = self.table.item(row, 3).text()

        dlg = QDialog(self); dlg.setWindowTitle(f"PC Order {pcid}")
        lay = QVBoxLayout(dlg)
        info = QLabel(f"<b>{pcid}</b> — {vendor} — {date_txt}"); info.setTextFormat(Qt.RichText)
        lay.addWidget(info)
        btns = QHBoxLayout()
        b1 = QPushButton("Download Bill PDF")
        b2 = QPushButton("Download Gate Pass PDF")
        b3 = QPushButton("Make Payment")
        b4 = QPushButton("Change Status")
        for b in (b1,b2,b3,b4): btns.addWidget(b)
        lay.addLayout(btns)

        def _fetch_order():
            qq = db.collection("powder_coating_orders").where("pcid","==",pcid).limit(1).get()
            if not qq:
                QMessageBox.warning(dlg,"Not found","Order not found.")
                return None, None
            return qq[0], qq[0].to_dict() or {}

        def _download_bill():
            doc, order = _fetch_order()
            if not order: return
            tmp = tempfile.gettempdir(); path = os.path.join(tmp, f"{bill_ref}.pdf")
            doc_for_pdf = dict(order); doc_for_pdf["date"] = doc_for_pdf.get("date") or date_txt
            _export_pc_bill_pdf(doc_for_pdf, path)
            dest, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF As…", f"{bill_ref}.pdf", "PDF Files (*.pdf)")
            if dest:
                try: shutil.copyfile(path, dest)
                except Exception as e: QMessageBox.warning(self,"Save failed", str(e))
                try:
                    if sys.platform.startswith("win"): os.startfile(dest)  # nosec
                except Exception:
                    pass

        def _download_gate():
            doc, order = _fetch_order()
            if not order: return
            tmp = tempfile.gettempdir(); path = os.path.join(tmp, f"GP-{pcid}.pdf")
            _export_gate_pass_pdf(pcid, bill_ref, order.get("branch"), order.get("vendor_name"), order.get("items") or [], path)
            dest, _ = QFileDialog.getSaveFileName(self, "Save Gate Pass PDF As…", f"GP-{pcid}.pdf", "PDF Files (*.pdf)")
            if dest:
                try: shutil.copyfile(path, dest)
                except Exception as e: QMessageBox.warning(self,"Save failed", str(e))
                try:
                    if sys.platform.startswith("win"): os.startfile(dest)  # nosec
                except Exception:
                    pass

        def _make_payment():
            d = QDialog(self); d.setWindowTitle("Make Payment")
            f = QFormLayout(d)
            amt = QDoubleSpinBox(); amt.setDecimals(2); amt.setMaximum(1e12)
            acct = QLineEdit(); acct.setPlaceholderText("Cash/Bank Account ID")
            f.addRow("Amount:", amt); f.addRow("Debit Account (Cash/Bank ID):", acct)
            bb = QHBoxLayout(); ok=QPushButton("Post"); cc=QPushButton("Cancel")
            ok.clicked.connect(d.accept); cc.clicked.connect(d.reject)
            bb.addStretch(1); bb.addWidget(ok); bb.addWidget(cc); f.addRow(bb)
            if d.exec_():
                amount = float(amt.value() or 0)
                debit_acc = acct.text().strip()
                if amount <= 0 or not debit_acc:
                    QMessageBox.warning(self,"Payment","Enter amount and debit account."); return
                try:
                    _post_payment_je(self.user_data, bill_ref, debit_acc, pcid, amount)
                    QMessageBox.information(self,"Payment","Payment posted.")
                except Exception as e:
                    QMessageBox.warning(self,"Payment failed", str(e))

        def _change_status():
            d = QDialog(self); d.setWindowTitle("Change Status")
            f=QFormLayout(d)
            cb = QComboBox(); cb.addItems(["IN_PROGRESS","COMPLETED"])
            f.addRow("Status:", cb)
            bb=QHBoxLayout(); ok=QPushButton("Apply"); cc=QPushButton("Cancel")
            ok.clicked.connect(d.accept); cc.clicked.connect(d.reject)
            bb.addStretch(1); bb.addWidget(ok); bb.addWidget(cc); f.addRow(bb)
            if d.exec_():
                newst = cb.currentText()
                doc, order = _fetch_order()
                if not order: return
                if order.get("status") != newst:
                    db.collection("powder_coating_orders").document(doc.id).update({"status": newst})
                    if newst == "COMPLETED":
                        _add_inventory_after_pc(order.get("branch"), order.get("items") or [])
                    QMessageBox.information(self,"Updated", f"Status set to {newst}.")
                    self._load_orders()

        b1.clicked.connect(_download_bill)
        b2.clicked.connect(_download_gate)
        b3.clicked.connect(_make_payment)
        b4.clicked.connect(_change_status)
        dlg.exec_()


class AddPowderCoatingDialog(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Add New Powder Coating Order")
        self.setMinimumWidth(980)
        self.setStyleSheet(_COMMON_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("➕ Add New Powder Coating Order")
        title.setObjectName("SubTitle")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(title)

        form = QFormLayout()
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True)

        # Branch dropdown
        self.branch_cb = QComboBox()
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        for b in branches: self.branch_cb.addItem(b)
        if not branches: self.branch_cb.addItem("-")

        # Vendor (party)
        self.vendor_cb = QComboBox()
        self._load_vendors()

        self.manual_id = QLineEdit(); self.manual_id.setPlaceholderText("Optional manual ID")
        self.notes = QTextEdit(); self.notes.setPlaceholderText("Optional notes")
        self.btn_pick = QPushButton("Pick Inventory + Rates")
        self.btn_pick.clicked.connect(self._pick_inventory)

        # Items live table
        self.items_tbl = QTableWidget(0, 9)
        self.items_tbl.setHorizontalHeaderLabels(["Item Code","Name","Src Color","PC Color","Cond.","Qty","Rate","Amount","Unit"])
        self.items_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.items_tbl.verticalHeader().setVisible(False)
        self.items_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_tbl.setAlternatingRowColors(True)

        row_btns = QHBoxLayout()
        self.btn_edit_row = QPushButton("Edit Selected"); self.btn_edit_row.clicked.connect(self._edit_selected_row)
        self.btn_remove_row = QPushButton("Remove Selected"); self.btn_remove_row.clicked.connect(self._remove_selected_row)
        self.btn_add_more = QPushButton("Add More Items"); self.btn_add_more.clicked.connect(self._pick_inventory)
        row_btns.addWidget(self.btn_edit_row); row_btns.addWidget(self.btn_remove_row); row_btns.addStretch(1); row_btns.addWidget(self.btn_add_more)

        self.items = []
        self._preselected = {}

        form.addRow("Date:", self.date)
        form.addRow("Branch:", self.branch_cb)
        form.addRow("Vendor:", self.vendor_cb)
        form.addRow("Manual ID:", self.manual_id)
        form.addRow(self.btn_pick)
        form.addRow(self.items_tbl)
        form.addRow(row_btns)
        form.addRow("Notes:", self.notes)

        layout.addLayout(form)

        btns = QHBoxLayout()
        self.btn_save = QPushButton("Save Order, Bill & Gate Pass")
        self.btn_save.clicked.connect(self._save)
        btns.addStretch(1); btns.addWidget(self.btn_save)
        layout.addLayout(btns)

    def _load_vendors(self):
        q = db.collection("parties").select(["name","type","coa_account_id"]).get()
        self.vendor_cb.clear(); self.vendor_cb.addItem("-- Select Vendor --", None)
        for d in q:
            data = d.to_dict() or {}
            typ = str(data.get("type","")).lower()
            if typ in ("vendor","supplier","both"):
                self.vendor_cb.addItem(data.get("name","[No Name]"), d.id)

    def _refresh_items_table(self):
        self.items_tbl.setRowCount(0)
        for it in (self.items or []):
            r = self.items_tbl.rowCount(); self.items_tbl.insertRow(r)
            def cell(v): return QTableWidgetItem(str(v if v is not None else ""))
            amt = float(it.get("qty",0)) * float(it.get("rate",0))
            self.items_tbl.setItem(r, 0, cell(it.get("item_code")))
            self.items_tbl.setItem(r, 1, cell(it.get("product_name")))
            self.items_tbl.setItem(r, 2, cell(it.get("src_color")))
            self.items_tbl.setItem(r, 3, cell(it.get("pc_color")))
            self.items_tbl.setItem(r, 4, cell(it.get("condition")))
            self.items_tbl.setItem(r, 5, cell(it.get("qty")))
            self.items_tbl.setItem(r, 6, cell(it.get("rate")))
            self.items_tbl.setItem(r, 7, cell(_fmt_money(amt)))
            self.items_tbl.setItem(r, 8, cell(it.get("unit") or "sqft"))

    def _selected_row_index(self):
        rows = self.items_tbl.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _edit_selected_row(self):
        idx = self._selected_row_index()
        if idx is None:
            QMessageBox.information(self, "Select a row", "Please select an item row to edit.")
            return
        self.items[idx] = _edit_single_item_dialog(self, self.items[idx])
        self._refresh_items_table()

    def _remove_selected_row(self):
        idx = self._selected_row_index()
        if idx is None:
            QMessageBox.information(self, "Select a row", "Please select an item row to remove.")
            return
        del self.items[idx]
        self._refresh_items_table()

    def _pick_inventory(self):
        branch = self.branch_cb.currentText().strip()
        if branch in ("", "-"):
            QMessageBox.warning(self, "Select Branch", "Please select a valid branch first.")
            return
        if not InventorySelectorDialog:
            QMessageBox.warning(self, "Missing", "Inventory selector not available in this build.")
            return

        dlg = InventorySelectorDialog(branch=branch, preselected=self._preselected, parent=self)
        if dlg.exec_():
            picked = dlg.selected
            vendor_id = self.vendor_cb.currentData()
            rates_map = _load_rates(vendor_id)  # vendor-only rates
            colors_all = _load_pc_colors()
            items, pre = [], {}
            for r in picked:
                code = str(r.get("item_code") or r.get("code") or "").strip()
                qty  = float(r.get("qty") or 0)
                if qty <= 0: continue
                product_name = r.get("product_name") or r.get("name") or code
                rate = _rate_for_product(rates_map, product_name, code)

                src_color = r.get("color")
                pc_color_default = src_color if src_color in (colors_all or []) else ((colors_all or ["No Color"])[0])
                unit = "sqft"

                item = {
                    "item_code": code,
                    "product_name": product_name,
                    "src_color": src_color,
                    "pc_color": pc_color_default,
                    "condition": r.get("condition"),
                    "qty": qty,
                    "rate": rate,
                    "unit": unit,
                    "amount": qty * rate,
                    "meta": {
                        "length": r.get("length"), "width": r.get("width"),
                        "height": r.get("height"), "gauge": r.get("gauge")
                    }
                }
                items.append(item)
                pre_key = f"{branch}|{code}|{r.get('color')}|{r.get('condition')}"
                pre[pre_key] = qty

            edited = _edit_rates_dialog(self, items, enable_color_select=True, show_src_color=True)
            self.items.extend(edited)
            self._preselected.update(pre)
            self._refresh_items_table()

    def _save(self):
        if not self.items:
            QMessageBox.warning(self, "No items", "Please pick inventory items and add rates.")
            return
        vendor_id = self.vendor_cb.currentData(); vendor_name = self.vendor_cb.currentText()
        if not vendor_id:
            QMessageBox.warning(self, "Select vendor", "Please select a vendor.")
            return

        pcid, bill_ref = _tx_next_numbers()
        branch = self.branch_cb.currentText().strip()
        date_py = self.date.date().toPyDate()
        total_qty = sum(float(i.get("qty",0) or 0) for i in self.items)
        total_net = sum(float(i.get("amount",0) or 0) for i in self.items)

        payload = {
            "pcid": pcid,
            "manual_id": (self.manual_id.text().strip() or None),
            "branch": branch,
            "vendor_party_id": vendor_id,
            "vendor_name": vendor_name,
            "date": firestore.SERVER_TIMESTAMP,
            "status": "IN_PROGRESS",
            "items": self.items,
            "totals": {"lines": len(self.items), "qty": total_qty, "net": total_net},
            "bill_ref": bill_ref,
            "notes": self.notes.toPlainText().strip() or None,
            "created_by": self.user_data.get("email","system"),
            "created_at": firestore.SERVER_TIMESTAMP
        }

        # 1) Subtract SOURCE inventory immediately
        try:
            _subtract_inventory_for_pc(branch, self.items)
        except Exception as e:
            QMessageBox.warning(self, "Inventory", f"Could not subtract inventory: {e}")
            return

        # 2) Save single combined document
        order_ref = db.collection("powder_coating_orders").document()
        payload["bill"] = {
            "bill_ref": bill_ref,
            "status": "In Progress",
            "je_id": None
        }
        order_ref.set(payload)

        # 4) Post JE: Dr System Offset (no balance change), Cr Vendor (liability increases)
        try:
            je_id = _post_pc_bill_je(self.user_data, branch, vendor_id, vendor_name, total_net, bill_ref)
            if je_id:
                order_ref.update({"je_id": je_id})
        except Exception as e:
            QMessageBox.warning(self, "JE not posted", f"Order saved but JE failed: {e}")

        QMessageBox.information(self, "Saved", f"Order {pcid} saved successfully.\nYou can download the Bill or Gate Pass later from the order viewer.")
        self.accept()


class InProgressGroupedWindow(QWidget):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Grouped In-Progress Items")
        self.setMinimumSize(980, 600)
        self.setStyleSheet(_COMMON_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("📋 Grouped In-Progress Items")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        root.addWidget(title)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Item Code","Name","Src Color","PC Color","Total Qty (In-Progress)","Orders"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        self._load()

    def _load(self):
        self.table.setRowCount(0)
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        q = db.collection("powder_coating_orders").where("status","==","IN_PROGRESS").get()
        agg = {}
        for d in q:
            row = d.to_dict() or {}
            if branches and row.get("branch") not in branches: continue
            for it in (row.get("items") or []):
                key = (it.get("item_code"), it.get("src_color"), it.get("pc_color"))
                g = agg.setdefault(key, {"name": it.get("product_name"), "qty": 0.0, "orders": set()})
                try: g["qty"] += float(it.get("qty") or 0)
                except Exception: pass
                g["orders"].add(row.get("pcid"))
        for (code, src_color, pc_color), v in agg.items():
            r = self.table.rowCount(); self.table.insertRow(r)
            def cell(x, align=Qt.AlignLeft):
                it = QTableWidgetItem(str(x or "")); it.setTextAlignment(align | Qt.AlignVCenter); return it
            self.table.setItem(r,0,cell(code))
            self.table.setItem(r,1,cell(v["name"]))
            self.table.setItem(r,2,cell(src_color))
            self.table.setItem(r,3,cell(pc_color))
            self.table.setItem(r,4,cell(v["qty"], Qt.AlignRight))
            self.table.setItem(r,5,cell(", ".join(sorted(v["orders"]))))


# -------- Modify Rates (Keyword Rules) --------
class ModifyRatesDialog(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Modify Powder Coating Rates")
        self.setMinimumSize(760, 520)
        self.setStyleSheet(_COMMON_STYLE)

        form = QFormLayout(self)

        self.vendor_cb = QComboBox(); self._load_vendors()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Keyword (case-insensitive)", "Rate", "Unit"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        self.default_rate = QDoubleSpinBox(); self.default_rate.setDecimals(2); self.default_rate.setMaximum(1e9)

        tb = QToolBar(); tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        act_add = QAction("Add Rule", self); act_add.triggered.connect(self._add_rule_row)
        act_save = QAction("Save Rules", self); act_save.triggered.connect(self._save)
        tb.addAction(act_add); tb.addAction(act_save)

        layout = QVBoxLayout(self)
        title = QLabel("⚖️ Modify Powder Coating Rates")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(title)
        layout.addLayout(form)

        form.addRow("Vendor:", self.vendor_cb)
        form.addRow(tb)
        form.addRow(self.table)
        form.addRow("Default Rate (fallback):", self.default_rate)

        self._load_rules()
        self.vendor_cb.currentIndexChanged.connect(self._load_rules)

    def _load_vendors(self):
        q = db.collection("parties").select(["name","type"]).get()
        self.vendor_cb.clear(); self.vendor_cb.addItem("-- Select Vendor --", None)
        for d in q:
            data = d.to_dict() or {}
            typ = str(data.get("type","")).lower()
            if typ in ("vendor","supplier","both"):
                self.vendor_cb.addItem(data.get("name","[No Name]"), d.id)

    def _add_rule_row(self, kw: str = "", rate: float = 0.0, unit: str = "sqft"):
        r = self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(kw))
        ds = QDoubleSpinBox(); ds.setMaximum(1e9); ds.setDecimals(2); ds.setValue(float(rate))
        self.table.setCellWidget(r, 1, ds)
        cb = QComboBox(); cb.addItems(["sqft", "rft", "cbft"])
        if unit in ["sqft", "rft", "cbft"]: cb.setCurrentText(unit)
        self.table.setCellWidget(r, 2, cb)

    def _load_rules(self):
        vendor = self.vendor_cb.currentData()
        self.table.setRowCount(0); self.default_rate.setValue(0.0)
        if not vendor:
            return
        rules_doc = _load_rates(vendor)
        for rule in (rules_doc.get("rules") or []):
            self._add_rule_row(rule.get("keyword",""), rule.get("rate") or 0, rule.get("unit", "sqft"))
        try:
            self.default_rate.setValue(float(rules_doc.get("default_rate") or 0.0))
        except Exception:
            pass

    def _save(self):
        vendor = self.vendor_cb.currentData()
        if not vendor:
            QMessageBox.warning(self, "Vendor", "Select a vendor first.")
            return
        rules = []
        for r in range(self.table.rowCount()):
            kw_item = self.table.item(r, 0)
            kw = kw_item.text().strip() if kw_item else ""
            rate_widget = self.table.cellWidget(r, 1)
            unit_widget = self.table.cellWidget(r, 2)
            try:
                rate_val = float(rate_widget.value())
            except Exception:
                rate_val = 0.0
            unit_val = unit_widget.currentText() if unit_widget else "sqft"
            if kw:
                rules.append({"keyword": kw, "rate": rate_val, "unit": unit_val})
        payload = {"rules": rules, "default_rate": float(self.default_rate.value() or 0.0)}
        _save_rates(vendor, payload)
        QMessageBox.information(self, "Saved", "Rates saved.")
        self.accept()


# ---------- Helper dialogs used by the module (kept unchanged, referenced functions) ----------
# Note: The functions _edit_single_item_dialog and _edit_rates_dialog are referenced
# in the original implementation. Ensure they exist elsewhere in your codebase.
# If not present, you will need to re-add them here (they were in original file).

# End of file

# -------- Inline editors --------

def _edit_single_item_dialog(parent, item):
    dlg = QDialog(parent); dlg.setWindowTitle("Edit Item")
    lay = QFormLayout(dlg)

    code = QLabel(item.get("item_code",""))
    name = QLabel(item.get("product_name",""))

    colors = _load_pc_colors()
    src_lbl = QLabel(str(item.get("src_color") or ""))
    pc_cb = QComboBox()
    if colors: pc_cb.addItems(colors)
    pc_init = str(item.get("pc_color") or item.get("src_color") or "")
    if pc_init and (pc_init not in (colors or [])): pc_cb.insertItem(0, pc_init)
    if pc_init: pc_cb.setCurrentText(pc_init)

    cond = QLineEdit(str(item.get("condition") or ""))
    qty_sp = QDoubleSpinBox(); qty_sp.setDecimals(3); qty_sp.setMaximum(1e9); qty_sp.setValue(float(item.get("qty") or 0))
    rate_sp = QDoubleSpinBox(); rate_sp.setDecimals(2); rate_sp.setMaximum(1e9); rate_sp.setValue(float(item.get("rate") or 0))

    unit_cb = QComboBox(); unit_cb.addItems(["sqft","rft","cbft"]); unit_cb.setCurrentText(item.get("unit") or "sqft")

    lay.addRow("Item Code:", code)
    lay.addRow("Name:", name)
    lay.addRow("Source Color:", src_lbl)
    lay.addRow("PC Color:", pc_cb)
    lay.addRow("Condition:", cond)
    lay.addRow("Qty:", qty_sp)
    lay.addRow("Rate:", rate_sp)
    lay.addRow("Unit:", unit_cb)

    bb = QHBoxLayout(); ok = QPushButton("OK"); cc = QPushButton("Cancel")
    ok.clicked.connect(dlg.accept); cc.clicked.connect(dlg.reject)
    bb.addStretch(1); bb.addWidget(ok); bb.addWidget(cc); lay.addRow(bb)

    if dlg.exec_():
        obj = dict(item)
        obj.update({
            "pc_color": pc_cb.currentText(),
            "condition": cond.text().strip() or item.get("condition"),
            "qty": float(qty_sp.value()),
            "rate": float(rate_sp.value()),
            "unit": unit_cb.currentText(),
        })
        obj["amount"] = float(obj["qty"]) * float(obj["rate"])
        return obj
    return item


def _edit_rates_dialog(parent, items, enable_color_select=False, show_src_color=False):
    """
    Multi-row editor before saving:
    - If enable_color_select: per-row PC Color combobox
    - If show_src_color: include read-only Src Color column
    """
    dlg = QDialog(parent); dlg.setWindowTitle("Confirm Items / Rates")
    lay = QVBoxLayout(dlg)

    cols = ["Item Code","Name"]
    if show_src_color: cols.append("Src Color")
    if enable_color_select: cols.append("PC Color")
    cols.extend(["Cond.","Qty","Rate","Amount","Unit"])

    tbl = QTableWidget(0, len(cols))
    tbl.setHorizontalHeaderLabels(cols)
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    tbl.verticalHeader().setVisible(False)
    tbl.setAlternatingRowColors(True)
    lay.addWidget(tbl)

    all_colors = _load_pc_colors() if enable_color_select else []

    def add_row(x):
        r = tbl.rowCount(); tbl.insertRow(r)
        c = 0
        tbl.setItem(r, c, QTableWidgetItem(x["item_code"])); c += 1
        tbl.setItem(r, c, QTableWidgetItem(x["product_name"])); c += 1

        if show_src_color:
            it = QTableWidgetItem(str(x.get("src_color") or "")); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            tbl.setItem(r, c, it); c += 1

        if enable_color_select:
            pc_widget = QComboBox()
            if all_colors: pc_widget.addItems(all_colors)
            init_color = str(x.get("pc_color") or x.get("src_color") or "")
            if init_color and (init_color not in (all_colors or [])):
                pc_widget.insertItem(0, init_color)
            if init_color: pc_widget.setCurrentText(init_color)
            tbl.setCellWidget(r, c, pc_widget); c += 1

        tbl.setItem(r, c, QTableWidgetItem(str(x.get("condition")))); c += 1
        tbl.setItem(r, c, QTableWidgetItem(str(x.get("qty")))); c += 1

        rate_sp = QDoubleSpinBox(); rate_sp.setDecimals(2); rate_sp.setMaximum(1e9)
        rate_sp.setValue(float(x.get("rate") or 0))
        tbl.setCellWidget(r, c, rate_sp); c += 1

        amt = float(x.get("qty",0)) * float(x.get("rate",0))
        amt_item = QTableWidgetItem(_fmt_money(amt)); amt_item.setFlags(amt_item.flags() & ~Qt.ItemIsEditable)
        tbl.setItem(r, c, amt_item); c += 1

        unit_cb = QComboBox(); unit_cb.addItems(["sqft","rft","cbft"])
        if x.get("unit") in ["sqft","rft","cbft"]:
            unit_cb.setCurrentText(x.get("unit"))
        tbl.setCellWidget(r, c, unit_cb)

    for it in items:
        add_row(it)

    bb = QHBoxLayout(); ok = QPushButton("OK"); cc = QPushButton("Cancel")
    ok.clicked.connect(dlg.accept); cc.clicked.connect(dlg.reject)
    bb.addStretch(1); bb.addWidget(ok); bb.addWidget(cc); lay.addLayout(bb)

    if dlg.exec_():
        out = []
        for r in range(tbl.rowCount()):
            c = 0
            code = tbl.item(r, c).text(); c += 1
            name = tbl.item(r, c).text(); c += 1
            src_color = None
            if show_src_color:
                src_color = tbl.item(r, c).text() if tbl.item(r, c) else None
                c += 1
            pc_color = None
            if enable_color_select:
                pc_widget = tbl.cellWidget(r, c)
                pc_color = pc_widget.currentText() if pc_widget else None
                c += 1
            cond = tbl.item(r, c).text(); c += 1
            qty  = float(tbl.item(r, c).text()); c += 1
            rate = float(tbl.cellWidget(r, c).value()); c += 1
            c += 1  # skip displayed amount
            unit = tbl.cellWidget(r, c).currentText()
            out.append({
                "item_code": code,
                "product_name": name,
                "src_color": src_color,
                "pc_color": pc_color,
                "condition": cond,
                "qty": qty,
                "rate": rate,
                "unit": unit,
                "amount": qty * rate
            })
        return out
    return items
