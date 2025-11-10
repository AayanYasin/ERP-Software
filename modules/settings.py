# settings.py

import os
import sys
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFrame, QListWidget, QLineEdit, QScrollArea,
    QProgressDialog
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
from firebase.config import db


class SettingsWindow(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.setWindowTitle("ERP Settings")
        self.setFixedSize(600, 650)
        self.setStyleSheet("background-color: #f8f9fa;")

        self.user_data = user_data
        self.settings_changed = False

        docs = db.collection("users").where("email", "==", self.user_data["email"]).limit(1).get()
        if not docs:
            QMessageBox.critical(self, "Error", "Could not find user document.")
            self.close()
            return

        self.user_doc = docs[0].reference

        # Create scroll area
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(30, 30, 30, 30)
        self.scroll_layout.setSpacing(25)

        scroll.setWidget(scroll_content)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)

        # Floating banner
        self.restart_banner = QWidget(self)
        self.restart_banner.setStyleSheet("background-color: #ffeaa7; border: 1px solid #fdcb6e;")
        self.restart_banner.setFixedHeight(40)
        self.restart_banner.hide()

        banner_layout = QHBoxLayout(self.restart_banner)
        banner_layout.setContentsMargins(10, 0, 10, 0)
        banner_layout.addWidget(QLabel("Changes made. Please restart to apply."))

        restart_now_btn = QPushButton("Restart Now")
        restart_now_btn.setCursor(Qt.PointingHandCursor)
        restart_now_btn.setStyleSheet("""
            QPushButton {
                background-color: #e17055;
                color: white;
                padding: 5px 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #d35400;
            }
        """)
        restart_now_btn.clicked.connect(self.restart_app)
        banner_layout.addWidget(restart_now_btn)
        banner_layout.addStretch()

        main_layout.addWidget(self.restart_banner)

        loader = self.show_loader(self, "Please wait...", "Loading Data")
        self.setup_ui()
        
        # Call load_branches only if the user is an admin
        if self.user_data.get("role") == "admin":
            self.load_branches()
            self.load_colors()  # This can remain for both admins and non-admins
            
        loader.close()

    def setup_ui(self):
        layout = self.scroll_layout

        title = QLabel("ERP Settings")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # ─── Remove Access ───
        remove_row = QHBoxLayout()
        remove_label = QLabel("Remove database access for this PC")
        remove_label.setFont(QFont("Segoe UI", 12))
        remove_btn = self.styled_button("Remove Access", "#b71c1c", "#e53935")
        remove_btn.clicked.connect(self.confirm_reset)
        remove_row.addWidget(remove_label)
        remove_row.addStretch()
        remove_row.addWidget(remove_btn)
        layout.addLayout(remove_row)

        layout.addWidget(self.divider())

        # Only show the Branch and Color Sections for Admins
        if self.user_data.get("role") == "admin":
            # ─── Branch Section ───
            layout.addWidget(self.section_title("Manage Branches"))
            self.branch_list = QListWidget()
            self.branch_input = QLineEdit()
            self.branch_input.setPlaceholderText("Enter new branch name...")

            branch_btn_row = QHBoxLayout()
            branch_add_btn = self.styled_button("Add", "#0984e3", "#74b9ff")
            branch_delete_btn = self.styled_button("Delete", "#d63031", "#ff7675")
            branch_add_btn.clicked.connect(self.add_branch)
            branch_delete_btn.clicked.connect(self.delete_selected_branch)
            branch_btn_row.addWidget(branch_add_btn)
            branch_btn_row.addWidget(branch_delete_btn)

            layout.addWidget(self.branch_list)
            layout.addWidget(self.branch_input)
            layout.addLayout(branch_btn_row)

            layout.addWidget(self.divider())

            # ─── Color Section ───
            layout.addWidget(self.section_title("Manage Product Colors"))
            self.color_list = QListWidget()
            self.color_input = QLineEdit()
            self.color_input.setPlaceholderText("Enter new color...")

            color_btn_row = QHBoxLayout()
            color_add_btn = self.styled_button("Add", "#00b894", "#55efc4")
            color_delete_btn = self.styled_button("Delete", "#d63031", "#ff7675")
            color_add_btn.clicked.connect(self.add_color)
            color_delete_btn.clicked.connect(self.delete_selected_color)
            color_btn_row.addWidget(color_add_btn)
            color_btn_row.addWidget(color_delete_btn)

            layout.addWidget(self.color_list)
            layout.addWidget(self.color_input)
            layout.addLayout(color_btn_row)

            layout.addWidget(self.divider())

        else:
            # If the user is not an admin, show only the "Remove Access" option
            more = QLabel("More settings coming soon...")
            more.setFont(QFont("Segoe UI", 10))
            more.setStyleSheet("color: #a4b0be;")
            more.setAlignment(Qt.AlignCenter)
            layout.addWidget(more)

    # ─── Helpers ───
    def section_title(self, text):
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        label.setStyleSheet("color: #2d3436;")
        return label

    def divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def styled_button(self, text, color, hover_color):
        btn = QPushButton(text)
        btn.setFont(QFont("Segoe UI", 11))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                padding: 8px 18px;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """)
        return btn

    def show_loader(self, parent, title="Please wait...", message="Processing..."):
        loader = QProgressDialog(message, None, 0, 0, parent)
        loader.setWindowModality(Qt.WindowModal)
        loader.setAutoClose(True)
        loader.setCancelButton(None)
        loader.setWindowTitle(title)
        loader.show()
        QApplication.processEvents()
        return loader

    def show_restart_banner(self):
        self.settings_changed = True
        self.restart_banner.show()

    def restart_app(self):
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit()

    # ─── Events ───
    def closeEvent(self, event):
        if self.settings_changed:
            QMessageBox.information(
                self,
                "Restart Required",
                "App will now restart to apply settings."
            )
            self.restart_app()
        event.accept()
        
    def confirm_reset(self):
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            "Are you sure you want to remove database access?\n\nYour data in the cloud remains safe.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.remove_credentials()

    # ─── Cred Delete ───
    def remove_credentials(self):
        path = os.path.join(os.getenv("APPDATA"), "MyERP", "cred.bin")
        if os.path.exists(path):
            try:
                os.remove(path)
                QMessageBox.information(self, "Done", "Access removed. The app will now close.")
                QApplication.quit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete: {e}")
        else:
            QMessageBox.information(self, "Already Clean", "No access file found. You're good.")

    # ─── Branches ───
    def load_branches(self):
        doc = self.user_doc.get().to_dict()
        self.branches = doc.get("branch", [])
        self.branch_list.clear()
        for b in self.branches:
            self.branch_list.addItem(b)

    def add_branch(self):
        name = self.branch_input.text().strip().title()
        if not name or name in self.branches:
            return
        self.branches.append(name)
        self.user_doc.update({"branch": self.branches})
        self.load_branches()
        self.branch_input.clear()
        self.show_restart_banner()

    def delete_selected_branch(self):
        selected = self.branch_list.currentItem()
        if not selected:
            return
        name = selected.text()
        reply = QMessageBox.question(self, "Delete Branch", f"Delete branch '{name}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.branches.remove(name)
            self.user_doc.update({"branch": self.branches})
            self.load_branches()
            self.show_restart_banner()

    # ─── Colors ───
    def load_colors(self):
        doc = db.collection("meta").document("colors").get().to_dict()
        self.colors = doc.get("pc_colors", []) if doc else []
        self.color_list.clear()
        for c in self.colors:
            self.color_list.addItem(c)

    def add_color(self):
        color = self.color_input.text().strip().title()
        if not color or color in self.colors:
            return
        self.colors.append(color)
        db.collection("meta").document("colors").set({"pc_colors": self.colors})
        self.load_colors()
        self.color_input.clear()
        self.show_restart_banner()

    def delete_selected_color(self):
        selected = self.color_list.currentItem()
        if not selected:
            return
        color = selected.text()
        reply = QMessageBox.question(self, "Delete Color", f"Delete color '{color}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.colors.remove(color)
            db.collection("meta").document("colors").set({"pc_colors": self.colors})
            self.load_colors()
            self.show_restart_banner()
