# ui/login.py
from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QFrame, QMessageBox, QToolButton, QSizePolicy, QProgressDialog
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
import requests
from packaging.version import Version, InvalidVersion

from firebase.config import db, FIREBASE_LOGIN_URL, SECURE_TOKEN_URL, APP_VERSION
from firebase.cred_loader import get_refresh_token, set_refresh_token
from ui.dashboard import DashboardApp
from ui.network_monitor import NetworkMonitor
import subprocess
import hashlib
import os
import tempfile
import sys

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


# --------------------- Updater Threads ---------------------

class UpdateChecker(QThread):
    """Reads Firestore doc: meta/appdata"""
    found = pyqtSignal(dict)     # emits manifest dict
    error = pyqtSignal(str)

    def run(self):
        try:
            doc = db.collection("meta").document("appdata").get()
            self.found.emit(doc.to_dict() if doc.exists else {})
        except Exception as e:
            self.error.emit(str(e))


class UpdateDownloader(QThread):
    progress = pyqtSignal(int)   # 0..100
    done = pyqtSignal(str)       # local path
    error = pyqtSignal(str)

    def __init__(self, url: str, sha256: str = "", parent=None):
        super().__init__(parent)
        self.url = (url or "").strip()
        self.sha256 = (sha256 or "").lower().strip()

    def run(self):
        try:
            if not self.url:
                raise RuntimeError("No update URL provided")

            r = requests.get(self.url, stream=True, timeout=(5, 60))
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)

            # Prefer temp; fallback to Downloads if needed
            try:
                fd, tmp_path = tempfile.mkstemp(prefix="erp_update_", suffix=".exe")
                os.close(fd)
            except Exception:
                downloads = os.path.join(os.path.expanduser("~"), "Downloads")
                os.makedirs(downloads, exist_ok=True)
                tmp_path = os.path.join(downloads, "ERP_Update.exe")

            h = hashlib.sha256()
            read = 0
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(128 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    h.update(chunk)
                    read += len(chunk)
                    if total:
                        self.progress.emit(int(read * 100 / total))

            # If content-length present, finish at 100
            if total:
                self.progress.emit(100)

            if self.sha256:
                if h.hexdigest().lower() != self.sha256:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    raise RuntimeError("Integrity check failed (SHA-256 mismatch).")

            self.done.emit(tmp_path)
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
            QLabel { background: transparent; }
            QFrame#card {
                background: #ffffff;
                border: none;
                border-radius: 12px;
            }
            QLabel.title {
                color: #0b1220; font-size: 22px; font-weight: 900;
                background: transparent;
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

        # Updater check after monitor starts
        self._check_for_updates()

        # Try session refresh if token exists
        rtok = get_refresh_token()
        if rtok:
            self._set_busy(True, "Checking session…")
            self.refresh_worker = RefreshWorker(rtok, self.company_name, self)
            self.refresh_worker.success.connect(self._on_login_success)
            self.refresh_worker.error.connect(self._on_silent_error)
            self.refresh_worker.start()

    # ------- Updater -------
    def _check_for_updates(self):
        if getattr(self, "net_status", "online") == "offline":
            return
        self._upd = UpdateChecker(self)
        self._upd.found.connect(self._on_update_manifest)
        self._upd.error.connect(lambda _e: None)  # silent
        self._upd.start()

    def _on_update_manifest(self, m: dict):
        try:
            latest = str(m.get("version", "")).strip()
            url     = str(m.get("url", "")).strip()
            must    = bool(m.get("mandatory", False))
            notes   = str(m.get("notes", "") or "").strip()
            sha256  = str(m.get("sha256", "") or "").strip()
            if not latest or not url:
                return

            def v(vs):
                try: return Version(vs)
                except InvalidVersion: return Version("0")

            if v(latest) <= v(APP_VERSION):
                return  # already on newest

            msg = f"New version {latest} is available (you have {APP_VERSION})."
            if notes:
                msg += f"\n\nWhat's new:\n{notes}"

            buttons = QMessageBox.Ok if must else (QMessageBox.Ok | QMessageBox.Cancel)
            title = "Update Required" if must else "Update Available"
            choice = QMessageBox.information(self, title, msg + "\n\nUpdate now?", buttons)

            if choice == QMessageBox.Ok:
                self._download_and_install(url, sha256, force=must)
            elif must:
                QMessageBox.warning(self, "Update Required", "This update is mandatory. The app will now close.")
                self.close()
        except Exception:
            pass

    # Add these helper methods to handle the app update process
    def _download_and_install(self, url: str, sha256: str, force: bool = False):
        self._prog = QProgressDialog("Downloading update…", None, 0, 100, self)
        self._prog.setWindowModality(Qt.ApplicationModal)
        self._prog.setCancelButton(None)
        self._prog.setMinimumDuration(0)
        self._prog.setAutoClose(True)
        self._prog.show()

        # Start the download process
        self.dl = UpdateDownloader(url, sha256, self)
        self.dl.progress.connect(self._prog.setValue)
        self.dl.done.connect(self._on_update_downloaded)
        # For mandatory updates: show error; for optional: close quietly
        self.dl.error.connect(self._on_update_error if force else self._on_update_error_quiet)
        self.dl.start()

    def _on_update_downloaded(self, local_path: str):
        try:
            if getattr(self, "_prog", None):
                self._prog.reset()

            current_exe = sys.executable
            new_exe = local_path
            updater_path = os.path.join(tempfile.gettempdir(), "erp_updater.bat")

            bat_script = f"""@echo off
            echo Waiting for application to close...

            :waitloop
            tasklist | find /i "YourApp.exe" >nul
            if not errorlevel 1 (
                timeout /t 1 /nobreak >nul
                goto waitloop
            )

            echo App closed. Waiting for cleanup...
            timeout /t 4 /nobreak >nul

            echo Replacing old version...
            move /y "{new_exe}" "{current_exe}" >nul 2>&1

            if errorlevel 1 (
                echo Move failed, retrying...
                timeout /t 2 /nobreak >nul
                move /y "{new_exe}" "{current_exe}" >nul 2>&1
            )

            echo Starting updated version...
            timeout /t 1 /nobreak >nul
            start "" "{current_exe}"

            :: delete the updater script itself
            del "%~f0" & exit
            """

            with open(updater_path, "w") as f:
                f.write(bat_script)

            # Start the updater and forcefully exit immediately
            subprocess.Popen(["cmd", "/c", updater_path], creationflags=subprocess.CREATE_NO_WINDOW)

            # Give the subprocess a small head start, then kill this process completely
            QTimer.singleShot(300, lambda: os._exit(0))

        except Exception as e:
            QMessageBox.critical(self, "Update Failed", str(e))



    def _delete_current_app(self):
        # Specify the path to your current application file
        current_app_path = os.path.join(os.path.expanduser("~"), "Documents", "YourApp.exe")

        # Check if the app exists and delete it
        if os.path.exists(current_app_path):
            try:
                os.remove(current_app_path)  # Try to delete the file
                print(f"Successfully deleted the old app at {current_app_path}")
            except Exception as e:
                print(f"Failed to delete current app: {e}")
        else:
            print("Current app not found, skipping deletion.")

    def _replace_with_new_exe(self, new_exe_path: str):
        try:
            # Specify the final path where the new EXE will be placed (e.g., the original app path)
            final_app_path = os.path.join(os.path.expanduser("~"), "Documents", "YourApp.exe")

            # Rename the downloaded EXE to the final app name
            os.rename(new_exe_path, final_app_path)

            print(f"New app installed successfully at {final_app_path}")

        except Exception as e:
            print(f"Failed to replace app with new version: {e}")
            raise RuntimeError("Failed to replace old app with new version.")

    def _on_update_error(self, msg: str):
        # Mandatory update: show the error
        try:
            if getattr(self, "_prog", None):
                self._prog.reset()
        except Exception:
            pass
        QMessageBox.critical(self, "Update Failed", msg)

    def _on_update_error_quiet(self, _msg: str):
        # Optional update: close dialog, no popups
        try:
            if getattr(self, "_prog", None):
                self._prog.reset()
        except Exception:
            pass

    # ------- UI Build -------
    def _build_ui(self):
        font_title = QFont("Segoe UI", 20, QFont.Bold)
        font_label = QFont("Segoe UI", 12)
        font_input = QFont("Segoe UI", 12)
        font_button = QFont("Segoe UI", 12, QFont.Bold)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(50, 40, 50, 40)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignCenter)

        # Network badge
        self.net_badge = QLabel("Checking…")
        self.net_badge.setObjectName("badge")
        self.net_badge.setProperty("class", "badge")
        self.net_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.net_badge.setAlignment(Qt.AlignRight)
        self._paint_net_badge("checking")
        main_layout.addWidget(self.net_badge, 0, Qt.AlignRight)

        # Card
        login_panel = QFrame()
        login_panel.setObjectName("card")
        login_layout = QVBoxLayout(login_panel)
        login_layout.setContentsMargins(32, 28, 32, 28)
        login_layout.setSpacing(20)

        # Title
        self.title_label = QLabel(f"{self.company_name} — ERP")
        self.title_label.setObjectName("title")
        self.title_label.setProperty("class", "title")
        self.title_label.setFont(QFont("Segoe UI", 22, QFont.Bold))
        self.title_label.setStyleSheet("margin-top: 6px; margin-bottom: 18px;")
        self.title_label.setAutoFillBackground(False)
        login_layout.addWidget(self.title_label, 0, Qt.AlignHCenter)

        # Email
        email_label = QLabel("Email"); email_label.setFont(font_label)
        email_label.setAutoFillBackground(False)
        email_label.setStyleSheet("background: transparent;")
        login_layout.addWidget(email_label)

        self.entry_email = QLineEdit(); self.entry_email.setFont(font_input)
        self.entry_email.setPlaceholderText("Enter your email")
        login_layout.addWidget(self.entry_email)

        # Password
        pass_label = QLabel("Password"); pass_label.setFont(font_label)
        pass_label.setAutoFillBackground(False)
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
