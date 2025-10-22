from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget,
    QComboBox, QGridLayout, QMessageBox, QFileDialog, QProgressDialog, QApplication,
    QDialog, QFormLayout, QDialogButtonBox, QFrame, QSplitter, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QScrollArea
from PyQt5.QtGui import QIcon
from firebase.config import db
import pandas as pd


class ProductsPage(QWidget):
    """
    UI polish only — underlying UX, data flow and method names are unchanged.
    - Softer look (rounded cards, spacing, typography)
    - Better layout using a QSplitter
    - Comfortable control sizes (bigger inputs, list item padding)
    - Consistent button styling (primary / subtle)
    - Subtle section headers
    - Responsive tweaks for smaller screens (vertical stacking, compact paddings, scrollable form)
    """

    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.branches = user_data.get("branch", [])
        if isinstance(self.branches, str):
            self.branches = [self.branches]
        self.is_admin = user_data.get("role") == "admin"  # Check if user is admin

        # ===== Window =====
        self.setWindowTitle("Products Management")
        self.resize(1200, 750)
        self.setMinimumSize(900, 620)

        # ===== Global Stylesheet (Qt-friendly — no box-shadow) =====
        self._regular_styles = (
            """
            QWidget { background-color: #f5f7fb; color: #1f2937; font-size: 13px; }
            QLabel#TitleLabel { font-size: 20px; font-weight: 700; color: #111827; }
            QLabel#SectionLabel { font-size: 12px; font-weight: 600; color: #6b7280; margin: 6px 2px; text-transform: uppercase; }
            QFrame#Card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; }
            QFrame#Toolbar { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; }
            QLineEdit, QComboBox { 
                border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px 10px; min-height: 36px; 
                background: #ffffff; selection-background-color: #c7d2fe; 
            }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #6366f1; }
            QListWidget { border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; }
            QListWidget::item { padding: 10px 12px; margin: 2px; border-radius: 8px; min-height: 34px; }
            QListWidget::item:selected { background: #eef2ff; color: #111827; }
            QPushButton { border: none; border-radius: 12px; padding: 9px 14px; font-weight: 600; }
            QPushButton#Primary { background: #4f46e5; color: white; }
            QPushButton#Primary:hover { background: #4338ca; }
            QPushButton#Subtle { background: #eef2ff; color: #3730a3; }
            QPushButton#Subtle:hover { background: #e0e7ff; }
            QPushButton#Danger { background: #fee2e2; color: #b91c1c; }
            QPushButton#Danger:hover { background: #fecaca; }
            QLabel#DialogHeading { font-size: 14px; font-weight: 700; margin: 6px 0 10px 0; }
            QProgressDialog { border: 1px solid #e5e7eb; border-radius: 12px; }
            """
        )
        self._compact_styles = (
            """
            QWidget { background-color: #f5f7fb; color: #1f2937; font-size: 12px; }
            QLabel#TitleLabel { font-size: 18px; font-weight: 700; color: #111827; }
            QLabel#SectionLabel { font-size: 11px; font-weight: 600; color: #6b7280; margin: 4px 2px; text-transform: uppercase; }
            QFrame#Card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; }
            QLineEdit, QComboBox { 
                border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 8px; min-height: 32px; 
                background: #ffffff; selection-background-color: #c7d2fe; 
            }
            QListWidget { border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
            QListWidget::item { padding: 8px 10px; margin: 2px; border-radius: 8px; min-height: 30px; }
            QPushButton { border: none; border-radius: 10px; padding: 7px 12px; font-weight: 600; }
            QPushButton#Primary { background: #4f46e5; color: white; }
            QPushButton#Subtle { background: #eef2ff; color: #3730a3; }
            QPushButton#Danger { background: #fee2e2; color: #b91c1c; }
            """
        )
        self.setStyleSheet(self._regular_styles)

        self.categories = []
        self.subcategories = []
        self.items = []
        self.selected_main_id = None
        self.selected_sub_id = None

        self.setup_ui()
        self.refresh_categories()

    # ================= UI =================
    def _card(self):
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        return card, lay

    def _toolbar(self):
        bar = QFrame()
        bar.setObjectName("Toolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        return bar, lay

    def _btn(self, text, clicked, kind="primary", icon: QIcon = None):
        btn = QPushButton(text)
        if icon:
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
        if kind == "primary":
            btn.setObjectName("Primary")
        elif kind == "danger":
            btn.setObjectName("Danger")
        else:
            btn.setObjectName("Subtle")
        btn.clicked.connect(clicked)
        return btn

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title + header actions (button snug with title, not full-width)
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📦 Product Setup Panel")
        title.setObjectName("TitleLabel")
        title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header_row.addWidget(title, 0, Qt.AlignLeft)
        header_row.addStretch(1)

        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_imp_exp_anything" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            import_btn = self._btn("Import Inventory", self.show_not_allowed_warning, kind="primary")
        else:
            import_btn = self._btn("Import Inventory", self.import_inventory, kind="primary")
        
        import_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # avoid stretching full width
        header_row.addWidget(import_btn, 0, Qt.AlignRight)

        root.addLayout(header_row)

        # Split main area
        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        self.splitter = splitter
        root.addWidget(splitter, 1)

        # Left pane (Categories + Subcategories)
        left_card, left_lay = self._card()
        splitter.addWidget(left_card)

        lbl_cat = QLabel("Main Categories")
        lbl_cat.setObjectName("SectionLabel")
        lbl_cat.setWordWrap(True)
        left_lay.addWidget(lbl_cat)

        self.cat_list = QListWidget()
        self.cat_list.setUniformItemSizes(False)
        self.cat_list.setTextElideMode(Qt.ElideRight)
        self.cat_list.itemSelectionChanged.connect(self.on_main_category_selected)
        self.cat_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_lay.addWidget(self.cat_list)

        cat_row = QHBoxLayout()
        self.cat_input = QLineEdit()
        self.cat_input.setPlaceholderText("Add or rename main category…")
        cat_row.addWidget(self.cat_input, 1)
        cat_row.addWidget(self._btn("Add", self.add_category, kind="subtle"))
        
        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_edit_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            rename_btn = self._btn("Rename", self.show_not_allowed_warning, kind="subtle")  
        else:
            rename_btn = self._btn("Rename", self.edit_category, kind="subtle")


        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_delete_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            delete_btn = self._btn("Delete", self.show_not_allowed_warning, kind="danger")  
        else:
            delete_btn = self._btn("Delete", self.delete_category, kind="danger")

        cat_row.addWidget(rename_btn)
        cat_row.addWidget(delete_btn)
        
        left_lay.addLayout(cat_row)

        left_lay.addSpacing(6)
        lbl_sub = QLabel("Sub Categories")
        lbl_sub.setObjectName("SectionLabel")
        lbl_sub.setWordWrap(True)
        left_lay.addWidget(lbl_sub)

        self.subcat_list = QListWidget()
        self.subcat_list.setUniformItemSizes(False)
        self.subcat_list.setTextElideMode(Qt.ElideRight)
        self.subcat_list.itemSelectionChanged.connect(self.on_sub_category_selected)
        self.subcat_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_lay.addWidget(self.subcat_list)

        sub_row = QHBoxLayout()
        self.subcat_input = QLineEdit()
        self.subcat_input.setPlaceholderText("Add or rename sub category…")
        sub_row.addWidget(self.subcat_input, 1)
        sub_row.addWidget(self._btn("Add", self.add_subcategory, kind="subtle"))
        
        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_edit_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            edit_subcategory_btn = self._btn("Rename", self.show_not_allowed_warning, kind="subtle")
        else:
            edit_subcategory_btn = self._btn("Rename", self.edit_subcategory, kind="subtle")
            
        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_delete_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            delete_subcategory_btn = self._btn("Delete", self.show_not_allowed_warning, kind="danger")
        else:
            delete_subcategory_btn = self._btn("Delete", self.delete_subcategory, kind="danger")

        sub_row.addWidget(edit_subcategory_btn)
        sub_row.addWidget(delete_subcategory_btn)
        
        left_lay.addLayout(sub_row)

        # ===== Right pane (Items + Form) =====
        right_card, right_lay = self._card()
        splitter.addWidget(right_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        lbl_items = QLabel("Items") 
        lbl_items.setObjectName("SectionLabel")
        lbl_items.setWordWrap(True)
        right_lay.addWidget(lbl_items)

        self.item_list = QListWidget()
        self.item_list.setUniformItemSizes(False)
        self.item_list.setTextElideMode(Qt.ElideRight)
        self.item_list.itemSelectionChanged.connect(self.on_item_selected)
        right_lay.addWidget(self.item_list, 1)

        # Form card inside right pane (scrollable on small screens)
        form_card, form_lay = self._card()
        form_title = QLabel("Item Details")
        form_title.setObjectName("SectionLabel")
        form_title.setWordWrap(True)
        form_lay.addWidget(form_title)

        form_grid = self.build_item_form()
        form_lay.addLayout(form_grid)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_container = QWidget()
        self.form_container.setLayout(QVBoxLayout())
        self.form_container.layout().setContentsMargins(0, 0, 0, 0)
        self.form_container.layout().addWidget(form_card)
        self.form_scroll.setWidget(self.form_container)
        right_lay.addWidget(self.form_scroll, 2)

        # Action row
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._btn("Add", self.add_item, kind="primary"))
        
        # Disable delete button for non-admins
        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_edit_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            edit_item_btn = self._btn("Edit", self.show_not_allowed_warning, kind="subtle")  
        else:
            edit_item_btn = self._btn("Edit", self.edit_item, kind="subtle")

        # Disable delete button for non-admins
        # Check if the user is an admin or if they have the permission to delete
        if not self.is_admin and "can_delete_products" not in self.user_data.get("extra_perm", []):
            # delete_btn.setDisabled(True)
            # Connect the button to the warning function when clicked
            delete_item_btn = self._btn("Delete", self.show_not_allowed_warning, kind="danger")  
        else:
            delete_item_btn = self._btn("Delete", self.delete_item, kind="danger")

        actions.addWidget(edit_item_btn)
        actions.addWidget(delete_item_btn)

        actions.addWidget(self._btn("Clear", self.clear_fields, kind="subtle"))
        right_lay.addLayout(actions)

        # Start in the right mode for current size
        self._apply_responsive_layout()

    # ================= Helpers (no logic change) =================
    def show_not_allowed_warning(self):
        QMessageBox.warning(self, "Not Allowed", "You do not have permission to perform this action.")

    def make_button_row(self, txt1, cmd1, txt2, cmd2, txt3, cmd3, txt4, cmd4):
        # kept for compatibility
        row = QHBoxLayout()
        for txt, cmd in [(txt1, cmd1), (txt2, cmd2), (txt3, cmd3), (txt4, cmd4)]:
            btn = self._btn(txt, cmd, kind="subtle")
            row.addWidget(btn)
        return row

    def make_button_row_3(self, txt1, cmd1, txt2, cmd2, txt3, cmd3):
        # kept for compatibility
        row = QHBoxLayout()
        for txt, cmd in [(txt1, cmd1), (txt2, cmd2), (txt3, cmd3)]:
            btn = self._btn(txt, cmd, kind="subtle")
            row.addWidget(btn)
        return row

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

    def build_item_form(self):
        self.fields = {}
        self.qty_fields = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        # Fields before Metal Type
        labels_before_metal = [
            ("Item Code", True), ("Name", False), ("Length", False), ("Width", False),
            ("Height", False), ("Gauge", False)
        ]

        row = 0
        for label, readonly in labels_before_metal:
            lab = QLabel(label + ":")
            grid.addWidget(lab, row, 0)
            entry = QLineEdit()
            entry.setReadOnly(readonly)
            entry.setPlaceholderText(label)
            self.fields[label.lower().replace(" ", "_")] = entry
            grid.addWidget(entry, row, 1)
            row += 1

        # Metal Type (inserted right after Gauge)
        self.metal_type_label = QLabel("Metal Type:")
        grid.addWidget(self.metal_type_label, row, 0)
        self.fields["metal_type"] = QComboBox()
        self.fields["metal_type"].addItems(["", "HRC", "CRC", "GP"])
        grid.addWidget(self.fields["metal_type"], row, 1)
        self.metal_type_label.setVisible(False)
        self.fields["metal_type"].setVisible(False)
        row += 1

        # Fields after Metal Type
        labels_after_metal = [
            ("Selling Price", False), ("Reorder Qty", False), ("Weight", False)
        ]
        for label, readonly in labels_after_metal:
            lab = QLabel(label + ":")
            grid.addWidget(lab, row, 0)
            entry = QLineEdit()
            entry.setReadOnly(readonly)
            entry.setPlaceholderText(label)
            self.fields[label.lower().replace(" ", "_")] = entry
            grid.addWidget(entry, row, 1)
            row += 1

        # Unit selectors aligned with dimensions
        self.unit_fields = {}
        for i, dim in enumerate(["length", "width", "height"]):
            grid.addWidget(QLabel(dim.capitalize() + " Unit:"), i + 2, 2)  # align with length/width/height rows
            unit_cb = QComboBox()
            unit_cb.addItems(["Ft", "Inch", "mm"])
            self.unit_fields[dim + "_unit"] = unit_cb
            grid.addWidget(unit_cb, i + 2, 3)

        # Weight unit
        grid.addWidget(QLabel("Weight Unit:"), row - 1, 2)
        weight_unit_cb = QComboBox()
        weight_unit_cb.addItems(["g", "kg"])
        self.unit_fields["weight_unit"] = weight_unit_cb
        grid.addWidget(weight_unit_cb, row - 1, 3)

        # Instructional label
        hint = QLabel("Qty input will be prompted per branch and color when saving.")
        hint.setStyleSheet("font-style: italic; color: #6b7280;")
        grid.addWidget(hint, row, 0, 1, 4)

        return grid

    # ================= Responsive helpers =================
    def _apply_responsive_layout(self):
        # Switch to vertical stack when narrow and apply compact styles
        narrow = self.width() < 980
        try:
            if hasattr(self, 'splitter') and self.splitter is not None:
                self.splitter.setOrientation(Qt.Vertical if narrow else Qt.Horizontal)
                # When vertical, give right pane more stretch
                if not narrow:
                    self.splitter.setStretchFactor(0, 1)
                    self.splitter.setStretchFactor(1, 2)
        except Exception:
            pass
        self.setStyleSheet(self._compact_styles if narrow else self._regular_styles)

    def resizeEvent(self, event):
        self._apply_responsive_layout()
        super().resizeEvent(event)

    # ================= Behavior (unchanged) =================
    def on_main_category_selected(self):
        index = self.cat_list.currentRow()
        if index >= 0 and index < len(self.categories):
            self.selected_main_id = self.categories[index][0]
            self.refresh_subcategories()

        # Handle Metal Type visibility
        selected_name = self.categories[index][1].strip().lower()
        is_raw_material = selected_name == "raw material"

        self.metal_type_label.setVisible(is_raw_material)
        self.fields["metal_type"].setVisible(is_raw_material)
        self.fields["metal_type"].setEnabled(is_raw_material)

        if not is_raw_material:
            self.fields["metal_type"].setCurrentIndex(0)

    def on_sub_category_selected(self):
        index = self.subcat_list.currentRow()
        if index >= 0 and index < len(self.subcategories):
            self.selected_sub_id = self.subcategories[index][0]
            self.refresh_items()

    def on_item_selected(self):
        index = self.item_list.currentRow()
        if index >= 0 and index < len(self.items):
            doc_id, data = self.items[index]
            for key, field in self.fields.items():
                if isinstance(field, QComboBox):
                    val = data.get(key, "")
                    idx = field.findText(val)
                    field.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    field.setText(str(data.get(key, "")))
            # Enable/disable metal_type field based on current main category
            main_index = self.cat_list.currentRow()
            if main_index >= 0:
                selected_name = self.categories[main_index][1].strip().lower()
                is_raw_material = selected_name == "raw material"
                self.fields["metal_type"].setEnabled(is_raw_material)
                self.fields["metal_type"].setVisible(is_raw_material)
                self.metal_type_label.setVisible(is_raw_material)
            for dim in ["length", "width", "height", "weight"]:
                unit_cb = self.unit_fields.get(dim + "_unit")
                unit = data.get(dim + "_unit", "Ft" if dim != "weight" else "kg")
                if unit_cb:
                    idx = unit_cb.findText(unit)
                    unit_cb.setCurrentIndex(idx if idx >= 0 else 0)

    def validate_fields(self):
        length = self.fields["length"].text().strip()
        width = self.fields["width"].text().strip()
        height = self.fields["height"].text().strip()
        count = sum([bool(length), bool(width), bool(height)])
        if count < 2:
            QMessageBox.critical(self, "Validation Error", "At least two of Length, Width, Height must be provided.")
            return False
        try:
            float(length or 0)
            float(width or 0)
            float(height or 0)
            float(self.fields["weight"].text().strip() or 0)
            int(self.fields["gauge"].text().strip())
            int(self.fields["selling_price"].text().strip())
            int(self.fields["reorder_qty"].text().strip())
            for qty in self.qty_fields.values():
                int(qty.text().strip() or 0)
        except ValueError:
            QMessageBox.critical(self, "Validation Error", "Check your numeric fields (dimensions, prices, weight, qty).")
            return False
        return True

    def get_item_data(self):
        return {
            "item_code": self.fields["item_code"].text() or self.generate_code(),
            "name": self.fields["name"].text().strip(),
            "length": float(self.fields["length"].text().strip() or 0),
            "width": float(self.fields["width"].text().strip() or 0),
            "height": float(self.fields["height"].text().strip() or 0),
            "weight": float(self.fields["weight"].text().strip() or 0),
            "length_unit": self.unit_fields["length_unit"].currentText(),
            "width_unit": self.unit_fields["width_unit"].currentText(),
            "height_unit": self.unit_fields["height_unit"].currentText(),
            "weight_unit": self.unit_fields["weight_unit"].currentText(),
            "gauge": int(self.fields["gauge"].text().strip() or 0),
            "metal_type": self.fields["metal_type"].currentText() if self.fields["metal_type"].isEnabled() else "",
            "selling_price": int(self.fields["selling_price"].text().strip() or 0),
            "reorder_qty": int(self.fields["reorder_qty"].text().strip() or 0),
            "sub_id": self.selected_sub_id,
        }

    def fetch_colors(self):
        doc = db.collection("meta").document("colors").get()
        return doc.to_dict().get("pc_colors", [])

    def clear_fields(self):
        for key, field in self.fields.items():
            if isinstance(field, QComboBox):
                field.setCurrentIndex(0)
            else:
                field.setText("")
        for cb in self.unit_fields.values():
            cb.setCurrentIndex(0)
        for qty_input in self.qty_fields.values():
            qty_input.setText("")

    def refresh_categories(self):
        loader = self.show_loader(self, "Loading Categories", "Fetching categories...")
        self.cat_list.clear()
        self.categories = []
        for doc in db.collection("product_main_categories").stream():
            data = doc.to_dict()
            self.categories.append((doc.id, data["name"]))
            self.cat_list.addItem(data["name"])
        loader.close()

    def refresh_subcategories(self):
        loader = self.show_loader(self, "Loading Categories", "Fetching subcategories...")
        self.subcat_list.clear()
        self.subcategories = []
        if not self.selected_main_id:
            loader.close()
            return
        for doc in db.collection("product_sub_categories").where("main_id", "==", self.selected_main_id).stream():
            data = doc.to_dict()
            self.subcategories.append((doc.id, data["name"]))
            self.subcat_list.addItem(data["name"])
        loader.close()

    def refresh_items(self):
        loader = self.show_loader(self, "Loading Categories", "Refreshing Items...")
        self.item_list.clear()
        self.items = []
        if not self.selected_sub_id:
            loader.close()
            return
        query = db.collection("products").where("sub_id", "==", self.selected_sub_id)
        for doc in query.stream():
            data = doc.to_dict()
            self.items.append((doc.id, data))
            self.item_list.addItem(f"{data.get('item_code', '')} - {data.get('name', '')}")
        loader.close()

    def add_category(self):
        name = self.cat_input.text().strip()
        if name:
            db.collection("product_main_categories").add({"name": name})
            self.cat_input.clear()
            self.refresh_categories()

    def edit_category(self):
        index = self.cat_list.currentRow()
        name = self.cat_input.text().strip()
        if index >= 0 and name:
            doc_id = self.categories[index][0]
            db.collection("product_main_categories").document(doc_id).update({"name": name})
            self.refresh_categories()

    def delete_category(self):
        index = self.cat_list.currentRow()
        if index >= 0:
            doc_id = self.categories[index][0]
            db.collection("product_main_categories").document(doc_id).delete()
            self.refresh_categories()

    def add_subcategory(self):
        name = self.subcat_input.text().strip()
        if name and self.selected_main_id:
            db.collection("product_sub_categories").add({"name": name, "main_id": self.selected_main_id})
            self.subcat_input.clear()
            self.refresh_subcategories()

    def edit_subcategory(self):
        index = self.subcat_list.currentRow()
        name = self.subcat_input.text().strip()
        if index >= 0 and name:
            doc_id = self.subcategories[index][0]
            db.collection("product_sub_categories").document(doc_id).update({"name": name})
            self.refresh_subcategories()

    def delete_subcategory(self):
        index = self.subcat_list.currentRow()
        if index >= 0:
            doc_id = self.subcategories[index][0]
            db.collection("product_sub_categories").document(doc_id).delete()
            self.refresh_subcategories()

    def add_item(self):
        loader = self.show_loader(self, "Adding Item...", "Please wait...")

        if not self.selected_sub_id:
            QMessageBox.critical(self, "Error", "Select a sub-category first.")
            loader.close()
            return

        if not self.validate_fields():
            loader.close()
            return

        # Check again for duplicate item_code
        new_code = self.fields["item_code"].text().strip() or self.generate_code()
        duplicate = db.collection("products").where("item_code", "==", new_code).get()
        if duplicate:
            QMessageBox.critical(self, "Duplicate Code", f"Item code {new_code} already exists.")
            loader.close()
            return

        # Set the code
        self.fields["item_code"].setText(new_code)
        item_data = self.get_item_data()
        item_data.pop("qty", None)  # Don't set qty yet

        # Add item first
        doc_ref = db.collection("products").add(item_data)[1]

        # Prompt for qty
        confirm = QMessageBox.question(
            self,
            "Add Opening Quantity",
            "Do you want to define opening quantity for this product?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            qty = self.get_qty_per_branch_and_color()
            if qty:
                doc_ref.update({"qty": qty})

        self.refresh_items()
        self.clear_fields()
        loader.close()

    def edit_item(self):
        loader = self.show_loader(self, "Loading Categories", "Editing Item...")
        index = self.item_list.currentRow()
        if index >= 0 and self.validate_fields():
            doc_id = self.items[index][0]
            data = self.get_item_data()
            data.pop("qty", None)  # prevent qty update on edit
            db.collection("products").document(doc_id).update(data)
            self.refresh_items()
        loader.close()

    def delete_item(self):
        loader = self.show_loader(self, "Loading Categories", "Deleting Item...")
        index = self.item_list.currentRow()
        if index >= 0:
            doc_id = self.items[index][0]
            db.collection("products").document(doc_id).delete()
            self.refresh_items()
            self.clear_fields()
        loader.close()

    def import_inventory(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Excel File", "", "Excel Files (*.xlsx *.xls)")
        loader = self.show_loader(self, "Loading", "Importing Inventory...")

        if file_path:
            df = pd.read_excel(file_path)
            products = {}

            for _, row in df.iterrows():
                item_code = str(row.get("item_code")).strip()
                if not item_code or pd.isna(item_code):
                    continue

                # 🔍 Subcategory existence check and create if missing
                sub_id = row.get("sub_id", self.selected_sub_id)
                if sub_id and not db.collection("product_sub_categories").document(sub_id).get().exists:
                    main_cat_name = str(row.get("main_category", "")).strip()
                    main_cat_docs = db.collection("product_main_categories").where("name", "==", main_cat_name).get()

                    if main_cat_docs:
                        main_id = main_cat_docs[0].id
                    else:
                        main_id = ""  # fallback if not found

                    db.collection("product_sub_categories").document(sub_id).set({
                        "name": "Missing Subcategory (Rename It)",
                        "main_id": main_id
                    })

                if item_code not in products:
                    products[item_code] = {
                        "item_code": item_code,
                        "name": str(row.get("name", "")).strip(),
                        "length": float(row.get("length", 0) or 0),
                        "width": float(row.get("width", 0) or 0),
                        "height": float(row.get("height", 0) or 0),
                        "weight": float(row.get("weight", 0) or 0),
                        "length_unit": str(row.get("length_unit", "")).strip(),
                        "width_unit": str(row.get("width_unit", "")).strip(),
                        "height_unit": str(row.get("height_unit", "")).strip(),
                        "weight_unit": str(row.get("weight_unit", "")).strip(),
                        "gauge": int(row.get("gauge", 0) or 0),
                        "metal_type": str(row.get("metal_type", "")).strip(),
                        "selling_price": int(row.get("selling_price", 0) or 0),
                        "reorder_qty": int(row.get("reorder_qty", 0) or 0),
                        "sub_id": sub_id,
                        "qty": {}
                    }

                # 🧩 Handle qty dictionary structure
                branch = str(row.get("branch", "")).strip()
                color = str(row.get("color", "")).strip()
                condition = str(row.get("condition", "New")).strip()
                quantity = int(row.get("qty", 0) or 0)

                if branch and color and condition:
                    prod_qty = products[item_code]["qty"]
                    if branch not in prod_qty:
                        prod_qty[branch] = {}
                    if color not in prod_qty[branch]:
                        prod_qty[branch][color] = {}
                    prod_qty[branch][color][condition] = quantity

            # ⬆ Upload all grouped products
            for product in products.values():
                db.collection("products").add(product)

            QMessageBox.information(self, "Success", f"{len(products)} items imported successfully.")
        loader.close()

    def generate_code(self):
        from firebase_admin import firestore
        counter_ref = db.collection("meta").document("item_code_counter")
        transaction = firestore.client().transaction()

        @firestore.transactional
        def increment_code(trans):
            snapshot = counter_ref.get(transaction=trans)
            last_code = snapshot.get("last_code") or 1000
            new_code = last_code + 1
            trans.update(counter_ref, {"last_code": new_code})
            return str(new_code)

        return increment_code(transaction)

    def get_qty_per_branch_and_color(self):
        colors = self.fetch_colors()
        conditions = ["New", "Used", "Bad"]
        if not colors:
            QMessageBox.warning(self, "No Colors", "No colors found in meta/colors.")
            return {}

        qty_data = {}

        for branch in self.branches:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Enter Qty for {branch}")
            dialog.setMinimumWidth(520)

            layout = QVBoxLayout(dialog)

            heading = QLabel(f"Branch: {branch}")
            heading.setObjectName("DialogHeading")
            layout.addWidget(heading)

            form = QFormLayout()
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            input_map = {}  # color -> condition -> input

            for color in colors:
                row = QHBoxLayout()
                input_map[color] = {}

                for cond in conditions:
                    input_field = QLineEdit()
                    input_field.setPlaceholderText(f"{cond}: 0")
                    input_field.setFixedWidth(90)
                    input_field.setMinimumHeight(32)
                    input_map[color][cond] = input_field
                    row.addWidget(input_field)

                form.addRow(QLabel(f"{color}:") , row)

            layout.addLayout(form)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            if dialog.exec_() == QDialog.Accepted:
                branch_data = {}
                for color, cond_inputs in input_map.items():
                    color_data = {}
                    for cond, input_field in cond_inputs.items():
                        try:
                            qty = int(input_field.text().strip() or 0)
                            if qty > 0:
                                color_data[cond] = qty
                        except ValueError:
                            pass
                    if color_data:
                        branch_data[color] = color_data
                if branch_data:
                    qty_data[branch] = branch_data

        return qty_data
