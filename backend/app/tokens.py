from __future__ import annotations

import secrets
from datetime import timedelta

from app.extensions import db
from app.mail import send_mail
from app.models import EmailToken, User, utcnow
from app.security import hash_token


def issue_email_code(user: User, purpose: str, ttl_minutes: int = 30) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = EmailToken(
        user_id=user.id,
        purpose=purpose,
        code_hash=hash_token(code),
        expires_at=utcnow() + timedelta(minutes=ttl_minutes),
    )
    db.session.add(token)
    db.session.commit()
    return code


def consume_email_code(user: User, purpose: str, code: str) -> bool:
    now = utcnow()
    rows = (
        EmailToken.query.filter_by(user_id=user.id, purpose=purpose, used_at=None)
        .order_by(EmailToken.id.desc())
        .limit(5)
        .all()
    )
    target = hash_token(code.strip())
    for row in rows:
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=now.tzinfo)
        if expires < now:
            continue
        if row.code_hash == target:
            row.used_at = now
            db.session.commit()
            return True
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
