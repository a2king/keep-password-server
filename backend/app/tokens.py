from __future__ import annotations

import secrets
from datetime import timedelta

from flask import current_app

from app.extensions import db
from app.mail import send_mail
from app.models import EmailToken, User, utcnow
from app.security import hash_token


def _make_code(length: int = 8) -> str:
    # 去掉易混淆字符
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def issue_email_code(user: User, purpose: str, ttl_minutes: int = 30) -> str:
    # 使同用途旧码失效，避免多码并行被刷
    now = utcnow()
    EmailToken.query.filter_by(user_id=user.id, purpose=purpose, used_at=None).update(
        {"used_at": now},
        synchronize_session=False,
    )
    code = _make_code(8)
    token = EmailToken(
        user_id=user.id,
        purpose=purpose,
        code_hash=hash_token(code),
        expires_at=now + timedelta(minutes=ttl_minutes),
        attempts=0,
    )
    db.session.add(token)
    db.session.commit()
    return code


def consume_email_code(user: User, purpose: str, code: str) -> bool:
    """校验验证码；失败会计次，超过上限则作废。"""
    now = utcnow()
    max_attempts = int(current_app.config.get("EMAIL_CODE_MAX_ATTEMPTS", 5))
    row = (
        EmailToken.query.filter_by(user_id=user.id, purpose=purpose, used_at=None)
        .order_by(EmailToken.id.desc())
        .first()
    )
    if row is None:
        return False

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=now.tzinfo)
    if expires < now:
        row.used_at = now
        db.session.commit()
        return False

    if row.attempts >= max_attempts:
        row.used_at = now
        db.session.commit()
        return False

    target = hash_token((code or "").strip().upper())
    if row.code_hash == target:
        row.used_at = now
        db.session.commit()
        return True

    row.attempts += 1
    if row.attempts >= max_attempts:
        row.used_at = now
    db.session.commit()
    return False


def send_verify_email(user: User) -> None:
    code = issue_email_code(user, "verify", ttl_minutes=60)
    send_mail(
        user.email,
        "验证你的 Keep Password 邮箱",
        f"你的验证码是：{code}\n\n一小时内有效。如果不是你本人操作，请忽略本邮件。",
    )


def send_reset_email(user: User) -> None:
    code = issue_email_code(user, "reset", ttl_minutes=30)
    send_mail(
        user.email,
        "重置 Keep Password 账号密码",
        f"你的重置验证码是：{code}\n\n三十分钟内有效。如果不是你本人操作，请忽略本邮件。",
    )


def send_device_bind_email(user: User) -> None:
    code = issue_email_code(user, "device_bind", ttl_minutes=15)
    send_mail(
        user.email,
        "Keep Password 设备绑定验证码",
        f"你的设备绑定验证码是：{code}\n\n十五分钟内有效。",
    )


def send_sensitive_email(user: User, purpose: str, title: str) -> None:
    code = issue_email_code(user, purpose, ttl_minutes=15)
    send_mail(user.email, title, f"验证码：{code}\n\n十五分钟内有效。如果不是你本人操作，请尽快检查账号安全。")
