# ui/dashboard.py
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QTextEdit,
    QDateEdit, QFrame, QGridLayout, QScrollArea, QSplitter, QMessageBox, QTableWidget,
    QTableWidgetItem, QSizePolicy, QHeaderView, QToolButton
)
from PyQt5.QtCore import Qt, QDate, QPoint, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from ui.sidebar import create_expandable_sidebar
from ui.network_monitor import NetworkMonitor
from firebase.cred_loader import set_refresh_token  # for logout
from firebase.config import db

# ---- App modules ----
from modules.products import ProductsPage
from modules.stock_adjustment import StockAdjustment
from modules.create_new_login import CreateUserModule
from modules.view_inventory import ViewInventory
from modules.manufacturing_cycle import ManufacturingModule
from modules.view_manufacturing_orders import ViewManufacturingWindow
from modules.settings import SettingsWindow
from modules.chart_of_accounts import ChartOfAccounts
from modules.view_journal_entries import JournalEntryViewer
from modules.employee_master import EmployeeModule
from modules.clients_master import PartyModule
from modules.invoice import InvoiceModule
from modules.view_invoice import ViewInvoicesModule
from modules.delivery_chalan import DeliveryChalanModule
from modules.view_users import ViewUsersModule



# ---------------- Floating notice chip (offline) ----------------
class FloatingNotice(QFrame):
    def __init__(self, parent=None, anchor="top-right", margin=16, dismissable=True):
        super().__init__(parent)
        self.anchor = anchor
        self.margin = margin
        self.dismissable = dismissable
        self.setObjectName("FloatingNotice")
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("""
            #FloatingNotice {
                background-color: rgba(255, 243, 205, 0.98);
                border: 1px solid #ffe8a1;
                border-radius: 12px;
            }
            QLabel#msg { color: #856404; }
            QPushButton#close {
                background: transparent; border: none; color: #856404;
                font-weight: bold; padding: 0px 6px; border-radius: 6px;
            }
            QPushButton#close:hover { background: rgba(0,0,0,0.06); }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(8)

        self.msg = QLabel("", self)
        self.msg.setObjectName("msg")
        self.msg.setWordWrap(False)
        self.msg.setFont(QFont("Segoe UI", 10, QFont.Bold))

        self.btn_close = QPushButton("✕", self)
        self.btn_close.setObjectName("close")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide)

        lay.addWidget(self.msg)
        lay.addWidget(self.btn_close)

        # apply initial dismissable state
        if not self.dismissable:
            self.btn_close.hide()
            self.btn_close.setDisabled(True)

        self.hide()

    def set_dismissable(self, flag: bool):
        """Toggle the visibility/availability of the close (✕) button."""
        self.dismissable = bool(flag)
        if self.dismissable:
            self.btn_close.setDisabled(False)
            self.btn_close.show()
        else:
            self.btn_close.hide()
            self.btn_close.setDisabled(True)
        self.adjustSize()
        self._reposition()

    def show_message(self, text: str):
        self.msg.setText(text)
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.show()

    def _reposition(self):
        if not self.parent():
            return
        rect = self.parent().rect()
        self.adjustSize()
        w, h = self.width(), self.height()
        m = self.margin
        if self.anchor == "top-right":
            x, y = rect.right() - w - m, rect.top() + m
        elif self.anchor == "top-left":
            x, y = rect.left() + m, rect.top() + m
        elif self.anchor == "bottom-right":
            x, y = rect.right() - w - m, rect.bottom() - h - m
        else:  # bottom-left
            x, y = rect.left() + m, rect.bottom() - h - m
        self.move(QPoint(max(x, 0), max(y, 0)))

# ---------------- Data worker (parallel; off the UI thread) ----------------
from concurrent.futures import ThreadPoolExecutor, as_completed

class DashboardDataWorker(QThread):
    accounts_ready = pyqtSignal(dict)   # {"totals":..., "net_worth":..., "profit":...}
    top_ready = pyqtSignal(list)        # list of rows: {"code","name","balance",...}
    stock_ready = pyqtSignal(dict)      # {"total_items":..., "below_reorder":..., "highlights":[...]}
    done = pyqtSignal(dict)
    fail = pyqtSignal(str)

    def run(self):
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                fut_accounts = ex.submit(self._load_accounts_snapshot)
                fut_top      = ex.submit(self._load_top_parties_batched)
                fut_stock    = ex.submit(self._load_stock_report)

                results = {"accounts": None, "top_parties": None, "stock": None}

                for fut in as_completed([fut_accounts, fut_top, fut_stock]):
                    if fut is fut_accounts:
                        results["accounts"] = fut.result()
                        self.accounts_ready.emit(results["accounts"])
                    elif fut is fut_top:
                        results["top_parties"] = fut.result()
                        self.top_ready.emit(results["top_parties"])
                    else:
                        results["stock"] = fut.result()
                        self.stock_ready.emit(results["stock"])

            self.done.emit(results)
        except Exception as e:
            self.fail.emit(str(e))

    # ---- Top customers by balance (batched + field projection) ----
    def _load_top_parties_batched(self):
        parties_iter = []
        try:
            # Case-sensitive values based on your data model
            parties_iter.extend(
                db.collection("parties")
                .where("type", "==", "Customer")
                .select(["id", "name", "type", "coa_account_id"])
                .stream()
            )
            parties_iter.extend(
                db.collection("parties")
                .where("type", "==", "Both")
                .select(["id", "name", "type", "coa_account_id"])
                .stream()
            )
        except Exception:
            # Fallback if 'select' or compound ops fail in env
            parties_iter = db.collection("parties").stream()

        party_rows, acc_refs = [], []
        for p in parties_iter:
            d = p.to_dict() or {}
            t = str(d.get("type", "")).strip()
            if t not in ("Customer", "Both"):
                continue
            ref = d.get("coa_account_id")
            if not ref:
                continue
            acc_ref = ref if hasattr(ref, "path") else db.collection("accounts").document(str(ref))
            acc_refs.append(acc_ref)
            party_rows.append({
                "party_id": p.id,
                "code": (d.get("id") or "").strip(),
                "name": (d.get("name") or "").strip(),
                "type": t,
                "acc_path": acc_ref.path
            })

        balances = {}
        if acc_refs:
            try:
                for snap in db.get_all(acc_refs):
                    if snap and snap.exists:
                        data = snap.to_dict() or {}
                        balances[snap.reference.path] = float(data.get("current_balance", 0.0) or 0.0)
            except Exception:
                for ref in acc_refs:
                    try:
                        s = ref.get()
                        if s.exists:
                            data = s.to_dict() or {}
                            balances[ref.path] = float(data.get("current_balance", 0.0) or 0.0)
                    except Exception:
                        pass

        rows = []
        for r in party_rows:
            bal = balances.get(r["acc_path"], 0.0)
            rows.append({
                "party_id": r["party_id"],
                "code": r["code"],
                "name": r["name"],
                "type": r["type"],
                "balance": bal
            })
        rows.sort(key=lambda x: x["balance"], reverse=True)
        return rows[:5]

    # ---- Accounts snapshot (project only what's needed) ----
    def _load_accounts_snapshot(self):
        totals = {"Asset": 0.0, "Liability": 0.0, "Equity": 0.0, "Income": 0.0, "Expense": 0.0}
        docs = db.collection("accounts").select(["type", "current_balance"]).stream()
        for d in docs:
            data = d.to_dict() or {}
            t = (data.get("type") or "").strip()
            if t in totals:
                try:
                    totals[t] += float(data.get("current_balance", 0.0) or 0.0)
                except Exception:
                    pass
        assets = totals["Asset"]; liabilities = totals["Liability"]
        return {"totals": totals, "net_worth": assets - liabilities, "profit": totals["Income"] - totals["Expense"]}

    # ---- Stock report (project only used fields) ----
    def _sum_nested_qty(self, qval):
        """
        Accepts nested qty dicts like:
        {branch: {color: {condition: qty}}}
        or flat numerics. Returns float total or None.
        """
        try:
            if qval is None or qval == "":
                return None
            if isinstance(qval, (int, float, str)):
                # numeric or numeric-ish string
                try:
                    return float(qval)
                except Exception:
                    return None
            # nested dicts
            total = 0.0
            stack = [qval]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    stack.extend(cur.values())
                else:
                    try:
                        total += float(cur or 0)
                    except Exception:
                        pass
            return total
        except Exception:
            return None

    def _load_stock_report(self):
        total_items = 0
        highlights = []

        # --- products collection (new structure) ---
        try:
            snaps = db.collection("products") \
                .select([
                    "name","item_name","item_code",
                    "qty","reorder_qty",
                    "length","width","height",
                    "length_unit","width_unit","height_unit",
                    "gauge"
                ]) \
                .stream()

            for snap in snaps:
                total_items += 1
                it = snap.to_dict() or {}

                code = (it.get("item_code") or "").strip() or "-"
                name = (it.get("name") or it.get("item_name") or code or "Item")

                # merged (grand total) quantity across nested dicts
                q = self._sum_nested_qty(it.get("qty"))
                if q is None:
                    q = self._to_float(it.get("qty_total") or it.get("quantity") or it.get("qty"))

                rq = self._to_float(it.get("reorder_qty"))

                if q is not None and rq is not None and q < rq:
                    # carry dimensions + units + gauge so UI can format
                    highlights.append({
                        "code": code,
                        "name": name,
                        "qty": q,
                        "reorder_qty": rq,
                        "length": it.get("length"),
                        "width": it.get("width"),
                        "height": it.get("height"),
                        "length_unit": it.get("length_unit"),
                        "width_unit": it.get("width_unit"),
                        "height_unit": it.get("height_unit"),
                        "gauge": it.get("gauge"),
                    })

            # sort by how low relative to reorder (lowest first) and keep top 5
            try:
                highlights.sort(key=lambda x: (x["qty"] / (x["reorder_qty"] or 1.0)) if x["reorder_qty"] else 0.0)
            except Exception:
                pass
            highlights = highlights[:5]
            return {"total_items": total_items, "below_reorder": len(highlights), "highlights": highlights}
        except Exception:
            # empty fallback (you can re-add legacy 'items' path if you still need it)
            return {"total_items": 0, "below_reorder": 0, "highlights": []}

    def _to_float(self, val):
        try:
            if val is None or val == "":
                return None
            return float(val)
        except Exception:
            return None


# ---------------- Dashboard Window ----------------
class DashboardApp(QMainWindow):
    """
    Modern, fast dashboard with:
      • Gradient/glassy header, quick actions, live network badge
      • KPI cards (Assets, Liabilities, Equity, Income, Expense, Net Worth, Profit)
      • Top 5 Customers by Balance
      • Stock Report highlights
    Plus:
      • Floating offline chip + offline policy
      • All data loaded in parallel with partial UI updates
    """
    OFFLINE_ALLOWED_CLASSES = (ViewInventory, ChartOfAccounts)

    def __init__(self, username, user_data, company_name: str = "ERP"):
        super().__init__()
        self.username = username
        self.user_data = user_data or {}
        self.company_name = company_name
        self._is_admin = self._is_admin_user(self.user_data)

        self.setWindowTitle(f"{self.company_name} ERP — Dashboard")
        self.showMaximized()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.open_windows = []
        self.monitor = None
        self.net_badge = None
        self.offline = False
        self.offline_chip = FloatingNotice(self, anchor="bottom-right", margin=16, dismissable=False)

        self._build_ui()
        self._start_network_monitor()
        self._kick_data_load() if self._is_admin else None

    # ---------------- UI scaffold ----------------
    def _build_ui(self):
        # Global aesthetics (lightweight CSS)
        self.setStyleSheet("""  
            QWidget#ContentArea { background: #f6f7fb; }
            QFrame#Glass {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #8ec5fc, stop:1 #e0c3fc);
                border: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 16px;
            }
            QFrame#KPI { background:#ffffff; border:1px solid #e5e7eb; border-radius:18px; }
            QFrame#Card { background:#ffffff; border:1px solid #e5e7eb; border-radius:18px; }
            QTableWidget {
                gridline-color: #e5e7eb; alternate-background-color: #fafafa;
                background: transparent; selection-background-color: #e8f2ff;
            }
            QHeaderView::section {
                background: #f2f4f7; border: 0px; padding: 8px; font-weight: 600;
            }
        """)

        root = QHBoxLayout(self.central_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar_items = [
            # Group 1: Dashboard
            ("Dashboard", lambda: None),  # Simple function case

            # Group 2: Parties
            ("Parties", [("Manage/View", lambda: self.launch_module("party_window", PartyModule, self.user_data))]),

            # Group 3: Employees
            ("Employees", [("Manage/View", lambda: self.launch_module("Emploee_window", EmployeeModule, self.user_data))]),

            # Group 4: Accounting
            ("Accounting", [
                ("Chart of Accounts", lambda: self.launch_module("chart_of_accounts", ChartOfAccounts, self.user_data)),
                ("Open Journal", lambda: self.launch_module("wiew_journal_entry", JournalEntryViewer, self.user_data)),
            ]),

            # Group 5: Sales
            ("Sales", [
                ("Invoice", lambda: self.launch_module("invoice_window", InvoiceModule, self.user_data)),
                ("View Invoice", lambda: self.launch_module("view_invoice_window", ViewInvoicesModule, self.user_data)),
            ]),

            # Group 6: Purchase
            ("Purchase", [("Purchase Order", lambda: QMessageBox.about(self, "Dev Log", "Cannot Acces, Under Development!"))]),

            # Group 7: Inventory
            ("Inventory", [
                ("Chart of Inventory", lambda: self.launch_module("products_window", ProductsPage, self.user_data)),
                ("Stock Adjustment", lambda: setattr(self, "inventory_window", StockAdjustment.show_if_admin(self.user_data, self))),
                ("View Inventory", lambda: self.launch_module("view_inventory_window", ViewInventory, self.user_data)),
                ("Delivery Chalan", lambda: self.launch_module("delivery_chalan", DeliveryChalanModule, self.user_data)),
            ]),

            # Group 8: Manufacturing
            ("Manufacturing", [
                ("Create Order", lambda: self.launch_module("manufacturing_window", ManufacturingModule)),
                ("View Orders", lambda: self.launch_module("view_orders_window", ViewManufacturingWindow, self.user_data, self)),
            ]),

            # Group 9: Core Options
            ("Core Options", [
                ("Settings", lambda: self.launch_module("settings_window", SettingsWindow, self.user_data)),
                ("Create Login (Admin Only)", lambda: setattr(self, "create_user_window", CreateUserModule.show_if_admin(self.user_data))),
                ("View Users (Admin Only)", lambda: setattr(self, "view_users_window", ViewUsersModule.show_if_admin(self.user_data))),
                ("Connect Whatsapp", lambda: QMessageBox.about(self, "Dev Log", "Cannot Acces, Under Development!")),
            ]),
        ]

        # For non-admin users, filter out the modules that are not in the allowed_modules list
        if not self._is_admin:
            allowed_modules = self.user_data.get('allowed_modules', [])
            sidebar_items = [
                (label, actions)  # If actions are a list, iterate over them
                if isinstance(actions, list)
                else (label, actions)  # Handle the function case (e.g., "Dashboard")
                for label, actions in sidebar_items
                for label, action in (actions if isinstance(actions, list) else [(label, actions)])  # Ensure it's iterable
                if label in allowed_modules  # Check if the module is in allowed_modules
            ]

        sidebar = create_expandable_sidebar(self, sidebar_items, self.logout, font_scale=1.1)
        
        # --- Right content ---
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); content.setObjectName("ContentArea"); scroll.setWidget(content)
        right = QVBoxLayout(content)
        right.setContentsMargins(24, 20, 24, 24)
        right.setSpacing(16)

        # ======= Header (glassy gradient bar with quick actions) =======
        header = QFrame(); header.setObjectName("Glass")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 16, 18, 16); h.setSpacing(12)

        title = QLabel(f"Welcome, {self.username} — {self.company_name} Dashboard")
        title.setStyleSheet("color:#0b1220; font-size:18px; font-weight:800;")
        h.addWidget(title)

        # network badge
        self.net_badge = QLabel("Network: Checking…")
        self.net_badge.setStyleSheet("color:#0b1220; font-size:12px; font-weight:700;")
        h.addStretch(1)
        h.addWidget(self.net_badge)

        # Quick actions
        if self._is_admin:
            btn_refresh = QToolButton(); btn_refresh.setText("↻ Refresh")
            btn_refresh.setCursor(Qt.PointingHandCursor)
            btn_refresh.setStyleSheet("QToolButton{padding:6px 10px; background:#ffffff; border:1px solid #dfe3ea; border-radius:8px;}")
            btn_refresh.clicked.connect(self._kick_data_load)
            h.addWidget(btn_refresh)

        btn_settings = QToolButton(); btn_settings.setText("⚙ Settings")
        btn_settings.setCursor(Qt.PointingHandCursor)
        btn_settings.setStyleSheet("QToolButton{padding:6px 10px; background:#ffffff; border:1px solid #dfe3ea; border-radius:8px;}")
        btn_settings.clicked.connect(lambda: self.launch_module("settings_window", SettingsWindow, self.user_data))
        h.addWidget(btn_settings)

        
        right.addWidget(header)

        if self._is_admin:
            # ======= KPI cards row =======
            kpi_row = QHBoxLayout(); kpi_row.setSpacing(12)
            right.addLayout(kpi_row)
            self.kpi_cards = {}
            for title_txt in ["Assets", "Liabilities", "Equity", "Income", "Expense", "Net Worth", "Profit"]:
                card = self._kpi_card(title_txt, "0.00")
                self.kpi_cards[title_txt] = card
                kpi_row.addWidget(card["frame"])

            # ======= Two-column content =======
            grid_row = QHBoxLayout(); grid_row.setSpacing(12)
            right.addLayout(grid_row)

            # Left column: Top 5 Customers
            self.top_box, self.top_table = self._build_table_card(
            "👥 Top 5 Customers by Balance",
            headers=["Code", "Customer", "Type", "Balance"]
            )
            grid_row.addWidget(self.top_box, 1)

            # Right column: Stock Report (now with Code)
            self.stock_box, self.stock_table = self._build_table_card(
                "📦 Stock Report (Quick View)",
                headers=["Code", "Item", "Qty", "Reorder Qty"]
            )
            grid_row.addWidget(self.stock_box, 1)

            # ======= Message Board (larger, clearer) =======
            notes = QFrame(); notes.setObjectName("Card")
            notes_lay = QVBoxLayout(notes)
            notes_lay.setContentsMargins(18, 18, 18, 18)
            notes_lay.setSpacing(10)
            ttl = QLabel("🔔 Message Board")
            ttl.setStyleSheet("font-size:16px; font-weight:800; color:#111827;")
            msg = QTextEdit(); msg.setReadOnly(True)
            msg.setText("• No pending approvals\n• 2 orders awaiting dispatch\n• System running smoothly\n• Welcome, Admin.")
            msg.setFont(QFont("Segoe UI", 12))
            msg.setMinimumHeight(180)
            msg.setStyleSheet("""
                QTextEdit {
                    background:#ffffff;
                    border:1px solid #edf0f4;
                    border-radius:12px;
                    padding:12px;
                }
            """)
            notes_lay.addWidget(ttl); notes_lay.addWidget(msg)
            right.addWidget(notes)
        else:
            # Non-admin launchpad (icons grid)
            right.addWidget(self._build_nonadmin_launchpad())
        right.addStretch(1)

        # Layout: sidebar + content
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(scroll)
        splitter.setSizes([200, 1200])
        root.addWidget(splitter)

    # ---------------- Card builders ----------------
    def _kpi_card(self, title: str, value_text: str):
        frame = QFrame(); frame.setObjectName("KPI")
        layout = QVBoxLayout(frame); layout.setContentsMargins(14, 12, 14, 12); layout.setSpacing(4)
        ttl = QLabel(title); ttl.setStyleSheet("font-size:12px; font-weight:700; color:#6b7280;")
        val = QLabel(value_text); val.setStyleSheet("font-size:22px; font-weight:900; color:#111827;")
        layout.addWidget(ttl); layout.addWidget(val)
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return {"frame": frame, "title": ttl, "value": val}

    def _build_table_card(self, title: str, headers: list):
        box = QFrame(); box.setObjectName("Card")
        lay = QVBoxLayout(box); lay.setContentsMargins(14, 14, 14, 14); lay.setSpacing(8)
        ttl = QLabel(title); ttl.setStyleSheet("font-size:14px; font-weight:800; color:#111827;")
        table = QTableWidget(0, len(headers))
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        # Default: don't stretch last by itself, we’ll control explicitly
        table.horizontalHeader().setStretchLastSection(False)

        # Apply header labels
        table.setHorizontalHeaderLabels(headers)

        # === Custom sizing rules ===
        # Accounts card: Code* | Customer** | Type* | Balance*
        if headers == ["Code", "Customer", "Type", "Balance"]:
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Code
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)            # Customer
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Type
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Balance

        # Stock card: Code* | Item** | Qty* | Reorder Qty*
        elif headers == ["Code", "Item", "Qty", "Reorder Qty"]:
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Code
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)           # Item
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Qty
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Reorder Qty

        else:
            # fallback: auto-fit
            for c in range(len(headers)):
                table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)

        lay.addWidget(ttl); lay.addWidget(table)
        return box, table

    # ---------------- Data load / render ----------------
    def _kick_data_load(self):
        # If a previous worker is still running, wait for it to finish
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            try:
                self.worker.wait(1500)
            except Exception:
                pass

        self.worker = DashboardDataWorker(self)
        # partial renders
        self.worker.accounts_ready.connect(self._render_accounts)
        self.worker.top_ready.connect(self._render_top)
        self.worker.stock_ready.connect(self._render_stock)
        # final (optional)
        self.worker.done.connect(lambda _p: None)
        self.worker.fail.connect(lambda e: QMessageBox.critical(self, "Dashboard", f"Failed to load dashboard data:\n{e}"))
        self.worker.start()

    def _render_accounts(self, accounts: dict):
        tot = accounts.get("totals", {})
        self._set_kpi("Assets",     tot.get("Asset", 0.0))
        self._set_kpi("Liabilities",tot.get("Liability", 0.0))
        self._set_kpi("Equity",     tot.get("Equity", 0.0))
        self._set_kpi("Income",     tot.get("Income", 0.0))
        self._set_kpi("Expense",    tot.get("Expense", 0.0))
        self._set_kpi("Net Worth",  accounts.get("net_worth", 0.0))
        self._set_kpi("Profit",     accounts.get("profit", 0.0))

    def _render_top(self, rows: list):
        self._fill_table(self.top_table, [
            [row["code"], row["name"], row["type"], self._fmt(row["balance"])]
            for row in rows
        ])

    def _render_stock(self, stock: dict):
        total = stock.get("total_items", 0)
        low = stock.get("below_reorder", 0)
        self._set_table_title_suffix(self.stock_box, f" • Items: {total:,} | Below Reorder: {low:,}")

        def fmt_item(h: dict) -> str:
            # NAME - L<U> x W<U> x H<U> - gauge(g)
            name = h.get("name") or "-"

            length = h.get("length"); lunit = (h.get("length_unit") or "").strip().lower()
            width  = h.get("width");  wunit = (h.get("width_unit") or "").strip().lower()
            height = h.get("height"); hunit = (h.get("height_unit") or "").strip().lower()
            gauge  = h.get("gauge")

            def unit_symbol(u: str) -> str:
                if u in ('inch', 'in', '"'):
                    return '"'
                if u in ('ft', 'feet', "'"):
                    return "'"
                if u in ('mm', 'millimeter', 'millimetre'):
                    return "mm"
                return u  # default: leave as is

            def _fmt_num_clean(v):
                try:
                    f = float(v)
                    if f.is_integer():
                        return str(int(f))
                    return str(f)
                except Exception:
                    return str(v)

            dims = []
            if length not in (None, "", 0, 0.0):
                dims.append(f"{_fmt_num_clean(length)}{unit_symbol(lunit)}")
            if width not in (None, "", 0, 0.0):
                dims.append(f"{_fmt_num_clean(width)}{unit_symbol(wunit)}")
            if height not in (None, "", 0, 0.0):
                dims.append(f"{_fmt_num_clean(height)}{unit_symbol(hunit)}")

            parts = [name]
            if dims:
                parts.append(" x ".join(dims))
            if gauge not in (None, "", 0, 0.0):
                parts.append(f"{_fmt_num_clean(gauge)}g")

            return " - ".join(parts)

        self._fill_table(self.stock_table, [
            [h.get("code", "-"), fmt_item(h), self._num(h.get("qty")), self._num(h.get("reorder_qty"))]
            for h in stock.get("highlights", [])
        ])


    def _set_table_title_suffix(self, card: QFrame, suffix: str):
        try:
            ttl = card.findChildren(QLabel)[0]
            base = ttl.text().split(" • ")[0]
            ttl.setText(base + suffix)
        except Exception:
            pass

    def _set_kpi(self, key: str, val: float):
        card = self.kpi_cards.get(key)
        if not card: return
        card["value"].setText(self._fmt(val))

    def _fmt(self, v: float) -> str:
        try: return f"{float(v):,.2f}"
        except Exception: return "0.00"

    def _num(self, v) -> str:
        try: return f"{float(v):,.0f}"
        except Exception: return "-"

    def _fill_table(self, table: QTableWidget, rows: list):
        table.setRowCount(0)
        for rdata in rows:
            r = table.rowCount(); table.insertRow(r)
            for c, txt in enumerate(rdata):
                it = QTableWidgetItem(str(txt))
                if c == len(rdata) - 1:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, it)

    def _is_admin_user(self, user: dict) -> bool:
        if not user:
            return False
        # Check directly if the user has an admin role.
        print(user.get("role", ""))
        role = str(user.get("role", "")).lower()
        if role == "admin":
            return True
        roles = user.get("roles") or []
        if isinstance(roles, (list, tuple, set)) and "admin" in roles:
            return True
        return False

    def _is_inventory_manager(self, user: dict) -> bool:
        if not user:
            return False
        role = str(user.get("role", "")).strip().lower()
        if role == "inventory manager":
            return True
        roles = user.get("roles") or []
        if isinstance(roles, (list, tuple, set)):
            return any(str(r).strip().lower() == "inventory manager" for r in roles)
        return False

    def _build_nonadmin_launchpad(self):
        wrap = QFrame()
        wrap.setObjectName("Card")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(24, 32, 24, 32)
        lay.setSpacing(18)
        
        title = QLabel(f"Choose a Module to work on!")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:22px;font-weight:900;color:#111827;")
        lay.addWidget(title)

        # Create a placeholder text for when no modules are allowed
        if not self._is_admin:
            allowed_modules = self.user_data.get('allowed_modules', [])
            if not allowed_modules:  # If allowed_modules is empty
                placeholder = QLabel("No modules are available. Please contact your admin.")
                placeholder.setAlignment(Qt.AlignCenter)
                placeholder.setStyleSheet("font-size:16px; font-weight:600; color:#ff0000;")  # Red for emphasis
                lay.addWidget(placeholder)
                return wrap  # Return early, as no further tiles are needed

        # Continue with the usual tile generation if allowed_modules is not empty
        grid = QGridLayout()
        grid.setSpacing(16)
        lay.addLayout(grid)
        
        # Define the module tiles to be included
        all_modules = [
            ("📦", "Manage / View Parties", lambda: self.launch_module("party_window", PartyModule, self.user_data)),
            ("✅", "Manage / View Employees", lambda: self.launch_module("Emploee_window", EmployeeModule, self.user_data)),
            ("📊", "Chart of Accounts", lambda: self.launch_module("chart_of_accounts", ChartOfAccounts, self.user_data)),
            ("📝", "Journal", lambda: self.launch_module("wiew_journal_entry", JournalEntryViewer, self.user_data)),
            ("🧾", "Invoice", lambda: self.launch_module("invoice_window", InvoiceModule, self.user_data)),
            ("📑", "View Invoices", lambda: self.launch_module("view_invoice_window", ViewInvoicesModule, self.user_data)),
            ("📦", "Purchase Order", lambda: QMessageBox.about(self, "Dev Log", "Cannot Access, Under Development!")),
            ("📦", "Chart of Inventory", lambda: self.launch_module("products_window", ProductsPage, self.user_data)),
            ("📦", "View Inventory", lambda: self.launch_module("view_inventory_window", ViewInventory, self.user_data)),
            ("🚚", "Delivery Chalan", lambda: self.launch_module("delivery_chalan", DeliveryChalanModule, self.user_data)),
            ("🏭", "Create Manufacturing Order", lambda: self.launch_module("manufacturing_window", ManufacturingModule)),
            ("🏭", "View Manufacturing Order", lambda: self.launch_module("view_orders_window", ViewManufacturingWindow, self.user_data, self)),
        ]

        # If user is not admin, filter based on allowed modules
        if not self._is_admin:
            allowed_modules = self.user_data.get('allowed_modules', [])
            all_modules = [(emoji, label, fn) for emoji, label, fn in all_modules if label in allowed_modules]

        # Add the filtered tiles to the layout (all tiles will be of the same size)
        for i, (emoji, label, fn) in enumerate(all_modules):
            r, c = divmod(i, 4)  # Arrange in grid
            tile = self._square_tile(emoji, label, fn)
            grid.addWidget(tile, r, c)

        # Add a message box below the tiles section (to display messages or instructions)
        message_box = QFrame()
        message_layout = QVBoxLayout(message_box)
        message_layout.setContentsMargins(18, 18, 18, 18)
        message_layout.setSpacing(10)
        message_title = QLabel("🔔 Important Notice")
        message_title.setStyleSheet("font-size:16px; font-weight:800; color:#111827;")
        message_content = QTextEdit()
        message_content.setReadOnly(True)
        message_content.setText("• Please contact your admin if you have any issues accessing the modules.\n• Keep this section updated.")
        message_content.setFont(QFont("Segoe UI", 12))
        message_content.setStyleSheet("""
            QTextEdit {
                background:#ffffff;
                border:1px solid #edf0f4;
                border-radius:12px;
                padding:12px;
            }
        """)
        message_layout.addWidget(message_title)
        message_layout.addWidget(message_content)
        lay.addWidget(message_box)

        return wrap

    def _square_tile(self, emoji, label, on_click):
        btn = QToolButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setText(f"{emoji}\n{label}")
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setMinimumSize(200, 160)  # Ensuring all tiles are of same size
        btn.setStyleSheet("""
            QToolButton {
                background:#fff;
                border:1px solid #e5e7eb;
                border-radius:18px;
                padding:20px;
                font-size:16px;
                font-weight:800;
                color:#111827;
            }
            QToolButton:hover {
                border-color:#cbd5e1;
            }
        """)
        btn.clicked.connect(on_click)
        return btn

    # ---------------- Network handling ----------------
    def _paint_net_badge(self, state: str, rtt_ms: int = 0):
        if state == "online":
            self.net_badge.setText(f"Network: Online ({rtt_ms} ms)")
            self.net_badge.setStyleSheet("color:#0b1220; font-weight: 800;")
        elif state == "slow":
            self.net_badge.setText(f"Network: Slow ({rtt_ms} ms)")
            self.net_badge.setStyleSheet("color:#6e3b00; font-weight: 800;")
        elif state == "offline":
            self.net_badge.setText("Network: Offline")
            self.net_badge.setStyleSheet("color:#7a0000; font-weight: 800;")
        else:
            self.net_badge.setText("Network: Checking…")
            self.net_badge.setStyleSheet("color:#0b1220; font-weight: 800;")

    def _start_network_monitor(self):
        self.monitor = NetworkMonitor(interval_sec=3.0, slow_threshold_ms=800, parent=self)
        self.monitor.status_changed.connect(self._on_net_status)
        self.monitor.start()

    def _on_net_status(self, status: str, rtt_ms: int):
        self._paint_net_badge(status, rtt_ms)
        if status == "offline":
            self._enter_offline_mode()
        elif status in ("online", "slow"):
            self._exit_offline_mode()

    def _enter_offline_mode(self):
        if self.offline: return
        self.offline = True
        self.offline_chip.show_message("⚠ You’re offline. Cached/read-only data shown. Some features disabled.")
        self._enforce_offline_policy()

    def _exit_offline_mode(self):
        if not self.offline: return
        self.offline = False
        self.offline_chip.hide()
        for win in list(self.open_windows):
            self._set_read_only_if_supported(win, False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            if self.offline_chip.isVisible():
                self.offline_chip._reposition()
        except Exception:
            pass

    def _enforce_offline_policy(self):
        for win in list(self.open_windows):
            if not self._is_offline_allowed_instance(win):
                try: win.close()
                except Exception: pass
                finally:
                    try: self.open_windows.remove(win)
                    except ValueError: pass
            else:
                self._set_read_only_if_supported(win, True)

    def _is_offline_allowed_class(self, cls) -> bool:
        if cls in self.OFFLINE_ALLOWED_CLASSES:
            return True
        return getattr(cls, "OFFLINE_CACHE_SAFE", False)

    def _is_offline_allowed_instance(self, win) -> bool:
        return self._is_offline_allowed_class(win.__class__)

    def _set_read_only_if_supported(self, win, read_only: bool):
        try:
            if hasattr(win, "set_offline_mode"):
                win.set_offline_mode(read_only=read_only)
            elif hasattr(win, "set_read_only"):
                win.set_read_only(read_only)
        except Exception:
            pass

    # ---------------- Module management ----------------
    def launch_module(self, attr_name, window_class, *args):
        if self.offline and not self._is_offline_allowed_class(window_class):
            QMessageBox.information(
                self, "Offline Mode",
                "You're offline. This feature is disabled.\n\n"
                "Allowed offline: \n1) View Inventory\n2) Chart of Accounts\n3) View Journal."
            )
            return

        win = getattr(self, attr_name, None)
        if win and win.isVisible():
            win.raise_(); win.activateWindow(); return
        elif win:
            setattr(self, attr_name, None)
            if win in self.open_windows:
                self.open_windows.remove(win)

        win = window_class(*args)
        setattr(self, attr_name, win); self.open_windows.append(win)

        if self.offline and self._is_offline_allowed_instance(win):
            self._set_read_only_if_supported(win, True)

        def remove_ref(win=win):
            try:
                if win in self.open_windows:
                    self.open_windows.remove(win)
            except Exception:
                pass
            if getattr(self, attr_name, None) == win:
                setattr(self, attr_name, None)

        try:
            win.destroyed.connect(remove_ref)
        except Exception:
            pass
        win.show()

    def closeEvent(self, event):
        # Wait for data worker
        try:
            if getattr(self, "worker", None) and self.worker.isRunning():
                self.worker.wait(1500)
        except Exception:
            pass

        # Stop monitor and wait
        try:
            if self.monitor and self.monitor.isRunning():
                self.monitor.stop()
        except Exception:
            pass

        for win in list(self.open_windows):
            try:
                if win and win.isVisible():
                    win.close()
            except Exception as e:
                print(f"Failed to close window: {e}")
        super().closeEvent(event)

    # ---------------- Logout ----------------
    def logout(self):
        try:
            set_refresh_token("")  # delete session
        except Exception as e:
            print("Warning: could not clear refresh token:", e)

        # Ensure data worker is not running
        try:
            if getattr(self, "worker", None) and self.worker.isRunning():
                self.worker.wait(1500)
        except Exception:
            pass

        # Stop monitor and wait
        try:
            if self.monitor and self.monitor.isRunning():
                self.monitor.stop()
        except Exception:
            pass

        from ui.login import LoginWindow
        self.user_data = None
        self.close()
        self.login_window = LoginWindow()
        self.login_window.show()
