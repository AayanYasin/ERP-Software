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

    def setup_ui(self):
        self.setWindowTitle("📦 Stock Adjustment")
        self.setStyleSheet("background-color: #f4f6f9;")
        self.resize(1100, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header_layout = QHBoxLayout()
        title = QLabel("📦 Stock Adjustment")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #2d3436;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.product_id_input = QLineEdit()
        self.product_id_input.setPlaceholderText("Enter Product ID")
        self.product_id_input.setFixedWidth(250)
        header_layout.addWidget(self.product_id_input)

        import_btn = QPushButton("📥 Import Item")
        import_btn.setStyleSheet("padding: 6px 12px; background-color: #0984e3; color: white; border-radius: 6px;")
        import_btn.clicked.connect(self.import_items)
        header_layout.addWidget(import_btn)

        layout.addLayout(header_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Branch", "Color", "Condition", "Qty"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionMode(self.table.NoSelection)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("💾 Save Adjustments")
        save_btn.setStyleSheet("padding: 8px 20px; background-color: #2ecc71; color: white; border-radius: 6px;")
        save_btn.clicked.connect(self.save_balances)

        view_log_btn = QPushButton("📜 View Log")
        view_log_btn.setStyleSheet("padding: 8px 20px; background-color: #636e72; color: white; border-radius: 6px;")
        view_log_btn.clicked.connect(self.view_log)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(view_log_btn)
        layout.addLayout(btn_layout)
        
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

                            branch_item = QTableWidgetItem(branch)
                            branch_item.setFlags(branch_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 0, branch_item)

                            color_item = QTableWidgetItem(color)
                            color_item.setFlags(color_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 1, color_item)

                            condition_item = QTableWidgetItem(condition)
                            condition_item.setFlags(condition_item.flags() ^ Qt.ItemIsEditable)
                            self.table.setItem(row, 2, condition_item)

                            qty_item = QTableWidgetItem(str(value))
                            qty_item.setFlags(qty_item.flags() | Qt.ItemIsEditable)  # ✅ Only qty is editable
                            qty_item.setTextAlignment(Qt.AlignCenter)
                            self.table.setItem(row, 3, qty_item)


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
        self.log_window.resize(800, 600)

        # ✅ Track in dashboard for closing
        if self.dashboard:
            self.dashboard.open_windows.append(self.log_window)
            self.log_window.destroyed.connect(
                lambda: self.dashboard.open_windows.remove(self.log_window)
                if self.log_window in self.dashboard.open_windows else None
            )

        layout = QVBoxLayout(self.log_window)

        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search by item code or name")
        layout.addWidget(search_bar)

        self.log_list = QListWidget()
        layout.addWidget(self.log_list)

        delete_btn = QPushButton("🗑 Delete Selected Record")
        delete_btn.clicked.connect(self.delete_log_entry)
        layout.addWidget(delete_btn)

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

                        # ➕ Get dimensions and units
                        width = product_data.get("width")
                        length = product_data.get("length")
                        height = product_data.get("height")

                        width_unit = product_data.get("width_unit", "")
                        length_unit = product_data.get("length_unit", "")
                        height_unit = product_data.get("height_unit", "")

                        def format_value(val):
                            return str(int(val)) if isinstance(val, (int, float)) and val == int(val) else str(val)

                        def unit_symbol(unit):
                            unit = unit.lower()
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
                        display_name = f"[{dims}] {pname}"
                    else:
                        display_name = pname = item_code = ""

                    log_text = (
                        f"📦 {item_code} - {display_name}\n"
                        f"Branch: {branch} | Color: {color} | Condition: {condition}\n"
                        f"Qty: {old_qty} → {new_qty} at {created}"
                    )

                    item = QListWidgetItem(log_text)
                    item.setData(Qt.UserRole, (doc.id, pid, branch, color, condition, old_qty, new_qty))
                    self.logs.append((doc.id, pid, branch, color, condition, old_qty, new_qty, created, display_name, item_code))
                    self.log_list.addItem(item)

                    separator = QListWidgetItem("—" * 60)
                    separator.setFlags(separator.flags() & ~Qt.ItemIsSelectable)
                    separator.setForeground(Qt.gray)
                    self.log_list.addItem(separator)
            finally:
                loader.close()

        def filter_logs():
            keyword = search_bar.text().lower()
            self.log_list.clear()

            for doc_id, pid, branch, color, condition, old_qty, new_qty, created, display_name, item_code in self.logs:
                if any(keyword in s.lower() for s in [item_code, display_name, branch, color, condition]):
                    log_text = (
                        f"📦 {item_code} - {display_name}\n"
                        f"Branch: {branch} | Color: {color} | Condition: {condition}\n"
                        f"Qty: {old_qty} → {new_qty} at {created}"
                    )

                    item = QListWidgetItem(log_text)
                    item.setData(Qt.UserRole, (doc_id, pid, branch, color, condition, old_qty, new_qty))
                    self.log_list.addItem(item)

                    separator = QListWidgetItem("—" * 60)
                    separator.setFlags(separator.flags() & ~Qt.ItemIsSelectable)
                    separator.setForeground(Qt.gray)
                    self.log_list.addItem(separator)

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