from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from flask import current_app, jsonify, request
from sqlalchemy import func

from app.api import api_bp
from app.extensions import db
from app.models import Device, SyncEvent, User, utcnow
from app.security import require_admin


@api_bp.get("/admin/overview")
@require_admin
def overview():
    now = utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    total_users = User.query.count()
    verified = User.query.filter_by(is_verified=True).count()
    devices = Device.query.filter(Device.revoked_at.is_(None)).count()
    dau = (
        User.query.filter(User.last_sync_at.isnot(None), User.last_sync_at >= day_ago).count()
        + User.query.filter(User.last_login_at.isnot(None), User.last_login_at >= day_ago).count()
    )
    # rough unique active: prefer sync, fall back login — keep simple counts separate
    daily_active = db.session.query(User.id).filter(
        ((User.last_sync_at.isnot(None)) & (User.last_sync_at >= day_ago))
        | ((User.last_login_at.isnot(None)) & (User.last_login_at >= day_ago))
    ).distinct().count()
    weekly_active = db.session.query(User.id).filter(
        ((User.last_sync_at.isnot(None)) & (User.last_sync_at >= week_ago))
        | ((User.last_login_at.isnot(None)) & (User.last_login_at >= week_ago))
    ).distinct().count()

    storage = db.session.query(func.coalesce(func.sum(User.vault_size_bytes), 0)).scalar() or 0

    reg_rows = (
        db.session.query(func.strftime("%Y-%m-%d", User.created_at), func.count(User.id))
        .filter(User.created_at >= now - timedelta(days=30))
        .group_by(func.strftime("%Y-%m-%d", User.created_at))
        .all()
    )
    sync_rows = (
        db.session.query(SyncEvent.day, func.sum(SyncEvent.count))
        .filter(SyncEvent.day >= (now - timedelta(days=30)).date().isoformat())
        .group_by(SyncEvent.day)
        .all()
    )

    return jsonify(
        {
            "totalUsers": total_users,
            "verifiedUsers": verified,
            "activeDevices": devices,
            "dailyActiveUsers": daily_active,
            "weeklyActiveUsers": weekly_active,
            "totalStorageBytes": int(storage),
            "registrationsLast30Days": [{"day": d, "count": c} for d, c in reg_rows if d],
            "syncsLast30Days": [{"day": d, "count": int(c)} for d, c in sync_rows],
        }
    )


@api_bp.post("/admin/releases/upload")
@require_admin
def upload_release():
    """管理员上传客户端安装包（官网备用下载通道）。"""
    if "file" not in request.files:
        return jsonify({"error": "缺少文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    root = Path(current_app.config["VAULT_STORAGE_DIR"]).parent / "releases"
    root.mkdir(parents=True, exist_ok=True)
    # 只保留文件名，防止路径穿越
    name = Path(f.filename).name
    target = root / name
    f.save(target)
    latest = root / "latest.txt"
    latest.write_text(name, encoding="utf-8")
    return jsonify({"ok": True, "filename": name})


@api_bp.get("/admin/releases/latest")
def latest_release_public():
    root = Path(current_app.config["VAULT_STORAGE_DIR"]).parent / "releases"
    latest = root / "latest.txt"
    if not latest.exists():
        return jsonify({"filename": None})
    name = latest.read_text(encoding="utf-8").strip()
    return jsonify({"filename": name, "url": f"/downloads/{name}"})
