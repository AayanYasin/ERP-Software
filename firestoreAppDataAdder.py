# create_update_manifest.py
from firebase.config import db   # your existing Firestore connection

# --- CONFIGURE THESE ---
VERSION = "1.3.2"
URL = "https://github.com/<OWNER>/<REPO>/releases/download/v1.3.2/ERP_Setup_1.3.2.exe"
SHA256 = "PUT_YOUR_HASH_HERE"
MANDATORY = False
NOTES = "Bug fixes and dashboard improvements."
PLATFORM = "windows"
# ------------------------

def create_or_update_manifest():
    """Creates or updates Firestore document meta/appdata."""
    doc_ref = db.collection("meta").document("appdata")
    data = {
        "platform": PLATFORM,
        "version": VERSION,
        "url": URL,
        "sha256": SHA256,
        "mandatory": MANDATORY,
        "notes": NOTES,
    }

    doc_ref.set(data)
    print(f"✅ Firestore document meta/appdata updated to version {VERSION}")

if __name__ == "__main__":
    create_or_update_manifest()
