from __future__ import annotations

import json

from flask import g, jsonify, request

from app.api import api_bp
from app.extensions import db
from app.models import AuditLog, Device, utcnow
from app.security import generate_binding_key, require_web_auth, verify_password
from app.tokens import consume_email_code, send_sensitive_email
from app.vault_storage import delete_vault


def _audit(action: str, detail: str = "") -> None:
    db.session.add(AuditLog(user_id=g.user.id, action=action, detail=detail, ip=(request.remote_addr or "")[:64]))


@api_bp.get("/me")
@require_web_auth
def me():
    user = g.user
    devices = (
        Device.query.filter_by(user_id=user.id, revoked_at=None).order_by(Device.last_seen_at.desc()).all()
    )
    return jsonify(
        {
            "email": user.email,
            "isAdmin": user.is_admin,
            "bindingKeyFingerprint": user.binding_key_fingerprint,
            "bindingKeyCreatedAt": user.binding_key_created_at.isoformat() if user.binding_key_created_at else None,
            "vaultVersion": user.vault_version,
            "vaultSizeBytes": user.vault_size_bytes,
            "hasWrappedKey": user.wrapped_kpkey is not None,
            "devices": [
                {
                    "id": d.id,
                    "name": d.name,
                    "platform": d.platform,
                    "clientVersion": d.client_version,
                    "createdAt": d.created_at.isoformat(),
                    "lastSeenAt": d.last_seen_at.isoformat(),
                }
                for d in devices
            ],
        }
    )


@api_bp.post("/me/request-code")
@require_web_auth
def request_code():
    data = request.get_json(silent=True) or {}
    purpose = data.get("purpose") or ""
    mapping = {
        "unbind_device": "设备解绑确认",
        "regen_binding_key": "重新生成绑定密钥确认",
        "delete_account": "注销账号确认",
    }
    if purpose not in mapping:
        return jsonify({"error": "不支持的操作"}), 400
    send_sensitive_email(g.user, purpose, f"Keep Password {mapping[purpose]}")
    return jsonify({"ok": True})


@api_bp.post("/me/devices/<int:device_id>/revoke")
@require_web_auth
def revoke_device(device_id: int):
    data = request.get_json(silent=True) or {}
    if not consume_email_code(g.user, "unbind_device", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400
    device = Device.query.filter_by(id=device_id, user_id=g.user.id).first()
    if device is None or device.revoked_at is not None:
        return jsonify({"error": "设备不存在"}), 404
    device.revoked_at = utcnow()
    _audit("revoke_device", str(device_id))
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.post("/me/binding-key/regenerate")
@require_web_auth
def regenerate_binding_key():
    data = request.get_json(silent=True) or {}
    if not consume_email_code(g.user, "regen_binding_key", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400
    raw_key, fingerprint, key_hash = generate_binding_key()
    g.user.binding_key_hash = key_hash
    g.user.binding_key_fingerprint = fingerprint
    g.user.binding_key_created_at = utcnow()
    _audit("regen_binding_key", fingerprint)
    db.session.commit()
    content = json.dumps(
        {
            "format": "keep-password-binding",
            "version": 1,
            "email": g.user.email,
            "key": raw_key,
            "fingerprint": fingerprint,
            "notice": "此文件用于绑定新设备。请妥善保管；在官网重新生成后旧文件立即失效。",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return jsonify(
        {
            "ok": True,
            "fingerprint": fingerprint,
            "filename": f"keep-password-binding-{fingerprint}.kpbind",
            "bindingKeyFile": content,
        }
    )


@api_bp.post("/me/delete")
@require_web_auth
def delete_account():
    data = request.get_json(silent=True) or {}
    if not verify_password(g.user.password_hash, data.get("password") or ""):
        return jsonify({"error": "密码不正确"}), 401
    if not consume_email_code(g.user, "delete_account", data.get("code", "")):
        return jsonify({"error": "验证码不正确或已过期"}), 400
    user = g.user
    delete_vault(user)
    _audit("delete_account")
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})
