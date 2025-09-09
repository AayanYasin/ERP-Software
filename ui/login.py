# ui/login.py
from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QFrame, QMessageBox, QToolButton, QSizePolicy
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
import requests

from firebase.config import db, FIREBASE_LOGIN_URL, SECURE_TOKEN_URL
from firebase.cred_loader import get_refresh_token, set_refresh_token
from ui.dashboard import DashboardApp
from ui.network_monitor import NetworkMonitor


# --------------------- Worker Threads ---------------------

class LoginWorker(QThread):
    success = pyqtSignal(dict, str)
    error = pyqtSignal(str)

    def __init__(self, email: str, password: str, company_name: str, parent=None):
        super().__init__(parent)
        self.email = email
        self.password = self._safe_str(password)
        self.company_name = company_name
        self.session = requests.Session()

    def run(self):
        try:
            payload = {"email": self.email, "password": self.password, "returnSecureToken": True}
            res = self.session.post(FIREBASE_LOGIN_URL, json=payload, timeout=(3, 7))
            if res.status_code != 200:
                raise Exception("Invalid credentials or network issue")

            user_data = res.json()
            uid = user_data["localId"]
            refresh_token = user_data.get("refreshToken", "")

            user_doc = db.collection("users").document(uid).get()
            if not user_doc.exists:
                raise Exception("User profile not found in database.")

            profile = user_doc.to_dict()
            if refresh_token:
                set_refresh_token(refresh_token)

            self.success.emit(profile, self.company_name)
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _safe_str(s):
        return "" if s is None else str(s)


class RefreshWorker(QThread):
    success = pyqtSignal(dict, str)
    error = pyqtSignal(str)

    def __init__(self, refresh_token: str, company_name: str, parent=None):
        super().__init__(parent)
        self.refresh_token = refresh_token or ""
        self.company_name = company_name
        self.session = requests.Session()

    def run(self):
        try:
            if not self.refresh_token:
                raise Exception("No stored session")

            data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            r = self.session.post(SECURE_TOKEN_URL, data=data, timeout=(3, 7))
            if r.status_code != 200:
                set_refresh_token("")
                raise Exception("Session expired or network issue")

            out = r.json()
            uid = out.get("user_id")
            new_refresh = out.get("refresh_token", "")
            if new_refresh:
                set_refresh_token(new_refresh)

            user_doc = db.collection("users").document(uid).get()
            if not user_doc.exists:
                raise Exception("User profile not found in database.")

            profile = user_doc.to_dict()
            self.success.emit(profile, self.company_name)
        except Exception as e:
            self.error.emit(str(e))


# --------------------- UI ---------------------

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        try:
            doc = db.collection("meta").document("company_name").get()
            self.company_name = "ERP"
            if doc.exists:
                data = doc.to_dict()
                self.company_name = data.get("name", "ERP")
        except Exception:
            self.company_name = "ERP"

        self.setWindowTitle(f"{self.company_name} ERP - Login")
        self.setFixedSize(520, 540)

        # Global, clean styling; force all labels to be transparent
        self.setStyleSheet("""
            QWidget { background-color: #f6f8fb; }
            QLabel { background: transparent; }         /* <-- important */
            QFrame#card {
                background: #ffffff;
                border: none;
                border-radius: 12px;
            }
            QLabel.title {
                color: #0b1220; font-size: 22px; font-weight: 900;
                background: transparent;                 /* <-- important */
            }
            QLabel.badge {
                font-weight: 800; font-size: 11px;
                padding: 6px 10px; border-radius: 999px;
            }
            QLineEdit {
                padding: 9px 11px;
                border-radius: 8px;
                border: 1px solid #e6ebf2;
                background: #ffffff;
                selection-background-color: #cfe5ff;
            }
            QLineEdit:focus {
                border: 1px solid #7aa7ff;
                background: #fbfdff;
            }
            QPushButton.primary {
                background: #2563eb; color:#fff;
                border: none; border-radius: 8px;
                padding: 10px 14px; font-weight: 800;
            }
            QPushButton.primary:hover { background: #3b82f6; }
            QPushButton.primary:pressed { background: #1d4ed8; }
            QPushButton.primary:disabled { background: #a7b5cc; color:#f0f3f9; }
            QToolButton.eye { border: none; background: transparent; font-size: 16px; }
        """)

        self._build_ui()

        self._busy_guard = QTimer(self)
        self._busy_guard.setSingleShot(True)
        self._busy_guard.timeout.connect(lambda: self._set_busy(False))

        self.net_status = "online"
        self.monitor = NetworkMonitor(interval_sec=3.0, slow_threshold_ms=800, parent=self)
        self.monitor.status_changed.connect(self._on_net_status)
        self.monitor.start()

        rtok = get_refresh_token()
        if rtok:
            self._set_busy(True, "Checking session…")
            self.refresh_worker = RefreshWorker(rtok, self.company_name, self)
            self.refresh_worker.success.connect(self._on_login_success)
            self.refresh_worker.error.connect(self._on_silent_error)
            self.refresh_worker.start()

    def _build_ui(self):
        font_title = QFont("Segoe UI", 20, QFont.Bold)
        font_label = QFont("Segoe UI", 12)
        font_input = QFont("Segoe UI", 12)
        font_button = QFont("Segoe UI", 12, QFont.Bold)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(50, 40, 50, 40)  # more side/top padding
        main_layout.setSpacing(20)                      # more space between elements
        main_layout.setAlignment(Qt.AlignCenter)

        # --- Network badge sits above the card (no overlap with title) ---
        self.net_badge = QLabel("Checking…")
        self.net_badge.setObjectName("badge")
        self.net_badge.setProperty("class", "badge")
        self.net_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.net_badge.setAlignment(Qt.AlignRight)
        self._paint_net_badge("checking")
        main_layout.addWidget(self.net_badge, 0, Qt.AlignRight)

        # Card container for fields
        login_panel = QFrame()
        login_panel.setObjectName("card")
        login_layout = QVBoxLayout(login_panel)
        login_layout.setContentsMargins(32, 28, 32, 28) # more padding inside card
        login_layout.setSpacing(20)                     # more spacing between widgets

        # Title (transparent background)
        self.title_label = QLabel(f"{self.company_name} — ERP")
        self.title_label.setObjectName("title")
        self.title_label.setProperty("class", "title")
        self.title_label.setFont(QFont("Segoe UI", 22, QFont.Bold))
        self.title_label.setStyleSheet("margin-top: 6px; margin-bottom: 18px;")
        self.title_label.setAutoFillBackground(False)     # <-- ensure no fill
        login_layout.addWidget(self.title_label, 0, Qt.AlignHCenter)

        # Email
        email_label = QLabel("Email"); email_label.setFont(font_label)
        email_label.setAutoFillBackground(False)          # <-- ensure no fill
        email_label.setStyleSheet("background: transparent;")  # <-- belt & suspenders
        login_layout.addWidget(email_label)

        self.entry_email = QLineEdit(); self.entry_email.setFont(font_input)
        self.entry_email.setPlaceholderText("Enter your email")
        login_layout.addWidget(self.entry_email)

        # Password
        pass_label = QLabel("Password"); pass_label.setFont(font_label)
        pass_label.setAutoFillBackground(False)           # <-- ensure no fill
        pass_label.setStyleSheet("background: transparent;")
        login_layout.addWidget(pass_label)

        password_row = QHBoxLayout()
        self.entry_pass = QLineEdit(); self.entry_pass.setFont(font_input)
        self.entry_pass.setEchoMode(QLineEdit.Password)
        self.entry_pass.setPlaceholderText("Enter your password")
        password_row.addWidget(self.entry_pass)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("👁")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setProperty("class", "eye")
        self.toggle_btn.setObjectName("eye")
        self.toggle_btn.clicked.connect(self._toggle_password)
        password_row.addWidget(self.toggle_btn)
        login_layout.addLayout(password_row)

        # Login Button
        self.login_btn = QPushButton("Login")
        self.login_btn.setFont(font_button)
        self.login_btn.setProperty("class", "primary")
        self.login_btn.setObjectName("primary")
        self.login_btn.clicked.connect(self._handle_login)
        login_layout.addSpacing(6)
        login_layout.addWidget(self.login_btn)

        # Hint
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #64748b; background: transparent;")
        login_layout.addWidget(self.hint)

        main_layout.addStretch()
        main_layout.addWidget(login_panel)
        main_layout.addStretch()

    # ------- helpers -------
    def _toggle_password(self):
        if self.toggle_btn.isChecked():
            self.entry_pass.setEchoMode(QLineEdit.Normal)
            self.toggle_btn.setText("🙈")
        else:
            self.entry_pass.setEchoMode(QLineEdit.Password)
            self.toggle_btn.setText("👁")

    def _paint_net_badge(self, state: str, rtt_ms: int = 0):
        if state == "online":
            self.net_badge.setText(f"Online • {rtt_ms} ms")
            self.net_badge.setStyleSheet("color:#065f46; background:#d1fae5;")
        elif state == "slow":
            self.net_badge.setText(f"Slow • {rtt_ms} ms")
            self.net_badge.setStyleSheet("color:#92400e; background:#fef3c7;")
        elif state == "offline":
            self.net_badge.setText("Offline")
            self.net_badge.setStyleSheet("color:#7f1d1d; background:#fee2e2;")
        else:
            self.net_badge.setText("Checking…")
            self.net_badge.setStyleSheet("color:#374151; background:#f3f4f6;")

    def _set_busy(self, busy: bool, text: str = "Logging in…"):
        self.login_btn.setEnabled(not busy and self.net_status != "offline")
        self.login_btn.setText(text if busy else "Login")
        if busy:
            self._busy_guard.start(10000)
        else:
            self._busy_guard.stop()

    def _on_net_status(self, status: str, rtt_ms: int):
        self.net_status = status
        self._paint_net_badge(status, rtt_ms)
        if status == "offline":
            self.hint.setText("You're offline. Check your internet connection and try again.")
            self.login_btn.setEnabled(False)
        elif status == "slow":
            self.hint.setText("Network is slow. Login may take a few seconds.")
            if self.login_btn.text() != "Logging in…":
                self.login_btn.setEnabled(True)
        else:
            self.hint.setText("")
            if self.login_btn.text() != "Logging in…":
                self.login_btn.setEnabled(True)

    def _handle_login(self):
        if self.net_status == "offline":
            QMessageBox.warning(self, "No Internet", "You're offline. Please connect to the internet and try again.")
            return
        email = (self.entry_email.text() or "").strip()
        password = (self.entry_pass.text() or "").strip()
        if not email or not password:
            QMessageBox.warning(self, "Login Failed", "Please fill in all fields.")
            return
        self._set_busy(True, "Logging in…")
        self.worker = LoginWorker(email, password, self.company_name, self)
        self.worker.success.connect(self._on_login_success)
        self.worker.error.connect(self._on_login_error)
        self.worker.start()

    def _on_login_success(self, profile: dict, company_name: str):
        self._set_busy(False)
        self.dashboard = DashboardApp(profile.get("name", "User"), profile, company_name=company_name)
        self.dashboard.show()
        try:
            self.monitor.stop()
        except Exception:
            pass
        self.close()

    def _on_login_error(self, message: str):
        self._set_busy(False)
        QMessageBox.critical(self, "Login Failed", message)

    def _on_silent_error(self, _msg: str):
        self._set_busy(False)

    def closeEvent(self, event):
        # Wait for workers, if any
        for attr in ("worker", "refresh_worker"):
            w = getattr(self, attr, None)
            if w and w.isRunning():
                try:
                    w.wait(2000)   # up to 2s
                except Exception:
                    try:
                        w.terminate(); w.wait(1000)
                    except Exception:
                        pass
        # Stop the monitor and wait
        try:
            if getattr(self, "monitor", None):
                self.monitor.stop()
        except Exception:
            pass
        super().closeEvent(event)
