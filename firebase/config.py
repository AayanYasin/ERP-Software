# # firebase/config.py

# import os
# import firebase_admin
# from firebase_admin import credentials, firestore
# from PyQt5.QtWidgets import QApplication, QDialog
# from firebase.cred_loader import credentials_exist, load_decrypted_credentials, get_api_key
# from firebase.credential_setup import CredentialSetupDialog

# # Show setup dialog if credentials are missing
# if not credentials_exist():
#     app = QApplication([])
#     dialog = CredentialSetupDialog()
#     if dialog.exec_() != QDialog.Accepted:
#         exit()

# # Load credentials
# cred_dict = load_decrypted_credentials()
# cred = credentials.Certificate(cred_dict)

# if not firebase_admin._apps:
#     firebase_admin.initialize_app(cred)

# db = firestore.client()

# # Load API key from secure store
# FIREBASE_API_KEY = get_api_key()
# FIREBASE_LOGIN_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
# SECURE_TOKEN_URL = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"

# firebase/config.py — lazy, side-effect free, backward-compatible

import os
import threading
import firebase_admin
from firebase_admin import credentials, firestore

from firebase.cred_loader import (
    credentials_exist,
    load_decrypted_credentials,
    get_api_key,
    get_value,  # optional convenience
)

# ---------- Public constants (lightweight) ----------
_FIREBASE_API_KEY = get_api_key() or ""
FIREBASE_LOGIN_URL = (
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={_FIREBASE_API_KEY}"
    if _FIREBASE_API_KEY else ""
)
SECURE_TOKEN_URL = (
    f"https://securetoken.googleapis.com/v1/token?key={_FIREBASE_API_KEY}"
    if _FIREBASE_API_KEY else ""
)

# ---------- Lazy Firestore client (public: db) ----------
__db_lock = threading.Lock()
__db_real = None

def _ensure_db():
    global __db_real
    if __db_real is not None:
        return __db_real
    with __db_lock:
        if __db_real is not None:
            return __db_real

        if not credentials_exist():
            raise RuntimeError("Firebase credentials/API key missing. Run credential setup first.")

        sa = load_decrypted_credentials()
        if not sa:
            raise RuntimeError("Failed to load/decrypt Firebase service-account credentials.")

        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(sa))
        __db_real = firestore.client()
        return __db_real

class _LazyFirestore:
    """Proxy that initializes Firestore only on first use."""
    def __getattr__(self, name):
        return getattr(_ensure_db(), name)
    def __call__(self, *args, **kwargs):
        return _ensure_db()(*args, **kwargs)

db = _LazyFirestore()  # ← exported name used by 100+ modules


# ---- App Version (bump this each release) ----
APP_VERSION = "1.0.9"