import os, json, hashlib, uuid
from Crypto.Cipher import AES
from base64 import b64encode, b64decode

# Path to encrypted credentials
CREDENTIALS_PATH = os.path.join(os.getenv("APPDATA"), "PlayWithAayan-ERP_Software", "cred.bin")

# ✅ Step 1: Derive key from machine fingerprint (MAC address)
def get_machine_fingerprint() -> str:
    return str(uuid.getnode())

def derive_machine_key() -> bytes:
    fingerprint = get_machine_fingerprint()
    return hashlib.sha256(fingerprint.encode()).digest()  # 32-byte key

KEY = derive_machine_key()  # 🔐 machine-bound AES key

# ✅ Step 2: AES encryption helpers
def pad(data):
    return data + b"\0" * (16 - len(data) % 16)

def encrypt(data: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(pad(data))
    return cipher.nonce + ciphertext

def decrypt(enc_data: bytes, key: bytes) -> bytes:
    nonce = enc_data[:16]
    ciphertext = enc_data[16:]
    cipher = AES.new(key, AES.MODE_EAX, nonce)
    return cipher.decrypt(ciphertext).rstrip(b"\0")

# ✅ Step 3: Save/Load credentials securely
def save_encrypted_credentials(json_dict: dict):
    os.makedirs(os.path.dirname(CREDENTIALS_PATH), exist_ok=True)
    enc_data = encrypt(json.dumps(json_dict).encode(), KEY)
    with open(CREDENTIALS_PATH, "wb") as f:
        f.write(enc_data)

def load_decrypted_credentials() -> dict:
    with open(CREDENTIALS_PATH, "rb") as f:
        enc = f.read()
    return json.loads(decrypt(enc, KEY).decode())

# ✅ Step 4: Utilities
def credentials_exist() -> bool:
    return os.path.exists(CREDENTIALS_PATH)

def get_api_key() -> str:
    return load_decrypted_credentials().get("__api_key", "")
