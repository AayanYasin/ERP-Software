# ui/create_new_login.py
from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QCheckBox, QMessageBox, QComboBox, QScrollArea
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, pyqtSignal
from firebase.config import db
from firebase_admin import auth as admin_auth

class CreateUserModule(QWidget):
    user_created = pyqtSignal()
    def __init__(self, user_data, first_time=False):
        super().__init__()
        self.user_data = user_data
        self.first_time = first_time
        self.setWindowTitle("Create New User")
        self.resize(450, 750)
        self.setStyleSheet("background-color: #f4f6f9;")
        self.setup_ui()

    @staticmethod
    def show_if_admin(user_data):
        if user_data.get("role") != "admin":
            QMessageBox.critical(None, "Access Denied", "You are not authorized to create users.")
            return
        window = CreateUserModule(user_data, False)
        window.show()
        return window

    def setup_ui(self):
        font_label = QFont("Segoe UI", 11)
        font_input = QFont("Segoe UI", 11)
        font_button = QFont("Segoe UI", 12, QFont.Bold)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel("Create User Login")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("border: none; background: none;")
        layout.addWidget(title)

        self.fields = {}
        
        if self.first_time:
            lbl = QLabel("Company Name")
            lbl.setFont(font_label)
            lbl.setStyleSheet("background: none;")
            layout.addWidget(lbl)

            self.company_name_input = QLineEdit()
            self.company_name_input.setFont(font_input)
            self.company_name_input.setStyleSheet("""
                QLineEdit {
                    padding: 8px;
                    border-radius: 6px;
                    border: 1px solid #b2bec3;
                    background-color: white;
                }
                QLineEdit:focus {
                    border: 1px solid #0984e3;
                    background-color: #ecf0f1;
                }
            """)
            layout.addWidget(self.company_name_input)
        
        for label_text in ["Name", "Email", "Password", "Confirm Password"]:
            lbl = QLabel(label_text)
            lbl.setFont(font_label)
            lbl.setStyleSheet("background: none;")
            layout.addWidget(lbl)

            line_edit = QLineEdit()
            line_edit.setFont(font_input)
            if "Password" in label_text:
                line_edit.setEchoMode(QLineEdit.Password)
            line_edit.setStyleSheet("""
                QLineEdit {
                    padding: 8px;
                    border-radius: 6px;
                    border: 1px solid #b2bec3;
                    background-color: white;
                }
                QLineEdit:focus {
                    border: 1px solid #0984e3;
                    background-color: #ecf0f1;
                }
            """)
            layout.addWidget(line_edit)
            self.fields[label_text] = line_edit

        # Role
        role_lbl = QLabel("Role:")
        role_lbl.setFont(font_label)
        layout.addWidget(role_lbl)

        self.role_dropdown = QComboBox()
        self.role_dropdown.setFont(font_input)

        if self.first_time:
            self.role_dropdown.addItem("Admin")
            self.role_dropdown.setEnabled(False)
        else:
            self.role_dropdown.addItems(["Branch Manager", "Accountant", "Inventory Manager", "Viewer"])
        self.role_dropdown.setStyleSheet("""
            QComboBox {
                padding: 8px;
                font-size: 12pt;
                border: 1px solid #b2bec3;
                border-radius: 6px;
                background-color: white;
            }
            QComboBox:hover {
                border: 1px solid #0984e3;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #b2bec3;
            }
        """)
        layout.addWidget(self.role_dropdown)

        # Branches
        branch_lbl = QLabel("Assign Branches:")
        branch_lbl.setFont(font_label)
        layout.addWidget(branch_lbl)

        self.branch_vars = {}
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        branch_widget = QWidget()
        branch_layout = QVBoxLayout(branch_widget)
        branch_layout.setAlignment(Qt.AlignTop)

        for branch in self.user_data.get("branch", []):
            checkbox = QCheckBox(branch)
            checkbox.setFont(font_input)
            checkbox.setEnabled(not self.first_time)
            checkbox.setStyleSheet("""
                QCheckBox {
                    spacing: 8px;
                    font-size: 12pt;
                    color: #2d3436;
                    background: transparent;
                    border: none;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #b2bec3;
                    border-radius: 4px;
                    background: white;
                }
                QCheckBox::indicator:checked {
                    background-color: #0984e3;
                    border: 2px solid #0984e3;
                }
            """)
            branch_layout.addWidget(checkbox)
            self.branch_vars[branch] = checkbox

        scroll_area.setWidget(branch_widget)
        scroll_area.setStyleSheet("background-color: white; border: 1px solid #dfe6e9; border-radius: 6px;")
        layout.addWidget(scroll_area)

        # Submit Button
        submit_btn = QPushButton("Create User")
        submit_btn.setFont(font_button)
        submit_btn.setCursor(Qt.PointingHandCursor)
        submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        submit_btn.clicked.connect(self.create_user)
        layout.addWidget(submit_btn)

    def create_user(self):
        name = self.fields["Name"].text().strip()
        email = self.fields["Email"].text().strip()
        password = self.fields["Password"].text()
        confirm = self.fields["Confirm Password"].text()
        role = self.role_dropdown.currentText()
        branches = [b for b, cb in self.branch_vars.items() if cb.isChecked()]

        if not all([name, email, password, confirm, role]):
            QMessageBox.critical(self, "Error", "All fields are required.")
            return

        if password != confirm:
            QMessageBox.critical(self, "Error", "Passwords do not match.")
            return

        if self.first_time:
            company_name = self.company_name_input.text().strip()
            if not company_name:
                QMessageBox.critical(self, "Error", "Company name is required.")
                return

        try:
            user = admin_auth.create_user(
                email=email,
                password=password,
                display_name=name
            )
            uid = user.uid

            db.collection("users").document(uid).set({
                "name": name,
                "email": email,
                "role": role.lower(),
                "branch": branches
            })

            if self.first_time:
                db.collection("meta").document("company_name").set({
                    "name": company_name
                })
                                

            QMessageBox.information(self, "Success", f"User {email} created successfully." + f"{"\nApp will now restart" if self.first_time else ""}")
            self.user_created.emit()
            self.close()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create user:\n{str(e)}")
