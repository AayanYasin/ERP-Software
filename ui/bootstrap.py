# bootstrap.py

from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QTimer, QThread
from firebase.config import db
from ui.login import LoginWindow
from modules.create_new_login import CreateUserModule

import sys, subprocess

class AppBootstrap:
    def __init__(self, app: QApplication):
        self.app = app
        self.login_window = None
        self.create_admin_window = None

    def launch_login(self):
        self.login_window = LoginWindow()
        self.login_window.show()

    def start(self):
        try:
            # ✅ Show login UI immediately (no pre-login Firestore work)
            self.launch_login()

            # Run ensure tasks shortly after UI shows, in a worker thread
            QTimer.singleShot(0, self._kick_background_setup)

        except Exception as e:
            QMessageBox.critical(None, "Startup Error", f"Could not complete startup:\n{e}")
            self.launch_login()

    # -------------- background setup --------------
    def _kick_background_setup(self):
        self.worker = _SetupWorker()
        self.worker.finished_ok.connect(self._after_setup)
        self.worker.error.connect(self._setup_error)
        self.worker.start()

    def _after_setup(self, has_users: bool):
        if not has_users:
            self.run_first_time_setup()

    def _setup_error(self, msg: str):
        # Non-fatal; we already showed login
        print("[Bootstrap] Background setup error:", msg)

    # -------------- first time setup (unchanged flow) --------------
    def run_first_time_setup(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from PyQt5.QtGui import QFont
        from PyQt5.QtCore import Qt

        class WelcomeDialog(QDialog):
            def __init__(self):
                super().__init__()
                self.setWindowTitle("Welcome to ERP Software")
                self.setFixedSize(600, 450)
                self.setStyleSheet("""
                    QDialog { background-color: #ffffff; border-radius: 16px; border: 2px solid #0984e3; }
                    QLabel { color: #2d3436; }
                    QPushButton { background-color: #0984e3; color: white; font-weight: bold; padding: 10px 20px; border-radius: 8px; font-size: 12pt; }
                    QPushButton:hover { background-color: #74b9ff; }
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
                subtitle.setAlignment(Qt.AlignCenter); subtitle.setWordWrap(True); subtitle.setFont(QFont("Segoe UI", 11))
                layout.addWidget(subtitle); layout.addSpacing(20)
                btn = QPushButton("🚀 Let's Begin"); btn.setFixedWidth(200); btn.clicked.connect(self.accept)
                layout.addWidget(btn, alignment=Qt.AlignCenter)

        dlg = WelcomeDialog(); dlg.exec_()

        dummy_admin_data = {"role": "admin", "branch": []}
        self.create_admin_window = CreateUserModule(dummy_admin_data, first_time=True)

        def after_admin_created():
            self.create_admin_window = None
            subprocess.Popen([sys.executable] + sys.argv)
            sys.exit()

        self.create_admin_window.user_created.connect(after_admin_created)
        self.create_admin_window.show()


# ---------------- worker to run setup async ----------------

from PyQt5.QtCore import pyqtSignal
class _SetupWorker(QThread):
    finished_ok = pyqtSignal(bool)  # has_users
    error = pyqtSignal(str)

    def run(self):
        try:
            # ensure meta docs
            meta_ref = db.collection("meta").document("item_code_counter")
            if not meta_ref.get().exists:
                meta_ref.set({"last_code": 1000})
            colors_ref = db.collection("meta").document("colors")
            if not colors_ref.get().exists:
                colors_ref.set({"pc_colors": ["No Color", "Black", "White", "Red", "Blue", "Orange"]})

            # ensure main/sub categories
            collection_name = "product_main_categories"
            required_names = {"Raw Material", "Finished Products"}
            existing_docs = db.collection(collection_name).get()
            existing_names = {doc.to_dict().get("name") for doc in existing_docs}
            missing = required_names - existing_names
            for name in missing:
                db.collection(collection_name).add({"name": name})

            required_subs = {"Metal Sheet", "Metal Pipe"}
            main_docs = db.collection("product_main_categories").where("name", "==", "Raw Material").get()
            if main_docs:
                raw_material_main_id = main_docs[0].id
                existing_docs = db.collection("product_sub_categories").where("main_id", "==", raw_material_main_id).get()
                existing_names = {doc.to_dict().get("name") for doc in existing_docs}
                for name in (required_subs - existing_names):
                    db.collection("product_sub_categories").add({"name": name, "main_id": raw_material_main_id})

            # users present?
            users = db.collection("users").limit(1).get()
            self.finished_ok.emit(bool(users))
        except Exception as e:
            self.error.emit(str(e))
