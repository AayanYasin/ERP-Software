import asyncio
if not hasattr(asyncio, "coroutine"):
    # no-op decorator so old libs don't crash on Python 3.12+
    asyncio.coroutine = lambda f: f
    
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget,
    QComboBox, QGridLayout, QMessageBox, QFileDialog, QProgressDialog, QApplication,
    QDialog, QFormLayout, QDialogButtonBox, QFrame, QSplitter, QSizePolicy, QCompleter, QShortcut
)
from PyQt5.QtCore import Qt, QSize, QUrl
from PyQt5.QtWidgets import QScrollArea, QDialog, QVBoxLayout
from PyQt5.QtGui import QIcon, QKeySequence, QDesktopServices
from PyQt5 import QtWebEngineWidgets
from PyQt5.QtWebEngineWidgets import QWebEngineView
from firebase.config import db
import pandas as pd



from firebase_admin import storage
import datetime
import os

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
        
        self.showMaximized()

        self.setup_ui()
        self._setup_name_autocomplete()
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
            
        # --- Quick Product Finder (by Item Code) ---
        search_row = QHBoxLayout()
        # search_row.setSpacing(6)
        # search_row.setContentsMargins(0, 0, 0, 0)
        self.search_code_input = QLineEdit()
        self.search_code_input.setPlaceholderText("Enter Item Code…")
        self.search_code_input.setFixedWidth(180)

        search_btn = self._btn("Find", self.search_product_by_code, kind="subtle")

        search_row.addWidget(self.search_code_input)
        search_row.addWidget(search_btn)
        header_row.addLayout(search_row)

        
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
        
        actions.addWidget(self._btn("Add Image", self.add_image_to_firebase, kind="subtle"))
        
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
        
        # --- Edit Qty button (admin or permission-based) ---
        if self.is_admin or "can_edit_popup_qty" in self.user_data.get("extra_perm", []):
            edit_qty_btn = self._btn("Edit Qty", self.edit_item_qty, kind="subtle")
        else:
            edit_qty_btn = self._btn("Edit Qty", self.show_not_allowed_warning, kind="subtle")

        actions.addWidget(edit_qty_btn)
        
        actions.addWidget(delete_item_btn)

        actions.addWidget(self._btn("Clear", self.clear_fields, kind="subtle"))
        right_lay.addLayout(actions)

        # Start in the right mode for current size
        self._apply_responsive_layout()
        
    # ================= FIREBASE STORAGE UPLOAD =================
    def upload_to_firebase_storage(self, local_path, item_code=None):
        """
        Uploads a file to Firebase Storage (using the initialized Firebase Admin app).
        """
        try:
            # Use the same initialized app and credentials
            bucket = storage.bucket("danish-brothers---erp-so-382b6.firebasestorage.app")

            base = os.path.basename(local_path)
            remote_path = f"products/{item_code}/{base}" if item_code else f"products/{base}"

            blob = bucket.blob(remote_path)
            blob.upload_from_filename(local_path)

            # Optional: Generate signed download URL (valid for 1 year)
            url = blob.generate_signed_url(
                expiration=datetime.timedelta(days=365),
                method="GET"
            )

            return url

        except Exception as e:
            QMessageBox.critical(self, "Firebase Upload Failed", str(e))
            return None


    def add_image_to_firebase(self):
        """
        Lets user pick an image and upload to Firebase Storage.
        """
        index = self.item_list.currentRow()
        if index < 0 or index >= len(self.items):
            QMessageBox.warning(self, "No Product Selected", "Select a product in the list first.")
            return

        doc_id, data = self.items[index]
        item_code = (str(data.get("item_code") or "").strip()) or "Unassigned"

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif);;All Files (*)"
        )
        if not file_path:
            return

        base = os.path.basename(file_path)
        reply = QMessageBox.question(
            self,
            "Confirm Upload",
            f"Upload '{base}' to Firebase Storage and attach to product '{item_code}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        loader = self.show_loader(self, "Uploading", "Uploading image to Firebase Storage…")

        try:
            url = self.upload_to_firebase_storage(file_path, item_code)
            if not url:
                QMessageBox.critical(self, "Upload Failed", "Could not upload the image.")
                return

            # Save link to Firestore
            db.collection("products").document(doc_id).update({"image_url": url})

            # # Reflect in UI
            # if "image_url" in self.fields:
            #     self.fields["image_url"].setText(url)

            QMessageBox.information(self, "Image Added", "Upload complete and URL saved.")
            
            self.refresh_items()
            
            # Reflect in UI
            if "image_url" in self.fields:
                self.fields["image_url"].setText(url)
        except Exception as e:
            QMessageBox.critical(self, "Firebase Upload Failed", str(e))
        finally:
            loader.close()

    # ================= Helpers (no logic change) =================
    def _fetch_name_autocomplete_keys(self):
        """Read the autocomplete source array from meta/product_autocomplete_list.keys."""
        try:
            snap = db.collection("meta").document("product_autocomplete_list").get()
            data = snap.to_dict() or {}
            keys = data.get("keys", []) or []
            # normalize to strings and strip
            return sorted({str(k).strip() for k in keys if str(k).strip()})
        except Exception as e:
            print("Autocomplete load error:", e)
            return []

    def _setup_name_autocomplete(self):
        """Attach a QCompleter to the Name field using keys from meta."""
        try:
            keys = self._fetch_name_autocomplete_keys()
            name_edit = self.fields.get("name")
            if not isinstance(name_edit, QLineEdit):
                return
            completer = QCompleter(keys, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            # show suggestions that contain the substring, not just prefix:
            try:
                completer.setFilterMode(Qt.MatchContains)
            except Exception:
                pass  # older Qt fallback; prefix matching will still work
            completer.setCompletionMode(QCompleter.PopupCompletion)
            name_edit.setCompleter(completer)
            self._name_completer = completer  # keep a ref to update later
        except Exception as e:
            print("Autocomplete setup error:", e)

    def _refresh_name_autocomplete_if_needed(self, new_name: str):
        """
        Ensure the new name is in meta/product_autocomplete_list.keys and refresh the completer.
        Uses a simple read-modify-write to avoid extra deps.
        """
        try:
            new_name = (new_name or "").strip()
            if not new_name:
                return

            doc_ref = db.collection("meta").document("product_autocomplete_list")
            snap = doc_ref.get()
            data = snap.to_dict() or {}
            keys = set(data.get("keys", []) or [])
            # Insert case-sensitively but avoid dupes (normalize compare)
            if new_name not in keys and new_name.lower() not in {k.lower() for k in keys}:
                keys.add(new_name)
                doc_ref.set({"keys": sorted(keys)}, merge=True)

            # Update the attached completer's model
            if hasattr(self, "_name_completer"):
                try:
                    self._name_completer.model().setStringList(sorted(keys))
                except Exception:
                    # recreate if model is not a QStringListModel
                    self._setup_name_autocomplete()
        except Exception as e:
            print("Autocomplete update error:", e)

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
            
        self.fields["gauge"].setPlaceholderText("Gauge in mm (e.g. 0.8)")

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
            unit_cb.addItems(["Inch", "Ft", "mm"])
            self.unit_fields[dim + "_unit"] = unit_cb
            grid.addWidget(unit_cb, i + 2, 3)

        # Weight unit
        # grid.addWidget(QLabel("Weight Unit:"), row - 1, 2)
        # Add Calculate Button next to Weight field
        weight_unit_cb = QComboBox()
        weight_unit_cb.addItems(["kg", "g"])
        self.unit_fields["weight_unit"] = weight_unit_cb
        grid.addWidget(weight_unit_cb, row - 1, 2)
        self.calculate_btn = self._btn("=⚖️", self.open_calculate_dialog, kind="primary")
        grid.addWidget(self.calculate_btn, row - 1, 3)
        
        lab_img = QLabel("Image:")
        grid.addWidget(lab_img, row, 0)
        img_entry = QLineEdit()
        img_entry.setPlaceholderText("https://… (public IMAGE URL)")
        self.fields["image_url"] = img_entry
        grid.addWidget(img_entry, row, 1)
        # --- Add Open Image button ---
        open_img_btn = self._btn("View Image", self.open_image_url, kind="subtle")
        grid.addWidget(open_img_btn, row, 2)
        row += 1

        # Instructional label
        hint = QLabel("Qty input will be prompted per branch and color when saving.")
        hint.setStyleSheet("font-style: italic; color: #6b7280;")
        grid.addWidget(hint, row, 0, 1, 4)

        return grid

    def convert_to_inch(self, value, unit):
        """Convert the value to inches if the unit is in mm or ft."""
        if unit == "Ft":
            return value * 12  # Convert feet to inches
        elif unit == "mm":
            return value * 0.0393701  # Convert mm to inches
        else:
            return value  # No conversion for inch

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
        
    def open_calculate_dialog(self):

        # Create the dialog box
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Shelf Type")
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)

        # Heading Label
        heading = QLabel("Select Shelf Type to Calculate:")
        layout.addWidget(heading)

        # --- Auto-close logic --- 
        def calculate_and_close(length_add, width_add, height_add, btn_type):
            self.calculate_weight(length_add, width_add, height_add, btn_type)
            dialog.accept()  # ✅ closes the popup immediately

        # Buttons for options
        plain_shelf_btn = self._btn("Plain Shelf", lambda: calculate_and_close(1.75, 3, 1, "pln_shelf"), kind="subtle")
        deluxe_shelf_btn = self._btn("Deluxe Shelf", lambda: calculate_and_close(1.75, 6, 1, "dlx_shelf"), kind="subtle")
        # New button for super deluxe shelf
        super_deluxe_shelf_btn = self._btn("Super Deluxe Shelf", lambda: calculate_and_close(1.75, 3.5, 1, "spr_dlx_shelf"), kind="subtle")
        
        # New button for foresupport shelf
        foresupport_shelf_btn = self._btn("Foresupport Shelf", lambda: calculate_and_close(3, 3, 1, "fr_sp_shelf"), kind="subtle")
        
        # Remove pole and bracket buttons
        # Remove these two
        # pole_btn = self._btn("Pole", lambda: calculate_and_close(0, 0, 0), kind="subtle")
        bracket_btn = self._btn("Bracket", lambda: calculate_and_close(1.5, 1.5, 1, "bracket"), kind="subtle")
        
        # Add new buttons for Foursupport Angle and Wallpost
        foursupport_angle_btn = self._btn("Foursupport Angle", lambda: self.calculate_foursupport_angle(), kind="subtle")
        wallpost_btn = self._btn("Wallpost", lambda: self.calculate_wallpost(), kind="subtle")
        
        # Add buttons to layout
        layout.addWidget(plain_shelf_btn)
        layout.addWidget(deluxe_shelf_btn)
        layout.addWidget(super_deluxe_shelf_btn)
        layout.addWidget(bracket_btn)
        layout.addWidget(foresupport_shelf_btn)
        layout.addWidget(foursupport_angle_btn)
        layout.addWidget(wallpost_btn)

        # Execute dialog
        dialog.exec_()
          
    def calculate_foursupport_angle(self):
        # Get gauge value from the user input, defaulting to 0 if invalid
        try:
            gauge_mm = int(self.fields["gauge"].text().strip())
        except ValueError:
            gauge_mm = 0  # Default to 0 if gauge is empty or invalid
        
        # Implement the foursupport angle calculation logic
        angle_cut = 17  # Default angle cut
        length = float(self.fields["length"].text().strip())
        width = float(self.fields["width"].text().strip())
        
        # Adjust angle cut if size is 2x2
        if length == 2 and width == 2:
            angle_cut = 13  # Change angle cut for 2x2 size
        
        # Get height value and its unit
        height = float(self.fields["height"].text().strip())
        height_unit = self.unit_fields["height_unit"].currentText()

        # Convert height to feet if necessary
        if height_unit != "Ft":
            if height_unit == "Inch":
                height = height / 12  # Convert inches to feet
            elif height_unit == "mm":
                height = height * 0.00328084  # Convert mm to feet

        # Formula for Foursupport Angle
        weight = ((32 * 0.729 * gauge_mm) / angle_cut) / 8 * height
        
        weight_unit = self.unit_fields["weight_unit"].currentText()

        # If weight unit is grams (g), multiply by 1000 to convert to grams
        if weight_unit == "g":
            weight *= 1000

        # Set the calculated weight back to the weight field
        self.fields["weight"].setText(f"{weight:.2f}")


    def calculate_wallpost(self):
        # Get gauge value from the user input, defaulting to 0 if invalid
        try:
            gauge_mm = int(self.fields["gauge"].text().strip())
        except ValueError:
            gauge_mm = 0  # Default to 0 if gauge is empty or invalid
        
        # Implement the wallpost calculation logic
        angle_cut = 14  # Default angle cut
        width = float(self.fields["width"].text().strip())
        
        # # Adjust angle cut if width is 1.75
        # if width == 1.75:
        #     angle_cut = 13  # Change angle cut for 1.75 width
        
        # Get height value and its unit
        height = float(self.fields["height"].text().strip())
        height_unit = self.unit_fields["height_unit"].currentText()

        # Convert height to feet if necessary
        if height_unit != "Ft":
            if height_unit == "Inch":
                height = height / 12  # Convert inches to feet
            elif height_unit == "mm":
                height = height * 0.00328084  # Convert mm to feet

        # Formula for Wallpost
        weight = ((32 * 0.729 * gauge_mm) / angle_cut) / 8 * height
        
        weight_unit = self.unit_fields["weight_unit"].currentText()

        # If weight unit is grams (g), multiply by 1000 to convert to grams
        if weight_unit == "g":
            weight *= 1000

        # Set the calculated weight back to the weight field
        self.fields["weight"].setText(f"{weight:.2f}")

            
    def calculate_weight(self, length_add, width_add, height_add, btn_type=""):
        # Get current item dimensions and gauge value
        try:
            length = float(self.fields["length"].text().strip())
        except ValueError:
            length = 0.0  # Default to 0 if length is empty or invalid

        try:
            width = float(self.fields["width"].text().strip())
        except ValueError:
            width = 0.0  # Default to 0 if width is empty or invalid

        # Check for empty height field and assign 0 if empty or invalid
        try:
            height = float(self.fields["height"].text().strip())
        except ValueError:
            height = 0.0 # Default to 0 if height is empty or invalid

        # Get the unit for each dimension (Length, Width, Height)
        length_unit = self.unit_fields["length_unit"].currentText()
        width_unit = self.unit_fields["width_unit"].currentText()
        height_unit = self.unit_fields["height_unit"].currentText()

        # Convert the units to inches if not already in inches
        length = self.convert_to_inch(length, length_unit)
        width = self.convert_to_inch(width, width_unit)
        height = self.convert_to_inch(height, height_unit)

        # Get gauge value from the user input, defaulting to 0 if invalid
        try:
            gauge_mm = float(self.fields["gauge"].text().strip())
        except ValueError:
            gauge_mm = 0  # Default to 0 if gauge is empty or invalid

        # Calculate weight
        weight = ((length + length_add) * (width + width_add) * (height + height_add) / 144) * 0.729 * gauge_mm
        
        if btn_type=="bracket":
            weight /= 2

        # Get the weight unit (g or kg)
        weight_unit = self.unit_fields["weight_unit"].currentText()

        # If weight unit is grams (g), multiply by 1000 to convert to grams
        if weight_unit == "g":
            weight *= 1000

        # Set the calculated weight back to the weight field
        self.fields["weight"].setText(f"{weight:.2f}")
        
    def open_image_url(self):
        """Opens the image URL from the image_url field."""
        url = self.fields["image_url"].text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Please enter an image URL first.")
            return

        # Option 1: Open in default browser
        # QDesktopServices.openUrl(QUrl(url))

        # --- Optional Option 2: open in a small popup window ---
        # Uncomment to use a popup viewer instead of browser
        # """
        dialog = QDialog(self)
        dialog.setWindowTitle("Image Preview")
        dialog.resize(600, 400)
        layout = QVBoxLayout(dialog)
        viewer = QWebEngineView(dialog)
        viewer.setUrl(QUrl(url))
        layout.addWidget(viewer)
        dialog.exec_()
        # """


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
            float(self.fields["gauge"].text().strip() or 0)
            int(self.fields["selling_price"].text().strip() or 0)
            int(self.fields["reorder_qty"].text().strip() or 100)
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
            "gauge": float(self.fields["gauge"].text().strip() or 0),
            "metal_type": self.fields["metal_type"].currentText() if self.fields["metal_type"].isEnabled() else "",
            "selling_price": int(self.fields["selling_price"].text().strip() or 0),
            "reorder_qty": int(self.fields["reorder_qty"].text().strip() or 0),
            "sub_id": self.selected_sub_id,
            "image_url": self.fields["image_url"].text().strip(),
        }

    def fetch_colors(self):
        doc = db.collection("meta").document("colors").get()
        return doc.to_dict().get("pc_colors", [])

    def clear_fields(self):
        """Clear all input fields and reset item selection state."""
        # Temporarily block signals to avoid triggering repopulation
        self.item_list.blockSignals(True)

        # Clear text fields
        for key, field in self.fields.items():
            if isinstance(field, QComboBox):
                field.setCurrentIndex(0)
            else:
                field.setText("")

        # Reset unit dropdowns
        for cb in self.unit_fields.values():
            cb.setCurrentIndex(0)

        # Reset quantity inputs
        for qty_input in self.qty_fields.values():
            qty_input.setText("")

        # Deselect current product so on_item_selected() doesn't repopulate fields later
        self.item_list.clearSelection()
        self.selected_main_id = None
        self.selected_sub_id = None

        # Re-enable signals
        self.item_list.blockSignals(False)

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
        
        # Open the quantity input popup and ensure it completes
        qty = self.get_qty_per_branch_and_color()
        
        # Proceed only if the user provides the quantity (i.e., does not cancel)
        if qty:
            # Set default selling price if not provided
            selling_price = int(self.fields["selling_price"].text().strip() or 0)
            self.fields["selling_price"].setText(str(selling_price))

            # Set item code and check for duplicates
            new_code = self.fields["item_code"].text().strip() or self.generate_code()
            # Check for duplicate item code before adding item to Firebase
            duplicate = db.collection("products").where("item_code", "==", new_code).get()
            if duplicate:
                QMessageBox.critical(self, "Duplicate Code", f"Item code {new_code} already exists.")
                loader.close()
                return

            self.fields["item_code"].setText(new_code)

            # Create item data but do not add it to the database yet
            item_data = self.get_item_data()

            # Add item to the database first (without item code initially)
            doc_ref = db.collection("products").add(item_data)[1]  # Add item to Firestore
            
            # Now that the item is added, update the item code in Firestore
            doc_ref.update({"item_code": new_code})  # Ensure the item code is updated in Firebase
            
            # Now update the qty after the item is confirmed in the database
            doc_ref.update({"qty": qty})  # Update with the quantity

            # Update the autocomplete list & refresh the completer
            self._refresh_name_autocomplete_if_needed(item_data.get("name", ""))

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
        """Handle quantity input for each branch using separate pop-ups and navigation."""
        colors = self.fetch_colors()
        conditions = ["New", "Used", "Bad"]
        if not colors:
            QMessageBox.warning(self, "No Colors", "No colors found in meta/colors.")
            return {}

        qty_data = {}
        terminated = {"flag": False}  # mutable flag to break recursion

        def show_branch_popup(branch_index):
            # If user terminated earlier, stop completely
            if terminated["flag"]:
                return

            branch = self.branches[branch_index]
            input_map = {}

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Enter Qty for Branch: {branch}")
            dialog.setMinimumWidth(520)
            dialog.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
            dialog.setModal(True)

            layout = QVBoxLayout(dialog)

            # ===== Top Row (Heading + Terminate) =====
            top_row = QHBoxLayout()
            heading = QLabel(f"Branch: {branch}")
            heading.setObjectName("DialogHeading")
            top_row.addWidget(heading)

            terminate_btn = QPushButton("Terminate")
            terminate_btn.setObjectName("Danger")
            terminate_btn.setFixedHeight(28)
            terminate_btn.setStyleSheet("QPushButton { background-color: #fee2e2; color: #b91c1c; border-radius: 6px; padding: 4px 10px; }"
                                        "QPushButton:hover { background-color: #fecaca; }")
            top_row.addStretch(1)
            top_row.addWidget(terminate_btn)
            layout.addLayout(top_row)

            # ===== Scrollable area =====
            scroll_area = QScrollArea(dialog)
            scroll_area.setWidgetResizable(True)
            form_widget = QWidget()
            form_layout = QFormLayout(form_widget)
            form_layout.setHorizontalSpacing(12)
            form_layout.setVerticalSpacing(8)

            # Input fields
            for color in colors:
                row = QHBoxLayout()
                input_map[color] = {}
                for cond in conditions:
                    input_field = QLineEdit()
                    input_field.setPlaceholderText(cond)
                    input_field.setFixedWidth(90)
                    input_field.setMinimumHeight(32)
                    input_map[color][cond] = input_field
                    row.addWidget(input_field)
                form_layout.addRow(QLabel(f"{color}:"), row)

            scroll_area.setWidget(form_widget)
            layout.addWidget(scroll_area)

            # ===== Helpers =====
            def save_current_data():
                branch_data = {}
                for color, cond_inputs in input_map.items():
                    color_data = {}
                    for cond, input_field in cond_inputs.items():
                        text = input_field.text().strip()
                        color_data[cond] = int(text) if text.isdigit() else 0
                    branch_data[color] = color_data
                qty_data[branch] = branch_data

            def terminate_process():
                terminated["flag"] = True
                qty_data.clear()
                dialog.reject()
                dialog.deleteLater()

            def go_to_next():
                if terminated["flag"]:
                    return
                save_current_data()
                dialog.accept()
                dialog.deleteLater()
                if branch_index + 1 < len(self.branches):
                    QApplication.processEvents()
                    show_branch_popup(branch_index + 1)

            def go_to_prev():
                if terminated["flag"]:
                    return
                save_current_data()
                dialog.accept()
                dialog.deleteLater()
                if branch_index - 1 >= 0:
                    QApplication.processEvents()
                    show_branch_popup(branch_index - 1)

            terminate_btn.clicked.connect(terminate_process)

            # ===== Navigation Buttons =====
            button_layout = QHBoxLayout()
            if branch_index > 0:
                prev_button = QPushButton("Back")
                prev_button.clicked.connect(go_to_prev)
                button_layout.addWidget(prev_button)
            else:
                button_layout.addStretch(1)

            next_button = QPushButton("Finish" if branch_index + 1 >= len(self.branches) else "Next")
            next_button.clicked.connect(go_to_next)
            button_layout.addWidget(next_button)

            layout.addLayout(button_layout)
            
            # ===== Connect "Enter" key to "Next" button =====
            enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), dialog)
            enter_shortcut.activated.connect(next_button.click)

            # Restore any previous data
            branch_data = qty_data.get(branch, {})
            for color, cond_inputs in input_map.items():
                for cond, input_field in cond_inputs.items():
                    val = branch_data.get(color, {}).get(cond, 0)
                    input_field.setText("" if val == 0 else str(val))

            dialog.exec_()

        # Start process
        show_branch_popup(0)

        # Return None if user terminated
        if terminated["flag"]:
            return None
        return qty_data

    def edit_item_qty(self):
        """Allow admin or permitted user to edit existing product quantity via popup WITHOUT overwriting unchanged values."""
        index = self.item_list.currentRow()
        if index < 0:
            QMessageBox.warning(self, "No Selection", "Select a product to edit its quantity.")
            return

        # Get selected product data
        doc_id, data = self.items[index]
        current_qty = data.get("qty", {}) or {}

        branches = self.branches
        colors = self.fetch_colors()
        conditions = ["New", "Used", "Bad"]

        # ------------------------------------------------------------------
        # ORIGINAL POPUP UI (kept fully intact)
        # ------------------------------------------------------------------
        def open_edit_qty_popup():
            qty_changes = {}          # only changed fields will be saved
            terminated = {"flag": False}

            def show_branch_popup(branch_index):
                if terminated["flag"]:
                    return

                branch = branches[branch_index]
                input_map = {}
                initial_map = {}

                dialog = QDialog(self)
                dialog.setWindowTitle(f"Edit Qty for Branch: {branch}")
                dialog.setMinimumWidth(520)
                dialog.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
                dialog.setModal(True)

                layout = QVBoxLayout(dialog)

                # === Header + Terminate ===
                top_row = QHBoxLayout()
                heading = QLabel(f"Branch: {branch}")
                heading.setObjectName("DialogHeading")
                top_row.addWidget(heading)

                terminate_btn = QPushButton("Terminate")
                terminate_btn.setObjectName("Danger")
                terminate_btn.setFixedHeight(28)
                terminate_btn.setStyleSheet(
                    "QPushButton { background-color: #fee2e2; color: #b91c1c; "
                    "border-radius: 6px; padding: 4px 10px; }"
                    "QPushButton:hover { background-color: #fecaca; }"
                )
                top_row.addStretch(1)
                top_row.addWidget(terminate_btn)
                layout.addLayout(top_row)

                # === Scroll Area ===
                scroll_area = QScrollArea(dialog)
                scroll_area.setWidgetResizable(True)
                form_widget = QWidget()
                form_layout = QFormLayout(form_widget)
                form_layout.setHorizontalSpacing(12)
                form_layout.setVerticalSpacing(8)

                # Fields per color/condition
                for color in colors:
                    row = QHBoxLayout()
                    input_map[color] = {}
                    initial_map[color] = {}

                    for cond in conditions:
                        f = QLineEdit()
                        f.setPlaceholderText(cond)
                        f.setFixedWidth(90)
                        f.setMinimumHeight(32)

                        existing_val = (
                            current_qty
                            .get(branch, {})
                            .get(color, {})
                            .get(cond, 0)
                        )

                        shown = "" if existing_val == 0 else str(existing_val)
                        f.setText(shown)
                        input_map[color][cond] = f
                        initial_map[color][cond] = shown

                        row.addWidget(f)

                    form_layout.addRow(QLabel(f"{color}:"), row)

                scroll_area.setWidget(form_widget)
                layout.addWidget(scroll_area)

                # ------------------------------------------------------------------
                # Collect only changed values (your original data-saving logic extended)
                # ------------------------------------------------------------------
                def collect_changes():
                    for color, cond_inputs in input_map.items():
                        for cond, field in cond_inputs.items():
                            new = field.text().strip()
                            old = initial_map[color][cond]

                            # unchanged → ignore
                            if new == old:
                                continue

                            # blank text → treat as "no change"
                            if new == "":
                                continue

                            # valid integer? record as patched update
                            try:
                                val = int(new)
                            except ValueError:
                                continue

                            qty_changes.setdefault(branch, {}).setdefault(color, {})[cond] = val

                # ------------------------------------------------------------------
                # Navigation logic (unchanged)
                # ------------------------------------------------------------------
                def terminate_process():
                    terminated["flag"] = True
                    qty_changes.clear()
                    dialog.reject()
                    dialog.deleteLater()

                def go_to_next():
                    collect_changes()
                    dialog.accept()
                    dialog.deleteLater()
                    if branch_index + 1 < len(branches):
                        QApplication.processEvents()
                        show_branch_popup(branch_index + 1)

                def go_to_prev():
                    collect_changes()
                    dialog.accept()
                    dialog.deleteLater()
                    if branch_index - 1 >= 0:
                        QApplication.processEvents()
                        show_branch_popup(branch_index - 1)

                terminate_btn.clicked.connect(terminate_process)

                # === Navigation Buttons ===
                button_layout = QHBoxLayout()
                if branch_index > 0:
                    prev_button = QPushButton("Back")
                    prev_button.clicked.connect(go_to_prev)
                    button_layout.addWidget(prev_button)
                else:
                    button_layout.addStretch(1)

                next_button = QPushButton("Finish" if branch_index + 1 >= len(branches) else "Next")
                next_button.clicked.connect(go_to_next)
                button_layout.addWidget(next_button)

                layout.addLayout(button_layout)

                # Enter key = Next
                enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), dialog)
                enter_shortcut.activated.connect(next_button.click)

                dialog.exec_()

            if not branches:
                return None

            show_branch_popup(0)

            if terminated["flag"]:
                return None

            return qty_changes

        # ------------------------------------------------------------------
        # Run popup and get only changed qty fields
        # ------------------------------------------------------------------
        new_changes = open_edit_qty_popup()
        if new_changes is None:
            return

        if not new_changes:
            QMessageBox.information(self, "No Changes", "Nothing was changed.")
            return

        # ------------------------------------------------------------------
        # Confirm user wants to apply changes
        # ------------------------------------------------------------------
        confirm = QMessageBox.question(
            self,
            "Confirm Update",
            "Apply these qty changes without overwriting other quantities?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        # ------------------------------------------------------------------
        # Build Firestore dotted-path updates
        # ------------------------------------------------------------------
        updates = {}
        for branch, color_map in new_changes.items():
            for color, cond_map in color_map.items():
                for cond, val in cond_map.items():
                    updates[f"qty.{branch}.{color}.{cond}"] = val

        if not updates:
            QMessageBox.information(self, "No Changes", "Nothing was changed.")
            return

        # ------------------------------------------------------------------
        # Apply patch-update to Firestore
        # ------------------------------------------------------------------
        loader = self.show_loader(self, "Updating Qty", "Applying changes...")
        try:
            db.collection("products").document(doc_id).update(updates)
            QMessageBox.information(self, "Success", "Quantities updated without overwriting others.")
            self.refresh_items()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update qty: {e}")
        finally:
            loader.close()

    def search_product_by_code(self):
        """Find a product by its item code, select its subcategory/main category, and fill details."""
        code = self.search_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Input Required", "Please enter a product code to search.")
            return

        loader = self.show_loader(self, "Searching", f"Looking up product {code}...")

        try:
            query = db.collection("products").where("item_code", "==", code).get()
            if not query:
                QMessageBox.information(self, "Not Found", f"No product found with code {code}.")
                loader.close()
                return

            # Get the product document
            product_doc = query[0]
            product_data = product_doc.to_dict()
            sub_id = product_data.get("sub_id")

            if not sub_id:
                QMessageBox.warning(self, "Data Error", "Product found but subcategory is missing.")
                loader.close()
                return

            # Find subcategory document
            sub_doc = db.collection("product_sub_categories").document(sub_id).get()
            if not sub_doc.exists:
                QMessageBox.warning(self, "Data Error", "Product subcategory not found.")
                loader.close()
                return

            sub_data = sub_doc.to_dict()
            main_id = sub_data.get("main_id")

            # --- Select main category ---
            self.refresh_categories()
            QApplication.processEvents()
            for i, (cat_id, name) in enumerate(self.categories):
                if cat_id == main_id:
                    self.cat_list.setCurrentRow(i)
                    self.selected_main_id = main_id
                    break

            # --- Select subcategory ---
            self.refresh_subcategories()
            QApplication.processEvents()
            for i, (subcat_id, name) in enumerate(self.subcategories):
                if subcat_id == sub_id:
                    self.subcat_list.setCurrentRow(i)
                    self.selected_sub_id = sub_id
                    break

            # --- Select product item ---
            self.refresh_items()
            QApplication.processEvents()
            for i, (doc_id, data) in enumerate(self.items):
                if doc_id == product_doc.id:
                    self.item_list.setCurrentRow(i)
                    break

            # --- Fill form fields ---
            for key, field in self.fields.items():
                if isinstance(field, QComboBox):
                    val = product_data.get(key, "")
                    idx = field.findText(val)
                    field.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    field.setText(str(product_data.get(key, "")))

            for dim in ["length", "width", "height", "weight"]:
                unit_cb = self.unit_fields.get(dim + "_unit")
                unit = product_data.get(dim + "_unit", "Ft" if dim != "weight" else "kg")
                if unit_cb:
                    idx = unit_cb.findText(unit)
                    unit_cb.setCurrentIndex(idx if idx >= 0 else 0)

            # QMessageBox.information(self, "Success", f"Product {code} loaded successfully.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error fetching product: {e}")
        finally:
            loader.close()
