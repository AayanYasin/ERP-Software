from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QHBoxLayout, QGraphicsTextItem, QGraphicsEllipseItem,
    QComboBox, QMessageBox, QTabWidget, QCheckBox, QSpinBox, QProgressDialog, QApplication, QGraphicsLineItem, QSizePolicy
)
from PyQt5.QtGui import QBrush, QColor, QPen, QPainter, QFont, QTransform
from PyQt5.QtCore import Qt
from firebase.config import db
from uuid import uuid4
from firebase_admin import firestore
from fractions import Fraction
from collections import Counter
from math import ceil
from itertools import permutations
from collections import defaultdict

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
        
        item_row = QHBoxLayout()

        self.item_dropdown = QComboBox()
        item_row.addWidget(self.item_dropdown, stretch=1)

        self.refresh_qty_button = QPushButton("🔄 Refresh")
        self.refresh_qty_button.setFixedWidth(70)  # This line controls the button width
        self.refresh_qty_button.clicked.connect(self.refresh_raw_quantities)
        item_row.addWidget(self.refresh_qty_button)

        left_layout.addLayout(item_row)

        # Create the raw_qty_input field first
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
        self.cut_length.setPlaceholderText("Width")
        self.cut_width.setPlaceholderText("Height")
        self.cut_qty.setPlaceholderText("No.")
        self.bracket_checkbox = QCheckBox("Bracket")
        cut_input_layout.addWidget(self.cut_length)
        cut_input_layout.addWidget(self.length_soot)
        cut_input_layout.addWidget(self.cut_width)
        cut_input_layout.addWidget(self.width_soot)
        cut_input_layout.addWidget(self.cut_qty)
        cut_input_layout.addWidget(self.bracket_checkbox)
        left_layout.addLayout(cut_input_layout)

        # Button row
        button_row = QHBoxLayout()
        self.add_cut_btn = QPushButton("Add Cut")
        self.remove_cut_btn = QPushButton("Remove Cut")
        self.sort_toggle = QCheckBox("🔀 Auto-Sort")
        self.sort_toggle.setChecked(True)
        self.sort_toggle.setToolTip("When ON, auto-sorts cut sizes for optimal layout.")
        # ✅ Ensure the checkbox doesn't expand unnecessarily
        self.sort_toggle.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        # Add buttons first so they take the stretch
        button_row.addWidget(self.add_cut_btn, stretch=1)
        button_row.addWidget(self.remove_cut_btn, stretch=1)
        # Checkbox gets no stretch — it only takes what it needs
        button_row.addWidget(self.sort_toggle, stretch=0)
        # Connect actions
        self.add_cut_btn.clicked.connect(self.add_cut_size)
        self.remove_cut_btn.clicked.connect(self.remove_selected_cut)
        # Add to layout
        left_layout.addLayout(button_row)

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
        
    def refresh_raw_quantities(self):
        loader = self.show_loader(self, "Refreshing", "Fetching updated quantities...")

        try:
            for index, sheet in self.sheet_data.items():
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
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to refresh quantities:\n{e}")
        finally:
            loader.close()
            if self.sheet_tabs.currentIndex() >= 0:
                self.load_sheet_data()

        
    def fill_cut_fields_from_selection(self, item):
        text = item.text().lower().strip()  # e.g., "24 3/8 x 12 1/2 - bracket" or "24 height - bracket"
        try:
            is_pipe = self.is_pipe_selected()

            # Determine if it's a bracket (only relevant in sheet mode)
            is_bracket = "bracket" in text
            self.bracket_checkbox.setChecked(is_bracket if not is_pipe else False)

            # Clean out the "- bracket" for parsing
            clean_text = text.replace(" - bracket", "").strip()

            def parse_soot(value_str):
                parts = value_str.strip().split()
                inch = parts[0]
                soot = parts[1] if len(parts) > 1 else "0"
                return inch, soot

            if is_pipe:
                # Pipe mode expects just height
                parts = clean_text.replace("height", "").strip().split()
                inch = parts[0].replace("\"", "")
                soot = parts[1].replace("\"", "") if len(parts) > 1 else "0"

                self.cut_length.setText(inch)
                self.length_soot.setCurrentText(soot)

                self.cut_width.clear()
                self.width_soot.setCurrentIndex(0)

            else:
                # Sheet mode: length x width
                if "x" in clean_text:
                    length_str, width_str = [s.strip() for s in clean_text.split('x')]

                    l_inch, l_soot = parse_soot(length_str)
                    w_inch, w_soot = parse_soot(width_str)

                    self.cut_length.setText(l_inch)
                    self.length_soot.setCurrentText(l_soot)
                    self.cut_width.setText(w_inch)
                    self.width_soot.setCurrentText(w_soot)

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
                if len(c) == 5:
                    # Sheet cut with bracket info
                    label = f"{c[2]} x {c[3]}"
                    if c[4]:
                        label += " - Bracket"
                    self.cut_list.addItem(label)
                elif len(c) == 4:
                    # Sheet cut (no bracket flag)
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
        if self.sheet_tabs.count() > 1:
            self.simulate_cutting()


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
            label_text = (
                f"{p.get('item_code', '')} - {p.get('name', '')} - "
                f"{p.get('length', 0)}{p.get('length_unit', '')} x "
                f"{p.get('width', 0)}{p.get('width_unit', '')} x "
                f"{p.get('height', 0)}{p.get('height_unit', '')}"
            )
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
                    is_bracket = self.bracket_checkbox.isChecked()
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

                    # Append " - Bracket" if selected
                    label = f"{l_str} x {w_str}"
                    if is_bracket:
                        label += " - Bracket"

                    for _ in range(qty):
                        self.cut_list.addItem(label)
                        if index in self.sheet_data:
                            self.sheet_data[index]["cuts"].append((l, w, l_str, w_str, is_bracket))

                    self.cut_length.clear()
                    self.cut_width.clear()
                    self.length_soot.setCurrentIndex(0)
                    self.width_soot.setCurrentIndex(0)
                    self.bracket_checkbox.setChecked(False)

                except Exception as e:
                    pass

            if hasattr(self, "cut_qty"):
                self.cut_qty.clear()

            self.simulate_cutting()

        except Exception as e:
            pass


    def remove_selected_cut(self):
        try:
            row = self.cut_list.currentRow()
            if row < 0:
                return

            index = self.sheet_tabs.currentIndex()
            if index not in self.sheet_data:
                return

            cuts = self.sheet_data[index]["cuts"]
            if not cuts:
                return

            # Determine how many to remove
            qty_to_remove = 1
            if self.cut_qty.text().isdigit():
                qty_to_remove = int(self.cut_qty.text())
                if qty_to_remove <= 0:
                    qty_to_remove = 1

            # Get the label of selected row
            selected_label = self.cut_list.item(row).text().strip()

            # Build label for comparison (same as simulate_cutting)
            def make_label(cut):
                label = f"{cut[2]} x {cut[3]}"
                if cut[4]:
                    label += " - Bracket"
                return label

            # Remove matching cuts
            new_cuts = []
            removed_count = 0
            for cut in cuts:
                if removed_count < qty_to_remove and make_label(cut) == selected_label:
                    removed_count += 1
                    continue  # skip this one (remove)
                new_cuts.append(cut)

            # Update data
            self.sheet_data[index]["cuts"] = new_cuts

            # Clear input fields
            self.cut_length.clear()
            self.cut_width.clear()
            self.length_soot.setCurrentIndex(0)
            self.width_soot.setCurrentIndex(0)
            self.bracket_checkbox.setChecked(False)
            self.cut_qty.clear()

            # ✅ Always refresh cut list and canvas
            if new_cuts:
                self.simulate_cutting()
            else:
                self.cut_list.clear()
                self.show_empty_raw()

        except Exception as e:
            print("Remove cut error:", e)



    def zoom_in(self):
        self.canvas.scale(1.25, 1.25)

    def zoom_out(self):
        self.canvas.scale(0.8, 0.8)
        
    def toggle_pipe_mode(self):
        if self.is_pipe_selected():
            # Pipe mode: disable width and bracket
            self.cut_width.setDisabled(True)
            self.width_soot.setDisabled(True)
            self.cut_width.setPlaceholderText("Disabled for pipe")
            self.cut_length.setPlaceholderText("Height")

            self.bracket_checkbox.setChecked(False)
            self.bracket_checkbox.setDisabled(True)
            self.sort_toggle.setDisabled(True)
            self.sort_toggle.setToolTip("Sorting not applicable in pipe mode.")

        else:
            # Sheet mode: enable width and bracket
            self.cut_width.setDisabled(False)
            self.width_soot.setDisabled(False)
            self.cut_width.setPlaceholderText("Height")
            self.cut_length.setPlaceholderText("Width")
            self.sort_toggle.setDisabled(False)
            self.sort_toggle.setToolTip("Enable to auto-sort cut sizes")

            self.bracket_checkbox.setDisabled(False)
            
    def smart_group_sort(self, raw_pieces):
        from collections import defaultdict

        grouped = defaultdict(list)
        for piece in raw_pieces:
            grouped[(piece[2], piece[3])].append(piece)

        def nesting_sort_key(k):
            w = self.parse_inches(k[0])
            h = self.parse_inches(k[1])
            group = grouped[k]
            qty = len(group)
            area = w * h
            aspect_ratio = h / w if w else float('inf')
            is_portrait = int(h >= w)

            return (w, -is_portrait, -qty, -area)

        sorted_keys = sorted(grouped.keys(), key=nesting_sort_key)
        return [p for key in sorted_keys for p in grouped[key]]
    
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

            raw_cuts = self.sheet_data.get(self.sheet_tabs.currentIndex(), {}).get("cuts", [])
            # Step 1: Sort cuts using smart grouping if on
            if self.sort_toggle.isChecked():
                sorted_cuts = self.smart_group_sort(raw_cuts)
            else:
                sorted_cuts = raw_cuts[:]

            # Step 2: Convert to (w, h, label, is_bracket)
            cuts_for_placement = [
                (
                    self.parse_inches(c[2]),
                    self.parse_inches(c[3]),
                    f"{c[2]} x {c[3]}",
                    c[4]
                )
                for c in sorted_cuts if len(c) == 5
            ]
            used_rects, unplaced = self.place_rectangles(sheet_w, sheet_h, cuts_for_placement)
            if not used_rects:
                return
            
            self.draw_canvas(sheet_w, sheet_h, used_rects)
            
            # ✅ Always update cut_list with visual highlighting
            # ✅ Count how many times each label was placed
            placed_label_counts = Counter([
                f"{label} - Bracket" if is_bracket else label
                for _, _, _, _, label, is_bracket in used_rects
            ])

            self.cut_list.clear()

            for c in sorted_cuts:
                if len(c) == 5:
                    label = f"{c[2]} x {c[3]}"
                    if c[4]:
                        label += " - Bracket"

                    item = QListWidgetItem(label)

                    if placed_label_counts[label] > 0:
                        placed_label_counts[label] -= 1  # Mark one as placed
                    else:
                        item.setBackground(QColor("#ffe6e6"))  # 🔴 Light red
                        item.setToolTip("❌ Not placed on sheet")

                    self.cut_list.addItem(item)

        except Exception as e:
            print("Simulation error:", e)
            
    
    def to_mixed_fraction(self, value):
        inches = int(value)
        fraction = Fraction(value - inches).limit_denominator(16)
        if fraction == 0:
            return f"{inches}"
        return f"{inches} {fraction.numerator}/{fraction.denominator}"

    def scan_waste_blocks(self, sheet_w, sheet_h, rects, scan_direction="top", resolution=8):
        grid_w = int(sheet_w * resolution)
        grid_h = int(sheet_h * resolution)
        used = [[False for _ in range(grid_w)] for _ in range(grid_h)]

        for x, y, w, h, *_ in rects:
            for dx in range(ceil(w * resolution)):
                for dy in range(ceil(h * resolution)):
                    px = int((x * resolution) + dx)
                    py = int((y * resolution) + dy)
                    if 0 <= px < grid_w and 0 <= py < grid_h:
                        used[py][px] = True

        visited = [[False for _ in range(grid_w)] for _ in range(grid_h)]
        waste_blocks = []

        y_range = range(grid_h) if scan_direction == "top" else range(grid_h - 1, -1, -1)

        for y in y_range:
            for x in range(grid_w):
                if not used[y][x] and not visited[y][x]:
                    max_w = 0
                    while x + max_w < grid_w and not used[y][x + max_w] and not visited[y][x + max_w]:
                        max_w += 1

                    max_h = 1
                    done = False
                    while True:
                        next_y = y + max_h if scan_direction == "top" else y - max_h
                        if next_y < 0 or next_y >= grid_h:
                            break
                        for dx in range(max_w):
                            if used[next_y][x + dx] or visited[next_y][x + dx]:
                                done = True
                                break
                        if done:
                            break
                        max_h += 1

                    for dy in range(max_h):
                        for dx in range(max_w):
                            yy = y + dy if scan_direction == "top" else y - dy
                            visited[yy][x + dx] = True

                    top_y = y if scan_direction == "top" else y - max_h + 1
                    # Convert back to inches
                    waste_blocks.append((x / resolution, top_y / resolution, max_w / resolution, max_h / resolution))

        return waste_blocks

    
    def find_all_waste_blocks(self, sheet_w, sheet_h, rects):
        return self.scan_waste_blocks(sheet_w, sheet_h, rects, scan_direction="bottom")



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

        for i, (x, y, w, h, label, is_bracket) in enumerate(rects):
            used_area += w * h
            rect_item = QGraphicsRectItem(x * scale, y * scale, w * scale, h * scale)
            rect_item.setBrush(QBrush(QColor("#74b9ff")))
            rect_item.setPen(QPen(Qt.darkBlue, 1))
            self.scene.addItem(rect_item)

            # Match original cut label
            original_label = label
            

            min_dim = min(w, h)
            font_size = max(6, min(14, int(min_dim * scale * 0.2)))

            label = QGraphicsTextItem(original_label)
            font = QFont("Arial", font_size)
            label.setFont(font)
            label.setDefaultTextColor(Qt.black)
            label.setZValue(10)

            label_rect = label.boundingRect()

            if h > w:
                # Rotate -90 around center
                transform = QTransform()
                transform.translate((x + w / 2) * scale, (y + h / 2) * scale)
                transform.rotate(-90)
                transform.translate(-label_rect.width() / 2, -label_rect.height() / 2)
                label.setTransform(transform)
            else:
                label.setPos((x + w / 2) * scale - label_rect.width() / 2,
                            (y + h / 2) * scale - label_rect.height() / 2)

            self.scene.addItem(label)

            # Draw diagonal if bracket
            if is_bracket:
                x_px = x * scale
                y_px = y * scale
                w_px = w * scale
                h_px = h * scale
                offset = 15

                if w_px > h_px:
                    x1 = x_px
                    y1 = y_px + offset
                    x2 = x_px + w_px
                    y2 = y_px + h_px - offset
                else:
                    x1 = x_px + w_px - offset
                    y1 = y_px
                    x2 = x_px + offset
                    y2 = y_px + h_px

                line = QGraphicsLineItem(x1, y1, x2, y2)
                line.setPen(QPen(QColor("#2c3e50"), 1.5, Qt.SolidLine))
                self.scene.addItem(line)

        # === Summary ===
        # Count cut usage
        usage_counter = Counter()
        for i, (x, y, w, h, label, is_bracket) in enumerate(rects):
            if is_bracket:
                label = f"{label} - Bracket"
            usage_counter[label] += 1

        lines = [f"Sheet: {int(sheet_w)} x {int(sheet_h)} inch"]

        # ✅ Add spacing + used section if cuts exist
        if usage_counter:
            lines.append("-")  # <-- Blank line before Used
            lines.append("Used:")
            for label, count in usage_counter.items():
                lines.append(f"  {label} = {count}")

        # ✅ Add spacing + waste block sizes if any
        if rects:
            waste_blocks = self.find_all_waste_blocks(int(sheet_w), int(sheet_h), rects)
        else:
            waste_blocks = []

        if waste_blocks:
            lines.append("")
            for i, (x, y, w, h) in enumerate(waste_blocks, 1):
                w_str = self.to_mixed_fraction(w)
                h_str = self.to_mixed_fraction(h)
                lines.append(f"Waste Block {i}: {w_str} x {h_str} inch")

        # Render summary
        info = QGraphicsTextItem("\n".join(lines))
        info.setDefaultTextColor(Qt.darkRed)
        info.setFont(QFont("Arial", 9))
        info.setPos(canvas_w + 20, 10)
        self.scene.addItem(info)

        # Title
        title = QGraphicsTextItem("Sheet Cutting Visualization")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setDefaultTextColor(Qt.darkBlue)
        title.setPos(10, -30)
        self.scene.addItem(title)

        self.canvas.setSceneRect(-20, -60, canvas_w + 250, sheet_h * scale + 100)
        
    def auto_optimize_sheet(self, sheet_w, sheet_h, rectangles):
        def dp_find_best_row(pieces, max_width):
            n = len(pieces)
            dp = [{} for _ in range(n + 1)]
            dp[0][0] = (0, [])

            for i in range(1, n + 1):
                w0, h0, label, is_bracket = pieces[i - 1]
                orientations = [(w0, h0), (h0, w0)]
                for prev_w, (total, items) in dp[i - 1].items():
                    for w, h in orientations:
                        new_w = prev_w + w
                        if new_w <= max_width:
                            new_total = total + w
                            new_items = items + [(w, h, label, is_bracket, i - 1)]
                            if new_w not in dp[i] or dp[i][new_w][0] < new_total:
                                dp[i][new_w] = (new_total, new_items)
                    if prev_w not in dp[i] or dp[i][prev_w][0] < total:
                        dp[i][prev_w] = (total, items)

            best_total = 0
            best_items = []
            for total, items in dp[n].values():
                if total > best_total:
                    best_total = total
                    best_items = items

            if not best_items:
                return None

            used_indexes = [idx for *_, idx in best_items]
            used_items = [pieces[i] for i in used_indexes]
            row = [item[:4] for item in best_items]
            return used_items, row

        parsed = [tuple(cut) for cut in rectangles]
        y_cursor = 0
        layout = []

        while parsed:
            result = dp_find_best_row(parsed, sheet_w)
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

        return [(w, h, label, is_bracket) for w, h, label, is_bracket in layout]
        
    # def place_rectangles(self, sheet_w, sheet_h, rectangles, fallback_allowed=True):
    #     used = []
    #     current_y = 0
    #     row_height = 0
    #     current_x = 0
    #     resolution = 8
    #     unplaced = []

    #     for rect in rectangles:
    #         w, h, label, is_bracket = rect
    #         placed = False

    #         # Step 1: Current row
    #         for pw, ph in [(w, h), (h, w)] if w != h else [(w, h)]:
    #             if current_x + pw <= sheet_w and current_y + ph <= sheet_h:
    #                 overlaps = any(
    #                     not (current_x + pw <= ux or ux + uw <= current_x or
    #                         current_y + ph <= uy or uy + uh <= current_y)
    #                     for ux, uy, uw, uh, *_ in used
    #                 )
    #                 if not overlaps:
    #                     used.append((current_x, current_y, pw, ph, label, is_bracket))
    #                     current_x += pw
    #                     row_height = max(row_height, ph)
    #                     placed = True
    #                     break

    #         # Step 2: New row
    #         if not placed:
    #             new_y = current_y + row_height
    #             for pw, ph in [(w, h), (h, w)] if w != h else [(w, h)]:
    #                 if new_y + ph <= sheet_h and pw <= sheet_w:
    #                     overlaps = any(
    #                         not (0 + pw <= ux or ux + uw <= 0 or
    #                             new_y + ph <= uy or uy + uh <= new_y)
    #                         for ux, uy, uw, uh, *_ in used
    #                     )
    #                     if not overlaps:
    #                         current_y = new_y
    #                         current_x = 0
    #                         row_height = ph
    #                         used.append((current_x, current_y, pw, ph, label, is_bracket))
    #                         current_x += pw
    #                         placed = True
    #                         break

    #         # Step 3: Waste block
    #         if not placed:
    #             waste_blocks = self.scan_waste_blocks(sheet_w, sheet_h, used)
    #             for wx, wy, ww, wh in waste_blocks:
    #                 for pw, ph in [(w, h), (h, w)] if w != h else [(w, h)]:
    #                     if pw <= ww and ph <= wh:
    #                         overlaps = any(
    #                             not (wx + pw <= ux or ux + uw <= wx or
    #                                 wy + ph <= uy or uy + uh <= wy)
    #                             for ux, uy, uw, uh, *_ in used
    #                         )
    #                         if not overlaps:
    #                             used.append((wx, wy, pw, ph, label, is_bracket))
    #                             placed = True
    #                             break
    #                 if placed:
    #                     break

    #         # Step 4: Grid scan
    #         if not placed:
    #             grid_w = int(sheet_w * resolution)
    #             grid_h = int(sheet_h * resolution)
    #             grid = [[False for _ in range(grid_w)] for _ in range(grid_h)]

    #             for ux, uy, uw, uh, *_ in used:
    #                 for dx in range(int(uw * resolution)):
    #                     for dy in range(int(uh * resolution)):
    #                         gx = int((ux + dx / resolution) * resolution)
    #                         gy = int((uy + dy / resolution) * resolution)
    #                         if 0 <= gx < grid_w and 0 <= gy < grid_h:
    #                             grid[gy][gx] = True

    #             for gy in range(grid_h):
    #                 for gx in range(grid_w):
    #                     x_pos = gx / resolution
    #                     y_pos = gy / resolution
    #                     if x_pos + w > sheet_w or y_pos + h > sheet_h:
    #                         continue

    #                     fits = True
    #                     for dy in range(int(h * resolution)):
    #                         for dx in range(int(w * resolution)):
    #                             if grid[gy + dy][gx + dx]:
    #                                 fits = False
    #                                 break
    #                         if not fits:
    #                             break

    #                     if fits:
    #                         used.append((x_pos, y_pos, w, h, label, is_bracket))
    #                         placed = True
    #                         break
    #                 if placed:
    #                     break
        
        
    def place_rectangles(self, sheet_w, sheet_h, rectangles, fallback_allowed=True):
        from math import ceil

        used = []
        unplaced = []
        step = 0.125        # Resolution (1/8 inch)
        kerf = 0.0          # Space between cuts

        map_width = int(sheet_w / step)
        height_map = [0.0] * map_width  # Stores Y-height at each X-step

        def fits_at(x_idx, w_steps, rect_w, rect_h):
            x = x_idx * step
            max_y = max(height_map[x_idx:x_idx + w_steps])
            if max_y + rect_h > sheet_h:
                return None
            return x, max_y  # x and y position to place

        def update_height_map(x_idx, w_steps, new_top):
            for i in range(x_idx, x_idx + w_steps):
                height_map[i] = new_top

        def try_place(w, h):
            w_steps = int(ceil((w + kerf) / step))
            best_x_idx = None
            best_y = None

            for x_idx in range(0, map_width - w_steps + 1):
                result = fits_at(x_idx, w_steps, w, h)
                if result:
                    x, y = result
                    if best_y is None or y < best_y or (y == best_y and x < best_x_idx * step):
                        best_x_idx = x_idx
                        best_y = y

            if best_x_idx is not None:
                x = best_x_idx * step
                y = best_y
                update_height_map(best_x_idx, w_steps, y + h + kerf)
                return x, y
            return None

        for w, h, label, is_bracket in rectangles:
            placed = False

            # Try original orientation
            pos = try_place(w, h)

            # Try rotated
            if not pos and w != h:
                pos = try_place(h, w)
                if pos:
                    w, h = h, w  # apply rotation

            if pos:
                x, y = pos
                used.append((x, y, w, h, label, is_bracket))
                placed = True

            # Fallback optimizer
            if not placed and fallback_allowed:
                optimized = self.auto_optimize_sheet(sheet_w, sheet_h, rectangles)
                return self.place_rectangles(sheet_w, sheet_h, optimized, fallback_allowed=False)

            if not placed:
                unplaced.append(label)

        return used, unplaced



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
                base_id = doc.id
                qty = data.get("qty", {})

                for branch, colors in qty.items():
                    for color, conditions in colors.items():
                        for condition, amount in conditions.items():
                            variant = data.copy()
                            variant["id"] = base_id
                            variant["branch"] = branch
                            variant["color"] = color
                            variant["condition"] = condition
                            variant["available_qty"] = amount
                            self.items.append(variant)

                            # Get fields safely
                            item_code = variant.get("item_code", "")
                            name = variant.get("name", "Unnamed")
                            length = variant.get("length", 0)
                            length_unit = variant.get("length_unit", "")
                            width = variant.get("width", 0)
                            width_unit = variant.get("width_unit", "")
                            metal_type = variant.get("metal_type", "").upper()

                            label = (
                                f"{item_code} - {name} "
                                f"({length} {length_unit} x {width} {width_unit}) - "
                                f"{metal_type} | {color} - {condition} ({branch}) - Q{amount}"
                            )

                            self.item_dropdown.addItem(label, variant)

        except Exception as e:
            print("Error loading items:", e)


    def load_products(self):
        self.products = []
        loader = self.show_loader(self, "Loading", "Fetching finished products...")
        try:
            finished_main_id = None
            for doc in db.collection("product_main_categories").stream():
                if doc.to_dict().get("name") == "Finished Products":
                    finished_main_id = doc.id
                    break
            if not finished_main_id:
                return

            finished_sub_ids = []
            for doc in db.collection("product_sub_categories").where("main_id", "==", finished_main_id).stream():
                finished_sub_ids.append(doc.id)

            # Load finished products directly without variants
            for doc in db.collection("products").stream():
                data = doc.to_dict()
                data["id"] = doc.id

                if data.get("sub_id") in finished_sub_ids:
                    self.products.append(data)

            self.filter_products()
        except Exception as e:
            print("load_products error:", e)
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
        # from collections import defaultdict
        # loader = self.show_loader(self, "Validating", "Checking inventory...")
        # # Group usage by raw material variant key
        # usage_map = defaultdict(float)

        # for index, sheet in self.sheet_data.items():
        #     raw_item = sheet.get("raw_item", {})
        #     raw_qty_input = sheet.get("raw_qty", "")
        #     available_qty = raw_item.get("available_qty", 0)

        #     try:
        #         raw_qty_input = float(raw_qty_input)
        #     except (ValueError, TypeError):
        #         QMessageBox.critical(self, "Invalid Quantity", f"Sheet {index+1}: Enter a valid number for raw material quantity.")
        #         loader.close()
        #         return

        #     # Build a unique key for the raw material variant
        #     key = f"{raw_item.get('id')}|{raw_item.get('branch')}|{raw_item.get('color')}|{raw_item.get('condition')}"
        #     usage_map[key] += raw_qty_input

        #     # Check availability once total is accumulated
        #     if usage_map[key] > available_qty:
        #         QMessageBox.critical(
        #             self,
        #             "Inventory Error",
        #             f"Raw material overuse detected!\n\n"
        #             f"Variant: {raw_item.get('item_code', '')} - {raw_item.get('name', '')} "
        #             f"({raw_item.get('color', '')}, {raw_item.get('condition', '')}) @ {raw_item.get('branch', '')}\n"
        #             f"Available: {available_qty}\n"
        #             f"Total Requested: {usage_map[key]}"
        #         )
        #         loader.close()
        #         return
        # loader.close()
        
        from collections import defaultdict

        loader = self.show_loader(self, "Validating", "Checking inventory...")
        usage_map = defaultdict(float)
        overuse_detected = []

        for index, sheet in self.sheet_data.items():
            raw_item = sheet.get("raw_item", {})
            raw_qty_input = sheet.get("raw_qty", "")
            available_qty = raw_item.get("available_qty", 0)

            try:
                raw_qty_input = float(raw_qty_input)
            except (ValueError, TypeError):
                QMessageBox.critical(self, "Invalid Quantity", f"Sheet {index+1}: Enter a valid number for raw material quantity.")
                loader.close()
                return

            # Build unique variant key
            key = f"{raw_item.get('id')}|{raw_item.get('branch')}|{raw_item.get('color')}|{raw_item.get('condition')}"
            usage_map[key] += raw_qty_input

            # Check overuse
            if usage_map[key] > available_qty:
                overuse_detected.append({
                    "variant": f"{raw_item.get('item_code', '')} - {raw_item.get('name', '')}",
                    "branch": raw_item.get("branch", ""),
                    "color": raw_item.get("color", ""),
                    "condition": raw_item.get("condition", ""),
                    "available": available_qty,
                    "requested": usage_map[key]
                })

        loader.close()

        # If any overuse, ask user
        if overuse_detected:
            msg = "Raw material overuse detected:\n\n"
            for o in overuse_detected:
                msg += (
                    f"🔹 {o['variant']} ({o['color']}, {o['condition']}) @ {o['branch']}\n"
                    f"Available: {o['available']} | Requested: {o['requested']}\n\n"
                )
            msg += "Do you still want to proceed with the order?"

            reply = QMessageBox.question(
                self,
                "Inventory Warning",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.No:
                return  # user cancelled the submission

        # 2. Build Batches
        batches = []
        for sheet in self.sheet_data.values():
            raw = sheet.get("raw_item", {})
            raw_ref = db.collection("products").document(raw.get("id", ""))
            cuts = []

            for c in sheet.get("cuts", []):
                if isinstance(c, dict):
                    cuts.append(c)
                elif isinstance(c, (list, tuple)):
                    if len(c) == 5:
                        cuts.append({
                            "length": c[0], "width": c[1],
                            "length_raw": c[2], "width_raw": c[3],
                            "is_bracket": c[4]
                        })
                    elif len(c) == 2:
                        cuts.append({
                            "height": c[0],
                            "height_raw": c[1]
                        })

            products = [
                {
                    "product_ref": db.collection("products").document(p["id"]),
                    "name": f"{p.get('item_code')} - {p.get('name')} - "
                            f"{p.get('length', 0)}{p.get('length_unit')} x "
                            f"{p.get('width', 0)}{p.get('width_unit')} x "
                            f"{p.get('height', 0)}{p.get('height_unit')}",
                    "qty": p.get("qty", 1),
                    "qty_done": 0
                }
                for p in sheet.get("products", [])
            ]

            batches.append({
                "raw_subcat": sheet.get("raw_subcat"),
                "raw_item": {
                    "raw_ref": raw_ref,
                    "name": raw.get("name", ""),
                    "branch": raw.get("branch"),
                    "color": raw.get("color"),
                    "condition": raw.get("condition"),
                    "qty": sheet.get("raw_qty", ""),
                    "raw_done": 0
                },
                "cuts": cuts,
                "products": products
            })

        # 3. Final Upload
        payload = {
            "sheets": batches,
            "status": "In Progress" if self.edit_data else "Pending",
            "created_at": firestore.SERVER_TIMESTAMP,
            "notes": self.notes.text().strip()
        }

        loader = self.show_loader(self, "Sending Order", "Uploading to Firebase...")
        try:
            if self.doc_id:
                db.collection("manufacturing_orders").document(self.doc_id).update(payload)
            else:
                db.collection("manufacturing_orders").add(payload)
            QMessageBox.information(self, "Success", "Order saved successfully.")
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
        finally:
            loader.close()