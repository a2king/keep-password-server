from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from flask import current_app, jsonify, request

from app.api import api_bp
from app.captcha import create_captcha, verify_captcha
from app.extensions import db
from app.httputil import client_ip
from app.mail import send_mail
from app.models import AuditLog, AuthThrottle, Device, LoginFailure, User, utcnow
from app.security import generate_binding_key, hash_password, issue_web_token, verify_password
from app.tokens import consume_email_code, send_reset_email, send_verify_email


def _audit(user: User | None, action: str, detail: str = "") -> None:
    db.session.add(
        AuditLog(user_id=user.id if user else None, action=action, detail=detail, ip=client_ip())
    )


def _normalize_email(raw: str) -> str:
    info = validate_email(raw, check_deliverability=False)
    return info.normalized.lower()


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _recent_failures(email: str) -> int:
    since = utcnow() - timedelta(seconds=current_app.config["LOGIN_FAIL_WINDOW_SECONDS"])
    return LoginFailure.query.filter(LoginFailure.email == email, LoginFailure.created_at >= since).count()


def _throttle_hit(bucket_key: str, action: str) -> bool:
    """True 表示已超限。限制：同 key 每分钟 1 次、每小时 5 次。"""
    now = utcnow()
    per_min = int(current_app.config.get("FORGOT_RATE_PER_MINUTE", 1))
    per_hour = int(current_app.config.get("FORGOT_RATE_PER_HOUR", 5))
    since_min = now - timedelta(minutes=1)
    since_hour = now - timedelta(hours=1)
    q = AuthThrottle.query.filter_by(bucket_key=bucket_key, action=action)
    if q.filter(AuthThrottle.created_at >= since_min).count() >= per_min:
        return True
    if q.filter(AuthThrottle.created_at >= since_hour).count() >= per_hour:
        return True
    return False


def _throttle_record(bucket_key: str, action: str) -> None:
    db.session.add(AuthThrottle(bucket_key=bucket_key, action=action, ip=client_ip()))
    db.session.commit()


def _binding_file(email: str, raw_key: str, fingerprint: str) -> tuple[str, str]:
    filename = f"keep-password-binding-{fingerprint}.kpbind"
    content = json.dumps(
        {
            "format": "keep-password-binding",
            "version": 1,
            "email": email,
            "key": raw_key,
            "fingerprint": fingerprint,
            "notice": "此文件用于绑定新设备。请妥善保管；在官网重新生成后旧文件立即失效。",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    return filename, content


def _revoke_user_devices(user: User) -> int:
    now = utcnow()
    rows = Device.query.filter_by(user_id=user.id, revoked_at=None).all()
    for d in rows:
        d.revoked_at = now
    return len(rows)


@api_bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "keep-password-server"})


@api_bp.get("/auth/captcha")
def captcha():
    challenge_id, question = create_captcha()
    return jsonify({"challengeId": challenge_id, "question": question})


@api_bp.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    password = data.get("password") or ""
    if len(password) < current_app.config["PASSWORD_MIN_LENGTH"]:
        return jsonify({"error": f"密码至少 {current_app.config['PASSWORD_MIN_LENGTH']} 位"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "该邮箱已注册"}), 409

    user = User(email=email, password_hash=hash_password(password), is_verified=False)
    db.session.add(user)
    _audit(user, "register")
    db.session.commit()
    send_verify_email(user)
    return jsonify({"ok": True, "message": "注册成功，请查收邮箱验证码"}), 201


@api_bp.post("/auth/verify-email")
def verify_email():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    # 统一错误，避免探测邮箱是否注册
    invalid = ({"error": "验证码不正确或已过期"}, 400)

    user = User.query.filter_by(email=email).first()
    if user is None:
        return jsonify(invalid[0]), invalid[1]
    if user.is_verified and user.binding_key_hash:
        return jsonify(invalid[0]), invalid[1]
    if not consume_email_code(user, "verify", data.get("code", "")):
        return jsonify(invalid[0]), invalid[1]

    raw_key, fingerprint, key_hash = generate_binding_key()
    user.is_verified = True
    user.binding_key_hash = key_hash
    user.binding_key_fingerprint = fingerprint
    user.binding_key_created_at = utcnow()
    _audit(user, "verify_email", fingerprint)
    db.session.commit()

    filename, content = _binding_file(user.email, raw_key, fingerprint)
    return jsonify(
        {
            "ok": True,
            "fingerprint": fingerprint,
            "filename": filename,
            "bindingKeyFile": content,
            "token": issue_web_token(user),
        }
    )


@api_bp.post("/auth/resend-verify")
def resend_verify():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400
    user = User.query.filter_by(email=email).first()
    # 无论是否存在都返回 ok，避免枚举
    if user and not user.is_verified:
        send_verify_email(user)
    return jsonify({"ok": True})


@api_bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    failures = _recent_failures(email)
    if failures >= current_app.config["LOGIN_FAIL_LIMIT"]:
        return jsonify({"error": "失败次数过多，请稍后再试", "captchaRequired": True}), 429

    need_captcha = failures >= current_app.config["CAPTCHA_AFTER_FAILURES"]
    if need_captcha and not verify_captcha(data.get("captchaId"), data.get("captchaAnswer")):
        return jsonify({"error": "请完成图形验证码", "captchaRequired": True}), 400

    user = User.query.filter_by(email=email).first()
    password = data.get("password") or ""
    if user is None or not verify_password(user.password_hash, password):
        db.session.add(LoginFailure(user_id=user.id if user else None, email=email, ip=client_ip()))
        db.session.commit()
        return jsonify(
            {
                "error": "邮箱或密码不正确",
                "captchaRequired": _recent_failures(email) >= current_app.config["CAPTCHA_AFTER_FAILURES"],
            }
        ), 401

    if user.is_disabled:
        return jsonify({"error": "账号已禁用"}), 403
    if not user.is_verified:
        return jsonify({"error": "请先完成邮箱验证", "needVerify": True}), 403

    user.last_login_at = utcnow()
    _audit(user, "login")
    db.session.commit()
    return jsonify(
        {
            "token": issue_web_token(user),
            "email": user.email,
            "isAdmin": user.is_admin,
            "bindingKeyFingerprint": user.binding_key_fingerprint,
        }
    )


_FORGOT_OK = {"ok": True, "message": "如果该邮箱已注册，将收到验证码"}


def _do_forgot(data: dict):
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    email_key = "email:" + _email_hash(email)
    ip_key = "ip:" + (client_ip() or "unknown")
    if _throttle_hit(email_key, "forgot") or _throttle_hit(ip_key, "forgot"):
        # 仍返回同一文案，避免枚举；不发信
        return jsonify(_FORGOT_OK)

    _throttle_record(email_key, "forgot")
    _throttle_record(ip_key, "forgot")

    user = User.query.filter_by(email=email).first()
    if user and user.is_verified and not user.is_disabled:
        send_reset_email(user)
        _audit(user, "forgot_password")
        db.session.commit()
    return jsonify(_FORGOT_OK)


def _do_reset(data: dict):
    try:
        email = _normalize_email(data.get("email", ""))
    except EmailNotValidError:
        return jsonify({"error": "邮箱格式不正确"}), 400

    password = data.get("newPassword") or data.get("password") or ""
    if len(password) < current_app.config["PASSWORD_MIN_LENGTH"]:
        return jsonify({"error": f"密码至少 {current_app.config['PASSWORD_MIN_LENGTH']} 位"}), 400

    invalid = ({"error": "验证码不正确或已过期"}, 400)
    user = User.query.filter_by(email=email).first()
    if user is None or not consume_email_code(user, "reset", data.get("code", "")):
        return jsonify(invalid[0]), invalid[1]

    user.password_hash = hash_password(password)
    user.wrapped_kpkey = None
    user.wrapped_kpkey_updated_at = None
    revoked = _revoke_user_devices(user)
    _audit(user, "reset_password", f"revoked_devices={revoked}")
    db.session.commit()
    send_mail(
        user.email,
        "Keep Password 密码已重置",
        "账号密码已重置（仅网站登录）。云端加密的保险库密钥包已清除，"
        "已绑定设备会话已作废。本地保险库主密码不受影响。"
        "请在已绑定设备上用新密码重新上传，或在新设备手动导入 .kpkey。",
    )
    return jsonify({"ok": True})


@api_bp.post("/auth/forgot")
def forgot():
    return _do_forgot(request.get_json(silent=True) or {})


@api_bp.post("/auth/reset")
def reset():
    return _do_reset(request.get_json(silent=True) or {})


# 兼容旧路径
@api_bp.post("/auth/forgot-password")
def forgot_password():
    return _do_forgot(request.get_json(silent=True) or {})


@api_bp.post("/auth/reset-password")
def reset_password():
    return _do_reset(request.get_json(silent=True) or {})
