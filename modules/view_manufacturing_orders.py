from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QGraphicsScene, QDialog, QMessageBox, QListView, QFrame,
    QTextBrowser, QScrollArea, QProgressDialog, QApplication, QInputDialog
)
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtCore import Qt, QSize
from firebase.config import db
from firebase_admin import firestore
from datetime import datetime, timezone
from modules.manufacturing_cycle import ManufacturingModule, PannableGraphicsView
import traceback


class ViewManufacturingWindow(QWidget):
    def __init__(self, user_data, dashboard=None, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.dashboard = dashboard
        self.setWindowTitle("📦 Manufacturing Orders")
        self.resize(1200, 700)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("📋 List of Manufacturing Orders"))

        self.order_list = QListWidget()
        self.order_list.setViewMode(QListView.ListMode)
        self.order_list.setSpacing(6)
        self.order_list.setStyleSheet("QListWidget::item { padding: 10px; }")
        self.order_list.itemDoubleClicked.connect(self.open_order)
        layout.addWidget(self.order_list)

        self.load_orders()

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

    def load_orders(self):
        loader = self.show_loader(self, "Loading Orders", "Fetching manufacturing orders...")
        self.order_list.clear()
        try:
            orders = db.collection("manufacturing_orders").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
            for doc in orders:
                data = doc.to_dict()
                data['id'] = doc.id
                ts = data.get("created_at")
                readable_date = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else "Unknown"
                sheets = data.get("sheets", [])
                status = data.get("status", "Pending")

                status_colors = {
                    "Completed": "#2ecc71",
                    "In Progress": "#3498db",
                    "Rejected": "#e74c3c",
                    "Pending": "#f39c12"
                }
                status_color = status_colors.get(status, "#95a5a6")

                summary = f"""
                <div style='
                    background-color: #fdfdfd;
                    border: 1px solid #ddd;
                    border-radius: 12px;
                    padding: 12px 16px;
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    color: #2d3436;
                '>
                    <div style='margin-bottom: 6px;'>
                        <span style='font-weight: bold;'>🆔 {doc.id}</span>
                    </div>
                    <div>📄 Sheets: <b>{len(sheets)}</b></div>
                    <div>📅 <span>{readable_date}</span></div>
                    <div style='margin-top: 8px;'>
                        <span style='
                            background-color: {status_color};
                            color: white;
                            padding: 8px 8px;
                            border-radius: 12px;
                            font-weight: bold;
                            font-size: 12px;
                        '>
                            {status}
                        </span>
                    </div>
                </div>
                """
                item = QListWidgetItem()
                item.setSizeHint(QSize(300, 150))
                label = QLabel(summary)
                label.setStyleSheet("QLabel { padding: 10px; }")
                label.setFrameShape(QFrame.Box)
                label.setTextFormat(Qt.RichText)
                self.order_list.addItem(item)
                self.order_list.setItemWidget(item, label)
                item.setData(Qt.UserRole, data)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
        finally:
            loader.close()

    def open_order(self, item):
        data = item.data(Qt.UserRole)
        dlg = RefactoredOrderDialog(order_data=data, user_data=self.user_data, dashboard=self.dashboard, parent=self)
        if self.dashboard:
            self.dashboard.open_windows.append(dlg)
            dlg.destroyed.connect(lambda: self.dashboard.open_windows.remove(dlg))
        dlg.exec_()
        self.load_orders()

class RefactoredOrderDialog(QDialog):
    def __init__(self, order_data, user_data, dashboard=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 Order Details")
        self.resize(1200, 800)

        self.order_data = order_data
        self.user_data = user_data
        self.dashboard = dashboard
        self.current_index = 0
        self.sheet_data = {}  # ✅ Add this line

        # === Main Layout ===
        main_layout = QHBoxLayout(self)

        # === Left Panel (Info + Controls) ===
        left_panel = QVBoxLayout()
        header = QLabel(f"🧾 Order ID: {order_data.get('id', 'N/A')}")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        left_panel.addWidget(header)

        self.order_info = QTextBrowser()
        self.order_info.setStyleSheet("background-color: #f9f9f9; font-size: 13px;")
        self.order_info.setMinimumWidth(350)
        left_panel.addWidget(self.order_info, 1)

        controls = QHBoxLayout()
        self.btn_prev = QPushButton("⬅️ Previous")
        self.btn_prev.clicked.connect(self.prev_sheet)
        self.btn_next = QPushButton("Next ➡️")
        self.btn_next.clicked.connect(self.next_sheet)
        self.btn_refresh = QPushButton("🔁 Qty")
        self.btn_refresh.clicked.connect(self.refresh_raw_quantities)
        self.controls_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶️ Start")
        self.btn_start.clicked.connect(lambda: self.update_status("Started"))

        self.btn_partial = QPushButton("🟡 Complete Partially")
        self.btn_partial.clicked.connect(lambda: self.update_status("Partially Completed"))

        self.btn_done = QPushButton("✅ Complete Order")
        self.btn_done.clicked.connect(lambda: self.update_status("Completed"))

        self.btn_reject = QPushButton("❌ Reject")
        self.btn_reject.clicked.connect(lambda: self.update_status("Rejected"))
        self.btn_reject.clicked.connect(self.reject_order)

        controls.addWidget(self.btn_prev)
        controls.addWidget(self.btn_next)
        controls.addWidget(self.btn_refresh)
        controls.addStretch()
        # controls.addWidget(self.btn_start)
        # controls.addWidget(self.btn_done)
        # controls.addWidget(self.btn_partial)
        # controls.addWidget(self.btn_reject)
        # Controls: Sheet nav + refresh
        left_panel.addLayout(controls)

        # ✅ Add status-based buttons container properly
        status_controls_widget = QWidget()
        status_controls_widget.setLayout(self.controls_layout)
        left_panel.addWidget(status_controls_widget)

        # === Right Panel (Canvas) ===
        self.canvas = PannableGraphicsView()
        self.canvas.setMinimumSize(700, 700)
        self.scene = self.canvas.scene

        # Add both panels to main layout
        main_layout.addLayout(left_panel, 1)
        main_layout.addWidget(self.canvas, 2)

        self.refresh_view()
        self.refresh_status_controls()
        
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
    
    def refresh_status_controls(self):
        # Clear previous buttons
        for i in reversed(range(self.controls_layout.count())):
            widget = self.controls_layout.itemAt(i).widget()
            if widget:
                self.controls_layout.removeWidget(widget)
                widget.deleteLater()

        status = self.order_data.get("status", "Pending")
        
        if self.user_data.get("role") == "admin":
            self.btn_revert = QPushButton("Revert Status")
            self.btn_revert.clicked.connect(self.revert_status)
            self.controls_layout.addWidget(self.btn_revert)

        if status == "Pending":
            self.controls_layout.addWidget(self.btn_start)
            self.controls_layout.addWidget(self.btn_reject)
        elif status == "Started" or status == "Partially Completed":
            self.controls_layout.addWidget(self.btn_done)
            self.controls_layout.addWidget(self.btn_partial)
        else:
            notice = QLabel("🛑 No actions available.")
            notice.setStyleSheet("color: gray; font-style: italic;")
            self.controls_layout.addWidget(notice)
        
    def refresh_raw_quantities(self):
        loader = self.show_loader(self, "Refreshing", "Fetching updated quantities...")

        try:
            sheets = self.order_data.get("sheets", [])
            for sheet in sheets:
                raw_item = sheet.get("raw_item")
                if not raw_item:
                    continue

                raw_id = raw_item.get("id")
                branch = raw_item.get("branch")
                color = raw_item.get("color")
                condition = raw_item.get("condition")

                if not all([raw_id, branch, color, condition]):
                    continue

                # 🔄 Fetch latest data from Firestore
                doc = db.collection("products").document(raw_id).get()
                if not doc.exists:
                    continue

                product_data = doc.to_dict()
                qty_data = product_data.get("qty", {})
                updated_qty = qty_data.get(branch, {}).get(color, {}).get(condition, 0)

                sheet["raw_item"]["available_qty"] = updated_qty

            QMessageBox.information(self, "Refreshed", "Inventory quantities have been updated.")
            self.refresh_view()  # ✅ redraw updated info
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to refresh quantities:\n{e}")
        finally:
            loader.close()


    def refresh_view(self):
        sheets = self.order_data.get("sheets", [])
        if not sheets:
            self.order_info.setHtml("<h3>No sheets found for this order.</h3>")
            return
        self.current_index = max(0, min(self.current_index, len(sheets) - 1))
        sheet = sheets[self.current_index]
        self.setWindowTitle(f"🧾 Order View — Sheet {self.current_index + 1} of {len(sheets)}")
        self.draw_sheet(sheet)
        self.update_info_text(sheet)

    def prev_sheet(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.refresh_view()

    def next_sheet(self):
        if self.current_index < len(self.order_data.get("sheets", [])) - 1:
            self.current_index += 1
            self.refresh_view()

    def mark_completed(self):
        self.update_status("Completed")

    def reject_order(self):
        self.update_status("Rejected")
        
    def revert_status(self):
        order_id = self.order_data.get("id")
        if not order_id:
            QMessageBox.warning(self, "Missing ID", "Order ID not available.")
            return

        # Get history (in reverse to find last status)
        history = self.order_data.get("status_history", [])
        if len(history) < 2:
            QMessageBox.information(self, "No Previous Status", "There’s no previous status to revert to.")
            return

        prev_status = history[-2]["status"]  # second last
        confirm = QMessageBox.question(
            self, "Confirm Revert",
            f"Revert to previous status: {prev_status}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            # Revert status
            db.collection("manufacturing_orders").document(order_id).update({
                "status": prev_status,
                "status_history": history[:-1]  # remove last entry
            })
            QMessageBox.information(self, "Reverted", f"Order status reverted to {prev_status}.")
            self.order_data["status"] = prev_status
            self.order_data["status_history"] = history[:-1]
            self.refresh_status_controls()
            self.refresh_view()
        except Exception as e:
            QMessageBox.critical(self, "Revert Failed", str(e))

    def update_status(self, new_status):
        from PyQt5.QtWidgets import QInputDialog
        from collections import defaultdict

        status_labels = {
            "Started": "start this order",
            "Completed": "mark this order as completed",
            "Partially Completed": "mark this order as partially completed",
            "Rejected": "reject this order"
        }
        
        self.summary_text = "None"

        label = status_labels.get(new_status, f"change the status to '{new_status}'")
        confirm = QMessageBox.question(
            self,
            "Confirm Status Change",
            f"Are you sure you want to {label}?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return  # Cancelled

        order_id = self.order_data.get("id")
        if not order_id:
            QMessageBox.warning(self, "Missing Order ID", "Order ID is not set.")
            return
        
        soot_map = {
            0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2",
            0.625: "5/8", 0.75: "3/4", 0.875: "7/8"
        }

        def format_soot(value):
            whole = int(value)
            fraction = round(value - whole, 3)  # Round to nearest thousandth for safety

            # Snap to nearest known soot_map key
            closest = min(soot_map.keys(), key=lambda x: abs(x - fraction))

            # Only show fraction if it's not zero
            if abs(closest - 0) < 0.01:
                return f"{whole}"
            else:
                return f"{whole} {soot_map[closest]}"

        try:
            updates = []

            if new_status == "Started":
                # ✅ VALIDATE INVENTORY BEFORE STARTING
                usage_map = defaultdict(float)
                sheets = self.order_data.get("sheets", [])

                for sheet in sheets:
                    raw_item = sheet.get("raw_item", {})
                    raw_qty = float(raw_item.get("qty", 0))
                    raw_ref = raw_item.get("raw_ref")  # ✅ Now defined
                    branch = raw_item.get("branch", "")
                    color = raw_item.get("color", "")
                    condition = raw_item.get("condition", "")

                    # Get live quantity from Firestore
                    if raw_ref:
                        raw_doc = raw_ref.get()
                        if raw_doc.exists:
                            prod_data = raw_doc.to_dict()
                            available = prod_data.get("qty", {}).get(branch, {}).get(color, {}).get(condition, 0)
                        else:
                            available = 0
                    else:
                        available = 0

                    key = f"{raw_item.get('id')}|{branch}|{color}|{condition}"
                    usage_map[key] += raw_qty

                    if usage_map[key] > available:
                        QMessageBox.critical(
                            self,
                            "Inventory Error",
                            f"Can Not Start Order! Not Enough Raw Material In Inventory.\n\n"
                            f"{raw_item.get('name', '')} ({color or 'No Color'}, {condition}) @ {branch}\n"
                            f"Available: {available}, Requested: {usage_map[key]}"
                        )
                        return

            elif new_status in  ["Completed", "Partially Completed"]:
                sheets = self.order_data.get("sheets", [])
                summary_lines = []

                for sheet in sheets:
                    raw_item = sheet.get("raw_item", {})
                    products = sheet.get("products", [])
                    raw_qty = int(raw_item.get("qty", 0))
                    branch = raw_item.get("branch", "")
                    color = raw_item.get("color", "")
                    condition = raw_item.get("condition", "")
                    raw_ref = raw_item.get("raw_ref")
                    raw_doc = raw_ref.get().to_dict() if raw_ref else {}

                    used_qty = raw_qty
                    if new_status == "Partially Completed":
                        used_qty, ok = QInputDialog.getInt(
                            self, "Raw Used", f"How much raw qty used (of {raw_qty})?", raw_qty, 1, raw_qty
                        )
                        if not ok:
                            continue

                    # 🔻 Subtract Raw
                    if raw_ref:
                        doc = raw_ref.get()
                        if doc.exists:
                            inv = doc.to_dict().get("qty", {}).get(branch, {}).get(color, {}).get(condition, 0)
                            new_raw = max(0, inv - used_qty)
                            updates.append(("products", raw_ref.id, f"qty.{branch}.{color}.{condition}", new_raw))
                            summary_lines.append(f"🔻 -{used_qty} Raw: {raw_item.get('name')}")

                    # 🔺 Add Finished Products
                    for p in products:
                        prod_ref = p.get("product_ref")
                        if not prod_ref:
                            continue

                        # ✅ Already produced qty
                        qty_done = p.get("qty_done", 0)

                        # ✅ Total target = (units per raw) × (raw qty used)
                        full_target = int(p.get("qty", 0)) * raw_qty
                        remaining_qty = max(0, full_target - qty_done)

                        if remaining_qty == 0:
                            continue  # Nothing left to produce

                        # ✅ Determine how much to add this time
                        if new_status == "Completed":
                            prod_qty = remaining_qty  # Finish whatever's left
                        else:
                            # Ask user how much to produce (max = remaining)
                            prod_qty, ok2 = QInputDialog.getInt(
                                self,
                                "Product Qty",
                                f"How many units of '{p.get('name', '')}' made?\nRemaining: {remaining_qty}",
                                remaining_qty,  # Default
                                0,              # Min
                                remaining_qty   # Max
                            )
                            if not ok2:
                                continue

                        # ✅ Add this to write qty_done
                        product_path = f"sheets.{sheets.index(sheet)}.products.{products.index(p)}.qty_done"
                        updates.append(("manufacturing_orders", order_id, product_path, prod_qty))

                        prod_doc = prod_ref.get()
                        if prod_doc.exists:
                            inv = prod_doc.to_dict().get("qty", {}).get(branch, {}).get(color, {}).get(condition, 0)
                            updates.append(("products", prod_ref.id, f"qty.{branch}.{color}.{condition}", inv + prod_qty))
                            summary_lines.append(f"🔺 +{prod_qty} Finished: {p.get('name')}")

                    # === 3. Handle Waste Blocks ===
                    cuts = sheet.get("cuts", [])
                    item_data = raw_doc
                    
                    if item_data:
                        sheet_w = item_data.get("width", 0)
                        sheet_h = item_data.get("length", 0)

                        if cuts and sheet_w and sheet_h:
                            # 🧼 Clean and validate all rectangles (even legacy ones)
                            rectangles = []
                            for c in cuts:
                                try:
                                    x = float(c.get("x", 0)) if "x" in c else 0.0
                                    y = float(c.get("y", 0)) if "y" in c else 0.0

                                    # Guard: check for tuple/list values
                                    length = c.get("length", 0)
                                    width = c.get("width", 0)

                                    if isinstance(length, (tuple, list)) or isinstance(width, (tuple, list)):
                                        print(f"⚠️ Skipping invalid cut (tuple values): {c}")
                                        continue

                                    w = float(length)
                                    h = float(width)

                                    rectangles.append((x, y, w, h))

                                except Exception as e:
                                    print(f"⚠️ Skipping malformed cut: {c}, error: {e}")

                            sheet_w = item_data.get("width", 0)
                            sheet_h = item_data.get("length", 0)

                            rects, _ = ManufacturingModule().place_rectangles(sheet_w, sheet_h, rectangles)
                            rects_clean = []
                            for r in rects:
                                try:
                                    x, y, w, h = map(float, r[:4])  # ✅ Force real numbers
                                    rects_clean.append((x, y, w, h))
                                except Exception as e:
                                    print("⚠️ Skipping bad rect:", r, "→", e)
                            waste_blocks = ManufacturingModule().find_all_waste_blocks(sheet_w, sheet_h, rects_clean)

                            if waste_blocks:
                                block_lines = []
                                for i, block in enumerate(waste_blocks, 1):
                                    if not isinstance(block, (list, tuple)) or len(block) != 4:
                                        print(f"⚠️ Skipping malformed waste block: {block}")
                                        continue

                                    x, y, w, h = block

                                    try:
                                        w = float(w)
                                        h = float(h)
                                    except Exception as e:
                                        print(f"⚠️ Skipping block due to non-numeric dimensions: w={w}, h={h}, error={e}")
                                        continue

                                    w, h = sorted([w, h], reverse=True)
                                    if w < 1.5 or h < 1.5:
                                        continue  # Ignore too small scraps

                                    block_lines.append(f"🔹 Block {i}: {w:.2f} x {h:.2f} inch × {raw_qty} pcs")
                                self.summary_text = "\n".join(block_lines)
                                # ask = QMessageBox.question(
                                #     self,
                                #     "Confirm Waste Blocks",
                                #     f"The following waste blocks will be added to inventory:\n\n{summary_text}\n\nProceed?",
                                #     QMessageBox.Yes | QMessageBox.No
                                # )

                                # if ask == QMessageBox.Yes:
                                if True:
                                    # Get last item_code from meta/item_code_counter
                                    counter_ref = db.collection("meta").document("item_code_counter")
                                    counter_doc = counter_ref.get()
                                    last_code = counter_doc.to_dict().get("last_code", 1000)

                                    # Shared fields from raw material
                                    metal_type = item_data.get("metal_type", "")
                                    weight = item_data.get("weight", 0.0)
                                    gauge = item_data.get("gauge", 0)
                                    selling_price = item_data.get("selling_price", 0)
                                    reorder_qty = item_data.get("reorder_qty", 0)
                                    weight_unit = item_data.get("weight_unit", "kg")
                                    height_unit = item_data.get("height_unit", "Inch")
                                    
                                    # 🔁 Ensure 'Waste Raw Material' subcategory exists under 'Raw Material' main category
                                    waste_sub_id = None
                                    waste_name = "Waste Raw Material"
                                    subcats_ref = db.collection("product_sub_categories")
                                    maincats_ref = db.collection("product_main_categories")

                                    try:
                                        # 1. Get main_id of 'Raw Material'
                                        raw_main_id = None
                                        maincat_query = maincats_ref.where("name", "==", "Raw Material").limit(1).stream()
                                        maincat_doc = next(maincat_query, None)
                                        if maincat_doc:
                                            raw_main_id = maincat_doc.id

                                        if not raw_main_id:
                                            raise Exception("⚠️ 'Raw Material' main category not found!")

                                        # 2. Check for 'Waste Raw Material' subcategory under this main_id
                                        waste_sub_query = subcats_ref.where("name", "==", waste_name).where("main_id", "==", raw_main_id).limit(1).stream()
                                        waste_sub_doc = next(waste_sub_query, None)

                                        if waste_sub_doc:
                                            waste_sub_id = waste_sub_doc.id
                                        else:
                                            # 3. Create new subcategory
                                            new_doc = subcats_ref.add({
                                                "name": waste_name,
                                                "main_id": raw_main_id,
                                            })
                                            waste_sub_id = new_doc[1].id  # [1] is DocumentReference

                                    except Exception as e:
                                        print("🔥 Failed to get/create Waste Raw Material subcategory:", e)
                                        waste_sub_id = ""  # fallback if needed

                                    for block in waste_blocks:
                                        if not isinstance(block, (list, tuple)) or len(block) != 4:
                                            print(f"⚠️ Skipping invalid waste block: {block}")
                                            continue

                                        x, y, w, h = block

                                        try:
                                            w = float(w)
                                            h = float(h)
                                        except Exception as e:
                                            print(f"⚠️ Skipping block due to bad dimensions: w={w}, h={h}, error={e}")
                                            continue

                                        w, h = sorted([w, h], reverse=True)


                                        # Round to 2 decimal places to ensure match consistency
                                        rounded_w = round(w, 2)
                                        rounded_h = round(h, 2)

                                        # 🔍 Check for existing product
                                        query = db.collection("products") \
                                            .where("length", "==", rounded_w) \
                                            .where("width", "==", rounded_h) \
                                            .where("length_unit", "==", "Inch") \
                                            .where("width_unit", "==", "Inch") \
                                            .where("metal_type", "==", metal_type) \
                                            .where("gauge", "==", gauge) \
                                            .where("sub_id", "==", waste_sub_id) \
                                            .limit(1)

                                        existing_docs = list(query.stream())

                                        if existing_docs:
                                            # ✅ Reuse existing product, just update qty
                                            existing_doc = existing_docs[0]
                                            prod_data = existing_doc.to_dict()
                                            prod_id = existing_doc.id

                                            existing_qty = prod_data.get("qty", {}).get(branch, {}).get(color, {}).get(condition, 0)
                                            new_qty = existing_qty + raw_qty

                                            updates.append(("products", prod_id, f"qty.{branch}.{color}.{condition}", new_qty))

                                        else:
                                            # ❌ Not found — create new waste product
                                            last_code += 1
                                            new_code = str(last_code)
                                            
                                            # 🧮 Calculate weight based on dimensions and gauge in mm
                                            gauge_to_mm = {
                                                '11': 3, '12': 2.5, '13': 2.3, '14': 2, '16': 1.5,
                                                '18': 1.2, '20': 1, '22': 0.8, '23': 0.7,
                                                '24': 0.6, '26': 0.55, '28': 0.5
                                            }
                                            gauge_str = str(gauge)
                                            gauge_mm = gauge_to_mm.get(gauge_str, 0)
                                            calc_weight = round(((rounded_w * rounded_h)/144) * 0.729 * gauge_mm, 2)
                                            weight_unit = "kg"
                                            if calc_weight < 1:
                                                calc_weight *= 1000
                                                weight_unit = "g"
                                                
                                            w_str = format_soot(w)
                                            h_str = format_soot(h)

                                            name = f"Waste Sheet {w_str}\" x {h_str}\""

                                            waste_data = {
                                                "item_code": new_code,
                                                "name": name
                                                ,
                                                "length": rounded_w,
                                                "width": rounded_h,
                                                "height": 0.0,
                                                "length_unit": "Inch",
                                                "width_unit": "Inch",
                                                "height_unit": height_unit,
                                                "metal_type": metal_type,
                                                "weight": calc_weight,
                                                "weight_unit": weight_unit,
                                                "gauge": gauge,
                                                "selling_price": selling_price,
                                                "reorder_qty": reorder_qty,
                                                "sub_id": waste_sub_id,
                                                "qty": {
                                                    branch: {
                                                        color: {
                                                            condition: raw_qty
                                                        }
                                                    }
                                                }
                                            }

                                            try:
                                                db.collection("products").add(waste_data)
                                            except Exception as e:
                                                print("🔥 Error adding new waste product:", e)

                                            # ✅ Update item code counter only when new product is created
                                            counter_ref.update({"last_code": last_code})
                if summary_lines:
                    QMessageBox.information(self, "Inventory Summary", "\n".join(summary_lines) + f"\nWaste Added:\n{self.summary_text}")

            # === Final Step: Update Status ===
            # === Step 1: Safely update qty_done by modifying and writing back full sheets array ===
            order_doc_ref = db.collection("manufacturing_orders").document(order_id)
            order_data_full = order_doc_ref.get().to_dict()

            if not order_data_full:
                QMessageBox.critical(self, "Error", f"Order {order_id} no longer exists.")
                return

            # Get full sheets structure from Firestore
            sheets = order_data_full.get("sheets", [])

            # Apply qty_done from self.order_data (which has the latest UI values)
            for sheet_idx, sheet in enumerate(sheets):
                products = sheet.get("products", [])
                for prod_idx, product in enumerate(products):
                    try:
                        new_qty_done = self.order_data["sheets"][sheet_idx]["products"][prod_idx].get("qty_done")
                        if new_qty_done is not None:
                            product["qty_done"] = new_qty_done
                    except Exception as e:
                        print(f"Error copying qty_done for sheet {sheet_idx} product {prod_idx}: {e}")

            # ✅ Write back entire sheets array safely
            order_doc_ref.update({
                "sheets": sheets,
                "status": new_status,
                "status_history": firestore.ArrayUnion([{
                    "status": new_status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user": self.user_data.get("name", "Unknown")
                }])
            })

            # === Step 3: Apply all deep field updates (qty_done, inventory) ===
            for col, doc_id, field, value in updates:
                db.collection(col).document(doc_id).update({field: value})

            # === Step 4: Inventory adjustments (raw, finished, waste blocks) ===
            for sheet in self.order_data.get("sheets", []):
                raw_ref = sheet.get("raw_ref")
                if raw_ref:
                    try:
                        raw_data = raw_ref.get().to_dict()
                        raw_id = raw_ref.id
                        color = raw_data.get("color", "Unknown")
                        branch = self.user_data.get("branch")
                        condition = "Used"
                        used_qty = sheet.get("used_qty", 0)
                        raw_field = f"qty.{branch}.{color}.{condition}"
                        updates.append(("products", raw_id, raw_field, firestore.Increment(-used_qty)))
                    except Exception as e:
                        print(f"Failed to get raw_ref: {e}")

                for product in sheet.get("products", []):
                    prod_ref = product.get("product_ref")
                    if prod_ref:
                        try:
                            prod_data = prod_ref.get().to_dict()
                            prod_id = prod_ref.id
                            color = prod_data.get("color", "Unknown")
                            branch = self.user_data.get("branch")
                            condition = "Waste" if product.get("is_waste") else "New"
                            qty_done = product.get("qty_done", 0)
                            prod_field = f"qty.{branch}.{color}.{condition}"
                            updates.append(("products", prod_id, prod_field, firestore.Increment(qty_done)))
                        except Exception as e:
                            print(f"Failed to get prod_ref: {e}")
                            
            # === Step 5: Apply inventory updates ===
            for col, doc_id, field, value in updates:
                db.collection(col).document(doc_id).update({field: value})

            # === Step 6: UI Updates ===
            QMessageBox.information(self, "Status Updated", f"Order marked as {new_status}.")
            self.order_data["status"] = new_status
            self.order_data.setdefault("status_history", []).append({
                "status": new_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user": self.user_data.get("name", "Unknown")
            })
            self.refresh_status_controls()
            self.refresh_view()

        except Exception as e:
            error_message = traceback.format_exc()
            QMessageBox.critical(self, "Update Failed", str(error_message))
            


    def draw_sheet(self, sheet):
        dummy = ManufacturingModule()
        raw_item = sheet.get("raw_item", {})
        raw_ref = raw_item.get("raw_ref")
        if isinstance(raw_ref, str):
            raw_ref = db.document(raw_ref)

        try:
            item_data = raw_ref.get().to_dict() if raw_ref else {}
        except:
            item_data = {}

        dummy.item_dropdown.clear()
        dummy.item_dropdown.addItem(raw_item.get("name", "Unknown"), item_data)
        dummy.item_dropdown.setCurrentIndex(0)

        cuts = sheet.get("cuts", [])
        is_pipe = "pipe" in sheet.get("raw_subcat", "").lower()

        if is_pipe:
            dummy = ManufacturingModule()
            dummy.item_dropdown.clear()
            dummy.item_dropdown.addItem(raw_item.get("name", "Unknown"), item_data)
            dummy.item_dropdown.setCurrentIndex(0)

            dummy.sheet_data[0] = {
                "cuts": [ [c.get("height", 0)] for c in cuts ]
            }

            dummy.simulate_pipe_cutting(item_data)

            self.scene = dummy.scene
            self.canvas.setScene(self.scene)
        else:
            rectangles = []
            for c in cuts:
                try:
                    length = float(c.get("length", 0))
                    width = float(c.get("width", 0))
                    length_str = c.get("length_raw", str(length))
                    width_str = c.get("width_raw", str(width))
                    is_bracket = c.get("is_bracket", False)
                    rectangles.append((length, width, length_str, width_str, is_bracket))
                except:
                    pass

            dummy.sheet_data[0] = {"cuts": rectangles}
            dummy.simulate_cutting()

        self.scene = dummy.scene
        self.canvas.setScene(self.scene)

    def update_info_text(self, sheet):
        raw_item_data = sheet.get("raw_item", {})
        raw_ref = raw_item_data.get("raw_ref")
        product_doc = raw_ref.get().to_dict() if raw_ref else {}

        item_code = product_doc.get("item_code", "N/A")
        name = product_doc.get("name", "N/A")
        l_unit = product_doc.get("length_unit", "L")
        w_unit = product_doc.get("width_unit", "W")
        h_unit = product_doc.get("height_unit", "H")
        length = product_doc.get("length", 0)
        width = product_doc.get("width", 0)
        height = product_doc.get("height", 0)
        metal_type = product_doc.get("metal_type", "N/A")
        notes = self.order_data.get("notes", "").strip()

        formatted_name = f"{item_code} - {name} - {length}{l_unit} x {width}{w_unit} x {height}{h_unit} - {metal_type}"

        color = raw_item_data.get("color", "N/A")
        condition = raw_item_data.get("condition", "N/A")
        branch = raw_item_data.get("branch", "N/A")
        raw_qty = int(raw_item_data.get("qty", 1))
        qty_data = product_doc.get("qty", {}).get(branch, {}).get(color, {}).get(condition, 0)

        cuts = sheet.get("cuts", [])
        products = sheet.get("products", [])

        cut_lines = "".join(
            f"<li>{cut.get('height_raw', '?')} height</li>" if "height" in cut
            else f"<li>{cut.get('length_raw', '?')} x {cut.get('width_raw', '?')} {'(Bracket)' if cut.get('is_bracket') else ''}</li>"
            for cut in cuts
        )

        prod_lines = ""
        for p in products:
            name = p.get("name", "?")
            per_raw = int(p.get("qty", 0))
            total_expected = per_raw * raw_qty

            # ✅ Use the newly tracked `qty_done` field instead of legacy produced
            produced = int(p.get("qty_done", 0))  # fallback to 0 if missing

            # ✅ Status icon logic
            if produced >= total_expected:
                status_icon = "✅"
            elif produced > 0:
                status_icon = "⏳"
            else:
                status_icon = "❌"

            # ✅ Display as: ⏳ Product Name: 4 / 10
            prod_lines += f"<li>{status_icon} {name}: {produced} / {total_expected}</li>"
            
        html = f"""
        <h3>🔹 Raw Material</h3>
        <p><b>{formatted_name}</b><br>
        🎨 Color: {color}<br>
        🧪 Condition: {condition}<br>
        📦 Available in Inventory: {qty_data}<br>
        🧾 Required Quantity: {raw_qty}<br>
        <hr>
        <h4>✂️ Cuts</h4>
        <ul>{cut_lines}</ul>
        <h4>📦 Products</h4>
        <ul>{prod_lines}</ul>
        <h4>📝 Notes</h4>
        <ul>{notes}</ul>
        </p>
        """
        self.order_info.setHtml(html)
