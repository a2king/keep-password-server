from __future__ import annotations

import random
import secrets
from datetime import timedelta

from app.extensions import db
from app.models import CaptchaChallenge, utcnow
from app.security import hash_token


def create_captcha() -> tuple[str, str]:
    """返回 (challengeId, 题目文本)。不依赖图像库，便于在精简环境运行。"""
    a = random.randint(2, 19)
    b = random.randint(2, 19)
    answer = str(a + b)
    challenge_id = secrets.token_urlsafe(16)
    db.session.add(
        CaptchaChallenge(
            id=challenge_id,
            answer_hash=hash_token(answer),
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.session.commit()
    return challenge_id, f"{a} + {b} = ?"


def verify_captcha(challenge_id: str | None, answer: str | None) -> bool:
    if not challenge_id or not answer:
        return False
    row = db.session.get(CaptchaChallenge, challenge_id)
    if row is None:
        return False
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=utcnow().tzinfo)
    ok = expires >= utcnow() and row.answer_hash == hash_token(answer.strip())
    db.session.delete(row)
    db.session.commit()
    return ok
