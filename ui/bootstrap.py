# bootstrap.py

from PyQt5.QtWidgets import QMessageBox, QApplication
from firebase.config import db
from ui.login import LoginWindow
from modules.create_new_login import CreateUserModule

from PyQt5.QtCore import QTimer

import os
import sys
import subprocess


class AppBootstrap:
    def __init__(self, app: QApplication):
        self.app = app
        self.login_window = None
        self.create_admin_window = None
        
    def launch_login(self):
        from ui.login import LoginWindow
        self.login_window = LoginWindow()
        self.login_window.show()

    def start(self):
        try:
            self.ensure_meta_documents()
            self.ensure_main_categories_exist()
            self.ensure_sub_categories_exist()

            users = db.collection("users").limit(1).get()
            if not users:
                self.run_first_time_setup()
            else:
                self.launch_login()

        except Exception as e:
            QMessageBox.critical(None, "Startup Error", f"Could not complete startup:\n{e}")
            self.launch_login()

    def ensure_meta_documents(self):
        meta_ref = db.collection("meta").document("item_code_counter")
        if not meta_ref.get().exists:
            meta_ref.set({"last_code": 1000})
            
        doc_ref = db.collection("meta").document("colors")
        if not doc_ref.get().exists:
            doc_ref.set({"pc_colors": ["No Color", "Black", "White", "Red", "Blue", "Orange"]})

    
    def ensure_main_categories_exist(self):
        collection_name = "product_main_categories"
        required_names = {"Raw Material", "Finished Products"}

        existing_docs = db.collection(collection_name).get()
        existing_names = {doc.to_dict().get("name") for doc in existing_docs}

        missing = required_names - existing_names
        if not missing:
            return  # ✅ All main categories exist

        for name in missing:
            db.collection(collection_name).add({"name": name})
            print(f"Created main category: {name}")

                
    def ensure_sub_categories_exist(self):
        required_subs = {"Metal Sheet", "Metal Pipe"}

        # ✅ Get 'Raw Material' main category ID
        main_docs = db.collection("product_main_categories").where("name", "==", "Raw Material").get()
        if not main_docs:
            return

        raw_material_main_id = main_docs[0].id

        # ✅ Get existing subcategories under Raw Material
        existing_docs = db.collection("product_sub_categories").where("main_id", "==", raw_material_main_id).get()
        existing_names = {doc.to_dict().get("name") for doc in existing_docs}

        missing = required_subs - existing_names
        if not missing:
            return  # ✅ All subcategories already exist

        for name in missing:
            db.collection("product_sub_categories").add({
                "name": name,
                "main_id": raw_material_main_id
            })
            print(f"Created sub-category: {name}")
            

    def run_first_time_setup(self):
        # Welcome popup
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from PyQt5.QtGui import QFont
        from PyQt5.QtCore import Qt

        class WelcomeDialog(QDialog):
            def __init__(self):
                super().__init__()
                self.setWindowTitle("Welcome to ERP Software")
                self.setFixedSize(600, 450)
                self.setStyleSheet("""
                    QDialog {
                        background-color: #ffffff;
                        border-radius: 16px;
                        border: 2px solid #0984e3;
                    }
                    QLabel {
                        color: #2d3436;
                    }
                    QPushButton {
                        background-color: #0984e3;
                        color: white;
                        font-weight: bold;
                        padding: 10px 20px;
                        border-radius: 8px;
                        font-size: 12pt;
                    }
                    QPushButton:hover {
                        background-color: #74b9ff;
                    }
                """)

                layout = QVBoxLayout(self)
                layout.setAlignment(Qt.AlignCenter)
                layout.setContentsMargins(40, 40, 40, 40)
                layout.setSpacing(20)

                title = QLabel("👋 Welcome to PlayWithAayan ERP System")
                title.setFont(QFont("Segoe UI", 16, QFont.Bold))
                title.setAlignment(Qt.AlignCenter)
                title.setWordWrap(True)
                layout.addWidget(title)

                subtitle = QLabel(
                    "We're excited to have you on board!\n\n"
                    "This ERP will streamline your operations, save time, and improve accuracy.\n\n"
                    "Let's begin by creating your Admin login."
                )
                subtitle.setAlignment(Qt.AlignCenter)
                subtitle.setWordWrap(True)
                subtitle.setFont(QFont("Segoe UI", 11))
                layout.addWidget(subtitle)
                layout.addSpacing(20)

                btn = QPushButton("🚀 Let's Begin")
                btn.setFixedWidth(200)
                btn.clicked.connect(self.accept)
                layout.addWidget(btn, alignment=Qt.AlignCenter)

        dlg = WelcomeDialog()
        dlg.exec_()

        dummy_admin_data = {
            "role": "admin",
            "branch": []
        }

        self.create_admin_window = CreateUserModule(dummy_admin_data, first_time=True)

        def after_admin_created():
            self.create_admin_window = None
            # Relaunch the current executable (python or .exe)
            subprocess.Popen([sys.executable] + sys.argv)
            sys.exit()

        self.create_admin_window.user_created.connect(after_admin_created)
        self.create_admin_window.show()
