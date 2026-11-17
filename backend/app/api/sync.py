from __future__ import annotations

import base64
import hashlib
import re
from datetime import date

from email_validator import EmailNotValidError, validate_email
from flask import current_app, g, jsonify, request
from sqlalchemy import select, update

from app.api import api_bp
from app.device_bind_rate import RATE_LIMIT_ERROR, consume_device_bind_code_quota
from app.extensions import db
from app.httputil import client_ip
from app.models import AuditLog, Device, SyncEvent, User, utcnow
from app.security import hash_token, issue_device_token, require_device_auth, verify_password
from app.tokens import consume_email_code, send_device_bind_email
from app.vault_storage import read_vault, vault_path


_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")
_KEY_ID_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
# 不要写产品英文名：客户端会屏蔽含 "password" 等字样的错误文本，用户只会看到“请求无效”。
CLIENT_TOO_OLD_ERROR = "请把客户端升级到 {version} 或更高版本后再开启云同步。"


def _normalize_email(raw: str) -> str:
    return validate_email(raw, check_deliverability=False).normalized.lower()


def _parse_version(raw) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(str(raw or ""))
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _client_too_old(raw) -> bool:
    """1.0.1 起服务器不再保存密钥包、不再校验 .kpbind。旧客户端的绑定流程依赖二者，直接拒绝。"""
    minimum = _parse_version(current_app.config.get("MIN_SYNC_CLIENT_VERSION", "1.0.1"))
    version = _parse_version(raw)
    return minimum is not None and (version is None or version < minimum)


def _key_id(data: dict):
    """客户端上报的数据密钥标识：密钥 SHA-256 的前 12 位十六进制，与 .kpkey 文件名中的编号相同。

    只用于提示用户该选哪一份密钥文件，以及拦截用错密钥的上传。不能用来解密。
    返回 (标识或 None, 错误响应或 None)。
    """
    raw = data.get("keyId")
    if raw is None or raw == "":
        return None, None
    if not isinstance(raw, str) or not _KEY_ID_RE.match(raw):
        return None, (jsonify({"error": "密钥标识无效"}), 400)
    return raw.upper(), None


def _key_mismatch(user: User, key_id: str | None) -> bool:
    return bool(key_id and user.vault_key_id and user.vault_key_id != key_id)


def _key_mismatch_response(user: User):
    return jsonify(
        {
            "error": "这台设备使用的加密密钥与云端不同，已拒绝写入。",
            "keyChanged": True,
            "conflict": True,
            "keyVersion": user.key_version,
            "vaultVersion": user.vault_version,
            "vaultKeyId": user.vault_key_id,
            "serverTime": utcnow().isoformat(),
        }
    ), 409


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
    if not consume_device_bind_code_quota(email):
        return jsonify({"error": RATE_LIMIT_ERROR}), 429
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

    # 先于账号检查，不泄露邮箱是否注册。用 400 而不是 426：0.9.1 会把 426 显示成“请升级到 0.9.1”。
    if _client_too_old(data.get("clientVersion")):
        minimum = current_app.config.get("MIN_SYNC_CLIENT_VERSION", "1.0.1")
        return jsonify({"error": CLIENT_TOO_OLD_ERROR.format(version=minimum), "upgradeRequired": True}), 400

    user = User.query.filter_by(email=email).first()
    password = data.get("password") or ""
    if user is None or user.is_disabled or not user.is_verified:
        return jsonify({"error": "账号不可用"}), 401
    if not verify_password(user.password_hash, password):
        return jsonify({"error": "邮箱或密码不正确"}), 401
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
            "vaultKeyId": user.vault_key_id,
            "hasVault": user.vault_version > 0,
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
            "vaultKeyId": user.vault_key_id,
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
    key_id, error = _key_id(data)
    if error is not None:
        return error

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

    if _key_mismatch(user, key_id):
        response = _key_mismatch_response(user)
        db.session.rollback()
        return response

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
        .values(
            vault_version=next_version,
            vault_size_bytes=len(raw),
            vault_sha256=digest,
            # 老库还没有标识时，用第一次上报的补上。已有标识不会被覆盖（不一致的已在上面拒绝）。
            vault_key_id=user.vault_key_id or key_id,
        )
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
    """1.0.1 起服务器不再下发密钥包。保留接口只为让 0.9.1 设备得到明确的空结果。"""
    return jsonify({"dataBase64": None, "keyVersion": g.user.key_version})


@api_bp.put("/sync/wrapped-key")
@require_device_auth
def put_wrapped_key():
    """1.0.1 起服务器不再保存任何能解开保险库的数据。"""
    return jsonify({"error": "服务器不再保存密钥包。请把客户端升级到最新版本。"}), 410


@api_bp.put("/sync/commit")
@require_device_auth
def commit_generation():
    """原子提交保险库密文与密钥代。purpose=establish 首次建立，rotate 显式换钥，vault 只更新密文。

    1.0.1 起不再保存密钥包：wrappedKeyBase64 即使由旧客户端带上也直接忽略。
    客户端可上报 keyId（数据密钥标识），服务器只记录它，用来提示和拦截用错密钥的写入。
    """
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
    key_id, error = _key_id(data)
    if error is not None:
        return error

    vault_sha = hashlib.sha256(raw).hexdigest()
    user = db.session.execute(
        select(User).where(User.id == g.user.id).with_for_update()
    ).scalar_one()

    if _is_idempotent_replay(user, purpose, expected_key, vault_sha, key_id):
        return _commit_ok(user, idempotent=True)

    if purpose == "establish" and expected_key != 0:
        db.session.rollback()
        return _version_conflict(user, expected_key)

    if purpose == "rotate" and key_id and user.vault_key_id == key_id:
        db.session.rollback()
        return jsonify({"error": "换钥必须使用新的加密密钥。原云端数据不会被清空。"}), 400

    if purpose == "vault" and _key_mismatch(user, key_id):
        response = _key_mismatch_response(user)
        db.session.rollback()
        return response

    where = [User.id == user.id, User.vault_version == expected_vault]
    values = {
        "vault_version": expected_vault + 1,
        "vault_size_bytes": len(raw),
        "vault_sha256": vault_sha,
    }
    # 建立或换钥时顺手清掉旧版留下的密钥包：它包的是旧密钥，留着只有风险。
    drop_legacy_wrap = {"wrapped_kpkey": None, "wrapped_key_sha256": None, "wrapped_kpkey_updated_at": None}
    if purpose == "establish":
        where.append(User.key_version == 0)
        values.update(key_version=1, vault_key_id=key_id, **drop_legacy_wrap)
    elif purpose == "rotate":
        where.append(User.key_version == expected_key)
        # 旧客户端换钥不带 keyId：新密钥标识未知，记为空，由下一次 1.0.1 上传补上。
        values.update(key_version=expected_key + 1, vault_key_id=key_id, **drop_legacy_wrap)
    else:
        where.append(User.key_version == expected_key)
        values.update(vault_key_id=user.vault_key_id or key_id)

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


def _is_idempotent_replay(user: User, purpose: str, expected_key: int, vault_sha: str, key_id: str | None) -> bool:
    """上一次提交已成功但响应丢了，客户端重试同一份密文。密文带随机 nonce，sha256 相同即同一次提交。"""
    if user.vault_sha256 != vault_sha or user.vault_version <= 0:
        return False
    if purpose == "vault":
        return user.key_version == expected_key
    if key_id and user.vault_key_id and user.vault_key_id != key_id:
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
            "keyVersion": key_version,
            "vaultKeyId": user.vault_key_id if user else None,
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
            "vaultKeyId": user.vault_key_id,
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
