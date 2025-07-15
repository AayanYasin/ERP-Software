from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QHBoxLayout, QGraphicsTextItem, QGraphicsEllipseItem,
    QComboBox, QMessageBox, QTabWidget, QCheckBox, QSpinBox, QProgressDialog, QApplication
)
from PyQt5.QtGui import QBrush, QColor, QPen, QPainter, QFont, QTransform
from PyQt5.QtCore import Qt
from firebase.config import db
from uuid import uuid4
from firebase_admin import firestore
from fractions import Fraction
from collections import Counter
import re

class PannableGraphicsView(QGraphicsView):
    def __init__(self, scene=None):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self._drag_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos:
            delta = event.pos() - self._drag_pos
            self._drag_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ArrowCursor)
            self._drag_pos = None
        super().mouseReleaseEvent(event)



class ManufacturingModule(QWidget):
    def __init__(self, edit_data=None, doc_id=None):
        super().__init__()
        self.setWindowTitle("📏 Manufacturing Module")
        self.resize(1300, 800)

        self.edit_data = edit_data
        self.doc_id = doc_id

        self.zoom_level = 1
        self.sheet_data = {}
        self.products = []
        self.subcategories = []

        self.init_ui()
        self.load_subcategories()
        self.load_products()

        if self.edit_data:
            self.load_existing_order()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # ========== LEFT PANE ==========
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, 2)

        self.sheet_tabs = QTabWidget()
        
        self.sheet_tabs.currentChanged.connect(self.load_sheet_data)
        left_layout.addWidget(self.sheet_tabs)

        # Add/Remove Sheet Buttons
        sheet_btn_layout = QHBoxLayout()
        self.add_sheet_btn = QPushButton("➕ Add Sheet")
        self.remove_sheet_btn = QPushButton("➖ Remove Sheet")
        self.add_sheet_btn.clicked.connect(self.add_new_sheet)
        self.remove_sheet_btn.clicked.connect(self.remove_current_sheet)
        sheet_btn_layout.addWidget(self.add_sheet_btn)
        sheet_btn_layout.addWidget(self.remove_sheet_btn)
        left_layout.addLayout(sheet_btn_layout)

        # Raw material dropdowns
        self.subcategory_dropdown = QComboBox()
        self.subcategory_dropdown.currentIndexChanged.connect(self.load_items)
        self.item_dropdown = QComboBox()

        left_layout.addWidget(QLabel("Select Raw Material Subcategory:"))
        left_layout.addWidget(self.subcategory_dropdown)
        left_layout.addWidget(QLabel("Select Raw Material Item:"))
        left_layout.addWidget(self.item_dropdown)
        self.raw_qty_input = QLineEdit()
        left_layout.addWidget(QLabel("Enter Raw Material Quantity:"))
        left_layout.addWidget(self.raw_qty_input)

        # Cut sizes input
        self.cut_list = QListWidget()
        self.cut_list.itemClicked.connect(self.fill_cut_fields_from_selection)
        left_layout.addWidget(QLabel("Cut Sizes - Inch Only:"))
        left_layout.addWidget(self.cut_list)
        
        # Soot dropdowns
        self.length_soot = QComboBox()
        self.width_soot = QComboBox()

        # Add soot/fraction options
        soot_values = ["", "1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8"]
        self.length_soot.addItems(soot_values)
        self.width_soot.addItems(soot_values)

        cut_input_layout = QHBoxLayout()
        self.cut_length = QLineEdit()
        self.cut_width = QLineEdit()
        self.cut_qty = QLineEdit()
        self.cut_length.setPlaceholderText("Length")
        self.cut_width.setPlaceholderText("Width")
        self.cut_qty.setPlaceholderText("No.")
        self.add_cut_btn = QPushButton("Add Cut")
        self.remove_cut_btn = QPushButton("Remove Selected")
        self.add_cut_btn.clicked.connect(self.add_cut_size)
        self.remove_cut_btn.clicked.connect(self.remove_selected_cut)
        cut_input_layout.addWidget(self.cut_length)
        cut_input_layout.addWidget(self.length_soot)
        cut_input_layout.addWidget(self.cut_width)
        cut_input_layout.addWidget(self.width_soot)
        cut_input_layout.addWidget(self.cut_qty)
        cut_input_layout.addWidget(self.add_cut_btn)
        cut_input_layout.addWidget(self.remove_cut_btn)
        left_layout.addLayout(cut_input_layout)

        # Action buttons
        # self.auto_btn = QPushButton("⚙️ Auto Layout")
        # self.auto_btn.clicked.connect(self.auto_optimize_sheet) # Function to be defined
        # left_layout.addWidget(self.auto_btn)
        
        zoom_layout = QHBoxLayout()
        self.zoom_in_btn = QPushButton("➕ Zoom In")
        self.zoom_out_btn = QPushButton("➖ Zoom Out")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(self.zoom_in_btn)
        zoom_layout.addWidget(self.zoom_out_btn)
        left_layout.addLayout(zoom_layout)

        # Finished product list
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search Finished Products")
        self.search_input.textChanged.connect(self.filter_products)
        left_layout.addWidget(self.search_input)

        self.product_list = QListWidget()
        self.product_list.itemChanged.connect(self.save_product_selection)
        left_layout.addWidget(self.product_list)
        
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Manufacturing Notes")
        left_layout.addWidget(QLabel("📝 Notes"))
        left_layout.addWidget(self.notes)

        # Send to Manufacturing
        self.send_btn = QPushButton("🚀 Send for Manufacturing")
        self.send_btn.clicked.connect(self.send_to_manufacturing)
        left_layout.addWidget(self.send_btn)

        # ========== RIGHT PANE ==========
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout, 3)

        self.scene = QGraphicsScene()
        self.canvas = PannableGraphicsView(self.scene)
        self.canvas.setRenderHint(QPainter.Antialiasing)
        right_layout.addWidget(self.canvas)
        
        self.subcategory_dropdown.currentIndexChanged.connect(self.on_subcategory_changed)
        self.item_dropdown.currentIndexChanged.connect(self.on_item_changed)
        self.raw_qty_input.textChanged.connect(self.on_raw_qty_changed)
        self.item_dropdown.currentIndexChanged.connect(self.show_empty_raw)

        self.add_new_sheet()
        
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
    
    def populate_soot_dropdowns(self):
        soot_values = ["", "1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8"]
        self.length_soot.clear()
        self.length_soot.addItems(soot_values)

        self.width_soot.clear()
        self.width_soot.addItems(soot_values)
    
    def show_empty_raw(self):
        index = self.item_dropdown.currentIndex()
        if index < 0:
            return

        item = self.item_dropdown.itemData(index)
        if not item:
            return

        tab_index = self.sheet_tabs.currentIndex()
        if tab_index < 0:
            return

        cuts = self.sheet_data.get(tab_index, {}).get("cuts", [])
        
        if cuts:
            self.simulate_cutting()
            return

        # No cuts: draw empty pipe or sheet
        subcat = self.subcategory_dropdown.currentText().lower()

        def to_inches(val, unit):
            unit = unit.lower()
            if unit == 'ft':
                return float(val) * 12
            elif unit == 'mm':
                return float(val) / 25.4
            return float(val)

        if "pipe" in subcat:
            height = to_inches(item.get("height", 0), item.get("height_unit", "inch"))
            if height <= 0:
                return
            self.draw_pipe_stack([height])  # Blank full-height pipe
        else:
            sheet_w = to_inches(item.get("width", 0), item.get("width_unit", "inch"))
            sheet_h = to_inches(item.get("length", 0), item.get("length_unit", "inch"))
            self.draw_canvas(sheet_w, sheet_h, [])  # Blank sheet
        
        self.populate_soot_dropdowns()
        
    def load_existing_order(self):
        loader = self.show_loader(self, "Loading", "Loading Order Data...")
        sheets = self.edit_data.get("sheets", [])
        self.sheet_tabs.clear()
        self.sheet_data.clear()

        for i, sheet in enumerate(sheets):
            self.sheet_tabs.addTab(QWidget(), f"Sheet {i + 1}")
            processed = {
                "raw_subcat": sheet.get("raw_subcat", ""),
                "raw_qty": sheet.get("raw_qty", ""),
                "raw_item": {},
                "cuts": [],
                "products": []
            }

            # Reconstruct raw_item
            raw_item = sheet.get("raw_item", {})
            if isinstance(raw_item, dict):
                processed["raw_item"] = {
                    "id": raw_item.get("raw_ref").id if raw_item.get("raw_ref") else "",
                    "name": raw_item.get("name", "")
                }

            # Cuts
            for cut in sheet.get("cuts", []):
                if "length" in cut and "width" in cut:
                    processed["cuts"].append((cut["length"], cut["width"], cut["length_raw"], cut["width_raw"]))
                elif "height" in cut:
                    processed["cuts"].append((cut["height"], cut["height_raw"]))

            # Products
            for prod in sheet.get("products", []):
                ref = prod.get("product_ref")
                processed["products"].append({
                    "id": ref.id if ref else "",
                    "name": prod.get("name", ""),
                    "qty": prod.get("qty", 1)
                })

            self.sheet_data[i] = processed

        # Reload UI for first sheet
        loader.close()
        self.sheet_tabs.setCurrentIndex(0)
        self.load_sheet_data()
        
    def fill_cut_fields_from_selection(self, item):
        text = item.text().lower()  # e.g., "24 3/8 x 12 1/2" or "24 height"
        try:
            if "x" in text:
                length_str, width_str = [s.strip() for s in text.split('x')]

                def parse_soot(value_str):
                    parts = value_str.strip().split()
                    inch = parts[0]
                    soot = parts[1] if len(parts) > 1 else "0"
                    return inch, soot

                l_inch, l_soot = parse_soot(length_str)
                w_inch, w_soot = parse_soot(width_str)

                self.cut_length.setText(l_inch)
                self.length_soot.setCurrentText(l_soot)
                self.cut_width.setText(w_inch)
                self.width_soot.setCurrentText(w_soot)
            elif "height" in text:
                value = text.replace("height", "").strip()
                parts = value.split()
                inch = parts[0]
                soot = parts[1] if len(parts) > 1 else "0"
                self.cut_length.setText(inch)
                self.length_soot.setCurrentText(soot)
                self.cut_width.clear()
                self.width_soot.setCurrentIndex(0)
        except Exception as e:
            print("Parse error in fill_cut_fields_from_selection:", e)



    def add_new_sheet(self):
        index = self.sheet_tabs.count()
        self.sheet_tabs.addTab(QWidget(), f"Sheet {index+1}")
        self.sheet_tabs.setCurrentIndex(index)
        self.sheet_data[index] = {"products": [], "cuts": []}
        self.cut_list.clear()
        self.filter_products()

    def remove_current_sheet(self):
        index = self.sheet_tabs.currentIndex()
        if index >= 0:
            self.sheet_tabs.removeTab(index)
            if index in self.sheet_data:
                del self.sheet_data[index]

            # Shift all sheet_data keys down after removal
            self.sheet_data = {
                new_i: self.sheet_data[old_i]
                for new_i, old_i in enumerate(sorted(self.sheet_data.keys()))
            }

            # After deletion, refresh cut list for new selected tab
            self.cut_list.clear()
            self.filter_products()
            self.load_sheet_data()

    def load_sheet_data(self):
        loader = self.show_loader(self, "Loading", "Switching sheets...")
        index = self.sheet_tabs.currentIndex()
        if index < 0:
            return
        sheet = self.sheet_data.get(index, {})
        # print(sheet)

        # ---- Block signals to prevent on_*_changed interference ----
        self.subcategory_dropdown.blockSignals(True)
        self.item_dropdown.blockSignals(True)
        self.raw_qty_input.blockSignals(True)

        # Restore raw subcategory
        if sheet.get("raw_subcat"):
            idx = self.subcategory_dropdown.findText(sheet["raw_subcat"])
            self.subcategory_dropdown.setCurrentIndex(idx if idx != -1 else 0)
        else:
            self.subcategory_dropdown.setCurrentIndex(0)

        # Restore raw item
        self.load_items()
        if sheet.get("raw_item"):
            for i in range(self.item_dropdown.count()):
                if self.item_dropdown.itemData(i) == sheet["raw_item"]:
                    self.item_dropdown.setCurrentIndex(i)
                    break

        # Restore raw qty
        self.raw_qty_input.setText(sheet.get("raw_qty", ""))

        # ---- Re-enable signals now ----
        self.subcategory_dropdown.blockSignals(False)
        self.item_dropdown.blockSignals(False)
        self.raw_qty_input.blockSignals(False)

        # Reload cuts and products
        self.cut_list.clear()
        self.product_list.blockSignals(True)
        self.filter_products()
        self.product_list.blockSignals(False)

        cuts = sheet.get("cuts", [])
        for c in cuts:
            if isinstance(c, (list, tuple)):
                if len(c) == 4:
                    # Sheet cut
                    self.cut_list.addItem(f"{c[2]} x {c[3]}")
                elif len(c) == 2:
                    # Pipe cut
                    self.cut_list.addItem(str(c[1]))  # height string
                elif len(c) == 1:
                    self.cut_list.addItem(str(c[0]))  # fallback
            elif isinstance(c, dict):
                if "length" in c and "width" in c:
                    self.cut_list.addItem(f"{c['length']} x {c['width']}")
                elif "height" in c:
                    self.cut_list.addItem(c['height'])
            
        self.toggle_pipe_mode()
        loader.close()



    def save_product_selection(self):
        index = self.sheet_tabs.currentIndex()
        selected = []

        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            widget = self.product_list.itemWidget(item)
            if not widget:
                continue

            checkbox = widget.layout().itemAt(0).widget()
            spinbox = widget.layout().itemAt(1).widget()

            if checkbox.isChecked():
                data = checkbox.product_data.copy()
                data["qty"] = spinbox.value()
                selected.append(data)

        self.sheet_data[index]["products"] = selected

    def filter_products(self):
        keyword = self.search_input.text().lower()
        self.product_list.clear()
        index = self.sheet_tabs.currentIndex()
        current_products = self.sheet_data.get(index, {}).get("products", [])
        current_ids = [p["id"] for p in current_products]
        current_qtys = {p["id"]: p.get("qty", 1) for p in current_products}

        for p in self.products:
            label_text = f"{p['item_code']} - {p['name']} - {p['length']}{p['length_unit']} x {p['width']}{p['width_unit']} x {p['height']}{p['height_unit']}"
            if keyword in label_text.lower():
                container = QWidget()
                layout = QHBoxLayout()
                layout.setContentsMargins(0, 0, 0, 0)

                checkbox = QCheckBox(label_text)
                checkbox.setChecked(p["id"] in current_ids)

                spinbox = QSpinBox()
                spinbox.setRange(1, 999)
                spinbox.setValue(current_qtys.get(p["id"], 1))

                # Save reference to update logic
                checkbox.stateChanged.connect(self.save_product_selection)
                spinbox.valueChanged.connect(self.save_product_selection)

                checkbox.product_data = p
                checkbox.qty_spinbox = spinbox
                spinbox.product_id = p["id"]

                layout.addWidget(checkbox)
                layout.addWidget(spinbox)
                container.setLayout(layout)

                item = QListWidgetItem()
                item.setSizeHint(container.sizeHint())
                self.product_list.addItem(item)
                self.product_list.setItemWidget(item, container)


    def add_cut_size(self):
        try:
            is_pipe = self.is_pipe_selected()
            qty = int(self.cut_qty.text()) if hasattr(self, "cut_qty") and self.cut_qty.text().isdigit() and int(self.cut_qty.text()) > 0 else 1
            index = self.sheet_tabs.currentIndex()

            if is_pipe:
                h = float(self.cut_length.text())
                h_str = self.cut_length.text()

                if self.length_soot.currentText():
                    frac = self.length_soot.currentText()
                    h += float(Fraction(frac))
                    h_str += f" {frac}"

                label = f"{h_str}\""
                for _ in range(qty):
                    self.cut_list.addItem(label)
                    if index in self.sheet_data:
                        self.sheet_data[index]["cuts"].append((h, h_str))

                self.cut_length.clear()
                self.length_soot.setCurrentIndex(0)

            else:
                try:
                    l = float(self.cut_length.text())
                    w = float(self.cut_width.text())
                    l_str = self.cut_length.text()
                    w_str = self.cut_width.text()

                    if self.length_soot.currentText():
                        frac = self.length_soot.currentText()
                        l += float(Fraction(frac))
                        l_str += f" {frac}"

                    if self.width_soot.currentText():
                        frac = self.width_soot.currentText()
                        w += float(Fraction(frac))
                        w_str += f" {frac}"

                    label = f"{l_str} x {w_str}"
                    for _ in range(qty):
                        self.cut_list.addItem(label)
                        if index in self.sheet_data:
                            self.sheet_data[index]["cuts"].append((l, w, l_str, w_str))

                    self.cut_length.clear()
                    self.cut_width.clear()
                    self.length_soot.setCurrentIndex(0)
                    self.width_soot.setCurrentIndex(0)
                except Exception as e:
                    QMessageBox.warning(self, "Invalid Input", f"Error parsing input: {str(e)}")
            if hasattr(self, "cut_qty"):
                self.cut_qty.clear()

            self.simulate_cutting()

        except Exception as e:
            QMessageBox.warning(self, "Invalid Input", f"Error parsing input: {str(e)}")


    def remove_selected_cut(self):
        row = self.cut_list.currentRow()
        if row >= 0:
            self.cut_list.takeItem(row)
            index = self.sheet_tabs.currentIndex()
            if index in self.sheet_data:
                try:
                    del self.sheet_data[index]["cuts"][row]

                    # ✅ Clear input fields
                    self.cut_length.clear()
                    self.cut_width.clear()
                    self.length_soot.clear()
                    self.width_soot.clear()

                    # ✅ Simulate or show blank if no cuts left
                    if self.sheet_data[index]["cuts"]:
                        self.simulate_cutting()
                    else:
                        self.show_empty_raw()

                except IndexError:
                    pass

    def zoom_in(self):
        self.canvas.scale(1.25, 1.25)

    def zoom_out(self):
        self.canvas.scale(0.8, 0.8)
        
    def toggle_pipe_mode(self):
        if self.is_pipe_selected():
            self.cut_width.setDisabled(True)
            self.width_soot.setDisabled(True)
            # self.auto_btn.setDisabled(True)
            self.cut_width.setPlaceholderText("Disabled for pipe")

            self.cut_length.setPlaceholderText("Height")
        else:
            self.cut_width.setDisabled(False)
            self.width_soot.setDisabled(False)
            # self.auto_btn.setDisabled(False)
            self.cut_width.setPlaceholderText("Width")
            self.cut_length.setPlaceholderText("Length")

    def simulate_cutting(self):
        index = self.item_dropdown.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "No Sheet Selected", "Please select a raw material item.")
            return

        item_data = self.item_dropdown.itemData(index)  # ✅ Define early

        if self.is_pipe_selected():
            self.simulate_pipe_cutting(item_data)
            return

        try:
            raw_length = float(item_data.get("length", 0))
            raw_width = float(item_data.get("width", 0))
            length_unit = item_data.get("length_unit", "inch").lower()
            width_unit = item_data.get("width_unit", "inch").lower()

            def convert_to_inches(value, unit):
                if unit == "ft":
                    return value * 12
                elif unit == "mm":
                    return value / 25.4
                return value  # already inch

            sheet_w = convert_to_inches(raw_width, width_unit)
            sheet_h = convert_to_inches(raw_length, length_unit)

            cuts = self.sheet_data.get(self.sheet_tabs.currentIndex(), {}).get("cuts", [])
            placements = self.place_rectangles(sheet_w, sheet_h, cuts)
            if not placements:
                return
            self.draw_canvas(sheet_w, sheet_h, placements)

        except Exception as e:
            print("Simulation error:", e)


    def draw_canvas(self, sheet_w, sheet_h, rects):
        self.scene.clear()
        self.canvas.resetTransform()

        canvas_h = 700
        scale = canvas_h / sheet_h
        canvas_w = sheet_w * scale

        # Subtle background grid every 6 inches (horizontal + vertical)
        grid_pen = QPen(QColor("#ecf0f1"), 1, Qt.DotLine)
        for y in range(0, int(sheet_h) + 1, 6):
            y_scaled = y * scale
            self.scene.addLine(0, y_scaled, canvas_w, y_scaled, grid_pen)
        for x in range(0, int(sheet_w) + 1, 6):
            x_scaled = x * scale
            self.scene.addLine(x_scaled, 0, x_scaled, canvas_h, grid_pen)

        # Drop shadow
        shadow = QGraphicsRectItem(4, 4, canvas_w, canvas_h)
        shadow.setBrush(QBrush(QColor(0, 0, 0, 30)))  # soft shadow
        shadow.setPen(QPen(Qt.NoPen))
        self.scene.addItem(shadow)

        # Main sheet background
        sheet_rect = QGraphicsRectItem(0, 0, canvas_w, canvas_h)
        sheet_rect.setBrush(QBrush(QColor("#dfe6e9")))
        sheet_rect.setPen(QPen(Qt.black, 2))
        self.scene.addItem(sheet_rect)

        used_area = 0
        index = self.sheet_tabs.currentIndex()
        cuts_with_labels = self.sheet_data.get(index, {}).get("cuts", [])

        for x, y, w, h in rects:
            used_area += w * h
            rect = QGraphicsRectItem(x * scale, y * scale, w * scale, h * scale)
            rect.setBrush(QBrush(QColor("#74b9ff")))
            rect.setPen(QPen(Qt.darkBlue, 1))
            self.scene.addItem(rect)

            # Match original cut label
            original_label = f"{w:.2f} x {h:.2f} inch"
            for (lw, lh, lw_str, lh_str) in cuts_with_labels:
                if abs(lw - w) < 0.01 and abs(lh - h) < 0.01:
                    original_label = f"{lw_str} x {lh_str} inch"
                    break

            min_dim = min(w, h)
            font_size = max(6, min(14, int(min_dim * scale * 0.2)))

            label = QGraphicsTextItem(original_label)
            font = QFont("Arial", font_size)
            label.setFont(font)
            label.setDefaultTextColor(Qt.black)

            if h > w:
                label.setTransform(QTransform().rotate(-90))
                label.setPos((x + w / 2) * scale - 5, (y + h / 2) * scale + 10)
            else:
                label.setPos(x * scale + 4, y * scale + 4)

            self.scene.addItem(label)

        # Summary info
        waste_area = sheet_w * sheet_h - used_area
        info = QGraphicsTextItem(
            f"Sheet: {int(sheet_w)} x {int(sheet_h)} inch\n"
            f"Used: {int(used_area)} inch²\n"
            f"Waste: {int(waste_area)} inch²"
        )
        info.setDefaultTextColor(Qt.darkRed)
        info.setFont(QFont("Arial", 9))
        info.setPos(10, sheet_h * scale + 10)
        self.scene.addItem(info)

        # Title
        title = QGraphicsTextItem("Sheet Cutting Visualization")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setDefaultTextColor(Qt.darkBlue)
        title.setPos(10, -30)
        self.scene.addItem(title)

        self.canvas.setSceneRect(0, -40, canvas_w + 100, sheet_h * scale + 100)
        
        
    def auto_optimize_sheet(self):
        try:
            item_data = self.item_dropdown.currentData()
            if not item_data:
                QMessageBox.warning(self, "No Sheet", "Please select a raw material.")
                return

            index = self.sheet_tabs.currentIndex()
            cuts = self.sheet_data.get(index, {}).get("cuts", [])
            if not cuts:
                QMessageBox.warning(self, "No Cuts", "No cut sizes entered.")
                return

            def parse_inches(val):
                try:
                    if isinstance(val, (float, int)):
                        return float(val)
                    if ' ' in val:
                        whole, frac = val.strip().split(' ')
                        num, denom = frac.split('/')
                        return int(whole) + int(num) / int(denom)
                    elif '/' in val:
                        num, denom = val.strip().split('/')
                        return int(num) / int(denom)
                    return float(val)
                except Exception:
                    return 0.0

            def find_best_row(pieces, max_width):
                from itertools import combinations, product
                best_combo = []
                best_total = 0.0
                for r in range(1, len(pieces) + 1):
                    for combo in combinations(pieces, r):
                        for orientation in product([0, 1], repeat=len(combo)):
                            total = 0.0
                            row = []
                            valid = True
                            for i, p in enumerate(combo):
                                if orientation[i] == 0:
                                    w = p['length']
                                    h = p['width']
                                    l_str, w_str = p['length_str'], p['width_str']
                                else:
                                    w = p['width']
                                    h = p['length']
                                    l_str, w_str = p['width_str'], p['length_str']
                                if total + w > max_width:
                                    valid = False
                                    break
                                row.append((w, h, l_str, w_str))
                                total += w
                            if valid and total > best_total:
                                best_total = total
                                best_combo = (combo, row)
                return best_combo

            def optimize_layout(sheet_w, sheet_h, cuts):
                parsed = []
                for idx, c in enumerate(cuts):
                    l = parse_inches(c[0])
                    w = parse_inches(c[1])
                    parsed.append({
                        'id': idx,
                        'length': l,
                        'width': w,
                        'length_str': c[2],
                        'width_str': c[3]
                    })

                y_cursor = 0
                layout = []
                while parsed:
                    result = find_best_row(parsed, sheet_w)
                    if not result:
                        break
                    used_items, row = result
                    row_height = max(h for _, h, _, _ in row)
                    if y_cursor + row_height > sheet_h:
                        break
                    layout.extend(row)
                    for item in used_items:
                        parsed.remove(item)
                    y_cursor += row_height
                return layout

            # Convert sheet dimensions to inches
            def to_inches(val, unit):
                unit = unit.lower()
                if unit == 'ft':
                    return float(val) * 12
                elif unit == 'mm':
                    return float(val) / 25.4
                return float(val)

            sheet_w = to_inches(item_data.get("width", 0), item_data.get("width_unit", "inch"))
            sheet_h = to_inches(item_data.get("length", 0), item_data.get("length_unit", "inch"))

            optimized = optimize_layout(sheet_w, sheet_h, cuts)

            # Update internal sheet_data and UI
            self.sheet_data[index]["cuts"] = [
                (round(w, 4), round(h, 4), l_str, w_str) for (w, h, l_str, w_str) in optimized
            ]

            self.cut_list.clear()
            for (w, h, l_str, w_str) in optimized:
                self.cut_list.addItem(f"{l_str} x {w_str}")

            # QMessageBox.information(self, "Optimized", "Cut sizes reordered for best fit.")
            
            self.simulate_cutting()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Optimization failed:\n{str(e)}")



        
    def place_rectangles(self, sheet_w, sheet_h, rectangles):
        used = []
        current_y = 0
        row_height = 0
        current_x = 0

        for rect in rectangles:
            if len(rect) == 4:
                w, h = rect[0], rect[1]
            elif len(rect) == 3:
                w, h = rect[0], rect[1]
            else:
                w, h = rect

            # If current row has enough horizontal space
            if current_x + w <= sheet_w:
                used.append((current_x, current_y, w, h))
                current_x += w
                row_height = max(row_height, h)
            else:
                # Move to next row
                current_y += row_height
                if current_y + h > sheet_h:
                    loader = self.show_loader(self, "Size Error", f"Not enough space for cut {w} x {h} inch, Trying to Auto Adjust Sheet...")
                    self.auto_optimize_sheet()
                    loader.close()
                    return
                # Start new row
                current_x = 0
                row_height = h
                used.append((current_x, current_y, w, h))
                current_x += w

        return used



    def load_subcategories(self):
        self.subcategories = []
        self.subcategory_dropdown.clear()
        self.subcategory_dropdown.addItem("Select Raw Material Type")
        try:
            raw_main_id = None
            for doc in db.collection("product_main_categories").stream():
                if doc.to_dict().get("name") == "Raw Material":
                    raw_main_id = doc.id
                    break
            if not raw_main_id:
                return
            for doc in db.collection("product_sub_categories").where("main_id", "==", raw_main_id).stream():
                data = doc.to_dict()
                data["id"] = doc.id
                self.subcategories.append(data)
                self.subcategory_dropdown.addItem(data.get("name", "Unnamed"))
        except Exception:
            pass

    def load_items(self):
        self.toggle_pipe_mode()
        subcat_name = self.subcategory_dropdown.currentText()
        if subcat_name == "Select Raw Material Type":
            self.item_dropdown.clear()
            return

        subcat_doc = next((s for s in self.subcategories if s.get("name") == subcat_name), None)
        if not subcat_doc:
            return

        subcat_id = subcat_doc["id"]
        self.items = []
        self.item_dropdown.clear()

        try:
            query = db.collection("products").where("sub_id", "==", subcat_id)
            for doc in query.stream():
                data = doc.to_dict()
                data["id"] = doc.id
                label = f"{data['item_code']} - {data['name']} ({data.get('length', 0)} {data.get('length_unit', 0)} x {data.get('width', 0)} {data.get('width_unit', 0)})"
                self.items.append(data)
                self.item_dropdown.addItem(label, data)
        except Exception:
            pass
        

    def load_products(self):
        self.products = []
        loader = self.show_loader(self, "Loading", "Fetching finished products...")
        try:
            finished_main_id = None
            for doc in db.collection("product_main_categories").stream():
                if doc.to_dict().get("name") == "Finished Goods":
                    finished_main_id = doc.id
                    break
            if not finished_main_id:
                return

            finished_sub_ids = []
            for doc in db.collection("product_sub_categories").where("main_id", "==", finished_main_id).stream():
                finished_sub_ids.append(doc.id)

            for doc in db.collection("products").stream():
                data = doc.to_dict()
                data["id"] = doc.id
                if data.get("sub_id") in finished_sub_ids and data.get("color") == "No Color":
                    self.products.append(data)

            self.filter_products()
        except Exception:
            pass
        finally:
            loader.close()
        
    def on_subcategory_changed(self):
        index = self.sheet_tabs.currentIndex()
        if index < 0:
            return

        selected = self.subcategory_dropdown.currentText()
        if selected != self.sheet_data[index].get("raw_subcat"):
            self.sheet_data[index]["raw_subcat"] = selected
        self.load_items()

        
    def on_item_changed(self):
        index = self.sheet_tabs.currentIndex()
        if index < 0:
            return

        if index not in self.sheet_data:
            self.sheet_data[index] = {"products": [], "cuts": []}

        item = self.item_dropdown.itemData(self.item_dropdown.currentIndex())
        if item != self.sheet_data[index].get("raw_item"):
            self.sheet_data[index]["raw_item"] = item
            


    def on_raw_qty_changed(self):
        index = self.sheet_tabs.currentIndex()
        if index < 0:
            return

        new_qty = self.raw_qty_input.text()
        current_qty = self.sheet_data.get(index, {}).get("raw_qty", "")

        if new_qty != current_qty:
            self.sheet_data[index]["raw_qty"] = new_qty

    def is_pipe_selected(self):
        subcat_name = self.subcategory_dropdown.currentText().lower()
        return "pipe" in subcat_name or "tube" in subcat_name

    def simulate_pipe_cutting(self, item_data):
        try:
            raw_height = float(item_data.get("height", 0))
            height_unit = item_data.get("height_unit", "ft").lower()

            def convert_to_inches(val, unit):
                if unit == "ft":
                    return val * 12
                elif unit == "mm":
                    return val / 25.4
                return val

            pipe_h = convert_to_inches(raw_height, height_unit)

            cuts = self.sheet_data.get(self.sheet_tabs.currentIndex(), {}).get("cuts", [])
            cut_heights = []

            for c in cuts:
                try:
                    if isinstance(c, (tuple, list)):
                        if len(c) >= 1:
                            val = str(c[0])
                        else:
                            continue
                    else:
                        val = str(c)

                    h_inch = self.parse_inches(val)  # always in inches now
                    cut_heights.append(h_inch)
                except Exception as e:
                    print("Cut parse error:", c, e)
                    continue

            segments = []
            used = 0
            for h in cut_heights:
                if used + h > pipe_h:
                    QMessageBox.warning(self, "Overcut", "Cut exceeds pipe length.")
                    break
                segments.append(h)
                used += h

            remaining = pipe_h - used
            if remaining > 0:
                segments.append(remaining)

            self.draw_pipe_stack(segments)

        except Exception as e:
            print("Pipe simulation error:", e)

            
    def draw_pipe_stack(self, segments):
        self.scene.clear()
        self.canvas.resetTransform()

        try:
            index = self.item_dropdown.currentIndex()
            item_data = self.item_dropdown.itemData(index)

            pipe_length = float(item_data.get("height", 0))  # pipe height = vertical
            pipe_diameter = float(item_data.get("width", 0))  # pipe diameter = horizontal
            length_unit = item_data.get("height_unit", "ft").lower()
            diameter_unit = item_data.get("width_unit", "inch").lower()

            def convert_to_inches(val, unit):
                if unit == "ft":
                    return val * 12
                elif unit == "mm":
                    return val / 25.4
                return val

            pipe_length_in = convert_to_inches(pipe_length, length_unit)
            pipe_diameter_in = convert_to_inches(pipe_diameter, diameter_unit)

            # Canvas size and scaling
            canvas_h = 700
            canvas_w = 400
            scale = canvas_h / pipe_length_in

            visual_length = pipe_length_in * scale
            visual_diameter = pipe_diameter_in * scale
            x_offset = 120
            y_offset = 50

            # Optional: Background Grid
            grid_pen = QPen(QColor("#dcdde1"), 1, Qt.DotLine)
            for i in range(0, int(pipe_length_in) + 1, 6):  # every 6 inch
                y = y_offset + i * scale
                self.scene.addLine(0, y, canvas_w, y, grid_pen)

            # Pipe Shadow
            shadow = QGraphicsRectItem(x_offset + 4, y_offset + 4, visual_diameter, visual_length)
            shadow.setBrush(QBrush(QColor(0, 0, 0, 40)))
            shadow.setPen(QPen(Qt.NoPen))
            self.scene.addItem(shadow)

            # Pipe body
            pipe_body = QGraphicsRectItem(x_offset, y_offset, visual_diameter, visual_length)
            pipe_body.setBrush(QBrush(QColor("#dfe6e9")))
            pipe_body.setPen(QPen(Qt.black, 2))
            self.scene.addItem(pipe_body)

            # Pipe caps (ellipse top and bottom) with enhanced clarity
            cap_color = QColor("#b2bec3")
            cap_pen = QPen(Qt.black)
            cap_pen.setWidth(2) 

            # Add a light gradient brush to give some depth
            pipe_gradient = QBrush(QColor("#a0a0a0"))

            # Top cap
            top_cap = QGraphicsEllipseItem(
                x_offset, y_offset - visual_diameter / 2, visual_diameter, visual_diameter
            )
            top_cap.setBrush(QBrush(cap_color))
            top_cap.setPen(cap_pen)

            # Bottom cap
            bottom_cap = QGraphicsEllipseItem(
                x_offset, y_offset + visual_length - visual_diameter / 2, visual_diameter, visual_diameter
            )
            bottom_cap.setBrush(QBrush(cap_color))
            bottom_cap.setPen(cap_pen)

            self.scene.addItem(top_cap)
            self.scene.addItem(bottom_cap)

            # Draw segments
            y_cursor = y_offset
            used_total = 0
            segment_colors = [
                "#00a8ff", "#9c88ff", "#fbc531", "#4cd137", "#e84118",
                "#00cec9", "#fd79a8", "#e17055", "#fab1a0", "#6c5ce7"
            ]
            
            def to_fraction_str(val):
                whole = int(val)
                frac = round(val - whole, 3)
                soot_map = {
                    0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2",
                    0.625: "5/8", 0.75: "3/4", 0.875: "7/8"
                }
                soot_str = soot_map.get(frac, "")
                return f"{whole} {soot_str}".strip() + '"'

            for i, seg in enumerate(segments):
                seg_px = seg * scale
                color_hex = segment_colors[i % len(segment_colors)]
                color = QColor(color_hex)

                cut = QGraphicsRectItem(x_offset, y_cursor, visual_diameter, seg_px)
                cut.setBrush(QBrush(color))
                cut.setPen(QPen(Qt.darkGray, 1))
                cut.setZValue(1)
                self.scene.addItem(cut)

                # Cut label inside segment
                cut_label = QGraphicsTextItem(f"{round(seg/12, 2)} ft")
                cut_label.setDefaultTextColor(Qt.white)
                cut_label.setFont(QFont("Arial", 10, QFont.Bold))
                cut_label.setZValue(2)
                cut_label.setPos(x_offset + 10, y_cursor + seg_px / 2 - 10)
                self.scene.addItem(cut_label)

                # Left-hand dimension line and arrow
                arrow_x = x_offset - 25  # space to the left of the pipe
                line_top = y_cursor
                line_bottom = y_cursor + seg_px

                # Draw vertical line
                dimension_line = self.scene.addLine(arrow_x, line_top, arrow_x, line_bottom, QPen(Qt.black, 1))

                # Arrows at top and bottom
                arrow_size = 5
                self.scene.addLine(arrow_x - arrow_size, line_top, arrow_x + arrow_size, line_top, QPen(Qt.black, 1))
                self.scene.addLine(arrow_x - arrow_size, line_bottom, arrow_x + arrow_size, line_bottom, QPen(Qt.black, 1))

                # Dimension text (e.g., "48 Inch")
                inch_str = to_fraction_str(seg)
                dimension_text = QGraphicsTextItem(inch_str)
                dimension_text.setFont(QFont("Arial", 9))
                dimension_text.setDefaultTextColor(Qt.black)
                dimension_text.setPos(arrow_x - 40, y_cursor + seg_px / 2 - 8)
                self.scene.addItem(dimension_text)


                y_cursor += seg_px
                used_total += seg if i < len(segments) - 1 else 0

            pipe_qty = 1
            try:
                pipe_qty = int(self.raw_qty_input.text())
            except:
                pass

            # Include ALL segments (cuts + leftover) for pipe tally
            cut_counts = Counter()
            for seg in segments:
                cut_label = to_fraction_str(seg)
                cut_counts[cut_label] += 1

            cut_only_count = len(segments) - 1 if len(segments) > 1 else 0
            pipe_total_count = len(segments)  # now includes leftover as pipe

            total_height_str = to_fraction_str(pipe_length_in)
            cut_summary = f"Total Cuts: {cut_only_count} (Single Pipe) | {cut_only_count * pipe_qty} (Total)"
            pipe_summary = f"Total Pipes: {pipe_total_count * pipe_qty}"

            size_lines = [
                f'{label}: {count * pipe_qty}'
                for label, count in sorted(cut_counts.items(), key=lambda x: self.parse_inches(x[0]))
            ]

            legend_text = f"Total Height: {total_height_str}\n{cut_summary}\n–\n{pipe_summary}\n" + "\n".join(size_lines)

            legend = QGraphicsTextItem(legend_text)
            legend.setFont(QFont("Arial", 10))
            legend.setDefaultTextColor(Qt.black)
            legend.setPos(x_offset + visual_diameter + 30, y_offset + 20)
            self.scene.addItem(legend)

            title = QGraphicsTextItem("Pipe Cutting Visualization")
            title.setFont(QFont("Arial", 14, QFont.Bold))
            title.setDefaultTextColor(Qt.darkBlue)
            title.setPos(20, 5)
            self.scene.addItem(title)

            self.canvas.setSceneRect(0, 0, canvas_w, y_offset + visual_length + 80)

        except Exception as e:
            print("Enhanced pipe view error:", e)


    def parse_inches(self, val):
        """
        Converts strings like '60"', '60.25', '60 1/4"', or '1/2' to float inches.
        """
        import re
        from fractions import Fraction

        val = val.replace('"', '').replace('inch', '').strip()

        # First, try to directly parse float (handles "60", "60.0", "48.25")
        try:
            return float(val)
        except ValueError:
            pass

        # Try fraction formats: "60 1/4" or just "1/4"
        match = re.match(r"^(\d+)?(?:\s+)?(\d+/\d+)$", val)
        if match:
            whole = int(match.group(1)) if match.group(1) else 0
            frac = Fraction(match.group(2))
            return float(whole + frac)

        # fallback
        print(f"Invalid inch input: '{val}'")
        return 0
    
    
    def send_to_manufacturing(self):
        batches = []

        for index, sheet in self.sheet_data.items():
            # Prepare raw item
            raw_item = sheet.get("raw_item", {})
            raw_ref = db.collection("products").document(raw_item.get("id", ""))
            if "length" in raw_item and "width" in raw_item and "height" in raw_item:
                length = f'{raw_item.get("length", 0)} {raw_item.get("length_unit", "")}'
                width = f'{raw_item.get("width", 0)} {raw_item.get("width_unit", "")}'
                height = f'{raw_item.get("height", 0)} {raw_item.get("height_unit", "")}'
                raw_name = f"{raw_item.get('item_code', '')} - {raw_item.get('name', '')} - {length} x {width} x {height}"
            else:
                raw_name = raw_item.get("name", "Unknown")


            batch = {
                "raw_subcat": sheet.get("raw_subcat", ""),
                "raw_qty": sheet.get("raw_qty", ""),
                "raw_item": {
                    "raw_ref": raw_ref,
                    "name": raw_name
                },
                "cuts": [],
                "products": []
            }

            # CUTS (converted to dicts)
            for cut in sheet.get("cuts", []):
                if isinstance(cut, (list, tuple)):
                    if len(cut) == 4:
                        batch["cuts"].append({
                            "length": cut[0],
                            "width": cut[1],
                            "length_raw": cut[2],
                            "width_raw": cut[3]
                        })
                    elif len(cut) == 2:
                        batch["cuts"].append({
                            "height": cut[0],
                            "height_raw": cut[1]
                        })

            # PRODUCTS (with reference + display name)
            for p in sheet.get("products", []):
                product_ref = db.collection("products").document(p["id"])
                if "length" in p and "width" in p and "height" in p:
                    length = f'{p.get("length", 0)} {p.get("length_unit", "")}'
                    width = f'{p.get("width", 0)} {p.get("width_unit", "")}'
                    height = f'{p.get("height", 0)} {p.get("height_unit", "")}'
                    name = f"{p.get('item_code', '')} - {p.get('name', '')} - {length} x {width} x {height}"
                else:
                    name = p.get("name", "Unknown")

                batch["products"].append({
                    "product_ref": product_ref,
                    "name": name,
                    "qty": p.get("qty", 1)
                })

            batches.append(batch)

        # 🔄 Save or update based on edit mode
        order_payload = {
            "sheets": batches,
            "status": "In Progress" if self.edit_data else "Pending",
            "created_at": firestore.SERVER_TIMESTAMP
        }

        loader = self.show_loader(self, "Sending Order", "Please wait while the order is being submitted...")
        try:
            if self.doc_id:
                db.collection("manufacturing_orders").document(self.doc_id).update(order_payload)
                QMessageBox.information(self, "Updated", "Manufacturing order updated successfully.")
            else:
                db.collection("manufacturing_orders").add(order_payload)
                QMessageBox.information(self, "Created", "Manufacturing order saved successfully.")
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save manufacturing order: {str(e)}")
        finally:
            loader.close()

# ADD LOADERS
# ADD RIGHTS
# CORRECT RAW MATERIAL INVENTORY LOGIC