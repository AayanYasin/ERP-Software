from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QLineEdit, QDateEdit, QDialog, QDialogButtonBox, QHeaderView,
    QMessageBox, QPushButton, QFileDialog, QMenu, QComboBox, QApplication,
    QGridLayout, QFrame, QToolButton, QGraphicsDropShadowEffect   # ← add
)
from PyQt5.QtCore import QDate, Qt, QSize
from PyQt5.QtGui import QIcon, QFont, QColor
from firebase.config import db
from firebase_admin import firestore
import datetime

from modules.journal_entry import JournalEntryForm


# ============================
# JournalEntryViewer (UI Rev B)
# ============================
# Goals (UI-only, no UX logic changed):
# - High-contrast, enterprise-neutral look (no emojis)
# - Bigger, readable fonts; stronger header; clearer row spacing
# - Numbers right-aligned + monospace
# - Table columns sized sanely with less jitter
# - Subtle zebra stripes, clearer selection
# - Keep all signals/flows untouched
#
# If you want ultra-compact or dark theme variant, shout and I'll switch presets.

class JournalEntryViewer(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setWindowTitle("Journal Entry Viewer")
        self.resize(1380, 760)

        # ===== Root layout =====
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ===== Header =====
        header = QHBoxLayout()
        title = QLabel("Journal Entries")
        title.setStyleSheet("font-weight:700;font-size:20px;letter-spacing:0.2px;")
        header.addWidget(title)
        header.addStretch(1)

        self.btn_clear = QPushButton("Clear Filters")
        self.btn_export = QPushButton("Export PDF")
        self.btn_refresh = QPushButton("Refresh")
        for b in (self.btn_clear, self.btn_export, self.btn_refresh):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(34)
            b.setStyleSheet("padding:6px 14px;border-radius:8px;border:1px solid #D0D7E2;background:#F8FAFF;")
        self.btn_clear.clicked.connect(self.clear_filters)
        self.btn_export.clicked.connect(self.export_to_pdf)
        self.btn_refresh.clicked.connect(self.load_entries)

        header.addWidget(self.btn_clear)
        header.addWidget(self.btn_export)
        header.addWidget(self.btn_refresh)
        root.addLayout(header)

        # ===== Filters row =====
        fl = QHBoxLayout(); fl.setSpacing(8)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Search description / reference…")
        self.search_input.textChanged.connect(self.apply_filters)

        self.account_filter = QComboBox(); self.account_filter.addItem("— All Accounts —", None)
        self.account_map, self.account_disp_map = {}, {}
        self.load_account_list(); self.account_filter.currentIndexChanged.connect(self.apply_filters)

        self.branch_filter = QComboBox(); self.load_branch_filter(); self.branch_filter.currentIndexChanged.connect(self.apply_filters)

        self.purpose_filter = QComboBox(); self.purpose_filter.addItem("— All Purposes —", None)
        for p in ["Sale","Purchase","Expense","Refund","Advance","Adjustment","Tax","Bank Charges","Salary","Other"]:
            self.purpose_filter.addItem(p, p)
        self.purpose_filter.currentIndexChanged.connect(self.apply_filters)

        self.from_date = QDateEdit(QDate.currentDate().addMonths(-1)); self.from_date.setCalendarPopup(True); self.from_date.setDisplayFormat("yyyy-MM-dd"); self.from_date.dateChanged.connect(self.apply_filters)
        self.to_date   = QDateEdit(QDate.currentDate());               self.to_date.setCalendarPopup(True);   self.to_date.setDisplayFormat("yyyy-MM-dd");   self.to_date.dateChanged.connect(self.apply_filters)

        fl.addWidget(QLabel("Search"));  fl.addWidget(self.search_input, 2)
        fl.addWidget(QLabel("Account")); fl.addWidget(self.account_filter, 2)
        fl.addWidget(QLabel("Branch"));  fl.addWidget(self.branch_filter, 1)
        fl.addWidget(QLabel("Purpose")); fl.addWidget(self.purpose_filter, 1)
        fl.addWidget(QLabel("From"));    fl.addWidget(self.from_date)
        fl.addWidget(QLabel("To"));      fl.addWidget(self.to_date)
        root.addLayout(fl)

        # ===== Table =====
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Date","Reference","Description","Purpose","Branch",
            "Debited Accounts","Credited Accounts","Amount (DR/CR)","User","Created At"
        ])

        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        # Reasonable defaults: fixed for meta, stretch for account columns
        for col in range(10):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)

        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_menu)
        self.table.cellDoubleClicked.connect(self.view_entry_details)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)

        root.addWidget(self.table)

        # ===== Totals =====
        self.total_label = QLabel("Total Debit: 0.00  —  Total Credit: 0.00")
        self.total_label.setObjectName("TotalsPill")
        root.addWidget(self.total_label)

        # ===== Global style (light, high-contrast) =====
        self.setStyleSheet(
            """
            QWidget { font-family: 'Segoe UI', 'Inter', sans-serif; font-size:14px; }
            QLineEdit, QComboBox, QDateEdit { padding:8px; border:1px solid #CBD5E1; border-radius:8px; background:#FFFFFF; }
            QTableWidget { gridline-color:#E2E8F0; alternate-background-color:#F8FAFC; selection-background-color:#1D4ED8; }
            QHeaderView::section { background:#FAFBFC; color:#334E68; padding:8px; border: 1px solid #E5E9F2; font-weight:600; }
            QLabel#TotalsPill { font-weight:700; font-size:13px; padding:10px 12px; border-radius:10px; background:#EEF2FF; color:#1E293B; }
            QTableWidget::item:selected { color:#FFFFFF; }
            QPushButton:hover { background:#EDF2FF; }
            """
        )

        # ===== Data caches & first load =====
        self.entries_cache = []
        self.filtered_entries = []
        self.load_entries()

        # ===== Floating Add button (visual only; behavior unchanged) =====
        self.btn_add_entry = QToolButton(self)
        self.btn_add_entry.setObjectName("FabAdd")
        self.btn_add_entry.setText("＋")                           # clean plus
        self.btn_add_entry.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_add_entry.setCursor(Qt.PointingHandCursor)
        self.btn_add_entry.setAutoRaise(True)
        self.btn_add_entry.setFixedSize(56, 56)                   # circle size
        self.btn_add_entry.setStyleSheet("""
            QToolButton#FabAdd {
                background: #10B981;        /* emerald */
                color: white;
                font-size: 26px;
                font-weight: 700;
                border-radius: 28px;        /* half of 56 = perfect circle */
            }
            QToolButton#FabAdd:hover { background: #0EA371; }
            QToolButton#FabAdd:pressed { background: #0C8D62; }
        """)
        # soft drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setOffset(0, 4)
        shadow.setBlurRadius(22)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.btn_add_entry.setGraphicsEffect(shadow)

        self.btn_add_entry.setToolTip("Add journal entry")
        self.btn_add_entry.clicked.connect(self.add_journal_entry)
        self._position_fab()
        self.btn_add_entry.raise_()

    # ===== Helpers: visuals =====
    def _position_fab(self):
        if not hasattr(self, "btn_add_entry"):
            return
        margin_x = 30   # distance from right edge
        margin_y = 80   # distance from bottom edge
        s = self.btn_add_entry.height()  # button size (50px)
        hsb = getattr(self.table, "horizontalScrollBar", None)
        bar_h = self.table.horizontalScrollBar().height() if (hsb and self.table.horizontalScrollBar().isVisible()) else 0
        x = max(margin_x, self.width() - s - margin_x)
        y = max(margin_y, self.height() - s - margin_y - bar_h)
        self.btn_add_entry.move(x, y)

    def resizeEvent(self, event):
        self._position_fab();
        super().resizeEvent(event)

    # ===== Open form (logic untouched) =====
    def add_journal_entry(self):
        try:
            form = JournalEntryForm(self.user_data, parent=self)
        except TypeError:
            form = JournalEntryForm(self.user_data)
        for sig_name in ("entry_saved","saved","posted"):
            try:
                getattr(form, sig_name).connect(self.load_entries)
                break
            except Exception:
                pass
        if isinstance(form, QDialog) or hasattr(form, "finished"):
            try:
                form.finished.connect(lambda _: self.load_entries())
            except Exception:
                pass
            if hasattr(form, "exec_"):
                form.exec_()
            elif hasattr(form, "exec"):
                form.exec()
            else:
                form.setModal(True); form.show()
            return
        form.setAttribute(Qt.WA_DeleteOnClose, True)
        try:
            form.destroyed.connect(lambda *_: self.load_entries())
        except Exception:
            pass
        form.show()

    # ===== Date helpers =====
    def _to_datetime(self, val):
        if val is None: return None
        if hasattr(val, "to_datetime"):
            try: return val.to_datetime()
            except Exception: pass
        if isinstance(val, datetime.datetime): return val
        if isinstance(val, str):
            for fmt in ("%Y-%m-%d",):
                try: return datetime.datetime.strptime(val, fmt)
                except Exception: pass
            try: return datetime.datetime.fromisoformat(val.replace("Z","+00:00"))
            except Exception: return None
        return None

    def _to_qdate(self, val):
        dt = self._to_datetime(val)
        if dt: return QDate(dt.year, dt.month, dt.day)
        if isinstance(val, str):
            qd = QDate.fromString(val, "yyyy-MM-dd")
            return qd if qd.isValid() else None
        return None

    def _date_to_string(self, val):
        dt = self._to_datetime(val)
        if dt: return dt.strftime("%Y-%m-%d")
        if isinstance(val, str): return val
        return ""

    def _datetime_to_string(self, val):
        dt = self._to_datetime(val)
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""

    def _resolve_account_name(self, account_id, fallback=None):
        return self.account_map.get(account_id) or fallback or f"{account_id}"

    def _resolve_branch_for_entry(self, data):
        return data.get("branch") or "-"

    def _format_lines_by_side(self, lines):
        debited, credited = [], []
        for ln in lines:
            name = ln.get("account_name") or self._resolve_account_name(ln.get("account_id",""), "-")
            d = float(ln.get("debit",0) or 0); c = float(ln.get("credit",0) or 0)
            if d>0: debited.append(name)
            if c>0: credited.append(name)
        return " • ".join(debited) if debited else "-", " • ".join(credited) if credited else "-"

    # ===== Filters data =====
    def load_branch_filter(self):
        self.branch_filter.clear()
        role = self.user_data.get("role", "")
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str): branches = [branches]
        if role == "admin":
            self.branch_filter.addItem("— All Branches —", None)
            for b in branches: self.branch_filter.addItem(b, b)
        else:
            if branches: self.branch_filter.addItem(branches[0], branches[0])
            else: self.branch_filter.addItem("-", None)
            self.branch_filter.setDisabled(True)

    def load_account_list(self):
        self.account_map.clear(); self.account_disp_map.clear()
        self.account_filter.clear(); self.account_filter.addItem("— All Accounts —", None)
        for doc in db.collection("accounts").stream():
            acc = doc.to_dict() or {}
            name, code = acc.get("name",""), acc.get("code","")
            disp = f"[{code}] {name}" if code else name
            self.account_map[doc.id] = name
            self.account_disp_map[doc.id] = disp
            self.account_filter.addItem(disp, doc.id)

    # ===== Load entries =====
    def load_entries(self):
        try:
            self.entries_cache = []
            query = db.collection("journal_entries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
            for doc in query:
                data = doc.to_dict() or {}
                data["doc_id"] = doc.id

                data["_date_q"] = self._to_qdate(data.get("date"))
                data["_date_str"] = self._date_to_string(data.get("date"))
                data["_reference"] = data.get("reference_no") or data.get("reference") or "-"
                data["_description"] = data.get("description", "")
                data["_purpose"] = data.get("purpose") or "-"
                data["_branch"] = self._resolve_branch_for_entry(data)
                data["_user"] = data.get("created_by", "-")
                data["_created_at_str"] = self._datetime_to_string(data.get("created_at") or data.get("date"))

                fixed_lines = []
                for ln in (data.get("lines", []) or []):
                    ln = dict(ln or {})
                    if not ln.get("account_name"):
                        ln["account_name"] = self._resolve_account_name(ln.get("account_id",""), "-")
                    ln["debit"] = float(ln.get("debit",0) or 0)
                    ln["credit"] = float(ln.get("credit",0) or 0)
                    ln["balance_before"] = float(ln.get("balance_before",0) or 0.0)
                    fixed_lines.append(ln)
                data["_lines"] = fixed_lines
                data["_debit_sum"] = sum(l["debit"] for l in fixed_lines)
                data["_credit_sum"] = sum(l["credit"] for l in fixed_lines)
                data["_debited_str"], data["_credited_str"] = self._format_lines_by_side(fixed_lines)

                self.entries_cache.append(data)

            self.apply_filters()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load journal entries:{e}")

    # ===== Balance helpers =====
    def _fmt_balance(self, amount, acc_type):
        if acc_type in ("Asset","Expense"): dr = (amount >= 0)
        else: dr = (amount < 0)
        return f"{abs(amount):,.2f} {'DR' if dr else 'CR'}"

    def _account_type(self, acc_id: str) -> str:
        if not hasattr(self, "_acct_type_cache"): self._acct_type_cache = {}
        if acc_id in self._acct_type_cache: return self._acct_type_cache[acc_id]
        try:
            snap = db.collection("accounts").document(acc_id).get()
            a_type = (snap.to_dict() or {}).get("type", "Asset")
        except Exception:
            a_type = "Asset"
        self._acct_type_cache[acc_id] = a_type
        return a_type

    # ===== Filtering + display =====
    def clear_filters(self):
        self.search_input.clear(); self.account_filter.setCurrentIndex(0); self.branch_filter.setCurrentIndex(0); self.purpose_filter.setCurrentIndex(0)
        self.from_date.setDate(QDate.currentDate().addMonths(-1)); self.to_date.setDate(QDate.currentDate())
        self.apply_filters()

    def apply_filters(self):
        self.table.setRowCount(0); self.filtered_entries = []
        search_text = (self.search_input.text() or "").lower().strip()
        selected_account_id = self.account_filter.currentData()
        selected_branch = self.branch_filter.currentData()
        selected_purpose = self.purpose_filter.currentData()
        from_qd, to_qd = self.from_date.date(), self.to_date.date()

        total_debit = 0.0; total_credit = 0.0
        mono = QFont("Consolas"); mono.setStyleHint(QFont.Monospace)

        for data in self.entries_cache:
            entry_qd = data.get("_date_q")
            if not entry_qd or entry_qd < from_qd or entry_qd > to_qd: continue
            if search_text:
                if (search_text not in data.get("_description","" ).lower() and search_text not in data.get("_reference","-").lower()):
                    continue
            if selected_account_id:
                if not any(ln.get("account_id") == selected_account_id for ln in data.get("_lines",[])): continue
            if selected_branch and data.get("_branch") != selected_branch: continue
            if selected_purpose and (data.get("_purpose") != selected_purpose): continue

            self.filtered_entries.append(data)
            total_debit += data.get("_debit_sum",0.0); total_credit += data.get("_credit_sum",0.0)

            row = self.table.rowCount(); self.table.insertRow(row)
            def put(col, text, right=False, mono_font=False):
                it = QTableWidgetItem(text if text is not None else "-")
                if right: it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if mono_font: it.setFont(mono)
                self.table.setItem(row, col, it)
            put(0, data.get("_date_str",""))
            put(1, data.get("_reference","-"))
            put(2, data.get("_description",""))
            put(3, data.get("_purpose","-"))
            put(4, data.get("_branch","-"))
            put(5, data.get("_debited_str","-"))
            put(6, data.get("_credited_str","-"))
            put(7, f"{abs(data.get('_debit_sum',0.0)):,.2f}", right=True, mono_font=True)
            put(8, data.get("_user","-"))
            put(9, data.get("_created_at_str",""))
            self.table.item(row,0).setData(Qt.UserRole, data)

        self.table.resizeColumnsToContents()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        self.total_label.setText(f"Total Debit: {total_debit:,.2f}  —  Total Credit: {total_credit:,.2f}")
        
    def _signed_amount(self, debit: float, credit: float, acc_type: str,
                   *, is_opening: bool = False, is_ob_equity: bool = False) -> float:
        # Base sign rule (unchanged)
        amt = (debit - credit) if acc_type in ("Asset", "Expense") else (credit - debit)
        # Special DISPLAY override: in Opening Balance JEs, flip "Opening Balances Equity"
        if is_opening and is_ob_equity:
            amt = -amt
        return amt


    # ===== Detail dialog (visual polish only) =====
    def view_entry_details(self, row, column):
        item = self.table.item(row, 0)
        if not item: return
        data = item.data(Qt.UserRole) or {}

        dlg = QDialog(self); dlg.setWindowTitle(f"Journal Entry — {data.get('_reference','-')}"); dlg.setMinimumWidth(860)
        root = QVBoxLayout(dlg); root.setSpacing(10)

        head = QHBoxLayout()
        left = QVBoxLayout(); left.addWidget(QLabel("Journal Entry")); left.addWidget(QLabel(f"Ref: {data.get('_reference','-')}")); left.addStretch(1)
        tag = QLabel(data.get("_purpose") or "-"); tag.setStyleSheet("background:#E2E8F0;border-radius:10px;padding:4px 10px;font-weight:600;")
        head.addLayout(left); head.addStretch(1); head.addWidget(tag)
        root.addLayout(head)

        info_box = QFrame(); info_box.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px}")
        info = QGridLayout(info_box); info.setContentsMargins(12,10,12,10); info.setHorizontalSpacing(18); info.setVerticalSpacing(6)
        def keylbl(t): return QLabel(f"<span style='color:#475569'>{t}</span>")
        def vallbl(t): w = QLabel(f"<b>{t}</b>"); w.setTextInteractionFlags(Qt.TextSelectableByMouse); return w
        info.addWidget(keylbl("Date"),0,0);       info.addWidget(vallbl(data.get("_date_str","")),0,1)
        info.addWidget(keylbl("Branch"),0,2);     info.addWidget(vallbl(data.get("_branch","-")),0,3)
        info.addWidget(keylbl("Created At"),1,0); info.addWidget(vallbl(data.get("_created_at_str","")),1,1)
        info.addWidget(keylbl("User"),1,2);       info.addWidget(vallbl(data.get("_user","-")),1,3)
        info.addWidget(keylbl("Description"),2,0); d = QLabel(data.get("_description","")); d.setWordWrap(True); d.setTextInteractionFlags(Qt.TextSelectableByMouse); info.addWidget(d,2,1,1,3)
        root.addWidget(info_box)

        # Lines table
        lines_box = QFrame(); lines_box.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px}")
        lv = QVBoxLayout(lines_box); lv.setContentsMargins(12,10,12,10); lv.setSpacing(6)
        lv.addWidget(QLabel("Lines"))
        table = QTableWidget(0,5)
        table.setHorizontalHeaderLabels(["Account","DR/CR","Amount","Previous Balance","New Balance"])
        h = table.horizontalHeader(); h.setStretchLastSection(False); h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1,2,3,4): h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        table.setAlternatingRowColors(True); table.setEditTriggers(QTableWidget.NoEditTriggers); table.setSelectionMode(QTableWidget.NoSelection)
        mono = QFont("Consolas"); mono.setStyleHint(QFont.Monospace)

        debit_total = credit_total = 0.0
        for ln in (data.get("_lines", []) or []):
            acc_name = ln.get("account_name","-")
            acc_id   = ln.get("account_id","")
            d_amt = float(ln.get("debit",0) or 0.0)
            c_amt = float(ln.get("credit",0) or 0.0)
            prev   = float(ln.get("balance_before",0) or 0.0)

            side = "DR" if d_amt>0 else ("CR" if c_amt>0 else "-")
            acc_type = self._account_type(acc_id)

            # ↓↓↓ add these three lines / replace your existing flags + signed_amt calc
            is_opening = (data.get("meta",{}) or {}).get("kind") == "opening_balance"
            eq_id = self._opening_equity_id()
            is_ob_equity = (acc_id == eq_id) or (acc_name == "Opening Balances Equity")

            signed_amt = self._signed_amount(d_amt, c_amt, acc_type,
                                            is_opening=is_opening, is_ob_equity=is_ob_equity)

            # Net movement for balances (same as signed amount),
            # but OB Equity in opening JEs keeps balance frozen below.
            net = self._signed_amount(d_amt, c_amt, acc_type)  # base rule for movement

            is_equity_ob_line = is_opening and is_ob_equity
            new_signed = prev if is_equity_ob_line else (prev + net)

            r = table.rowCount(); table.insertRow(r)
            table.setItem(r,0,QTableWidgetItem(acc_name))
            table.setItem(r,1,QTableWidgetItem(side))  # keep side column for reference
            amt_item = QTableWidgetItem(f"{signed_amt:,.2f}")             # ← signed (no DR/CR text)
            amt_item.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter); amt_item.setFont(mono); table.setItem(r,2,amt_item)

            prev_item = QTableWidgetItem(f"{prev:,.2f}")                  # ← signed previous balance
            prev_item.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter); prev_item.setFont(mono); table.setItem(r,3,prev_item)

            new_item = QTableWidgetItem(f"{new_signed:,.2f}")             # ← signed new balance
            new_item.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter); new_item.setFont(mono); table.setItem(r,4,new_item)

            debit_total += d_amt; credit_total += c_amt

        table.resizeColumnsToContents(); lv.addWidget(table)
        tot = QHBoxLayout(); tot.addStretch(1)
        t = QLabel(f"Total: {debit_total:,.2f} DR  •  {credit_total:,.2f} CR")  # totals label unchanged
        t.setStyleSheet("color:#334155;font-weight:600"); tot.addWidget(t)
        lv.addLayout(tot)
        root.addWidget(lines_box)

        btns = QDialogButtonBox(QDialogButtonBox.Close); btns.rejected.connect(dlg.reject); root.addWidget(btns)
        dlg.exec_()


    def table_menu(self, position):
        item = self.table.itemAt(position)
        if not item: return
        data = item.data(Qt.UserRole)
        menu = QMenu()
        copy_act = menu.addAction("Copy Reference")
        view_act = menu.addAction("View Details")
        delete_act = None
        if self.user_data.get("role") in ("admin",):
            delete_act = menu.addAction("Delete Entry (Reverses Balances)")
        action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if action == copy_act:
            ref = data.get("_reference","-")
            QApplication.clipboard().setText(ref)
            QMessageBox.information(self, "Copied", f"Reference copied:{ref}")
        elif action == view_act:
            idx = self.table.indexAt(position)
            self.view_entry_details(idx.row(), idx.column())
        elif delete_act and action == delete_act:
            self._delete_entry_with_reversal(data)

    def _opening_equity_id(self):
        if hasattr(self, "_opening_equity_id_cache"): return self._opening_equity_id_cache
        try:
            q = db.collection("accounts").where("slug","==","opening_balances_equity").limit(1).get()
            self._opening_equity_id_cache = q[0].id if q else None
        except Exception:
            self._opening_equity_id_cache = None
        return self._opening_equity_id_cache

    def _delete_entry_with_reversal(self, data):
        if self.user_data.get("role") != "admin":
            QMessageBox.warning(self, "Not Allowed", "Only admins can delete journal entries.")
            return
        ref = data.get("_reference","-")
        if QMessageBox.question(self, "Confirm Deletion", f"Delete journal entry {ref}? This will reverse balances on all impacted accounts.", QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            lines = data.get("_lines",[]) or []
            if not lines:
                snap = db.collection("journal_entries").document(data["doc_id"]).get()
                if snap.exists: lines = (snap.to_dict() or {}).get("lines",[]) or []
            account_types = {}
            for ln in lines:
                acc_id = ln.get("account_id")
                if acc_id and acc_id not in account_types:
                    acc_doc = db.collection("accounts").document(acc_id).get()
                    account_types[acc_id] = (acc_doc.to_dict() or {}).get("type","Asset")
            for ln in lines:
                acc_id = ln.get("account_id");
                if not acc_id: continue
                acc_type = account_types.get(acc_id,"Asset")
                d = float(ln.get("debit",0) or 0.0); c = float(ln.get("credit",0) or 0.0)
                net = (d - c) if acc_type in ["Asset","Expense"] else (c - d)
                if net != 0:
                    db.collection("accounts").document(acc_id).update({"current_balance": firestore.Increment(-net)})
            db.collection("journal_entries").document(data["doc_id"]).delete()
            QMessageBox.information(self, "Deleted", f"Entry {ref} deleted and balances reversed.")
            self.load_entries()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Delete failed: {e}")

    def export_to_pdf(self):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        now_str = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", f"LedgerExport-{now_str}.pdf", "PDF Files (*.pdf)")
        if not path: return
        if not path.lower().endswith(".pdf"): path += ".pdf"
        try:
            pdf = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
            elements = []
            styles = getSampleStyleSheet()
            title_style = styles["Title"]; title_style.fontSize = 13; title_style.leading = 16

            wrap_style = ParagraphStyle(
                "wrap", parent=styles["Normal"], fontName="Helvetica",
                fontSize=7.5, leading=9.2, wordWrap="CJK"
            )

            # NEW: bold styles for main rows
            bold_style = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9.2)
            bold_wrap_style = ParagraphStyle("bold_wrap", parent=wrap_style, fontName="Helvetica-Bold")

            elements += [
                Paragraph("Journal Entries", title_style),
                Paragraph(f"<font size='8.5'>Range: {self.from_date.date().toString('yyyy-MM-dd')} → {self.to_date.date().toString('yyyy-MM-dd')}</font>", styles["Normal"]),
                Spacer(1,6)
            ]

            # Header text changed: remove (DR/CR)
            headers = ["Date","Reference","Description","Purpose","Branch","Account","Amount","New Balance"]
            data = [headers]

            for e in self.filtered_entries:
                desc_p = Paragraph(e.get("_description", "") or "-", wrap_style)
                line_rows = []
                for ln in (e.get("_lines",[]) or []):
                    name = ln.get("account_name") or "-"
                    acc_id = ln.get("account_id","")
                    d = float(ln.get("debit",0) or 0.0)
                    c = float(ln.get("credit",0) or 0.0)
                    prev = float(ln.get("balance_before",0) or 0.0)

                    acc_type = self._account_type(acc_id)

                    is_opening = (e.get("meta",{}) or {}).get("kind") == "opening_balance"
                    eq_id = self._opening_equity_id()
                    is_ob_equity = (acc_id == eq_id) or (name == "Opening Balances Equity")

                    # DISPLAY sign (with OB Equity flip on opening JEs)
                    signed_amt = self._signed_amount(d, c, acc_type,
                                                    is_opening=is_opening, is_ob_equity=is_ob_equity)

                    # Movement uses the base rule; we’ll freeze OB Equity below
                    net = self._signed_amount(d, c, acc_type)

                    is_equity_ob_line = is_opening and is_ob_equity
                    new_signed = prev if is_equity_ob_line else (prev + net)

                    line_rows.append(["","","","","", name, f"{signed_amt:,.2f}", f"{new_signed:,.2f}"])

                # Main row: bold cells, no amount
                main_row = [
                    Paragraph(e.get("_date_str","") or "-", bold_style),
                    Paragraph(e.get("_reference","-") or "-", bold_style),
                    Paragraph(e.get("_description","") or "-", bold_wrap_style),
                    Paragraph(e.get("_purpose","-") or "-", bold_style),
                    Paragraph(e.get("_branch","-") or "-", bold_style),
                    "—",   # Account
                    "",    # Amount (blank on main row)
                    "—"    # New Balance
                ]
                data.append(main_row)
                data.extend(line_rows)

            def maxlen(col):
                m = 0
                for r in data[1:]:
                    v = r[col]
                    if isinstance(v, Paragraph):
                        from xml.sax.saxutils import unescape
                        v = unescape(v.getPlainText())
                    m = max(m, len(str(v)))
                return m

            w=[maxlen(0)*0.8, maxlen(1)*0.85, 28, maxlen(3)*0.5, maxlen(4)*0.6, 26, maxlen(6)*0.7, maxlen(7)*0.7]
            mins=[40,85,120,55,55,140,80,90]; avail=pdf.width; total=sum(max(a,b) for a,b in zip(w,mins))
            col_widths=[avail*(max(a,b)/total) for a,b in zip(w,mins)]

            tbl = Table(data, colWidths=col_widths, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#FAFBFC")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#334E68")),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,0), 9),
                ("ALIGN", (0,0), (-1,0), "CENTER"),
                ("BOTTOMPADDING", (0,0), (-1,0), 5),
                ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
                ("FONTSIZE", (0,1), (-1,-1), 7.5),
                ("VALIGN", (0,1), (-1,-1), "TOP"),
                ("ALIGN", (6,1), (7,-1), "RIGHT"),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor("#F8FAFC")]),
                ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
                ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ]))
            pdf.build(elements+[tbl])
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
