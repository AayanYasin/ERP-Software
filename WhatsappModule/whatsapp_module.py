from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QListWidget, QListWidgetItem, QMessageBox
)


import os
import json
import logging
import threading

from PyQt5.QtCore import Qt

from firebase.config import db
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import tempfile
import time
from selenium.common.exceptions import TimeoutException
import traceback

logger = logging.getLogger("modules.whatsapp_module")
logging.basicConfig(level=logging.INFO)

PROFILE_SAVE_FILE = "whatsapp_profile.json"

def get_chrome_user_data_path():
    if os.name == "nt":
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    elif os.name == "posix":
        return os.path.expanduser("~/.config/google-chrome")
    else:
        return ""


class WhatsAppIntegrationWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WhatsApp Integration")
        self.setMinimumWidth(400)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.chrome_user_data_dir = get_chrome_user_data_path()

        self.link_input = QLineEdit()
        self.link_input.setPlaceholderText("Enter number or WhatsApp group invite link")
        self.layout.addWidget(QLabel("WhatsApp Target:"))
        self.layout.addWidget(self.link_input)

        self.module_dropdown = QComboBox()
        self.module_dropdown.addItems(["Manufacturing"])
        self.layout.addWidget(QLabel("Module:"))
        self.layout.addWidget(self.module_dropdown)

        self.profile_dropdown = QComboBox()
        self.layout.addWidget(QLabel("Chrome Profile:"))
        self.layout.addWidget(self.profile_dropdown)

        self.load_chrome_profiles()
        self.load_saved_profile()

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_to_firestore)
        self.layout.addWidget(self.save_btn)

        self.entry_list = QListWidget()
        self.entry_list.itemClicked.connect(self.load_entry)
        self.layout.addWidget(QLabel("Saved WhatsApp Links:"))
        self.layout.addWidget(self.entry_list)

        self.send_btn = QPushButton("Send Test Message")
        self.send_btn.clicked.connect(self.send_message)
        self.layout.addWidget(self.send_btn)

        self.selected_doc_id = None
        self.load_saved_entries()

    def load_chrome_profiles(self):
        self.profile_dropdown.clear()
        profiles = []
        if os.path.exists(self.chrome_user_data_dir):
            for f in os.listdir(self.chrome_user_data_dir):
                full_path = os.path.join(self.chrome_user_data_dir, f)
                if os.path.isdir(full_path) and (f.startswith("Profile") or f == "Default"):
                    profiles.append(f)
        profiles.sort()
        self.profile_dropdown.addItems(profiles or ["Default"])

    def load_saved_profile(self):
        if os.path.exists(PROFILE_SAVE_FILE):
            with open(PROFILE_SAVE_FILE, "r") as f:
                profile = json.load(f).get("profile")
                index = self.profile_dropdown.findText(profile)
                if index >= 0:
                    self.profile_dropdown.setCurrentIndex(index)

    def save_selected_profile(self):
        selected_profile = self.profile_dropdown.currentText()
        with open(PROFILE_SAVE_FILE, "w") as f:
            json.dump({"profile": selected_profile}, f)

    def save_to_firestore(self):
        data = {
            "target": self.link_input.text().strip(),
            "module": self.module_dropdown.currentText()
        }

        if not data["target"]:
            QMessageBox.warning(self, "Input Error", "Please enter a valid number or group link.")
            return

        if self.selected_doc_id:
            db.collection("whatsapp").document(self.selected_doc_id).update(data)
        else:
            db.collection("whatsapp").add(data)

        self.link_input.clear()
        self.selected_doc_id = None
        self.load_saved_entries()
        self.save_selected_profile()

    def load_saved_entries(self):
        self.entry_list.clear()
        entries = db.collection("whatsapp").stream()
        for doc in entries:
            item = QListWidgetItem(f'{doc.to_dict().get("target")} ({doc.to_dict().get("module")})')
            item.setData(Qt.UserRole, doc.id)
            self.entry_list.addItem(item)

    def load_entry(self, item):
        doc_id = item.data(Qt.UserRole)
        doc = db.collection("whatsapp").document(doc_id).get()
        if doc.exists:
            data = doc.to_dict()
            self.link_input.setText(data["target"])
            index = self.module_dropdown.findText(data["module"])
            self.module_dropdown.setCurrentIndex(index if index >= 0 else 0)
            self.selected_doc_id = doc_id

    def send_message(self):
        self.save_selected_profile()
        items = db.collection("whatsapp").stream()
        for doc in items:
            data = doc.to_dict()
            threading.Thread(
                target=self._send_whatsapp,
                args=(data["target"], "This is a test message."),
                daemon=True
            ).start()

    def _send_whatsapp(self, target, message):
        try:
            # Create a temporary clean user profile
            temp_user_data_dir = tempfile.mkdtemp()

            options = Options()
            options.add_argument(f"--user-data-dir={temp_user_data_dir}")
            options.add_argument("--no-sandbox")
            options.add_argument("--window-size=1200,800")
            options.add_argument("--disable-extensions")
            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            logger.info("✅ Chrome launched")

            driver.get("https://web.whatsapp.com")
            logger.info("🔄 Waiting for WhatsApp Web to load...")

            # Wait up to 60 seconds for the chat list to appear
            try:
                WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='chat-list']"))
                )
                logger.info("✅ WhatsApp Web is ready")
            except TimeoutException:
                logger.error("❌ Timeout: WhatsApp Web did not load properly")
                return

            # Send message
            if "http" in target:
                logger.info(f"➡️ Opening group link: {target}")
                driver.get(target)
            else:
                url = f"https://web.whatsapp.com/send?phone={target}&text={message}"
                logger.info(f"➡️ Opening chat with: {target}")
                driver.get(url)

            # Wait for send button to appear
            try:
                send_button = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']"))
                )
                send_button.click()
                logger.info(f"✅ Message sent to {target}")
            except TimeoutException:
                logger.error("❌ Send button not found - maybe the number is not on WhatsApp or blocked.")

        except Exception as e:
            logger.error(f"❌ Failed to send message to {target}: {e}")
            logger.error(traceback.format_exc())
        finally:
            try:
                driver.quit()
            except:
                pass