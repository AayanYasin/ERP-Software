# modules/powder_coating_cycle.py
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit,
    QHeaderView, QAbstractItemView, QMessageBox, QDateEdit, QFileDialog, QGroupBox,
    QSpinBox, QDoubleSpinBox, QToolBar, QAction
)
from PyQt5.QtCore import Qt, QDate
from firebase.config import db
from firebase_admin import firestore
import datetime, uuid, os, tempfile

# ===== Reuse existing patterns/components =====
# Inventory selector (to pick items & qty per branch)
from modules.delivery_chalan import InventorySelectorDialog, export_delivery_chalan_pdf  # PDF style to mirror
# Parties list/structure & COA patterns referenced in clients_master/chart_of_accounts
# (no direct import needed; we call Firestore collections like your modules do)

# ---------- Helpers ----------
def _fmt_money(n):
    try:
        return f"{float(n or 0):,.2f}"
    except Exception:
        return "0.00"

def _ensure_expense_account(user_data):
    """
    Ensure a posting Expense account exists for Powder Coating.
    Mirrors your system-account creation pattern used in chart_of_accounts
    when creating an equity/offset account, including current_balance handling.
    """
    q = db.collection("accounts").where("slug", "==", "powder_coating_expense").limit(1).get()
    if q:
        return q[0].id, (q[0].to_dict() or {}).get("name", "Powder Coating Expense")

    # If missing, create it (posting, active), code generation similar to your approach
    from modules.chart_of_accounts import _generate_code_once_tx, _admin_branches_or
    code = _generate_code_once_tx(db, "Expense")
    branches = _admin_branches_or(user_data.get("branch", []))
    payload = {
        "name": "Powder Coating Expense",
        "slug": "powder_coating_expense",
        "type": "Expense",
        "code": code,
        "parent": None,
        "branch": branches if isinstance(branches, list) else [branches] if branches else [],
        "description": "Job work / service cost for powder coating",
        "active": True,
        "is_posting": True,
        "opening_balance": None,
        "current_balance": 0.0,
    }
    doc_ref = db.collection("accounts").document()
    doc_ref.set(payload)
    return doc_ref.id, "Powder Coating Expense"

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
        return f"PC-{new_pcid:06d}", f"BILL-{datetime.date.today().isoformat()}-{new_bill:04d}"

    return _inc(transaction)

def _export_pc_bill_pdf(pc_doc: dict, out_path: str):
    """
    Export a neat Bill PDF by leveraging your Delivery Chalan PDF style for consistency.
    """
    # We piggyback your reportlab layout helpers via export_delivery_chalan_pdf-like table building.
    # Build a DC-like dict but with bill fields and a Rate/Amount column added in the table text.
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception:
        raise RuntimeError("ReportLab not installed. Please: pip install reportlab")

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm,
                            title=f"Powder Coating Bill {pc_doc.get('bill_ref','')}",
                            author=pc_doc.get("created_by","System"))
    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=16, spaceAfter=8, textColor=colors.HexColor("#111827"))
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=11, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#374151"))
    P  = ParagraphStyle("P",  parent=styles["BodyText"], fontName="Helvetica",
                        fontSize=9.3, leading=12, textColor=colors.HexColor("#111827"))

    story = []
    story.append(Paragraph(f"Powder Coating Bill <b>{pc_doc.get('bill_ref','')}</b>", H1))
    story.append(Spacer(0, 4))

    # Summary (similar to your DC)
    summary = [
        [Paragraph("<b>PCID</b>", P), Paragraph(pc_doc.get("pcid","-"), P),
         Paragraph("<b>Date</b>", P), Paragraph(str(pc_doc.get("date","-")), P)],
        [Paragraph("<b>Branch</b>", P), Paragraph(pc_doc.get("branch","-"), P),
         Paragraph("<b>Vendor</b>", P), Paragraph(pc_doc.get("vendor_name","-"), P)],
        [Paragraph("<b>Status</b>", P), Paragraph(pc_doc.get("status","-"), P),
         Paragraph("<b>Total</b>", P), Paragraph(_fmt_money(pc_doc.get("totals",{}).get("net",0)), P)],
    ]
    from reportlab.platypus import Table
    summary_tbl = Table(summary, colWidths=[25*mm, 65*mm, 20*mm, 62*mm])
    summary_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(summary_tbl)
    story.append(Spacer(0, 6))

    # Items table
    rows = [["Sr", "Item Code", "Name", "Color", "Cond.", "Qty", "Rate", "Amount"]]
    total_qty = 0.0
    for i, it in enumerate(pc_doc.get("items") or [], start=1):
        qty  = float(it.get("qty",0) or 0)
        rate = float(it.get("rate",0) or 0)
        amt  = qty * rate
        total_qty += qty
        rows.append([
            str(i),
            str(it.get("item_code","-")),
            str(it.get("product_name","-")),
            str(it.get("color","-")),
            str(it.get("condition","-")),
            f"{qty:g}",
            _fmt_money(rate),
            _fmt_money(amt),
        ])

    content_w = A4[0] - doc.leftMargin - doc.rightMargin
    col_widths = [10*mm, 22*mm, content_w-(10+22+20+18+16+20+22)*mm, 20*mm, 18*mm, 16*mm, 20*mm, 22*mm]
    items_tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E5E7EB")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BOX", (0,0), (-1,-1), 0.35, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("ALIGN", (-3,1), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(Paragraph("Items", H2))
    story.append(items_tbl)

    doc.build(story)

def _post_vendor_bill_je(user_data, branch, vendor_party_id, vendor_name, total_amount, description, ref_no):
    """
    Debit Powder Coating Expense, Credit Vendor A/P.
    Update balances via firestore.Increment, same spirit as your COA utilities.
    """
    if total_amount <= 0:
        return None

    exp_acc_id, exp_acc_name = _ensure_expense_account(user_data)

    # Find vendor's COA account from parties
    party_doc = db.collection("parties").document(vendor_party_id).get()
    party = party_doc.to_dict() or {}
    vendor_acc_id = party.get("coa_account_id")
    if not vendor_acc_id:
        raise RuntimeError("Selected vendor does not have a linked COA account.")

    # Pre balances
    def _curr_bal(acc_id):
        try:
            a = db.collection("accounts").document(acc_id).get().to_dict() or {}
            return float(a.get("current_balance", 0.0) or 0.0)
        except Exception:
            return 0.0

    debit_line  = {"account_id": exp_acc_id,    "account_name": exp_acc_name, "debit": float(total_amount), "credit": 0, "balance_before": _curr_bal(exp_acc_id)}
    credit_line = {"account_id": vendor_acc_id, "account_name": vendor_name,  "debit": 0, "credit": float(total_amount), "balance_before": _curr_bal(vendor_acc_id)}

    now_server = firestore.SERVER_TIMESTAMP
    branch_val = branch or (user_data.get("branch")[0] if isinstance(user_data.get("branch"), list) else user_data.get("branch") or "-")

    je = {
        "date": now_server,
        "created_at": now_server,
        "created_by": user_data.get("email", "system"),
        "purpose": "Purchase",
        "reference_no": ref_no,
        "branch": branch_val,
        "description": description or f"Powder Coating Bill for {vendor_name}",
        "lines": [debit_line, credit_line],
        "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
        "meta": {"kind": "vendor_bill"}
    }
    je_ref = db.collection("journal_entries").document()
    je_ref.set(je)

    # Update account current balances like your COA save worker
    db.collection("accounts").document(exp_acc_id).update({"current_balance": firestore.Increment(+float(total_amount))})
    db.collection("accounts").document(vendor_acc_id).update({"current_balance": firestore.Increment(-float(total_amount))})
    return je_ref.id

# ---------- Window 1: Main ----------
class PowderCoatingMain(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data or {}
        self.setWindowTitle("Powder Coating Cycle")
        self.setMinimumSize(1100, 650)

        root = QVBoxLayout(self)

        # Toolbar
        tb = QToolBar()
        act_add = QAction("Add New PC Order", self)
        act_add.triggered.connect(self._open_add_pc)
        act_rates = QAction("Modify Rates", self)
        act_rates.triggered.connect(self._open_rates)
        act_inprog = QAction("Grouped In-Progress", self)
        act_inprog.triggered.connect(self._open_inprogress_grouped)
        tb.addAction(act_add); tb.addAction(act_inprog); tb.addSeparator(); tb.addAction(act_rates)
        root.addWidget(tb)

        # List
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["PCID","Bill","Date","Branch","Vendor","Lines","Qty","Total"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        self._load_orders()

    def _load_orders(self):
        self.table.setRowCount(0)
        # Only show for user’s branches (if any)
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        q = db.collection("powder_coating_orders").order_by("created_at", direction=firestore.Query.DESCENDING)
        docs = q.get()
        for d in docs:
            row = d.to_dict() or {}
            if branches and row.get("branch") not in branches:
                continue
            r = self.table.rowCount(); self.table.insertRow(r)
            def cell(txt, align=Qt.AlignLeft):
                it = QTableWidgetItem(str(txt or ""))
                it.setTextAlignment(align | Qt.AlignVCenter)
                return it
            self.table.setItem(r,0, cell(row.get("pcid")))
            self.table.setItem(r,1, cell(row.get("bill_ref")))
            self.table.setItem(r,2, cell(str(row.get("date",""))))
            self.table.setItem(r,3, cell(row.get("branch")))
            self.table.setItem(r,4, cell(row.get("vendor_name")))
            self.table.setItem(r,5, cell(int(row.get("totals",{}).get("lines",0)), Qt.AlignRight))
            self.table.setItem(r,6, cell(row.get("totals",{}).get("qty",0), Qt.AlignRight))
            self.table.setItem(r,7, cell(_fmt_money(row.get("totals",{}).get("net",0)), Qt.AlignRight))

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

# ---------- Window 2: Add New PC ----------
class AddPowderCoatingDialog(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Add New Powder Coating Order")
        self.setMinimumWidth(980)

        form = QFormLayout(self)
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True)

        # Branch (preselect first user branch if present)
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

        self.items = []     # [{..., qty, rate}]
        self._preselected = {}  # to reopen selector with remembered qtys

        form.addRow("Date:", self.date)
        form.addRow("Branch:", self.branch_cb)
        form.addRow("Vendor:", self.vendor_cb)
        form.addRow("Manual ID:", self.manual_id)
        form.addRow(self.btn_pick)
        form.addRow("Notes:", self.notes)

        btns = QHBoxLayout()
        self.btn_save = QPushButton("Save & Generate Bill")
        self.btn_save.clicked.connect(self._save)
        btns.addWidget(self.btn_save)
        form.addRow(btns)

    def _load_vendors(self):
        # parties filtered to suppliers/both
        q = db.collection("parties").select(["name","type","coa_account_id"]).get()
        self.vendor_cb.clear()
        self.vendor_cb.addItem("-- Select Vendor --", None)
        for d in q:
            data = d.to_dict() or {}
            typ = str(data.get("type","")).lower()
            if typ in ("supplier","both"):
                self.vendor_cb.addItem(data.get("name","[No Name]"), d.id)

    def _pick_inventory(self):
        branch = self.branch_cb.currentText().strip()
        if branch in ("", "-"):
            QMessageBox.warning(self, "Select Branch", "Please select a valid branch first.")
            return
        dlg = InventorySelectorDialog(branch=branch, preselected=self._preselected, parent=self)
        if dlg.exec_():
            picked = dlg.selected  # list of dict rows incl. qty
            # Merge in default rates from meta if present
            vendor_id = self.vendor_cb.currentData()
            rates_map = _load_rates(branch, vendor_id)
            items = []
            pre = {}
            for r in picked:
                code = str(r.get("item_code") or r.get("code") or "").strip()
                qty  = float(r.get("qty") or 0)
                if qty <= 0: continue
                rate = float((rates_map.get(code) or {}).get("rate", 0))
                item = {
                    "item_code": code,
                    "product_name": r.get("product_name") or r.get("name") or code,
                    "color": r.get("color"), "condition": r.get("condition"),
                    "qty": qty, "rate": rate, "amount": qty * rate,
                    "meta": {
                        "length": r.get("length"), "width": r.get("width"),
                        "height": r.get("height"), "gauge": r.get("gauge")
                    }
                }
                items.append(item)
                pre_key = f"{code}|{r.get('color')}|{r.get('condition')}|{r.get('length')}|{r.get('width')}|{r.get('height')}|{r.get('gauge')}"
                pre[pre_key] = qty
            self.items = _edit_rates_dialog(self, items)  # small inline editor for rates
            self._preselected = pre

    def _save(self):
        if not self.items:
            QMessageBox.warning(self, "No items", "Please pick inventory items and add rates.")
            return
        vendor_id = self.vendor_cb.currentData()
        vendor_name = self.vendor_cb.currentText()
        if not vendor_id:
            QMessageBox.warning(self, "Select vendor", "Please select a vendor (supplier).")
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

        # Subtract inventory here for the chosen branch (same principle as Delivery Chalan)
        _subtract_inventory_for_pc(branch, self.items)

        # Save order
        doc_ref = db.collection("powder_coating_orders").document()
        doc_ref.set(payload)

        # Post JE (debit expense, credit vendor)
        je_id = _post_vendor_bill_je(
            user_data=self.user_data,
            branch=branch,
            vendor_party_id=vendor_id,
            vendor_name=vendor_name,
            total_amount=total_net,
            description=f"Bill {bill_ref} for {pcid}",
            ref_no=bill_ref
        )
        if je_id:
            doc_ref.update({"je_id": je_id})

        # Export Bill PDF
        try:
            tmp = tempfile.gettempdir()
            out_path = os.path.join(tmp, f"{bill_ref}.pdf")
            pc_for_pdf = payload.copy()
            pc_for_pdf["date"] = date_py.isoformat()
            _export_pc_bill_pdf(pc_for_pdf, out_path)
            doc_ref.update({"bill_pdf_path": out_path})
            QFileDialog.getSaveFileName(self, "Save Bill PDF As…", out_path, "PDF Files (*.pdf)")
        except Exception as e:
            QMessageBox.information(self, "PDF not created", f"Bill saved but PDF export failed: {e}")

        QMessageBox.information(self, "Saved", f"Order {pcid} saved and inventory subtracted.")
        self.accept()

# ---------- Window 3: Grouped In-Progress ----------
class InProgressGroupedWindow(QWidget):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Grouped In-Progress Items")
        self.setMinimumSize(980, 600)
        root = QVBoxLayout(self)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Item Code","Name","Color","Condition","Total Qty (In-Progress)","Orders"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        self._load()

    def _load(self):
        self.table.setRowCount(0)
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        q = db.collection("powder_coating_orders").where("status","==","IN_PROGRESS").get()
        agg = {}  # key=(code,color,cond) -> {name, qty, orders:set}
        for d in q:
            row = d.to_dict() or {}
            if branches and row.get("branch") not in branches: continue
            for it in (row.get("items") or []):
                key = (it.get("item_code"), it.get("color"), it.get("condition"))
                g = agg.setdefault(key, {"name": it.get("product_name"), "qty": 0.0, "orders": set()})
                try: g["qty"] += float(it.get("qty") or 0)
                except Exception: pass
                g["orders"].add(row.get("pcid"))
        for (code, color, cond), v in agg.items():
            r = self.table.rowCount(); self.table.insertRow(r)
            def cell(x, align=Qt.AlignLeft):
                it = QTableWidgetItem(str(x or ""))
                it.setTextAlignment(align | Qt.AlignVCenter); return it
            self.table.setItem(r,0,cell(code))
            self.table.setItem(r,1,cell(v["name"]))
            self.table.setItem(r,2,cell(color))
            self.table.setItem(r,3,cell(cond))
            self.table.setItem(r,4,cell(v["qty"], Qt.AlignRight))
            self.table.setItem(r,5,cell(", ".join(sorted(v["orders"]))))

# ---------- Window 4: Modify Rates ----------
def _rates_key(branch, vendor_id):
    return f"{branch}::{vendor_id}" if branch and vendor_id else None

def _load_rates(branch, vendor_id) -> dict:
    doc = db.collection("meta").document("powder_coating_rates").get()
    data = doc.to_dict() or {}
    node = data.get(_rates_key(branch, vendor_id), {})
    return node if isinstance(node, dict) else {}

def _save_rates(branch, vendor_id, rate_map: dict):
    ref = db.collection("meta").document("powder_coating_rates")
    ref.set({_rates_key(branch, vendor_id): rate_map}, merge=True)

class ModifyRatesDialog(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data or {}
        self.setWindowTitle("Modify Powder Coating Rates")
        self.setMinimumSize(800, 560)
        form = QFormLayout(self)

        self.branch_cb = QComboBox()
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches] if branches else []
        for b in branches: self.branch_cb.addItem(b)
        if not branches: self.branch_cb.addItem("-")

        self.vendor_cb = QComboBox()
        self._load_vendors()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Item Code","Item Name","Rate"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)

        tb = QToolBar()
        act_load = QAction("Load Item Catalog", self); act_load.triggered.connect(self._load_items_catalog)
        act_save = QAction("Save Rates", self); act_save.triggered.connect(self._save)
        tb.addAction(act_load); tb.addAction(act_save)

        form.addRow("Branch:", self.branch_cb)
        form.addRow("Vendor:", self.vendor_cb)
        form.addRow(tb)
        form.addRow(self.table)

    def _load_vendors(self):
        q = db.collection("parties").select(["name","type"]).get()
        self.vendor_cb.clear()
        self.vendor_cb.addItem("-- Select Vendor --", None)
        for d in q:
            data = d.to_dict() or {}
            typ = str(data.get("type","")).lower()
            if typ in ("supplier","both"):
                self.vendor_cb.addItem(data.get("name","[No Name]"), d.id)

    def _load_items_catalog(self):
        # Pull item codes & names from your Products catalog (left as a simple query; adapt to your schema)
        # If you have nested categories/subcategories, select flattened 'items' collection the way you already do.
        rows = []
        try:
            # Common patterns: collection 'products' or 'items'
            for snap in db.collection("products").select(["code","name"]).get():
                d = snap.to_dict() or {}
                code = d.get("code") or snap.id
                name = d.get("name") or code
                rows.append((code, name))
        except Exception:
            pass

        # Prefill table + current rate map
        branch = self.branch_cb.currentText().strip()
        vendor = self.vendor_cb.currentData()
        rates = _load_rates(branch, vendor)
        self.table.setRowCount(0)
        for code, name in rows:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r,0, QTableWidgetItem(code))
            self.table.setItem(r,1, QTableWidgetItem(name))
            ds = QDoubleSpinBox(); ds.setMaximum(1e9); ds.setDecimals(2); ds.setValue(float((rates.get(code) or {}).get("rate",0)))
            self.table.setCellWidget(r,2, ds)

    def _save(self):
        vendor = self.vendor_cb.currentData()
        if not vendor:
            QMessageBox.warning(self, "Select vendor", "Choose a vendor to save rates for.")
            return
        branch = self.branch_cb.currentText().strip()
        rate_map = {}
        for r in range(self.table.rowCount()):
            code = (self.table.item(r,0).text() or "").strip()
            name = (self.table.item(r,1).text() or "").strip()
            rate = float(self.table.cellWidget(r,2).value())
            rate_map[code] = {"rate": rate, "updated_at": firestore.SERVER_TIMESTAMP, "name": name}
        _save_rates(branch, vendor, rate_map)
        QMessageBox.information(self, "Saved", "Rates updated successfully.")
        self.accept()

# ---------- Inventory subtraction (branch-scoped) ----------
def _subtract_inventory_for_pc(branch, items):
    """
    Subtract qty from your per-branch inventory nodes.
    This mirrors the logic you already use around Delivery Chalan when moving goods.
    """
    # You likely store inventory under collection like "inventory" with documents per item/branch/color/condition.
    # Here we do a minimal example; replace with your exact doc paths & field names:
    batch = firestore.client().batch()
    for it in items:
        item_code = it.get("item_code")
        color     = it.get("color") or "No Color"
        cond      = it.get("condition") or "New"
        qty       = float(it.get("qty") or 0)
        inv_ref = db.collection("inventory").document(f"{branch}::{item_code}::{color}::{cond}")
        batch.set(inv_ref, {"branch": branch, "item_code": item_code, "color": color, "condition": cond},
                  merge=True)
        batch.update(inv_ref, {"qty": firestore.Increment(-qty)})
    batch.commit()

# ---------- Tiny inline rate editor ----------
def _edit_rates_dialog(parent, items):
    """
    Quick editor to tweak 'rate' per picked line before saving.
    """
    dlg = QDialog(parent); dlg.setWindowTitle("Confirm Rates")
    lay = QVBoxLayout(dlg)
    tbl = QTableWidget(0, 7)
    tbl.setHorizontalHeaderLabels(["Item Code","Name","Color","Cond.","Qty","Rate","Amount"])
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    tbl.verticalHeader().setVisible(False)
    lay.addWidget(tbl)

    def add_row(x):
        r = tbl.rowCount(); tbl.insertRow(r)
        tbl.setItem(r,0, QTableWidgetItem(x["item_code"]))
        tbl.setItem(r,1, QTableWidgetItem(x["product_name"]))
        tbl.setItem(r,2, QTableWidgetItem(str(x["color"])))
        tbl.setItem(r,3, QTableWidgetItem(str(x["condition"])))
        tbl.setItem(r,4, QTableWidgetItem(str(x["qty"])))
        sp = QDoubleSpinBox(); sp.setDecimals(2); sp.setMaximum(1e9); sp.setValue(float(x.get("rate") or 0))
        tbl.setCellWidget(r,5, sp)
        tbl.setItem(r,6, QTableWidgetItem(_fmt_money(x.get("amount",0))))
    for it in items:
        add_row(it)

    btns = QHBoxLayout()
    ok = QPushButton("OK"); cancel = QPushButton("Cancel")
    ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject)
    btns.addStretch(1); btns.addWidget(ok); btns.addWidget(cancel)
    lay.addLayout(btns)

    if dlg.exec_():
        out = []
        for r in range(tbl.rowCount()):
            code = tbl.item(r,0).text()
            name = tbl.item(r,1).text()
            color= tbl.item(r,2).text()
            cond = tbl.item(r,3).text()
            qty  = float(tbl.item(r,4).text())
            rate = float(tbl.cellWidget(r,5).value())
            out.append({
                "item_code": code, "product_name": name, "color": color, "condition": cond,
                "qty": qty, "rate": rate, "amount": qty * rate
            })
        return out
    return items
