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
            "keyVersion": user.key_version,
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
            "keyVersion": user.key_version,
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

    key_supplied = "keyVersion" in data
    key_version = None
    if key_supplied:
        try:
            key_version = int(data.get("keyVersion"))
        except (TypeError, ValueError):
            return jsonify({"error": "密钥版本无效"}), 400

    # 行锁 + 条件更新；文件先写临时再在版本更新成功后原子替换，避免并发覆盖
    user = db.session.execute(
        select(User).where(User.id == g.user.id).with_for_update()
    ).scalar_one()

    if user.key_version >= 1 and not key_supplied:
        current_key = user.key_version
        current_vault = user.vault_version
        db.session.rollback()
        return jsonify(
            {
                "error": "客户端版本过旧，不能覆盖新的密钥版本。请升级后再同步。",
                "upgradeRequired": True,
                "keyVersion": current_key,
                "vaultVersion": current_vault,
            }
        ), 426

    if key_supplied and key_version != user.key_version:
        current_key = user.key_version
        current_vault = user.vault_version
        db.session.rollback()
        return jsonify(
            {
                "error": "密钥版本已变化，已拒绝写入。",
                "keyChanged": True,
                "conflict": True,
                "keyVersion": current_key,
                "vaultVersion": current_vault,
                "serverTime": utcnow().isoformat(),
            }
        ), 409

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
    key_guard = key_version if key_supplied else 0
    result = db.session.execute(
        update(User)
        .where(User.id == user.id, User.vault_version == base_version, User.key_version == key_guard)
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
        return jsonify({"dataBase64": None, "keyVersion": user.key_version})
    return jsonify(
        {
            "dataBase64": base64.b64encode(user.wrapped_kpkey).decode("ascii"),
            "keyVersion": user.key_version,
            "updatedAt": user.wrapped_kpkey_updated_at.isoformat() if user.wrapped_kpkey_updated_at else None,
        }
    )


@api_bp.put("/sync/wrapped-key")
@require_device_auth
def put_wrapped_key():
    """旧客户端首次声明密钥包。已有包或密钥代已建立时拒绝覆盖。换钥必须走 /sync/commit。"""
    data = request.get_json(silent=True) or {}
    raw, error = _decode_blob(data.get("dataBase64"), "密钥包无效", 16 * 1024)
    if error is not None:
        return error
    digest = hashlib.sha256(raw).hexdigest()
    user = db.session.execute(
        select(User).where(User.id == g.user.id).with_for_update()
    ).scalar_one()
    result = db.session.execute(
        update(User)
        .where(User.id == user.id, User.key_version == 0, User.wrapped_kpkey.is_(None))
        .values(wrapped_kpkey=raw, wrapped_key_sha256=digest, wrapped_kpkey_updated_at=utcnow())
    )
    if result.rowcount != 1:
        db.session.rollback()
        fresh = db.session.get(User, user.id)
        return _version_conflict(fresh, expected_key=0)
    _audit(user, "wrapped_key_claim")
    db.session.commit()
    return jsonify({"ok": True, "keyVersion": 0})


@api_bp.put("/sync/commit")
@require_device_auth
def commit_generation():
    """原子提交密钥包与保险库密文。purpose=establish 首次建立，rotate 显式换钥，vault 只更新密文。"""
    data = request.get_json(silent=True) or {}
    purpose = data.get("purpose") or ""
    if purpose not in {"establish", "rotate", "vault"}:
        return jsonify({"error": "不支持的提交类型"}), 400
    try:
        expected_key = int(data.get("expectedKeyVersion"))
        expected_vault = int(data.get("expectedVaultVersion"))
    except (TypeError, ValueError):
        return jsonify({"error": "缺少版本号"}), 400

    max_bytes = current_app.config["MAX_VAULT_BYTES"]
    raw, error = _decode_blob(data.get("dataBase64"), "保险库数据无效", max_bytes)
    if error is not None:
        return error
    wrap = None
    if purpose in {"establish", "rotate"}:
        wrap, error = _decode_blob(data.get("wrappedKeyBase64"), "密钥包无效", 16 * 1024)
        if error is not None:
            return error
    elif data.get("wrappedKeyBase64"):
        return jsonify({"error": "普通同步不能顺便更换密钥包"}), 400

    vault_sha = hashlib.sha256(raw).hexdigest()
    wrap_sha = hashlib.sha256(wrap).hexdigest() if wrap is not None else None
    user = db.session.execute(
        select(User).where(User.id == g.user.id).with_for_update()
    ).scalar_one()

    if _is_idempotent_replay(user, purpose, expected_key, vault_sha, wrap_sha):
        return _commit_ok(user, idempotent=True)

    if purpose == "establish" and expected_key != 0:
        db.session.rollback()
        return _version_conflict(user, expected_key)

    if purpose == "rotate" and user.vault_version > 0 and user.wrapped_key_sha256 and wrap_sha == user.wrapped_key_sha256:
        db.session.rollback()
        return jsonify({"error": "换钥必须使用新的密钥包。原云端数据不会被清空。"}), 400

    where = [User.id == user.id, User.vault_version == expected_vault]
    values = {
        "vault_version": expected_vault + 1,
        "vault_size_bytes": len(raw),
        "vault_sha256": vault_sha,
    }
    if purpose == "establish":
        where.extend([User.key_version == 0, User.wrapped_kpkey.is_(None)])
        values.update(
            key_version=1,
            wrapped_kpkey=wrap,
            wrapped_key_sha256=wrap_sha,
            wrapped_kpkey_updated_at=utcnow(),
        )
    elif purpose == "rotate":
        where.append(User.key_version == expected_key)
        values.update(
            key_version=expected_key + 1,
            wrapped_kpkey=wrap,
            wrapped_key_sha256=wrap_sha,
            wrapped_kpkey_updated_at=utcnow(),
        )
    else:
        where.append(User.key_version == expected_key)

    result = db.session.execute(update(User).where(*where).values(**values))
    if result.rowcount != 1:
        db.session.rollback()
        fresh = db.session.get(User, user.id)
        return _version_conflict(fresh, expected_key)

    path = vault_path(user)
    previous = path.read_bytes() if path.exists() else None
    tmp = path.with_suffix(path.suffix + ".commit.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(raw)
        tmp.replace(path)
        db.session.expire(user)
        db.session.refresh(user)
        _bump_sync_stat(user)
        _audit(user, f"sync_commit_{purpose}", f"key{user.key_version}/vault{user.vault_version}")
        db.session.commit()
    except Exception:
        db.session.rollback()
        _restore_vault_file(path, previous)
        if tmp.exists():
            tmp.unlink()
        raise
    g.user = user
    return _commit_ok(user, idempotent=False)


@api_bp.post("/sync/device/unbind-self")
@require_device_auth
def unbind_self():
    g.device.revoked_at = utcnow()
    _audit(g.user, "device_unbind_self", str(g.device.id))
    db.session.commit()
    return jsonify({"ok": True})


def _decode_blob(value, label: str, max_bytes: int):
    try:
        raw = base64.b64decode(value or "", validate=True)
    except Exception:
        return None, (jsonify({"error": label}), 400)
    if len(raw) == 0 or len(raw) > max_bytes:
        return None, (jsonify({"error": f"{label}大小不合法"}), 400)
    return raw, None


def _is_idempotent_replay(user: User, purpose: str, expected_key: int, vault_sha: str, wrap_sha: str | None) -> bool:
    if user.vault_sha256 != vault_sha or user.vault_version <= 0:
        return False
    if purpose == "vault":
        return user.key_version == expected_key
    if not wrap_sha or user.wrapped_key_sha256 != wrap_sha:
        return False
    return user.key_version > 0


def _version_conflict(user: User | None, expected_key: int):
    key_version = user.key_version if user else 0
    vault_version = user.vault_version if user else 0
    changed = user is not None and key_version != expected_key
    return jsonify(
        {
            "error": "密钥版本已变化，已拒绝写入。" if changed else "版本冲突",
            "conflict": True,
            "keyChanged": changed,
            "hasWrappedKey": bool(user and user.wrapped_kpkey is not None),
            "keyVersion": key_version,
            "vaultVersion": vault_version,
            "serverTime": utcnow().isoformat(),
        }
    ), 409


def _commit_ok(user: User, *, idempotent: bool):
    return jsonify(
        {
            "ok": True,
            "idempotent": idempotent,
            "keyVersion": user.key_version,
            "vaultVersion": user.vault_version,
            "vaultSha256": user.vault_sha256,
            "hasWrappedKey": user.wrapped_kpkey is not None,
            "serverTime": utcnow().isoformat(),
        }
    )


def _restore_vault_file(path, previous: bytes | None) -> None:
    try:
        if previous is None:
            if path.exists():
                path.unlink()
        else:
            path.write_bytes(previous)
    except OSError:
        pass
