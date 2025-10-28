# modules/journal_entry.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDateEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QLabel, QHBoxLayout,
    QMessageBox, QHeaderView, QAbstractItemView, QCompleter, QFrame, QSpacerItem, QSizePolicy, QStyledItemDelegate, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont, QDoubleValidator, QColor
from firebase.config import db
import uuid
import datetime
from firebase_admin import firestore

class CellEditorDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        # numeric editors for Debit/Credit columns
        if index.column() in (1, 2):
            e = QLineEdit(parent)
            e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            e.setValidator(QDoubleValidator(0.0, 1e12, 2))
            return e
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            editor.setText(index.data() or "0.00")
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def updateEditorGeometry(self, editor, option, index):
        # fill the cell so nothing shows beneath, but stay inside borders
        editor.setGeometry(option.rect)


class JournalEntryForm(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.setWindowTitle("New Journal Entry")
        self.setMinimumSize(1100, 640)

        # ---------- Visual polish ----------
        self._apply_styles()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # === Header card ===
        header_card = self._card()
        header_layout = QFormLayout()
        header_layout.setLabelAlignment(Qt.AlignRight)
        header_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.setHorizontalSpacing(14)
        header_layout.setVerticalSpacing(10)
        header_card.setLayout(header_layout)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMinimumWidth(220)
        header_layout.addRow("Date:", self._wrap(self.date_edit))

        self.ref_input = QLineEdit()
        self.ref_input.setPlaceholderText("[Will Be Auto-generated]")
        self.ref_input.setReadOnly(True)
        header_layout.addRow("Reference No:", self._wrap(self.ref_input))

        self.purpose_cb = QComboBox()
        self.purpose_cb.addItems([
            "Sale", "Purchase", "Expense", "Refund",
            "Advance", "Adjustment", "Tax", "Bank Charges", "Salary", "Other"
        ])
        self.purpose_cb.setEditable(False)
        header_layout.addRow("Purpose of Payment:", self._wrap(self.purpose_cb))

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Add a short description (optional)")
        header_layout.addRow("Description:", self._wrap(self.desc_input))

        root.addWidget(header_card)

        # === Table card ===
        table_card = self._card()
        table_v = QVBoxLayout()
        table_v.setContentsMargins(8, 8, 8, 8)
        table_v.setSpacing(8)
        table_card.setLayout(table_v)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Account", "Debit", "Credit", "Balance"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(True)
        self.table.setContentsMargins(0, 0, 0, 0)
        self.table.setWordWrap(False)

        # slightly taller default row height (also set in _add_row)
        self.table.setStyleSheet(self.table.styleSheet() + " QTableView::item{ padding:0px; } ")
        
        self.table.setItemDelegate(CellEditorDelegate(self.table))

        table_v.addWidget(self.table)
        root.addWidget(table_card)

        # # Load accounts BEFORE creating rows (so dropdowns populate)
        self.accounts = []
        self.load_accounts()

        # Create exactly 2 lines by default
        self._add_row()
        self._add_row()

        # Keep totals & row balances updating as user types
        self.table.itemChanged.connect(lambda *_: (self.update_totals(), self.update_row_balances()))

        # === Footer / totals bar ===
        footer_bar = self._footer_bar()
        footer_layout = QHBoxLayout(footer_bar)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.setSpacing(12)

        self.total_label = QLabel("💰 Debit: 0.00   💸 Credit: 0.00")
        self.total_label.setObjectName("Totals")
        self.total_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        footer_layout.addWidget(self.total_label)
        footer_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setMinimumHeight(44)
        self.btn_save.setMinimumWidth(180)
        self.btn_save.setAutoDefault(True)
        self.btn_save.setDefault(True)
        self.btn_save.setShortcut("Ctrl+S")
        self.btn_save.setToolTip("Save (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_entry)

        # 👇 make Qt (not the OS theme) paint the button so radius applies
        self.btn_save.setFlat(True)
        self.btn_save.setAutoFillBackground(True)

        # (optional) re-apply the soft shadow after styling
        shadow = QGraphicsDropShadowEffect(self.btn_save)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.btn_save.setGraphicsEffect(shadow)

        # styles (no box-shadow; Qt-safe)
        # Style *only this* button by its objectName (highest precedence, no conflicts)
        self.btn_save.setStyleSheet("""
        #PrimaryButton {
            background-color: #10B981;  /* light green you asked for */
            color: #ffffff;
            border: 0px;
            border-radius: 8px;        /* ~half of 44px height for a pill */
            padding: 10px 22px;
            font-weight: 600;
            letter-spacing: 0.2px;
        }
        #PrimaryButton:hover { background-color: #0ea371; }
        #PrimaryButton:pressed {
            background-color: #0c8e63;
            padding-top: 11px;          /* subtle press effect */
            padding-bottom: 9px;
        }
        #PrimaryButton:disabled { background-color: #a7e5c9; color: #e8f5e9; }
        #PrimaryButton:focus { border: 2px solid #81c784; outline: none; }
        """)
        footer_layout.addWidget(self.btn_save)

        root.addWidget(footer_bar)

        # Ensure accounts list is fresh after UI assembled (idempotent)
        self.accounts = []
        self.load_accounts()
        self.update_totals()

    # ---------- UI helpers (visual only) ----------
    def _apply_styles(self):
        # Soft theme with light headers
        self.setStyleSheet("""
            QWidget {
                font-size: 14px;
            }
            QFrame#Card {
                background: #ffffff;
                border: 1px solid #e9edf3;
                border-radius: 12px;
            }
            QFrame#Footer {
                background: #fbfcfe;
                border: 1px solid #e9edf3;
                border-radius: 14px;
            }
            QLabel {
                color: #1f2a37;
            }
            QLabel#Totals {
                font-weight: 600;
                letter-spacing: 0.2px;
            }
            QLineEdit, QComboBox, QDateEdit {
                background: #ffffff;
                border: 1px solid #d8dee9;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
                border: 2px solid #90caf9;
                background-color: #f0f7ff;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #d8dee9;
                background: #ffffff;
                selection-background-color: #e9f3ff;
                outline: none;
            }
            /* Table */
            QHeaderView::section {
                background: #f5f7fb;
                color: #334155;
                padding: 8px 10px;
                border: 0px;
                border-right: 1px solid #e6ebf3;
                font-weight: 600;
            }
            QTableWidget {
                background: #ffffff;
                border: 1px solid #e9edf3;
                border-radius: 10px;
                gridline-color: #eef2f7;
                selection-background-color: #e9f3ff;
                selection-color: #111827;
                alternate-background-color: #fcfdff;
            }
            QTableWidget::item {
                padding: 8px 10px;
            }
        """)

        # Slightly larger base font for readability
        f = self.font()
        f.setPointSize(11)
        self.setFont(f)

    def _card(self):
        card = QFrame()
        card.setObjectName("Card")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Plain)
        return card

    def _footer_bar(self):
        footer = QFrame()
        footer.setObjectName("Footer")
        footer.setFrameShape(QFrame.StyledPanel)
        footer.setFrameShadow(QFrame.Plain)
        return footer

    def _wrap(self, w):
        # Provide a container to keep consistent spacing and allow future adornments
        box = QHBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        cont = QFrame()
        cont.setLayout(box)
        box.addWidget(w)
        return cont

    # ---------- Existing UX / logic kept identical below ----------
    def _add_row(self):
        """Insert one row with an account dropdown, zeroed amounts, and read-only live Balance."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 55)  # roomier rows

        combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumWidth(260)

        # Better contains matching for long charts
        combo_completer = combo.completer()
        combo_completer.setFilterMode(Qt.MatchContains)
        combo_completer.setCompletionMode(QCompleter.PopupCompletion)

        # Placeholder first so it's not auto-selected
        combo.addItem("", None)
        for acc in self.accounts:
            label = f"[{acc['code']}] {acc['name']}"
            combo.addItem(label, acc)

        # Recalc balances when account changes
        combo.currentIndexChanged.connect(lambda *_: self.update_row_balances())
        
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        combo.setMinimumHeight(38)  # matches row height visually
        combo.setStyleSheet("""
            QComboBox { border: 1px solid #d8dee9; border-radius: 6px; }
            QComboBox::drop-down { width: 22px; }
        """)

        self.table.setCellWidget(row, 0, combo)

        # Numeric cells: right-aligned by default for readability
        debit_item = QTableWidgetItem("0.00")
        debit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        credit_item = QTableWidgetItem("0.00")
        credit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 1, debit_item)
        self.table.setItem(row, 2, credit_item)

        # Read-only Balance cell
        bal_item = QTableWidgetItem("-")
        bal_item.setFlags(bal_item.flags() & ~Qt.ItemIsEditable)
        bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 3, bal_item)

    def update_row_balances(self):
        """Show projected balance (current_balance ± this row's net change) for each row."""
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            bal_item = self.table.item(row, 3)
            if not combo or bal_item is None:
                continue

            acc = combo.currentData()  # dict or None
            try:
                debit = float(self.table.item(row, 1).text())
                credit = float(self.table.item(row, 2).text())
            except Exception:
                debit = credit = 0.0

            if not acc:
                bal_item.setText("-")
                continue

            base = float(acc.get("balance", 0.0))
            acc_type = acc.get("type", "Asset")

            # Net change matches your posting logic
            net = (debit - credit) if acc_type in ["Asset", "Expense"] else (credit - debit)
            projected = base + net

            # Show with DR/CR tag based on account type/sign
            if acc_type in ["Asset", "Expense"]:
                dr = projected >= 0
            else:
                dr = projected < 0

            bal_item.setText(f"{abs(projected):,.2f} {'DR' if dr else 'CR'}")

    def load_accounts(self):
        """Load only active, posting accounts that match the current user's branch(es)."""
        self.accounts = []
        try:
            # Normalize the user's branches to a list
            user_branch = self.user_data.get("branch")
            if isinstance(user_branch, str):
                branches = [user_branch]
            elif isinstance(user_branch, list):
                branches = user_branch
            else:
                branches = []

            fields = ["code","name","type","current_balance","opening_balance",
                    "slug","is_posting","active","branch"]

            # Base query: active accounts only
            q = db.collection("accounts").where("active", "==", True).select(fields)

            # Restrict to the user's branch(es) if provided
            # (expects account docs to store branch as an array)
            if branches:
                q = q.where("branch", "array_contains_any", branches)

            docs = q.get()

            for doc in docs:
                data = doc.to_dict() or {}

                # Skip Opening Balances Equity account by slug (unchanged behavior)
                if data.get("slug") == "opening_balances_equity":
                    continue

                if data.get("is_posting", True):
                    current_balance = data.get("current_balance")
                    opening = data.get("opening_balance") or {}
                    if current_balance is None:
                        current_balance = float(opening.get("amount", 0.0))

                    self.accounts.append({
                        "id": doc.id,
                        "code": data.get("code"),
                        "name": data.get("name"),
                        "type": data.get("type"),
                        "balance": float(current_balance),
                        "balance_type": opening.get("type", "debit")
                    })
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load accounts: {e}")

            
    def update_totals(self):
        debit, credit = 0, 0
        for row in range(self.table.rowCount()):
            try:
                debit += float(self.table.item(row, 1).text())
                credit += float(self.table.item(row, 2).text())
            except:
                pass
        self.total_label.setText(f"💰 Debit: {debit:.2f}   💸 Credit: {credit:.2f}")
        self.update_row_balances()

    def save_entry(self):
        # ✅ Prevent selecting the same account in both lines
        if self.table.rowCount() >= 2:
            acc1 = self.table.cellWidget(0, 0).currentData()
            acc2 = self.table.cellWidget(1, 0).currentData()
            if acc1 and acc2 and acc1.get("id") == acc2.get("id"):
                QMessageBox.warning(
                    self,
                    "Invalid Selection",
                    "You cannot select the same account in both lines."
                )
                return
            
        date_py = self.date_edit.date().toPyDate()
        date = datetime.datetime.combine(date_py, datetime.datetime.min.time())
        desc = self.desc_input.text().strip()
        ref = f"JE-{uuid.uuid4().hex[:6].upper()}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
        purpose = self.purpose_cb.currentText().strip() if hasattr(self, "purpose_cb") else ""

        lines, debit_total, credit_total = [], 0.0, 0.0
        balance_updates = {}

        # Build lines
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if not combo:
                continue
            account = combo.currentData()
            if not account:
                continue

            try:
                debit = float(self.table.item(row, 1).text())
                credit = float(self.table.item(row, 2).text())
            except Exception:
                debit = credit = 0.0

            if debit == 0 and credit == 0:
                continue

            # Net change by account type
            if account["type"] in ["Asset", "Expense"]:
                net_change = debit - credit
            else:  # Liability, Equity, Income
                net_change = credit - debit

            try:
                snap = db.collection("accounts").document(account["id"]).get()
                acc_doc = snap.to_dict() or {}
                pre_bal = float(acc_doc.get("current_balance", 0.0) or 0.0)
            except Exception:
                pre_bal = 0.0

            lines.append({
                "account_id": account["id"],
                "account_name": account["name"],
                "debit": debit,
                "credit": credit,
                "balance_before": pre_bal,   # snapshot
            })

            balance_updates.setdefault(account["id"], 0.0)
            balance_updates[account["id"]] += net_change

            debit_total += debit
            credit_total += credit

        # --- Validations (unchanged) ---
        
        if self.table.rowCount() != 2:
            QMessageBox.warning(self, "Validation", "Exactly two lines are required.")
            return

        if len(lines) != 2:
            QMessageBox.warning(self, "Validation", "Both lines must have values (no empty lines).")
            return

        if any((l["debit"] > 0 and l["credit"] > 0) or (l["debit"] == 0 and l["credit"] == 0) for l in lines):
            QMessageBox.warning(self, "Validation", "Each line must have either a Debit or a Credit (not both or neither).")
            return

        debit_lines = [l for l in lines if l["debit"] > 0 and l["credit"] == 0]
        credit_lines = [l for l in lines if l["credit"] > 0 and l["debit"] == 0]
        if len(debit_lines) != 1 or len(credit_lines) != 1:
            QMessageBox.warning(self, "Validation", "You need exactly one debit line and one credit line.")
            return

        if round(debit_total, 2) != round(credit_total, 2):
            QMessageBox.warning(self, "Validation", "Debits and Credits must match.")
            return

        if any(l["debit"] < 0 or l["credit"] < 0 for l in lines):
            QMessageBox.warning(self, "Validation", "Negative amounts are not allowed.")
            return

        entry = {
            "date": date,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": self.user_data.get("email"),
            "reference_no": ref,
            "description": desc,
            "purpose": purpose,
            "branch": self.user_data.get("branch")[0] if isinstance(self.user_data.get("branch"), list) else self.user_data.get("branch"),
            "lines": lines,
            "lines_account_ids": [l["account_id"] for l in lines],
            "meta": {"kind": "manual"}
        }

        try:
            # Atomically create the JE and bump both accounts
            batch = db.batch()
            je_ref = db.collection("journal_entries").document()
            batch.set(je_ref, entry)

            for acc_id, net in balance_updates.items():
                acc_ref = db.collection("accounts").document(acc_id)
                batch.update(acc_ref, {"current_balance": firestore.Increment(net)})

            batch.commit()

            QMessageBox.information(self, "Saved", "Journal Entry saved.")
            # Reset the two rows to zeros but keep them present
            for r in range(self.table.rowCount()):
                self.table.setItem(r, 1, QTableWidgetItem("0.00"))
                self.table.setItem(r, 2, QTableWidgetItem("0.00"))
            self.ref_input.clear()
            self.desc_input.clear()
            self.update_totals()
            self.load_accounts()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save entry: {e}")

        # Close the form after saving (existing behavior)
        self.close()
