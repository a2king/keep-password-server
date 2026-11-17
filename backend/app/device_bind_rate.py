from __future__ import annotations

import hashlib
from datetime import timedelta

from flask import current_app
from sqlalchemy import text

from app.extensions import db
from app.httputil import client_ip
from app.models import DeviceBindCodeRequest, utcnow

RATE_LIMIT_ERROR = "操作过于频繁，请稍后再试。"


def hash_normalized_email(normalized_email: str) -> str:
    return hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()


def _advisory_lock_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _lock_rate_keys(email_digest: str, ip: str) -> None:
    """在计数前串行化同一邮箱/IP 的额度占用。

    PostgreSQL 用事务级咨询锁。SQLite 不用 fcntl 进程锁：gunicorn 多 worker
    和独立连接靠数据库文件锁。DEFERRED 事务的纯 SELECT 不会互斥，必须先写。
    """
    bind = db.session.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        lock_ids = sorted(
            {
                _advisory_lock_id(f"kps:device-bind:e:{email_digest}"),
                _advisory_lock_id(f"kps:device-bind:i:{ip}"),
            }
        )
        for lock_id in lock_ids:
            db.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_id})
        return
    if dialect == "sqlite":
        db.session.execute(text("PRAGMA busy_timeout = 30000"))
        # WHERE 0 仍是写语句，把 DEFERRED 升级为 RESERVED。
        # 不能把互斥只绑在“碰巧有过期行可删”上。
        db.session.execute(text("UPDATE device_bind_code_requests SET ip = ip WHERE 0"))


def consume_device_bind_code_quota(normalized_email: str) -> bool:
    """在发信/作废旧码之前占用额度。True 表示未超限；False 应返回 429。

    计数规则：
    - IP 窗口统计本小时全部请求（含被 429 的），因为 IP 限制的是请求次数。
    - 邮箱窗口只统计通过限流的记录，避免刷 429 把邮箱滑动窗口锁死。
    - 窗口使用 created_at > now - window：恰好满 60 秒 / 1 小时的记录掉出窗口。
    占用行在本函数内提交：后续会话 rollback 或发信失败都不应丢掉拒绝计数。
    """
    now = utcnow()
    ip = (client_ip() or "")[:64]
    digest = hash_normalized_email(normalized_email)
    per_60s = int(current_app.config.get("DEVICE_BIND_CODE_PER_60S", 1))
    per_hour = int(current_app.config.get("DEVICE_BIND_CODE_PER_HOUR", 10))
    ip_per_hour = int(current_app.config.get("DEVICE_BIND_IP_PER_HOUR", 30))
    retention_hours = int(current_app.config.get("DEVICE_BIND_CODE_RETENTION_HOURS", 24))
    since_60s = now - timedelta(seconds=60)
    since_hour = now - timedelta(hours=1)
    cutoff = now - timedelta(hours=retention_hours)

    _lock_rate_keys(digest, ip)
    DeviceBindCodeRequest.query.filter(DeviceBindCodeRequest.created_at < cutoff).delete(
        synchronize_session=False
    )

    ip_count = (
        DeviceBindCodeRequest.query.filter(
            DeviceBindCodeRequest.ip == ip,
            DeviceBindCodeRequest.created_at > since_hour,
        ).count()
    )
    email_60s = (
        DeviceBindCodeRequest.query.filter(
            DeviceBindCodeRequest.email_hash == digest,
            DeviceBindCodeRequest.created_at > since_60s,
        ).count()
    )
    email_hour = (
        DeviceBindCodeRequest.query.filter(
            DeviceBindCodeRequest.email_hash == digest,
            DeviceBindCodeRequest.created_at > since_hour,
        ).count()
    )
    over = ip_count >= ip_per_hour or email_60s >= per_60s or email_hour >= per_hour
    db.session.add(
        DeviceBindCodeRequest(
            email_hash=None if over else digest,
            ip=ip,
            created_at=now,
        )
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return not over
