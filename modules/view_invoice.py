# modules/view_invoices.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QTextEdit, QDialogButtonBox,
    QMessageBox, QHeaderView, QAbstractItemView, QToolBar, QAction, QStyle, QProgressBar,
    QSizePolicy, QGroupBox, QDateEdit, QTabWidget, QFrame, QFileDialog, QSpacerItem,
    QGridLayout, QToolButton, QMenu
)
from PyQt5.QtCore import Qt, QDate, QTimer
from PyQt5.QtGui import QColor
from firebase.config import db
from firebase_admin import firestore
import uuid, csv, os, tempfile, datetime
import datetime as _dt


# Try to import your editor to support View/Edit actions
try:
    from modules.invoice import InvoiceModule
except Exception:
    InvoiceModule = None  # We'll guard usage if unavailable


APP_STYLE = """
QWidget { font-size: 14px; }
QPushButton { background: #2d6cdf; color: white; border: none; padding: 6px 12px; border-radius: 8px; }
QPushButton:hover { background: #2458b2; }
QPushButton:disabled { background: #a9b7d1; }
QGroupBox { border: 1px solid #e3e7ef; border-radius: 10px; margin-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QTableWidget::item:selected { background: #dbeafe; color: #1e3a8a; }
"""

def _fmt_money(v) -> str:
    try:
        n = float(v or 0.0)
    except Exception:
        n = 0.0
    return f"Rs {n:,.2f}"


def _safe_date(d):
    """Return a naive datetime (no tzinfo) for consistent comparisons."""
    try:
        if d is None:
            return None
        if hasattr(d, "to_datetime"):        # Firestore Timestamp
            return d.to_datetime().replace(tzinfo=None)
        if isinstance(d, _dt.datetime):
            return d.replace(tzinfo=None)
        if isinstance(d, _dt.date):
            return _dt.datetime(d.year, d.month, d.day)
        s = str(d)
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return _dt.datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return None
    
def _today():
    return _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

def _due_status_color(due_dt):
    """Return (label, bg_color, fg_color) based on due date proximity."""
    from PyQt5.QtGui import QColor
    if not due_dt:
        return ("No Due", QColor("#e5e7eb"), QColor("#111827"))
    # Remove tz to make arithmetic consistent
    try:
        if getattr(due_dt, "tzinfo", None) is not None:
            due_dt = due_dt.replace(tzinfo=None)
    except Exception:
        pass
    delta = (due_dt - _today()).days
    if delta < 0:
        return ("Overdue", QColor("#fee2e2"), QColor("#991b1b"))
    if delta <= 2:
        return ("Due Soon", QColor("#fef3c7"), QColor("#78350f"))
    return ("On Time", QColor("#dcfce7"), QColor("#065f46"))


class DeliveryChalanDialog(QDialog):
    """Create a delivery chalan from an invoice's aggregated BoQ items."""
    def __init__(self, invoice_doc_id, invoice_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Delivery Chalan")
        self.setMinimumSize(720, 560)
        self.invoice_doc_id = invoice_doc_id
        self.invoice_data = invoice_data

        v = QVBoxLayout(self)

        # --- Header form ---
        form = QFormLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.vehicle = QLineEdit()
        self.person = QLineEdit()
        self.notes = QTextEdit()
        form.addRow("Date", self.date_edit)
        form.addRow("Vehicle", self.vehicle)
        form.addRow("Delivered By", self.person)
        form.addRow("Notes", self.notes)
        v.addLayout(form)

        # --- Items table (aggregated BoQ) ---
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Item", "Condition", "Qty (deliver)", "Already Delivered"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        v.addWidget(self.tbl)

        self._load_boq_items()

        # --- Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _load_boq_items(self):
        """Aggregate BoQ items across all main products on the invoice."""
        self.tbl.setRowCount(0)
        rows = []
        for mp in self.invoice_data.get("items", []):
            for b in mp.get("boq", []):
                rows.append({
                    "product": b.get("product", "") or "",
                    "condition": b.get("condition", "") or "",
                    "qty": float(b.get("qty", 0) or 0),
                })

        # Aggregate (product, condition) → total qty
        agg = {}
        for r in rows:
            key = (r["product"], r["condition"])
            agg[key] = agg.get(key, 0.0) + r["qty"]

        # TODO: replace with actual “already delivered” lookup if/when you want
        delivered_map = {}

        self.tbl.setRowCount(len(agg))
        for i, ((prod, cond), total_qty) in enumerate(agg.items()):
            self.tbl.setItem(i, 0, QTableWidgetItem(prod))
            self.tbl.setItem(i, 1, QTableWidgetItem(cond))
            qty_edit = QLineEdit(str(total_qty))
            self.tbl.setCellWidget(i, 2, qty_edit)
            self.tbl.setItem(i, 3, QTableWidgetItem(str(delivered_map.get((prod, cond), 0))))

    def _save(self):
        # Collect items
        items = []
        for r in range(self.tbl.rowCount()):
            prod = self.tbl.item(r, 0).text() if self.tbl.item(r, 0) else ""
            cond = self.tbl.item(r, 1).text() if self.tbl.item(r, 1) else ""
            qtyw = self.tbl.cellWidget(r, 2)
            try:
                qty = float((qtyw.text() if qtyw else "0") or 0)
            except Exception:
                qty = 0.0
            if qty > 0:
                items.append({"product": prod, "condition": cond, "qty": qty})

        payload = {
            "invoice_id": self.invoice_doc_id,
            "invoice_no": self.invoice_data.get("invoice_no"),
            "client_id": self.invoice_data.get("client_id"),
            "client_name": self.invoice_data.get("client_name"),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "vehicle": (self.vehicle.text() or "").strip(),
            "person": (self.person.text() or "").strip(),
            "notes": (self.notes.toPlainText() or "").strip(),
            "items": items,
            "created_at": firestore.SERVER_TIMESTAMP,
        }

        db.collection("delivery_chalans").add(payload)
        QMessageBox.information(self, "Saved", "Delivery Chalan saved.")
        self.accept()



# ---------- Read-only VIEW dialog ----------
class InvoiceDetailsDialog(QDialog):
    def __init__(self, doc_id, data, parent=None):
        super().__init__(parent)
        self.setStyleSheet(APP_STYLE)
        self.setWindowTitle(f"Invoice Details • {data.get('invoice_no','')}")
        self.setMinimumSize(900, 640)

        v = QVBoxLayout(self)

        # Top summary grid
        g = QGridLayout()
        def add(r, c, label, value):
            g.addWidget(QLabel(f"<b>{label}</b>"), r, c)
            lab = QLabel(value if value else "-")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(lab, r, c+1)

        # Resolve client name if not present on doc
        client_name = data.get("client_name")
        if not client_name:
            pid = data.get("client_id") or data.get("party_id")
            try:
                if pid:
                    p = db.collection("parties").document(pid).get()
                    if p.exists:
                        client_name = p.to_dict().get("name", "")
            except Exception:
                client_name = ""
        client_name = client_name or (data.get("client_id") or "")

        inv_date = _safe_date(data.get("invoice_date"))
        due_date = _safe_date(data.get("due_date"))
        am = data.get("amounts") or {}

        def money(x):
            try: return f"Rs {float(x or 0):,.2f}"
            except: return "Rs 0.00"

        add(0, 0, "Invoice #", data.get("invoice_no",""))
        add(0, 2, "Type", data.get("type",""))
        add(1, 0, "Status", data.get("status","Open"))
        add(1, 2, "Client", client_name)
        add(2, 0, "Invoice Date", inv_date.strftime("%Y-%m-%d") if inv_date else "-")
        add(2, 2, "Due Date", due_date.strftime("%Y-%m-%d") if due_date else "-")
        add(3, 0, "Subject", data.get("subject","") or "-")
        add(3, 2, "Site Address", data.get("site_address","") or "-")
        add(4, 0, "Total", money(am.get("total")))
        add(4, 2, "Received", money(am.get("received")))
        add(5, 0, "Balance", money(am.get("balance")))
        v.addLayout(g)

        # Items table — stretch name, auto-size amounts
        items = data.get("items") or []
        gb = QGroupBox("Items")
        gb_v = QVBoxLayout(gb)
        tbl = QTableWidget(0, 4)
        tbl.setHorizontalHeaderLabels(["Item", "Qty", "Rate", "Total"])
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        for it in items:
            r = tbl.rowCount(); tbl.insertRow(r)
            name = it.get("label") or it.get("name") or it.get("item_code") or it.get("main_product") or "(item)"
            qty  = it.get("qty", 0)
            rate = it.get("rate", 0)
            tot  = it.get("total", (float(qty or 0) * float(rate or 0)))
            i0 = QTableWidgetItem(str(name))
            i1 = QTableWidgetItem(str(qty));  i1.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            i2 = QTableWidgetItem(_fmt_money(rate)); i2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            i3 = QTableWidgetItem(_fmt_money(tot));  i3.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(r, 0, i0); tbl.setItem(r, 1, i1); tbl.setItem(r, 2, i2); tbl.setItem(r, 3, i3)

        gb_v.addWidget(tbl)
        v.addWidget(gb)

        # Notes / Terms
        if data.get("notes") or data.get("terms"):
            gb2 = QGroupBox("Notes & Terms")
            l2 = QVBoxLayout(gb2)
            if data.get("notes"):
                n = QLabel(f"<b>Notes:</b><br>{data.get('notes')}")
                n.setTextInteractionFlags(Qt.TextSelectableByMouse)
                l2.addWidget(n)
            if data.get("terms"):
                t = QLabel(f"<b>Terms:</b><br>{data.get('terms')}")
                t.setTextInteractionFlags(Qt.TextSelectableByMouse)
                l2.addWidget(t)
            v.addWidget(gb2)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)


# ---------- BoQ (MERGED across all main products) ----------
class BoQMergedDialog(QDialog):
    """Merged BoQ across invoice; Name column stretches; amounts autosize."""
    def __init__(self, invoice_data, parent=None):
        super().__init__(parent)
        self.setStyleSheet(APP_STYLE)
        self.setWindowTitle(f"BoQ (Merged) • {invoice_data.get('invoice_no','')}")
        self.setMinimumSize(900, 600)

        v = QVBoxLayout(self)

        items = invoice_data.get("items") or []
        merged = {}
        grand_qty = 0.0
        grand_total = 0.0

        def norm(t): return (str(t or "").strip())
        def get_id(b):
            for k in ("product_id","productId","id","item_id","itemId","code","item_code"):
                if b.get(k):
                    return str(b.get(k))
            return None

        for mp in items:
            for b in (mp.get("boq") or []):
                pid = get_id(b)
                if pid:
                    key = ("id", pid)
                else:
                    key = ("name", norm(b.get("product")), norm(b.get("color")), norm(b.get("condition")))
                entry = merged.get(key)
                qty = float(b.get("qty", 0) or 0.0)
                rate = float(b.get("rate", 0) or 0.0)
                total = float(b.get("total", qty * rate) or 0.0)

                if not entry:
                    merged[key] = {
                        "id": pid or "",
                        "product": b.get("product") or "",
                        "colors": set([norm(b.get("color"))]) if b.get("color") else set(),
                        "conditions": set([norm(b.get("condition"))]) if b.get("condition") else set(),
                        "qty": qty,
                        "total": total,
                    }
                else:
                    entry["qty"] += qty
                    entry["total"] += total
                    if b.get("color"): entry["colors"].add(norm(b.get("color")))
                    if b.get("condition"): entry["conditions"].add(norm(b.get("condition")))

        tbl = QTableWidget(0, 4)
        tbl.setHorizontalHeaderLabels(["Name", "Qty", "Avg Rate", "Total"])
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        def sort_key(kv):
            (k, v) = kv
            has_id = bool(v["id"])
            if has_id:
                try:
                    return (0, int(v["id"]))
                except Exception:
                    return (0, str(v["id"]).lower())
            return (1, v["product"].lower())

        for _k, row in sorted(merged.items(), key=sort_key):
            q = float(row["qty"] or 0.0)
            t = float(row["total"] or 0.0)
            avg = (t / q) if q else 0.0

            parts = []
            if row["id"]:
                parts.append(str(row["id"]))
            if row["product"]:
                parts.append(str(row["product"]))
            extra = []
            if row["colors"]:
                extra.append("/".join(sorted(c for c in row["colors"] if c)))
            if row["conditions"]:
                extra.append("/".join(sorted(c for c in row["conditions"] if c)))
            name = " — ".join(parts) if parts else "(Unnamed)"
            if extra:
                name = f"{name}  ({', '.join([e for e in extra if e])})"

            r = tbl.rowCount(); tbl.insertRow(r)
            i0 = QTableWidgetItem(name)
            i1 = QTableWidgetItem(str(q));           i1.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            i2 = QTableWidgetItem(_fmt_money(avg));  i2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            i3 = QTableWidgetItem(_fmt_money(t));    i3.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(r, 0, i0); tbl.setItem(r, 1, i1); tbl.setItem(r, 2, i2); tbl.setItem(r, 3, i3)

            grand_qty += q
            grand_total += t

        if tbl.rowCount() == 0:
            lbl = QLabel("No BoQ items found on this invoice.")
            lbl.setStyleSheet("color:#6b7280;")
            v.addWidget(lbl)
        else:
            v.addWidget(tbl)
            info = QLabel(f"<b>Lines:</b> {tbl.rowCount()}  •  <b>Total Qty:</b> {grand_qty}  •  <b>Grand Total:</b> {_fmt_money(grand_total)}")
            info.setStyleSheet("padding:6px 2px; color:#374151;")
            v.addWidget(info)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)


# ---------- Payment History dialog ----------
class PaymentHistoryDialog(QDialog):
    def __init__(self, doc_id, parent=None):
        super().__init__(parent)
        self.setStyleSheet(APP_STYLE)
        self.setWindowTitle("Payment History")
        self.setMinimumSize(800, 520)

        v = QVBoxLayout(self)

        tbl = QTableWidget(0, 6)
        tbl.setHorizontalHeaderLabels(["Date", "Amount", "Account", "Notes", "Created By", "Created At"])
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(tbl)

        rows = []
        try:
            ref = db.collection("invoices").document(doc_id).collection("payments")
            try:
                stream = ref.order_by("date").stream()
            except Exception:
                stream = ref.stream()
            for pdoc in stream:
                rows.append(pdoc.to_dict() or {})
        except Exception as e:
            QMessageBox.warning(self, "Payments", f"Failed to load payments:\n{e}")

        acc_name_cache = {}
        def account_name(acc_id):
            if not acc_id: return "-"
            if acc_id in acc_name_cache: return acc_name_cache[acc_id]
            try:
                s = db.collection("accounts").document(acc_id).get()
                n = (s.to_dict() or {}).get("name", acc_id)
            except Exception:
                n = acc_id
            acc_name_cache[acc_id] = n
            return n

        for r in rows:
            row = tbl.rowCount(); tbl.insertRow(row)
            d = _safe_date(r.get("date"))
            ca = _safe_date(r.get("created_at"))
            tbl.setItem(row, 0, QTableWidgetItem(d.strftime("%Y-%m-%d") if d else "-"))
            amt = QTableWidgetItem(_fmt_money(r.get("amount"))); amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(row, 1, amt)
            tbl.setItem(row, 2, QTableWidgetItem(account_name(r.get("account_id"))))
            tbl.setItem(row, 3, QTableWidgetItem(str(r.get("notes",""))))
            tbl.setItem(row, 4, QTableWidgetItem(str(r.get("created_by",""))))
            tbl.setItem(row, 5, QTableWidgetItem(ca.strftime("%Y-%m-%d %H:%M") if ca else "-"))

        info = QLabel(f"Total payments: {len(rows)}")
        info.setStyleSheet("color:#374151; padding:4px 2px;")
        v.addWidget(info)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)


# ---------- Chalan History dialog ----------
class ChalanHistoryDialog(QDialog):
    def __init__(self, doc_id, parent=None):
        super().__init__(parent)
        self.setStyleSheet(APP_STYLE)
        self.setWindowTitle("Delivery Chalan History")
        self.setMinimumSize(820, 520)

        v = QVBoxLayout(self)

        tbl = QTableWidget(0, 5)
        tbl.setHorizontalHeaderLabels(["Chalan ID", "Status", "Created At", "Client", "Notes"])
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(tbl)

        rows = []
        try:
            stream = db.collection("delivery_chalans").where("invoice_id", "==", doc_id).stream()
            for d in stream:
                rows.append({"id": d.id, **(d.to_dict() or {})})
        except Exception as e:
            QMessageBox.warning(self, "Chalan", f"Failed to load chalans:\n{e}")

        for r in rows:
            row = tbl.rowCount(); tbl.insertRow(row)
            ca = _safe_date(r.get("created_at"))
            tbl.setItem(row, 0, QTableWidgetItem(r.get("id","")))
            tbl.setItem(row, 1, QTableWidgetItem(r.get("status","")))
            tbl.setItem(row, 2, QTableWidgetItem(ca.strftime("%Y-%m-%d %H:%M") if ca else "-"))
            tbl.setItem(row, 3, QTableWidgetItem(r.get("client_name","") or str(r.get("client_id",""))))
            tbl.setItem(row, 4, QTableWidgetItem(r.get("notes","")))

        info = QLabel(f"Total chalans: {len(rows)}")
        info.setStyleSheet("color:#374151; padding:4px 2px;")
        v.addWidget(info)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)


class RecordPaymentDialog(QDialog):
    """Record payment + post JE as one atomic Firestore transaction."""
    def __init__(self, user_data, invoice_doc_id, invoice_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.invoice_id = invoice_doc_id
        self.invoice = invoice_data or {}
        self.setWindowTitle("Record Payment")
        self.setStyleSheet(APP_STYLE)
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_accounts()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True)
        self.amount = QLineEdit(); self.amount.setPlaceholderText("0.00")
        self.account_cb = QComboBox(); self.account_cb.setEditable(True)
        self.notes = QLineEdit(); self.notes.setPlaceholderText("Reference / notes (optional)")
        form.addRow("Date", self.date)
        form.addRow("Amount", self.amount)
        form.addRow("Receive into", self.account_cb)
        form.addRow("Notes", self.notes)
        lay.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _load_accounts(self):
        self.account_cb.clear()
        self.account_cb.addItem("", None)
        try:
            q = (db.collection("accounts")
                 .where("is_posting", "==", True)
                 .where("active", "==", True)
                 .where("type", "==", "Asset")
                 .where("subtype", "==", "Cash & Bank")
                 .stream())
            for doc in q:
                d = doc.to_dict() or {}
                label = f"{d.get('code','')} - {d.get('name','')}"
                self.account_cb.addItem(label, doc.id)
        except Exception:
            pass

    def _save(self):
        # ---- validate inputs
        try:
            amt = float(self.amount.text().replace(",", "") or 0.0)
        except Exception:
            amt = 0.0
        if amt <= 0:
            QMessageBox.warning(self, "Amount", "Enter a valid amount.")
            return
        recv_acc_id = self.account_cb.itemData(self.account_cb.currentIndex())
        if not recv_acc_id:
            QMessageBox.warning(self, "Account", "Select the receive account.")
            return

        party_id = self.invoice.get("client_id") or self.invoice.get("party_id")
        if not party_id:
            QMessageBox.critical(self, "Missing", "Invoice has no linked client/party.")
            return

        # Convert QDate -> datetime at midnight (naive)
        _qd = self.date.date().toPyDate()
        pay_date = datetime.datetime(_qd.year, _qd.month, _qd.day, 0, 0, 0)
        now = datetime.datetime.now()

        # Refs used inside the transaction
        inv_ref   = db.collection("invoices").document(self.invoice_id)
        party_ref = db.collection("parties").document(party_id)
        accs      = db.collection("accounts")
        je_ref    = db.collection("journal_entries").document()
        pay_ref   = inv_ref.collection("payments").document()

        transaction = firestore.client().transaction()

        @firestore.transactional
        def txn_all(tx):
            # -------- 1) READS

            # Party -> AR account
            party_snap = party_ref.get(transaction=tx)
            if not party_snap.exists:
                raise RuntimeError("Linked party not found.")
            party_data = party_snap.to_dict() or {}
            ar_id = party_data.get("coa_account_id")
            if not ar_id:
                raise RuntimeError("Party has no linked CoA account (AR).")

            # Verify real accounts exist
            recv_acc_ref = accs.document(recv_acc_id);  recv_snap = recv_acc_ref.get(transaction=tx)
            if not recv_snap.exists: raise RuntimeError("Receive account not found.")
            ar_acc_ref   = accs.document(ar_id);        ar_snap   = ar_acc_ref.get(transaction=tx)
            if not ar_snap.exists:   raise RuntimeError("AR account not found.")
            recv_acc = recv_snap.to_dict() or {}
            ar_acc   = ar_snap.to_dict() or {}

            # Invoice snapshot
            inv_snap = inv_ref.get(transaction=tx)
            if not inv_snap.exists:
                raise RuntimeError("Invoice not found.")
            inv = inv_snap.to_dict() or {}
            am  = inv.get("amounts") or {}
            total     = float(am.get("total", 0.0) or 0.0)
            received0 = float(am.get("received", 0.0) or 0.0)

            # Is this the first payment?
            has_any_payment = False
            for _ in inv_ref.collection("payments").limit(1).stream(transaction=tx):
                has_any_payment = True
                break
            first_payment = not has_any_payment

            # -------- 2) Compose JE & derived fields

            # Always: DR Cash / CR AR by 'amt'
            je_lines = [
                {"account_id": recv_acc_id, "debit": amt, "credit": 0},
                {"account_id": ar_id,       "debit": 0,   "credit": amt},
            ]
            # First payment: recognize sale with a VIRTUAL revenue line (by NAME only)
            if first_payment and total > 0:
                je_lines.append({"account_id": ar_id, "debit": total, "credit": 0})
                je_lines.append({
                    "account_name": "Sales Revenue (virtual)",
                    "is_virtual": True,
                    "debit": 0,
                    "credit": total
                })

            def _net_for(acc_type, debit, credit):
                return (debit - credit) if acc_type in ("Asset", "Expense") else (credit - debit)

            # aggregate only REAL accounts (those with account_id)
            by_acc = {}
            for l in je_lines:
                if "account_id" not in l or not l["account_id"]:
                    continue
                a = l["account_id"]
                by_acc.setdefault(a, {"debit": 0.0, "credit": 0.0})
                by_acc[a]["debit"]  += float(l.get("debit", 0) or 0.0)
                by_acc[a]["credit"] += float(l.get("credit", 0) or 0.0)

            types = {
                recv_acc_id: (recv_acc.get("type") or "Asset"),
                ar_id:       (ar_acc.get("type")   or "Asset"),
            }
            increments = {
                a_id: _net_for(types.get(a_id, "Asset"), v["debit"], v["credit"])
                for a_id, v in by_acc.items()
            }

            # New invoice aggregates and status/type
            received1 = received0 + amt
            balance1  = max(0.0, total - received1)
            new_status = inv.get("status") or "Open"
            if total > 0 and abs(balance1) < 0.01:
                new_status = "Paid"
            new_type = inv.get("type") or "Invoice"
            if first_payment and str(new_type).lower() == "quotation":
                new_type = "Invoice"

            pay_kind = "Advance" if first_payment else "Sale"

            je_doc = {
                "date": now,
                "created_at": now,
                "created_by": self.user_data.get("email", "system"),
                "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(now.timestamp())}",
                "purpose": pay_kind,  # "Advance" first, else "Sale"
                "branch": (self.user_data.get("branch") or ["-"])[0]
                          if isinstance(self.user_data.get("branch"), list)
                          else (self.user_data.get("branch") or "-"),
                "description": f"{pay_kind}: {self.invoice.get('invoice_no','(unknown)')} for {party_data.get('name','')}",
                "invoice_ref": self.invoice_id,
                "lines": je_lines,
                "lines_account_ids": [l["account_id"] for l in je_lines if l.get("account_id")],
                "meta": {"kind": "invoice_payment"},
            }

            pay_doc = {
                "date": pay_date,
                "amount": amt,
                "account_id": recv_acc_id,
                "notes": self.notes.text().strip(),
                "created_at": now,
                "created_by": self.user_data.get("email", "system"),
                "payment_type": pay_kind,
            }

            # -------- 3) WRITES (no reads after this)

            # Update balances for real accounts
            for a_id, inc in increments.items():
                tx.update(accs.document(a_id), {"current_balance": firestore.Increment(inc)})

            # Create JE and payment
            tx.set(je_ref, je_doc)
            tx.set(pay_ref, pay_doc)

            # Update invoice (nested fields via update)
            tx.update(inv_ref, {
                "amounts.received": received1,
                "amounts.balance":  balance1,
                "status": new_status,
                "type": new_type,
                "updated_at": now,
            })

        try:
            txn_all(transaction)
        except Exception as e:
            QMessageBox.critical(self, "Payment Failed",
                                 f"Nothing was saved.\nReason: {e}")
            return

        QMessageBox.information(self, "Saved", "Payment recorded and journaled.")
        self.accept()


class ViewInvoicesModule(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setWindowTitle("Invoices")
        self.setMinimumSize(1200, 720)
        self.setStyleSheet(APP_STYLE)

        _role = (self.user_data.get("role") or "")
        _roles = self.user_data.get("roles") or []
        if not isinstance(_roles, (list, tuple)):
            _roles = [_roles]
        self._is_admin = ("admin" in str(_role).lower()) or any("admin" in str(r).lower() for r in _roles)

        self._child_windows = []
        self._build_ui()
        QTimer.singleShot(0, self.load_invoices)

    def _build_ui(self):
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("🧾 Invoices")
        title.setStyleSheet("font-size: 20px; font-weight: 700; padding: 4px 2px;")
        header.addWidget(title)
        header.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search invoice no / client / subject…")
        self.search.textChanged.connect(self._apply_filters)
        header.addWidget(self.search)
        root.addLayout(header)

        toolbar = QToolBar()
        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.load_invoices)
        act_export = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Export CSV", self)
        act_export.triggered.connect(self._export_csv_visible)
        act_new = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "New Invoice", self)
        act_new.triggered.connect(self._new_invoice)
        toolbar.addAction(act_refresh); toolbar.addSeparator()
        toolbar.addAction(act_export);  toolbar.addSeparator()
        toolbar.addAction(act_new)
        root.addWidget(toolbar)

        self.filter_tabs = QTabWidget()
        self.filter_tabs.setTabPosition(QTabWidget.North)
        self.filter_tabs.setDocumentMode(True)
        for name in ["All", "Pending", "Paid", "Overdue", "Quotations", "Cash Sales"]:
            w = QWidget(); w.setLayout(QVBoxLayout()); self.filter_tabs.addTab(w, name)
        self.filter_tabs.currentChanged.connect(self._apply_filters)
        root.addWidget(self.filter_tabs)

        self.table = QTableWidget(0, 10)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._view_invoice)

        headers = ["Invoice #", "Type", "Status", "Client", "Total", "Received", "Balance", "Due Date", "Progress", "Actions"]
        self.table.setHorizontalHeaderLabels(headers)
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(True)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(9, QHeaderView.ResizeToContents)

        root.addWidget(self.table, stretch=1)

        foot = QHBoxLayout()
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        foot.addWidget(self.count_lbl)
        foot.addStretch()
        root.addLayout(foot)

    def load_invoices(self):
        self._rows = []
        self.table.setRowCount(0)
        try:
            for doc in db.collection("invoices").stream():
                self._add_row(doc.id, doc.to_dict() or {})
            self._apply_filters()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load invoices:\n{e}")

    def _add_row(self, doc_id, data):
        inv_no   = data.get("invoice_no") or data.get("reference") or "(no number)"
        inv_type = (data.get("type") or "Invoice")
        status   = data.get("status") or "Open"

        client_name = data.get("client_name")
        if not client_name:
            pid = data.get("client_id") or data.get("party_id")
            try:
                if pid:
                    p = db.collection("parties").document(pid).get()
                    if p.exists:
                        client_name = p.to_dict().get("name", "(client)")
            except Exception:
                client_name = "(client)"
        client_name = client_name or "(client)"

        am = data.get("amounts") or {}
        total    = float(am.get("total", 0.0) or 0.0)
        received = float(am.get("received", 0.0) or 0.0)
        balance  = float(am.get("balance", max(0.0, total - received)) or 0.0)

        due_dt  = _safe_date(data.get("due_date"))
        due_label, due_bg, due_fg = _due_status_color(due_dt)

        pct = 0 if total <= 0 else int(round(min(100.0, max(0.0, (received / total) * 100.0))))
        progress_widget = QProgressBar(); progress_widget.setValue(pct); progress_widget.setFixedWidth(140); progress_widget.setFormat(f"{pct}%")

        r = self.table.rowCount(); self.table.insertRow(r)
        def _item(text, align_right=False):
            it = QTableWidgetItem(text)
            if align_right: it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return it

        self.table.setItem(r, 0, _item(inv_no))
        self.table.setItem(r, 1, _item(inv_type))
        self.table.setItem(r, 2, _item(status))
        self.table.setItem(r, 3, _item(client_name))
        self.table.setItem(r, 4, _item(_fmt_money(total), True))
        self.table.setItem(r, 5, _item(_fmt_money(received), True))
        self.table.setItem(r, 6, _item(_fmt_money(balance), True))

        dd_text = due_dt.strftime("%Y-%m-%d") if due_dt else "-"
        dd_item = QTableWidgetItem(f"{dd_text}  •  {due_label}")
        dd_item.setBackground(due_bg); dd_item.setForeground(due_fg)
        self.table.setItem(r, 7, dd_item)

        self.table.setCellWidget(r, 8, progress_widget)

        actions = QWidget(); hl = QHBoxLayout(actions); hl.setContentsMargins(0,0,0,0); hl.setSpacing(0)
        tool = QToolButton(actions); tool.setText("⋯"); tool.setToolTip("Actions"); tool.setPopupMode(QToolButton.InstantPopup)
        tool.setStyleSheet("QToolButton { background:#e5e7eb; color:#111827; border-radius:8px; padding:4px 10px;} QToolButton::menu-indicator{image:none;} QToolButton:hover{background:#d1d5db;}")
        menu = QMenu(tool)
        act_view = QAction("View", menu)
        act_view_boq = QAction("View BoQ", menu)
        act_edit = QAction("Edit", menu)
        act_pay  = QAction("Record Payment", menu)
        act_ph   = QAction("Payment History", menu)
        act_dc   = QAction("Delivery Chalan", menu)
        act_ch   = QAction("Chalan History", menu)
        act_del  = QAction("Delete (Admin Only - Non Functional)", menu)
        if not self._is_admin: act_del.setEnabled(False)

        menu.addAction(act_view)
        menu.addAction(act_view_boq)
        menu.addAction(act_edit)
        menu.addSeparator()
        menu.addAction(act_pay)
        menu.addAction(act_ph)
        menu.addSeparator()
        menu.addAction(act_dc)
        menu.addAction(act_ch)
        menu.addSeparator()
        menu.addAction(act_del)
        tool.setMenu(menu)
        hl.addWidget(tool); hl.addStretch()
        self.table.setCellWidget(r, 9, actions)

        self.table.item(r, 0).setData(Qt.UserRole, doc_id)

        act_view.triggered.connect(lambda *_: self._open_invoice(doc_id, data, mode="view"))
        act_view_boq.triggered.connect(lambda *_: self._view_boq_merged(doc_id, data))
        act_edit.triggered.connect(lambda *_: self._open_invoice(doc_id, data, mode="edit"))
        act_pay.triggered.connect(lambda *_: self._record_payment(doc_id, data))
        act_ph.triggered.connect(lambda *_: self._view_payment_history(doc_id))
        act_dc.triggered.connect(lambda *_: self._create_delivery_chalan(doc_id, data))
        act_ch.triggered.connect(lambda *_: self._view_chalan_history(doc_id))
        act_del.triggered.connect(lambda *_: QMessageBox.information(self, "Delete", "Delete is admin-only and not implemented yet."))

        self._rows.append({
            "doc_id": doc_id, "invoice_no": inv_no, "type": inv_type, "status": status,
            "client": client_name, "total": total, "received": received, "balance": balance,
            "due_dt": due_dt, "due_label": due_label, "row_index": r
        })

    def _apply_filters(self):
        term = (self.search.text() or "").lower()
        which = self.filter_tabs.tabText(self.filter_tabs.currentIndex())
        visible = 0
        for row in self._rows:
            r = row["row_index"]
            row_text = " ".join([row["invoice_no"], row["type"], row["status"], row["client"],
                                 _fmt_money(row["total"]), _fmt_money(row["received"]), _fmt_money(row["balance"]),
                                 row["due_label"]]).lower()
            hit = (term in row_text)
            ok = True
            if which == "Pending":
                ok = row["status"].lower() not in ("paid", "cancelled") and (row["balance"] > 0.01)
            elif which == "Paid":
                ok = row["status"].lower() == "paid" or (row["balance"] <= 0.01 and row["total"] > 0)
            elif which == "Overdue":
                dd = row["due_dt"]; ok = dd is not None and (dd < _today()) and (row["balance"] > 0.01)
            elif which == "Quotations":
                ok = row["type"].lower() == "quotation"
            elif which == "Cash Sales":
                ok = row["type"].lower() == "cash sale"
            show = (hit and ok)
            self.table.setRowHidden(r, not show)
            if show: visible += 1
        self.count_lbl.setText(f"Showing {visible} / {len(self._rows)}")

    def _view_invoice(self, row, _col):
        item = self.table.item(row, 0)
        if not item: return
        doc_id = item.data(Qt.UserRole)
        snap = db.collection("invoices").document(doc_id).get()
        data = snap.to_dict() if snap.exists else {}
        self._open_invoice(doc_id, data, mode="view")

    def _open_invoice(self, doc_id, data, mode="view"):
        if mode == "view":
            dlg = InvoiceDetailsDialog(doc_id, data, self)
            self._child_windows.append(dlg)
            dlg.finished.connect(lambda *_,
                                 w=dlg: self._child_windows.remove(w) if w in self._child_windows else None)
            dlg.exec_(); return
        if InvoiceModule is None:
            QMessageBox.information(self, "Unavailable", "Invoice editor not available in this build.")
            return
        try:
            win = InvoiceModule(self.user_data)
            win.setAttribute(Qt.WA_DeleteOnClose, True)
            if hasattr(win, "load_invoice"):
                win.load_invoice(doc_id, data)
            win.setWindowTitle(f"Edit Invoice • {data.get('invoice_no', '')}")
            self._child_windows.append(win)
            win.destroyed.connect(lambda *_,
                                  w=win: self._child_windows.remove(w) if w in self._child_windows else None)
            win.show(); win.raise_(); win.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "Open Error", f"Unable to open editor:\n{e}")

    def _view_boq_merged(self, _doc_id, data):
        dlg = BoQMergedDialog(data, self)
        self._child_windows.append(dlg)
        dlg.finished.connect(lambda *_,
                             w=dlg: self._child_windows.remove(w) if w in self._child_windows else None)
        dlg.exec_()

    def _record_payment(self, doc_id, data):
        dlg = RecordPaymentDialog(self.user_data, doc_id, data, self)
        if dlg.exec_():
            self.load_invoices()

    def _view_payment_history(self, doc_id):
        dlg = PaymentHistoryDialog(doc_id, self)
        self._child_windows.append(dlg)
        dlg.finished.connect(lambda *_,
                             w=dlg: self._child_windows.remove(w) if w in self._child_windows else None)
        dlg.exec_()

    def _create_delivery_chalan(self, doc_id, data):
        """Open Delivery Chalan dialog for the selected invoice."""
        dlg = DeliveryChalanDialog(doc_id, data, self)
        if dlg.exec_():
            # optional: refresh the chalan history right away
            self._view_chalan_history(doc_id)


    def _view_chalan_history(self, doc_id):
        dlg = ChalanHistoryDialog(doc_id, self)
        self._child_windows.append(dlg)
        dlg.finished.connect(lambda *_,
                             w=dlg: self._child_windows.remove(w) if w in self._child_windows else None)
        dlg.exec_()

    def _new_invoice(self):
        if InvoiceModule is None:
            QMessageBox.information(self, "Unavailable", "Invoice editor not available in this build.")
            return
        try:
            win = InvoiceModule(self.user_data)
            win.setAttribute(Qt.WA_DeleteOnClose, True)
            self._child_windows.append(win)
            win.destroyed.connect(lambda *_,
                                  w=win: self._child_windows.remove(w) if w in self._child_windows else None)
            win.show(); win.raise_(); win.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "Open Error", f"Unable to open editor:\n{e}")

    def _export_csv_visible(self):
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(desktop):
                desktop = tempfile.gettempdir()
            path = os.path.join(desktop, "invoices_export.csv")
            headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f); writer.writerow(headers)
                for r in range(self.table.rowCount()):
                    if self.table.isRowHidden(r): continue
                    row = []
                    for c in range(self.table.columnCount()):
                        if c == 8:
                            w = self.table.cellWidget(r, c)
                            row.append(f"{w.value()}%" if isinstance(w, QProgressBar) else "")
                        elif c == 9:
                            row.append("")
                        else:
                            it = self.table.item(r, c); row.append(it.text() if it else "")
                    writer.writerow(row)
            QMessageBox.information(self, "Exported", f"CSV saved to: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
