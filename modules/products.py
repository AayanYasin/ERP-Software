from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget,
    QComboBox, QGridLayout, QMessageBox, QFileDialog, QProgressDialog, QApplication, QDialog, QFormLayout, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from firebase.config import db
import pandas as pd

class ProductsPage(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.branches = user_data.get("branch", [])
        if isinstance(self.branches, str):
            self.branches = [self.branches]

        self.setWindowTitle("Products Management")
        self.setGeometry(200, 100, 1100, 700)
        self.setStyleSheet("background-color: #f4f6f9;")

        self.categories = []
        self.subcategories = []
        self.items = []
        self.selected_main_id = None
        self.selected_sub_id = None

        self.setup_ui()
        self.refresh_categories()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("📦 Product Setup Panel")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #2d3436;")
        layout.addWidget(title, alignment=Qt.AlignHCenter)

        main_layout = QHBoxLayout()
        layout.addLayout(main_layout)

        # Left panel: Categories
        self.left_layout = QVBoxLayout()
        main_layout.addLayout(self.left_layout, 1)

        self.cat_list = QListWidget()
        self.cat_list.itemSelectionChanged.connect(self.on_main_category_selected)
        self.left_layout.addWidget(QLabel("Main Categories:"))
        self.left_layout.addWidget(self.cat_list)
        self.cat_input = QLineEdit()
        self.left_layout.addWidget(self.cat_input)
        # self.left_layout.addLayout(self.make_button_row_3("Add", self.add_category, "Edit", self.edit_category, "Delete", self.delete_category))

        self.subcat_list = QListWidget()
        self.subcat_list.itemSelectionChanged.connect(self.on_sub_category_selected)
        self.left_layout.addWidget(QLabel("Sub Categories:"))
        self.left_layout.addWidget(self.subcat_list)
        self.subcat_input = QLineEdit()
        self.left_layout.addWidget(self.subcat_input)
        self.left_layout.addLayout(self.make_button_row_3("Add", self.add_subcategory, "Edit", self.edit_subcategory, "Delete", self.delete_subcategory))

        # Right panel: Items
        self.right_layout = QVBoxLayout()
        main_layout.addLayout(self.right_layout, 2)

        self.item_list = QListWidget()
        self.item_list.itemSelectionChanged.connect(self.on_item_selected)
        self.right_layout.addWidget(QLabel("Items:"))
        self.right_layout.addWidget(self.item_list)

        self.item_form = self.build_item_form()
        self.right_layout.addLayout(self.item_form)
        self.right_layout.addLayout(self.make_button_row("Add", self.add_item, "Edit", self.edit_item, "Delete", self.delete_item, "Clear", self.clear_fields))

        import_btn = QPushButton("📥 Import Inventory")
        import_btn.clicked.connect(self.import_inventory)
        layout.addWidget(import_btn)

    def make_button_row(self, txt1, cmd1, txt2, cmd2, txt3, cmd3, txt4, cmd4):
        row = QHBoxLayout()
        for txt, cmd in [(txt1, cmd1), (txt2, cmd2), (txt3, cmd3), (txt4, cmd4)]:
            btn = QPushButton(txt)
            btn.clicked.connect(cmd)
            btn.setStyleSheet("padding: 5px 10px;")
            row.addWidget(btn)
        return row

    def make_button_row_3(self, txt1, cmd1, txt2, cmd2, txt3, cmd3):
        row = QHBoxLayout()
        for txt, cmd in [(txt1, cmd1), (txt2, cmd2), (txt3, cmd3)]:
            btn = QPushButton(txt)
            btn.clicked.connect(cmd)
            btn.setStyleSheet("padding: 5px 10px;")
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

        # Fields before Metal Type
        labels_before_metal = [
            ("Item Code", True), ("Name", False), ("Length", False), ("Width", False),
            ("Height", False), ("Gauge", False)
        ]

        row = 0
        for label, readonly in labels_before_metal:
            grid.addWidget(QLabel(label + ":"), row, 0)
            entry = QLineEdit()
            entry.setReadOnly(readonly)
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
            grid.addWidget(QLabel(label + ":"), row, 0)
            entry = QLineEdit()
            entry.setReadOnly(readonly)
            self.fields[label.lower().replace(" ", "_")] = entry
            grid.addWidget(entry, row, 1)
            row += 1

        # Unit selectors
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
        label = QLabel("Qty input will be prompted per branch and color when saving.")
        label.setStyleSheet("font-style: italic; color: #636e72;")
        grid.addWidget(label, row, 0, 1, 4)

        return grid



    def on_main_category_selected(self):
        index = self.cat_list.currentRow()
        if index >= 0 and index < len(self.categories):
            self.selected_main_id = self.categories[index][0]
            self.refresh_subcategories()

        # Handle Metal Type visibility
        selected_name = self.categories[index][1].strip().lower()
        is_raw_material = selected_name == "raw material"

        # Correct: Set both label + combo visible
        self.metal_type_label.setVisible(is_raw_material)
        self.fields["metal_type"].setVisible(is_raw_material)
        self.fields["metal_type"].setEnabled(is_raw_material)

        # Optional: disable instead of hide
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
            # qty_data = data.get("qty", {})
            # summary = []
            # for branch, color_map in qty_data.items():
            #     for color, qty in color_map.items():
            #         summary.append(f"{branch} - {color}: {qty}")
            # if summary:
            #     QMessageBox.information(self, "Qty Summary", "\n".join(summary))

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
            return
        for doc in db.collection("product_sub_categories").where("main_id", "==", self.selected_main_id).stream():
            data = doc.to_dict()
            self.subcategories.append((doc.id, data["name"]))
            self.subcat_list.addItem(data["name"])
        loader.close()

    def refresh_items(self):
        loader = self.show_loader(self, "Loading Categories", "Refreasing Items...")
        self.item_list.clear()
        self.items = []
        if not self.selected_sub_id:
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
            dialog.setMinimumWidth(500)

            layout = QVBoxLayout(dialog)

            heading = QLabel(f"Branch: {branch}")
            heading.setStyleSheet("font-weight: bold; font-size: 14pt; margin-bottom: 10px;")
            layout.addWidget(heading)

            form = QFormLayout()
            input_map = {}  # color -> condition -> input

            for color in colors:
                row = QHBoxLayout()
                input_map[color] = {}

                for cond in conditions:
                    input_field = QLineEdit()
                    input_field.setPlaceholderText(f"{cond}: 0")
                    input_field.setFixedWidth(80)
                    input_map[color][cond] = input_field
                    row.addWidget(input_field)

                form.addRow(QLabel(f"{color}:"), row)

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
