from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QPushButton, QDialog, QListWidget, QListWidgetItem,
    QDialogButtonBox, QRadioButton, QButtonGroup, QFileDialog, QMessageBox, QCheckBox, QSpinBox, QProgressDialog, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from firebase.config import db
from fpdf import FPDF
import pandas as pd
from datetime import datetime
import os
import json  # cache

# ---------------- Worker Thread: fetch inventory from Firestore (no UI freeze) ----------------
class _InventoryLoaderWorker(QThread):
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self):
        try:
            gauges, colors = set(), set()
            main_categories = {}   # name -> id
            sub_categories = {}    # sub_id -> main_id
            all_items = []

            # main categories
            for doc in db.collection("product_main_categories").stream():
                data = doc.to_dict() or {}
                name = data.get("name", "")
                if name:
                    main_categories[name] = doc.id

            # sub categories
            for doc in db.collection("product_sub_categories").stream():
                data = doc.to_dict() or {}
                sub_categories[doc.id] = data.get("main_id")

            # products
            for doc in db.collection("products").stream():
                data = doc.to_dict() or {}
                all_items.append(data)
                gauges.add(str(data.get("gauge", "")))
                qty = data.get("qty", {}) or {}
                for branch_data in qty.values():
                    if isinstance(branch_data, dict):
                        for color_name, blob in branch_data.items():
                            if isinstance(blob, dict):
                                colors.add((color_name or "").strip().lower())

            payload = {
                "main_categories": main_categories,
                "sub_categories": sub_categories,
                "all_items": all_items,
                "gauges": sorted(gauges),
                "colors": sorted(colors),
                "main_category_names": sorted(main_categories.keys()),
            }
            self.finished_ok.emit(payload)
        except Exception as e:
            self.failed.emit(str(e))


class ViewInventory(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.is_admin = user_data.get("role") == "admin"  # Check if user is admin
        
        # Fetch admin's branches from Firestore
        admin_branches = self.get_admin_branches()
        
        # Check if current user has permission to see other branches
        if "can_see_other_branches_inventory" in user_data.get("extra_perm", []):
            # User has permission to see all branches from the admin
            self.branches = admin_branches
        else:
            # Default: Show only the user's own branches
            self.branches = user_data.get("branch", [])
        
        self.main_categories = {}      # {name: doc_id}
        self.sub_categories = {}       # {sub_id: main_id}
        self.expanded_rows = set()     # expanded item_codes
        self.include_metal_type = False
        self._offline_read_only = False  # optional external toggle

        self.show_type_column = False
        if isinstance(self.branches, str):
            self.branches = [self.branches]

        self.setWindowTitle("📊 View Inventory")
        self.resize(1100, 700)
        self.setStyleSheet("""
            QWidget { background-color: #f4f6f9; }
            QLineEdit, QComboBox {
                padding: 4px 6px; border: 1px solid #ccc; border-radius: 6px;
                background-color: white; font-size: 13px;
            }
            QPushButton { padding: 5px 12px; border-radius: 6px; background-color: #2d98da; color: white; }
            QPushButton:hover { background-color: #1e77c2; }
            QHeaderView::section { background-color: #dfe6e9; font-weight: bold; padding: 6px; border: 1px solid #b2bec3; }
            QTableWidget {  background-color: white; border: 1px solid #dcdde1; font-size: 13px; }
            QTableWidget::item { padding: 6px; }
        """)

        self.current_page = 1
        self.items_per_page = 50  # was 10 → now 50 per page

        # ----- NEW: filtered list cache + debounce + header cache -----
        self._filtered_items = []
        self._filtered_dirty = True
        from PyQt5.QtCore import QTimer  # ensure import exists at top of file
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)  # 200 ms debounce
        self._refresh_timer.timeout.connect(self.refresh_table)

        self._last_headers = None
        # --------------------------------------------------------------

        layout = QVBoxLayout(self)
        title = QLabel("📊 Inventory Overview")
        title.setAlignment(Qt.AlignHCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #2d3436; margin: 10px 0;")
        layout.addWidget(title)

        # Filters/controls
        header_layout = QHBoxLayout(); header_layout.setSpacing(10)

        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Search by Item Code or Name")
        self.search_input.setFixedWidth(250); self.search_input.textChanged.connect(self.on_filters_changed)
        header_layout.addWidget(QLabel("Search:")); header_layout.addWidget(self.search_input)
        
        self.main_category_filter = QComboBox(); self.main_category_filter.setFixedWidth(180)
        self.main_category_filter.setEditable(False); self.main_category_filter.setInsertPolicy(QComboBox.NoInsert)
        self.main_category_filter.currentTextChanged.connect(self.on_filters_changed)
        header_layout.addWidget(QLabel("Main Cat:")); header_layout.addWidget(self.main_category_filter)

        self.guage_filter = QComboBox(); self.guage_filter.setFixedWidth(100)
        self.guage_filter.setEditable(True); self.guage_filter.setInsertPolicy(QComboBox.NoInsert)
        self.guage_filter.setPlaceholderText("Gauge"); self.guage_filter.currentTextChanged.connect(self.on_filters_changed)
        header_layout.addWidget(QLabel("Gauge:")); header_layout.addWidget(self.guage_filter)
        
        self.metal_type_filter = QComboBox(); self.metal_type_filter.setFixedWidth(120)
        self.metal_type_filter.setEditable(True); self.metal_type_filter.setInsertPolicy(QComboBox.NoInsert)
        self.metal_type_filter.setPlaceholderText("Metal Type"); self.metal_type_filter.currentTextChanged.connect(self.on_filters_changed)
        self.metal_type_filter.setVisible(False)
        self.metal_type_label = QLabel("Metal Type:"); self.metal_type_label.setVisible(False)
        header_layout.addWidget(self.metal_type_label); header_layout.addWidget(self.metal_type_filter)

        self.color_filter = QComboBox(); self.color_filter.setFixedWidth(120)
        self.color_filter.setEditable(True); self.color_filter.setInsertPolicy(QComboBox.NoInsert)
        self.color_filter.setPlaceholderText("Color"); self.color_filter.currentTextChanged.connect(self.on_color_change)
        header_layout.addWidget(QLabel("Color:")); header_layout.addWidget(self.color_filter)

        self.length_filter = QLineEdit(); self.length_filter.setPlaceholderText("Length"); self.length_filter.setFixedWidth(70)
        self.length_filter.textChanged.connect(self.on_filters_changed); header_layout.addWidget(QLabel("Length:")); header_layout.addWidget(self.length_filter)
        self.width_filter = QLineEdit(); self.width_filter.setPlaceholderText("Width"); self.width_filter.setFixedWidth(70)
        self.width_filter.textChanged.connect(self.on_filters_changed); header_layout.addWidget(QLabel("Width:")); header_layout.addWidget(self.width_filter)
        self.height_filter = QLineEdit(); self.height_filter.setPlaceholderText("Height"); self.height_filter.setFixedWidth(70)
        self.height_filter.textChanged.connect(self.on_filters_changed); header_layout.addWidget(QLabel("Height:")); header_layout.addWidget(self.height_filter)

        clear_btn = QPushButton("Clear Filters"); clear_btn.clicked.connect(self.clear_filters); header_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("Export")
        if not self.is_admin and "can_imp_exp_anything" not in self.user_data.get("extra_perm", []):
            export_btn.clicked.connect(self.show_not_allowed_warning)
        else:
            export_btn.clicked.connect(self.export_inventory)
        
        header_layout.addWidget(export_btn)

        # --- OFFLINE BADGE ---
        self.offline_badge = QLabel("Showing offline inventory")
        self.offline_badge.setVisible(False)
        self.offline_badge.setStyleSheet("""
            QLabel {
                background-color: #ffd166; color: #5a3e00;
                border: 1px solid #e0a800; border-radius: 6px;
                padding: 4px 8px; font-weight: 600;
            }
        """)
        header_layout.addWidget(self.offline_badge)
        # ----------------------

        layout.addLayout(header_layout)

        # Table
        self.table = QTableWidget()
        headers = ["#", "Item Code", "Name", "Dimensions LWH", "Gauge", "Color", "Condition", "Weight", "Selling Price"] + self.branches
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self.toggle_expand_row)
        layout.addWidget(self.table)

        # Pagination
        pagination_layout = QHBoxLayout()
        self.page_label = QLabel("Page: 1"); self.page_label.setFont(QFont("Segoe UI", 10))
        self.page_spin = QSpinBox(); self.page_spin.setMinimum(1); self.page_spin.setFixedWidth(70)
        self.page_spin.setStyleSheet("padding: 4px; font-size: 13px;")
        self.page_spin.valueChanged.connect(self.on_page_change)
        pagination_layout.addStretch(); pagination_layout.addWidget(self.page_label); pagination_layout.addWidget(self.page_spin)
        layout.addLayout(pagination_layout)

        # Data holders
        self.all_items = []

        # 1) Render cached snapshot instantly (if available), 2) then refresh online in background
        self._render_from_cache_if_any()
        self.reload_async()
        
    def on_filters_changed(self, *_):
        # Mark filtered list dirty and debounce UI refresh
        self._filtered_dirty = True
        # When filters change, go back to first page
        if self.page_spin.value() != 1:
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
        self._refresh_timer.start()


    # ---------------- Offline cache helpers (no UX change) ----------------
    def show_not_allowed_warning(self):
        QMessageBox.warning(self, "Not Allowed", "You do not have permission to perform this action.")
        
    def _app_dir(self) -> str:
        base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
        root = os.path.join(base, "PlayWithAayan-ERP_Software", "cache")
        os.makedirs(root, exist_ok=True)
        return root

    def _cache_file(self) -> str:
        return os.path.join(self._app_dir(), "inventory_snapshot.json")

    def _save_cache(self, payload: dict):
        try:
            tmp = self._cache_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self._cache_file())
        except Exception:
            pass

    def _load_cache(self) -> dict:
        try:
            if os.path.exists(self._cache_file()):
                with open(self._cache_file(), "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def set_offline_mode(self, read_only: bool):
        # Toggle offline mode; close any running loader and show cache immediately
        self._offline_read_only = bool(read_only)
        if read_only:
            # close loader if visible
            try:
                if getattr(self, "_loader_dialog", None):
                    self._loader_dialog.close()
            except Exception:
                pass
            # render cache now (if not already shown)
            if not self.all_items:
                self._render_from_cache_if_any()
            # show badge
            self._set_offline_badge(True)
        else:
            # back online: hide badge
            self._set_offline_badge(False)
            # optionally refresh online again
            self.reload_async()

    # ---------------- UI loader ----------------
    def get_admin_branches(self):
        # Fetch branches from admin role document in Firestore
        try:
            admin_doc = db.collection("users").where("role", "==", "admin").limit(1).stream()
            for admin in admin_doc:
                admin_data = admin.to_dict()
                return admin_data.get("branch", [])
        except Exception as e:
            print(f"Error fetching admin branches: {e}")
            return []  # Return empty if something goes wrong
        
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

    # ---------------- Cache-first render ----------------
    def _apply_cached_filters(self, gauges, colors, main_category_names):
        self.guage_filter.clear(); self.guage_filter.addItem(""); self.guage_filter.addItems([str(g) for g in gauges])
        self.color_filter.clear(); self.color_filter.addItem(""); self.color_filter.addItems([str(c).title() for c in colors])
        self.metal_type_filter.clear(); self.metal_type_filter.addItem(""); self.metal_type_filter.addItems(["HRC", "CRC", "GP"])
        self.main_category_filter.clear()
        if main_category_names:
            main_keys = sorted(main_category_names)
            if "Finished Products" in main_keys:
                self.main_category_filter.addItems(["Finished Products"] + [k for k in main_keys if k != "Finished Products"])
            else:
                self.main_category_filter.addItems(main_keys)
            self.main_category_filter.setCurrentIndex(0)

    def _render_from_cache_if_any(self):
        cached = self._load_cache()
        if not cached:
            return
        self.main_categories = cached.get("main_categories", {})
        self.sub_categories = cached.get("sub_categories", {})
        self.all_items = cached.get("all_items", [])
        self._apply_cached_filters(
            cached.get("gauges", []),
            cached.get("colors", []),
            cached.get("main_category_names", []),
        )
        # NEW: recompute filtered list once, then paginate
        self._filtered_dirty = True
        self._ensure_filtered()
        self.page_spin.setMaximum(max(1, (len(self._filtered_items) - 1) // self.items_per_page + 1))
        self.refresh_table()
        # if we're explicitly offline, show the badge now
        if self._offline_read_only:
            self._set_offline_badge(True)

    # ---------------- Async reload (no UI freeze) ----------------
    def reload_async(self):
        # If externally marked offline, don’t hit network and do NOT show loader
        if self._offline_read_only:
            return

        self._loader = _InventoryLoaderWorker()
        self._loader.finished_ok.connect(self._on_loaded_ok)
        self._loader.failed.connect(self._on_loaded_fail)
        self._loader_dialog = self.show_loader(self, "Loading Inventory", "Fetching latest inventory…")
        self._loader.start()

    def _on_loaded_ok(self, payload: dict):
        try:
            if getattr(self, "_loader_dialog", None): self._loader_dialog.close()
        except Exception:
            pass

        # update state
        self.main_categories = payload.get("main_categories", {})
        self.sub_categories = payload.get("sub_categories", {})
        self.all_items = payload.get("all_items", [])
        self._apply_cached_filters(
            payload.get("gauges", []),
            payload.get("colors", []),
            payload.get("main_category_names", []),
        )

        # NEW: recompute filtered list once, then paginate
        self._filtered_dirty = True
        self._ensure_filtered()
        self.page_spin.setMaximum(max(1, (len(self._filtered_items) - 1) // self.items_per_page + 1))
        self.refresh_table()

        # we are online; hide badge if it was visible
        self._set_offline_badge(False)

        # persist snapshot
        self._save_cache(payload)

    def _on_loaded_fail(self, err: str):
        try:
            if getattr(self, "_loader_dialog", None): self._loader_dialog.close()
        except Exception:
            pass

        # Try cache now
        if not self.all_items:
            cached = self._load_cache()
            if cached:
                # show badge if network failed → offline fallback
                self._set_offline_badge(True)
                self._on_loaded_ok(cached)
            else:
                QMessageBox.critical(self, "Inventory", f"Could not load inventory.\n{err}")
        else:
            # already had something on screen; just indicate offline
            self._set_offline_badge(True)

    # ---------------- small helper for badge visibility ----------------
    def _set_offline_badge(self, visible: bool):
        try:
            self.offline_badge.setVisible(bool(visible))
        except Exception:
            pass

    # ---------------- The rest below keeps original logic/UX ----------------
    def format_unit(self, val, unit):
        try:
            val = float(val)
            val_str = str(int(val)) if val.is_integer() else f"{val:.2f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError):
            return "—"
        unit = str(unit).strip().lower()
        if unit in ["inch", 'in', '"']:
            return f'{val_str}"'
        elif unit in ["ft", "feet", "'"]:
            return f"{val_str}ft"
        elif unit == "mm":
            return f"{val_str}mm"
        else:
            return f"{val_str}"

    def on_page_change(self):
        self.refresh_table()
        
    def on_color_change(self, _text):
        # keep color-specific behavior (auto-expand happens in refresh_table),
        # but use the same debounced refresh path
        self.on_filters_changed()
        
    def _ensure_filtered(self):
        if self._filtered_dirty:
            self._filtered_items = self.get_filtered_items()
            self._filtered_dirty = False

    def clear_filters(self):
        self.search_input.clear()
        self.guage_filter.setCurrentIndex(0)
        self.color_filter.setCurrentIndex(0)
        self.length_filter.clear()
        self.width_filter.clear()
        self.height_filter.clear()
        self.page_spin.setValue(1)

    def get_filtered_items(self):
        keyword = self.search_input.text().lower().strip()
        gauge_filter = self.guage_filter.currentText().strip()
        metal_type_filter = self.metal_type_filter.currentText().strip().lower()
        color_filter = self.color_filter.currentText().strip().lower()
        len_filter = self.length_filter.text().strip()
        wid_filter = self.width_filter.text().strip()
        hei_filter = self.height_filter.text().strip()
        main_cat_filter = self.main_category_filter.currentText().strip()
        if not main_cat_filter:
            return []

        result = []
        for data in self.all_items:
            code = data.get("item_code", "")
            name = data.get("name", "")
            gauge = str(data.get("gauge", ""))
            length = str(data.get("length", 0))
            width = str(data.get("width", 0))
            height = str(data.get("height", 0))
            sub_id = data.get("sub_id", "")
            qty_dict = data.get("qty", {})

            # main category
            if main_cat_filter:
                main_id = self.main_categories.get(main_cat_filter)
                sub_main_id = self.sub_categories.get(sub_id)
                if not sub_main_id or sub_main_id != main_id:
                    continue

            # keyword
            if keyword and keyword not in code.lower() and keyword not in name.lower():
                continue

            # gauge
            if gauge_filter and gauge != gauge_filter:
                continue

            # dims
            try:
                if len_filter and float(length) != float(len_filter): continue
                if wid_filter and float(width) != float(wid_filter): continue
                if hei_filter and float(height) != float(hei_filter): continue
            except ValueError:
                continue

            # color in qty
            if color_filter:
                matched = False
                for branch_data in qty_dict.values():
                    for color_name, condition_dict in branch_data.items():
                        if isinstance(condition_dict, dict) and (color_name or "").strip().lower() == color_filter:
                            matched = True; break
                    if matched: break
                if not matched:
                    continue

            if self.include_metal_type and metal_type_filter:
                metal_type = (data.get("metal_type", "")).strip().lower()
                if metal_type != metal_type_filter:
                    continue

            result.append(data)
        return result

    def refresh_table(self):
        # Prevent recursive signals during rebuild
        self.table.blockSignals(True)
        self._ensure_filtered()

        # Sort filtered items by item_code numerically if possible
        def sort_key(data):
            code = str(data.get("item_code", "")).strip()
            try:
                return int(code)
            except ValueError:
                return code.lower()
        filtered = sorted(self._filtered_items, key=sort_key)

        self.page_spin.setMaximum(max(1, (len(filtered) - 1) // self.items_per_page + 1))
        self.page_label.setText(f"Page: {self.page_spin.value()}")

        # Toggle metal type column based on main category
        main_cat = self.main_category_filter.currentText().strip().lower()
        self.include_metal_type = (main_cat == "raw material")
        self.metal_type_filter.setVisible(self.include_metal_type)
        self.metal_type_label.setVisible(self.include_metal_type)

        # Build headers only if changed
        headers = ["#", "Item Code", "Name", "Dimensions LWH", "Gauge"]
        if self.include_metal_type:
            headers.append("Metal Type")
        headers += ["Color", "Condition", "Weight", "Selling Price"] + self.branches

        if getattr(self, "_last_headers", None) != headers:
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self._last_headers = headers

        self.col_index = {header: idx for idx, header in enumerate(headers)}

        # Compute slice
        start = (self.page_spin.value() - 1) * self.items_per_page
        end = start + self.items_per_page
        page_slice = filtered[start:end]

        # Freeze repaints; clear contents fast
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)

        display_index = start
        color_filter_text = self.color_filter.currentText().strip().lower()

        for data in page_slice:
            display_index += 1
            item_code = data.get("item_code", "")
            qty_dict = data.get("qty", {})
            is_expanded = item_code in self.expanded_rows

            # If a color filter is active, auto-expand rows that contain that color
            if color_filter_text:
                match_found = False
                for branch in self.branches:
                    for color in qty_dict.get(branch, {}):
                        if color_filter_text in (color or "").strip().lower():
                            match_found = True
                            break
                    if match_found:
                        break
                if match_found:
                    self.expanded_rows.add(item_code)
                    is_expanded = True
                else:
                    self.expanded_rows.discard(item_code)

            # header row
            header_row = self.table.rowCount()
            self.table.insertRow(header_row)
            header_font = QFont("Segoe UI", 10, QFont.Bold)

            l = data.get("length", 0); w = data.get("width", 0); h = data.get("height", 0)
            dims = f"{self.format_unit(l, data.get('length_unit', ''))} x " \
                f"{self.format_unit(w, data.get('width_unit', ''))} x " \
                f"{self.format_unit(h, data.get('height_unit', ''))}"
            sp = data.get("selling_price", 0)
            weight = f"{data.get('weight', 0)} {data.get('weight_unit', '')}"

            header_items = [str(display_index), item_code, data.get("name", ""), dims, str(data.get("gauge", ""))]
            if self.include_metal_type:
                header_items.append(data.get("metal_type", "—"))
            header_items += ["—", "—", weight, f"{sp:,.0f}"]

            for col, val in enumerate(header_items):
                item = QTableWidgetItem(val)
                item.setFont(header_font)
                item.setBackground(Qt.lightGray)
                self.table.setItem(header_row, col, item)

            # totals per branch (header row)
            first_branch_col = self.col_index["Selling Price"] + 1
            for i, branch in enumerate(self.branches):
                branch_total = 0
                branch_data = qty_dict.get(branch, {})
                for color, condition_data in branch_data.items():
                    if color_filter_text and color_filter_text not in (color or "").lower():
                        continue
                    if isinstance(condition_data, dict):
                        for _condition, qty in condition_data.items():
                            if isinstance(qty, (int, float)):
                                branch_total += qty
                item = QTableWidgetItem(str(branch_total))
                item.setFont(header_font)
                item.setBackground(Qt.lightGray)
                self.table.setItem(header_row, first_branch_col + i, item)

            self.table.setRowHeight(header_row, 30)

            # child rows (expanded) — skip zero-total rows
            if is_expanded:
                shown_rows = set()
                for branch in self.branches:
                    branch_data = qty_dict.get(branch, {})
                    for color, conds in branch_data.items():
                        if color_filter_text and color_filter_text not in (color or "").lower():
                            continue
                        if isinstance(conds, dict):
                            for condition in conds:
                                shown_rows.add((color, condition))

                for color, condition in sorted(shown_rows):
                    total_across_branches = 0
                    for b in self.branches:
                        q = qty_dict.get(b, {}).get(color, {}).get(condition, 0)
                        if isinstance(q, (int, float)):
                            total_across_branches += q
                    if total_across_branches == 0:
                        continue  # skip zero-only sub item

                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self.table.setItem(row, 0, QTableWidgetItem(""))
                    self.table.setItem(row, 1, QTableWidgetItem(""))
                    self.table.setItem(row, 2, QTableWidgetItem("↳"))
                    for col in range(3, min(9, self.table.columnCount())):
                        self.table.setItem(row, col, QTableWidgetItem(""))

                    self.table.setItem(row, self.col_index["Color"], QTableWidgetItem(color))
                    self.table.setItem(row, self.col_index["Condition"], QTableWidgetItem(condition))

                    for i, branch in enumerate(self.branches):
                        qty = qty_dict.get(branch, {}).get(color, {}).get(condition, 0)
                        self.table.setItem(row, first_branch_col + i, QTableWidgetItem(str(qty)))

        # Re-enable painting & signals
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)


    def toggle_expand_row(self, row, col):
        item = self.table.item(row, 1)
        if not item: return
        item_code = item.text()
        if not item_code.strip(): return
        if item_code in self.expanded_rows: self.expanded_rows.remove(item_code)
        else: self.expanded_rows.add(item_code)
        self.refresh_table()

    def export_inventory(self):
        dialog = QDialog(self); dialog.setWindowTitle("Export Inventory")
        main_layout = QVBoxLayout(dialog)
        format_combo = QComboBox(); format_combo.addItems(["Excel", "PDF"])
        main_layout.addWidget(QLabel("Export Format:")); main_layout.addWidget(format_combo)

        options_container = QWidget(); options_layout = QVBoxLayout(options_container)
        options_container.setVisible(False); branch_checkboxes = []
        options_layout.addWidget(QLabel("Select Branch(es):"))
        for b in self.branches:
            cb = QCheckBox(b); options_layout.addWidget(cb); branch_checkboxes.append(cb)
        show_price_cb = QCheckBox("Include Price"); show_price_cb.setChecked(True); options_layout.addWidget(show_price_cb)
        main_layout.addWidget(options_container)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); main_layout.addWidget(btn_box)

        def on_format_change():
            options_container.setVisible(format_combo.currentText() == "PDF")
        format_combo.currentIndexChanged.connect(on_format_change); on_format_change()
        btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
        if dialog.exec_() != QDialog.Accepted: return

        export_format = format_combo.currentText()
        data = self.get_filtered_items()
        if export_format == "PDF":
            selected_branches = [cb.text() for cb in branch_checkboxes if cb.isChecked()]
            if not selected_branches:
                QMessageBox.warning(self, "Branch Required", "Select at least one branch.")
                return
            self.export_to_pdf(data, selected_branches, show_price_cb.isChecked())
        else:
            self.export_to_excel(data, [], False)

    # (Excel/PDF exports merged: keep offline-safe loader + detailed totals)
    def export_to_excel(self, *_):
        loader = self.show_loader(self, "Exporting Inventory", "Preparing Excel file...")
        main_categories = {}; sub_categories = {}
        for doc in db.collection("product_main_categories").stream():
            main_categories[doc.id] = doc.to_dict().get("name", "")
        for doc in db.collection("product_sub_categories").stream():
            data = doc.to_dict(); sub_categories[doc.id] = data.get("main_id", "")
        all_docs = db.collection("products").stream()
        rows = []
        for doc in all_docs:
            data = doc.to_dict()
            sub_id = data.get("sub_id", ""); main_id = sub_categories.get(sub_id, "")
            main_category = main_categories.get(main_id, "")
            qty_dict = data.get("qty", {})
            if qty_dict:
                for branch, branch_data in qty_dict.items():
                    for color, condition_data in branch_data.items():
                        for condition, qty in condition_data.items():
                            row = {
                                "main_category": main_category, "sub_id": sub_id,
                                "item_code": data.get("item_code", ""), "name": data.get("name", ""),
                                "length": data.get("length", 0), "width": data.get("width", 0), "height": data.get("height", 0),
                                "weight": data.get("weight", 0), "length_unit": data.get("length_unit", ""),
                                "width_unit": data.get("width_unit", ""), "height_unit": data.get("height_unit", ""),
                                "weight_unit": data.get("weight_unit", ""), "gauge": data.get("gauge", 0),
                                "metal_type": data.get("metal_type", ""), "selling_price": data.get("selling_price", 0),
                                "reorder_qty": data.get("reorder_qty", 0), "branch": branch,
                                "color": color, "condition": condition, "qty": qty,
                            }
                            if "rack_no" in data: row["rack_no"] = data["rack_no"]
                            rows.append(row)
            else:
                row = {
                    "main_category": main_category, "sub_id": sub_id,
                    "item_code": data.get("item_code", ""), "name": data.get("name", ""),
                    "length": data.get("length", 0), "width": data.get("width", 0), "height": data.get("height", 0),
                    "weight": data.get("weight", 0), "length_unit": data.get("length_unit", ""),
                    "width_unit": data.get("width_unit", ""), "height_unit": data.get("height_unit", ""),
                    "weight_unit": data.get("weight_unit", ""), "gauge": data.get("gauge", 0),
                    "metal_type": data.get("metal_type", ""), "selling_price": data.get("selling_price", 0),
                    "reorder_qty": data.get("reorder_qty", 0), "branch": "", "color": "", "condition": "", "qty": "",
                }
                if "rack_no" in data: row["rack_no"] = data["rack_no"]
                rows.append(row)
        if not rows:
            QMessageBox.warning(self, "No Data", "No inventory data found.")
            loader.close(); return
        df = pd.DataFrame(rows)
        date_str = datetime.now().strftime("%Y-%m-%d")
        fname, _ = QFileDialog.getSaveFileName(self, "Save Excel", f"all_inventory_{date_str}.xlsx", "Excel Files (*.xlsx)")
        if fname and os.path.exists(fname):
            try: os.rename(fname, fname)
            except PermissionError:
                QMessageBox.warning(self, "File In Use", "Please close the Excel file before exporting.")
                loader.close(); return
        if fname: df.to_excel(fname, index=False)
        loader.close()

    def export_to_pdf(self, items, branches, show_price):
        from collections import defaultdict
        def draw_separator():
            pdf.set_draw_color(180,180,180); pdf.set_line_width(0.4)
            y = pdf.get_y(); pdf.line(10, y, 290, y); pdf.ln(3)
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12); pdf.set_margins(10,10,10); pdf.add_page()
        date_str = datetime.now().strftime("%Y-%m-%d")
        pdf.set_font("Arial", 'B', 16); pdf.set_text_color(33,37,41); pdf.cell(0, 12, "Inventory Summary Report", 0, 1, 'C')
        pdf.set_font("Arial", '', 10); pdf.cell(0, 8, f"Generated on: {date_str}", 0, 1, 'C')

        grouped = defaultdict(list)
        for item in items: grouped[item.get("item_code", "")].append(item)

        total_weight_kg = 0; total_subtotal = 0
        for item_code, group_items in grouped.items():
            base = group_items[0]; pdf.ln(4); draw_separator()
            name = base.get("name", "")
            l = self.format_unit(base.get("length", 0), base.get("length_unit", ""))
            w = self.format_unit(base.get("width", 0), base.get("width_unit", ""))
            h = self.format_unit(base.get("height", 0), base.get("height_unit", ""))
            size = f"{l} x {w} x {h}"
            weight = base.get("weight", 0); weight_unit = base.get("weight_unit", "kg")
            gauge = str(base.get("gauge", "")); metal_type = base.get("metal_type", "")
            price = float(base.get("selling_price", 0))

            # Product header
            pdf.set_fill_color(235,235,235); pdf.set_text_color(0); pdf.set_font("Arial", 'B', 11)
            pdf.cell(0, 8, f"{item_code} - {name}", 0, 1, 'L', 1)
            pdf.set_font("Arial", '', 9)
            meta = f"Size: {size}    |    Gauge: {gauge}    |    Weight: {weight} {weight_unit}"
            if self.include_metal_type:
                meta += f"    |    Metal: {metal_type}"
            pdf.set_text_color(70,70,70); pdf.cell(0, 7, meta, 0, 1)

            # Summary row
            pdf.set_font("Arial", 'B', 8); pdf.set_fill_color(220,220,220)
            headers = [f"Qty - {b}" for b in branches]
            if show_price: headers += ["Price", "Subtotal"]
            table_width = 270; col_w = table_width / len(headers)
            for htxt in headers: pdf.cell(col_w, 7, htxt, 1, 0, 'C', 1)
            pdf.ln()
            pdf.set_font("Arial", '', 8); row_vals = []; total_qty = 0
            for branch in branches:
                qty = 0
                for item in group_items:
                    b_data = item.get("qty", {}).get(branch, {})
                    for c_data in b_data.values():
                        if isinstance(c_data, dict): qty += sum(c_data.values())
                row_vals.append(qty); total_qty += qty
            for val in row_vals: pdf.cell(col_w, 7, str(val), 1, 0, 'C')
            if show_price:
                subtotal = total_qty * price
                weight_kg = (weight/1000) * total_qty if str(weight_unit).lower() in ["g","gram"] else weight * total_qty
                total_weight_kg += weight_kg; total_subtotal += subtotal
                pdf.cell(col_w, 7, f"{price:,.2f}", 1, 0, 'C'); pdf.cell(col_w, 7, f"{subtotal:,.2f}", 1, 0, 'C')
            pdf.ln()

            # Details per branch
            for branch in branches:
                table_data = []
                for item in group_items:
                    b_data = item.get("qty", {}).get(branch, {})
                    for color, conds in b_data.items():
                        if isinstance(conds, dict):
                            for cond, qty in conds.items():
                                table_data.append((color, cond, qty))
                if table_data:
                    pdf.ln(1); pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.cell(0, 6, f"Branch: {branch}", 0, 1)
                    pdf.set_fill_color(230,230,230); pdf.set_font("Arial", 'B', 7)
                    pdf.cell(60, 6, "Color", 1, 0, 'C', 1); pdf.cell(60, 6, "Condition", 1, 0, 'C', 1); pdf.cell(40, 6, "Quantity", 1, 1, 'C', 1)
                    fill = False; pdf.set_font("Arial", '', 7)
                    for color, cond, qty in sorted(table_data):
                        pdf.set_fill_color(245,245,245) if fill else pdf.set_fill_color(255,255,255)
                        pdf.cell(60, 6, str(color), 1, 0, 'L', fill)
                        pdf.cell(60, 6, str(cond), 1, 0, 'L', fill)
                        pdf.cell(40, 6, str(qty), 1, 1, 'C', fill)
                        fill = not fill
        pdf.ln(4); pdf.set_font("Arial", 'B', 10); pdf.set_text_color(0); pdf.set_fill_color(245,245,245)
        pdf.cell(0, 9, "GRAND TOTAL", 0, 1, 'R', 1)
        pdf.set_font("Arial", '', 9)
        summary_line = f"Total Weight: {total_weight_kg:,.2f} kg"
        if show_price:
            summary_line += f"    |    Total Value: {total_subtotal:,.2f}"
        pdf.cell(0, 8, summary_line, 0, 1, 'R')
        fname, _ = QFileDialog.getSaveFileName(self, "Save PDF", f"inventory_{datetime.now().strftime('%Y-%m-%d')}.pdf", "PDF Files (*.pdf)")
        if fname: pdf.output(fname)
