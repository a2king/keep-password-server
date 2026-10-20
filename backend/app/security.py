from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import current_app, g, jsonify, request

from app.extensions import db
from app.models import Device, User, utcnow


def password_hasher() -> PasswordHasher:
    cfg = current_app.config
    return PasswordHasher(
        time_cost=cfg["ARGON2_TIME_COST"],
        memory_cost=cfg["ARGON2_MEMORY_COST"],
        parallelism=cfg["ARGON2_PARALLELISM"],
    )


def hash_password(password: str) -> str:
    return password_hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher().verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_binding_key() -> tuple[str, str, str]:
    """返回 (明文密钥文件内容, 指纹, 哈希)。"""
    raw = secrets.token_bytes(32)
    encoded = "KPB-" + secrets.token_urlsafe(32)
    fingerprint = hashlib.sha256(raw).hexdigest()[:16]
    return encoded, fingerprint, hash_token(encoded)


def issue_web_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "typ": "web",
        "email": user.email,
        "adm": bool(user.is_admin),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=current_app.config["JWT_WEB_HOURS"])).timestamp()),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def issue_device_token(user: User, device: Device) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "typ": "device",
        "did": device.id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=current_app.config["JWT_DEVICE_DAYS"])).timestamp()),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _bearer() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def require_web_auth(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _bearer()
        if not token:
            return jsonify({"error": "未登录"}), 401
        payload = decode_token(token)
        if not payload or payload.get("typ") != "web":
            return jsonify({"error": "登录已失效"}), 401
        user = db.session.get(User, int(payload["sub"]))
        if user is None or user.is_disabled or not user.is_verified:
            return jsonify({"error": "账号不可用"}), 401
        g.user = user
        g.auth_type = "web"
        return fn(*args, **kwargs)

    return wrapper


def require_device_auth(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _bearer()
        if not token:
            return jsonify({"error": "未授权"}), 401
        payload = decode_token(token)
        if not payload or payload.get("typ") != "device":
            return jsonify({"error": "设备令牌无效"}), 401
        user = db.session.get(User, int(payload["sub"]))
        device = db.session.get(Device, int(payload["did"]))
        if (
            user is None
            or device is None
            or device.user_id != user.id
            or not device.is_active
            or user.is_disabled
            or not user.is_verified
        ):
            return jsonify({"error": "设备已失效"}), 401
        if not hmac.compare_digest(device.token_hash, hash_token(token)):
            return jsonify({"error": "设备令牌无效"}), 401
        device.last_seen_at = utcnow()
        g.user = user
        g.device = device
        g.auth_type = "device"
        db.session.commit()
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn: Callable):
    @wraps(fn)
    @require_web_auth
    def wrapper(*args, **kwargs):
        if not g.user.is_admin:
            return jsonify({"error": "需要管理员权限"}), 403
        return fn(*args, **kwargs)

    return wrapper


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
