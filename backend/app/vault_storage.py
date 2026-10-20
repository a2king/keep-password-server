from __future__ import annotations

import hashlib
from pathlib import Path

from flask import current_app

from app.models import User


def vault_path(user: User) -> Path:
    root = Path(current_app.config["VAULT_STORAGE_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    return root / f"user_{user.id}.kpvault"


def write_vault(user: User, data: bytes) -> str:
    path = vault_path(user)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return hashlib.sha256(data).hexdigest()


def read_vault(user: User) -> bytes | None:
    path = vault_path(user)
    if not path.exists():
        return None
    return path.read_bytes()


def delete_vault(user: User) -> None:
    path = vault_path(user)
    if path.exists():
        path.unlink()
