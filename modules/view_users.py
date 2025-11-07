# view_users.py  — enhanced UI/UX, clearer permissions screen, centered dialogs

from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget, QDialog, QTableView, QVBoxLayout, QProgressBar, QHeaderView, QMessageBox,
    QCheckBox, QFormLayout, QDialogButtonBox, QLabel, QPushButton, QLineEdit, QComboBox,
    QScrollArea, QHBoxLayout, QFrame, QGroupBox, QApplication, QDesktopWidget, QToolButton, QGraphicsDropShadowEffect
) 
from firebase.config import db
from firebase_admin import auth as admin_auth


# ---------------------------
# Helpers / Common UI styling
# ---------------------------

PRIMARY_BTN = """
QPushButton {
    background-color: #10B981; color: white; border: none; padding: 10px 16px;
    border-radius: 8px; font-weight: 600;
}
QPushButton:hover { background-color: #0EA371; }
QPushButton:pressed { background-color: #0C8D62; }
"""

SECONDARY_BTN = """
QPushButton {
    background-color: #6B7280; color: white; border: none; padding: 10px 16px;
    border-radius: 8px; font-weight: 600;
}
QPushButton:hover { background-color: #5B616D; }
QPushButton:pressed { background-color: #4B505B; }
"""

INFO_BTN = """
QPushButton {
    background-color: #3B82F6; color: white; border: none; padding: 10px 16px;
    border-radius: 10px; font-weight: 600; font-size: 14px;
}
QPushButton:hover { background-color: #2F6EE6; }
QPushButton:pressed { background-color: #235AC7; }
"""

WARNING_BTN = """
QPushButton {
    background-color: #F59E0B; color: #111827; border: none; padding: 10px 16px;
    border-radius: 10px; font-weight: 700; font-size: 14px;
}
QPushButton:hover { background-color: #DB8B08; }
QPushButton:pressed { background-color: #B87406; color: white; }
"""

ACCENT_BTN = """
QPushButton {
    background-color: #8B5CF6; color: white; border: none; padding: 10px 16px;
    border-radius: 10px; font-weight: 700; font-size: 14px;
}
QPushButton:hover { background-color: #7A48F3; }
QPushButton:pressed { background-color: #6A3FE0; }
"""

SECTION_LABEL = """
QLabel {
    font-size: 16px; font-weight: 700; color: #111827;
}
"""

SUBTLE_LABEL = """
QLabel {
    font-size: 13px; color: #374151;
}
"""

CHECKBOX_BIG = """
QCheckBox {
    font-size: 14px;
}
"""

TABLE_STYLE = """
QTableView {
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    gridline-color: #E5E7EB;
    selection-background-color: #DBEAFE;
    selection-color: #111827;
}
QHeaderView::section {
    background-color: #F3F4F6;
    color: #111827;
    padding: 8px;
    border: 1px solid #E5E7EB;
    font-weight: 600;
}
"""

CARD_STYLE = """
QDialog {
    background: #FFFFFF;
}
"""

def hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("color: #E5E7EB;")
    return line

def center_on_screen(widget: QDialog):
    # Center without shrinking the window size chosen via resize()/setGeometry()
    frame_geom = widget.frameGeometry()
    center_point = QDesktopWidget().availableGeometry(widget).center()
    frame_geom.moveCenter(center_point)
    widget.move(frame_geom.topLeft())


# ---------------------------
# Firebase data fetching
# ---------------------------

class ViewUsersThread(QThread):
    users_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, page_size=20, start_after=None):
        super().__init__()
        self.page_size = page_size
        self.start_after = start_after

    def run(self):
        try:
            users_ref = db.collection("users")
            # Exclude users with the role "admin"
            query = users_ref.where("role", "!=", "admin").limit(self.page_size)
            if self.start_after:
                query = query.start_after(self.start_after)

            users = query.stream()
            user_list = []
            last_doc = None

            for user in users:
                data = user.to_dict()
                user_list.append({
                    "user_id": user.id,
                    "name": data.get("name", "N/A"),
                    "email": data.get("email", "N/A"),
                    "role": data.get("role", "N/A")
                })
                last_doc = user

            self.users_fetched.emit(user_list)
            if last_doc:
                self.start_after = last_doc

        except Exception as e:
            self.error_occurred.emit(str(e))


# ---------------------------
# Users Window
# ---------------------------

class ViewUsersModule(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.setWindowTitle("User Management (Admin Only)")
        self.resize(1200, 750)
        self.setStyleSheet(CARD_STYLE)
        self._create_user_win = None  # keep a reference so it doesn't get GC'd

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QLabel("Manage Users")
        header.setStyleSheet(SECTION_LABEL)
        root.addWidget(header)

        sub = QLabel("Double-click a row to open actions.")
        sub.setStyleSheet(SUBTLE_LABEL)
        root.addWidget(sub)

        # Progress bar for loading
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)  # Infinite progress
        root.addWidget(self.progress)

        # Table for displaying users
        self.table = QTableView(self)
        self.table.setStyleSheet(TABLE_STYLE)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        root.addWidget(self.table)

        self.model = UserTableModel([], self)
        self.table.setModel(self.model)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)

        # Double-click event to open options
        self.table.doubleClicked.connect(self.show_user_options)

        # Thread to fetch users
        self.thread = ViewUsersThread()
        self.thread.users_fetched.connect(self.update_table)
        self.thread.error_occurred.connect(self.show_error)
        self.thread.start()

        center_on_screen(self)
        
        # ===== Floating "Add User" button =====
        self.btn_add_user = QToolButton(self)
        self.btn_add_user.setObjectName("FabAddUser")
        self.btn_add_user.setText("＋")
        self.btn_add_user.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_add_user.setCursor(Qt.PointingHandCursor)
        self.btn_add_user.setAutoRaise(True)
        self.btn_add_user.setFixedSize(56, 56)
        self.btn_add_user.setStyleSheet("""
            QToolButton#FabAddUser {
                background: #10B981;    /* emerald */
                color: white;
                font-size: 26px;
                font-weight: 700;
                border-radius: 28px;
            }
            QToolButton#FabAddUser:hover  { background: #0EA371; }
            QToolButton#FabAddUser:pressed{ background: #0C8D62; }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setOffset(0, 4)
        shadow.setBlurRadius(22)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.btn_add_user.setGraphicsEffect(shadow)
        self.btn_add_user.setToolTip("Create new user")
        self.btn_add_user.clicked.connect(self._open_create_user_dialog)

        # place it initially
        self._position_fab()
        self.btn_add_user.raise_()


    @staticmethod
    def show_if_admin(user_data):
        if user_data.get("role") != "admin":
            QMessageBox.critical(None, "Access Denied", "You are not authorized to manage users.")
            return
        window = ViewUsersModule(user_data)
        window.show()
        return window
    
    def _position_fab(self):
        """Position FAB at bottom-right with margins, similar to Journal viewer."""
        if not hasattr(self, "btn_add_user"):
            return
        margin_x = 30
        margin_y = 30
        s = self.btn_add_user.height()
        x = max(margin_x, self.width() - s - margin_x)
        y = max(margin_y, self.height() - s - margin_y)
        self.btn_add_user.move(x, y)

    def resizeEvent(self, event):
        self._position_fab()
        super().resizeEvent(event)

    def show_user_options(self, index):
        user_id = self.model.users[index.row()]["user_id"]
        dialog = UserOptionsDialog(user_id, self.user_data, self)
        dialog.exec_()

    def update_table(self, users):
        self.model.add_users(users)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    def show_error(self, error_message):
        QMessageBox.critical(self, "Error", f"Failed to fetch users: {error_message}")
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        
    def _open_create_user_dialog(self):
        # If it's already open, just focus it
        if getattr(self, "_create_user_win", None) and self._create_user_win.isVisible():
            self._create_user_win.raise_()
            self._create_user_win.activateWindow()
            return

        try:
            # Import here to avoid circulars
            from modules.create_new_login import CreateUserModule

            # If you have an admin gate method, use it; otherwise instantiate directly
            if hasattr(CreateUserModule, "show_if_admin"):
                win = CreateUserModule.show_if_admin(self.user_data)
                if win is None:
                    return  # not admin / denied
            else:
                win = CreateUserModule(self.user_data)

            # Keep a strong ref so it doesn't get collected
            self._create_user_win = win

            # Make it behave like a dialog window (since CreateUserModule is a QWidget)
            self._create_user_win.setParent(None)
            self._create_user_win.setWindowFlag(Qt.Dialog, True)
            self._create_user_win.setWindowModality(Qt.ApplicationModal)
            self._create_user_win.setAttribute(Qt.WA_DeleteOnClose, True)

            # Refresh the users list after a successful create
            if hasattr(self._create_user_win, "user_created"):
                self._create_user_win.user_created.connect(self._refresh_users_list)
                # When it finishes, clear our ref so a new one can open later
                self._create_user_win.user_created.connect(lambda: setattr(self, "_create_user_win", None))

            # Also clear the ref when the window is closed manually
            try:
                self._create_user_win.destroyed.connect(lambda *_: setattr(self, "_create_user_win", None))
            except Exception:
                pass

            self._create_user_win.show()

        except Exception as e:
            QMessageBox.warning(self, "Open Failed", f"Could not open Create New Login: {e}")


    def _refresh_users_list(self):
        # Re-run the loading thread to refresh the table
        try:
            self.model.clear_data()
            # restart a fresh thread (keeps your existing pattern)
            self.thread = ViewUsersThread()
            self.thread.users_fetched.connect(self.update_table)
            self.thread.error_occurred.connect(self.show_error)
            self.thread.start()
        except Exception as e:
            QMessageBox.warning(self, "Refresh Failed", f"Could not refresh users: {e}")



class UserTableModel(QAbstractTableModel):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.users = data
        self.headers = ["User ID", "Name", "Email", "Role"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.users)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            user = self.users[index.row()]
            col = index.column()
            if col == 0:
                return user["user_id"]
            elif col == 1:
                return user["name"]
            elif col == 2:
                return user["email"]
            elif col == 3:
                return user["role"]
        return None

    def add_users(self, users):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount() + len(users) - 1)
        self.users.extend(users)
        self.endInsertRows()

    def clear_data(self):
        self.users = []
        self.layoutChanged.emit()


# ---------------------------
# Options Dialog
# ---------------------------

class UserOptionsDialog(QDialog):
    def __init__(self, user_id, admin_user_data, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.admin_user_data = admin_user_data
        self.setWindowTitle("Choose an Action")
        self.resize(480, 240)
        self.setStyleSheet(CARD_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("What would you like to do?")
        title.setStyleSheet(SECTION_LABEL)
        root.addWidget(title)
        root.addWidget(hline())

        # Big, colorful buttons in a row
        row1 = QHBoxLayout()
        self.edit_user_btn = QPushButton("Edit User")
        self.edit_user_btn.setStyleSheet(INFO_BTN)
        row1.addWidget(self.edit_user_btn)

        self.edit_permissions_btn = QPushButton("Edit Permissions")
        self.edit_permissions_btn.setStyleSheet(WARNING_BTN)
        row1.addWidget(self.edit_permissions_btn)

        self.send_reset_btn = QPushButton("Send Reset Password Link")
        self.send_reset_btn.setStyleSheet(ACCENT_BTN)
        row1.addWidget(self.send_reset_btn)

        root.addLayout(row1)

        # Wire up actions
        self.edit_user_btn.clicked.connect(self.edit_user)
        self.edit_permissions_btn.clicked.connect(self.edit_permissions)
        self.send_reset_btn.clicked.connect(self.send_reset_password)

        center_on_screen(self)

    def edit_user(self):
        dialog = EditUserDialog(self.user_id, self.admin_user_data, self)
        dialog.exec_()

    def edit_permissions(self):
        dialog = AssignModulesDialog(self.user_id, self)
        dialog.exec_()

    def send_reset_password(self):
        try:
            user = admin_auth.get_user(self.user_id)
            link = admin_auth.generate_password_reset_link(user.email)
            # NOTE: You may want to email 'link' yourself; here we just notify success.
            QMessageBox.information(self, "Password Reset", f"A password reset link has been sent to {user.email}.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send reset link: {str(e)}")
        self.accept()


# ---------------------------
# Edit User Dialog
# ---------------------------

class EditUserDialog(QDialog):
    def __init__(self, user_id, admin_user_data, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.admin_user_data = admin_user_data
        self.setWindowTitle("Edit User")
        self.resize(520, 520)
        self.setStyleSheet(CARD_STYLE + CHECKBOX_BIG)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QLabel("Edit User Details")
        header.setStyleSheet(SECTION_LABEL)
        root.addWidget(header)
        root.addWidget(hline())

        form_box = QGroupBox()
        form_box.setTitle("Basic Info")
        form_layout = QFormLayout(form_box)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(10)

        self.name_input = QLineEdit(self)
        self.role_dropdown = QComboBox(self)
        self.role_dropdown.addItems(["Admin", "Branch Manager", "Accountant", "Inventory Manager", "Viewer"])
        form_layout.addRow(QLabel("Name:"), self.name_input)
        form_layout.addRow(QLabel("Role:"), self.role_dropdown)

        root.addWidget(form_box)
        root.addWidget(hline())

        # Branches section
        branches_box = QGroupBox()
        branches_box.setTitle("Assign Branches")
        branches_layout = QVBoxLayout(branches_box)

        self.branch_checkboxes = {}
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setSpacing(6)
        self.scroll_layout.setContentsMargins(6, 6, 6, 6)

        self.scroll_area.setWidget(self.scroll_widget)
        branches_layout.addWidget(self.scroll_area)
        root.addWidget(branches_box)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        save_btn = QPushButton("Save Changes", self)
        save_btn.setStyleSheet(PRIMARY_BTN)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setStyleSheet(SECONDARY_BTN)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.save_changes)

        # Populate UI
        self.fetch_admin_branches()
        self.load_user_data()

        center_on_screen(self)

    def fetch_admin_branches(self):
        admin_branches = self.admin_user_data.get("branch", [])
        for branch_name in admin_branches:
            checkbox = QCheckBox(branch_name, self)
            self.branch_checkboxes[branch_name] = checkbox
            self.scroll_layout.addWidget(checkbox)

    def load_user_data(self):
        user_ref = db.collection("users").document(self.user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            self.name_input.setText(user_data.get("name", ""))
            self.role_dropdown.setCurrentText(user_data.get("role", "Viewer"))

            assigned_branches = user_data.get("branch", [])
            for branch_name in assigned_branches:
                if branch_name in self.branch_checkboxes:
                    self.branch_checkboxes[branch_name].setChecked(True)

    def save_changes(self):
        name = self.name_input.text().strip()
        role = self.role_dropdown.currentText()
        selected_branches = [b for b, cb in self.branch_checkboxes.items() if cb.isChecked()]

        user_ref = db.collection("users").document(self.user_id)
        user_ref.update({
            "name": name,
            "role": role,
            "branch": selected_branches
        })

        QMessageBox.information(self, "Success", "User details updated successfully!")
        self.accept()


# ---------------------------
# Assign Modules / Permissions (Enhanced)
# ---------------------------

class AssignModulesDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Edit Permissions")
        self.resize(720, 700)
        self.setStyleSheet(CARD_STYLE + CHECKBOX_BIG)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QLabel("Edit Permissions")
        header.setStyleSheet(SECTION_LABEL)
        root.addWidget(header)
        root.addWidget(hline())

        # ===== Allowed Modules Section =====
        modules_box = QGroupBox("Allowed Modules")
        modules_layout = QVBoxLayout(modules_box)
        modules_layout.setSpacing(8)

        info = QLabel("Select the modules this user can access.")
        info.setStyleSheet(SUBTLE_LABEL)
        modules_layout.addWidget(info)

        # Scrollable area for many modules
        self.module_checkboxes = {}
        self.modules = [
            "Manage / View Parties", "Manage / View Employees", "Chart of Accounts", "Journal",
            "Invoice", "View Invoice", "Purchase Order", "Chart of Inventory", "View Inventory",
            "Delivery Chalan", "Create Manufacturing Order", "View Manufacturing Order"
        ]

        mod_scroll = QScrollArea()
        mod_scroll.setWidgetResizable(True)
        mod_container = QWidget()
        mod_v = QVBoxLayout(mod_container)
        mod_v.setSpacing(6)
        mod_v.setContentsMargins(6, 6, 6, 6)

        for module in self.modules:
            cb = QCheckBox(module, self)
            self.module_checkboxes[module] = cb
            mod_v.addWidget(cb)

        mod_v.addStretch(1)
        mod_scroll.setWidget(mod_container)
        modules_layout.addWidget(mod_scroll)

        root.addWidget(modules_box)
        root.addWidget(hline())

        # ===== Extra Permissions Section =====
        perm_box = QGroupBox("Extra Permissions")
        perm_layout = QVBoxLayout(perm_box)
        perm_layout.setSpacing(8)

        perm_info = QLabel("Grant special permissions beyond the selected modules.")
        perm_info.setStyleSheet(SUBTLE_LABEL)
        perm_layout.addWidget(perm_info)

        self.extra_perm_checkboxes = {
            "can_see_other_branches_inventory": QCheckBox("Can View all branch Inventories?"),
            "can_delete_products": QCheckBox("Can Delete Products?"),
            "can_edit_products": QCheckBox("Can Edit Products?"),
            "can_edit_popup_qty": QCheckBox("Can Edit Product Opening Qty?"),
            "can_see_other_branches_journals": QCheckBox("Can View all branch Journals?"),
            "can_imp_exp_anything": QCheckBox("Can Import/Export Anything?")
        }

        perm_scroll = QScrollArea()
        perm_scroll.setWidgetResizable(True)
        perm_container = QWidget()
        perm_v = QVBoxLayout(perm_container)
        perm_v.setSpacing(6)
        perm_v.setContentsMargins(6, 6, 6, 6)

        for cb in self.extra_perm_checkboxes.values():
            perm_v.addWidget(cb)

        perm_v.addStretch(1)
        perm_scroll.setWidget(perm_container)
        perm_layout.addWidget(perm_scroll)

        root.addWidget(perm_box)

        # ===== Action Buttons =====
        root.addWidget(hline())
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(SECONDARY_BTN)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(PRIMARY_BTN)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.save_modules)

        # Preload current settings
        self.fetch_user_permissions()

        center_on_screen(self)

    def fetch_user_permissions(self):
        user_ref = db.collection("users").document(self.user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            data = user_doc.to_dict()
            allowed_modules = data.get("allowed_modules", [])
            extra_perm = data.get("extra_perm", [])

            for module in allowed_modules:
                if module in self.module_checkboxes:
                    self.module_checkboxes[module].setChecked(True)

            for perm in extra_perm:
                if perm in self.extra_perm_checkboxes:
                    self.extra_perm_checkboxes[perm].setChecked(True)

    def save_modules(self):
        selected_modules = [m for m, cb in self.module_checkboxes.items() if cb.isChecked()]
        selected_extra_perm = [k for k, cb in self.extra_perm_checkboxes.items() if cb.isChecked()]

        user_ref = db.collection("users").document(self.user_id)
        user_ref.update({
            "allowed_modules": selected_modules,
            "extra_perm": selected_extra_perm
        })

        QMessageBox.information(self, "Saved", "Permissions updated successfully.")
        self.accept()
