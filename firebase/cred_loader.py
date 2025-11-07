# firebase/cred_loader.py
import os
import json
import uuid
import hashlib
import tempfile
from typing import Dict

try:
    from Crypto.Cipher import AES  # PyCryptodome
except Exception as e:
    raise RuntimeError("PyCryptodome is required (pip install pycryptodome)") from e


# -------------------------
# Storage location (Windows-friendly, works elsewhere too)
# -------------------------
def _app_dir() -> str:
    base = os.environ.get("APPDATA")
    if base and os.path.isdir(base):
        root = os.path.join(base, "PlayWithAayan-ERP_Software")
    else:
        root = os.path.join(os.path.expanduser("~"), ".config", "PlayWithAayan-ERP_Software")
    os.makedirs(root, exist_ok=True)
    return root


CREDENTIALS_PATH = os.path.join(_app_dir(), "cred.bin")


# -------------------------
# Key derivation (machine-bound)
# -------------------------
def _derive_key() -> bytes:
    """
    Derive a 32-byte key tied to this machine using its MAC address.
    (Same behavior as before so existing files continue to decrypt.)
    """
    mac = uuid.getnode()
    mac_bytes = str(mac).encode("utf-8")
    return hashlib.sha256(mac_bytes).digest()


KEY = _derive_key()


# -------------------------
# AEAD encrypt/decrypt (AES-EAX)
# Layout: [16-byte nonce][16-byte tag][ciphertext...]
# -------------------------
def encrypt(data: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return cipher.nonce + tag + ciphertext


def decrypt(enc_data: bytes, key: bytes) -> bytes:
    if len(enc_data) < 32:
        raise ValueError("Encrypted data too short")
    nonce = enc_data[:16]
    tag = enc_data[16:32]
    ciphertext = enc_data[32:]
    cipher = AES.new(key, AES.MODE_EAX, nonce=nonce)
    plaintext = cipher.decrypt(ciphertext)
    cipher.verify(tag)  # raises ValueError if tampered/wrong key
    return plaintext


# -------------------------
# File I/O helpers (robust)
# -------------------------
def load_decrypted_credentials() -> Dict:
    """
    Load, decrypt, and parse the credentials file.
    Returns {} on first run, missing file, or unreadable/corrupted file.
    """
    if not os.path.exists(CREDENTIALS_PATH):
        return {}
    try:
        with open(CREDENTIALS_PATH, "rb") as f:
            enc = f.read()
        raw = decrypt(enc, KEY)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        # Corrupted or wrong key -> treat as empty
        return {}


def save_encrypted_credentials(data: Dict) -> None:
    """
    Encrypt and write atomically to avoid partial/corrupt files.
    """
    if not isinstance(data, dict):
        raise TypeError("save_encrypted_credentials expects a dict")

    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    enc = encrypt(raw, KEY)

    dirpath = os.path.dirname(CREDENTIALS_PATH)
    os.makedirs(dirpath, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix="cred.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(enc)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, CREDENTIALS_PATH)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# -------------------------
# Existence check (restored for config.py)
# -------------------------
_REQUIRED_SA_KEYS = {
    "type", "project_id", "private_key_id", "private_key",
    "client_email", "client_id", "auth_uri", "token_uri",
    "auth_provider_x509_cert_url", "client_x509_cert_url"
}
_API_MARKER = "__api_key"


def credentials_exist() -> bool:
    """
    Returns True only if:
      - the encrypted file exists AND
      - it decrypts successfully AND
      - it contains a full Firebase service-account JSON (required keys) AND
      - it also contains the API key marker (__api_key)
    This matches what CredentialSetupDialog writes.
    """
    if not os.path.exists(CREDENTIALS_PATH):
        return False
    data = load_decrypted_credentials()
    if not data:
        return False
    if not _REQUIRED_SA_KEYS.issubset(set(data.keys())):
        return False
    if _API_MARKER not in data or not str(data.get(_API_MARKER) or "").strip():
        return False
    return True


# -------------------------
# Convenience getters/setters (backward compatible)
# Keys used previously: "__refresh_token", "__api_key"
# -------------------------
_REFRESH_KEY = "__refresh_token"
_API_KEY = "__api_key"


def get_refresh_token() -> str:
    data = load_decrypted_credentials()
    return str(data.get(_REFRESH_KEY, "") or "")


def set_refresh_token(token: str) -> None:
    data = load_decrypted_credentials()
    if token:
        data[_REFRESH_KEY] = str(token)
    else:
        data.pop(_REFRESH_KEY, None)
    save_encrypted_credentials(data)


def get_api_key() -> str:
    data = load_decrypted_credentials()
    return str(data.get(_API_KEY, "") or "")


def set_api_key(api_key: str) -> None:
    data = load_decrypted_credentials()
    if api_key:
        data[_API_KEY] = str(api_key)
    else:
        data.pop(_API_KEY, None)
    save_encrypted_credentials(data)


# Generic helpers (optional)
def get_value(key: str, default=None):
    data = load_decrypted_credentials()
    return data.get(key, default)


def set_value(key: str, value) -> None:
    data = load_decrypted_credentials()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save_encrypted_credentials(data)
# firebase/cred_loader.py
import os
import json
import uuid
import hashlib
import tempfile
from typing import Dict

try:
    from Crypto.Cipher import AES  # PyCryptodome
except Exception as e:
    raise RuntimeError("PyCryptodome is required (pip install pycryptodome)") from e


# -------------------------
# Storage location (Windows-friendly, works elsewhere too)
# -------------------------
def _app_dir() -> str:
    base = os.environ.get("APPDATA")
    if base and os.path.isdir(base):
        root = os.path.join(base, "PlayWithAayan-ERP_Software")
    else:
        root = os.path.join(os.path.expanduser("~"), ".config", "PlayWithAayan-ERP_Software")
    os.makedirs(root, exist_ok=True)
    return root


CREDENTIALS_PATH = os.path.join(_app_dir(), "cred.bin")


# -------------------------
# Key derivation (machine-bound)
# -------------------------
def _derive_key() -> bytes:
    """
    Derive a 32-byte key tied to this machine using its MAC address.
    (Same behavior as before so existing files continue to decrypt.)
    """
    mac = uuid.getnode()
    mac_bytes = str(mac).encode("utf-8")
    return hashlib.sha256(mac_bytes).digest()


KEY = _derive_key()


# -------------------------
# AEAD encrypt/decrypt (AES-EAX)
# Layout: [16-byte nonce][16-byte tag][ciphertext...]
# -------------------------
def encrypt(data: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return cipher.nonce + tag + ciphertext


def decrypt(enc_data: bytes, key: bytes) -> bytes:
    if len(enc_data) < 32:
        raise ValueError("Encrypted data too short")
    nonce = enc_data[:16]
    tag = enc_data[16:32]
    ciphertext = enc_data[32:]
    cipher = AES.new(key, AES.MODE_EAX, nonce=nonce)
    plaintext = cipher.decrypt(ciphertext)
    cipher.verify(tag)  # raises ValueError if tampered/wrong key
    return plaintext


# -------------------------
# File I/O helpers (robust)
# -------------------------
def load_decrypted_credentials() -> Dict:
    """
    Load, decrypt, and parse the credentials file.
    Returns {} on first run, missing file, or unreadable/corrupted file.
    """
    if not os.path.exists(CREDENTIALS_PATH):
        return {}
    try:
        with open(CREDENTIALS_PATH, "rb") as f:
            enc = f.read()
        raw = decrypt(enc, KEY)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        # Corrupted or wrong key -> treat as empty
        return {}


def save_encrypted_credentials(data: Dict) -> None:
    """
    Encrypt and write atomically to avoid partial/corrupt files.
    """
    if not isinstance(data, dict):
        raise TypeError("save_encrypted_credentials expects a dict")

    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    enc = encrypt(raw, KEY)

    dirpath = os.path.dirname(CREDENTIALS_PATH)
    os.makedirs(dirpath, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix="cred.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(enc)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, CREDENTIALS_PATH)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# -------------------------
# Existence check (restored for config.py)
# -------------------------
_REQUIRED_SA_KEYS = {
    "type", "project_id", "private_key_id", "private_key",
    "client_email", "client_id", "auth_uri", "token_uri",
    "auth_provider_x509_cert_url", "client_x509_cert_url"
}
_API_MARKER = "__api_key"


def credentials_exist() -> bool:
    """
    Returns True only if:
      - the encrypted file exists AND
      - it decrypts successfully AND
      - it is a Firebase *service account* JSON (type == "service_account") AND
      - all required SA keys are present AND
      - the API key marker (__api_key) is present and non-empty
    """
    if not os.path.exists(CREDENTIALS_PATH):
        return False

    data = load_decrypted_credentials()
    if not data:
        return False

    # Ensure this is a proper service-account blob, not just tokens
    if data.get("type") != "service_account":
        return False

    if not _REQUIRED_SA_KEYS.issubset(set(data.keys())):
        return False

    api_key = str(data.get(_API_MARKER, "")).strip()
    if not api_key:
        return False

    return True



# -------------------------
# Convenience getters/setters (backward compatible)
# Keys used previously: "__refresh_token", "__api_key"
# -------------------------
_REFRESH_KEY = "__refresh_token"
_API_KEY = "__api_key"


def get_refresh_token() -> str:
    data = load_decrypted_credentials()
    return str(data.get(_REFRESH_KEY, "") or "")


def set_refresh_token(token: str) -> None:
    data = load_decrypted_credentials()
    if token:
        data[_REFRESH_KEY] = str(token)
    else:
        data.pop(_REFRESH_KEY, None)
    save_encrypted_credentials(data)


def get_api_key() -> str:
    data = load_decrypted_credentials()
    return str(data.get(_API_KEY, "") or "")


def set_api_key(api_key: str) -> None:
    data = load_decrypted_credentials()
    if api_key:
        data[_API_KEY] = str(api_key)
    else:
        data.pop(_API_KEY, None)
    save_encrypted_credentials(data)


# Generic helpers (optional)
def get_value(key: str, default=None):
    data = load_decrypted_credentials()
    return data.get(key, default)


def set_value(key: str, value) -> None:
    data = load_decrypted_credentials()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save_encrypted_credentials(data)
