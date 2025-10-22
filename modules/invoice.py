# modules/invoice.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTextEdit, QPushButton, QGridLayout, QMessageBox, QCompleter, QDialog,
    QDialogButtonBox, QDateEdit, QProgressDialog, QApplication, QGroupBox, QScrollArea, QMenu, QAction, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QDate
from firebase.config import db
from modules.clients_master import PartyDialog
from firebase_admin import firestore
import datetime
import uuid


class MainProductCardPreview(QWidget):
    def __init__(self, data, on_edit, on_remove):
        super().__init__()
        self.data = data
        self.on_edit = on_edit
        self.on_remove = on_remove

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        font_style = """
            font-size: 14px;
            min-height: 32px;       /* same as header */
        """
        font_style_name = """
            font-size: 14px;
        """  # no min-height → can grow with text

        self.name_lbl = QLabel(data.get("main_product", ""))
        self.name_lbl.setWordWrap(True)
        self.name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.qty_lbl = QLabel(str(data.get("qty", 1)))
        self.rate_lbl = QLabel(f"Rs {data.get('rate', 0):,.2f}")
        self.total_lbl = QLabel(f"Rs {data.get('total', 0):,.2f}")

        for lbl in (self.name_lbl, self.qty_lbl, self.rate_lbl, self.total_lbl):
            if lbl == self.name_lbl:
                self.name_lbl.setStyleSheet(font_style_name)
            else:
                lbl.setStyleSheet(font_style)
            lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        layout.addWidget(self.name_lbl, 4)
        layout.addWidget(self.qty_lbl, 1)
        layout.addWidget(self.rate_lbl, 1)
        layout.addWidget(self.total_lbl, 2)

        layout.addStretch()

        edit_btn = QPushButton("✏️ Edit")
        edit_btn.clicked.connect(self._edit)
        remove_btn = QPushButton("🗑️ Remove")
        remove_btn.clicked.connect(self._remove)

        layout.addWidget(edit_btn)
        layout.addWidget(remove_btn)

    def _edit(self):
        self.on_edit(self)

    def _remove(self):
        self.setParent(None)
        self.on_remove(self)

    def update_data(self, new_data):
        self.data = new_data
        self.name_lbl.setText(new_data.get("main_product", ""))
        self.qty_lbl.setText(str(new_data.get("qty", 1)))
        self.rate_lbl.setText(f"Rs {new_data.get('rate', 0):,.2f}")
        self.total_lbl.setText(f"Rs {new_data.get('total', 0):,.2f}")


class InvoiceModule(QWidget):
    def __init__(self, user_data, default_type=None):
        super().__init__()
        self.user_data = user_data
        self.clients = {}
        self.product_dict = {}
        self.products = []
        self.sales_reps = {}
        self.default_type = default_type
        self.product_cards = []

        # --- edit mode state ---
        self._loaded_doc_id = None  # set by load_invoice when editing

        # Fetch colors & hard-code conditions
        try:
            doc = db.collection("meta").document("colors").get()
            self.pc_colors = doc.to_dict().get("pc_colors", [])
        except:
            self.pc_colors = []
        self.conditions = ["New", "Old", "Bad"]

        # Window setup
        self.setWindowTitle("Create Invoice")
        self.setMinimumSize(1500, 1000)
        self._apply_styles()
        
        
        # Center the window
        frameGm = self.frameGeometry()
        screen = QApplication.desktop().screenNumber(QApplication.desktop().cursor().pos())
        centerPoint = QApplication.desktop().screenGeometry(screen).center()
        frameGm.moveCenter(centerPoint)
        self.move(frameGm.topLeft())

        # Main layout
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(15)
        
        # Build sections first (combos now exist)
        main.addWidget(self._build_header_section())
        main.addWidget(self._build_items_section())
        main.addWidget(self._build_summary_section())
        self.load_postable_accounts()  # this needs received_account_cb already built
        main.addWidget(self._build_notes_section())
        main.addLayout(self._build_footer_layout())

        # Now load data (these can safely touch the combos)
        self.load_clients()
        self.load_products()
        self.load_sales_reps()
        
        self.status_cb.currentTextChanged.connect(self._update_invoice_no_preview)
        self.status_cb.currentTextChanged.connect(self._toggle_payment_fields)
        self._toggle_payment_fields(self.status_cb.currentText())
        if self.default_type and self.default_type in [self.status_cb.itemText(i) for i in range(self.status_cb.count())]:
            self.status_cb.setCurrentText(self.default_type)
        else:
            self.status_cb.setCurrentIndex(0)
        self._update_invoice_no_preview()

    def _apply_styles(self):
        self.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                border: 1px solid #aaa; 
                border-radius: 4px; 
                margin-top: 10px; 
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
            QPushButton {
                padding: 6px 12px;
                border: 1px solid #888;
                border-radius: 4px;
                background: #f0f0f0;
            }
            QPushButton:hover {
                background: #e0e0e0;
            }
            QLineEdit, QComboBox, QTextEdit, QDateEdit {
                border: 1px solid #bbb; 
                border-radius: 3px; 
                padding: 4px;
            }
        """)

    # — Data loading —

    def load_clients(self):
        self.clients.clear()
        try:
            client_docs = db.collection("parties").where("active", "==", True).stream()
            for doc in client_docs:
                d = doc.to_dict() or {}
                id_field = d.get("id", doc.id)
                name = d.get("name", "Unnamed")
                client_type = (d.get("type") or "Customer").lower()
                short_type = "SUP" if client_type == "supplier" else "CUST"
                contact = d.get("phone") or d.get("email") or "No Contact"
                display_text = f"[{id_field}] - {name} ({short_type}) - {contact}"
                # map by Firestore doc.id → keep both the data and the display text
                self.clients[doc.id] = {"data": d, "display": display_text}
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load clients: {e}")
            return

        if hasattr(self, "client_cb"):
            self._refresh_client_combo()
            
    def _toggle_payment_fields(self, doc_type):
        """
        Disable Received account dropdown + amount field if type is Quotation.
        Enable them otherwise.
        """
        is_quotation = (doc_type.strip().lower() == "quotation")
        self.received_account_cb.setDisabled(is_quotation)
        self.received.setDisabled(is_quotation)

    def _refresh_client_combo(self):
        self.client_cb.blockSignals(True)
        self.client_cb.clear()
        self.client_cb.addItem("")  # optional blank
        for doc_id, payload in self.clients.items():
            self.client_cb.addItem(payload["display"], doc_id)  # store doc.id in itemData
        self._apply_completer(self.client_cb)
        self.client_cb.blockSignals(False)

        
    def load_products(self):
        self.products.clear()
        self.product_dict.clear()
        loader = self._show_loader("Loading products…")
        try:
            main_id = next(
                (d.id for d in db.collection("product_main_categories").stream()
                 if d.to_dict().get("name") == "Finished Products"),
                None
            )
            if main_id:
                sub_ids = [d.id for d in db.collection("product_sub_categories")
                           .where("main_id", "==", main_id).stream()]
            else:
                sub_ids = []

            def fmt(x):
                return int(x) if float(x).is_integer() else round(float(x), 2)

            for doc in db.collection("products").stream():
                p = doc.to_dict()
                if p.get("sub_id") not in sub_ids:
                    continue
                L, W, H = fmt(p.get("length", 0)), fmt(p.get("width", 0)), fmt(p.get("height", 0))
                size = f"{L}{p.get('length_unit','')}×{W}{p.get('width_unit','')}"
                if H:
                    size += f"×{H}{p.get('height_unit','')}"
                label = f"{p.get('item_code','')} - {p.get('name','')} - {size} - {p.get('gauge')}G"
                p["label"], p["id"] = label, doc.id
                self.product_dict[label] = p
                self.products.append(p)
        finally:
            loader.close()

    def load_sales_reps(self):
        self.sales_reps.clear()

        items = []
        for doc in db.collection("employees").where("active", "==", True).stream():
            d = doc.to_dict() or {}
            name = (d.get("name") or "Unnamed").strip()
            code = (d.get("employee_code") or "").strip()

            # NEW format: [Code] - Name  (fallback to Name if code missing)
            label = f"[{code}] - {name}" if code else name

            self.sales_reps[label] = doc.id
            items.append((label, doc.id))

        if hasattr(self, "rep_cb"):
            self.rep_cb.blockSignals(True)
            self.rep_cb.clear()
            self.rep_cb.addItem("")  # optional blank
            for label, emp_id in items:
                self.rep_cb.addItem(label, emp_id)
            self._apply_completer(self.rep_cb)
            self.rep_cb.blockSignals(False)
            
    def _fmt_employee_label(self, d: dict) -> str:
        name = (d.get("name") or "Unnamed").strip()
        code = (d.get("employee_code") or "").strip()
        return f"[{code}] - {name}" if code else name
            
    def load_postable_accounts(self):
        self.postable_accounts = {}
        self.received_account_cb.clear()
        self.received_account_cb.addItem("", None)  # empty option with no payload

        account_docs = (
            db.collection("accounts")
            .where("is_posting", "==", True)
            .where("active", "==", True)
            .where("type", "==", "Asset")
            .where("subtype", "==", "Cash & Bank")
            .stream()
        )

        for doc in account_docs:
            d = doc.to_dict() or {}
            code = d.get("code", "")
            name = d.get("name", "")
            branches = d.get("branch", [])

            def add(label_branch, branch_value):
                label = f"{code} - {name}" + (f" ({label_branch})" if label_branch else "")
                payload = {"id": doc.id, "branch": branch_value, "data": d}
                # keep map (useful elsewhere) AND store payload in userData for direct read
                self.postable_accounts[label] = payload
                self.received_account_cb.addItem(label, payload)

            if branches:
                for b in branches:
                    add(b, b)
            else:
                add(None, None)

    def _show_loader(self, message):
        dlg = QProgressDialog(message, None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setAutoClose(True)
        dlg.setCancelButton(None)
        dlg.show()
        QApplication.processEvents()
        return dlg

    # — Header section —

    def _update_payment_terms_display(self):
        selected = [a.text() for a in self.payment_terms_menu.actions() if a.isChecked()]
        self.payment_terms_btn.setText(", ".join(selected) if selected else "Select")
        
    def _build_header_section(self):
        gb = QGroupBox("Invoice Info")
        grid = QGridLayout(gb)

        # Fields
        self.invoice_no    = QLineEdit(); self.invoice_no.setReadOnly(True)
        self.invoice_date  = QDateEdit(QDate.currentDate()); self.invoice_date.setCalendarPopup(True)
        self.due_date      = QDateEdit(QDate.currentDate().addDays(7)); self.due_date.setCalendarPopup(True)
        self.status_cb     = QComboBox(); self.status_cb.addItems(["Quotation", "Cash Sale"])
        
        self.subject       = QLineEdit()
        self.payment_terms_btn = QPushButton("Select")
        self.payment_terms_menu = QMenu(self.payment_terms_btn)
        self.payment_term_options = ["Bank Transfer", "Cheque", "Cash", "Pay Order", "Card", "Loan"]

        for option in self.payment_term_options:
            action = QAction(option, self.payment_terms_menu)
            action.setCheckable(True)
            action.toggled.connect(self._update_payment_terms_display)
            self.payment_terms_menu.addAction(action)
            
        # Default to "Cash"
        for action in self.payment_terms_menu.actions():
            if action.text() == "Cash":
                action.setChecked(True)
                break
        self._update_payment_terms_display()

        self.payment_terms_btn.setMenu(self.payment_terms_menu)
        self.site_address  = QLineEdit()

        self.client_cb = QComboBox()
        self.client_cb.addItem("")
        self.client_cb.setInsertPolicy(QComboBox.NoInsert)
        self.client_cb.currentTextChanged.connect(self._autofill_site_address)
        self.client_cb.setEditable(True)
        self._apply_completer(self.client_cb)

        # If clients were loaded earlier for any reason, reflect them now
        if getattr(self, "clients", None):
            self._refresh_client_combo()
        
        # ✅ Select first filtered item on Enter
        def select_first_from_completer():
            comp = self.client_cb.completer()
            model = comp.completionModel()
            if model.rowCount() > 0:
                index = model.index(0, 0)
                first_match = index.data(Qt.DisplayRole)
                i = self.client_cb.findText(first_match, Qt.MatchExactly)
                if i != -1:
                    self.client_cb.setCurrentIndex(i)

        # self.client_cb.lineEdit().returnPressed.connect(select_first_from_completer)

        self.rep_cb = QComboBox()
        self.rep_cb.addItem("")  # optional
        for label, emp_id in self.sales_reps.items():
            self.rep_cb.addItem(label, emp_id)  # store Firestore doc.id
        self._apply_completer(self.rep_cb)

        # Row 0
        grid.addWidget(QLabel("Invoice #:"),   0, 0)
        grid.addWidget(self.invoice_no,        0, 1)
        grid.addWidget(QLabel("Type:"),        0, 2)
        grid.addWidget(self.status_cb,         0, 3)
        grid.addWidget(QLabel("Subject:"),     0, 4)
        grid.addWidget(self.subject,           0, 5)

        # Row 1
        grid.addWidget(QLabel("Invoice Date:"), 1, 0)
        grid.addWidget(self.invoice_date,       1, 1)
        grid.addWidget(QLabel("Due Date:"),     1, 2)
        grid.addWidget(self.due_date,           1, 3)
        grid.addWidget(QLabel("Payment Terms:"), 1, 4)
        grid.addWidget(self.payment_terms_btn,   1, 5)

        # Row 2
        grid.addWidget(QLabel("Client:"),       2, 0)
        grid.addWidget(self.client_cb,          2, 1)
        grid.addWidget(QLabel("Site Address:"), 2, 2)
        grid.addWidget(self.site_address,       2, 3)
        grid.addWidget(QLabel("Sales Rep:"),    2, 4)
        grid.addWidget(self.rep_cb,             2, 5)
        
        add_client_btn = QPushButton("➕ Add New Client")
        add_client_btn.setToolTip("Add New Client")
        grid.addWidget(add_client_btn, 3, 1, alignment=Qt.AlignLeft)
        add_client_btn.clicked.connect(self._add_new_client)
                
        # for i in range(6):
        #     grid.setColumnStretch(i, 1)

        return gb

    # — Items section —
    
    def _autofill_site_address(self, selected_text):
        selected_index = self.client_cb.currentIndex()
        client_doc_id = self.client_cb.itemData(selected_index)
        client_info = self.clients.get(client_doc_id)
        if client_info:
            addr = client_info["data"].get("address", "")
            self.site_address.setText(addr)
        else:
            self.site_address.clear()

    def _build_items_section(self):
        gb = QGroupBox("📦 Items")
        gb.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 15px;
                border: 2px solid #bbb;
                border-radius: 8px;
                margin-top: 10px;
                background-color: #fefefe;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 4px 10px;
                color: #2c3e50;
                font-size: 16px;
            }
        """)

        layout = QVBoxLayout(gb)
        layout.setContentsMargins(10, 10, 10, 10)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(5, 5, 5, 5)
        header_layout.setSpacing(10)

        header_style = """
            font-weight: bold;
            font-size: 15px;
            min-height: 32px;        /* match row height */
        """

        header_name = QLabel("Name");     header_name.setStyleSheet(header_style)
        header_qty = QLabel("Qty");       header_qty.setStyleSheet(header_style)
        header_rate = QLabel("Rate");     header_rate.setStyleSheet(header_style)
        header_amount = QLabel("Amount"); header_amount.setStyleSheet(header_style)
        header_edit = QLabel("Options"); header_edit.setStyleSheet(header_style)

        for lbl in (header_name, header_qty, header_rate, header_amount, header_edit):
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        header_layout.addWidget(header_name, 4)
        header_layout.addWidget(header_qty, 1)
        header_layout.addWidget(header_rate, 1)
        header_layout.addWidget(header_amount, 2)
        header_layout.addWidget(header_edit, 1)

        layout.addLayout(header_layout)

        # Scroll Area with container widget
        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setFixedHeight(300)  # fixed height, same as before
        self.items_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.items_scroll.setStyleSheet("""
            QScrollArea {
                background: #fdfdfd;
                border: none;
            }
        """)

        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setSpacing(10)
        self.items_layout.setContentsMargins(5, 5, 5, 5)
        self.items_layout.setAlignment(Qt.AlignTop)

        self.items_scroll.setWidget(self.items_container)
        layout.addWidget(self.items_scroll)

        # Add Main Product Button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        add_main_btn = QPushButton("➕ Add Main Product")
        add_main_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        add_main_btn.clicked.connect(self.add_main_product)
        btn_layout.addWidget(add_main_btn)
        layout.addLayout(btn_layout)

        return gb
    
    def add_main_product(self):
        dlg = MainProductEditorDialog(self.product_dict, self.pc_colors, self.conditions, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            self._add_main_product_card(data)
            
    def _add_main_product_card(self, data):
        # Create and add the card
        card = MainProductCardPreview(data, self._edit_main_product_card, self._remove_main_product_card)
        self.items_layout.addWidget(card)
        self.product_cards.append(card)

        # Divider line after each card
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet("color: #ccc; margin: 5px 0;")
        self.items_layout.addWidget(divider)

        self.calculate_totals()

    # — Summary section —
    
    def _get_subtotal(self):
        subtotal = 0
        for card in getattr(self, "product_cards", []):
            subtotal += card.data.get("total", 0)
        return subtotal
    
    def toggle_discount_mode(self):
        subtotal = self._get_subtotal()
        try:
            val = float(self.discount.text().replace(",", ""))
        except:
            val = 0
        if self.discount_is_percent:
            # Convert % to Rs
            val = subtotal * val / 100
            self.discount_toggle.setText("Rs")
            self.discount.setText(f"{val:.2f}")
        else:
            # Convert Rs to %
            val = (val / subtotal * 100) if subtotal else 0
            self.discount_toggle.setText("%")
            self.discount.setText(f"{val:.2f}")
        self.discount_is_percent = not self.discount_is_percent
        self.calculate_totals()

    def toggle_tax_mode(self):
        subtotal = self._get_subtotal()
        try:
            val = float(self.tax.text().replace(",", ""))
        except:
            val = 0.0
        if self.tax_is_percent:
            val = subtotal * val / 100
            self.tax_toggle.setText("Rs")
            self.tax.setText(f"{val:.2f}")
        else:
            val = (val / subtotal * 100) if subtotal else 0
            self.tax_toggle.setText("%")
            self.tax.setText(f"{val:.2f}")
        self.tax_is_percent = not self.tax_is_percent
        self.calculate_totals()

    def _build_summary_section(self):
        gb = QGroupBox("Summary")
        g = QGridLayout(gb)

        self.discount = QLineEdit("0")
        self.tax      = QLineEdit("0")
        self.shipping = QLineEdit("0")
        self.labour = QLineEdit("0")
        self.received_account_cb = QComboBox()
        self.received_account_cb.setEditable(True)  # searchablet
        self._apply_completer(self.received_account_cb)
        self.received = QLineEdit("0")
        self.total    = QLabel("Rs 0.00")
        self.balance  = QLabel("Rs 0.00")
        self.total.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.balance.setStyleSheet("font-weight: bold; font-size: 14px;")

        # Flags for percentage mode
        self.discount_is_percent = False
        self.tax_is_percent = False

        # Toggle buttons
        self.discount_toggle = QPushButton("Rs")
        self.discount_toggle.setFixedWidth(30)
        self.discount_toggle.clicked.connect(self.toggle_discount_mode)

        self.tax_toggle = QPushButton("Rs")
        self.tax_toggle.setFixedWidth(30)
        self.tax_toggle.clicked.connect(self.toggle_tax_mode)

        # Connect to totals
        for w in (self.discount, self.tax, self.shipping, self.received, self.labour):
            w.textChanged.connect(self.calculate_totals)

        # Layout
        g.addWidget(QLabel("Discount:"),  0, 0)
        g.addWidget(self.discount,        0, 1)
        g.addWidget(self.discount_toggle, 0, 2)

        g.addWidget(QLabel("Tax:"),       1, 0)
        g.addWidget(self.tax,             1, 1)
        g.addWidget(self.tax_toggle,      1, 2)

        g.addWidget(QLabel("Shipping:"),  0, 3); g.addWidget(self.shipping, 0, 4)
        g.addWidget(QLabel("Labour:"),  1, 3); g.addWidget(self.labour, 1, 4)
        
        g.addWidget(QLabel("Received:"),  2, 0)
        # Horizontal layout: account dropdown + amount field
        received_row = QHBoxLayout()
        received_row.setContentsMargins(0, 0, 0, 0)
        received_row.setSpacing(5)
        received_row.addWidget(self.received_account_cb, 2)
        received_row.addWidget(self.received, 1)
        g.addLayout(received_row, 2, 1, 1, 3)  # span across 3 columns

        g.addWidget(QLabel("Total:"),     2, 5); g.addWidget(self.total,    2, 6)
        g.addWidget(QLabel("Balance:"),   3, 5); g.addWidget(self.balance,  3, 6)

        return gb

    # — Notes section —

    def _build_notes_section(self):
        gb = QGroupBox("Notes & Terms")
        v = QVBoxLayout(gb)
        self.notes = QTextEdit(); self.notes.setPlaceholderText("Notes…")
        self.terms = QTextEdit(); self.terms.setPlaceholderText("Terms & conditions…")
        v.addWidget(self.notes); v.addWidget(self.terms)
        return gb

    # — Footer —

    def _build_footer_layout(self):
        h = QHBoxLayout()
        h.addStretch()
        self.save_btn = QPushButton("Save Invoice")
        self.save_btn.clicked.connect(self.finalize_invoice)  # default action (new doc)
        h.addWidget(self.save_btn)
        return h

    # — Calculations & actions —

    def calculate_totals(self):
        subtotal = self._get_subtotal()  # from product card

        try:
            disc = float(self.discount.text().replace(",", "") or 0)
            tax  = float(self.tax.text().replace(",", "") or 0)
            ship = float(self.shipping.text().replace(",", "") or 0)
            received = float(self.received.text().replace(",", "") or 0)
            labour = float(self.labour.text().replace(",", "") or 0)
        except:
            disc = tax = ship = received = labour = 0.0

        # Adjust based on % mode
        if self.discount_is_percent:
            disc = subtotal * disc / 100
        if self.tax_is_percent:
            tax = subtotal * tax / 100

        total = subtotal - disc + tax + ship + labour
        balance = total - received

        self.total.setText(f"Rs {total:,.2f}")
        self.balance.setText(f"Rs {max(0, balance):,.2f}")
        
    def get_invoice_data(self):
        items = []
        for card in self.product_cards:
            items.append(card.data)
        return items

    def finalize_invoice(self):
        """
        Quotation:
        - Save only (no JEs, no inventory).
        Cash Sale:
        - Validate AR link + payment account.
        - Save.
        - Post Revenue JE: DR AR (real) + CR 'Sales Revenue' (virtual, NO balance impact).
        - Post Payment JE: DR Cash/Bank, CR AR (updates balances).
        - (Inventory hook left for later.)
        """
        try:
            doc_type = self.status_cb.currentText().strip()  # "Quotation" or "Cash Sale"

            # --- Basic validations shared ---
            if self.client_cb.currentIndex() <= 0:
                QMessageBox.warning(self, "Missing Client", "Please select a client.")
                return

            items = self.get_invoice_data()
            if not items:
                QMessageBox.warning(self, "No Items", "Add at least one item before saving.")
                return

            # Totals from UI (+ % toggles)
            def _num(s):
                try: return float((s or "0").replace(",", ""))
                except: return 0.0

            subtotal = sum(i.get("total", 0.0) for i in items)
            disc = _num(self.discount.text()); tax = _num(self.tax.text())
            ship = _num(self.shipping.text()); labour = _num(self.labour.text())
            if getattr(self, "discount_is_percent", False): disc = subtotal * disc / 100.0
            if getattr(self, "tax_is_percent", False):      tax  = subtotal * tax  / 100.0
            total = round(subtotal - disc + tax + ship + labour, 2)

            # Dates & numbering
            inv_date = self.invoice_date.date().toPyDate()
            due_date = self.due_date.date().toPyDate()
            self._generate_invoice_number()
            inv_no = self.invoice_no.text().strip()

            # Client & rep
            client_id = self.client_cb.itemData(self.client_cb.currentIndex())
            rep_id = self.rep_cb.itemData(self.rep_cb.currentIndex())

            # Payment terms (multi)
            pay_terms = [a.text() for a in self.payment_terms_menu.actions() if a.isChecked()]

            # Received inputs (may be 0 for Quotation)
            received_amount = _num(self.received.text())
            recv_payload = self.received_account_cb.itemData(self.received_account_cb.currentIndex())
            received_account_id = (recv_payload or {}).get("id")

            # Branch meta
            branch_val = self.user_data.get("branch")
            if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
            branch_val = branch_val or "-"

            # Build doc
            invoice_doc = {
                "invoice_no": inv_no,
                "type": doc_type,
                "invoice_date": datetime.datetime.combine(inv_date, datetime.datetime.min.time()),
                "due_date": datetime.datetime.combine(due_date, datetime.datetime.min.time()),
                "client_id": client_id,
                "sales_rep_id": rep_id if rep_id else None,
                "site_address": self.site_address.text().strip(),
                "subject": self.subject.text().strip(),
                "payment_terms": pay_terms,
                "items": items,
                "amounts": {
                    "subtotal": float(subtotal),
                    "discount": float(disc),
                    "tax": float(tax),
                    "shipping": float(ship),
                    "labour": float(labour),
                    "total": float(total),
                    "received": float(received_amount if doc_type == "Cash Sale" else 0.0),
                    "balance": float(max(0.0, total - (received_amount if doc_type == "Cash Sale" else 0.0))),
                },
                "notes": self.notes.toPlainText().strip(),
                "terms": self.terms.toPlainText().strip(),
                "created_at": firestore.SERVER_TIMESTAMP,
                "created_by": self.user_data.get("email", "system"),
                "branch": branch_val,
                # Status: Open unless fully paid (for Cash Sale)
                "status": ("Open" if (doc_type == "Quotation" or total - received_amount > 0) else "Paid"),
            }

            # --- Quotation: save only ---
            if doc_type == "Quotation":
                inv_ref = db.collection("invoices").document()
                inv_ref.set(invoice_doc)
                QMessageBox.information(self, "Saved", f"Quotation {inv_no} saved.")
                self.close()
                return

            # --- Cash Sale flow ---
            # 1) AR must be linked on party; if missing, block (per your rule).
            party_ref = db.collection("parties").document(client_id)
            party_snap = party_ref.get()
            if not party_snap.exists:
                QMessageBox.critical(self, "Client Missing", "Selected client no longer exists.")
                return
            party = party_snap.to_dict() or {}
            ar_account_id = party.get("coa_account_id")
            if not ar_account_id:
                QMessageBox.warning(
                    self, "Link AR Account",
                    "This client has no linked Accounts Receivable account.\n\n"
                    "Open Clients/Suppliers and assign a CoA account first."
                )
                return

            # 2) Require a payment account + a non-zero received for Cash Sale (can be partial)
            if received_amount <= 0 or not received_account_id:
                QMessageBox.warning(self, "Payment Required",
                                    "Cash Sale requires a Received amount and a Cash/Bank account.")
                return

            # 3) Save doc first
            inv_ref = db.collection("invoices").document()
            inv_ref.set(invoice_doc)

            # 4) Post Revenue JE (virtual credit line, real AR debit → updates AR only)
            self._post_revenue_against_opening_equity(
                invoice_ref_id=inv_ref.id,
                client_id=client_id,
                amount=total,
                description=f"Cash Sale {inv_no} – revenue recognized (virtual revenue line)"
            )

            # 5) Post Payment JE (updates balances on Cash/Bank and AR)
            self._post_payment_journal(
                invoice_ref_id=inv_ref.id,
                client_id=client_id,
                received_account_id=received_account_id,
                amount=received_amount,
                description=f"Payment received for {inv_no}"
            )

            # 6) Inventory hook (left for future; non-blocking if present)
            try:
                if hasattr(self, "_adjust_inventory_on_sale"):
                    # In future this will also create Delivery Chalan
                    self._adjust_inventory_on_sale(items)
            except Exception as inv_err:
                QMessageBox.warning(self, "Inventory", f"Saved & posted, but inventory step skipped: {inv_err}")

            QMessageBox.information(self, "Saved", f"Cash Sale {inv_no} saved and posted.")
            self.close()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")


    def _post_revenue_virtual_je(self, invoice_ref_id, client_id, amount, description=""):
        """
        Revenue JE with a VIRTUAL credit line:
        - DR Accounts Receivable (party)  -> updates balances (real account)
        - CR 'Sales Revenue' (virtual)    -> NO balance impact, no account_id stored
        """
        if amount <= 0:
            return

        # Party & AR account (must exist — caller already validated)
        party = db.collection("parties").document(client_id).get().to_dict() or {}
        ar_account_id = party.get("coa_account_id")
        if not ar_account_id:
            raise RuntimeError("Client AR account missing while posting revenue JE.")

        # Snapshot current AR balance
        try:
            ar_snap = db.collection("accounts").document(ar_account_id).get()
            ar_doc = ar_snap.to_dict() or {}
            ar_pre = float(ar_doc.get("current_balance", 0.0) or 0.0)
            ar_type = ar_doc.get("type", "Asset")
        except Exception:
            ar_pre, ar_type = 0.0, "Asset"

        # Lines: one real, one virtual
        real_line = {
            "account_id": ar_account_id,
            "account_name": ar_doc.get("name", "Accounts Receivable"),
            "debit": float(amount),
            "credit": 0.0,
            "balance_before": ar_pre
        }
        virtual_line = {
            "virtual": True,
            "virtual_account_name": "Sales Revenue",
            "debit": 0.0,
            "credit": float(amount)
        }

        # Build JE (do not include virtual in lines_account_ids)
        now = datetime.datetime.now(datetime.timezone.utc)
        branch_val = self.user_data.get("branch")
        if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
        je = {
            "date": now,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": self.user_data.get("email", "system"),
            "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(now.timestamp())}",
            "description": description or "Invoice revenue (virtual counter line)",
            "purpose": "Sale",
            "branch": branch_val or "-",
            "invoice_ref": invoice_ref_id,
            "lines": [real_line, virtual_line],
            "lines_account_ids": [real_line["account_id"]],
            "meta": {"kind": "invoice_revenue", "virtual_credit": True}
        }

        # Apply AR balance increment only (Assets rule: debit - credit)
        net_change = float(amount) if ar_type in ["Asset", "Expense"] else -float(amount)

        db.collection("journal_entries").add(je)
        db.collection("accounts").document(ar_account_id).update({
            "current_balance": firestore.Increment(net_change)
        })
        
    def _post_revenue_against_opening_equity(self, invoice_ref_id, client_id, amount, description=""):
        # Revenue JE (NO virtual lines):
        # - DR Accounts Receivable (party)      -> real account
        # - CR Opening Balances Equity (global) -> real account (single money source)
        if amount <= 0:
            return

        # Resolve party + AR
        party = db.collection("parties").document(client_id).get().to_dict() or {}
        ar_account_id = party.get("coa_account_id")
        if not ar_account_id:
            raise RuntimeError("Client AR account missing while posting revenue JE.")

        # --- Find or create Opening Balances Equity ---
        eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
        if eq_q:
            equity_account_id = eq_q[0].id
            equity_account_name = (eq_q[0].to_dict() or {}).get("name", "System Offset Account")
            equity_doc = eq_q[0].to_dict() or {}
        else:
            # Create one (same shape as chart_of_accounts)
            from firebase_admin import firestore as _fs
            counter_ref = db.collection("meta").document("account_code_counter")
            transaction = _fs.client().transaction()

            @_fs.transactional
            def _generate_code_once_tx(trans):
                snap = counter_ref.get(transaction=trans)
                last = int(snap.get("last_code") or 1000)
                new  = last + 1
                trans.update(counter_ref, {"last_code": new})
                return new

            equity_code = _generate_code_once_tx(transaction)
            branches = self.user_data.get("branch", [])
            if isinstance(branches, str):
                branches = [branches]

            equity_account = {
                "name": "System Offset Account",
                "slug": "opening_balances_equity",
                "type": "Asset",
                "code": equity_code,
                "parent": None,
                "branch": branches,
                "description": "System-generated equity account for opening balances",
                "active": True,
                "is_posting": True,
                "opening_balance": None,
                "current_balance": 0.0,
                "subtype": "Equity",
            }
            doc_ref = db.collection("accounts").document()
            doc_ref.set(equity_account)
            equity_account_id = doc_ref.id
            equity_account_name = "Opening Balances Equity"
            equity_doc = equity_account

        # Snapshots for balances
        def _snap(acc_id):
            try:
                s = db.collection("accounts").document(acc_id).get()
                d = s.to_dict() or {}
                pre = float(d.get("current_balance", 0.0) or 0.0)
                return d, pre
            except Exception:
                return {}, 0.0

        ar_doc, ar_pre = _snap(ar_account_id)
        eq_doc, eq_pre = _snap(equity_account_id)

        # Lines
        real_lines = [
            {"account_id": ar_account_id,      "account_name": ar_doc.get("name","Accounts Receivable"), "debit": float(amount), "credit": 0.0, "balance_before": ar_pre},
            {"account_id": equity_account_id,  "account_name": equity_doc.get("name", "System Offset Account"), "debit": 0.0, "credit": float(amount), "balance_before": eq_pre},
        ]

        now = datetime.datetime.now(datetime.timezone.utc)
        branch_val = self.user_data.get("branch")
        if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
        je = {
            "date": now,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": self.user_data.get("email", "system"),
            "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(now.timestamp())}",
            "description": description or "Invoice revenue (Opening Balances Equity credit)",
            "purpose": "Sale",
            "branch": branch_val or "-",
            "invoice_ref": invoice_ref_id,
            "lines": real_lines,
            "lines_account_ids": [real_lines[0]["account_id"], real_lines[1]["account_id"]],
            "meta": {"kind": "opening_balance"}
        }

        # Balance deltas (Assets/Expenses: debit - credit; Others: credit - debit)
        def _net(acc_dict, debit, credit):
            typ = (acc_dict.get("type") or "Asset")
            return (debit - credit) if typ in ["Asset", "Expense"] else (credit - debit)

        updates = {
            ar_account_id: _net(ar_doc, float(amount), 0.0),
            equity_account_id: _net(eq_doc, 0.0, float(amount)),
        }

        db.collection("journal_entries").add(je)
        for acc_id, delta in updates.items():
            db.collection("accounts").document(acc_id).update({
                "current_balance": firestore.Increment(delta)
            })

    def _post_payment_journal(self, invoice_ref_id, client_id, received_account_id, amount, description=""):
        """
        Settlement JE (updates balances):
        DR Cash/Bank (received_account_id)  amount = paid
        CR Accounts Receivable (client AR)  amount = paid
        """
        if amount <= 0:
            return

        # AR must exist (already enforced for Cash Sale)
        party = db.collection("parties").document(client_id).get().to_dict() or {}
        ar_account_id = party.get("coa_account_id")
        if not ar_account_id:
            raise RuntimeError("Client AR account missing while posting payment JE.")

        # Pull account docs for snapshots
        def _snap(acc_id):
            try:
                s = db.collection("accounts").document(acc_id).get()
                d = s.to_dict() or {}; pre = float(d.get("current_balance", 0.0) or 0.0)
                return d, pre
            except Exception:
                return {}, 0.0

        recv_doc, recv_pre = _snap(received_account_id)
        ar_doc, ar_pre = _snap(ar_account_id)

        lines = [
            {"account_id": received_account_id, "account_name": recv_doc.get("name", ""), "debit": float(amount), "credit": 0.0, "balance_before": recv_pre},
            {"account_id": ar_account_id,       "account_name": ar_doc.get("name", ""),   "debit": 0.0,           "credit": float(amount), "balance_before": ar_pre},
        ]

        now = datetime.datetime.now(datetime.timezone.utc)
        branch_val = self.user_data.get("branch")
        if isinstance(branch_val, list): branch_val = branch_val[0] if branch_val else "-"
        je = {
            "date": now,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": self.user_data.get("email", "system"),
            "reference_no": f"JE-{uuid.uuid4().hex[:6].upper()}-{int(now.timestamp())}",
            "description": (description or "Invoice payment"),
            "purpose": "Sale",
            "branch": branch_val or "-",
            "invoice_ref": invoice_ref_id,
            "lines": lines,
            "lines_account_ids": [lines[0]["account_id"], lines[1]["account_id"]],
            "meta": {"kind": "invoice_payment"}
        }

        # Compute balance deltas using the same global rule as your JE screen
        # Assets/Expenses: debit - credit; Others: credit - debit  
        def _net(acc_dict, debit, credit):
            typ = (acc_dict.get("type") or "Asset")
            return (debit - credit) if typ in ["Asset", "Expense"] else (credit - debit)

        updates = {
            received_account_id: _net(recv_doc, float(amount), 0.0),
            ar_account_id:       _net(ar_doc,   0.0,           float(amount)),
        }

        # Commit: add JE, then increment balances
        db.collection("journal_entries").add(je)
        for acc_id, delta in updates.items():
            db.collection("accounts").document(acc_id).update({
                "current_balance": firestore.Increment(delta)
            })


    # ======== EDIT SUPPORT (load + update) ========

    def _to_qdate(self, val):
        try:
            import datetime as _dt
            if val is None:
                return QDate.currentDate()
            if hasattr(val, "to_datetime"):
                dt = val.to_datetime()
            elif isinstance(val, _dt.datetime):
                dt = val
            elif isinstance(val, _dt.date):
                dt = _dt.datetime(val.year, val.month, val.day)
            else:
                s = str(val)
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                dt = _dt.datetime.fromisoformat(s)
            return QDate(dt.year, dt.month, dt.day)
        except Exception:
            return QDate.currentDate()

    def _set_combo_by_data(self, combo, doc_id, fallback_label="(Unknown)"):
        if not doc_id:
            return
        i = combo.findData(doc_id)
        if i == -1:
            combo.addItem(fallback_label, doc_id)
            i = combo.count() - 1
        combo.setCurrentIndex(i)

    def _clear_items_ui(self):
        # remove product cards and dividers
        for i in reversed(range(self.items_layout.count())):
            w = self.items_layout.itemAt(i).widget()
            if w is not None:
                w.setParent(None)
        self.product_cards.clear()

    def load_invoice(self, doc_id, data=None):
        """
        Populate the editor with an existing invoice for EDITING.
        Call this from outside after constructing the window.
        """
        self._loaded_doc_id = doc_id

        # fetch if data not passed
        if data is None:
            snap = db.collection("invoices").document(doc_id).get()
            if not snap.exists:
                QMessageBox.critical(self, "Missing", "Invoice not found.")
                return
            data = snap.to_dict() or {}

        # Type / number
        doc_type = data.get("type") or "Quotation"
        if self.status_cb.findText(doc_type) != -1:
            self.status_cb.setCurrentText(doc_type)
        self.invoice_no.setText(data.get("invoice_no", ""))

        # Dates
        self.invoice_date.setDate(self._to_qdate(data.get("invoice_date")))
        self.due_date.setDate(self._to_qdate(data.get("due_date")))

        # Client / Rep
        self._set_combo_by_data(self.client_cb, data.get("client_id"), "[?] - Unknown client")
        self._set_combo_by_data(self.rep_cb,    data.get("sales_rep_id"), "Unknown")

        # Text fields
        self.subject.setText(data.get("subject", "") or "")
        self.site_address.setText(data.get("site_address", "") or "")
        self.notes.setPlainText(data.get("notes", "") or "")
        self.terms.setPlainText(data.get("terms", "") or "")

        # Payment terms (multi)
        selected_terms = set(data.get("payment_terms") or [])
        for act in self.payment_terms_menu.actions():
            act.setChecked(act.text() in selected_terms)
        self._update_payment_terms_display()

        # Items
        self._clear_items_ui()
        for it in (data.get("items") or []):
            self._add_main_product_card(it)

        # Amounts
        am = data.get("amounts") or {}
        def _num(x):
            try: return float(x or 0.0)
            except: return 0.0
        self.discount.setText(str(_num(am.get("discount"))))
        self.tax.setText(str(_num(am.get("tax"))))
        self.shipping.setText(str(_num(am.get("shipping"))))
        self.labour.setText(str(_num(am.get("labour"))))
        self.received.setText(str(_num(am.get("received"))))
        self.total.setText(f"Rs {_num(am.get('total')):,.2f}")
        self.balance.setText(f"Rs {_num(am.get('balance')):,.2f}")
        self._toggle_payment_fields(self.status_cb.currentText())
        self.calculate_totals()

        # Switch footer button to Update action
        try:
            self.save_btn.clicked.disconnect()
        except Exception:
            pass
        self.save_btn.setText("Update Invoice")
        self.save_btn.clicked.connect(self.update_invoice)

    def update_invoice(self):
        """
        Update the currently loaded invoice (no double JEs here).
        Use the 'Record Payment' flow elsewhere for cash movements.
        """
        if not self._loaded_doc_id:
            QMessageBox.warning(self, "No document", "Nothing loaded to update.")
            return

        # Rebuild items from cards
        items = [card.data for card in self.product_cards]

        # Numbers
        def _numtxt(le):
            try: return float((le.text() or "0").replace(",", ""))
            except: return 0.0

        try:
            subtotal = sum(float(i.get("total", 0.0) or 0.0) for i in items)
        except Exception:
            subtotal = 0.0

        disc   = _numtxt(self.discount)
        tax    = _numtxt(self.tax)
        ship   = _numtxt(self.shipping)
        labour = _numtxt(self.labour)
        total  = round(subtotal - disc + tax + ship + labour, 2)
        received_amt = _numtxt(self.received)  # informational; payments should be through JE flow
        balance = max(0.0, total - received_amt)

        inv_date = self.invoice_date.date().toPyDate()
        due_date = self.due_date.date().toPyDate()

        payload = {
            "type": self.status_cb.currentText(),
            "invoice_no": self.invoice_no.text().strip(),
            "invoice_date": datetime.datetime.combine(inv_date, datetime.datetime.min.time()),
            "due_date": datetime.datetime.combine(due_date, datetime.datetime.min.time()),
            "client_id": self.client_cb.itemData(self.client_cb.currentIndex()),
            "sales_rep_id": self.rep_cb.itemData(self.rep_cb.currentIndex()),
            "subject": self.subject.text().strip(),
            "site_address": self.site_address.text().strip(),
            "payment_terms": [a.text() for a in self.payment_terms_menu.actions() if a.isChecked()],
            "items": items,
            "amounts": {
                "subtotal": float(subtotal),
                "discount": float(disc),
                "tax": float(tax),
                "shipping": float(ship),
                "labour": float(labour),
                "total": float(total),
                "received": float(received_amt),
                "balance": float(balance),
            },
            "notes": self.notes.toPlainText().strip(),
            "terms": self.terms.toPlainText().strip(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        # Status: Open for Quotation, or until fully paid
        payload["status"] = ("Open" if (payload["type"] == "Quotation" or balance > 0.01) else "Paid")

        try:
            db.collection("invoices").document(self._loaded_doc_id).set(payload, merge=True)
            QMessageBox.information(self, "Updated", "Invoice updated.")
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Update failed", f"Could not update invoice:\n{e}")

    # — Helpers —
    
    def _add_new_client(self):
        # Step 1: Open Add Client Dialog
        dialog = PartyDialog(self.user_data)
        if dialog.exec_() == QDialog.Accepted:
            # Step 2: Reload clients
            self.load_clients()

            # Step 3: Match client by ID prefix before hyphen
            new_id = dialog.new_customer_id  # This should be the Firestore doc.id
            for i in range(self.client_cb.count()):
                doc_id = self.client_cb.itemData(i)
                if doc_id == new_id:
                    self.client_cb.setCurrentIndex(i)
                    break
                
    def _edit_main_product_card(self, card: MainProductCardPreview):
        dlg = MainProductEditorDialog(self.product_dict, self.pc_colors, self.conditions, card.data, self)
        if dlg.exec_() == QDialog.Accepted:
            updated_data = dlg.get_data()
            card.update_data(updated_data)
            self.calculate_totals()

    def _remove_main_product_card(self, card: MainProductCardPreview):
        self.items_layout.removeWidget(card)
        self.product_cards.remove(card)
        card.setParent(None)
        self.calculate_totals()  # ← trigger recalculation


    def _apply_completer(self, combo: QComboBox):
        combo.setEditable(True)
        comp = combo.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        
    def _update_invoice_no_preview(self):
        preview_code = self._get_next_invoice_code(self.status_cb.currentText())
        self.invoice_no.setText(preview_code)

    def _get_next_invoice_code(self, doc_type):
        prefix_map = {"Quotation": "QUOT", "Invoice": "INV", "Bill": "BILL", "Cash Sale": "CS"}
        prefix = prefix_map.get(doc_type, "INV")
        ref = db.collection("meta").document(f"invoice_code")
        doc = ref.get()
        n = int(doc.to_dict().get("value", 0)) + 1 if doc.exists else 1
        return f"{prefix}-{str(n).zfill(3)}"

    def _generate_invoice_number(self):
        doc_type = self.status_cb.currentText()
        code = self._get_next_invoice_code(doc_type)
        self.invoice_no.setText(code)

        # Update counter in Firestore
        prefix = code.split("-")[0]
        ref = db.collection("meta").document(f"invoice_code")
        ref.set({"value": int(code.split("-")[1])}, merge=True)
    def _find_first_account(self, **filters):
        """Return the first account document snapshot matching filters (or None)."""
        q = db.collection("accounts")
        for k, v in filters.items():
            q = q.where(k, "==", v)
        docs = list(q.limit(1).stream())
        return docs[0] if docs else None

    def _create_default_ar_account(self):
        """Create a minimal Accounts Receivable posting account and return its id."""
        account = {
            "name": "Accounts Receivable",
            "type": "Asset",
            "subtype": "Accounts Receivable",
            "code": f"AR-{uuid.uuid4().hex[:6]}",
            "parent": None,
            "branch": self.user_data.get("branch", []),
            "description": "System-generated Accounts Receivable",
            "active": True,
            "is_posting": True,
            "opening_balance": None,
            "current_balance": 0.0
        }
        doc_ref = db.collection("accounts").document()
        doc_ref.set(account)
        return doc_ref.id

    def _post_invoice_journal(self, invoice_ref_id, invoice_data):
        """Post invoice JE: Debit client AR account (must exist), Credit selected received account."""
        # Get party ID from combo box
        selected_index = self.client_cb.currentIndex()
        client_doc_id = self.client_cb.itemData(selected_index)

        # Get client party document
        try:
            party_doc = db.collection("parties").document(client_doc_id).get()
            if not party_doc.exists:
                raise RuntimeError(f"Party ID {client_doc_id} not found.")
            party_data = party_doc.to_dict() or {}
        except Exception as e:
            raise RuntimeError(f"Failed to load party data: {e}")

        # Require existing AR account
        ar_account_id = party_data.get("coa_account_id")
        if not ar_account_id:
            raise RuntimeError(
                f"No Accounts Receivable account linked to client '{party_data.get('name', '')}'.\n"
                f"Please open Clients/Suppliers and assign a CoA account first."
            )

        # Get credit account from UI
        payload = self.received_account_cb.itemData(self.received_account_cb.currentIndex())
        credit_account_id = payload.get("id") if isinstance(payload, dict) else None
        if not credit_account_id:
            raise RuntimeError("No credit account selected in received_account_cb.")

        # Amount from UI
        amount = float(self.received.text() or 0.0)
        if amount <= 0:
            raise RuntimeError("Invoice amount must be greater than zero.")

        # Journal entry lines
        lines = [
            {"account_id": ar_account_id, "debit": amount, "credit": 0},
            {"account_id": credit_account_id, "debit": 0, "credit": amount}
        ]

        now = datetime.datetime.now()
        je = {
            "date": now,
            "description": f"Invoice {invoice_ref_id} posting",
            "invoice_ref": invoice_ref_id,
            "created_at": now,
            "created_by": self.user_data.get("email", "system"),
            "lines": lines
        }

        transaction = firestore.client().transaction()
        je_ref = db.collection("journal_entries").document()

        @firestore.transactional
        def txn_post(tx):
            for l in lines:
                acc_ref = db.collection("accounts").document(l["account_id"])
                acc_snap = acc_ref.get(transaction=tx)
                if not acc_snap.exists:
                    raise RuntimeError(f"Account {l['account_id']} missing when posting invoice JE.")
                acc_data = acc_snap.to_dict() or {}
                acc_type = acc_data.get("type", "Asset")
                if acc_type in ["Asset", "Expense"]:
                    net = float(l.get("debit", 0)) - float(l.get("credit", 0))
                else:
                    net = float(l.get("credit", 0)) - float(l.get("debit", 0))
                tx.update(acc_ref, {"current_balance": firestore.Increment(net)})
            tx.set(je_ref, je)

        txn_post(transaction)



class MainProductWidget(QWidget):
    def __init__(self, product_dict, pc_colors, conditions, parent=None):
        super().__init__(parent)
        self.product_dict = product_dict
        self.pc_colors = pc_colors
        self.conditions = conditions
        self.boq_items = []

        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(12, 12, 12, 12)
        self.setStyleSheet("""
            QWidget#MainProductCard {
                border: 1px solid #ccc;
                border-radius: 6px;
                background-color: #fafafa;
            }
            QLabel {
                font-weight: normal;
                font-size: 13px;
            }
            QLineEdit, QComboBox, QTextEdit {
                font-size: 13px;
                padding: 4px;
            }
            QPushButton {
                padding: 4px 8px;
            }
        """)
        self.setObjectName("MainProductCard")

        # --- Main Product Info ---
        main_info_group = QGroupBox("Main Product Details")
        main_info_layout = QGridLayout(main_info_group)
        main_info_layout.setHorizontalSpacing(10)
        main_info_layout.setVerticalSpacing(6)

        self.main_product_text = QTextEdit()
        self.main_product_text.setPlaceholderText("Enter Main Product Description")
        self.main_product_text.setFixedHeight(50)

        self.qty_edit = QLineEdit("1")
        self.qty_edit.setFixedWidth(70)

        self.rate_edit = QLineEdit("0.00")
        self.rate_edit.setFixedWidth(100)

        self.total_label = QLabel("0.00")
        self.total_label.setFixedWidth(100)
        self.total_label.setStyleSheet("font-weight: bold;")

        # Signals
        self.qty_edit.textChanged.connect(self.recalculate_total)
        self.rate_edit.textChanged.connect(self.recalculate_total)

        main_info_layout.addWidget(QLabel("Description:"), 0, 0)
        main_info_layout.addWidget(self.main_product_text, 0, 1, 1, 4)

        main_info_layout.addWidget(QLabel("Qty:"), 1, 0)
        main_info_layout.addWidget(self.qty_edit, 1, 1)
        main_info_layout.addWidget(QLabel("Rate:"), 1, 2)
        main_info_layout.addWidget(self.rate_edit, 1, 3)
        main_info_layout.addWidget(QLabel("Total:"), 1, 4)
        main_info_layout.addWidget(self.total_label, 1, 5)

        main_layout.addWidget(main_info_group)

        # --- Divider Label ---
        divider = QLabel("Bill of Quantity (BoQ) Items")
        divider.setAlignment(Qt.AlignCenter)
        divider.setStyleSheet("color: #555; font-size: 12px; margin-top: 4px; margin-bottom: 4px;")
        main_layout.addWidget(divider)

        # --- BoQ Area ---
        self.boq_scroll = QScrollArea()
        self.boq_scroll.setWidgetResizable(True)

        self.boq_widget = QWidget()
        self.boq_layout = QVBoxLayout(self.boq_widget)
        self.boq_layout.setSpacing(8)
        self.boq_layout.setContentsMargins(8, 8, 8, 8)

        self.boq_scroll.setWidget(self.boq_widget)
        main_layout.addWidget(self.boq_scroll)

        # --- Add BoQ Button ---
        add_btn_layout = QHBoxLayout()
        add_btn_layout.addStretch()
        self.add_boq_btn = QPushButton("➕ Add BoQ Item")
        self.add_boq_btn.setToolTip("Add another item under this main product")
        self.add_boq_btn.clicked.connect(self.add_boq_item)
        add_btn_layout.addWidget(self.add_boq_btn)
        main_layout.addLayout(add_btn_layout)

        # Start with one item
        self.add_boq_item()
        
    def get_data(self):
        return {
            "main_product": self.main_product_text.toPlainText(),
            "qty": float(self.qty_edit.text() or "1"),
            "rate": float(self.rate_edit.text() or "0"),
            "total": float(self.total_label.text().replace(",", "") or "0"),
            "boq": [b.get_data() for b in self.boq_items]
        }

    def load_data(self, data):
        self.main_product_text.setText(data.get("main_product", ""))
        self.qty_edit.setText(str(data.get("qty", "1")))
        self.rate_edit.setText(str(data.get("rate", "0")))
        self.total_label.setText(f"{data.get('total', 0):,.2f}")

        # Clear existing and reload BoQ
        for b in self.boq_items:
            b.setParent(None)
        self.boq_items.clear()

        for bdata in data.get("boq", []):
            b = BoQItemWidget(self.product_dict, self.pc_colors, self.conditions)
            b.product_cb.setCurrentText(bdata.get("product", ""))
            b.color_cb.setCurrentText(bdata.get("color", ""))
            b.condition_cb.setCurrentText(bdata.get("condition", ""))
            b.qty_edit.setText(str(bdata.get("qty", "1")))
            b.rate_edit.setText(str(bdata.get("rate", "0")))
            b.recalculate_total()
            self.boq_items.append(b)
            self.boq_layout.addWidget(b)
            
        self.recalculate_total() 

    def add_boq_item(self):
        boq = BoQItemWidget(self.product_dict, self.pc_colors, self.conditions)
        boq.on_change_callback = self.recalculate_total
        self.boq_items.append(boq)
        self.boq_layout.addWidget(boq)
        self.recalculate_total()

    def recalculate_total(self):
        try:
            qty = float(self.qty_edit.text() or "1")
        except:
            qty = 1

        boq_total = sum(b.total for b in self.boq_items)

        # ✅ Only update if BoQ actually has something
        if boq_total > 0:
            rate = boq_total / qty if qty else boq_total
            self.rate_edit.setText(f"{rate:.2f}")
            self.total_label.setText(f"{boq_total:,.2f}")
        
class MainProductEditorDialog(QDialog):
    def __init__(self, product_dict, pc_colors, conditions, initial_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Main Product")
        self.setMinimumSize(900, 700)
        self.installEventFilter(self)

        self.widget = MainProductWidget(product_dict, pc_colors, conditions)
        layout = QVBoxLayout(self)
        layout.addWidget(self.widget)

        if initial_data:
            self.widget.load_data(initial_data)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return self.widget.get_data()
    
    def eventFilter(self, obj, event):
        if event.type() == event.KeyPress and event.key() == Qt.Key_Return:
            focused = self.focusWidget()
            # Block Return key if inside a line edit or combo box popup
            if isinstance(focused, (QLineEdit, QComboBox, QTextEdit)):
                return True  # Block the key press
        return super().eventFilter(obj, event)

        
class BoQItemWidget(QWidget):
    def __init__(self, product_dict, pc_colors, conditions, parent=None):
        super().__init__(parent)
        self.product_dict = product_dict
        self.on_change_callback = None
        self.total = 0.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setSpacing(3)

        self.product_cb = QComboBox()
        self.product_cb.setEditable(True)
        # Populate with labels so the list is visible
        self.product_cb.clear()
        self.product_cb.addItems(sorted(self.product_dict.keys()))
        self.product_cb.setFixedWidth(300)
        self.product_cb.setInsertPolicy(QComboBox.NoInsert)
        self.product_cb.currentIndexChanged.connect(self._on_product_change)

        # Initially empty — you can preload if needed later
        self.product_cb.addItem("")  

        # Setup completer
        completer = QCompleter(list(product_dict.keys()), self.product_cb)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.product_cb.setCompleter(completer)

        # Set completer behavior on enter
        def select_first_from_completer():
            comp = self.product_cb.completer()
            model = comp.completionModel()
            if model.rowCount() > 0:
                index = model.index(0, 0)
                first_match = index.data(Qt.DisplayRole)
                i = self.product_cb.findText(first_match, Qt.MatchExactly)
                if i != -1:
                    self.product_cb.setCurrentIndex(i)
                    self.update_price()

        self.product_cb.lineEdit().returnPressed.connect(select_first_from_completer)
        self.product_cb.currentTextChanged.connect(self.update_price)

        self.color_cb = QComboBox()
        self.color_cb.addItems(pc_colors)
        self.color_cb.setFixedWidth(80)

        self.condition_cb = QComboBox()
        self.condition_cb.addItems(conditions)
        self.condition_cb.setFixedWidth(80)

        self.qty_edit = QLineEdit("1")
        self.qty_edit.setFixedWidth(50)
        self.rate_edit = QLineEdit("0.00")
        self.rate_edit.setFixedWidth(70)
        self.total_label = QLabel("0.00")
        self.total_label.setFixedWidth(70)

        for w in [self.qty_edit, self.rate_edit]:
            w.textChanged.connect(self.recalculate_total)

        self.remove_btn = QPushButton("❌")
        self.remove_btn.setFixedWidth(30)
        self.remove_btn.clicked.connect(self.deleteLater)

        widgets = [
            self.product_cb, self.color_cb, self.condition_cb,
            self.qty_edit, self.rate_edit, self.total_label, self.remove_btn
        ]
        for w in widgets:
            layout.addWidget(w)
            
    def _on_product_change(self, *_):
        label = (self.product_cb.currentText() or "").strip()
        prod = self.product_dict.get(label) or {}
        try:
            rate = float(prod.get("selling_price", 0) or 0)
        except Exception:
            rate = 0.0
        # Only auto-set if user hasn't typed a custom rate yet or it's zero
        if (self.rate_edit.text() or "").strip() in ("", "0", "0.0", "0.00"):
            self.rate_edit.setText(f"{rate:.2f}")
        # Always recompute total
        self.recalculate_total()

    def get_data(self):
        return {
            "product": self.product_cb.currentText(),
            "color": self.color_cb.currentText(),
            "condition": self.condition_cb.currentText(),
            "qty": float(self.qty_edit.text() or "0"),
            "rate": float(self.rate_edit.text() or "0"),
            "total": float(self.total_label.text().replace(",", "") or "0")
        }

    def update_price(self):
        prod = self.product_dict.get(self.product_cb.currentText())
        if prod:
            self.rate_edit.setText(f"{prod.get('selling_price', 0):.2f}")
            self.recalculate_total()

    def recalculate_total(self):
        try:
            qty = float(self.qty_edit.text() or 0)
            rate = float(self.rate_edit.text() or 0)
            self.total = qty * rate
            self.total_label.setText(f"{self.total:,.2f}")
        except:
            self.total = 0
            self.total_label.setText("0.00")
        if self.on_change_callback:
            self.on_change_callback()
