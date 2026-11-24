"""设备配对：新设备经已绑定设备批准后，取得用临时密钥加密的数据密钥。

协议（服务器只做中转，看不到任何能解开保险库的内容）：

1. 新设备 N：生成临时 X25519 密钥对，POST /sync/pairing 只提交公钥承诺
   commitment = sha256("keep-password/pair-commit/v1" || N 公钥)。
2. 老设备 O：轮询 GET /sync/pairing/pending 看到请求，POST offer 提交自己的临时公钥。
3. N 看到 O 的公钥后 POST reveal 公开自己的公钥；服务器与 O 都核对承诺。
4. 两边用双方公钥算出同一个 6 位确认码。用户核对一致后在 O 上批准，O 用 ECDH
   派生的密钥加密数据密钥，POST approve 提交信封。
5. N 取回信封、本地解密，POST complete，服务器清空公钥与信封。

N 先承诺、后公开，服务器冒充任一方都必须在不知道对方公钥的情况下先选定自己的密钥，
无法事后挑选密钥让两边确认码相同。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from datetime import timedelta

from flask import current_app, g, jsonify, request
from sqlalchemy import select

from app.api import api_bp
from app.extensions import db
from app.httputil import client_ip
from app.models import AuditLog, Device, DevicePairing, utcnow
from app.security import require_device_auth

COMMIT_PREFIX = b"keep-password/pair-commit/v1"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTIVE = ("requested", "offered", "revealed", "approved")
MAX_ENVELOPE = 4096


def _aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=utcnow().tzinfo)


def _expired(row: DevicePairing) -> bool:
    return _aware(row.expires_at) <= utcnow()


def _public_key(raw) -> str | None:
    """校验 32 字节 X25519 公钥（标准 base64），返回规范化文本。"""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(decoded) != 32:
        return None
    return base64.b64encode(decoded).decode("ascii")


def commitment_of(public_key_b64: str) -> str:
    return hashlib.sha256(COMMIT_PREFIX + base64.b64decode(public_key_b64)).hexdigest()


def _audit(action: str, detail: str = "") -> None:
    db.session.add(AuditLog(user_id=g.user.id, action=action, detail=detail, ip=client_ip()))


def _device_name(device_id: int | None) -> tuple[str, str]:
    device = db.session.get(Device, device_id) if device_id else None
    return (device.name, device.platform) if device else ("", "")


def _load(pairing_id: str, *, lock: bool = False) -> DevicePairing | None:
    if not _ID_RE.match(pairing_id or ""):
        return None
    query = select(DevicePairing).where(DevicePairing.id == pairing_id, DevicePairing.user_id == g.user.id)
    if lock:
        query = query.with_for_update()
    return db.session.execute(query).scalar_one_or_none()


def _gone():
    # 不区分“不存在”和“属于别人”，避免探测。
    return jsonify({"error": "配对请求不存在或已过期"}), 404


def _state_conflict(row: DevicePairing):
    db.session.rollback()
    return jsonify({"error": "配对状态已变化，请重新发起", "status": row.status}), 409


def _view(row: DevicePairing, *, for_requester: bool) -> dict:
    status = "expired" if row.status in ACTIVE and _expired(row) else row.status
    requester_name, requester_platform = _device_name(row.requester_device_id)
    approver_name, approver_platform = _device_name(row.approver_device_id)
    body = {
        "pairingId": row.id,
        "status": status,
        "commitment": row.commitment,
        "requesterDeviceName": requester_name,
        "requesterPlatform": requester_platform,
        "approverDeviceName": approver_name,
        "approverPlatform": approver_platform,
        "requesterPublicKey": row.requester_public_key,
        "approverPublicKey": row.approver_public_key,
        "createdAt": _aware(row.created_at).isoformat(),
        "expiresAt": _aware(row.expires_at).isoformat(),
    }
    if for_requester and status == "approved":
        body["envelope"] = row.envelope
    return body


@api_bp.post("/sync/pairing")
@require_device_auth
def pairing_create():
    data = request.get_json(silent=True) or {}
    commitment = (data.get("commitment") or "").strip().lower()
    if not _HEX64.match(commitment):
        return jsonify({"error": "配对请求无效"}), 400

    now = utcnow()
    limit = int(current_app.config.get("PAIRING_PER_10_MIN", 10))
    recent = DevicePairing.query.filter(
        DevicePairing.user_id == g.user.id, DevicePairing.created_at > now - timedelta(minutes=10)
    ).count()
    if recent >= limit:
        return jsonify({"error": "操作过于频繁，请稍后再试。"}), 429

    # 顺手清理一天前的记录；同一设备只保留最新一个进行中的请求。
    DevicePairing.query.filter(DevicePairing.created_at < now - timedelta(days=1)).delete(synchronize_session=False)
    for old in DevicePairing.query.filter(
        DevicePairing.requester_device_id == g.device.id, DevicePairing.status.in_(ACTIVE)
    ).all():
        old.status = "cancelled"
        old.envelope = None
        old.updated_at = now

    ttl = int(current_app.config.get("PAIRING_TTL_SECONDS", 600))
    row = DevicePairing(
        id=secrets.token_urlsafe(18),
        user_id=g.user.id,
        requester_device_id=g.device.id,
        status="requested",
        commitment=commitment,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.session.add(row)
    _audit("pairing_request", g.device.name)
    db.session.commit()
    return jsonify(_view(row, for_requester=True)), 201


@api_bp.get("/sync/pairing/pending")
@require_device_auth
def pairing_pending():
    """给已绑定的其他设备：本账号里等待它响应的配对请求。"""
    now = utcnow()
    rows = (
        DevicePairing.query.filter(
            DevicePairing.user_id == g.user.id,
            DevicePairing.requester_device_id != g.device.id,
            DevicePairing.expires_at > now,
        )
        .order_by(DevicePairing.created_at.desc())
        .all()
    )
    items = []
    for row in rows:
        if _expired(row):
            continue
        if row.status == "requested" or (
            row.status in ("offered", "revealed") and row.approver_device_id == g.device.id
        ):
            items.append(_view(row, for_requester=False))
    return jsonify({"requests": items})


@api_bp.get("/sync/pairing/<pairing_id>")
@require_device_auth
def pairing_get(pairing_id: str):
    row = _load(pairing_id)
    if row is None or g.device.id not in (row.requester_device_id, row.approver_device_id):
        return _gone()
    return jsonify(_view(row, for_requester=row.requester_device_id == g.device.id))


@api_bp.post("/sync/pairing/<pairing_id>/offer")
@require_device_auth
def pairing_offer(pairing_id: str):
    data = request.get_json(silent=True) or {}
    key = _public_key(data.get("publicKey"))
    if key is None:
        return jsonify({"error": "公钥无效"}), 400
    row = _load(pairing_id, lock=True)
    if row is None or row.requester_device_id == g.device.id or _expired(row):
        db.session.rollback()
        return _gone()
    if row.status != "requested":
        return _state_conflict(row)
    row.status = "offered"
    row.approver_device_id = g.device.id
    row.approver_public_key = key
    row.updated_at = utcnow()
    db.session.commit()
    return jsonify(_view(row, for_requester=False))


@api_bp.post("/sync/pairing/<pairing_id>/reveal")
@require_device_auth
def pairing_reveal(pairing_id: str):
    data = request.get_json(silent=True) or {}
    key = _public_key(data.get("publicKey"))
    if key is None:
        return jsonify({"error": "公钥无效"}), 400
    row = _load(pairing_id, lock=True)
    if row is None or row.requester_device_id != g.device.id or _expired(row):
        db.session.rollback()
        return _gone()
    if row.status == "revealed" and row.requester_public_key == key:
        db.session.rollback()
        return jsonify(_view(row, for_requester=True))
    if row.status != "offered":
        return _state_conflict(row)
    if commitment_of(key) != row.commitment:
        db.session.rollback()
        return jsonify({"error": "公钥与配对请求不一致"}), 400
    row.status = "revealed"
    row.requester_public_key = key
    row.updated_at = utcnow()
    db.session.commit()
    return jsonify(_view(row, for_requester=True))


@api_bp.post("/sync/pairing/<pairing_id>/approve")
@require_device_auth
def pairing_approve(pairing_id: str):
    data = request.get_json(silent=True) or {}
    envelope = data.get("envelope")
    if not isinstance(envelope, str) or not envelope or len(envelope) > MAX_ENVELOPE:
        return jsonify({"error": "密钥信封无效"}), 400
    row = _load(pairing_id, lock=True)
    if row is None or row.approver_device_id != g.device.id or _expired(row):
        db.session.rollback()
        return _gone()
    # 扫码批准时新设备公钥来自二维码，不必等 reveal；确认码批准时客户端会先等 reveal。
    if row.status not in ("offered", "revealed"):
        return _state_conflict(row)
    row.status = "approved"
    row.envelope = envelope
    row.updated_at = utcnow()
    name, _ = _device_name(row.requester_device_id)
    _audit("pairing_approve", name)
    db.session.commit()
    return jsonify(_view(row, for_requester=False))


@api_bp.post("/sync/pairing/<pairing_id>/reject")
@require_device_auth
def pairing_reject(pairing_id: str):
    row = _load(pairing_id, lock=True)
    # 请求方可以取消；已响应的设备可以拒绝；还没人响应时，本账号任何一台设备都可以拒绝。
    involved = g.device.id in (row.requester_device_id, row.approver_device_id) if row else False
    unclaimed = row is not None and row.status == "requested"
    if row is None or not (involved or unclaimed):
        db.session.rollback()
        return _gone()
    if row.status not in ACTIVE:
        db.session.rollback()
        return jsonify(_view(row, for_requester=row.requester_device_id == g.device.id))
    by_requester = row.requester_device_id == g.device.id
    row.status = "cancelled" if by_requester else "rejected"
    if not by_requester and row.approver_device_id is None:
        row.approver_device_id = g.device.id
    row.envelope = None
    row.updated_at = utcnow()
    _audit("pairing_cancel" if by_requester else "pairing_reject")
    db.session.commit()
    return jsonify(_view(row, for_requester=by_requester))


@api_bp.post("/sync/pairing/<pairing_id>/complete")
@require_device_auth
def pairing_complete(pairing_id: str):
    row = _load(pairing_id, lock=True)
    if row is None or row.requester_device_id != g.device.id:
        db.session.rollback()
        return _gone()
    if row.status == "completed":
        db.session.rollback()
        return jsonify({"ok": True})
    if row.status != "approved":
        return _state_conflict(row)
    row.status = "completed"
    row.envelope = None
    row.requester_public_key = None
    row.approver_public_key = None
    row.updated_at = utcnow()
    db.session.commit()
    return jsonify({"ok": True})
