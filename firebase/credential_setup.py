# firebase/credential_setup.py

from PyQt5.QtWidgets import (
    QDialog, QTextEdit, QPushButton, QVBoxLayout, QLabel,
    QFileDialog, QMessageBox, QLineEdit, QProgressDialog, QApplication
)
from PyQt5.QtCore import Qt
import json
from firebase.cred_loader import save_encrypted_credentials

class CredentialSetupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Authorize ERP with Firebase")
        self.setMinimumSize(550, 500)

        layout = QVBoxLayout(self)

        # JSON input field
        layout.addWidget(QLabel("Paste your Firebase credentials.json content:"))
        self.text_edit = QTextEdit()
        layout.addWidget(self.text_edit)

        # Upload button
        self.upload_btn = QPushButton("Or Upload File")
        self.upload_btn.clicked.connect(self.load_file)
        layout.addWidget(self.upload_btn)

        # API Key input
        layout.addWidget(QLabel("Enter your Firebase API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("e.g., AIzaSyXXX...")
        layout.addWidget(self.api_key_edit)

        # Save button
        self.save_btn = QPushButton("Initialize")
        self.save_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_btn)

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

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Firebase credentials.json", "", "JSON Files (*.json)")
        if file_path:
            with open(file_path, "r") as f:
                self.text_edit.setText(f.read())

    def save_data(self):
        try:
            # Show loader
            loader = self.show_loader(self, title="Saving Credentials", message="Encrypting and saving securely...")

            raw_json = self.text_edit.toPlainText()
            api_key = self.api_key_edit.text().strip()

            if not raw_json or not api_key:
                QMessageBox.warning(self, "Missing Fields", "Both fields are required.")
                return

            cred_dict = json.loads(raw_json)
            cred_dict["__api_key"] = api_key  # store API key with marker

            save_encrypted_credentials(cred_dict)

            loader.close()
            
            QMessageBox.information(self, "Success", "Credentials and API key saved securely.")
            self.accept()

        except Exception as e:
            loader.close()
            QMessageBox.critical(self, "Error", f"Invalid data: {e}")
