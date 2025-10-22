from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QDialog, QTableView, QVBoxLayout, QProgressBar, QHeaderView, QMessageBox, QCheckBox, QFormLayout, QDialogButtonBox, QLabel, QPushButton, QLineEdit, QComboBox, QScrollArea  # <-- Make sure QScrollArea is here
from firebase.config import db
from firebase_admin import auth as admin_auth


# Firebase data fetching in a separate thread
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
            query = users_ref.where("role", "!=" , "admin").limit(self.page_size)
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


# ViewUsersModule to show users and handle module assignment
class ViewUsersModule(QDialog):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user_data = user_data
        self.setWindowTitle("User Management (Admin Only)")
        self.setGeometry(100, 100, 800, 600)
        self.layout = QVBoxLayout(self)

        # Progress bar for loading
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)  # Infinite progress
        self.layout.addWidget(self.progress)

        # Table for displaying users
        self.table = QTableView(self)
        self.layout.addWidget(self.table)
        self.model = UserTableModel([], self)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)

        # Double-click event to open AssignModulesDialog or options
        self.table.doubleClicked.connect(self.show_user_options)

        # Initialize and start the background thread to fetch users
        self.thread = ViewUsersThread()
        self.thread.users_fetched.connect(self.update_table)
        self.thread.error_occurred.connect(self.show_error)
        self.thread.start()

    @staticmethod
    def show_if_admin(user_data):
        if user_data.get("role") != "admin":
            QMessageBox.critical(None, "Access Denied", "You are not authorized to manage users.")
            return
        window = ViewUsersModule(user_data)
        window.show()
        return window

    def show_user_options(self, index):
        user_id = self.model.users[index.row()]["user_id"]
        # Pass only the necessary data (like user_id and user_data) to the dialog
        dialog = UserOptionsDialog(user_id, self.user_data, self)
        dialog.exec_()
        
    def update_table(self, users):
        # Add users to the model and stop the progress bar
        self.model.add_users(users)
        self.progress.setRange(0, 1)  # Stop progress (done)
        self.progress.setValue(1)  # Mark as completed

    def show_error(self, error_message):
        QMessageBox.critical(self, "Error", f"Failed to fetch users: {error_message}")
        self.progress.setRange(0, 1)  # Stop progress
        self.progress.setValue(1)  # Mark as completed


# UserTableModel to manage the table data
class UserTableModel(QAbstractTableModel):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.users = data

    def rowCount(self, parent=QModelIndex()):
        return len(self.users)

    def columnCount(self, parent=QModelIndex()):
        return 4  # user_id, name, email, role

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            user = self.users[index.row()]
            column = index.column()
            if column == 0:
                return user["user_id"]
            elif column == 1:
                return user["name"]
            elif column == 2:
                return user["email"]
            elif column == 3:
                return user["role"]

        return None

    def add_users(self, users):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount() + len(users) - 1)
        self.users.extend(users)
        self.endInsertRows()

    def clear_data(self):
        self.users = []
        self.layoutChanged.emit()


# Dialog for user options (Edit User, Edit Permissions, Reset Password)
class UserOptionsDialog(QDialog):
    def __init__(self, user_id, admin_user_data, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.admin_user_data = admin_user_data  # admin's complete data (role, email, branch, etc.)
        self.setWindowTitle("Choose an Action")
        self.setGeometry(150, 150, 400, 200)
        self.layout = QVBoxLayout(self)

        # Options for the admin
        self.edit_user_btn = QPushButton("Edit User", self)
        self.edit_permissions_btn = QPushButton("Edit Permissions", self)
        self.send_reset_btn = QPushButton("Send Reset Password Link", self)

        self.layout.addWidget(self.edit_user_btn)
        self.layout.addWidget(self.edit_permissions_btn)
        self.layout.addWidget(self.send_reset_btn)

        self.edit_user_btn.clicked.connect(self.edit_user)
        self.edit_permissions_btn.clicked.connect(self.edit_permissions)
        self.send_reset_btn.clicked.connect(self.send_reset_password)

    def edit_user(self):
        # Now, pass the necessary data (like user_id and admin_user_data) to EditUserDialog
        dialog = EditUserDialog(self.user_id, self.admin_user_data, self)  # Pass entire admin data
        dialog.exec_()

    def edit_permissions(self):
        dialog = AssignModulesDialog(self.user_id, self)
        dialog.exec_()

    def send_reset_password(self):
        try:
            # Send a reset password link using Firebase
            user = admin_auth.get_user(self.user_id)
            link = admin_auth.generate_password_reset_link(user.email)
            # Send the reset link to the user's email
            QMessageBox.information(self, "Password Reset", f"A password reset link has been sent to {user.email}.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send reset link: {str(e)}")

        self.accept()

# Dialog for editing user details
class EditUserDialog(QDialog):
    def __init__(self, user_id, admin_user_data, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.admin_user_data = admin_user_data  # Store the complete admin data here
        self.setWindowTitle("Edit User")
        self.setGeometry(150, 150, 400, 300)
        self.layout = QVBoxLayout(self)

        # Form for editing user details
        self.name_input = QLineEdit(self)
        self.role_dropdown = QComboBox(self)

        self.layout.addWidget(QLabel("Name:"))
        self.layout.addWidget(self.name_input)
        self.layout.addWidget(QLabel("Role:"))
        self.layout.addWidget(self.role_dropdown)

        # Populate role dropdown
        self.role_dropdown.addItems(["Admin", "Branch Manager", "Accountant", "Inventory Manager", "Viewer"])

        # Branches
        self.branch_label = QLabel("Assign Branches:")
        self.layout.addWidget(self.branch_label)

        self.branch_checkboxes = {}
        self.scroll_area = QScrollArea()  # Add a scrollable area for branches
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()  # This will hold all the checkboxes
        self.scroll_layout = QVBoxLayout(self.scroll_widget)

        self.scroll_area.setWidget(self.scroll_widget)
        self.layout.addWidget(self.scroll_area)

        # Fetch the admin's branches and display them
        self.fetch_admin_branches()

        # Save button
        self.save_btn = QPushButton("Save Changes", self)
        self.save_btn.clicked.connect(self.save_changes)
        self.layout.addWidget(self.save_btn)

        # Load current user data (name, role, branches)
        self.load_user_data()

    def fetch_admin_branches(self):
        # Get the admin user's branches from their document
        admin_branches = self.admin_user_data.get("branch", [])
        
        # Create checkboxes for the admin's branches
        for branch_name in admin_branches:
            checkbox = QCheckBox(branch_name, self)
            self.branch_checkboxes[branch_name] = checkbox
            self.scroll_layout.addWidget(checkbox)  # Add to the scrollable area

    def load_user_data(self):
        # Fetch user data from Firebase (load name, role, branches)
        user_ref = db.collection("users").document(self.user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            self.name_input.setText(user_data.get("name", ""))
            self.role_dropdown.setCurrentText(user_data.get("role", "Viewer"))

            # Pre-check the branches the user is assigned to (if any)
            assigned_branches = user_data.get("branch", [])
            for branch_name in assigned_branches:
                if branch_name in self.branch_checkboxes:
                    self.branch_checkboxes[branch_name].setChecked(True)

    def save_changes(self):
        name = self.name_input.text()
        role = self.role_dropdown.currentText()

        # Get the selected branches
        selected_branches = [
            branch_name for branch_name, checkbox in self.branch_checkboxes.items() if checkbox.isChecked()
        ]

        # Save the updated user details to Firebase
        user_ref = db.collection("users").document(self.user_id)
        user_ref.update({
            "name": name,
            "role": role,
            "branch": selected_branches  # Save selected branches
        })

        QMessageBox.information(self, "Success", "User details updated successfully!")
        self.accept()

# Dialog for Assigning Modules to Users (same as before)
class AssignModulesDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Assign Modules to User")
        self.setGeometry(100, 100, 400, 300)

        self.layout = QVBoxLayout(self)

        self.label = QLabel("Select Modules to Assign:", self)
        self.layout.addWidget(self.label)

        self.module_checkboxes = {}
        self.modules = [
            "Manage / View Parties", "Manage / View Employees", "Chart Of Accounts", "Journal", 
            "Invoice", "View Invoices", "Purchase Order", "Chart of Inventory", "View Inventory", 
            "Delivery Chalan", "Create Manufacturing Order", "View Manufacturing Order"
        ]

        # Create checkboxes for modules first but don't add them to layout until data is fetched
        form_layout = QFormLayout()
        for module in self.modules:
            checkbox = QCheckBox(module, self)
            form_layout.addRow(checkbox)
            self.module_checkboxes[module] = checkbox
        self.layout.addLayout(form_layout)

        # Add permission checkboxes
        self.permission_label = QLabel("Permissions:", self)
        self.layout.addWidget(self.permission_label)

        self.extra_perm_checkboxes = {
            "can_see_other_branches_inventory": QCheckBox("Can View all branch Inventories?", self),
            "can_delete_products": QCheckBox("Can Delete Products?", self),
            "can_edit_products": QCheckBox("Can Edit Products?", self),
            # "can_delete_parties": QCheckBox("Can Delete Parties?", self),
            # "can_edit_parties": QCheckBox("Can Edit Parties?", self),
            # "can_delete_employees": QCheckBox("Can Delete Employees?", self),
            # "can_edit_employees": QCheckBox("Can Edit Employees?", self),
            # "can_delete_accounts": QCheckBox("Can Delete Accounts?", self),
            # "can_edit_accounts": QCheckBox("Can Edit Accounts?", self),
            "can_imp_exp_anything": QCheckBox("Can Import/Export Anything?", self)
        }

        # Add permission checkboxes to the layout
        for checkbox in self.extra_perm_checkboxes.values():
            self.layout.addWidget(checkbox)

        # Add the save and cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.save_modules)
        self.button_box.rejected.connect(self.reject)

        self.layout.addWidget(self.button_box)

        # Fetch allowed modules and extra permissions
        self.fetch_user_permissions()

    def fetch_user_permissions(self):
        # Fetch the allowed_modules and extra_perm data for the user from Firestore
        user_ref = db.collection("users").document(self.user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            allowed_modules = user_doc.to_dict().get("allowed_modules", [])
            extra_perm = user_doc.to_dict().get("extra_perm", [])
            
            # Pre-select the checkboxes for allowed modules
            for module in allowed_modules:
                if module in self.module_checkboxes:
                    self.module_checkboxes[module].setChecked(True)

            # Pre-select the checkboxes for extra_perm permissions
            for perm in extra_perm:
                if perm in self.extra_perm_checkboxes:
                    self.extra_perm_checkboxes[perm].setChecked(True)

    def save_modules(self):
        # Get the selected modules and extra permissions
        selected_modules = [
            module for module, checkbox in self.module_checkboxes.items() if checkbox.isChecked()
        ]
        selected_extra_perm = [
            perm for perm, checkbox in self.extra_perm_checkboxes.items() if checkbox.isChecked()
        ]

        # Save to Firebase
        user_ref = db.collection("users").document(self.user_id)
        user_ref.update({
            "allowed_modules": selected_modules,
            "extra_perm": selected_extra_perm  # Save extra permissions
        })

        self.accept()
