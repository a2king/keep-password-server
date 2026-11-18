from __future__ import annotations

from flask import g, jsonify, request

from app.api import api_bp
from app.extensions import db
from app.httputil import client_ip
from app.models import AuditLog, Device, utcnow
from app.security import require_web_auth, verify_password
from app.tokens import consume_email_code, send_sensitive_email
from app.vault_storage import delete_vault


def _audit(action: str, detail: str = "") -> None:
    db.session.add(AuditLog(user_id=g.user.id, action=action, detail=detail, ip=client_ip()))


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
            "vaultVersion": user.vault_version,
            "vaultSizeBytes": user.vault_size_bytes,
            "vaultKeyId": user.vault_key_id,
            "keyVersion": user.key_version,
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
