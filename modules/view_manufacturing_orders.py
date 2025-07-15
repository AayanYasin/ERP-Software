from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QGraphicsScene, QDialog, QMessageBox, QListView, QFrame,
    QTextBrowser, QScrollArea, QSizePolicy, QProgressDialog, QApplication, QInputDialog
)
from PyQt5.QtGui import QPainter, QFont
from PyQt5.QtCore import Qt, QSize, QTimer
from firebase.config import db
from firebase_admin import firestore
from datetime import datetime
from modules.manufacturing_cycle import ManufacturingModule, PannableGraphicsView
import os


class ViewManufacturingWindow(QWidget):
    def __init__(self, user_data, dashboard=None, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.setWindowTitle("📦 Manufacturing Orders")
        self.resize(1200, 700)
        self.sheet_index = 0
        
        self.dashboard = dashboard

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
                    "Completed": "#2ecc71",       # green
                    "In Progress": "#3498db",     # blue
                    "Rejected": "#e74c3c",        # red
                    "Pending":  "#f39c12"  # orange
                }
                status_color = status_colors.get(status, "#95a5a6")  # fallback gray

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
        self.setWindowTitle("🔍 View Manufacturing Order")
        self.resize(1300, 800)
        self.order_data = order_data
        self.user_data = user_data
        self.sheet_index = 0
        
        self.dashboard = dashboard  

        main_layout = QHBoxLayout(self)

        # Left: scrollable order info
        left = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        self.order_info = QTextBrowser()
        self.order_info.setStyleSheet("""
            QTextBrowser {
                font-size: 14px;
                padding: 16px;
                background-color: #ffffff;
                border: 1px solid #ddd;
                border-radius: 10px;
                color: #333;
            }
            h3, h4 {
                margin-top: 16px;
                margin-bottom: 8px;
                font-weight: bold;
                color: #2d3436;
                border-bottom: 1px solid #ccc;
                padding-bottom: 4px;
            }
            p {
                margin: 8px 0;
                line-height: 1.5em;
            }
            ul {
                margin: 0 0 12px 20px;
                padding-left: 0;
            }
            li {
                margin-bottom: 6px;
                line-height: 1.4em;
            }
            b {
                color: #2d3436;
            }
        """)

        title = QLabel("📄 Sheet Details")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 8px;
                color: #2d3436;
            }
        """)
        scroll_layout.addWidget(title)
        scroll_layout.addWidget(self.order_info)


        # Sheet nav buttons
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("⬅ Previous")
        self.next_btn = QPushButton("Next ➡")
        self.sheet_label = QLabel("Sheet 1")
        self.prev_btn.clicked.connect(self.prev_sheet)
        self.next_btn.clicked.connect(self.next_sheet)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.sheet_label)
        nav.addWidget(self.next_btn)
        scroll_layout.addLayout(nav)

        # Status control buttons
        btns = QHBoxLayout()
        self.edit_btn = QPushButton("✏️ Edit")
        self.in_progress_btn = QPushButton("🚧 Mark In Progress")
        self.completed_btn = QPushButton("✅ Mark Completed")
        self.reject_btn = QPushButton("❌ Reject")
        self.delete_btn = QPushButton("🗑️ Delete")
        
        self.edit_btn.clicked.connect(self.edit_order)
        self.in_progress_btn.clicked.connect(lambda: self.update_status("In Progress"))
        self.completed_btn.clicked.connect(lambda: self.update_status("Completed"))
        self.reject_btn.clicked.connect(lambda: self.update_status("Rejected"))
        self.delete_btn.clicked.connect(self.delete_order)

        for b in [self.edit_btn, self.in_progress_btn, self.completed_btn, self.reject_btn, self.delete_btn]:
            btns.addWidget(b)

        scroll_layout.addLayout(btns)

        scroll.setWidget(scroll_content)
        left.addWidget(scroll)
        main_layout.addLayout(left, 3)

        # Right: canvas
        self.scene = QGraphicsScene()
        self.canvas = PannableGraphicsView(self.scene)
        self.canvas.setRenderHint(QPainter.Antialiasing)
        main_layout.addWidget(self.canvas, 4)

        if self.order_data.get("sheets"):
            self.load_sheet(0)

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

    def edit_order(self):
        self.close()
        self.win = ManufacturingModule(edit_data=self.order_data, doc_id=self.order_data.get("id"))
        self.win.setAttribute(Qt.WA_DeleteOnClose)

        if self.dashboard:
            self.dashboard.open_windows.append(self.win)
            self.win.destroyed.connect(lambda: self.dashboard.open_windows.remove(self.win))

        self.win.show()
        
    
    def get_selected_branch(self):
        branches = self.user_data.get("branch", [])
        if isinstance(branches, str):
            return branches
        if isinstance(branches, list):
            if len(branches) == 1:
                return branches[0]
            selected, ok = QInputDialog.getItem(
                self, "Select Branch", "Choose branch to update inventory:",
                branches, 0, False
            )
            if ok:
                return selected
        return None

    def update_status(self, status):
        if status != "Completed":
            try:
                db.collection("manufacturing_orders").document(self.order_data.get("id")).update({"status": status})
                QMessageBox.information(self, "Success", f"Status updated to {status}")
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        else:
            self.complete_manufacturing()

            
    def complete_manufacturing(self):
        try:
            selected_branch = self.get_selected_branch()
            if not selected_branch:
                QMessageBox.warning(self, "Branch Required", "No branch selected.")
                return

            sheets = self.order_data.get("sheets", [])  
            order_id = self.order_data.get("id")

            for sheet in sheets:
                raw_qty = int(sheet.get("raw_qty", 1))
                raw_ref = sheet.get("raw_item", {}).get("raw_ref")

                if raw_ref:
                    raw_doc = raw_ref.get()
                    raw_data = raw_doc.to_dict()

                    # Subtract raw material
                    qty_field = raw_data.get("qty", {})
                    qty_field[selected_branch] = qty_field.get(selected_branch, 0) - raw_qty
                    raw_ref.update({"qty": qty_field})

                    # Handle leftover
                    if "width" in raw_data and "length" in raw_data:
                        total_area = float(raw_data.get("width", 0)) * float(raw_data.get("length", 0))
                        used_area = sum(
                            float(cut.get("length", 0)) * float(cut.get("width", 0))
                            for cut in sheet.get("cuts", []) if "length" in cut and "width" in cut
                        )
                        leftover_area = total_area - used_area

                        if leftover_area > 0:
                            reply = QMessageBox.question(
                                self, "Add Waste?",
                                "Add leftover material to inventory?",
                                QMessageBox.Yes | QMessageBox.No
                            )
                            if reply == QMessageBox.Yes:
                                leftover_width = float(raw_data.get("width", 1))
                                leftover_length = round(leftover_area / leftover_width, 2)

                                db.collection("products").add({
                                    "name": f"Leftover from {raw_data.get('name', '')}",
                                    "category": "Raw Material",
                                    "subcategory": "Metal Sheet",
                                    "width": leftover_width,
                                    "length": leftover_length,
                                    "width_unit": raw_data.get("width_unit"),
                                    "length_unit": raw_data.get("length_unit"),
                                    "qty": {selected_branch: raw_qty}
                                })

                # Add finished products
                for prod in sheet.get("products", []):
                    prod_ref = prod.get("product_ref")
                    if prod_ref:
                        prod_doc = prod_ref.get()
                        prod_data = prod_doc.to_dict()
                        qty_field = prod_data.get("qty", {})
                        qty_field[selected_branch] = qty_field.get(selected_branch, 0) + (prod.get("qty", 1) * raw_qty)
                        prod_ref.update({"qty": qty_field})

            db.collection("manufacturing_orders").document(order_id).update({"status": "Completed"})
            QMessageBox.information(self, "Completed", "Order marked as completed and inventory updated.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Completion failed: {str(e)}")



    def delete_order(self):
        confirm = QMessageBox.question(self, "Confirm Delete", "Are you sure you want to delete this order?")
        if confirm == QMessageBox.Yes:
            db.collection("manufacturing_orders").document(self.order_data.get("id")).delete()
            self.accept()

    def prev_sheet(self):
        if self.sheet_index > 0:
            self.sheet_index -= 1
            self.load_sheet(self.sheet_index)

    def next_sheet(self):
        if self.sheet_index + 1 < len(self.order_data.get("sheets", [])):
            self.sheet_index += 1
            self.load_sheet(self.sheet_index)

    def load_sheet(self, index):
        sheets = self.order_data.get("sheets", [])
        if not sheets or index >= len(sheets):
            return

        sheet = sheets[index]
        self.sheet_label.setText(f"📄 Sheet {index + 1} of {len(sheets)}")
        self.update_info_text(sheet)
        self.draw_sheet(sheet)

    def update_info_text(self, sheet):
        raw_item = sheet.get("raw_item", {}).get("name", "N/A")
        raw_qty = sheet.get("raw_qty", "?")
        subcat = sheet.get("raw_subcat", "?")
        status = self.order_data.get("status", "Pending")
        
        # Hide/disable buttons based on status
        if status == "Pending":
            self.completed_btn.hide()
        elif status == "In Progress":
            self.in_progress_btn.hide()
            self.reject_btn.hide()
        elif status in ["Completed", "Rejected"]:
            for btn in [self.edit_btn, self.in_progress_btn, self.completed_btn, self.reject_btn, self.delete_btn]:
                btn.setDisabled(True)
                btn.setStyleSheet("color: gray; background-color: #eee;")

        cuts = sheet.get("cuts", [])
        products = sheet.get("products", [])

        cut_lines = "".join(
            f"<li>{cut['height_raw']} height</li>" if "height_raw" in cut
            else f"<li>{cut['length_raw']} x {cut['width_raw']}</li>"
            for cut in cuts
        )

        prod_lines = "".join(
            f"<li>{p['name']} = <b>{int(p['qty'])*int(raw_qty)}</b></li>" for p in products
        )

        html = f"""
        <h3 style='margin-bottom:5px;'>🔹 Raw Material</h3>
        <p><b>{raw_item}</b> <i>({subcat})</i><br><br>
        <b>Quantity:</b> {raw_qty}<br><br>
        <b>Status:</b> {status}</p>
        <hr>
        <h4>✂️ Cuts</h4>
        <ul>{cut_lines}</ul>
        <h4>📦 Products</h4>
        <ul>{prod_lines}</ul>
        """

        self.order_info.setHtml(html)
        

    def draw_sheet(self, sheet):
        loader = self.show_loader(self, "Rendering Sheet", "Generating layout view...")
        self.scene.clear()
        self.canvas.resetTransform()

        try:
            raw_item = sheet.get("raw_item", {})
            raw_ref = raw_item.get("raw_ref")
            if isinstance(raw_ref, str):
                raw_ref = db.document(raw_ref)

            item_data = raw_ref.get().to_dict() if raw_ref else {}
            if not item_data:
                raise ValueError("Could not fetch raw material data.")

            dummy = ManufacturingModule()
            cuts = sheet.get("cuts", [])
            subcat = sheet.get("raw_subcat", "").lower()

            dummy.item_dropdown.clear()
            dummy.item_dropdown.addItem(raw_item.get("name", "Unknown"), item_data)
            dummy.item_dropdown.setCurrentIndex(0)

            if "pipe" in subcat:
                segments = [c.get("height") for c in cuts if "height" in c]
                leftover = float(item_data.get("height", 0)) - sum(segments)
                if leftover > 0:
                    segments.append(leftover)
                dummy.draw_pipe_stack(segments)
            else:
                rectangles = []
                for c in cuts:
                    try:
                        length = float(c.get("length", 0))
                        width = float(c.get("width", 0))
                        length_str = c.get("length_raw", str(length))
                        width_str = c.get("width_raw", str(width))
                        rectangles.append((length, width, length_str, width_str))
                    except Exception as e:
                        print("Error parsing cut:", c, "|", e)
                sheet_w = float(item_data.get("width", 48))
                sheet_h = float(item_data.get("length", 96))
                dummy.sheet_tabs.setCurrentIndex(0)
                dummy.sheet_data[0] = {
                    "cuts": rectangles  # ensure proper labels reach draw_canvas
                }
                placements = dummy.place_rectangles(sheet_w, sheet_h, rectangles)
                dummy.draw_canvas(sheet_w, sheet_h, placements)

            self.scene = dummy.scene
            self.canvas.setScene(self.scene)

        except Exception as e:
            print("Draw error:", e)
            self.order_info.setHtml(f"<span style='color:red;'>Error drawing sheet: {str(e)}</span>")

        finally:
            loader.close()


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    win = ViewManufacturingWindow()
    win.show()
    sys.exit(app.exec_())