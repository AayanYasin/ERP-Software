# firebase/config.py

import os
import firebase_admin
from firebase_admin import credentials, firestore
from PyQt5.QtWidgets import QApplication, QDialog
from firebase.cred_loader import credentials_exist, load_decrypted_credentials, get_api_key
from firebase.credential_setup import CredentialSetupDialog

# Show setup dialog if credentials are missing
if not credentials_exist():
    app = QApplication([])
    dialog = CredentialSetupDialog()
    if dialog.exec_() != QDialog.Accepted:
        exit()

# Load credentials
cred_dict = load_decrypted_credentials()
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Load API key from secure store
FIREBASE_API_KEY = get_api_key()
FIREBASE_LOGIN_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
