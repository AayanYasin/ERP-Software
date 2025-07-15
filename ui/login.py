# ui/login.py
from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QFrame, QMessageBox, QToolButton, QDialog, QGraphicsDropShadowEffect
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer
from firebase.config import db, FIREBASE_LOGIN_URL
import requests
from ui.dashboard import DashboardApp
from modules.create_new_login import CreateUserModule

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        doc = db.collection("meta").document("company_name").get()
        self.company_name = "ERP"
        if doc.exists:
            data = doc.to_dict()
            self.company_name = data.get("name", "ERP")
        
        self.setWindowTitle(f"{self.company_name} ERP - Login")
        self.setFixedSize(500, 450)
        self.setStyleSheet("background-color: #f4f6f9;")
        self.setup_ui()

    def setup_ui(self):
        
        font_title = QFont("Segoe UI", 20, QFont.Bold)
        font_label = QFont("Segoe UI", 12)
        font_input = QFont("Segoe UI", 12)
        font_button = QFont("Segoe UI", 12, QFont.Bold)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignCenter)

        login_panel = QFrame()
        login_panel.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 10px;
                border: 1px solid #dfe6e9;
            }
        """)
        login_layout = QVBoxLayout(login_panel)
        login_layout.setContentsMargins(30, 30, 30, 30)
        login_layout.setSpacing(18)

        title = QLabel(f"{self.company_name} - ERP")
        title.setFont(font_title)
        title.setStyleSheet("background: none; border: none;")
        title.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(title)

        # Email
        email_label = QLabel("Email")
        email_label.setFont(font_label)
        email_label.setStyleSheet("background: none; border: none;")
        login_layout.addWidget(email_label)

        self.entry_email = QLineEdit()
        self.entry_email.setFont(font_input)
        self.entry_email.setPlaceholderText("Enter your email")
        self.entry_email.setStyleSheet("""
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
        login_layout.addWidget(self.entry_email)

        # Password
        pass_label = QLabel("Password")
        pass_label.setFont(font_label)
        pass_label.setStyleSheet("background: none; border: none;")
        login_layout.addWidget(pass_label)

        password_container = QHBoxLayout()
        self.entry_pass = QLineEdit()
        self.entry_pass.setFont(font_input)
        self.entry_pass.setEchoMode(QLineEdit.Password)
        self.entry_pass.setPlaceholderText("Enter your password")
        self.entry_pass.setStyleSheet("""
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
        password_container.addWidget(self.entry_pass)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("👁")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("background: none; border: none; font-size: 16px;")
        self.toggle_btn.clicked.connect(self.toggle_password_visibility)
        password_container.addWidget(self.toggle_btn)

        login_layout.addLayout(password_container)

        # Login Button
        self.login_btn = QPushButton("Login")
        self.login_btn.setFont(font_button)
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #0984e3;
                color: white;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #74b9ff;
            }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        login_layout.addSpacing(10)
        login_layout.addWidget(self.login_btn)

        main_layout.addStretch()
        main_layout.addWidget(login_panel)
        main_layout.addStretch()

    def toggle_password_visibility(self):
        if self.toggle_btn.isChecked():
            self.entry_pass.setEchoMode(QLineEdit.Normal)
            self.toggle_btn.setText("🙈")
        else:
            self.entry_pass.setEchoMode(QLineEdit.Password)
            self.toggle_btn.setText("👁")

    def handle_login(self):
        # email = self.entry_email.text().strip()
        # password = self.entry_pass.text().strip()
        email = "db.storagesolutions@gmail.com"
        password = "10485766"
        # email = "aayan06pk@gmail.com"
        # password = "10485766"

        if not email or not password:
            QMessageBox.warning(self, "Login Failed", "Please fill in all fields.")
            return

        self.login_btn.setText("Logging in...")
        self.login_btn.setEnabled(False)

        # Simulate async call with delay
        QTimer.singleShot(200, lambda: self.login(email, password))
        
    def reset_login_btn(self):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Login")

    def login(self, email, password):
        try:
            # REST API login
            payload = {
                "email": email,
                "password": password,
                "returnSecureToken": True
            }
            res = requests.post(FIREBASE_LOGIN_URL, json=payload)
            if res.status_code != 200:
                raise Exception("Invalid credentials")

            user_data = res.json()
            uid = user_data["localId"]

            # Get user profile from Firestore
            doc_ref = db.collection("users").document(uid)
            user_doc = doc_ref.get()

            if not user_doc.exists:
                QMessageBox.critical(self, "Error", "User profile not found in database.")
                self.reset_login_btn()
                return

            profile = user_doc.to_dict()

            self.dashboard = DashboardApp(profile["name"], profile)
            self.dashboard.show()
            self.close()

        except Exception as e:
            QMessageBox.critical(self, "Login Failed", str(e))
            self.reset_login_btn()