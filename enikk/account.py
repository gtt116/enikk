"""Account storage — encrypted with Fernet (key derived from username + 'enikk')."""
import base64
import getpass
import hashlib
import json
import os
import logging
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger("enikk")

ACCOUNT_DIR = Path(__file__).resolve().parent.parent / "accounts"


def _derive_key() -> bytes:
    """Derive AES key from Windows username + 'enikk'."""
    username = getpass.getuser()
    raw = f"{username}enikk".encode('utf-8')
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _encrypt(text: str) -> str:
    """Encrypt text using Fernet (AES)."""
    f = Fernet(_derive_key())
    return f.encrypt(text.encode()).decode()


def _decrypt(token: str) -> str:
    """Decrypt text using Fernet (AES)."""
    f = Fernet(_derive_key())
    return f.decrypt(token.encode()).decode()


def save_account(config_name: str, account: str, password: str) -> Path:
    """Save encrypted account to disk."""
    ACCOUNT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "account": _encrypt(account),
        "password": _encrypt(password),
    }
    path = ACCOUNT_DIR / f"{config_name}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    logger.info(f"Account saved to {path}")
    return path


def load_account(config_name: str) -> tuple[str | None, str | None]:
    """Load and decrypt account from disk."""
    path = ACCOUNT_DIR / f"{config_name}.json"
    if not path.exists():
        logger.warning(f"Account file not found: {path}")
        return None, None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        account = _decrypt(data["account"])
        password = _decrypt(data["password"])
        return account, password
    except Exception as e:
        logger.error(f"Failed to load account: {e}")
        return None, None
