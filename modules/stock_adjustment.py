from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QApplication, QProgressDialog, QListWidget, QLineEdit, QListWidgetItem
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QDateTime
from firebase.config import db

class StockAdjustment(QWidget):
    def __init__(self, user_data, dashboard=None):
        super().__init__()
        self.user_data = user_data
        self.branches = user_data.get("branch", [])
        if isinstance(self.branches, str):
            self.branches = [self.branches]

        self.products_data = []
        self.setup_ui()
        
        self.dashboard = dashboard
    
    @staticmethod
    def show_if_admin(user_data, dashboard=None):
        if user_data.get("role") != "admin":
            QMessageBox.critical(None, "Access Denied", "You are not authorized to adjust stocks")
            return
        window = StockAdjustment(user_data, dashboard)
        window.show()
        return window

    def setup_ui(self):
        self.setWindowTitle("📦 Stock Adjustment")
        self.resize(1280, 780)

        # --- Global, tasteful styling (bigger controls, rounded corners) ---
        self.setStyleSheet("""
            QWidget { background: #f3f5f9; color: #1f2937; font-family: 'Segoe UI', 'Inter', sans-serif; }
            QLabel { font-size: 15px; }
            QLineEdit, QComboBox {
                font-size: 16px; padding: 10px 14px; border-radius: 10px;
                border: 1px solid #d7dfeb; background: #ffffff;
            }
            QComboBox QAbstractItemView {
                font-size: 15px; padding: 6px; border: 1px solid #d7dfeb; background: #ffffff;
                selection-background-color: #e6f0ff;
            }
            QPushButton {
                font-size: 16px; padding: 10px 18px; border-radius: 10px; border: none;
                background: #2563eb; color: #ffffff;
            }
            QPushButton:hover { background: #1e40af; }
            QPushButton:disabled { background: #9ca3af; color: #f8fafc; }

            /* Cards */
            .card {
                background: #ffffff; border: 1px solid #e6ecf5; border-radius: 16px;
            }
            /* Table header */
            QHeaderView::section {
                background: #f8fafc; padding: 10px; font-size: 15px; border: none; border-bottom: 1px solid #e6ecf5;
            }
            QTableWidget {
                background: #ffffff; border: 1px solid #e6ecf5; border-radius: 12px;
                gridline-color: #edf2f7; font-size: 15px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # === HEADER CARD ===
        header_card = QWidget()
        header_card.setObjectName("header_card")
        header_card.setStyleSheet("QWidget#header_card { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f8fbff, stop:1 #ffffff); border: 1px solid #e6ecf5; border-radius: 16px; }")
        header_wrap = QVBoxLayout(header_card)
        header_wrap.setContentsMargins(18, 16, 18, 16)
        header_wrap.setSpacing(12)

        # Title row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title = QLabel("📦 Stock Adjustment")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Item code input + import button (bigger / prettier)
        self.product_id_input = QLineEdit()
        self.product_id_input.setPlaceholderText("Enter Product ID (e.g., ABC-001)")
        self.product_id_input.setFixedWidth(360)
        self.product_id_input.setMinimumHeight(44)

        import_btn = QPushButton("📥 Import Item")
        import_btn.setMinimumHeight(44)
        import_btn.setStyleSheet("QPushButton { background: #10b981; } QPushButton:hover { background: #059669; }")
        import_btn.clicked.connect(self.import_items)

        header_layout.addWidget(self.product_id_input)
        header_layout.addWidget(import_btn)

        header_wrap.addLayout(header_layout)

        # === FILTERS CARD ===
        filters_card = QWidget()
        filters_card.setObjectName("filters_card")
        filters_card.setProperty("class", "card")
        filters_wrap = QHBoxLayout(filters_card)
        filters_wrap.setContentsMargins(16, 14, 16, 14)
        filters_wrap.setSpacing(12)

        # Filter widgets — bigger + clear labels
        # Branch (from current user)
        lbl_branch = QLabel("Branch")
        lbl_branch.setStyleSheet("font-weight: 600;")
        self.branch_filter = QComboBox()
        self.branch_filter.setMinimumWidth(220)
        self.branch_filter.setMinimumHeight(44)
        self.branch_filter.addItem("All Branches")
        self.branch_filter.addItems(self.branches)

        # Color (meta/colors -> pc_colors)
        lbl_color = QLabel("Color")
        lbl_color.setStyleSheet("font-weight: 600;")
        self.color_filter = QComboBox()
        self.color_filter.setMinimumWidth(220)
        self.color_filter.setMinimumHeight(44)
        self.color_filter.addItem("All Colors")
        try:
            colors_doc = db.collection("meta").document("colors").get()
            if getattr(colors_doc, "exists", False):
                pc_colors = (colors_doc.to_dict() or {}).get("pc_colors", [])
                if isinstance(pc_colors, dict):
                    pc_colors = list(pc_colors.values())
                elif isinstance(pc_colors, str):
                    pc_colors = [pc_colors]
                cleaned = []
                seen = set()
                for c in pc_colors or []:
                    s = str(c).strip()
                    if s and s not in seen:
                        seen.add(s); cleaned.append(s)
                if cleaned:
                    self.color_filter.addItems(cleaned)
        except Exception as e:
            print(f"⚠️ Failed to load pc_colors: {e}")

        # Condition (fixed)
        lbl_condition = QLabel("Condition")
        lbl_condition.setStyleSheet("font-weight: 600;")
        self.condition_filter = QComboBox()
        self.condition_filter.setMinimumWidth(220)
        self.condition_filter.setMinimumHeight(44)
        self.condition_filter.addItem("All Conditions")
        self.condition_filter.addItems(["New", "Used", "Bad"])

        # Lay out filters (label above control for cleanliness)
        branch_col = QVBoxLayout(); branch_col.setSpacing(6)
        branch_col.addWidget(lbl_branch); branch_col.addWidget(self.branch_filter)

        color_col = QVBoxLayout(); color_col.setSpacing(6)
        color_col.addWidget(lbl_color); color_col.addWidget(self.color_filter)

        cond_col = QVBoxLayout(); cond_col.setSpacing(6)
        cond_col.addWidget(lbl_condition); cond_col.addWidget(self.condition_filter)

        filters_wrap.addLayout(branch_col)
        filters_wrap.addLayout(color_col)
        filters_wrap.addLayout(cond_col)
        filters_wrap.addStretch(1)

        header_wrap.addWidget(filters_card)
        layout.addWidget(header_card)

        # === TABLE (larger, comfy) ===
        table_card = QWidget()
        table_card.setObjectName("table_card")
        table_card.setProperty("class", "card")
        table_wrap = QVBoxLayout(table_card)
        table_wrap.setContentsMargins(14, 14, 14, 14)
        table_wrap.setSpacing(12)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Product", "Branch", "Color", "Condition", "Qty"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionMode(self.table.NoSelection)
        self.table.setMinimumHeight(420)
        self.table.setStyleSheet("QTableWidget::item { padding: 10px; }")

        table_wrap.addWidget(self.table)
        layout.addWidget(table_card)

        # === FOOTER BUTTONS (bigger) ===
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setStyleSheet("QWidget#footer { background: transparent; }")
        btn_layout = QHBoxLayout(footer)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch()

        save_btn = QPushButton("💾 Save Adjustments")
        save_btn.setMinimumHeight(46)
        save_btn.setStyleSheet("QPushButton { background: #22c55e; } QPushButton:hover { background: #16a34a; }")
        save_btn.clicked.connect(self.save_balances)

        view_log_btn = QPushButton("📜 View Log")
        view_log_btn.setMinimumHeight(46)
        view_log_btn.setStyleSheet("QPushButton { background: #64748b; } QPushButton:hover { background: #475569; }")
        view_log_btn.clicked.connect(self.view_log)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(view_log_btn)
        layout.addWidget(footer)

        # === Filter interactions ===
        self.branch_filter.currentTextChanged.connect(self.apply_filters)
        self.color_filter.currentTextChanged.connect(self.apply_filters)
        self.condition_filter.currentTextChanged.connect(self.apply_filters)


    def apply_filters(self):
        branch = self.branch_filter.currentText()
        color = self.color_filter.currentText()
        condition = self.condition_filter.currentText()

        for row in range(self.table.rowCount()):
            show = True
            if branch != "All Branches" and self.table.item(row, 1).text() != branch:
                show = False
            if color != "All Colors" and self.table.item(row, 2).text() != color:
                show = False
            if condition != "All Conditions" and self.table.item(row, 3).text() != condition:
                show = False
            self.table.setRowHidden(row, not show)
        
    def show_loader(self, parent, title="Please wait...", message="Processing..."):
        loader = QProgressDialog(message, None, 0, 0, parent)
        loader.setWindowModality(Qt.WindowModal)
        loader.setMinimumDuration(0)
        loader.setAutoClose(True)
        loader.setCancelButton(None)
        loader.setWindowTitle(title)
        loader.show()
        QApplication.processEvents()
        return loader
    
    def _unit_symbol(self, unit):
        u = (unit or "").strip().lower()
        if u == "inch": return '"'
        if u == "ft":   return "'"
        if u == "mm":   return "mm"
        return unit or ""

    def _fmt_num(self, val):
        try:
            f = float(val)
            if f == 0:
                return None  # treat zero as “skip”
            return str(int(f)) if f.is_integer() else str(f)
        except Exception:
            return None

    def _fmt_dims(self, length, width, height, length_unit, width_unit, height_unit):
        parts = []
        L = self._fmt_num(length)
        if L: parts.append(f"{L}{self._unit_symbol(length_unit)}")
        W = self._fmt_num(width)
        if W: parts.append(f"{W}{self._unit_symbol(width_unit)}")
        H = self._fmt_num(height)
        if H: parts.append(f"{H}{self._unit_symbol(height_unit)}")
        return " x ".join(parts)

    def import_items(self):
        item_code = self.product_id_input.text().strip()
        if not item_code:
            QMessageBox.warning(self, "Input Required", "Please enter a product code.")
            return

        try:
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            self.products_data.clear()

            loader = QProgressDialog("Fetching product from cloud...", "Cancel", 0, 0, self)
            loader.setWindowModality(Qt.WindowModal)
            loader.setMinimumDuration(0)
            loader.setCancelButton(None)
            loader.setWindowTitle("Please wait...")
            loader.show()
            QApplication.processEvents()

            # 🔍 Query by item_code field
            docs = db.collection("products").where("item_code", "==", item_code).stream()
            found = False
            for doc in docs:
                found = True
                data = doc.to_dict()
                product_id = doc.id
                sp = float(data.get("selling_price", 0))
                name = data.get("name", "")
                
                length  = data.get("length")
                width   = data.get("width")
                height  = data.get("height")
                l_unit  = data.get("length_unit")
                w_unit  = data.get("width_unit")
                h_unit  = data.get("height_unit")

                dims = self._fmt_dims(length, width, height, l_unit, w_unit, h_unit)
                display_name = f"{name} {dims}".strip() if dims else name

                self.products_data.append({
                    "doc_id": product_id,
                    "item_code": item_code,
                    "name": name,
                    "selling_price": sp
                })

                qty = data.get("qty", {})

                row = 0
                for branch, color_data in qty.items():
                    for color, cond_data in color_data.items():
                        for condition, value in cond_data.items():
                            self.table.insertRow(row)
                            
                            # Product name cell (same for all rows for this product)
                            product_item = QTableWidgetItem(display_name)
                            product_item.setFlags(product_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 0, product_item)

                            branch_item = QTableWidgetItem(branch)
                            branch_item.setFlags(branch_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 1, branch_item)

                            color_item = QTableWidgetItem(color)
                            color_item.setFlags(color_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 2, color_item)

                            condition_item = QTableWidgetItem(condition)
                            condition_item.setFlags(condition_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 3, condition_item)

                            qty_item = QTableWidgetItem(str(value))
                            qty_item.setFlags(qty_item.flags() | Qt.ItemIsEditable)  # ✅ Only qty is editable
                            qty_item.setTextAlignment(Qt.AlignCenter)
                            self.table.setItem(row, 4, qty_item)


                            # sp_item = QTableWidgetItem(f"{sp:.2f}")
                            # sp_item.setFlags(sp_item.flags() ^ Qt.ItemIsEditable)
                            # sp_item.setTextAlignment(Qt.AlignCenter)
                            # self.table.setItem(row, 4, sp_item)

                            # total_item = QTableWidgetItem(f"{value * sp:.2f}")
                            # total_item.setFlags(total_item.flags() ^ Qt.ItemIsEditable)
                            # total_item.setTextAlignment(Qt.AlignCenter)
                            # self.table.setItem(row, 5, total_item)

                            row += 1

            loader.close()
            self.table.blockSignals(False)

            if not found:
                QMessageBox.warning(self, "Not Found", "No product found with this item code.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch product: {e}")
            self.table.blockSignals(False)
        loader.close()


    # def on_item_changed(self, item):
    #     if item.column() == 3:
    #         self.update_total(item.row())

    # def update_total(self, row):
    #     try:
    #         qty_item = self.table.item(row, 3)
    #         sp_item = self.table.item(row, 4)
    #         total_item = self.table.item(row, 5)
    #         if not qty_item or not sp_item or not total_item:
    #             return
    #         qty = int(qty_item.text())
    #         sp = float(sp_item.text())
    #         total_item.setText(f"{qty * sp:.2f}")
    #     except:
    #         if self.table.item(row, 5):
    #             self.table.item(row, 5).setText("0.00")


    def save_balances(self):
        if not self.products_data:
            QMessageBox.warning(self, "No Data", "Please import a product first.")
            return

        product_id = self.products_data[0]["doc_id"]
        ref = db.collection("products").document(product_id)
        doc = ref.get()
        data = doc.to_dict()
        qty_data = {}

        loader = QProgressDialog("Saving adjustments...", None, 0, 0, self)
        loader.setWindowModality(Qt.WindowModal)
        loader.setMinimumDuration(0)
        loader.setCancelButton(None)
        loader.setWindowTitle("Please wait...")
        loader.show()
        QApplication.processEvents()

        for row in range(self.table.rowCount()):
            branch = self.table.item(row, 0).text()
            color = self.table.item(row, 1).text()
            condition = self.table.item(row, 2).text()
            qty = int(self.table.item(row, 3).text())

            qty_data.setdefault(branch, {}).setdefault(color, {})[condition] = qty

        ref.update({"qty": qty_data})

        old_qty_data = data.get("qty", {})
        updates_to_log = []

        for row in range(self.table.rowCount()):
            branch = self.table.item(row, 0).text()
            color = self.table.item(row, 1).text()
            condition = self.table.item(row, 2).text()
            new_qty = int(self.table.item(row, 3).text())

            old_qty = int(
                old_qty_data.get(branch, {})
                            .get(color, {})
                            .get(condition, 0)
            )

            if branch not in qty_data:
                qty_data[branch] = {}
            if color not in qty_data[branch]:
                qty_data[branch][color] = {}

            qty_data[branch][color][condition] = new_qty

            if old_qty != new_qty:
                updates_to_log.append({
                    "product_id": product_id,
                    "branch": branch,
                    "color": color,
                    "condition": condition,
                    "old_qty": old_qty,
                    "new_qty": new_qty,
                    "changed_qty": new_qty - old_qty,
                    "created": QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
                })

        loader.close()
        for entry in updates_to_log:
            db.collection("stock_adjustment").add(entry)
        QMessageBox.information(self, "Saved", "Stock adjusted successfully.")
        
    def get_total_qty(self, qty_dict):
        total = 0
        for b in qty_dict.values():
            for c in b.values():
                for val in c.values():
                    total += val
        return total

    def view_log(self):
        self.log_window = QWidget()
        self.log_window.setWindowTitle("📜 Stock Adjustment Log")
        self.log_window.resize(900, 640)

        # ✅ Track in dashboard for closing
        if self.dashboard:
            self.dashboard.open_windows.append(self.log_window)
            self.log_window.destroyed.connect(
                lambda: self.dashboard.open_windows.remove(self.log_window)
                if self.log_window in self.dashboard.open_windows else None
            )

        layout = QVBoxLayout(self.log_window)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ---- Visuals for the log window & list (UI only) ----
        self.log_window.setStyleSheet("""
            QWidget { background: #f6f7fb; font: 13px 'Segoe UI'; color: #1f2937; }
            QLineEdit { border: 1px solid #dbe3ec; border-radius: 8px; padding: 6px 10px; background:#fff; }
            QPushButton { border: none; border-radius: 8px; padding: 6px 12px; background:#6b7280; color:#fff; }
            QPushButton:hover { background:#575e6b; }
            QListWidget { background:#fff; border:1px solid #e8edf3; border-radius: 12px; }
            /* Chip badge */
            .chip { border:1px solid #e6eaf0; border-radius: 10px; padding:2px 8px; background:#f8fafc; color:#475569; }
            .muted { color:#6b7280; }
            .deltaPlus { color:#059669; font-weight:600; }
            .deltaMinus { color:#dc2626; font-weight:600; }
            .mono { font-family: 'Consolas','Courier New', monospace; }
        """)

        # Header row (search + count)
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search by item code, name, branch, color, condition")
        header_row.addWidget(search_bar, 1)

        self.count_label = QLabel("")
        header_row.addWidget(self.count_label, 0, Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(header_row)

        # Pretty list
        self.log_list = QListWidget()
        self.log_list.setSpacing(4)  # a bit of breathing room between rows
        layout.addWidget(self.log_list)

        # Footer actions
        footer = QHBoxLayout()
        footer.addStretch(1)
        delete_btn = QPushButton("🗑 Delete Selected Record")
        delete_btn.clicked.connect(self.delete_log_entry)
        footer.addWidget(delete_btn)
        layout.addLayout(footer)

        # --- helpers to render a pretty row (no logic changes) ---
        def make_row_widget(item_code, display_name, branch, color, condition, old_qty, new_qty, created):
            # Card container (no extra imports needed)
            card = QWidget()
            card.setObjectName("card")
            card.setStyleSheet("QWidget#card{border:1px solid #edf1f6; border-radius:10px; background:#ffffff;}")
            outer = QVBoxLayout(card)
            outer.setContentsMargins(10, 8, 10, 8)
            outer.setSpacing(6)

            # Top line: Title + quantities
            top = QHBoxLayout()
            top.setSpacing(6)

            safe_display_name = display_name or ""
            safe_item_code = item_code or ""
            title_lbl = QLabel(f"<b class='mono'>📦 {safe_item_code}</b> — {safe_display_name}")
            title_lbl.setTextFormat(Qt.RichText)
            top.addWidget(title_lbl, 1)

            # Right side: qty old → new and delta colored
            qty_box = QHBoxLayout()
            qty_box.setSpacing(6)
            try:
                old_i = int(old_qty)
            except Exception:
                old_i = 0
            try:
                new_i = int(new_qty)
            except Exception:
                new_i = 0
            qty_lbl = QLabel(f"<span class='mono'>{old_i} → {new_i}</span>")
            qty_lbl.setTextFormat(Qt.RichText)
            delta = new_i - old_i
            delta_cls = "deltaPlus" if delta > 0 else ("deltaMinus" if delta < 0 else "muted")
            delta_lbl = QLabel(f"<span class='{delta_cls} mono'><b>{ '+' if delta>0 else ''}{delta}</b></span>")
            delta_lbl.setTextFormat(Qt.RichText)
            qty_box.addWidget(qty_lbl, 0, Qt.AlignRight)
            qty_box.addWidget(delta_lbl, 0, Qt.AlignRight)
            top.addLayout(qty_box, 0)

            outer.addLayout(top)

            # Mid line: chips
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for text in (f"Branch: {branch}", f"Color: {color}", f"Condition: {condition}"):
                chip = QLabel(f"<span class='chip'>{text}</span>")
                chip.setTextFormat(Qt.RichText)
                chips.addWidget(chip, 0, Qt.AlignLeft)
            chips.addStretch(1)
            outer.addLayout(chips)

            # Bottom line: created timestamp
            created_lbl = QLabel(f"<span class='muted'>⏱ {created}</span>")
            created_lbl.setTextFormat(Qt.RichText)
            outer.addWidget(created_lbl, 0, Qt.AlignLeft)

            return card

        def set_count(n):
            self.count_label.setText(f"{n} record" + ("s" if n != 1 else ""))

        def render_items(items):
            self.log_list.clear()
            for (doc_id, pid, branch, color, condition, old_qty, new_qty, created, display_name, item_code) in items:
                row_widget = make_row_widget(item_code, display_name, branch, color, condition, old_qty, new_qty, created)
                list_item = QListWidgetItem(self.log_list)
                # keep delete logic intact: store tuple in UserRole
                list_item.setData(Qt.UserRole, (doc_id, pid, branch, color, condition, old_qty, new_qty))
                list_item.setSizeHint(row_widget.sizeHint())
                self.log_list.addItem(list_item)
                self.log_list.setItemWidget(list_item, row_widget)
            set_count(len(items))

        def load_logs():
            self.logs = []
            self.log_list.clear()

            loader = self.show_loader(self.log_window, "Loading Logs", "Fetching adjustment history...")
            try:
                for doc in db.collection("stock_adjustment").order_by("created", direction="DESCENDING").stream():
                    data = doc.to_dict()
                    pid = data.get("product_id", "")
                    branch = data.get("branch", "")
                    color = data.get("color", "")
                    condition = data.get("condition", "")
                    old_qty = data.get("old_qty", 0)
                    new_qty = data.get("new_qty", 0)
                    created = data.get("created", "")

                    # 🔍 Always fetch product details from Firestore
                    product_doc = db.collection("products").document(pid).get()
                    if product_doc.exists:
                        product_data = product_doc.to_dict()
                        pname = product_data.get("name", "")
                        item_code = product_data.get("item_code", "")

                        # ➕ Dimensions (nice in name if present)
                        width = product_data.get("width")
                        length = product_data.get("length")
                        height = product_data.get("height")

                        width_unit = product_data.get("width_unit", "")
                        length_unit = product_data.get("length_unit", "")
                        height_unit = product_data.get("height_unit", "")

                        def format_value(val):
                            return str(int(val)) if isinstance(val, (int, float)) and val == int(val) else str(val)

                        def unit_symbol(unit):
                            unit = (unit or "").lower()
                            if unit == "inch":
                                return '"'
                            elif unit == "ft":
                                return "'"
                            elif unit == "mm":
                                return "mm"
                            return unit

                        width_str = f"{format_value(width)}{unit_symbol(width_unit)}" if width is not None else ""
                        length_str = f"{format_value(length)}{unit_symbol(length_unit)}" if length is not None else ""
                        height_str = f"{format_value(height)}{unit_symbol(height_unit)}" if height is not None else ""
                        dims = " x ".join(filter(None, [width_str, length_str, height_str]))
                        display_name = f"[{dims}] {pname}" if dims else pname
                    else:
                        display_name = pname = item_code = ""

                    self.logs.append((doc.id, pid, branch, color, condition, old_qty, new_qty, created, display_name, item_code))
            finally:
                loader.close()

            render_items(self.logs)

        def filter_logs():
            keyword = search_bar.text().lower().strip()
            if not keyword:
                render_items(self.logs)
                return

            filtered = []
            for tup in self.logs:
                doc_id, pid, branch, color, condition, old_qty, new_qty, created, display_name, item_code = tup
                hay = " ".join([
                    str(item_code or ""), str(display_name or ""), str(branch or ""), str(color or ""), str(condition or "")
                ]).lower()
                if keyword in hay:
                    filtered.append(tup)
            render_items(filtered)

        search_bar.textChanged.connect(filter_logs)
        load_logs()
        self.log_window.show()


    def delete_log_entry(self):
        current_item = self.log_list.currentItem()
        if current_item is None:
            QMessageBox.warning(self, "Select Entry", "Please select a log entry to delete.")
            return

        data = current_item.data(Qt.UserRole)

        # 🔒 Skip if it's a separator or invalid
        if not data:
            # QMessageBox.warning(self, "Invalid Selection", "Please select a valid log entry, not a separator.")
            return

        loader = self.show_loader(self, "Deleting", "Please wait...")

        doc_id, pid, branch, color, condition, old_qty, new_qty = data

        try:
            ref = db.collection("products").document(pid)
            product_data = ref.get().to_dict()
            qty_data = product_data.get("qty", {})

            # Revert to old_qty
            if branch in qty_data and color in qty_data[branch] and condition in qty_data[branch][color]:
                qty_data[branch][color][condition] = old_qty
                ref.update({"qty": qty_data})
                db.collection("stock_adjustment").document(doc_id).delete()

                loader.close()
                QMessageBox.information(self, "Deleted", "Log entry deleted and stock reverted.")
                self.view_log()
            else:
                loader.close()
                QMessageBox.warning(self, "Error", "Matching stock entry not found to reverse.")
        except Exception as e:
            loader.close()
            QMessageBox.critical(self, "Error", f"Failed to delete: {e}")