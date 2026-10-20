from __future__ import annotations

import base64
import hashlib
from datetime import date

from email_validator import EmailNotValidError, validate_email
from flask import current_app, g, jsonify, request
from sqlalchemy import select, update

from app.api import api_bp
from app.extensions import db
from app.httputil import client_ip
from app.models import AuditLog, Device, SyncEvent, User, utcnow
from app.security import hash_token, issue_device_token, require_device_auth, verify_password
from app.tokens import consume_email_code, send_device_bind_email
from app.vault_storage import read_vault, vault_path


def _normalize_email(raw: str) -> str:
    return validate_email(raw, check_deliverability=False).normalized.lower()


def _audit(user: User, action: str, detail: str = "") -> None:
    db.session.add(AuditLog(user_id=user.id, action=action, detail=detail, ip=client_ip()))


def _bump_sync_stat(user: User) -> None:
    day = date.today().isoformat()
    row = SyncEvent.query.filter_by(user_id=user.id, day=day).first()
    if row is None:
        db.session.add(SyncEvent(user_id=user.id, day=day, count=1))
    else:
        row.count += 1
    user.last_sync_at = utcnow()


@api_bp.post("/sync/device/request-code")
def device_request_code():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400
    user = User.query.filter_by(email=email, is_verified=True).first()
    if user and not user.is_disabled:
        send_device_bind_email(user)
    return jsonify({"ok": True})


@api_bp.post("/sync/device/bind")
def device_bind():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    user = User.query.filter_by(email=email).first()
    password = data.get("password") or ""
    binding_key = (data.get("bindingKey") or "").strip()
    if user is None or user.is_disabled or not user.is_verified:
        return jsonify({"error": "账号不可用"}), 401
    if not verify_password(user.password_hash, password):
        return jsonify({"error": "邮箱或密码不正确"}), 401
    if not user.binding_key_hash or hash_token(binding_key) != user.binding_key_hash:
        return jsonify({"error": "绑定密钥不正确或已失效"}), 401
    if not consume_email_code(user, "device_bind", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400

    device = Device(
        user_id=user.id,
        name=(data.get("deviceName") or "未命名设备")[:120],
        platform=(data.get("platform") or "")[:40],
        client_version=(data.get("clientVersion") or "")[:40],
        token_hash="pending",
    )
    db.session.add(device)
    db.session.flush()
    token = issue_device_token(user, device)
    device.token_hash = hash_token(token)
    _audit(user, "device_bind", device.name)
    db.session.commit()
    return jsonify(
        {
            "deviceToken": token,
            "deviceId": device.id,
            "vaultVersion": user.vault_version,
            "bindingKeyFingerprint": user.binding_key_fingerprint,
            "hasVault": user.vault_version > 0,
            "hasWrappedKey": user.wrapped_kpkey is not None,
            "serverTime": utcnow().isoformat(),
        }
    )


@api_bp.get("/sync/status")
@require_device_auth
def sync_status():
    user = g.user
    return jsonify(
        {
            "vaultVersion": user.vault_version,
            "vaultSizeBytes": user.vault_size_bytes,
            "vaultSha256": user.vault_sha256,
            "bindingKeyFingerprint": user.binding_key_fingerprint,
            "bindingKeyCreatedAt": user.binding_key_created_at.isoformat() if user.binding_key_created_at else None,
            "hasWrappedKey": user.wrapped_kpkey is not None,
            "serverTime": utcnow().isoformat(),
        }
    )


@api_bp.get("/sync/vault")
@require_device_auth
def download_vault():
    user = g.user
    if user.vault_version <= 0:
        return jsonify({"vaultVersion": 0, "dataBase64": None, "serverTime": utcnow().isoformat()})
    data = read_vault(user)
    if data is None:
        return jsonify({"error": "云端保险库缺失"}), 500
    return jsonify(
        {
            "vaultVersion": user.vault_version,
            "vaultSha256": user.vault_sha256,
            "dataBase64": base64.b64encode(data).decode("ascii"),
            "serverTime": utcnow().isoformat(),
        }
    )


@api_bp.put("/sync/vault")
@require_device_auth
def upload_vault():
    data = request.get_json(silent=True) or {}
    try:
        base_version = int(data.get("baseVersion"))
    except (TypeError, ValueError):
        return jsonify({"error": "缺少 baseVersion"}), 400

    raw_b64 = data.get("dataBase64") or ""
    try:
        raw = base64.b64decode(raw_b64, validate=True)
    except Exception:
        return jsonify({"error": "保险库数据无效"}), 400

    max_bytes = current_app.config["MAX_VAULT_BYTES"]
    if len(raw) == 0 or len(raw) > max_bytes:
        return jsonify({"error": f"保险库大小必须在 1 到 {max_bytes} 字节之间"}), 400

    # 行锁 + 条件更新；文件先写临时再在版本更新成功后原子替换，避免并发覆盖
    user = db.session.execute(
        select(User).where(User.id == g.user.id).with_for_update()
    ).scalar_one()

    if base_version != user.vault_version:
        return jsonify(
            {
                "error": "版本冲突",
                "conflict": True,
                "vaultVersion": user.vault_version,
                "serverTime": utcnow().isoformat(),
            }
        ), 409

    digest = hashlib.sha256(raw).hexdigest()
    path = vault_path(user)
    tmp = path.with_suffix(path.suffix + f".{base_version}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(raw)

    next_version = base_version + 1
    result = db.session.execute(
        update(User)
        .where(User.id == user.id, User.vault_version == base_version)
        .values(vault_version=next_version, vault_size_bytes=len(raw), vault_sha256=digest)
    )
    if result.rowcount != 1:
        try:
            tmp.unlink(missing_ok=True)
        except TypeError:
            if tmp.exists():
                tmp.unlink()
        db.session.rollback()
        fresh = db.session.get(User, user.id)
        return jsonify(
            {
                "error": "版本冲突",
                "conflict": True,
                "vaultVersion": fresh.vault_version if fresh else base_version,
                "serverTime": utcnow().isoformat(),
            }
        ), 409

    tmp.replace(path)
    db.session.refresh(user)
    _bump_sync_stat(user)
    _audit(user, "vault_upload", f"v{user.vault_version}")
    db.session.commit()
    g.user = user
    return jsonify(
        {
            "ok": True,
            "vaultVersion": user.vault_version,
            "vaultSha256": user.vault_sha256,
            "serverTime": utcnow().isoformat(),
        }
    )


@api_bp.get("/sync/wrapped-key")
@require_device_auth
def get_wrapped_key():
    user = g.user
    if not user.wrapped_kpkey:
        return jsonify({"dataBase64": None})
    return jsonify(
        {
            "dataBase64": base64.b64encode(user.wrapped_kpkey).decode("ascii"),
            "updatedAt": user.wrapped_kpkey_updated_at.isoformat() if user.wrapped_kpkey_updated_at else None,
        }
    )


@api_bp.put("/sync/wrapped-key")
@require_device_auth
def put_wrapped_key():
    user = g.user
    data = request.get_json(silent=True) or {}
    try:
        raw = base64.b64decode(data.get("dataBase64") or "", validate=True)
    except Exception:
        return jsonify({"error": "密钥包无效"}), 400
    if len(raw) == 0 or len(raw) > 16 * 1024:
        return jsonify({"error": "密钥包大小不合法"}), 400
    user.wrapped_kpkey = raw
    user.wrapped_kpkey_updated_at = utcnow()
    _audit(user, "wrapped_key_upload")
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.post("/sync/device/unbind-self")
@require_device_auth
def unbind_self():
    g.device.revoked_at = utcnow()
    _audit(g.user, "device_unbind_self", str(g.device.id))
    db.session.commit()
    return jsonify({"ok": True})
