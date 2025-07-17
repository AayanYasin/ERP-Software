from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QGraphicsScene, QDialog, QMessageBox, QListView, QFrame,
    QTextBrowser, QScrollArea, QProgressDialog, QApplication, QInputDialog
)
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtCore import Qt, QSize
from firebase.config import db
from firebase_admin import firestore
from datetime import datetime
from modules.manufacturing_cycle import ManufacturingModule, PannableGraphicsView


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
        controls.addWidget(self.btn_done)
        controls.addWidget(self.btn_reject)
        left_panel.addLayout(controls)

        # === Right Panel (Canvas) ===
        self.canvas = PannableGraphicsView()
        self.canvas.setMinimumSize(700, 700)
        self.scene = self.canvas.scene

        # Add both panels to main layout
        main_layout.addLayout(left_panel, 1)
        main_layout.addWidget(self.canvas, 2)

        self.refresh_view()
        
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

        if status == "Pending":
            self.controls_layout.addWidget(self.btn_start)
            self.controls_layout.addWidget(self.btn_reject)
        elif status == "Started":
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

    def update_status(self, new_status):
        status_labels = {
            "Started": "start this order",
            "Completed": "mark this order as completed",
            "Partially Completed": "mark this order as partially completed",
            "Rejected": "reject this order"
        }

        label = status_labels.get(new_status, f"change the status to '{new_status}'")
        confirm = QMessageBox.question(
            self,
            "Confirm Status Change",
            f"Are you sure you want to {label}?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return  # User cancelled

        try:
            db.collection("manufacturing_orders").document(self.order_data["id"]).update({
                "status": new_status
            })
            QMessageBox.information(self, "Status Updated", f"Order marked as {new_status}.")
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Update Failed", str(e))

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

        prod_lines = "".join(
            f"<li>{p.get('name', '?')}: {int(p.get('qty', 0))} x {raw_qty} = <b>{int(p.get('qty', 0)) * raw_qty}</b></li>"
            for p in products
        )

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
